"""
reports — отчёты работы: `/api/projects/{id}/reports`.

    GET    /api/projects/{id}/reports            200  отчёты работы (viewer)
    POST   /api/projects/{id}/reports            201  завести отчёт  (editor)
    DELETE /api/projects/{id}/reports/{run_id}   204  снести отчёт   (editor)

**Отчётов в работе много.** У каждого свой бланк, свои значения тегов с
историей версий и свои сборки: титульный лист по одному ГОСТу, приложение по
другому, вторая глава третьим бланком. До этого у работы был один набор
значений, и второй отчёт в ней означал бы затирание первого.

**Отчёт — это запись журнала запусков (`module: "reports"`) и каталог документа
рядом с ней.** Второй таблицы не заводится: имя, номер, время и «кто завёл» уже
описаны журналом (`runs.py`), а всё, что принадлежит самому документу, лежит на
томе (`orchestrator.Project(path, report=<run_id>)` — каталог `reports/<id>/`).
Строка без каталога — законное состояние: так выглядят отчёты, заведённые до
появления второго документа, и читают их из корня работы, чтобы не потерять
написанное.

**Корневой документ принадлежит самой старой записи об отчёте.** Работа
существует до всяких отчётов: её заводят с бланком, в ней пишут значения и
собирают PDF. Поэтому первый отчёт работы забирает этот документ, а не заводит
пустой каталог рядом, — иначе написанное разом пропало бы с экрана, оставшись
целым на томе. Названный при этом бланк назначается корню тем же действием, что
и «собирать по этому бланку», то есть с сохранением значений тегов. Все
следующие отчёты получают свой каталог.

**Список чинит старые записи** по тому же правилу. Каталог документа заводится и
здесь, при чтении списка: журнал мог получить вторую запись об отчёте раньше,
чем появились каталоги, и тогда два отчёта смотрели бы в один и тот же набор
значений. Порядка вызовов правило не требует: корневой документ принадлежит
самой старой записи, каждая следующая получает свой каталог. Первый отчёт при
этом никуда не переезжает — его значения остаются там, где были записаны.

**Удаление сносит документ, а не бланк.** Уходят значения, их версии и каталог
сборки этого отчёта; приложенный к работе бланк остаётся на полке, а артефакты —
на томе: артефакт адресуется содержимым и может стоять значением тега в соседнем
отчёте (то же правило, что у `DELETE …/runs/{run_id}`).

Коды отказа этого модуля:

    unauthorized    401  вошедшего нет
    invalid_id      400  идентификатор не uuid4
    bad_template    400  бланк не читается
    not_found       404  нет работы, нет отчёта, спрашивающий не участник
    forbidden       403  участник есть, роли мало
    in_trash        409  работа в корзине
"""
from __future__ import annotations

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select

import orchestrator

from ..db import SessionDep
from ..errors import ApiError, NOT_FOUND
from ..ids import check_id
from ..log import беды
from ..settings import Settings
from ..workspaces.deps import CurrentUser
from ..workspaces.service import EDITOR, VIEWER, iso
from .models import NAME_MAX, ProjectRun
from .routes import BAD_TEMPLATE, доступный, настройки, открыть
from .runs import завести

router = APIRouter(prefix="/projects/{project_id}/reports", tags=["projects"])

# Модуль, записями которого журнал держит отчёты. Слово берётся у журнала, а не
# пишется здесь второй раз: разойтись им нельзя (`runs.проверить_модуль`).
МОДУЛЬ = "reports"


class ReportIn(BaseModel):
    """Тело создания отчёта: по какому бланку и как его звать."""

    template_id: str | None = Field(
        default=None,
        description=("One of the templates attached to this project "
                     "(GET /api/projects/{id}/templates). Without it the "
                     "first report of a project keeps the template the work "
                     "already has and any later report is started from a "
                     "blank document."))
    name: str = Field(
        default="", max_length=NAME_MAX,
        description=("What to call this report. Empty is fine: the interface "
                     "names it itself, from the module and n."))


class ReportOut(BaseModel):
    """Отчёт наружу: запись журнала плюс то, что видно на его карточке."""

    id: str = Field(description="Run id of this report: the value of ?report=")
    project_id: str
    name: str = Field(description="Empty means the interface names it itself")
    n: int = Field(description="Which report of this project, from 1")
    user_id: str | None = None
    created_at: str | None = None
    preview_artifact_id: str | None = Field(
        default=None,
        description="First page of the built document, as a PNG artifact")
    template_name: str = Field(
        default="",
        description="Name of the template this report is built from, if known")
    tags: int = Field(default=0, description="How many tags its template has")


def карточка(запись: ProjectRun, *, бланк: str = "", тегов: int = 0) -> dict:
    return {"id": запись.id, "project_id": запись.project_id,
            "name": запись.name, "n": int(запись.n),
            "user_id": запись.user_id, "created_at": iso(запись.created_at),
            "preview_artifact_id": запись.preview_artifact_id,
            "template_name": бланк, "tags": int(тегов)}


