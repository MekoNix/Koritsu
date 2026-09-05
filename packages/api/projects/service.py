"""
service — каталог проекта на томе, размер, корзина и её уборка.

Единственное место пакета проектов, которое знает про пути. Правило то же, что у
`orchestrator.project`, и по той же причине: путь, собранный в маршруте, —
это путь, который при переезде тома чинится по всем маршрутам сразу.

Раскладка:

    {data_dir}/users/<owner_uuid>/projects/<project_uuid>/

Оба куска — канонические uuid4 из базы, и оба проходят `check_id` **до** того,
как попадут в `os.path.join`. Это и есть заслон от обхода каталогов: `..` не
проходит форму uuid, а значит `../../etc` неоткуда взяться — клиент путей не
называет вовсе (`ids.py`).

**Наружу путь не уезжает никогда.** Ни в карточке проекта, ни в ошибке: карточка
отдаёт `bytes_used`, а не `path`, а `OrchestratorError` с путём внутри
превращается в `bad_template` без подробностей. Проверяется это тестом, который
ищет `/data` и абсолютные пути в теле любого ответа.

**Корзина** — два поля и одна функция. `deleted_at` ставится при удалении,
`purge_after = deleted_at + trash_days` («физическая уборка через 10 дней»).
Каталог живёт до `purge_after` и до тех пор **считается в квоте**: место он
занимает, и списывать его раньше времени значило бы обещать человеку байты,
которых у него нет.

`purge_expired` живёт вне запроса, поэтому берёт сессию аргументом: её зовут
консольная команда `purge` и воркер очереди.
"""
from __future__ import annotations

import datetime
import os
import shutil

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import now
from ..errors import ApiError
from ..ids import check_id
from ..settings import Settings
from ..workspaces.models import Workspace
from ..workspaces.service import NOT_IN_TRASH, IN_TRASH
from .models import Project

NOT_FOUND = "not_found"

# Имена каталогов раскладки тома. Строками в одном месте, а не по месту: «users»
# в двух файлах — это два разных «users» после первого же переименования.
USERS_DIR = "users"
PROJECTS_DIR = "projects"
# Шаблоны отчётов человека лежат рядом с его проектами, а не внутри одного из
# них: шаблон принадлежит человеку и переживает работу, по которой его завели
# (`api.templates`). Имя каталога — здесь, потому что здесь живёт вся раскладка
# тома: второе такое знание в пакете шаблонов разошлось бы с этим при первом же
# переименовании, и квота перестала бы находить файлы.
TEMPLATES_DIR = "templates"


# ── пути на томе ─────────────────────────────────────────────────────────────

def user_dir(settings: Settings, owner_id: str) -> str:
    """Каталог человека на томе. Идентификатор проверяется до склейки пути."""
    return os.path.join(settings.data_dir, USERS_DIR,
                        check_id(owner_id, where="owner_id"))


def templates_dir(settings: Settings, owner_id: str) -> str:
    """Каталог шаблонов отчётов человека. Идентификатор проверяется до склейки.

    Живёт здесь, а не в `api.templates`, по правилу этого файла: про пути на
    томе знает одно место. Считается он в ту же квоту, что и проекты, — см.
    `bytes_used`.
    """
    return os.path.join(user_dir(settings, owner_id), TEMPLATES_DIR)


def dir_for(settings: Settings, owner_id: str, project_id: str) -> str:
    """Каталог проекта по паре идентификаторов, без похода в базу."""
    return os.path.join(user_dir(settings, owner_id), PROJECTS_DIR,
                        check_id(project_id, where="project_id"))


def project_dir(s: Session, settings: Settings, project_id: str) -> str:
    """Каталог проекта по его идентификатору. Форма для соседей (материалы).

    Ходит в базу, потому что владельца проекта знает только она, а каталог лежит
    у владельца — не у того, кто сейчас спрашивает. Доступ здесь **не**
    проверяется: это дело `workspaces.require_role`, и складывать две проверки в
    одну функцию значило бы, что однажды кто-то позовёт её ради пути и получит
    заодно чужой отказ вместо своего.
    """
    p = get_row(s, project_id)
    return dir_for(settings, p.owner_id, p.id)


def get_row(s: Session, project_id: str, *,
            where: str = "path.project_id") -> Project:
    """Строка проекта или 404. Форму идентификатора проверяем до базы."""
    p = s.get(Project, check_id(project_id, where=where))
    if p is None:
        raise ApiError(NOT_FOUND, "Project not found", 404, where=where)
    return p


# ── размер и квота ───────────────────────────────────────────────────────────

