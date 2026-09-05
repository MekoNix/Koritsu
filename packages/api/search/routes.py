"""
routes — `/api/search`: одна строка запроса, два списка в ответ.

    GET /api/search?q=сорти&limit=20   200  {"projects": [...], "materials": [...]}

Право — вошедший, и никакого пространства в параметрах: ищут именно затем,
чтобы не помнить, в каком пространстве работа лежит. Отбор доступа при этом
никуда не девается — он в `service.доступные`: чужая работа не находится, даже
если человек угадал её имя дословно.

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
"""
from __future__ import annotations

from fastapi import APIRouter, Query, Request

from ..db import SessionDep
from ..settings import Settings
from ..workspaces.deps import CurrentUser
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
            summary="Find a project or a material by name",
            description=(
                "Searches the names of every project the caller can reach "
                "(both the workspaces they own and the ones they were invited "
                "to) and the names of the materials inside those projects. "
                "Matching is case-insensitive and by substring, and the trash "
                "is not searched. Answers two lists, at most 20 entries each; "
                "an empty query answers two empty lists rather than everything. "
                "Each project carries the module its work belongs to, so the "
                "caller knows which screen to open."))
def найти(request: Request, s: SessionDep, user: CurrentUser,
          q: str = Query("", max_length=200,
                         description="What to look for, a substring of a name"),
          limit: int = Query(ПОТОЛОК, ge=1, le=ПОТОЛОК,
                             description="Max entries in each list")) -> dict:
    """Работы и файлы, в именах которых есть набранное."""
    запрос = str(q or "").strip()
    if not запрос:
        return {"projects": [], "materials": []}
    строки = service.доступные(s, user.id)
    settings = настройки(request)
    return {"projects": service.проекты(строки, settings, запрос, limit),
            "materials": service.материалы(строки, settings, запрос, limit)}


__all__ = ["router", "ПОТОЛОК"]
