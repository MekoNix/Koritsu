"""
routes — админка службы: `/api/admin`.

    GET   /api/admin/users            200  люди: план, квота, расход за месяц
    PATCH /api/admin/users/{user_id}  200  сменить план, лимиты, права владельца
    GET   /api/admin/queue            200  очередь: сколько ждёт, слоты, воркеры
    GET   /api/admin/security         200  события безопасности, новые сверху
    GET   /api/admin/stats            200  расход, задания и регистрации по дням

**Не-админ получает `403 forbidden`, а не `404`.** Это исключение из правила
«чужого не существует» (§3), и оно осознанное: `/api/admin` — не чужая строка, а
известный всем адрес, и прятать его бессмысленно, зато `403` честно говорит
вошедшему человеку, что он вошёл правильно, но не туда.

**Ключом сюда нельзя** (§11: аккаунты и админка — только сессией сайта). Ключ
живёт в конфиге скрипта, а админка меняет планы и права.

**Белый список IP — на прокси, а не здесь.** Решение владельца §3: у админки
отдельный origin и доступ по адресу на уровне Caddy. В коде остаётся только
флаг `users.is_admin`, и это не половина работы, а разделение: адрес проверяет
тот, кто видит настоящий адрес соединения, а служба за прокси видит заголовок,
который пишет кто угодно (`accounts.service.client_ip` объясняет, почему).
Ставится флаг руками в базе — маршрута «сделай меня админом» нет и не будет:
его пришлось бы защищать тем самым флагом, которого ещё нет.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field

from ..db import SessionDep
from ..errors import ApiError
from ..workspaces.deps import CurrentUser
from . import service

FORBIDDEN = service.FORBIDDEN


def require_admin(user: CurrentUser) -> object:
    """Зависимость: этот человек — владелец службы, иначе `403 forbidden`.

    Вешается на весь роутер разом (`dependencies=` ниже), а не на маршруты:
    админка, где защищён каждый маршрут, кроме забытого, — это незащищённая
    админка, и забыть тут легче всего при добавлении четвёртой страницы.
    """
    if not getattr(user, "is_admin", False):
        raise ApiError(FORBIDDEN, "Administrator access required", 403)
    return user


router = APIRouter(prefix="/admin", tags=["admin"],
                   dependencies=[Depends(require_admin)])


class UserPatchIn(BaseModel):
    """Тело `PATCH /api/admin/users/{id}`: только то, что владелец и правит.

    Все поля необязательны, и не заданное не трогается: правка «сменить план»
    не должна молча обнулять лимиты, поставленные в прошлый раз.
    """

    plan: str | None = Field(default=None, max_length=32,
                             description="Subscription plan, e.g. free or pro")
    is_admin: bool | None = Field(
        default=None, description="Grant or revoke administrator access")
    limits: dict | None = Field(
        default=None,
        description=("Per-user limit overrides, replaced as a whole; known "
                     "keys: monthly_units, quota_bytes. Empty means defaults."))


@router.get("/users", operation_id="admin_list_users",
            summary="List people with plan, quota and spending",
            description=(
                "Everyone registered, newest first: plan, storage quota and "
                "bytes used, spending in internal units this calendar month. "
                "403 forbidden."))
def люди(request: Request, s: SessionDep,
         limit: int = Query(200, ge=1, le=1000)) -> dict:
    """Список людей. Расход и занятое место считаются, а не хранятся."""
    return {"users": service.люди(s, request.app.state.settings, limit=limit)}


@router.patch("/users/{user_id}", operation_id="admin_patch_user",
              summary="Change plan, limits or administrator access",
              description=(
                  "Changes a person's plan, per-user limit overrides and "
                  "administrator flag. Fields left out are left alone; limits "
                  "are replaced as a whole. 404 not_found, 403 forbidden."))
def поправить(user_id: str, тело: UserPatchIn, request: Request,
              s: SessionDep) -> dict:
    """Сменить план, лимиты и флаг владельца."""
    settings = request.app.state.settings
    from ..jobs.service import расход_за_месяц
    from ..projects import bytes_used

    user = service.поправить(s, user_id, plan=тело.plan,
                             is_admin=тело.is_admin, limits=тело.limits)
    s.flush()
    # Сумма — из общего места (`jobs.service`), и по одному человеку: карточка
    # после правки показывает то же число, что покажут список и `GET /api/usage`.
    расход = расход_за_месяц(s, user_id=user.id).get(user.id, 0)
    return service.карточка_человека(user, settings,
                                     bytes_used=bytes_used(s, settings, user.id),
                                     spent_units=расход)


@router.get("/queue", operation_id="admin_queue",
            summary="Queue state, slots and workers",
            description=(
                "How many jobs wait and run, broken down by kind; the slot "
                "limits this machine runs with; and the workers currently "
                "holding a job, with the age of their last heartbeat. "
                "403 forbidden."))
def очередь(request: Request, s: SessionDep) -> dict:
    """Состояние очереди целиком: это страница «жива ли машина»."""
    return service.очередь(s, request.app.state.settings)


@router.get("/security", operation_id="admin_security_events",
            summary="Security events, newest first",
            description=(
                "Failed logins, account locks, rate limits, refused CSRF and "
                "revoked tokens: when, from which address, about whom. Never "
                "carries passwords, token strings or email addresses. "
                "403 forbidden."))
def события(s: SessionDep,
            kind: str | None = Query(None, max_length=32,
                                     description="Only events of this kind"),
            limit: int = Query(service.СОБЫТИЙ_ПО_УМОЛЧАНИЮ, ge=1,
                               le=service.СОБЫТИЙ_МАКСИМУМ)) -> dict:
    """События безопасности из таблицы — тот же поток, что уходит в stderr."""
    строки = service.события(s, kind=kind, limit=limit)
    return {"events": [service.карточка_события(e) for e in строки]}


@router.get("/stats", operation_id="admin_stats",
            summary="Spending, jobs and registrations over the last days",
            description=(
                "Spending in internal units per day, jobs of the period "
                "broken down by kind with the failed ones counted, "
                "registrations per day and how many people ran anything. "
                "Days are consecutive UTC days, empty ones included. "
                "403 forbidden."))
def сводка(s: SessionDep,
           days: int = Query(service.СВОДКА_ДНЕЙ_ПО_УМОЛЧАНИЮ, ge=1,
                             le=service.СВОДКА_ДНЕЙ_МАКСИМУМ,
                             description="How many days back to count")) -> dict:
    """Ряды для графиков админки. Почему отдельным маршрутом — см. `service.сводка`."""
    return service.сводка(s, days=days)


__all__ = ["router", "require_admin", "UserPatchIn", "FORBIDDEN"]
