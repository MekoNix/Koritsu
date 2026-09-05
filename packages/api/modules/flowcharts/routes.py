"""
routes — блок-схемы: `/api/flowcharts` и `/api/projects/{id}/flowcharts`.

    POST /api/projects/{id}/flowcharts           201  построить и сохранить
    PUT  /api/projects/{id}/flowcharts/{run_id}  200  перестроить сохранённую
    GET  /api/projects/{id}/flowcharts           200  список схем работы
    GET  /api/projects/{id}/flowcharts/{run_id}  200  схема с кодом и XML
    GET  /api/flowcharts/modes                   200  режимы отрисовки
    POST /api/flowcharts/preview                 200  схема без проекта

**Построение в проект — оно же сохранение.** Отдельной кнопки «сохранить в
проект» нет: построенная схема уже результат работы, и человек, ушедший с
экрана, ждёт найти её назавтра в своей работе. Поэтому маршрут кладёт XML
артефактом, пишет запись в журнал запусков и запоминает, чем схема построена
(код, язык, режим) — вместе, одним запросом. Подробности — `api/modules/saved.py`.

Перестройка (`PUT`) новой записи не заводит: пока подбирается код, кнопку
нажимают пять раз подряд, и пять «Схема 1…5» в журнале — это не история, а шум.

**Предпросмотр без проекта остаётся**, но он не про экран работы: там схема
сохраняется, а этот маршрут не пишет на том **ничего** и не требует роли — он
для схемы, построенной вне работы (внешним ключом, чужим инструментом).

Исходник — либо текстом (`source`), либо идентификатором материала
(`material_id`), ровно одно из двух. Оба сразу — отказ: прислав оба, человек не
узнал бы, какой из них попал на схему, иначе как по картинке, то есть поздно.

Коды отказа и потолок исходника — общие с модулем `uml` и объяснены там же
(`api/modules/diagrams.py`).
"""
from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

import orchestrator

from ...db import SessionDep
from ...materials.deps import (CurrentUser, РедакторПроекта, Проект,
                               ЧитательПроекта)
from .. import diagrams as общее
from .. import saved

router = APIRouter(tags=["flowcharts"])

# Умолчания входа. Стоят одним местом, потому что их два маршрута и одно
# значение: разъехавшись, они дали бы разные схемы по одному коду — ровно то,
# ради чего фасад `orchestrator.diagrams` и заводился.
ЯЗЫК_ПО_УМОЛЧАНИЮ = "py"
РЕЖИМ_ПО_УМОЛЧАНИЮ = "default"

# Имя артефакта. Наружу не уезжает и в путь не превращается: `put_artifact`
# адресует содержимым, а имя принимает только для читаемости вызова.
ИМЯ_АРТЕФАКТА = "схема"

# Имя модуля в реестре и в журнале запусков. Строкой здесь, а не в `saved`:
# `saved` общий на два модуля и не обязан знать, какой из них его позвал.
МОДУЛЬ = "flowcharts"

_ЯЗЫК = Field(default=ЯЗЫК_ПО_УМОЛЧАНИЮ,
              description="Source language: py, cs or cpp")
_РЕЖИМ = Field(default=РЕЖИМ_ПО_УМОЛЧАНИЮ,
               description=("Drawing mode, see GET /api/flowcharts/modes; "
                            "loopLimit is accepted as the former name of "
                            "gost_19_701_90"))


class FlowchartIn(BaseModel):
    """Что рисуем: код текстом или материал проекта, и как именно."""

    source: str | None = Field(
        default=None, description="Source code; give this or material_id")
    material_id: str | None = Field(
        default=None, description="Id of a text material of the project")
    lang: str = _ЯЗЫК
    mode: str = _РЕЖИМ


class FlowchartPreviewIn(BaseModel):
    """То же, но без проекта: материалов здесь нет, только текст."""

    source: str = Field(description="Source code to draw")
    lang: str = _ЯЗЫК
    mode: str = _РЕЖИМ


