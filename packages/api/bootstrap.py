"""
bootstrap — один ответ на всё, что сайту нужно для первого экрана.

Страница сайта до этого маршрута начиналась с пяти запросов подряд: кто вошёл,
какие есть модули, сколько осталось за месяц, в каких пространствах человек
состоит и что лежит в колокольчике. Все пять уходили одновременно, каждый
занимал своё соединение, и ни один из них ничего не знал про остальные —
человек с медленным каналом видел оболочку, собирающуюся по частям.

Поэтому здесь один маршрут, отдающий те же пять ответов вместе.

**Вложенные объекты — той же формы, что у отдельных маршрутов, и получены теми
же функциями.** Это не удобство, а единственный способ не завести второй
договор: `me` строит `accounts.routes.профиль`, `usage` — `runs.routes.расход`,
и так далее. Поле, добавленное в карточку пространства, приезжает сюда само;
описать формы заново значило бы получить сайт, которому одно и то же поле
приходит по-разному в зависимости от того, каким запросом он спросил.

Отдельные маршруты при этом остаются и остаться обязаны: сводный ответ нужен
загрузке страницы, а перечитать один расход после задания — это один расход, а
не пять ответов заново.

Наружу (`/api/v1`) маршрут не выставляется: сводка собрана под первый экран
сайта, а внешнему клиенту нужны проекты и задания, а не колокольчик.
"""
from __future__ import annotations

from fastapi import APIRouter, Query, Request

from .db import SessionDep
from .workspaces.deps import CurrentUser

router = APIRouter(tags=["bootstrap"])

# Сколько уведомлений кладётся в сводку по умолчанию. Столько же показывает
# колокольчик: сводка существует затем, чтобы он нарисовался без второго
# запроса, и список короче нужного означал бы этот второй запрос.
УВЕДОМЛЕНИЙ = 20


@router.get("/bootstrap", operation_id="bootstrap",
            summary="Everything the first screen needs, in one answer",
            description=(
                "The signed-in account, the modules the interface may show, "
                "the monthly limit with what is left, the workspaces the "
                "caller belongs to, the newest notifications with the unread "
                "count, and admin_domain: the host the admin area lives on, "
                "or an empty string when it is not split off a subdomain. "
                "Every nested object has exactly the shape its "
                "own route returns, and is built by the very same code; the "
                "separate routes stay for refreshing one thing at a time. "
                "401 unauthenticated."))
def сводка(request: Request, s: SessionDep, user: CurrentUser,
           notifications: int = Query(
               УВЕДОМЛЕНИЙ, ge=1, le=100,
               description="how many newest notifications to include")) -> dict:
    """Всё для первого экрана одним ответом.

    Обработчики зовутся напрямую, а не через сеть: зависимости у них уже
    разрешены здесь (сессия и вошедший — те же самые), а копия их тел была бы
    тем самым вторым договором, ради отсутствия которого маршрут и написан.
    """
    from .accounts.routes import профиль                        # noqa: PLC0415
    from .modules import список_модулей                         # noqa: PLC0415
    from .notifications.routes import список as уведомления      # noqa: PLC0415
    from .runs.routes import расход                             # noqa: PLC0415
    from .workspaces.routes import список as пространства        # noqa: PLC0415

    return {
        "me": профиль(user),
        # Рядом с профилем, а не внутри: имя домена админки — настройка
        # машины, а не поле человека, и список полей карточки закрыт
        # намеренно (`accounts.routes.профиль`). Та же пара, что у
        # `GET /api/auth/me`, — сайт читает её одинаково откуда бы ни спросил.
        "admin_domain": request.app.state.settings.admin_domain,
        "modules": список_модулей(),
        "usage": расход(request, s, user),
        # Массивом, а не `{"workspaces": [...]}`: обёртка отдельного маршрута
        # нужна ему затем, чтобы у тела был корень-объект, а здесь корень уже
        # есть, и вторая обёртка читалась бы как `workspaces.workspaces`.
        "workspaces": пространства(s, user)["workspaces"],
        # А здесь обёртка сохранена: `unread_count` лежит рядом со списком, и
        # без неё число пришлось бы класть отдельным полем сводки — то есть
        # разойтись с формой собственного маршрута.
        "notifications": уведомления(s, user, unread=None,
                                     limit=notifications),
    }


__all__ = ["router", "УВЕДОМЛЕНИЙ"]