def записи(s, project_id: str) -> list[ProjectRun]:
    """Записи журнала об отчётах этой работы, старые сверху.

    Порядок — по времени и по номеру: он же определяет, какая запись владеет
    корневым документом (самая старая), и менять его отбором сортировки нельзя.
    """
    return list(s.scalars(
        select(ProjectRun)
        .where(ProjectRun.project_id == project_id,
               ProjectRun.module == МОДУЛЬ)
        .order_by(ProjectRun.created_at.asc(), ProjectRun.n.asc())))


def найти(s, project_id: str, run_id: str) -> ProjectRun:
    """Запись отчёта или `404`. Чужая и несуществующая отвечают одинаково."""
    запись = s.get(ProjectRun, check_id(run_id, where="path.run_id"))
    if (запись is None or запись.project_id != project_id
            or запись.module != МОДУЛЬ):
        raise ApiError(NOT_FOUND, "Report not found", 404, where="path.run_id")
    return запись


def развести(проект: orchestrator.Project, строки: list[ProjectRun]) -> None:
    """Дать каждой записи, кроме самой старой, свой каталог документа.

    Чинит работы, у которых журнал успел получить вторую запись об отчёте до
    появления каталогов: без этого два отчёта читали бы один набор значений и
    затирали бы друг друга. Самая старая запись остаётся в корне работы —
    переносить её значения незачем, они уже там, где записаны.

    Заводится документ по текущему бланку работы, а не по пустому: человек,
    нажавший «создать отчёт» на карточке работы, ждёт теги её бланка.
    Бланка нет — документ строится с нуля, как и работа без бланка.
    """
    for запись in строки[1:]:
        if есть_каталог(проект, запись.id):
            continue
        try:
            проект.create_report(запись.id, template=бланк_работы(проект))
        except orchestrator.OrchestratorError:
            беды.exception("работа %s: документ отчёта %s не завёлся",
                           проект.path, запись.id)


def есть_каталог(проект: orchestrator.Project, run_id: str) -> bool:
    """Есть ли у отчёта свой каталог документа."""
    return run_id in set(проект.reports())


def бланк_работы(проект: orchestrator.Project) -> bytes | None:
    """Байты бланка, по которому собирается корневой документ, или `None`."""
    try:
        return orchestrator.Project(проект.path).template()
    except orchestrator.OrchestratorError:
        return None


def бланк_отчёта(s, проект: orchestrator.Project, project_id: str,
                 run_id: str) -> tuple[str, int]:
    """Имя приложенного бланка этого отчёта и число тегов в нём.

    Имя ищется сличением артефакта бланка с `sha256` приложенных шаблонов — тем
    же способом, которым список бланков работы помечает выбранный
    (`templates.service.текущий_шаблон`). Отдельного поля «какой бланк у этого
    отчёта» в базе нет намеренно: правда о том, чем документ собирается, лежит
    в его `project.json`, и вторая запись рядом разошлась бы с ней при первой же
    смене бланка.
    """
    from ..templates import service as шаблоны                # noqa: PLC0415

    документ = orchestrator.Project(проект.path, report=run_id)
    try:
        свой = документ.template_artifact()
    except orchestrator.OrchestratorError:
        return "", 0
    for шаблон in шаблоны.шаблоны_проекта(s, project_id):
        if шаблон.sha256 == свой:
            return шаблон.name, int(шаблон.tags)
    try:
        return "", len(документ.manifest().tags)
    except orchestrator.OrchestratorError:
        return "", 0


@router.get("", operation_id="list_project_reports",
            response_model=list[ReportOut],
            summary="Reports of this project",
            description=(
                "Every report of the project, oldest first: what it is called, "
                "which report of this project it is, which template it is "
                "built from and the first page of what it built last. A "
                "project carries several reports, each with its own template "
                "and its own tag values; the id of a report is what the other "
                "routes take as `report`. Viewer role. 400 invalid_id, "
                "404 not_found, 409 in_trash."))
def список(project_id: str, request: Request, s: SessionDep,
           user: CurrentUser) -> list[dict]:
    """Отчёты работы карточками. Пустой список — законное состояние новой работы."""
    settings: Settings = настройки(request)
    p = доступный(s, user, project_id, VIEWER)
    проект = открыть(p, settings)
    строки = записи(s, p.id)
    развести(проект, строки)
    итог = []
    for запись in строки:
        бланк, тегов = бланк_отчёта(s, проект, p.id, запись.id)
        итог.append(карточка(запись, бланк=бланк, тегов=тегов))
    return итог


