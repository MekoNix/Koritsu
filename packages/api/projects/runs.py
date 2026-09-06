"""
runs — журнал запусков модулей в работе: `/api/projects/{id}/runs`.

    POST   /api/projects/{id}/runs           201  записать запуск (editor)
    GET    /api/projects/{id}/runs           200  журнал работы (viewer)
    PATCH  /api/projects/{id}/runs/{run_id}  200  переименовать запись (editor)
    DELETE /api/projects/{id}/runs/{run_id}  204  убрать запись (editor)

**Зачем журнал.** Работа переживает много запусков разных модулей — отчёт,
задание, две блок-схемы, — и до него карточка работы отвечала только на вопрос
«куда можно пойти» (плитки «открыть в модуле»). На работе с двумя схемами такой
ответ бесполезен: человек ищет не модуль, а ту схему, которую он вчера сделал.
Журнал отвечает именно на это: какой модуль, когда, как называется.

**Одна таблица на все модули, а не своя у каждого.** Список запусков читается
целиком и сортируется целиком; четыре списка, склеиваемых на клиенте, дали бы
четыре разных порядка и четыре разных «когда». Модуль здесь — поле, и оно же
отбор (`?module=flowcharts`).

**Номер даёт служба, имя — клиент.** `n` — который это запуск данного модуля в
данной работе; считается он в базе, потому что два браузера, открывшие проект
разом, придумали бы одно и то же «Схема 2». А вот текст имени служба за клиента
не сочиняет: имя по умолчанию — русское слово («Схема 2 — Курсовая»), а наружу
служба говорит по-английски, и вторая таблица переводов в ней разошлась бы с
той, что в интерфейсе. Поэтому пустое `name` — законное значение, и рисует его
интерфейс сам, из `module` и `n`. По той же причине пустое имя в правке — не
отказ, а возврат к имени по умолчанию: стереть своё название и снова увидеть
«Схема 2 — Курсовая» человек должен уметь тем же полем, которым он его давал.

**Удаление записи не трогает артефакт.** Схема удаляется из работы записью
журнала: XML на томе адресуется содержимым и может стоять значением тега, а
снести его вслед за строкой значило бы выбить картинку из готового документа.
Место освобождает уборка работы целиком.

Коды отказа этого модуля:

    unauthorized    401  вошедшего нет
    invalid_id      400  идентификатор не uuid4, `artifact_id` не той формы
    unknown_module  400  модуля с таким именем служба не отдаёт
    not_found       404  нет работы, спрашивающий не участник, нет записи
    forbidden       403  участник есть, роли мало
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from ..db import SessionDep
from ..errors import ApiError, INVALID_ID, NOT_FOUND
from ..ids import check_id
from ..materials.deps import CurrentUser, РедакторПроекта, ЧитательПроекта
from ..workspaces.service import iso
from .models import ARTIFACT_LEN, MODULE_LEN, NAME_MAX, ProjectRun

router = APIRouter(prefix="/projects/{project_id}/runs", tags=["projects"])

UNKNOWN_MODULE = "unknown_module"

# Как сортируется журнал. Перечислением, а не свободной строкой: список значений
# уезжает в OpenAPI и становится типом в клиенте сайта, а неизвестное значение
# отвергается разбором тела до обработчика (`422 validation_failed`) — то есть
# ошибка в имени сортировки не превращается молча в порядок по умолчанию.
Сортировка = Literal["new", "old", "name", "module"]


class ProjectRunIn(BaseModel):
    """Запись о запуске. Имя по-английски: оно уезжает типом в клиент сайта."""

    module: str = Field(
        min_length=1, max_length=MODULE_LEN,
        description="Module id from GET /api/modules: reports, kadai, …")
    name: str = Field(
        default="", max_length=NAME_MAX,
        description=("What to call this run. Empty is fine: the interface "
                     "draws a default name from the module and n."))
    artifact_id: str | None = Field(
        default=None,
        description="Artifact this run produced, when it produced one")


class ProjectRunPatchIn(BaseModel):
    """Правка записи. Поле одно — имя: всё остальное в записи не редактируется.

    Модуль, номер и артефакт — это то, что случилось, а случившееся не правят:
    переписать модуль у записи значило бы сказать, что схему построил отчёт.
    Имя — единственное, что в записи придумал человек, и единственное, что он
    может передумать.

    Обязательное поле, а не необязательное: у правки с одним полем «поля нет»
    означало бы «ничего не делать», то есть запрос, на который незачем ходить.
    """

    name: str = Field(
        max_length=NAME_MAX,
        description=("New name for this run. Empty resets it: the interface "
                     "draws the default name from the module and n again."))


class ProjectRunOut(BaseModel):
    """Запись журнала наружу. Путей на томе в ней нет и быть не может."""

    id: str
    project_id: str
    module: str
    name: str = Field(description="Empty means the interface names it itself")
    n: int = Field(description="Which run of this module in this project, from 1")
    artifact_id: str | None = None
    user_id: str | None = Field(default=None, description="Who started it")
    created_at: str | None = None


def карточка(запись: ProjectRun) -> dict:
    return {"id": запись.id, "project_id": запись.project_id,
            "module": запись.module, "name": запись.name, "n": int(запись.n),
            "artifact_id": запись.artifact_id, "user_id": запись.user_id,
            "created_at": iso(запись.created_at)}


def проверить_модуль(module: str, *, where: str = "body.module") -> str:
    """Модуль из реестра — или `400 unknown_module`.

    Спрашивается тот же реестр, из которого строится `GET /api/modules`
    (`api.modules`), а не свой список слов: второй разошёлся бы с первым на
    первом же заведённом модуле, и журнал заполнился бы именами, которых в
    службе нет. Неготовые модули не годятся по той же причине, по какой их не
    видно в интерфейсе: записи о запуске того, чего человеку не показывают, не
    бывает.
    """
    # Импорт внутри функции: реестр модулей тянет их подпакеты, а те —
    # зависимости доступа, которые читают этот пакет обратно (тот же довод, что
    # у `routes.collect`).
    from .. import modules                                    # noqa: PLC0415

    имя = (module or "").strip()
    if имя not in {info.id for info in modules.all_modules() if info.ready}:
        raise ApiError(UNKNOWN_MODULE, "No such module", 400, where=where)
    return имя


def проверить_артефакт(artifact_id: str | None) -> str | None:
    """Форма идентификатора артефакта — или `400 invalid_id`.

    Проверяется **форма, а не наличие**: журнал — это заметка о том, что
    случилось, а не ссылка, которую служба обязана держать живой. Артефакт
    адресуется содержимым, и спрашивать том на каждой записи значило бы платить
    обходом каталога за проверку, которая всё равно устареет к первому чтению.
    Форма же нужна: из идентификатора собирается путь скачивания, и мусор в нём
    обязан умереть на входе.
    """
    if artifact_id is None or not artifact_id.strip():
        return None
    # Регулярка берётся у того, кто артефакты и отдаёт, — второй такой же здесь
    # разошёлся бы с ней при первом же удлинении среза хеша.
    from ..modules.artifacts import ARTIFACT_ID_RE            # noqa: PLC0415

    значение = artifact_id.strip()
    if not ARTIFACT_ID_RE.match(значение) or len(значение) > ARTIFACT_LEN:
        raise ApiError(INVALID_ID, "Artifact id is not of the right shape", 400,
                       where="body.artifact_id")
    return значение


def завести(s, проект, user, *, module: str, name: str = "",
            artifact_id: str | None = None) -> ProjectRun:
    """Новая запись журнала с посчитанным номером. → строка, ещё не в ответе.

    Отдельно от обработчика, потому что записи журнала заводит не только
    человек кнопкой: модуль схем пишет её сам, когда схема построилась
    (`api/modules/saved.py`), — схема сохраняется в работу без кнопки
    «сохранить». Второй такой же счётчик номеров рядом означал бы, что
    «Схема 2» однажды заведётся дважды.

    Номер считается запросом в базе, а не полем в проекте: два браузера,
    открывшие работу разом, придумали бы одно и то же число.
    """
    номер = 1 + int(s.scalar(
        select(func.count()).select_from(ProjectRun)
        .where(ProjectRun.project_id == проект.id,
               ProjectRun.module == module)) or 0)
    запись = ProjectRun(project_id=проект.id, user_id=user.id, module=module,
                        name=name.strip(), n=номер, artifact_id=artifact_id)
    s.add(запись)
    s.flush()
    return запись


@router.post("", status_code=201, operation_id="create_project_run",
             response_model=ProjectRunOut,
             summary="Write down a module run of this project",
             description=(
                 "Adds one entry to the run journal of a project: which module "
                 "was started, what it is called and what it produced. The "
                 "answer carries `n`, the sequence number of this run of this "
                 "module in this project, which the interface uses to name a "
                 "run that was left unnamed. Editor role. 400 invalid_id, "
                 "400 unknown_module, 403 forbidden, 404 not_found."))
def записать(тело: ProjectRunIn, проект: РедакторПроекта, s: SessionDep,
             user: CurrentUser) -> dict:
    """Записать запуск. Номер считает служба, имя приходит от клиента."""
    модуль = проверить_модуль(тело.module)
    артефакт = проверить_артефакт(тело.artifact_id)
    return карточка(завести(s, проект, user, module=модуль, name=тело.name,
                            artifact_id=артефакт))


@router.get("", operation_id="list_project_runs",
            response_model=list[ProjectRunOut],
            summary="Run journal of a project",
            description=(
                "Everything that has been started in this project: which "
                "module, when, under what name, and what it produced. `module` "
                "narrows the list down to one module; `sort` orders it: newest "
                "first by default, then oldest, by name or by module. Viewer "
                "role. 400 invalid_id, 400 unknown_module, 404 not_found."))
def журнал(проект: ЧитательПроекта, s: SessionDep, module: str = "",
           sort: Сортировка = "new") -> list[dict]:
    """Журнал работы. Пустой список — законное состояние новой работы."""
    запрос = select(ProjectRun).where(ProjectRun.project_id == проект.id)
    if module.strip():
        запрос = запрос.where(
            ProjectRun.module == проверить_модуль(module, where="query.module"))
    # Вторым ключом всюду стоит время создания, и не для красоты: имена
    # запусков повторяются («Схема» у двух работ подряд), а порядок в списке,
    # меняющийся между двумя запросами одной страницы, читается как пропавшая
    # строка.
    порядок = {
        "new": (ProjectRun.created_at.desc(),),
        "old": (ProjectRun.created_at.asc(),),
        "name": (ProjectRun.name.asc(), ProjectRun.created_at.desc()),
        "module": (ProjectRun.module.asc(), ProjectRun.created_at.desc()),
    }[sort]
    return [карточка(з) for з in s.scalars(запрос.order_by(*порядок))]


def запись_работы(s, проект, run_id: str) -> ProjectRun:
    """Запись журнала этой работы — или `404`.

    Чужая и несуществующая отвечают одинаково: разные ответы рассказывали бы,
    что запись с таким идентификатором есть у кого-то другого, — тот же довод,
    что у чужого проекта.
    """
    запись = s.get(ProjectRun, check_id(run_id, where="path.run_id"))
    if запись is None or запись.project_id != проект.id:
        raise ApiError(NOT_FOUND, "Run not found", 404, where="path.run_id")
    return запись


@router.patch("/{run_id}", operation_id="rename_project_run",
              response_model=ProjectRunOut,
              summary="Rename one entry of the run journal",
              description=(
                  "Renames a run: this is how a diagram, a report or a "
                  "solution is renamed. An empty name is not a refusal but a "
                  "reset: the interface goes back to drawing the default "
                  "name from the module and n. Editor role. 400 invalid_id, "
                  "403 forbidden, 404 not_found."))
def переименовать(run_id: str, тело: ProjectRunPatchIn, проект: РедакторПроекта,
                  s: SessionDep) -> dict:
    """Имя записи журнала. Пустое — снова имя по умолчанию."""
    запись = запись_работы(s, проект, run_id)
    запись.name = тело.name.strip()
    s.flush()
    return карточка(запись)


@router.delete("/{run_id}", status_code=204,
               operation_id="delete_project_run",
               summary="Remove one entry from the run journal",
               description=(
                   "Removes a run from the journal of the project: this is how "
                   "a diagram is deleted from a work. What the run produced "
                   "stays on the volume: an artifact is addressed by its "
                   "content and may be the value of a tag, so deleting it here "
                   "would knock a picture out of a finished document. Editor "
                   "role. 400 invalid_id, 403 forbidden, 404 not_found."),
               response_class=Response)
def убрать(run_id: str, проект: РедакторПроекта, s: SessionDep) -> Response:
    """Убрать запись журнала. Чужая и несуществующая отвечают одинаково."""
    s.delete(запись_работы(s, проект, run_id))
    s.flush()
    return Response(status_code=204)


__all__ = ["router", "ProjectRunIn", "ProjectRunPatchIn", "ProjectRunOut",
           "карточка", "завести", "запись_работы", "проверить_модуль",
           "проверить_артефакт", "UNKNOWN_MODULE"]
