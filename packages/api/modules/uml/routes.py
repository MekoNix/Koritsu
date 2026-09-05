"""
routes — диаграммы UML: `/api/uml` и `/api/projects/{id}/uml/…`.

    POST /api/projects/{id}/uml/classes  201  диаграмма классов (роль editor)
    POST /api/projects/{id}/uml/objects  201  диаграмма объектов (роль editor)
    GET  /api/uml/themes                 200  палитры
    POST /api/uml/classes/preview        200  классы без проекта и без записи
    POST /api/uml/objects/preview        200  объекты без проекта и без записи

Два вида диаграмм, а не один маршрут с полем `kind`. Они отвечают на разные
вопросы — «какие типы есть» и «какие экземпляры создаются», — и различить их
полем значило бы описать в OpenAPI один маршрут, у которого половина ответа
зависит от строки в теле: сгенерированный клиент сайта такое отдаёт `any`.

`sources` — список: строка считается идентификатором материала проекта, объект
`{name, source}` — исходником в теле. Смешивать можно: человек присылает три
файла проекта и один набросок, и запрещать это значило бы заставить его сначала
загрузить набросок материалом. У диаграммы объектов первый исходник — точка
входа (модуль, `Main()`, `main()`), остальные едут соседними файлами; порядок
поэтому значащий, и менять его служба не вправе.

Коды отказа, потолок исходника и подпроцесс — общие с модулем `flowcharts` и
объяснены там же (`api/modules/diagrams.py`).
"""
from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

import orchestrator

from ...materials.deps import CurrentUser, РедакторПроекта
from .. import diagrams as общее

router = APIRouter(tags=["uml"])

ЯЗЫК_ПО_УМОЛЧАНИЮ = "py"
ТЕМА_ПО_УМОЛЧАНИЮ = "dark"

# Имена артефактов. Те же слова, что ставит прогон агента (`tools.py`): одна
# схема, построенная двумя путями, обязана называться одинаково — иначе в
# журнале производных у неё два имени и ни одного правильного.
ИМЯ_КЛАССОВ = "классы"
ИМЯ_ОБЪЕКТОВ = "объекты"

_ЯЗЫК = Field(default=ЯЗЫК_ПО_УМОЛЧАНИЮ,
              description="Source language: py, cs or cpp")
_ТЕМА = Field(default=ТЕМА_ПО_УМОЛЧАНИЮ,
              description="Palette, see GET /api/uml/themes")


class UmlSourceIn(BaseModel):
    """Исходник в теле запроса: как называется и что в нём написано.

    Имя нужно разбору (в замечание «файл не разобрался» едет именно оно) и
    человеку в ответе. Путём оно не является и в путь не превращается нигде.
    """

    name: str = Field(default="", description="File name, for messages only")
    source: str = Field(description="Source code")


class UmlIn(BaseModel):
    """Что рисуем: материалы проекта, исходники в теле или и то и другое."""

    sources: list[str | UmlSourceIn] = Field(
        description="Material ids of the project, or objects with name and source")
    lang: str = _ЯЗЫК
    theme: str = _ТЕМА


class UmlPreviewIn(BaseModel):
    """То же, но без проекта: материалов здесь нет, только исходники в теле."""

    sources: list[UmlSourceIn] = Field(description="Sources to draw")
    lang: str = _ЯЗЫК
    theme: str = _ТЕМА


@router.get("/uml/themes", operation_id="uml_themes",
            summary="Palettes of the UML diagram builder",
            description=(
                "Every palette the builder accepts. The name goes into the "
                "theme field of the building routes. The css palette paints "
                "with CSS variables, so one diagram fits both a dark page and "
                "a light report."))
def темы() -> list[str]:
    """Палитры: перечень спрашивается у строителя, а не пишется здесь."""
    return orchestrator.diagrams.uml_themes()


# ── без проекта: для редактора на сайте ──────────────────────────────────────

@router.post("/uml/classes/preview", operation_id="uml_classes_preview",
             summary="Draw a class diagram without saving it",
             description=(
                 "Draws a UML class diagram from sources in the body and "
                 "returns the drawio XML without touching the volume. Any "
                 "signed-in user, at most 30 requests per minute. "
                 "400 invalid_source, 400 unknown_lang, 400 unknown_theme, "
                 "413 source_too_large, 422 diagram_failed, 429 rate_limited."))
def предпросмотр_классов(тело: UmlPreviewIn, request: Request,
                         user: CurrentUser) -> dict:
    """Диаграмма классов по исходникам из тела. На том не пишется ничего."""
    return _без_проекта(request, тело, общее.CLASSES, user)