@router.get("/flowcharts/modes", operation_id="flowcharts_modes",
            summary="Drawing modes of the flowchart builder",
            description=(
                "Every mode the builder accepts, with a short description of "
                "what it draws, in Russian for the site to translate. The id "
                "goes into the mode field of the two building routes. The GOST "
                "mode is listed once, as gost_19_701_90; its former name "
                "loopLimit is still accepted in requests."))
def режимы() -> list[dict]:
    """Режимы отрисовки: перечень спрашивается у строителя, не пишется здесь.

    Свой список разошёлся бы с `modes.yaml` на первом же добавленном режиме, и
    человек получал бы отказ на режим, который строитель прекрасно рисует.

    ГОСТ-режим назван одним именем — `gost_19_701_90`;
    прежнее `loopLimit` по-прежнему принимается на вход как синоним, но в
    перечне его нет: два пункта на один режим — это выбор, которого нет.
    """
    return orchestrator.diagrams.flowchart_modes()


@router.post("/flowcharts/preview", operation_id="flowcharts_preview",
             summary="Draw a flowchart without saving it",
             description=(
                 "Draws a flowchart from source code and returns the drawio XML "
                 "without touching the volume: nothing is stored and no project "
                 "is needed. For the editor screen, where the picture is "
                 "redrawn while the code is typed. Any signed-in user, at most "
                 "30 requests per minute. 400 invalid_source, 400 unknown_lang, "
                 "400 unknown_mode, 413 source_too_large, 422 diagram_failed, "
                 "429 rate_limited."))
def предпросмотр(тело: FlowchartPreviewIn, request: Request,
                 user: CurrentUser) -> dict:
    """Схема по коду из тела. На том не пишется ничего — в этом весь смысл.

    Вошедший нужен, а роли нет: проекта здесь тоже нет, спрашивать роль не в
    чем. Ограничивает этот маршрут не роль, а темп (30 в минуту на
    человека), потолок исходника и подпроцесс с лимитами.

    Темп спрашивается **первым** — до чтения тела и до подпроцесса: лимит,
    проверяемый после работы, не бережёт ту работу, ради которой он поставлен.
    """
    settings = request.app.state.settings
    общее.не_чаще(request, settings, user)
    имя, текст = общее.один_исходник(None, тело.source, None)
    общее.проверить_размер([(имя, текст)], settings, where="body.source")
    язык = общее.проверить_язык(тело.lang)
    режим = общее.проверить_режим(тело.mode)
    схема = общее.построить(request, settings, общее.FLOWCHART,
                            {"source": текст, "lang": язык, "mode": режим})
    return {"xml": схема.xml, "notices": схема.notices}


@router.post("/projects/{project_id}/flowcharts", status_code=201,
             operation_id="flowcharts_create",
             response_model=saved.DiagramBuiltOut,
             summary="Build a flowchart and keep it in the project",
             description=(
                 "Builds a flowchart from source code or from a text material "
                 "of the project, stores the drawio XML as a project artifact "
                 "and writes the diagram down in the run journal of the "
                 "project. There is no separate save step: what was built is "
                 "kept, together with the code and the settings it was built "
                 "with. The answer carries the XML, the artifact id and the "
                 "run_id of the journal entry: delete that entry to delete "
                 "the diagram. Editor role. 400 invalid_source, "
                 "400 unknown_lang, 400 unknown_mode, 403 forbidden, "
                 "404 not_found, 413 source_too_large, 422 diagram_failed."))
def построить(тело: FlowchartIn, request: Request, проект: РедакторПроекта,
              s: SessionDep, user: CurrentUser) -> dict:
    """Схема по коду или по материалу → артефакт проекта и запись журнала.

    Роль `editor`, а не `viewer`: артефакт занимает место на томе владельца
    проекта, и класть его в чужой проект тому, кому дали только смотреть,
    незачем.
    """
    схема, исходники, язык, режим = _построить(request, тело, проект)
    артефакт = общее.положить_артефакт(проект, схема, name=ИМЯ_АРТЕФАКТА)
    запись, строка = saved.сохранить(
        s, проект, user, module=МОДУЛЬ, kind=общее.FLOWCHART,
        artifact=артефакт, исходники=исходники, lang=язык, mode=режим)
    return saved.полная(проект, запись, строка, xml=схема.xml,
                        sources=saved.словарями(исходники),
                        notices=схема.notices, items=схема.items)


