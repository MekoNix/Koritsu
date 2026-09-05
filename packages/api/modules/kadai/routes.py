"""
routes — задания: `/api/kadai` и `/api/projects/{id}/kadai`.

    GET  /api/kadai/stages                  200  имена стадий по порядку
    GET  /api/projects/{id}/kadai           200  ход работы: стадии, остановка, файлы
    PUT  /api/projects/{id}/kadai/condition 200  назвать материал условием (editor)
    GET  /api/projects/{id}/kadai/wishes    200  пожелания к работе
    PUT  /api/projects/{id}/kadai/wishes    200  записать пожелания (editor)
    POST /api/projects/{id}/kadai/restart   200  начать стадию заново (editor)

Маршрутов хватает этих, потому что делает работу не модуль, а очередь: прогон
и замечание — задания `kadai_run` и `kadai_rework`, и второго способа их
запустить здесь не заводится. Осталось ровно то, чего у заданий нет.

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

from fastapi import APIRouter
from pydantic import BaseModel, Field

import materials as _materials
from orchestrator import kadai as сценарий

from ...errors import ApiError, NOT_FOUND
from ...materials.deps import РедакторПроекта, ЧитательПроекта
from ...materials.routes import проверить_ид
from ...materials.service import открыть

router = APIRouter(tags=["kadai"])

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


class RestartIn(BaseModel):
    """С какой стадии начинать заново. Пусто — с той, на которой встали."""

    stage: str = Field(
        default="",
        description="Stage to restart from; empty means the one that stumbled")


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
                "it costs nothing: no model call and no stage is run. "
                "400 invalid_id, 404 not_found."))
def ход(проект: ЧитательПроекта) -> dict:
    """Снимок хода работы. Пусто — прогона ещё не было.

    Пустой снимок отдаётся `200`, а не `404`: страница заданий открывается до
    первого прогона, и отказ на ней читался бы как «проекта нет».
    """
    снимок = сценарий.status(открыть(проект))
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
                "twice is the same state, which is why this is a PUT. Editor "
                "role. 400 invalid_id, 403 forbidden, 404 not_found."))
def назначить_условие(тело: ConditionIn, проект: РедакторПроекта) -> dict:
    """Назвать материал условием задачи. Материал обязан быть разобран."""
    проверить_ид(тело.material_id)
    проект_на_томе = открыть(проект)
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
                "error; it means nothing was written. 400 invalid_id, "
                "404 not_found."))
def пожелания(проект: ЧитательПроекта) -> dict:
    """Пожелания к работе с тома. Пусто — их не писали."""
    return сценарий.wishes(открыть(проект))


@router.put("/projects/{project_id}/kadai/wishes",
            operation_id="kadai_set_wishes",
            summary="Store the wishes for this work",
            description=(
                "Writes the wishes into the project, replacing what was there: "
                "wishes are one text and two flags, and half of them is not a "
                "state. They reach the model on the first run, and only there: "
                "the scenario reads its wishes once, when the work is created. "
                "Editor role. 400 invalid_id, 403 forbidden, 404 not_found."))
def записать_пожелания(тело: WishesIn, проект: РедакторПроекта) -> dict:
    """Записать пожелания в проект. Заменяются целиком."""
    return сценарий.set_wishes(открыть(проект), text=тело.text,
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
                 "422 kadai_failed."))
def начать_заново(тело: RestartIn, проект: РедакторПроекта) -> dict:
    """Вернуть вставшую работу к названной стадии. Модель не зовётся."""
    try:
        return сценарий.restart(открыть(проект), stage=тело.stage)
    except Exception as беда:                                # noqa: BLE001
        # Тот же довод, что в `runs/handlers/kadai_run.py`: ловить сценарий по
        # имени класса значило бы импортировать `kadai` из службы. Текст уезжает
        # наружу как есть — он по-русски и путей на томе не содержит.
        raise ApiError(KADAI_FAILED, str(беда), 422, where="body.stage") from None


__all__ = ["router", "ConditionIn", "WishesIn", "RestartIn", "KADAI_FAILED"]