@router.post("/uml/objects/preview", operation_id="uml_objects_preview",
             summary="Draw an object diagram without saving it",
             description=(
                 "Draws a UML object diagram from sources in the body and "
                 "returns the drawio XML without touching the volume. The first "
                 "source is the entry point, the rest are neighbouring files. "
                 "Any signed-in user, at most 30 requests per minute. "
                 "400 invalid_source, 400 unknown_lang, 400 unknown_theme, "
                 "413 source_too_large, 422 diagram_failed, 429 rate_limited."))
def предпросмотр_объектов(тело: UmlPreviewIn, request: Request,
                          user: CurrentUser) -> dict:
    """Диаграмма объектов по исходникам из тела. На том не пишется ничего."""
    return _без_проекта(request, тело, общее.OBJECTS, user)


# ── в проект: у схемы появляется идентификатор ───────────────────────────────

@router.post("/projects/{project_id}/uml/classes", status_code=201,
             operation_id="uml_classes",
             summary="Build a class diagram and keep it in the project",
             description=(
                 "Builds a UML class diagram from text materials of the project "
                 "or from sources in the body and stores the drawio XML as a "
                 "project artifact. The answer carries the artifact id and the "
                 "classes that got drawn. Editor role. 400 invalid_source, "
                 "400 unknown_lang, 400 unknown_theme, 403 forbidden, "
                 "404 not_found, 413 source_too_large, 422 diagram_failed."))
def классы(тело: UmlIn, request: Request, проект: РедакторПроекта) -> dict:
    """Диаграмма классов → артефакт проекта. В ответе — имена классов.

    Имена, а не только идентификатор: по ним человек видит, что схема про его
    код, — и видит это до того, как откроет картинку.
    """
    схема, язык, тема = _построить(request, тело, проект, общее.CLASSES)
    артефакт = общее.положить_артефакт(проект, схема, name=ИМЯ_КЛАССОВ)
    return {"artifact": артефакт, "notices": схема.notices,
            "lang": язык, "theme": тема, "classes": схема.items}


@router.post("/projects/{project_id}/uml/objects", status_code=201,
             operation_id="uml_objects",
             summary="Build an object diagram and keep it in the project",
             description=(
                 "Builds a UML object diagram from text materials of the project "
                 "or from sources in the body and stores the drawio XML as a "
                 "project artifact. The first source is the entry point, the "
                 "rest are neighbouring files. The answer carries the artifact "
                 "id, the instances that got drawn and the notes of the tracer. "
                 "Editor role. 400 invalid_source, 400 unknown_lang, "
                 "400 unknown_theme, 403 forbidden, 404 not_found, "
                 "413 source_too_large, 422 diagram_failed."))
def объекты(тело: UmlIn, request: Request, проект: РедакторПроекта) -> dict:
    """Диаграмма объектов → артефакт проекта. В ответе — экземпляры и заметки.

    Заметки трассировки («чего разбор не понял») отдаются целиком и ложатся
    рядом с артефактом: пересказать их короче значило бы решить за человека,
    какая недосказанность неважна, — а именно она и попадает потом в отчёт
    утверждением.
    """
    схема, язык, тема = _построить(request, тело, проект, общее.OBJECTS)
    артефакт = общее.положить_артефакт(проект, схема, name=ИМЯ_ОБЪЕКТОВ)
    return {"artifact": артефакт, "notices": схема.notices,
            "lang": язык, "theme": тема, "objects": схема.items}


# ── общее для четырёх маршрутов ──────────────────────────────────────────────

def _построить(request: Request, тело, проект, вид: str):
    """Проверки, потолок и подпроцесс. → `(схема, язык, тема)`.

    Четыре маршрута, одна последовательность шагов: порядок проверок — он же
    порядок отказов, и повторять его четырежды значило бы четырежды его менять.
    """
    settings = request.app.state.settings
    исходники = общее.несколько_исходников(проект, тело.sources)
    общее.проверить_размер(исходники, settings, where="body.sources")
    язык = общее.проверить_язык(тело.lang)
    тема = общее.проверить_тему(тело.theme)
    схема = общее.построить(
        request, settings, вид,
        {"sources": [{"name": имя, "source": код} for имя, код in исходники],
         "lang": язык, "theme": тема})
    return схема, язык, тема


def _без_проекта(request: Request, тело: UmlPreviewIn, вид: str, user) -> dict:
    """Предпросмотр обоих видов: тот же путь, но проекта нет и записи нет.

    Темп (30 в минуту на человека) спрашивается до всего остального и
    считается **общим на все три предпросмотра**, а не отдельным на маршрут:
    ограничивают-то не маршрут, а работу подпроцесса, а она у них одна и та же.
    Три отдельных счётчика по тридцать дали бы девяносто.
    """
    общее.не_чаще(request, request.app.state.settings, user)
    схема, _язык, _тема = _построить(request, тело, None, вид)
    return {"xml": схема.xml, "notices": схема.notices}


__all__ = ["router", "UmlIn", "UmlPreviewIn", "UmlSourceIn"]
