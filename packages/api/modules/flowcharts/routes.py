"""
routes — блок-схемы: `/api/flowcharts` и `/api/projects/{id}/flowcharts`.

    POST /api/projects/{id}/flowcharts  201  схема в проект (роль editor)
    GET  /api/flowcharts/modes          200  режимы отрисовки с описаниями
    POST /api/flowcharts/preview        200  схема без проекта и без записи

Два маршрута построения, а не один, — потому что у них разная цена и разные
права. Тот, что в проекте, кладёт XML артефактом: у схемы появляется
идентификатор, её можно поставить в тег отчёта, скачать и переделать. Тот, что
без проекта, — для левой половины экрана «Блок-схемы» (макет владельца: слева
код и параметры, справа схема): человек правит код и видит картинку, и заводить
артефакт на каждое нажатие клавиши значило бы засыпать том мусором, который
никто не назвал. Поэтому `preview` не пишет на том **ничего** и не требует роли
— только входа.

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

from ...materials.deps import CurrentUser, РедакторПроекта
from .. import diagrams as общее

router = APIRouter(tags=["flowcharts"])

# Умолчания входа. Стоят одним местом, потому что их два маршрута и одно
# значение: разъехавшись, они дали бы разные схемы по одному коду — ровно то,
# ради чего фасад `orchestrator.diagrams` и заводился.
ЯЗЫК_ПО_УМОЛЧАНИЮ = "py"
РЕЖИМ_ПО_УМОЛЧАНИЮ = "default"

# Имя артефакта. Наружу не уезжает и в путь не превращается: `put_artifact`
# адресует содержимым, а имя принимает только для читаемости вызова.
ИМЯ_АРТЕФАКТА = "схема"

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

    ГОСТ-режим назван одним именем — `gost_19_701_90` (решение владельца §12);
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
    чем. Ограничивает этот маршрут не роль, а темп (§12: 30 в минуту на
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
             summary="Build a flowchart and keep it in the project",
             description=(
                 "Builds a flowchart from source code or from a text material "
                 "of the project and stores the drawio XML as a project "
                 "artifact. The answer carries the artifact id: download it "
                 "with GET /api/projects/{project_id}/artifacts/{artifact_id} "
                 "or put it into a diagram tag value. Editor role. "
                 "400 invalid_source, 400 unknown_lang, 400 unknown_mode, "
                 "403 forbidden, 404 not_found, 413 source_too_large, "
                 "422 diagram_failed."))
def построить(тело: FlowchartIn, request: Request,
              проект: РедакторПроекта) -> dict:
    """Схема по коду или по материалу → артефакт проекта.

    Роль `editor`, а не `viewer`: артефакт занимает место на томе владельца
    проекта, и класть его в чужой проект тому, кому дали только смотреть,
    незачем.
    """
    settings = request.app.state.settings
    имя, текст = общее.один_исходник(проект, тело.source, тело.material_id)
    общее.проверить_размер([(имя, текст)], settings, where="body.source")
    язык = общее.проверить_язык(тело.lang)
    режим = общее.проверить_режим(тело.mode)
    схема = общее.построить(request, settings, общее.FLOWCHART,
                            {"source": текст, "lang": язык, "mode": режим})
    артефакт = общее.положить_артефакт(проект, схема, name=ИМЯ_АРТЕФАКТА)
    return {"artifact": артефакт, "notices": схема.notices,
            "mode": режим, "lang": язык}


__all__ = ["router", "FlowchartIn", "FlowchartPreviewIn"]
