"""
routes — решения: `/api/kadai` и `/api/projects/{id}/kadai`.

    GET    /api/kadai/stages                     200  имена стадий по порядку
    GET    /api/projects/{id}/kadai/runs         200  решения этой работы
    POST   /api/projects/{id}/kadai/runs         201  завести решение   (editor)
    DELETE /api/projects/{id}/kadai/runs/{run_id} 204 снести решение    (editor)
    GET    /api/projects/{id}/kadai?run=         200  ход решения: стадии, файлы
    PUT    /api/projects/{id}/kadai/condition    200  назвать материал условием (editor)
    GET    /api/projects/{id}/kadai/wishes       200  пожелания к решению
    PUT    /api/projects/{id}/kadai/wishes       200  записать пожелания (editor)
    POST   /api/projects/{id}/kadai/restart      200  начать стадию заново (editor)

Маршрутов хватает этих, потому что делает работу не модуль, а очередь: прогон
и замечание — задания `kadai_run` и `kadai_rework`, и второго способа их
запустить здесь не заводится. Осталось ровно то, чего у заданий нет.

**Решений в работе много.** Одна задача — одно решение, а задач в работе
столько, сколько их задали: у каждого своё условие, свои пожелания, свой ход
стадий, свой список блоков с историей версий и своя папка файлов контекста. До
этого всё перечисленное было одно на работу, и вторая задача в ней затирала
первую.

**Решение — это запись журнала запусков (`module: "kadai"`) и каталог рядом с
ней.** Второй таблицы не заводится: имя, номер, время и «кто завёл» уже описаны
журналом (`projects/runs.py`), а всё, что принадлежит самому решению, лежит на
томе (`orchestrator.Project(path, solution=<run_id>)` — каталог
`kadai/<run_id>/`). Тот же разрез, что у отчётов, и по той же причине.

**`run` необязателен.** Пустой — работа целиком, как её видели, пока решение в
ней было одно; так же её читают маршруты, которым до отдельного решения дела
нет. Список решений при этом чинит старые работы: первое решение переезжает из
корня работы в свой каталог со всем, что у него было (`adopt_root_kadai`).

**Пожелания живут в проекте, а не в браузере.** Человек пишет их при заведении
работы, а первый прогон случается позже — после
того, как он подтвердит распознанное условие. До этого записи о работе не
существует вовсе, и хранить пожелания было негде: они лежали в
`sessionStorage`, то есть терялись вместе с вкладкой и не доезжали до второго
устройства. Своя запись на томе (`orchestrator.kadai.WISHES_KEY`) отдельно от
записи о задании: непустая запись о задании означает «работа заведена», и
положить пожелания туда значило бы объявить работу заведённой до первой стадии.

**«Начать стадию заново» не ставит задание и не зовёт модель.** Оно только
возвращает ход работы на томе к названной стадии; прогон после этого человек
запускает обычным `kadai_run`. Второй точки, из которой начинается платный
прогон, здесь не заводится — цена ошибки в ней измеряется списанными
единицами. До этого маршрута вставшая работа чинилась только замечанием к
условию, а оно переигрывает всё с разбора задания и стоит цены прогона.

**Стадии — списком, а не константой в клиенте.** Их семь, границы между ними
проведены по цене ошибки, и сайт рисует по ним полоску ещё до
первого прогона. Своя копия списка в браузере отстала бы от пакета молча —
восьмая стадия появилась бы в службе и не появилась бы на экране.

**Ход работы — снимок с тома, а не карточка задания.** `job.result` знает срез
последнего прогона, а работа переживает несколько прогонов (остановка на
вопросе, замечание, продолжение), и после перезагрузки страницы карточки
задания может не быть вовсе. Читается это без модели и без стадий
(`orchestrator.kadai.status`), поэтому опрашивать снимок дёшево.

**Условие — отдельный маршрут, а не флаг загрузки.** Человек подтверждает
распознанное **после** приёма файла: до подтверждения условие — обычный
материал. Поэтому «назвать условием» это
действие над проектом, и `PUT`: назвать дважды тот же материал — то же
состояние, а не второе условие.

Коды отказа: `400 invalid_id` — форма идентификатора; `403 forbidden` — роли
мало; `404 not_found` — нет проекта, спрашивающий не участник или нет такого
материала (одинаково: разные ответы рассказывали бы, что проект существует).
"""
from __future__ import annotations