def dir_size(path: str) -> int:
    """Сколько байт занимает каталог. Ноль, если каталога нет.

    Считаются обычные файлы; символические ссылки пропускаются, иначе ссылка на
    чужой файл засчиталась бы человеку в квоту (а ссылка на каталог — ещё и
    зациклила бы обход). Файл, исчезнувший между `walk` и `stat`, пропускается
    молча: это уборка, работавшая параллельно, а не беда.
    """
    итог = 0
    for корень, каталоги, файлы in os.walk(path, followlinks=False):
        for имя in файлы:
            полный = os.path.join(корень, имя)
            if os.path.islink(полный):
                continue
            try:
                итог += os.path.getsize(полный)
            except OSError:
                continue
    return итог


def bytes_used(s: Session, settings: Settings, owner_id: str) -> int:
    """Сколько байт занимают проекты этого владельца. Экспорт для материалов.

    Квота — на владельца, поэтому суммируем по `owner_id`, а не по
    пространству: чужой проект в общем пространстве ест место того, кто его
    создал.

    Проекты в корзине считаются: их каталоги ещё на диске. Не считать их значило
    бы разрешить обойти квоту в 250 МБ, удаляя и создавая проекты по кругу.

    Материалы, лежащие внутри каталога проекта, уже входят сюда — `Project`
    держит `materials/` у себя. Если у материалов появятся файлы вне проектов,
    их пакет прибавляет своё к этому числу, а не заводит второй обход тома.

    Шаблоны отчётов (`api.templates`) — как раз такие файлы вне проектов, и они
    здесь считаются: DOCX человека занимает место на томе ровно так же, как его
    материалы, и не считать их значило бы обещать байты, которых нет. Отдельной
    квоты у них нет намеренно — второй порог развёлся бы с первым.
    """
    итог = dir_size(templates_dir(settings, owner_id))
    for p in s.scalars(select(Project).where(Project.owner_id == owner_id)):
        итог += dir_size(dir_for(settings, p.owner_id, p.id))
    return итог


# ── корзина ──────────────────────────────────────────────────────────────────

def trash(s: Session, p: Project, settings: Settings) -> datetime.datetime:
    """Положить проект в корзину. Каталог остаётся на месте до `purge_after`."""
    if p.deleted_at is not None:
        raise ApiError(IN_TRASH, "Project is already in the trash", 409,
                       where="path.project_id")
    момент = now()
    p.deleted_at = момент
    p.purge_after = момент + datetime.timedelta(days=settings.trash_days)
    s.flush()
    return момент


def restore(s: Session, p: Project) -> None:
    """Достать проект из корзины.

    В удалённое пространство не возвращаем: проект, восстановленный в корзину,
    не виден ни в одном списке и пропадёт при уборке пространства — то есть
    «Восстановить» соврало бы. Сначала достают пространство.
    """
    if p.deleted_at is None:
        raise ApiError(NOT_IN_TRASH, "Project is not in the trash", 409,
                       where="path.project_id")
    ws = s.get(Workspace, p.workspace_id)
    if ws is None or ws.deleted_at is not None:
        raise ApiError(IN_TRASH, "Restore the workspace first", 409,
                       where="path.project_id")
    p.deleted_at, p.purge_after = None, None
    s.flush()


def purge_expired(s: Session, settings: Settings) -> list[str]:
    """Убрать из корзины всё, чей срок вышел. → идентификаторы убранных проектов.

    Физически: каталог проекта сносится с тома, строка исчезает из базы. Порядок
    именно такой — сначала диск, потом база. Обратный оставил бы каталог, про
    который никто больше не знает: строки нет, значит нет и владельца, значит
    место занято навсегда и ничем не находится.

    Убираются и проекты пространств, чей срок вышел, — их `purge_after` тот же,
    потому что удаление пространства ставит его проектам ту же метку; условие по
    пространству оставлено на случай, если проект попал туда иначе.

    Сессию и настройки берёт аргументами: живёт вне запроса — зовут её
    консольная команда `purge` и воркер очереди.
    """
    момент = now()
    истёкшие_пространства = select(Workspace.id).where(
        Workspace.purge_after.is_not(None), Workspace.purge_after <= момент)
    просроченные = select(Project).where(
        (Project.purge_after.is_not(None) & (Project.purge_after <= момент))
        | Project.workspace_id.in_(истёкшие_пространства))
    убрано: list[str] = []
    for p in list(s.scalars(просроченные)):
        shutil.rmtree(dir_for(settings, p.owner_id, p.id), ignore_errors=True)
        s.delete(p)
        убрано.append(p.id)

    # Пространства убираем после проектов: строка пространства держит их внешним
    # ключом, и удалить её первой значило бы дать SQLite снести проекты каскадом
    # — вместе со знанием о том, какие каталоги надо было снести с диска.
    for ws in list(s.scalars(select(Workspace).where(
            Workspace.purge_after.is_not(None), Workspace.purge_after <= момент))):
        s.delete(ws)
    s.flush()
    return убрано


__all__ = ["user_dir", "dir_for", "templates_dir", "project_dir", "get_row",
           "dir_size", "bytes_used", "trash", "restore", "purge_expired",
           "USERS_DIR", "PROJECTS_DIR", "TEMPLATES_DIR", "NOT_FOUND"]
