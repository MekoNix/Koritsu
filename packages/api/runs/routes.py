"""
routes — `GET /api/usage`: сколько положено за месяц и сколько потрачено.

    GET /api/usage    200  план, потолок, расход, остаток, месяц и цены видов

Один маршрут и без параметров: расход — свойство человека, а не запроса.
Чужой расход не показывается никому и никак; админке для этого
предназначена своя дверь, и брать её через этот маршрут с `?user_id=` было бы
ровно тем разъездом двух правил доступа, от которого служба и отделена на два
входа.

Цифры отдаются во **внутренних единицах** («расход наружу во внутренних
единицах»), а не в деньгах: цены поставщиков лежат снимком в журнале каждого
вызова и меняются, а «сколько мне осталось работы» человек должен читать одним
числом, которое не пересчитывается задним числом.

Вместе с остатком уезжают и **цены видов заданий**: расход считается за
запуски нашего кода, и «сколько это стоит» — вопрос, который человек задаёт
перед нажатием кнопки, а не после отказа. Здесь же, а не отдельным маршрутом:
остаток без цены и цена без остатка одинаково бесполезны, а два запроса на один
экран — это два способа увидеть их рассогласованными.
"""
from __future__ import annotations

from fastapi import APIRouter, Request

from ..db import SessionDep
from ..workspaces.deps import CurrentUser
from . import limits

router = APIRouter(prefix="/usage", tags=["usage"])


@router.get("", operation_id="get_usage",
            summary="Your monthly limit and what you have spent",
            description=(
                "The plan, its monthly cap in internal units, what you have "
                "spent since the first of the month and what is left, plus "
                "what one job of each kind costs. A job is refused with "
                "402 limit_exhausted once its price no longer fits into what "
                "is left."))
def расход(request: Request, s: SessionDep, user: CurrentUser) -> dict:
    """План, потолок, расход за календарный месяц, остаток и цены видов."""
    settings = request.app.state.settings
    return {**limits.расход(s, settings, user).наружу(),
            "prices": limits.цены(settings)}


__all__ = ["router"]
