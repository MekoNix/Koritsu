"""
Маршруты аккаунтов: `/api/auth/…` — вход в службу для человека с браузером.

Роутер без префикса `/api`: его несёт вход сайта (`routes.site`). Внешнего входа
(`/api/v1/`) у аккаунтов нет и не будет — скрипт входит Bearer-токеном, а не
почтой с паролем; токены — работа ночи 2.

    POST /auth/register          201  {"status": "confirmation_sent"}
    POST /auth/confirm           200  {"status": "confirmed"}
    POST /auth/login             200  {"user": {...}} + cookie koritsu_session
    POST /auth/logout            200  {"status": "ok"}
    POST /auth/logout-all        200  {"status": "ok"}
    GET  /auth/me                200  {"user": {...}}
    POST /auth/password/forgot   200  {"status": "reset_sent"}
    POST /auth/password/reset    200  {"status": "password_changed"}

**Что здесь важнее удобства — три правила.**

1. **Ответ регистрации не зависит от того, занята ли почта.** Тело и код —
   одни и те же, буква в букву. Иначе форма регистрации превращается в
   проверялку «есть ли у вас аккаунт на Koritsu», а список почт — в товар.
   По той же причине `/password/forgot` отвечает одинаково всегда.
2. **Пароль проверяется раньше, чем подтверждение почты.** Порядок наоборот
   сообщал бы «такая почта у нас есть, но не подтверждена» кому угодно, кто
   ввёл чужой адрес.
3. **Пароль не уезжает никуда, кроме argon2.** Ни в ответ, ни в журнал, ни в
   событие безопасности; тело запроса не пишет и каркас (`log.py`, §3).

Формы запроса (`RegisterIn`, `LoginIn`, …) названы по-английски, а не как всё
остальное в проекте: их имена уезжают в OpenAPI и становятся именами типов в
клиенте сайта (§5), а `Регистрация` в TypeScript — это имя, которое никто не
наберёт. Всё, что наружу не видно, остаётся по-русски.

**Коды бед** (§7 — коды и тексты по-английски):

    validation_failed    422  не почта, короткий пароль (проверка формы)
    rate_limited         429  лимит регистраций по IP; запертый перебором вход
    invalid_credentials  401  не та почта или не тот пароль
    email_not_confirmed  403  пароль верный, почта не подтверждена
    unauthenticated      401  нет годной сессии (`/me`, `/logout-all`)
    invalid_token        400  токена нет, он чужой или уже использован
    token_expired        400  токен был годен, но протух
"""
from __future__ import annotations

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field, field_validator

from ..db import SessionDep, now
from ..errors import ApiError
from . import mail
from .models import CONFIRM, RESET, User
from .service import (EMAIL_NOT_CONFIRMED, INVALID_CREDENTIALS, PASSWORD_MAX,
                      PASSWORD_MIN, RATE_LIMITED, CurrentUser, в_utc,
                      взять_токен, выдать_токен, годная_почта, заперт,
                      захешировать, найти_по_почте, нормальная_почта,
                      отметить_неудачу, отозвать_все, открыть_сессию,
                      очистить_неудачи, поставить_cookie,
                      посчитать_регистрацию, потратить_время_впустую,
                      проверить_пароль,
                      создать_пользователя, снять_cookie, событие,
                      текущая_сессия)

router = APIRouter(prefix="/auth", tags=["auth"])

# Один и тот же ответ на «завёл нового» и «такая почта уже есть». Константой, а
# не двумя литералами: два литерала разойдутся на первой же правке текста, и
# разойдутся молча — тест на утечку сравнивает ответы целиком.
РЕГИСТРАЦИЯ_ПРИНЯТА = {"status": "confirmation_sent"}
СБРОС_ОТПРАВЛЕН = {"status": "reset_sent"}


# ── формы запроса ────────────────────────────────────────────────────────────

class _Почта(BaseModel):
    """Общее поле: почта приводится к нормальному виду прямо при разборе.

    Нормализация здесь, а не в обработчике, — чтобы к базе не было пути, на
    котором про неё забыли: `Ivan@X.RU ` и `ivan@x.ru` обязаны быть одним
    человеком.
    """

    email: str = Field(max_length=320)

    @field_validator("email")
    @classmethod
    def _почта(cls, значение: str) -> str:
        нормальная = нормальная_почта(значение)
        if not годная_почта(нормальная):
            raise ValueError("Not a valid email address")
        return нормальная