@router.post("", status_code=201, operation_id="create_project_report",
             response_model=ReportOut,
             summary="Start a new report in this project",
             description=(
                 "Starts a report: a journal entry and a document with its own "
                 "manifest and its own tag values. The very first report of a "
                 "project takes over the document the work already has, so "
                 "everything written in it before reports existed stays "
                 "visible; every report after that gets its own document on "
                 "the volume. `template_id` names one of the templates "
                 "attached to the project: for the first report it becomes the "
                 "template of the work, the same way "
                 "POST /api/projects/{id}/templates/{tid}/use does, and tag "
                 "values are kept; without it the first report keeps whatever "
                 "template the work already had and a later report starts from "
                 "a blank document. Editor role. 400 bad_template, "
                 "400 invalid_id, 403 forbidden, 404 not_found, 409 in_trash."))
def завести_отчёт(project_id: str, тело: ReportIn, request: Request,
                  s: SessionDep, user: CurrentUser) -> dict:
    """Новый отчёт: запись журнала и документ под ней.

    **Первый отчёт работы забирает её корневой документ, а не заводит пустой.**
    Работа существует до всяких отчётов: её заводили с бланком, в ней уже писали
    значения, собирали PDF. Отдельный пустой каталог первому же отчёту означал
    бы, что всё написанное разом пропало с экрана — при том, что лежит оно на
    томе целым. Правило то же самое, по которому список чинит старые работы
    (`развести`): корневой документ принадлежит самой старой записи об отчёте.
    Отсюда и условие — записей об отчётах ещё нет, значит корень свободен.

    Бланк при этом назначается корню тем же действием, что и «собирать по этому
    бланку» (`templates.service.выбрать` → `Project.update_template`): новый
    манифест строится поверх старого, и значения тегов остаются на месте. Завести
    корню документ заново значило бы стереть их ради смены бланка.

    Все следующие отчёты получают свой каталог **всегда**, даже когда бланк не
    назван: документ без каталога — это документ в корне работы, то есть общий с
    первым отчётом, и молча свести два отчёта в один набор значений хуже, чем
    завести пустой документ.

    Удаление первого отчёта корневой документ не сносит (`drop_report` не
    находит каталога и ничего не делает), поэтому следующий заведённый отчёт
    снова забирает его вместе с написанным. Это то же правило, а не исключение
    из него: у работы один собственный документ, и принадлежит он самой старой
    записи об отчёте — какой бы она ни была.
    """
    from ..templates import service as шаблоны                # noqa: PLC0415

    settings: Settings = настройки(request)
    p = доступный(s, user, project_id, EDITOR)
    проект = открыть(p, settings)

    бланк_ид = (тело.template_id or "").strip()
    корень_свободен = not записи(s, p.id)

    данные: bytes | None = None
    if бланк_ид:
        # Только из приложенных: список приложенных и есть то, из чего
        # выбирают, — тот же довод, что у «собирать по этому бланку». Проверка
        # стоит до записи журнала: чужой бланк не должен оставлять за собой
        # строку о несостоявшемся отчёте.
        шаблон = шаблоны.приложенный(s, p.id, бланк_ид)
        if not корень_свободен:
            данные = шаблоны.байты(settings, шаблон)

    запись = завести(s, p, user, module=МОДУЛЬ, name=тело.name)
    if корень_свободен:
        # Каталога не заводим вовсе: документ этого отчёта — корень работы.
        # Бланк, если он назван, встаёт корню сменой бланка, а не новым
        # документом; не назван — корень остаётся при своём.
        if бланк_ид:
            шаблоны.выбрать(s, settings, p.id, проект.path, бланк_ид)
    else:
        try:
            проект.create_report(запись.id, template=данные)
        except orchestrator.OrchestratorError:
            # В тексте беды оркестратора бывает путь на томе — наружу он не
            # уезжает.
            беды.exception("работа %s: отчёт по бланку не завёлся", p.id)
            raise ApiError(BAD_TEMPLATE,
                           "Template cannot be used for this work", 400,
                           where="body.template_id") from None
    бланк, тегов = бланк_отчёта(s, проект, p.id, запись.id)
    return карточка(запись, бланк=бланк, тегов=тегов)


@router.delete("/{run_id}", status_code=204,
               operation_id="delete_project_report",
               summary="Delete one report of this project",
               description=(
                   "Removes a report: its journal entry, its tag values, their "
                   "version history and its build directory. The template it "
                   "was built from stays attached to the project, and "
                   "artifacts stay on the volume: an artifact is addressed by "
                   "its content and may be the value of a tag in another "
                   "report. Editor role. 400 invalid_id, 403 forbidden, "
                   "404 not_found, 409 in_trash."),
               response_class=Response)
def снести(project_id: str, run_id: str, request: Request, s: SessionDep,
           user: CurrentUser) -> Response:
    """Снести отчёт вместе с его документом."""
    settings: Settings = настройки(request)
    p = доступный(s, user, project_id, EDITOR)
    запись = найти(s, p.id, run_id)
    проект = открыть(p, settings)
    проект.drop_report(запись.id)
    s.delete(запись)
    s.flush()
    return Response(status_code=204)


__all__ = ["router", "ReportIn", "ReportOut", "карточка", "записи", "найти",
           "развести", "МОДУЛЬ"]
