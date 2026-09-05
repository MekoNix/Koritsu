"""
deps — единственная дверь к соседям: кто пришёл (`accounts`) и чей это проект
(`projects`).

Смысл файла в слове «единственная». Аккаунты заводит `accounts`, проекты и роли
— `projects`, а материалы обязаны работать с обоими и при этом собираться, даже
когда соседнего пакета ещё нет. Дверь одна, поэтому:

* переход с заглушки на настоящие имена стоит одной правки, а не пятнадцати по
  маршрутам;
* подмена в тесте работает по **объекту функции** — второй импорт того же имени
  из другого места дал бы второй ключ в `dependency_overrides`, то есть
  подменённую зависимость в одном маршруте и настоящую в соседнем.

Вошедшего берём из `..workspaces.deps` (`current_user`, `CurrentUser`), а не
из `..accounts` напрямую: там уже стоит эта самая одна дверь, и второй такой же
объект-заглушка означал бы, что тест подменил вход для проектов и не подменил
для материалов.

**Разрез между «спросить у проектов» и «решить самим» проходит по строке
`проект_и_роль`.** Ниже неё — знание пакета проектов: где каталог проекта, в
каком пространстве он лежит, кто его завёл. Выше — политика отказов, и она
наша, потому что её проверяют наши тесты:

* **404 `not_found`** — нет такого проекта или спрашивающий не участник. Один и
  тот же ответ на оба случая: 403 на чужой проект сообщал бы, что проект с таким
  идентификатором существует, то есть отвечал бы на вопрос, задавать который
  спрашивающему не позволено («клиент видит только идентификаторы»).
* **403 `forbidden`** — участник есть, роли мало (`viewer` шлёт `POST`). Прятать
  тут нечего: он и так видит проект, а 404 выглядел бы как пропавшая работа.

Ровно та же пара кодов и тот же довод — в докстроке `..workspaces`; это не
совпадение, а одно правило службы, записанное там, где его исполняют.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Callable

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from ..db import SessionDep
from ..errors import ApiError, NOT_FOUND
from ..ids import check_id
from ..settings import Settings
from ..workspaces.deps import CurrentUser, current_user      # noqa: F401
from ..workspaces.service import EDITOR, OWNER, ROLES, VIEWER, role_of

FORBIDDEN = "forbidden"
# Пакет проектов ещё не собран. Отдельный код, а не пятисотка: это не поломка
# службы, а рабочее состояние, и различать их обязан тот, кто читает журнал.
NOT_READY = "not_ready"


@dataclass(frozen=True)
class Проект:
    """Что службе нужно знать о проекте, чтобы работать с его материалами.

    `dir` — каталог проекта на томе. Наружу он не уезжает никогда: наружу
    уходят только идентификаторы, и живёт он только внутри обработчика.

    `owner_id` — **владелец проекта, а не пришедший**: квота считается на того,
    кто проект завёл («чужие проекты в общем workspace едят место того, кто
    их создал»).
    """

    id: str
    dir: str
    owner_id: str
    role: str


# ── дверь к пакету проектов ──────────────────────────────────────────────────

def _проекты():
    """Пакет проектов или отказ `503`, пока его нет."""
    try:
        from .. import projects
    except Exception:                                        # noqa: BLE001
        projects = None
    if projects is None or not hasattr(projects, "project_dir"):
        raise ApiError(NOT_READY, "Projects are not available yet", 503)
    return projects


def проект_и_роль(s: Session, settings: Settings, user_id: str,
                  project_id: str) -> Проект | None:
    """Каталог проекта, его владелец и роль пришедшего. `None` — «не видит».

    Единственное место, знающее имена пакета проектов:
    `projects.project_dir(s, settings, project_id)` и строка `projects.Project`
    с полями `workspace_id` и
    `owner_id`. Всё остальное — роль, коды отказа, квота — считается выше и
    нашими правилами.

    `None`, а не исключение, потому что решение «что ответить на невидимый
    проект» принимается один раз в `найти_проект`, а не дважды — здесь и там.
    """
    projects = _проекты()
    строка = s.get(projects.Project, project_id)
    if строка is None or getattr(строка, "deleted_at", None) is not None:
        return None
    роль = role_of(s, user_id, строка.workspace_id)
    if роль is None:
        return None
    # Владелец — из строки проекта, не из пространства и не из пришедшего:
    # квота считается на того, кто проект завёл, и в общем пространстве
    # это разные люди.
    return Проект(id=project_id, role=роль, owner_id=str(строка.owner_id),
                  dir=str(projects.project_dir(s, settings, project_id)))


def bytes_used(s: Session, settings: Settings, owner_id: str) -> int:
    """Сколько байт уже занял этот владелец. Считает `projects`, по каталогам тома.

    Обёртка, а не прямой вызов из обработчика, по той же причине, что и всё в
    этом файле: имя соседа названо один раз.
    """
    return int(_проекты().bytes_used(s, settings, owner_id))


# ── политика отказов: наша ───────────────────────────────────────────────────

def найти_проект(s: Session, settings: Settings, user_id: str, project_id: str,
                 min_role: str) -> Проект:
    """Проект, если этот человек имеет в нём хотя бы такую роль.

    `404` — нет такого или не участник (одинаково, см. докстроку модуля);
    `403` — участник есть, роли мало. Роль неизвестного вида (соседи завели
    четвёртую и не сказали) — тоже `403`: пускать по непонятой роли значило бы
    трактовать незнание как разрешение.
    """
    проект = проект_и_роль(s, settings, user_id, project_id)
    if проект is None:
        raise ApiError(NOT_FOUND, "Project not found", 404,
                       where="path.project_id")
    if проект.role not in ROLES or ROLES.index(проект.role) < ROLES.index(min_role):
        raise ApiError(FORBIDDEN, f"Role '{min_role}' or higher is required",
                       403, where="path.project_id")
    return проект


def _доступ(min_role: str) -> Callable[..., Проект]:
    """Зависимость FastAPI «проект под такой ролью».

    Фабрика, но результаты её — две **постоянные** функции ниже, а не новый
    объект на каждый маршрут: `dependency_overrides` ключуется по объекту, и
    зависимость, созданная в декораторе каждого маршрута, не подменялась бы
    вовсе.
    """

    def зависимость(project_id: str, request: Request, s: SessionDep,
                    user: CurrentUser) -> Проект:
        # Форма идентификатора проверяется до похода в базу (`ids.py`): иначе
        # `../../etc` уехал бы в `s.get` и вернулся бы пятисоткой вместо отказа.
        check_id(project_id, where="path.project_id")
        return найти_проект(s, request.app.state.settings, user.id, project_id,
                            min_role)

    зависимость.__name__ = f"проект_{min_role}"
    return зависимость


читатель = _доступ(VIEWER)
редактор = _доступ(EDITOR)

ЧитательПроекта = Annotated[Проект, Depends(читатель)]
РедакторПроекта = Annotated[Проект, Depends(редактор)]


__all__ = ["Проект", "проект_и_роль", "найти_проект", "bytes_used",
           "читатель", "редактор", "ЧитательПроекта", "РедакторПроекта",
           "current_user", "CurrentUser", "FORBIDDEN", "NOT_READY",
           "VIEWER", "EDITOR", "OWNER", "ROLES"]