from fastapi import APIRouter, Response
from pydantic import BaseModel, Field
from sqlalchemy import select

import materials as _materials
import orchestrator
from orchestrator import kadai as сценарий

from ...db import SessionDep
from ...errors import ApiError, NOT_FOUND
from ...ids import check_id
from ...materials.deps import CurrentUser, РедакторПроекта, ЧитательПроекта
from ...materials.routes import проверить_ид
from ...materials.service import открыть
from ...projects.models import NAME_MAX, ProjectRun
from ...projects.routes import РЕШЕНИЕ
from ...projects.runs import завести
from ...workspaces.service import iso

router = APIRouter(tags=["kadai"])

# Модуль, записями которого журнал держит решения. Слово берётся у журнала, а не
# пишется здесь второй раз: разойтись им нельзя.
МОДУЛЬ = "kadai"

# Тот же код отказа, каким отвечает задание `kadai_run`. Один, а не свой:
# человек видит одну беду — «сценарий отказал», — и различать её по тому, каким
# входом он попросил, ему незачем (`runs/handlers/kadai_run.KADAI_FAILED`).
KADAI_FAILED = "kadai_failed"


class ConditionIn(BaseModel):
    """Какой материал проекта считать условием задачи."""

    material_id: str = Field(
        description="Id of an already parsed material of this project")


class WishesIn(BaseModel):
    """Пожелания человека к работе — те же три поля, что у `kadai.plan.Wishes`."""

    text: str = Field(default="", max_length=4000,
                      description="What the person wants from the work, in prose")
    show_task: bool = Field(
        default=False,
        description="Stop and show how the assignment was understood")
    show_structure: bool = Field(
        default=False, description="Stop and show the structure before writing")


class SolutionIn(BaseModel):
    """Тело заведения решения. Поле одно: как его звать."""

    name: str = Field(
        default="", max_length=NAME_MAX,
        description=("What to call this solution. Empty is fine: the interface "
                     "names it itself, from the module and n."))


class SolutionOut(BaseModel):
    """Решение наружу: запись журнала плюс то, что видно на его карточке."""

    id: str = Field(description="Run id of this solution: the value of ?run=")
    project_id: str
    name: str = Field(description="Empty means the interface names it itself")
    n: int = Field(description="Which solution of this project, from 1")
    user_id: str | None = None
    created_at: str | None = None
    state: str | None = Field(
        default=None,
        description="State of the work: running, waiting_user, done, failed")
    stage: str | None = Field(
        default=None, description="Stage it has got to, in Russian")
    condition_name: str = Field(
        default="", description="File name of the assignment, when one is named")


class RestartIn(BaseModel):
    """С какой стадии начинать заново. Пусто — с той, на которой встали."""

    stage: str = Field(
        default="",
        description="Stage to restart from; empty means the one that stumbled")


def записи_решений(s, project_id: str) -> list:
    """Записи журнала о решениях этой работы, старые сверху.

    Порядок — по времени и по номеру: он же решает, какая запись владеет
    решением, лежащим в корне работы (самая старая), и менять его отбором
    сортировки нельзя.
    """
    return list(s.scalars(
        select(ProjectRun)
        .where(ProjectRun.project_id == project_id, ProjectRun.module == МОДУЛЬ)
        .order_by(ProjectRun.created_at.asc(), ProjectRun.n.asc())))


def найти_решение(s, project_id: str, run_id: str, *,
                  where: str = "path.run_id"):
    """Запись решения или `404`. Чужая и несуществующая отвечают одинаково."""
    запись = s.get(ProjectRun, check_id(run_id, where=where))
    if (запись is None or запись.project_id != project_id
            or запись.module != МОДУЛЬ):
        raise ApiError(NOT_FOUND, "Solution not found", 404, where=where)
    return запись


