"""
routes — `/api/search`: одна строка запроса, два списка в ответ.

    GET /api/search?workspace_id=…&q=сорти   200  {"projects": [...], "materials": [...]}

**Пространство обязательно.** Раньше поиск ходил по всем пространствам сразу —
«ищут затем, чтобы не помнить, где работа лежит», — и это оказалось неправдой о
том, как пространствами пользуются: пространство разделяет работу с кафедрой и
свою, и человек, набравший три буквы в чужом пространстве, видел названия своих
работ там, где их быть не должно. Поиск поэтому ищет в том пространстве, в
котором человек сейчас работает, и параметра по умолчанию у него нет: пропущенный
`workspace_id` — `422 validation_failed`, а не «поищу везде».

Отбор доступа при этом никуда не девается — он в `require_role`: чужое
пространство отвечает `404`, даже если идентификатор угадан дословно.

**Два списка, а не один перемешанный.** Работа и файл внутри работы — разные
вещи: у первой свой экран, у второго только опись работы, куда он и ведёт.
Смешать их в одну выдачу значило бы, что клиент обязан различать их по полю, а
рисовать одинаково — то есть завести у себя ту же пару списков, только позже.

**Пустой запрос — пустые списки, а не вся опись.** `q=` без текста означает
«человек ещё ничего не набрал»; отдать ему на это всё, что у него есть, —
значит показать выдачу, которую он не спрашивал, и заплатить за неё обходом
тома.

Потолок у каждого списка свой (`ПОТОЛОК`, 20). Общего потолка на двоих нет
намеренно: сорок найденных файлов иначе вытеснили бы работу, которую человек и
искал.

Коды отказа этого модуля:

    unauthorized       401  вошедшего нет
    invalid_id         400  `workspace_id` не uuid4
    not_found          404  нет такого пространства, или спрашивающий не в нём
    validation_failed  422  `workspace_id` не прислан
"""
from __future__ import annotations

from fastapi import APIRouter, Query, Request

from ..db import SessionDep
from ..ids import check_id
from ..settings import Settings
from ..workspaces.deps import CurrentUser
from ..workspaces.service import VIEWER, require_role
from . import service

router = APIRouter(prefix="/search", tags=["search"])

# Сколько строк отдаём в каждом списке. Двадцать — это потолок подсказки, а не
# выдачи: палитра показывает их без прокрутки, и двадцать первая строка означает
# не «мало нашли», а «плохо спросили».
ПОТОЛОК = 20


def настройки(request: Request) -> Settings:
    """Настройки приложения. Через `request`, как у соседей: путь тома знает
    приложение, а не маршрут."""
    return request.app.state.settings


@router.get("", operation_id="search",
            summary="Find a project or a material in one workspace",
            description=(
                "Searches the names of the projects of one workspace and the "
                "names of the materials inside them. `workspace_id` is "
                "required: the search answers about the workspace the caller "
                "works in, never about all of them at once. Matching is "
                "case-insensitive and by substring, and the trash is not "
                "searched. Answers two lists, at most 20 entries each; an "
                "empty query answers two empty lists rather than everything. "
                "Each project carries the module its work belongs to, so the "
                "caller knows which screen to open. 400 invalid_id, "
                "404 not_found, 422 validation_failed."))
def найти(request: Request, s: SessionDep, user: CurrentUser,
          workspace_id: str = Query(
              ..., description="Workspace to search in; required"),
          q: str = Query("", max_length=200,
                         description="What to look for, a substring of a name"),
          limit: int = Query(ПОТОЛОК, ge=1, le=ПОТОЛОК,
                             description="Max entries in each list")) -> dict:
    """Работы и файлы пространства, в именах которых есть набранное."""
    ws = require_role(s, user.id,
                      check_id(workspace_id, where="query.workspace_id"),
                      VIEWER, where="query.workspace_id")
    запрос = str(q or "").strip()
    if not запрос:
        return {"projects": [], "materials": []}
    строки = service.доступные(s, user.id, ws.id)
    settings = настройки(request)
    return {"projects": service.проекты(строки, settings, запрос, limit),
            "materials": service.материалы(строки, settings, запрос, limit)}


__all__ = ["router", "ПОТОЛОК"]
