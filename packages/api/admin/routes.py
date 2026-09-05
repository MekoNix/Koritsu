"""
routes — админка службы: `/api/admin`.

    GET   /api/admin/users            200  люди: план, квота, расход за месяц
    POST  /api/admin/users            201  завести человека + ссылка сброса
    PATCH /api/admin/users/{user_id}  200  план, лимиты, права, блокировка
    GET   /api/admin/plans            200  справочник планов: потолок и квота
    GET   /api/admin/queue            200  очередь: сколько ждёт, слоты, воркеры
    GET   /api/admin/security         200  события безопасности, новые сверху
    GET   /api/admin/stats            200  расход, задания и регистрации по дням

**Ссылка сброса показывается один раз и только здесь** (писем служба не шлёт).
Она уезжает в ответ `POST /api/admin/users` и больше
нигде не хранится открытой — в базе от неё лежит sha256, как от всякого токена
почты. Владелец передаёт её человеку сам; человек ставит пароль обычным
`/auth/reset`, тем же маршрутом, что и забывший пароль.

**Не-админ получает `403 forbidden`, а не `404`.** Это исключение из правила
«чужого не существует», и оно осознанное: `/api/admin` — не чужая строка, а
известный всем адрес, и прятать его бессмысленно, зато `403` честно говорит
вошедшему человеку, что он вошёл правильно, но не туда.

**Ключом сюда нельзя** (аккаунты и админка — только сессией сайта). Ключ
живёт в конфиге скрипта, а админка меняет планы и права.

**Белый список IP — на прокси, а не здесь.** У админки отдельный origin и
доступ по адресу на уровне Caddy. В коде остаётся только
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
    blocked: bool | None = Field(
        default=None,
        description=("Block or unblock the account. Blocking revokes every "
                     "session; the person is refused with account_blocked at "
                     "sign-in, on the site and with an API token alike."))


class UserCreateIn(BaseModel):
    """Тело `POST /api/admin/users`: кого заводит владелец.

    Пароля здесь нет и быть не может: владелец не придумывает человеку пароль
    и не пересылает его — он передаёт ссылку сброса, а пароль человек ставит
    сам. Ник необязателен: не названный берётся из почты (`ник_из_почты`).
    """

    email: str = Field(max_length=320,
                       description="Email of the person to create")
    plan: str | None = Field(default=None, max_length=32,
                             description="Plan from GET /api/admin/plans")
    nickname: str | None = Field(
        default=None, max_length=128,
        description="Nickname; derived from the email when left out")


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


def _карточка(s, settings, user) -> dict:
    """Карточка одного человека с посчитанными расходом и местом.

    Одной функцией на все три маршрута, которые её отдают: список, создание и
    правка обязаны показывать одно и то же число, а три выкладки по месту
    разошлись бы на первой же новой колонке.
    """
    from ..jobs.service import расход_за_месяц
    from ..projects import bytes_used

    s.flush()
    # Сумма — из общего места (`jobs.service`), и по одному человеку: карточка
    # после правки показывает то же число, что покажут список и `GET /api/usage`.
    расход = расход_за_месяц(s, user_id=user.id).get(user.id, 0)
    return service.карточка_человека(user, settings,
                                     bytes_used=bytes_used(s, settings, user.id),
                                     spent_units=расход)


@router.post("/users", status_code=201, operation_id="admin_create_user",
             summary="Create a person and issue a password reset link",
             description=(
                 "Creates a confirmed account with no password and returns a "
                 "one-time password reset link (reset_url) next to the usual "
                 "person card. The service sends no mail: the administrator "
                 "passes the link on, and the person sets a password through "
                 "the ordinary reset page. The link is shown once and is not "
                 "stored in the clear. 409 email_taken, 409 nickname_taken, "
                 "400 unknown_plan, 422 validation_failed, 403 forbidden."))
def завести(тело: UserCreateIn, request: Request, s: SessionDep) -> dict:
    """Завести человека руками владельца и выдать ему ссылку сброса."""
    settings = request.app.state.settings
    user, ссылка = service.завести_человека(
        s, settings, email=тело.email, plan=тело.plan,
        nickname=тело.nickname, request=request)
    return {"user": _карточка(s, settings, user), "reset_url": ссылка}


@router.patch("/users/{user_id}", operation_id="admin_patch_user",
              summary="Change plan, limits, administrator access or blocking",
              description=(
                  "Changes a person's plan, per-user limit overrides, "
                  "administrator flag and blocking. Fields left out are left "
                  "alone; limits are replaced as a whole. Blocking revokes "
                  "every session of that person. 404 not_found, "
                  "400 unknown_plan, 403 forbidden."))
def поправить(user_id: str, тело: UserPatchIn, request: Request,
              s: SessionDep) -> dict:
    """Сменить план, лимиты, флаг владельца и блокировку."""
    settings = request.app.state.settings
    user = service.поправить(s, user_id, plan=тело.plan,
                             is_admin=тело.is_admin, limits=тело.limits,
                             blocked=тело.blocked, request=request)
    return _карточка(s, settings, user)


@router.get("/plans", operation_id="admin_plans",
            summary="Plans with their monthly ceiling and storage quota",
            description=(
                "The plans this service knows, in order: name, monthly "
                "ceiling in internal units and storage quota in bytes. The "
                "only values PATCH /api/admin/users accepts as a plan. "
                "403 forbidden."))
def планы(request: Request) -> dict:
    """Справочник планов. Числа — из настроек, список — из кода.

    Сколько людей на каком плане, здесь нет намеренно: это вопрос к списку
    людей, и складывать два ответа в один маршрут значило бы пересчитывать всю
    таблицу `users` каждый раз, когда сайту нужны три строки справочника.
    """
    from ..runs.limits import справочник

    return {"plans": справочник(request.app.state.settings)}


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


__all__ = ["router", "require_admin", "UserPatchIn", "UserCreateIn",
           "FORBIDDEN"]