class RegisterIn(_Почта):
    """Регистрация. Длина пароля проверяется формой, а не обработчиком: беда
    формы уезжает клиенту с адресом поля (`where: body.password`)."""

    password: str = Field(min_length=PASSWORD_MIN, max_length=PASSWORD_MAX)


class LoginIn(_Почта):
    """Вход. Длина пароля здесь **не** проверяется: старый пароль может быть
    короче нынешнего предела, и человеку надо дать войти и сменить его."""

    password: str = Field(max_length=PASSWORD_MAX)


class ForgotIn(_Почта):
    pass


class ConfirmIn(BaseModel):
    token: str = Field(max_length=256)


class ResetIn(ConfirmIn):
    password: str = Field(min_length=PASSWORD_MIN, max_length=PASSWORD_MAX)


# ── что мы рассказываем о человеке ───────────────────────────────────────────

def профиль(user: User) -> dict:
    """Пользователь наружу. Список полей закрыт намеренно.

    Чего здесь нет: `password_hash` (очевидно), `totp_secret` (второй фактор,
    отданный клиентом же, вторым фактором быть перестаёт) и `deleted_at`.
    Отдавать модель целиком через `from_attributes` было бы короче ровно до
    того дня, когда в таблицу допишут поле, — и оно уехало бы наружу само.

    `is_admin` здесь есть, и это не послабление. Правом он не заведует: доступ
    в админку решают её маршруты по колонке `users.is_admin` (`admin/routes.py`)
    и белый список адресов на прокси. Поле нужно интерфейсу, чтобы не рисовать
    страницу, за которую всё равно откажут: без него сайт вынужден пробовать
    админский маршрут «на отказ» — то есть просить 403 у каждого вошедшего
    просто чтобы узнать, кто он. Секрета в самом флаге нет: свой собственный
    признак админа человек и так узнаёт, зайдя по адресу.
    """
    return {
        "id": user.id,
        "email": user.email,
        "plan": user.plan,
        "email_confirmed": user.email_confirmed_at is not None,
        "totp_enabled": bool(user.totp_enabled),
        "is_admin": bool(user.is_admin),
        "created_at": (в_utc(user.created_at) or now()).isoformat(),
    }


def _письмо(request: Request, user: User, s, purpose: str) -> None:
    """Выдать токен и отправить письмо со ссылкой (в dev — в журнал).

    Токен существует открытым ровно здесь и уезжает только в письмо: ни в
    ответ, ни в событие безопасности он не попадает.
    """
    settings = request.app.state.settings
    токен = выдать_токен(s, user, purpose)
    отправитель = mail.mailer_for(settings)
    if purpose == CONFIRM:
        ссылка = mail.confirm_link(settings, токен)
        отправитель.send(user.email, mail.CONFIRM_SUBJECT,
                         mail.confirm_body(ссылка))
    else:
        ссылка = mail.reset_link(settings, токен)
        отправитель.send(user.email, mail.RESET_SUBJECT,
                         mail.reset_body(ссылка))


# ── регистрация и подтверждение ──────────────────────────────────────────────

@router.post("/register", status_code=201, operation_id="register",
             summary="Register with email and password",
             description=(
                 "Creates an account and emails a confirmation link. The answer "
                 "is the same whether or not the address is already taken. "
                 "422 validation_failed, 429 rate_limited."))