def развести_решения(проект, строки) -> None:
    """Дать каждому решению свой каталог, а первому — перевезти его из корня.

    Чинит работы, заведённые до появления второго решения: ход стадий, задание,
    пожелания и список блоков лежали тогда в корне работы, и вторая задача в той
    же работе читала бы их и затирала. Самая старая запись забирает корневое
    решение себе целиком, каждая следующая получает пустой каталог.

    Зовётся на каждом чтении списка и потому обязана быть безобидной на втором
    вызове: перевозить будет уже нечего, а каталоги на месте.
    """
    свои = set(проект.solutions())
    for номер, запись in enumerate(строки):
        if номер == 0:
            проект.adopt_root_kadai(запись.id)
        if запись.id not in свои:
            проект.create_solution(запись.id)


def карточка_решения(запись, вид=None) -> dict:
    """Запись журнала плюс то, что видно на карточке решения.

    `вид` — проект глазами этого решения; без него карточка одна запись журнала
    (так отвечает заведение: состояния у только что заведённого ещё нет).

    Имя файла с условием берётся из снимка хода работы, а нет снимка — с тома
    (`Project.condition`). Второй источник не запасной, а основной для решения,
    которое ещё не запускали: условие называют ДО прогона, и карточка,
    молчащая о нём до первой стадии, не отличала бы одну задачу от другой ровно
    там, где человек выбирает между ними.
    """
    снимок = сценарий.status(вид) if вид is not None else {}
    условие = dict(снимок.get("condition") or {})
    имя_условия = str(условие.get("name") or "")
    if not имя_условия and вид is not None:
        имя_условия = _имя_условия(вид)
    return {"id": запись.id, "project_id": запись.project_id,
            "name": запись.name, "n": int(запись.n), "user_id": запись.user_id,
            "created_at": iso(запись.created_at),
            "state": снимок.get("state"), "stage": снимок.get("stage"),
            "condition_name": имя_условия}


def _имя_условия(вид) -> str:
    """Как зовётся файл с условием этого решения. Не назван — пустая строка.

    Материала может уже не быть на томе (его унесли отдельным действием), и
    падать из-за этого списку решений нельзя: он открывается именно тогда,
    когда с работой что-то не так.
    """
    ид = вид.condition()
    if not ид:
        return ""
    try:
        return str(вид.store().get(ид).name)
    except Exception:                                        # noqa: BLE001
        return ""


def решение(проект, s, run: str, *, where: str = "query.run"):
    """Проект глазами названного решения. Пусто — работа целиком.

    Запись журнала спрашивается всегда, когда решение названо: без этого
    `?run=` открывал бы каталог по любой строке, которая прошла проверку формы,
    и решение соседней работы читалось бы своим.
    """
    если = str(run or "").strip()
    if not если:
        return открыть(проект)
    найти_решение(s, проект.id, если, where=where)
    return открыть(проект, solution=если)


@router.get("/projects/{project_id}/kadai/runs",
            operation_id="kadai_runs", response_model=list[SolutionOut],
            summary="Solutions of this project",
            description=(
                "Every solution of the project, oldest first: what it is "
                "called, which solution of this project it is, how far its "
                "work has got and which file holds its assignment. A project "
                "carries several solutions, each with its own assignment, its "
                "own wishes, its own list of blocks and its own context files; "
                "the id "
                "of a solution is what the other routes take as `run`. Viewer "
                "role. 400 invalid_id, 404 not_found."))
def решения(проект: ЧитательПроекта, s: SessionDep) -> list[dict]:
    """Решения работы карточками. Пустой список — законное состояние новой работы."""
    на_томе = открыть(проект)
    строки = записи_решений(s, проект.id)
    развести_решения(на_томе, строки)
    return [карточка_решения(з, на_томе.for_solution(з.id)) for з in строки]


@router.post("/projects/{project_id}/kadai/runs", status_code=201,
             operation_id="kadai_create_run", response_model=SolutionOut,
             summary="Start a new solution in this project",
             description=(
                 "Starts a solution: a journal entry and its own directory on "
                 "the volume, with its own assignment, wishes, block list and "
                 "context files. Nothing is run and nothing is charged here: "
                 "the run itself is started later by a `kadai_run` job, once the "
                 "assignment has been confirmed. Editor role. 400 invalid_id, "
                 "403 forbidden, 404 not_found."))
