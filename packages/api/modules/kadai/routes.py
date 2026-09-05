"""
routes — задания: `/api/kadai` и `/api/projects/{id}/kadai`.

    GET /api/kadai/stages                 200  имена стадий по порядку
    GET /api/projects/{id}/kadai          200  ход работы: стадии, остановка, файлы
    PUT /api/projects/{id}/kadai/condition 200 назвать материал условием (editor)

Трёх маршрутов хватает, потому что делает работу не модуль, а очередь: прогон
и замечание — задания `kadai_run` и `kadai_rework`, и второго способа их
запустить здесь не заводится. Осталось ровно то, чего у заданий нет.

**Стадии — списком, а не константой в клиенте.** Их семь, границы между ними
проведены по цене ошибки (записка Е.1), и сайт рисует по ним полоску ещё до
первого прогона. Своя копия списка в браузере отстала бы от пакета молча —
восьмая стадия появилась бы в службе и не появилась бы на экране.

**Ход работы — снимок с тома, а не карточка задания.** `job.result` знает срез
последнего прогона, а работа переживает несколько прогонов (остановка на
вопросе, замечание, продолжение), и после перезагрузки страницы карточки
задания может не быть вовсе. Читается это без модели и без стадий
(`orchestrator.kadai.status`), поэтому опрашивать снимок дёшево.

**Условие — отдельный маршрут, а не флаг загрузки.** Человек подтверждает
распознанное **после** приёма файла (решение владельца 2026-08-31): до
подтверждения условие — обычный материал. Поэтому «назвать условием» это
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


class ConditionIn(BaseModel):
    """Какой материал проекта считать условием задачи."""

    material_id: str = Field(
        description="Id of an already parsed material of this project")


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


__all__ = ["router", "ConditionIn"]