def register(тело: RegisterIn, request: Request, s: SessionDep) -> dict:
    """Завести аккаунт и отправить письмо с подтверждением.

    Ответ один и тот же во всех трёх случаях — почта свободна, почта занята
    неподтверждённым аккаунтом, почта занята подтверждённым. Разный ответ был
    бы проверялкой чужих адресов (см. правило 1 в докстроке модуля).

    Письмо при этом отправляется не всегда: подтверждённому аккаунту оно
    незачем — человек и так может войти, а «кто-то пробовал зарегистрироваться
    под вашим адресом» этой ночью не пишем (лишний повод для рассылки чужими
    руками).
    """
    посчитать_регистрацию(s, request, request.app.state.settings)

    user = найти_по_почте(s, тело.email)
    if user is None:
        user = создать_пользователя(s, тело.email, тело.password)
        _письмо(request, user, s, CONFIRM)
        событие(request, "registered", user=user.id)
    elif user.email_confirmed_at is None:
        # Письмо потерялось или протухло — шлём ещё раз. Прежний токен при этом
        # гасится (`выдать_токен`): два годных письма — два входа в аккаунт.
        _письмо(request, user, s, CONFIRM)
        событие(request, "register_repeat", user=user.id)
    else:
        событие(request, "register_existing", user=user.id)

    return dict(РЕГИСТРАЦИЯ_ПРИНЯТА)


@router.post("/confirm", operation_id="confirm_email",
             summary="Confirm an email address by token",
             description=(
                 "Confirms an email address by the token from the letter. No "
                 "session cookie is issued: the reader signs in afterwards. "
                 "400 invalid_token, 400 token_expired."))
def confirm(тело: ConfirmIn, request: Request, s: SessionDep) -> dict:
    """Подтвердить почту токеном из письма.

    Cookie здесь не выдаётся намеренно: ссылка из письма открывается в том
    браузере, который первым подвернулся (иногда — во встроенном браузере
    почтовой программы), и вход по факту перехода превращает пересланное письмо
    во вход в аккаунт. Человек подтверждает почту и входит сам.
    """
    токен = взять_токен(s, тело.token, CONFIRM)
    user = s.get(User, токен.user_id)
    if user is None or user.deleted_at is not None:
        raise ApiError("invalid_token", "Token is invalid or already used",
                       400, where="body.token")

    токен.used_at = now()
    if user.email_confirmed_at is None:
        user.email_confirmed_at = now()
    событие(request, "email_confirmed", user=user.id)
    return {"status": "confirmed"}


# ── вход и выход ─────────────────────────────────────────────────────────────

@router.post("/login", operation_id="login",
             summary="Sign in and receive a session cookie",
             description=(
                 "Checks the password and sets the session cookie. "
                 "401 invalid_credentials, 403 email_not_confirmed, "
                 "429 rate_limited."))
def login(тело: LoginIn, request: Request, response: Response,
          s: SessionDep) -> dict:
    """Войти: почта, пароль, подтверждённый аккаунт — и cookie сессии.

    Порядок проверок — часть защиты, а не вкус (см. правила 2 и 3 в докстроке
    модуля): замок перебора, потом пароль, и только потом подтверждение почты.
    """
    settings = request.app.state.settings
    нет = ApiError(INVALID_CREDENTIALS, "Invalid email or password", 401)

    user = найти_по_почте(s, тело.email)
    if user is None:
        # Считаем хеш и выбрасываем: иначе по времени ответа перебирается
        # список зарегистрированных почт, не зная ни одного пароля.
        потратить_время_впустую(тело.password)
        событие(request, "login_unknown_email")
        raise нет

    if заперт(user):
        событие(request, "login_locked", user=user.id)
        raise ApiError(RATE_LIMITED,
                       "Too many failed attempts, try again later", 429)

    if not проверить_пароль(user.password_hash, тело.password):
        отметить_неудачу(s, request, user)
        raise нет

    if user.email_confirmed_at is None:
        # Неудачей входа это не считаем: пароль верный, человек свой, и
        # запирать его аккаунт за неоткрытое письмо не за что.
        событие(request, "login_unconfirmed", user=user.id)
        raise ApiError(EMAIL_NOT_CONFIRMED,
                       "Confirm your email address first", 403)

    очистить_неудачи(user)
    сессия = открыть_сессию(s, user, request, settings)
    поставить_cookie(response, сессия, settings)
    событие(request, "login_ok", user=user.id, session=сессия.id)
    request.state.user_id = user.id
    return {"user": профиль(user)}


@router.post("/logout", operation_id="logout",
             summary="Sign out on this device",
             description=(
                 "Revokes this session and clears the cookie. Needs no "
                 "authentication and answers alike with or without a live "
                 "session."))