def завести_решение(тело: SolutionIn, проект: РедакторПроекта, s: SessionDep,
                    user: CurrentUser) -> dict:
    """Новое решение: запись журнала и каталог под её идентификатором.

    Каталог заводится сразу, а не при первой стадии: без него «решение есть, но
    ход стадий пуст» и «решения нет» на диске неразличимы, и второе решение
    работы читало бы ход первого.
    """
    на_томе = открыть(проект)
    строки = записи_решений(s, проект.id)
    развести_решения(на_томе, строки)
    запись = завести(s, проект, user, module=МОДУЛЬ, name=тело.name)
    на_томе.create_solution(запись.id)
    return карточка_решения(запись)


@router.delete("/projects/{project_id}/kadai/runs/{run_id}", status_code=204,
               operation_id="kadai_delete_run",
               summary="Delete one solution of this project",
               description=(
                   "Removes a solution: its journal entry, the state of its "
                   "work, its assignment, its wishes and its block list with "
                   "the version history. Its context files are unbound from "
                   "it; files attached to the project as a whole are left "
                   "alone, and so are artifacts: an artifact is addressed by "
                   "its content and may be part of another document. Editor "
                   "role. 400 invalid_id, 403 forbidden, 404 not_found."),
               response_class=Response)
def снести_решение(run_id: str, проект: РедакторПроекта,
                   s: SessionDep) -> Response:
    """Снести решение вместе с его каталогом и привязкой файлов контекста."""
    запись = найти_решение(s, проект.id, run_id)
    на_томе = открыть(проект)
    for mid in на_томе.solution_materials(запись.id):
        на_томе.unbind_material(mid, запись.id)
    на_томе.drop_solution(запись.id)
    s.delete(запись)
    s.flush()
    return Response(status_code=204)


@router.get("/kadai/stages", operation_id="kadai_stages",
            summary="Names of the seven stages, in order",
            description=(
                "The stages a piece of work goes through, in order. The "
                "interface draws its progress strip from this list, so it is "
                "data and not a constant in the client. Values are Russian on "
                "purpose: they are shown to a human as they are."))
def стадии() -> dict:
    """Имена стадий по порядку — то, из чего сайт рисует шаги."""
    return {"stages": list(сценарий.stage_names())}


@router.get("/projects/{project_id}/kadai", operation_id="kadai_status",
            summary="How far the work in this project has got",
            description=(
                "A snapshot of the work: stage states, what it is waiting for, "
                "the condition as it was read, problems, and the artifacts of "
                "everything already built. Empty `work` means no run has been "
                "started for this project yet, which is not an error. Reading "
                "it costs nothing: no model call and no stage is run. `run` "
                "names the solution to read; without it the project is read as "
                "a whole, the way it looked while it carried one solution. "
                "400 invalid_id, 404 not_found."))
def ход(проект: ЧитательПроекта, s: SessionDep, run: str = РЕШЕНИЕ) -> dict:
    """Снимок хода решения. Пусто — прогона ещё не было.

    Пустой снимок отдаётся `200`, а не `404`: страница решения открывается до
    первого прогона, и отказ на ней читался бы как «проекта нет».
    """
    снимок = сценарий.status(решение(проект, s, run))
    return снимок or {"work": None, "state": None, "stage": None, "stages": [],
                      "current": "", "hold": None, "condition": {},
                      "condition_text": "", "problems": [], "outputs": {},
                      "made": {}, "requirement": {}, "wishes": {}, "since": 0}


@router.put("/projects/{project_id}/kadai/condition",
            operation_id="kadai_set_condition",
            summary="Name the material that holds the assignment",
            description=(
                "Marks an already parsed material of this project as the "
                "condition of the task. Until one is named, a `kadai_run` job "
                "refuses: there is nothing to solve. Naming the same material "
                "twice is the same state, which is why this is a PUT. Every "
                "solution has an assignment of its own: `run` says which. "
                "Editor role. 400 invalid_id, 403 forbidden, 404 not_found."))