@router.put("/projects/{project_id}/flowcharts/{run_id}",
            operation_id="flowcharts_rebuild",
            response_model=saved.DiagramBuiltOut,
            summary="Rebuild a flowchart that is already in the project",
            description=(
                "Builds the flowchart again, from new code or with a new mode, "
                "and replaces what the journal entry points at. The "
                "entry itself stays: its name and its number do not change, "
                "because this is the same diagram drawn again, not a second "
                "one. Editor role. 400 invalid_id, 400 invalid_source, "
                "400 unknown_lang, 400 unknown_mode, 403 forbidden, "
                "404 not_found, 413 source_too_large, 422 diagram_failed."))
def перестроить(run_id: str, тело: FlowchartIn, request: Request,
                проект: РедакторПроекта, s: SessionDep) -> dict:
    """Та же схема заново: новый XML и новый код при прежнем номере."""
    запись, строка = saved.найти(s, проект, run_id, МОДУЛЬ)
    схема, исходники, язык, режим = _построить(request, тело, проект)
    артефакт = общее.положить_артефакт(проект, схема, name=ИМЯ_АРТЕФАКТА)
    saved.перестроить(s, проект, запись, строка, kind=общее.FLOWCHART,
                      artifact=артефакт, исходники=исходники, lang=язык,
                      mode=режим)
    return saved.полная(проект, запись, строка, xml=схема.xml,
                        sources=saved.словарями(исходники),
                        notices=схема.notices, items=схема.items)


@router.get("/projects/{project_id}/flowcharts", operation_id="flowcharts_list",
            response_model=list[saved.DiagramOut],
            summary="Flowcharts kept in this project",
            description=(
                "Every flowchart built in this project, newest first: what it "
                "is called, when it was built, what it was built with and "
                "which artifact holds its XML. UML diagrams are not in this "
                "list: they have their own. Viewer role. 400 invalid_id, "
                "404 not_found."))
def список(проект: ЧитательПроекта, s: SessionDep) -> list[dict]:
    """Список блок-схем работы. Диаграмм UML здесь нет — у них свой список."""
    return saved.список(s, проект, МОДУЛЬ)


@router.get("/projects/{project_id}/flowcharts/{run_id}",
            operation_id="flowcharts_one", response_model=saved.DiagramFullOut,
            summary="One kept flowchart, with its code and its XML",
            description=(
                "The diagram as it was built: the drawio XML, the source code "
                "and the settings. This is what opens the diagram back up for "
                "editing. Viewer role. 400 invalid_id, 404 not_found."))
def одна(run_id: str, проект: ЧитательПроекта, s: SessionDep) -> dict:
    """Сохранённая схема целиком: XML с тома, код и параметры из базы."""
    запись, строка = saved.найти(s, проект, run_id, МОДУЛЬ)
    артефакт = запись.artifact_id or ""
    return saved.полная(проект, запись, строка,
                        xml=saved.xml_артефакта(проект, артефакт),
                        notices=saved.замечания(проект, артефакт))


def _построить(request: Request, тело: FlowchartIn, проект: Проект):
    """Проверки, потолок и подпроцесс. → `(схема, исходники, язык, режим)`.

    Два маршрута постройки, одна последовательность шагов: порядок проверок —
    он же порядок отказов, и повторять его дважды значило бы дважды его менять.
    """
    settings = request.app.state.settings
    имя, текст = общее.один_исходник(проект, тело.source, тело.material_id)
    общее.проверить_размер([(имя, текст)], settings, where="body.source")
    язык = общее.проверить_язык(тело.lang)
    режим = общее.проверить_режим(тело.mode)
    схема = общее.построить(request, settings, общее.FLOWCHART,
                            {"source": текст, "lang": язык, "mode": режим})
    return схема, [(имя, текст)], язык, режим


__all__ = ["router", "FlowchartIn", "FlowchartPreviewIn"]