def logout(request: Request, response: Response, s: SessionDep) -> dict:
    """Погасить эту сессию и cookie.

    Аутентификации не требует и отвечает одинаково, была сессия или нет:
    «выйти» — действие, которое обязано удаваться всегда, в том числе когда
    сессия уже протухла. Отказ на выходе оставил бы человека с cookie, которую
    нечем убрать.
    """
    сессия = текущая_сессия(request, s)
    if сессия is not None:
        сессия.revoked_at = now()
        событие(request, "logout", user=сессия.user_id, session=сессия.id)
    снять_cookie(response, request.app.state.settings)
    return {"status": "ok"}


@router.post("/logout-all", operation_id="logout_all",
             summary="Sign out on every device",
             description=(
                 "Revokes every session of the signed-in user and clears the "
                 "cookie. 401 unauthenticated."))
def logout_all(me: CurrentUser, request: Request, response: Response,
               s: SessionDep) -> dict:
    """Выход со всех устройств (§7) — то, ради чего сессии лежат в базе."""
    отозвать_все(s, me)
    снять_cookie(response, request.app.state.settings)
    событие(request, "logout_all", user=me.id)
    return {"status": "ok"}


@router.get("/me", operation_id="get_current_user",
            summary="The signed-in user",
            description=(
                "Returns the account behind the session cookie. "
                "401 unauthenticated."))
def whoami(me: CurrentUser) -> dict:
    """Кто вошёл. Первое, что спрашивает сайт при загрузке страницы."""
    return {"user": профиль(me)}


# ── пароль ───────────────────────────────────────────────────────────────────

@router.post("/password/forgot", operation_id="forgot_password",
             summary="Ask for a password reset link",
             description=(
                 "Emails a password reset link. The answer is the same whether "
                 "or not the address is known."))
def forgot(тело: ForgotIn, request: Request, s: SessionDep) -> dict:
    """Отправить письмо со ссылкой сброса.

    Ответ одинаков всегда — есть такая почта или нет (правило 1). Здесь это
    важнее, чем в регистрации: форму «забыли пароль» никто не защищает капчей,
    и разный ответ проверял бы адреса пачками.
    """
    user = найти_по_почте(s, тело.email)
    if user is not None:
        _письмо(request, user, s, RESET)
        событие(request, "password_forgot", user=user.id)
    else:
        событие(request, "password_forgot_unknown")
    return dict(СБРОС_ОТПРАВЛЕН)


@router.post("/password/reset", operation_id="reset_password",
             summary="Set a new password by token",
             description=(
                 "Sets a new password by the token from the letter, revokes "
                 "every session and confirms the address. 400 invalid_token, "
                 "400 token_expired, 422 validation_failed."))
def reset(тело: ResetIn, request: Request, response: Response,
          s: SessionDep) -> dict:
    """Сменить пароль по токену из письма.

    Три вещи делаются заодно, и все три обязательны.

    * **Все сессии отзываются.** Пароль меняют, когда его увели; сессия, взятая
      старым паролем, переживает смену — и смена ничего не даёт.
    * **Почта считается подтверждённой.** Человек прочитал письмо по этому
      адресу — это ровно то, что проверяет подтверждение.
    * **Замок перебора снимается.** Иначе человек, которого только что заперли
      чужие попытки входа, сменил пароль и всё равно не может войти.
    """
    токен = взять_токен(s, тело.token, RESET)
    user = s.get(User, токен.user_id)
    if user is None or user.deleted_at is not None:
        raise ApiError("invalid_token", "Token is invalid or already used",
                       400, where="body.token")

    токен.used_at = now()
    user.password_hash = захешировать(тело.password)
    if user.email_confirmed_at is None:
        user.email_confirmed_at = now()
    очистить_неудачи(user)
    отозвать_все(s, user)
    снять_cookie(response, request.app.state.settings)
    событие(request, "password_reset", user=user.id)
    return {"status": "password_changed"}


__all__ = ["router", "профиль", "РЕГИСТРАЦИЯ_ПРИНЯТА", "СБРОС_ОТПРАВЛЕН"]