def назначить_условие(тело: ConditionIn, проект: РедакторПроекта,
                      s: SessionDep, run: str = РЕШЕНИЕ) -> dict:
    """Назвать материал условием задачи. Материал обязан быть разобран."""
    проверить_ид(тело.material_id)
    проект_на_томе = решение(проект, s, run)
    try:
        проект_на_томе.set_condition(тело.material_id)
    except _materials.MaterialsError:
        # Материал есть в задании на разбор, но ещё не разобран — с точки
        # зрения хранилища его нет, и различать эти два случая кодом ответа
        # значило бы рассказывать, что кто-то грузит файл прямо сейчас.
        raise ApiError(NOT_FOUND, "Material not found", 404,
                       where="body.material_id") from None
    return {"condition": проект_на_томе.condition()}


@router.get("/projects/{project_id}/kadai/wishes",
            operation_id="kadai_wishes",
            summary="What the person asked of this work",
            description=(
                "The wishes stored with the project: the prose request and the "
                "two stop points. A `kadai_run` job reads them when its payload "
                "carries none, which is what happens on the first run: the "
                "person writes them when the work is created, and the run only "
                "starts once the assignment has been confirmed. Empty is not an "
                "error; it means nothing was written. `run` names the "
                "solution they belong to. 400 invalid_id, 404 not_found."))
def пожелания(проект: ЧитательПроекта, s: SessionDep, run: str = РЕШЕНИЕ) -> dict:
    """Пожелания к решению с тома. Пусто — их не писали."""
    return сценарий.wishes(решение(проект, s, run))


@router.put("/projects/{project_id}/kadai/wishes",
            operation_id="kadai_set_wishes",
            summary="Store the wishes for this work",
            description=(
                "Writes the wishes into the project, replacing what was there: "
                "wishes are one text and two flags, and half of them is not a "
                "state. They reach the model on the first run, and only there: "
                "the scenario reads its wishes once, when the work is created. "
                "`run` names the solution they belong to. Editor role. "
                "400 invalid_id, 403 forbidden, 404 not_found."))
def записать_пожелания(тело: WishesIn, проект: РедакторПроекта,
                       s: SessionDep, run: str = РЕШЕНИЕ) -> dict:
    """Записать пожелания решения. Заменяются целиком."""
    return сценарий.set_wishes(решение(проект, s, run), text=тело.text,
                               show_task=тело.show_task,
                               show_structure=тело.show_structure)


@router.post("/projects/{project_id}/kadai/restart",
             operation_id="kadai_restart",
             summary="Start a stage over on a work that has stopped",
             description=(
                 "Puts the named stage and everything after it back to "
                 "'waiting' and the work back to 'running'. No model is called "
                 "and nothing is charged: the run itself is started afterwards "
                 "by the usual `kadai_run` job, so that a paid run still begins "
                 "in exactly one place. With no stage named it takes the one "
                 "that stumbled, or the one holding the work with a question. A "
                 "work that is running and has stopped nowhere is refused. "
                 "Editor role. 400 invalid_id, 403 forbidden, 404 not_found, "
                 "422 kadai_failed. `run` names the solution."))
def начать_заново(тело: RestartIn, проект: РедакторПроекта, s: SessionDep,
                  run: str = РЕШЕНИЕ) -> dict:
    """Вернуть вставшее решение к названной стадии. Модель не зовётся."""
    try:
        return сценарий.restart(решение(проект, s, run), stage=тело.stage)
    except Exception as беда:                                # noqa: BLE001
        # Тот же довод, что в `runs/handlers/kadai_run.py`: ловить сценарий по
        # имени класса значило бы импортировать `kadai` из службы. Текст уезжает
        # наружу как есть — он по-русски и путей на томе не содержит.
        raise ApiError(KADAI_FAILED, str(беда), 422, where="body.stage") from None


__all__ = ["router", "ConditionIn", "WishesIn", "RestartIn", "SolutionIn",
           "SolutionOut", "KADAI_FAILED", "МОДУЛЬ", "записи_решений",
           "найти_решение", "развести_решения", "решение", "карточка_решения"]
