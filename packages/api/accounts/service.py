"""
service — вся работа аккаунтов: пароли, токены, сессии, лимиты.

Здесь нет ни одного `@router`: маршруты (`routes.py`) отвечают за форму запроса
и ответа, а всё, что можно сделать неправильно, живёт тут. Разрез не
формальный — он ради того, чтобы правило «пароль проверяется до того, как мы
скажем про подтверждение почты» было записано в одном месте, а не повторялось в
каждом обработчике, который однажды его перепишет.

**Что экспортируется соседям:**

    current_user(request, session) -> User    зависимость: кто пришёл, иначе 401
    CurrentUser                               Annotated-форма для обработчика
    on_user_created                           список хуков «пользователь заведён»

`on_user_created` — то, чем `workspaces` заводит личный workspace. Список
функций, а не вызов `spaces` отсюда: `accounts` не имеет права знать про
workspace (иначе два подпакета связаны в кольцо, и ни один не собирается без
другого). Хук зовут
**внутри той же транзакции**, после `flush` (то есть `user.id` уже есть) и до
коммита: беда в хуке откатывает и регистрацию — пользователь без личного
workspace хуже, чем незарегистрированный пользователь.

    from api.accounts import on_user_created

    def завести_личный(s, user): ...
    on_user_created.append(завести_личный)

**Пароли — argon2id** (`argon2-cffi`, решение плана a5). bcrypt отвергнут в
`requirements.txt` за молчаливый предел в 72 байта: пароль длиннее обрезается, и
две разные длинные фразы открывают один аккаунт.

**Время.** Всё, что прочитано из базы, проходит через `в_utc`: на SQLite колонка
`DateTime(timezone=True)` отдаёт наивное время, и сравнение с `db.now()` падает
`TypeError` (см. докстроку `models.py`).

**Коды бед** (по-английски; их же перечисляет `routes.py`):

    rate_limited          429  лимит регистраций по IP или запертый аккаунт
    invalid_credentials   401  не та почта или не тот пароль
    email_not_confirmed   403  пароль верный, почта не подтверждена
    account_blocked       403  аккаунт заблокирован владельцем службы
    unauthenticated       401  нет годной сессии
    invalid_token         400  токена нет, он чужой или уже использован
    token_expired         400  токен был годен, но протух
    invalid_nickname      422  ник не той длины или не из тех знаков
    nickname_taken        409  такой ник уже занят (без учёта регистра)
"""
from __future__ import annotations

import datetime
import hashlib
import logging
import re
import secrets
from typing import Annotated, Callable

from argon2 import PasswordHasher
from argon2.exceptions import Argon2Error, VerifyMismatchError
from fastapi import Depends, Request, Response
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..db import SessionDep, now
from ..errors import ApiError
from ..settings import Settings
from .models import (CONFIRM, EMAIL_LEN, FAILS_BEFORE_LOCK, IP_LEN,
                     LOCK_MINUTES, NICK_LEN, RESET, UA_LEN, EmailToken,
                     RegistrationAttempt, User, UserSession)

# ── коды бед ─────────────────────────────────────────────────────────────────

RATE_LIMITED = "rate_limited"
INVALID_CREDENTIALS = "invalid_credentials"
EMAIL_NOT_CONFIRMED = "email_not_confirmed"
UNAUTHENTICATED = "unauthenticated"
INVALID_TOKEN = "invalid_token"
TOKEN_EXPIRED = "token_expired"
NICKNAME_TAKEN = "nickname_taken"
INVALID_NICKNAME = "invalid_nickname"
ACCOUNT_BLOCKED = "account_blocked"

# ── сроки ────────────────────────────────────────────────────────────────────

# Сутки на подтверждение и час на сброс. Час, а не сутки: ссылка сброса пароля
# — это вход в аккаунт, и она лежит в чужом почтовом ящике ровно столько,
# сколько живёт. Подтверждению столько жить незачем, а суток хватает человеку,
# который открыл письмо утром следующего дня.
CONFIRM_HOURS = 24
RESET_HOURS = 1

# Продлевать сессию не чаще раза в час. Иначе каждый запрос сайта — это запись
# в базу: на SQLite с одним писателем чтение списка проектов начало бы ждать
# собственную отметку времени.
ПРОДЛЕВАТЬ_НЕ_ЧАЩЕ = datetime.timedelta(hours=1)

COOKIE = "koritsu_session"

# Почта: не проверка на соответствие RFC, а отсев очевидного мусора. Полная
# проверка адреса невозможна в принципе (единственная настоящая — письмо дошло),
# а строгая регулярка отсекает годные адреса и превращается в жалобу.
EMAIL_RE = re.compile(r"\A[^@\s]{1,64}@[^@\s.]+(\.[^@\s.]+)+\Z")

# Пароль: не короче десяти знаков (задание) и не длиннее килобайта. Верхний
# предел — не придирка: argon2 честно хеширует всё, что дали, и мегабайтный
# «пароль» в теле запроса — это отказ обслуживания ценой одного запроса.
PASSWORD_MIN = 10
PASSWORD_MAX = 1024

# Ник: буквы, цифры, `_` и `-`, от двух знаков до тридцати двух. `\w` взят
# вместо перечисления букв намеренно: кириллица разрешена прямо, а список
# «латиница плюс кириллица» отказал бы человеку с любым третьим алфавитом
# ни за что. Подчёркивание входит в `\w` само.
NICK_MIN = 2
NICK_RE = re.compile(r"\A[\w-]+\Z", re.UNICODE)

# ── хук «пользователь заведён» ───────────────────────────────────────────────

on_user_created: list[Callable[[Session, User], None]] = []

# ── журнал событий безопасности (отдельный поток) ────────────────────────────

события = logging.getLogger("api.security")


def событие(request: Request | None, имя: str, **поля) -> None:
    """Записать событие безопасности: отказ входа, лимит, запирание аккаунта.

    Отдельный поток от технического журнала. Что сюда
    **не** попадает: пароль (никогда и ни в каком виде), сам токен, значение
    cookie. Почта тоже не попадает: событие связывается с человеком через UUID
    пользователя, а адрес — это то, что при удалении аккаунта обязано исчезнуть
    (право на забвение), и в журнале безопасности ему делать нечего.

    Обработчик ставится здесь по той же причине, что и в `mail.py`: `log.setup`
    настраивает только свои два потока, а логгер без обработчика молчит.
    """
    _настроить_события()
    rid = getattr(request.state, "request_id", None) if request else None
    хвост = " ".join(f"{k}={v}" for k, v in поля.items())
    события.info("rid=%s event=%s %s", rid or "-", имя, хвост)

    # То же событие — в таблицу `security_events`. Не вместо
    # строки выше, а вместе с ней: поток в stderr забирает сборщик логов и
    # переживает потерю базы, таблицу читает владелец в админке и переживает
    # перезапуск контейнера. Оба пишутся одним вызовом, поэтому разойтись не
    # могут. Импорт внутри функции — круг: `admin` знает про `accounts`.
    from ..admin import service as таблица_событий

    таблица_событий.событие(request, имя, **поля)


def _настроить_события() -> None:
    события.setLevel(logging.INFO)
    if not события.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s"))
        события.addHandler(handler)


# ── время ────────────────────────────────────────────────────────────────────

def в_utc(момент: datetime.datetime | None) -> datetime.datetime | None:
    """Время из базы — со своей зоной.

    SQLite возвращает наивное `datetime` даже из колонки `DateTime(timezone=True)`,
    и `момент < now()` на нём падает `TypeError`. Зона тут не догадка: писал в
    базу только `db.now()`, а он выдаёт UTC.
    """
    if момент is None:
        return None
    if момент.tzinfo is None:
        return момент.replace(tzinfo=datetime.timezone.utc)
    return момент


def сутки_utc() -> str:
    """Сегодняшние сутки строкой `YYYY-MM-DD` — ключ счётчика регистраций."""
    return now().date().isoformat()


# ── пароли ───────────────────────────────────────────────────────────────────

_хешер = PasswordHasher()

# Хеш заведомо несуществующего пароля. Нужен, чтобы вход по незнакомой почте
# занимал столько же времени, сколько по знакомой: без него «нет такого
# пользователя» отвечает мгновенно, а «пароль не тот» — через argon2, и по
# времени ответа перебирается список почт зарегистрированных людей.
_ПУСТЫШКА: str | None = None


def захешировать(пароль: str) -> str:
    """argon2id с умолчаниями библиотеки. Параметры не свои: подобранные на
    глаз параметры хеширования — это либо медленный вход, либо слабый хеш."""
    return _хешер.hash(пароль)


def проверить_пароль(хеш: str, пароль: str) -> bool:
    """Тот ли пароль. Любая беда разбора хеша — «не тот», а не пятисотка:
    испорченная строка в базе не должна пускать внутрь."""
    try:
        return _хешер.verify(хеш, пароль)
    except (VerifyMismatchError, Argon2Error, ValueError):
        return False


def потратить_время_впустую(пароль: str) -> None:
    """Посчитать хеш и выбросить — ради одинакового времени ответа."""
    global _ПУСТЫШКА
    if _ПУСТЫШКА is None:
        _ПУСТЫШКА = _хешер.hash("нет такого пользователя")
    проверить_пароль(_ПУСТЫШКА, пароль)


# ── почта и токены ───────────────────────────────────────────────────────────

def нормальная_почта(сырое: str) -> str:
    """Почта в том виде, в каком она ложится в базу: без краёв, в нижнем
    регистре. Единственный путь к полю `User.email`."""
    return (сырое or "").strip().lower()


def годная_почта(email: str) -> bool:
    """Похоже ли это на адрес. Настоящая проверка одна — письмо дошло."""
    return bool(email) and len(email) <= EMAIL_LEN and bool(EMAIL_RE.match(email))


def новый_токен() -> str:
    """Токен для письма: 32 случайных байта в URL-безопасном виде.

    `secrets`, а не `random`: `random` предсказуем по нескольким выданным
    значениям, то есть токен подтверждения угадывается по своему собственному.
    """
    return secrets.token_urlsafe(32)


def хеш_токена(токен: str) -> str:
    """sha256 в hex. Без соли и без argon2 намеренно: токен — 32 случайных
    байта, перебирать его нечем, а искать строку в базе надо по равенству."""
    return hashlib.sha256(токен.encode("utf-8")).hexdigest()


def выдать_токен(s: Session, user: User, purpose: str) -> str:
    """Завести токен и вернуть его открытым — единственный раз, когда он
    существует открытым. В базе только хеш.

    Прежние неиспользованные токены того же назначения гасятся: два годных
    письма «подтвердите почту» — это два входа в аккаунт вместо одного, и
    старший из них живёт дольше, чем ждал человек.
    """
    часы = CONFIRM_HOURS if purpose == CONFIRM else RESET_HOURS
    s.execute(update(EmailToken)
              .where(EmailToken.user_id == user.id,
                     EmailToken.purpose == purpose,
                     EmailToken.used_at.is_(None))
              .values(used_at=now()))
    токен = новый_токен()
    s.add(EmailToken(user_id=user.id, token_hash=хеш_токена(токен),
                     purpose=purpose,
                     expires_at=now() + datetime.timedelta(hours=часы)))
    return токен


def взять_токен(s: Session, токен: str, purpose: str) -> EmailToken:
    """Найти годный токен или отказать внятно.

    Разница между `invalid_token` и `token_expired` — не педантизм: первому
    интерфейс скажет «ссылка не годится», второму — «попросите новую», и это
    разные кнопки.
    """
    строка = s.scalar(select(EmailToken).where(
        EmailToken.token_hash == хеш_токена(токен or ""),
        EmailToken.purpose == purpose))
    if строка is None or строка.used_at is not None:
        raise ApiError(INVALID_TOKEN, "Token is invalid or already used", 400,
                       where="body.token")
    if (в_utc(строка.expires_at) or now()) < now():
        raise ApiError(TOKEN_EXPIRED, "Token has expired", 400,
                       where="body.token")
    return строка


# ── ник ──────────────────────────────────────────────────────────────────────

def нормальный_ник(сырое: str) -> str:
    """Ник в том виде, в каком его показывают: без пробелов по краям.

    Регистр здесь НЕ трогается намеренно: человек набрал `КириСу` — так его и
    зовут. Приведение для сравнения живёт отдельно (`ключ_ника`), и это разные
    вещи: одно показывают, по другому проверяют занятость.
    """
    return (сырое or "").strip()


def ключ_ника(ник: str) -> str:
    """То, по чему ник сравнивается с чужими: `casefold`, а не `lower`.

    `casefold` — потому что он и есть приведение для сравнения: `lower` не
    сводит немецкое `ß` с `ss`, а в SQLite он к тому же не трогает ничего, кроме
    ASCII. Приводит Python, в базе лежит уже приведённое значение
    (`users.nickname_key`), и уникальный ключ стоит на нём.
    """
    return нормальный_ник(ник).casefold()


def годный_ник(ник: str) -> bool:
    """Буквы, цифры, `_` и `-`, от `NICK_MIN` до `NICK_LEN` знаков."""
    return (NICK_MIN <= len(ник) <= NICK_LEN) and bool(NICK_RE.match(ник))


def проверить_ник(сырое: str, *, where: str = "body.nickname") -> str:
    """Нормализовать ник или отказать `invalid_nickname`.

    Отдельным кодом, а не проверкой формы pydantic: `422 validation_failed`
    говорит «что-то не то с телом», а сайту надо показать под полем «ник может
    состоять из букв, цифр, `_` и `-`». Код различает эти два случая, текст —
    работа интерфейса.
    """
    ник = нормальный_ник(сырое)
    if not годный_ник(ник):
        raise ApiError(INVALID_NICKNAME,
                       "Nickname must be 2-32 letters, digits, _ or -",
                       422, where=where)
    return ник


def ник_занят(s: Session, ключ: str, *, кроме: str | None = None) -> bool:
    """Есть ли уже такой ник у кого-то другого (без учёта регистра).

    Удалённые аккаунты считаются занявшими ник: пока строка в корзине лежит,
    её `nickname_key` держит уникальный ключ базы, и «свободен» здесь означало
    бы отказ на вставке вместо внятного `nickname_taken`.
    """
    запрос = select(User.id).where(User.nickname_key == ключ)
    if кроме:
        запрос = запрос.where(User.id != кроме)
    return s.scalar(запрос) is not None


def требовать_свободный_ник(s: Session, ключ: str, *, кроме: str | None = None,
                            where: str = "body.nickname") -> None:
    """Отказать `nickname_taken`, если ник уже чей-то.

    Отдельной функцией, потому что зовут её из двух мест: регистрация проверяет
    ник до того, как строка появилась (проверять `кроме` там не о чем), а
    правка профиля — исключая себя, иначе человек не мог бы сохранить свой же
    ник, поменяв в нём регистр.

    Проверка в коде, а не один только уникальный ключ базы: ключ отдал бы
    `IntegrityError` и `500`, то есть «служба сломалась» вместо «выберите
    другой ник». Ключ при этом стоит и снимать его нельзя — он ловит гонку
    двух одновременных регистраций, которую проверка в коде не ловит.
    """
    if ник_занят(s, ключ, кроме=кроме):
        raise ApiError(NICKNAME_TAKEN, "This nickname is already taken", 409,
                       where=where)


def занять_ник(s: Session, user: User, сырое: str, *,
               where: str = "body.nickname") -> str:
    """Проверить ник, убедиться, что он свободен, и поставить его человеку.

    Единственный путь к `users.nickname` у уже существующей строки: два пути
    разошлись бы на проверке, и второй однажды положил бы в базу ник, которого
    форма не пропускает.
    """
    ник = проверить_ник(сырое, where=where)
    ключ = ключ_ника(ник)
    требовать_свободный_ник(s, ключ, кроме=user.id, where=where)
    user.nickname = ник
    user.nickname_key = ключ
    return ник


def ник_из_почты(s: Session, email: str) -> str:
    """Придумать свободный ник по почте: `ivan@x.ru` → `ivan`, при столкновении
    — `ivan2`, `ivan3`.

    Нужен там, где ник не спрашивают: аккаунт, заведённый владельцем в админке,
    и старые строки при миграции. Выдумывать что-то более осмысленное службе
    не из чего — имени человека она не хранит, — а оставить поле пустым нельзя:
    ник показывается вместо почты, и пустое место означало бы участника без
    имени.
    """
    основа = "".join(з for з in (email or "").split("@")[0]
                     if NICK_RE.match(з))[:NICK_LEN]
    if len(основа) < NICK_MIN:
        основа = (основа + "user")[:NICK_LEN]
    номер = 1
    пробуем = основа
    while ник_занят(s, ключ_ника(пробуем)):
        номер += 1
        хвост = str(номер)
        пробуем = основа[:NICK_LEN - len(хвост)] + хвост
    return пробуем


# ── пользователи ─────────────────────────────────────────────────────────────

def найти_по_почте(s: Session, email: str) -> User | None:
    """Живой пользователь с этой почтой. Удалённый (`deleted_at`) — не найден:
    аккаунт в корзине не должен ни впускать, ни получать письма."""
    return s.scalar(select(User).where(User.email == email,
                                       User.deleted_at.is_(None)))


def создать_пользователя(s: Session, email: str, пароль: str,
                        ник: str | None = None) -> User:
    """Завести пользователя и позвать хуки.

    `flush` до хуков — не оптимизация: `user.id` до него `None`, а хуку
    пространств нужен именно он, чтобы завести личный workspace на владельца.

    `ник` необязателен, хотя форма регистрации его требует: заводить человека
    умеет не только она (владелец в админке), и обязательный довод заставил бы
    каждого нового вызывающего выдумывать ник самому — то есть по-своему.
    Пустой — берётся из почты (`ник_из_почты`). Проверка и занятость — не
    здесь: их делает `занять_ник` до вызова, чтобы отказ пришёл с адресом поля.
    """
    ник = нормальный_ник(ник) if ник else ник_из_почты(s, email)
    user = User(email=email, password_hash=захешировать(пароль),
                nickname=ник, nickname_key=ключ_ника(ник))
    s.add(user)
    s.flush()
    for хук in on_user_created:
        хук(s, user)
    return user


# ── адрес запроса и лимит регистраций ────────────────────────────────────────

def client_ip(request: Request, settings: Settings) -> str:
    """Адрес, с которого пришёл запрос.

    `X-Forwarded-For` берётся **только** при `settings.trust_proxy`
    (умолчание — «да в prod, нет в dev»). Заголовок этот пишет кто угодно;
    доверять ему на открытом порту значит отдать лимит регистраций по IP тому,
    кто умеет писать заголовки. Обратная крайность — не смотреть на него
    вовсе — за Caddy превращает лимит «5 на адрес» в «5 на весь сайт», потому
    что адрес у всех один: адрес прокси.

    Берётся первый адрес списка: прокси дописывают свои справа, а слева стоит
    тот, кто пришёл. Он же и подделываемый — потому и вся эта настройка.
    """
    if settings.trust_proxy:
        цепочка = request.headers.get("x-forwarded-for", "")
        первый = цепочка.split(",")[0].strip()
        if первый:
            return первый[:IP_LEN]
    клиент = request.client
    return (клиент.host if клиент else "-")[:IP_LEN]


def посчитать_регистрацию(s: Session, request: Request,
                          settings: Settings) -> str:
    """Учесть регистрацию с этого адреса, отказав при превышении.

    Считается **любая** регистрация, включая повторную с уже занятой почтой:
    иначе счётчик обходится тем, что бот шлёт один и тот же адрес — ответ-то
    одинаковый, а строки в базе не прибавляется.
    """
    ip = client_ip(request, settings)
    строка = s.scalar(select(RegistrationAttempt).where(
        RegistrationAttempt.ip == ip, RegistrationAttempt.day == сутки_utc()))
    if строка is None:
        строка = RegistrationAttempt(ip=ip, day=сутки_utc(), count=0)
        s.add(строка)
    if строка.count >= settings.registrations_per_ip_per_day:
        событие(request, "registration_rate_limited", ip=ip)
        raise ApiError(RATE_LIMITED,
                       "Too many registrations from this address today", 429)
    строка.count += 1
    return ip


# ── перебор пароля ───────────────────────────────────────────────────────────

def заперт(user: User) -> bool:
    """Заперт ли аккаунт прямо сейчас."""
    до = в_utc(user.locked_until)
    return до is not None and до > now()


# ── блокировка владельцем ────────────────────────────────────────────────────

def заблокирован(user: User | None) -> bool:
    """Заблокирован ли аккаунт владельцем службы.

    Не то же, что `заперт`: тот замок ставит сама служба за перебор пароля и
    снимает временем, а этот ставит и снимает только владелец в админке.
    """
    return user is not None and getattr(user, "blocked_at", None) is not None


def отказать_заблокированному(user: User | None) -> None:
    """`403 account_blocked`, если аккаунт заблокирован. Иначе — ничего.

    Одна дверь на все три входа: вход по паролю, сессия сайта и ключ `/api/v1`.
    Три отдельные проверки — это три места, где однажды забудут четвёртое, а
    блокировка, действующая на двух входах из трёх, блокировкой не является.

    Код и текст **одни и те же** на всех входах намеренно: сайт показывает по
    коду свой русский текст, и человек, которого не пустили, обязан прочитать
    одно и то же объяснение — вошёл он почтой или пришёл скриптом.
    """
    if заблокирован(user):
        raise ApiError(ACCOUNT_BLOCKED,
                       "This account has been blocked by the administrator",
                       403)


def отметить_неудачу(s: Session, request: Request, user: User) -> None:
    """Счётчик неудач +1, на десятой — замок на четверть часа.

    **Коммит здесь и сразу** — не небрежность, а необходимость: сессия запроса
    (`db.session`) откатывается на любом исключении, а сразу после этой функции
    обработчик бросает `ApiError`. Без коммита счётчик откатился бы вместе с
    отказом, и перебор шёл бы вечно с нулевым счётчиком. Коммитить при этом
    нечего, кроме самого счётчика: до сюда обработчик ничего не записал.
    """
    user.failed_logins = (user.failed_logins or 0) + 1
    if user.failed_logins >= FAILS_BEFORE_LOCK:
        user.locked_until = now() + datetime.timedelta(minutes=LOCK_MINUTES)
        событие(request, "account_locked", user=user.id,
                fails=user.failed_logins)
    else:
        событие(request, "login_failed", user=user.id,
                fails=user.failed_logins)
    s.commit()


def очистить_неудачи(user: User) -> None:
    """Вход удался — счётчик и замок обнуляются. Иначе девять забытых паролей
    за полгода запирают аккаунт на десятой опечатке."""
    user.failed_logins = 0
    user.locked_until = None


# ── сессии ───────────────────────────────────────────────────────────────────

def открыть_сессию(s: Session, user: User, request: Request,
                   settings: Settings) -> UserSession:
    """Завести сессию на 30 дней (`settings.session_days`)."""
    сессия = UserSession(
        user_id=user.id,
        last_seen_at=now(),
        expires_at=now() + datetime.timedelta(days=settings.session_days),
        user_agent=(request.headers.get("user-agent") or "")[:UA_LEN],
        ip=client_ip(request, settings))
    s.add(сессия)
    s.flush()
    return сессия


def cookie_флаги(settings: Settings) -> dict:
    """Флаги cookie сессии.

    * `HttpOnly` — cookie невидим для JavaScript: одна найденная XSS на сайте
      иначе уносит сессии всех, кто в этот момент читал страницу;
    * `SameSite=Lax` — чужой сайт не может послать за пользователя `POST`
      (CSRF); `Strict` не берём: переход по ссылке из письма (подтверждение
      почты) с ним приходит без cookie, и человек видит форму входа сразу после
      того, как вошёл;
    * `Secure` — по настройке `KORITSU_COOKIE_SECURE`, а её умолчание — «да в
      prod, нет в dev»: в dev сайт живёт на `http://localhost`, и cookie с этим
      флагом браузер попросту не сохранит. Настройка заведена ради теста без
      домена: там prod работает по HTTP на IP машины, и
      `Secure` означал бы вход, после которого человек снова видит форму входа.
      При живом HTTPS её трогать не надо;
    * домен **не задаём**: без него cookie принадлежит ровно тому имени, что
      его выдало. `Domain=koritsu.ru` отдал бы сессию любому поддомену, включая
      тот, который однажды заведут под чужую страницу;
    * `path="/"` — сайт и `/api` за одним прокси, cookie нужен обоим.
    """
    return {"httponly": True, "samesite": "lax",
            "secure": bool(settings.cookie_secure), "path": "/"}


def поставить_cookie(response: Response, сессия: UserSession,
                     settings: Settings) -> None:
    response.set_cookie(COOKIE, сессия.id,
                        max_age=settings.session_days * 24 * 3600,
                        **cookie_флаги(settings))


def снять_cookie(response: Response, settings: Settings) -> None:
    """Погасить cookie. Флаги те же, что при выдаче: браузер считает разными
    cookie, у которых разошёлся `path`, — и старая осталась бы жить."""
    флаги = cookie_флаги(settings)
    response.delete_cookie(COOKIE, path=флаги["path"],
                           httponly=флаги["httponly"],
                           samesite=флаги["samesite"], secure=флаги["secure"])


def отозвать_все(s: Session, user: User) -> None:
    """Выход со всех устройств. Одним `UPDATE`, а не по строке: сессий у
    человека десяток, и половина отозванных при беде — худшее из состояний."""
    s.execute(update(UserSession)
              .where(UserSession.user_id == user.id,
                     UserSession.revoked_at.is_(None))
              .values(revoked_at=now()))


def текущая_сессия(request: Request, s: Session) -> UserSession | None:
    """Сессия из cookie, если она есть и годна. Иначе `None` — без исключения:
    это нужно и `logout`, которому всё равно, была ли сессия."""
    ключ = request.cookies.get(COOKIE)
    if not ключ:
        return None
    сессия = s.get(UserSession, ключ)
    if сессия is None or сессия.revoked_at is not None:
        return None
    if (в_utc(сессия.expires_at) or now()) < now():
        return None
    return сессия


def продлить(сессия: UserSession, settings: Settings) -> None:
    """Отодвинуть срок сессии — но не чаще раза в час (`ПРОДЛЕВАТЬ_НЕ_ЧАЩЕ`).

    Продление при каждом запросе означало бы запись в базу на каждое движение
    мышью; раз в час — та же «сессия 30 дней с продлением» с точностью,
    которой человеку хватает.
    """
    видели = в_utc(сессия.last_seen_at) or now()
    if now() - видели < ПРОДЛЕВАТЬ_НЕ_ЧАЩЕ:
        return
    сессия.last_seen_at = now()
    сессия.expires_at = now() + datetime.timedelta(days=settings.session_days)


def current_user(request: Request, s: SessionDep) -> User:
    """Кто пришёл. Нет годной сессии — 401 `unauthenticated`.

    Зависимость, которую берут соседи:

        from api.accounts import CurrentUser

        @router.get("/projects")
        def список(me: CurrentUser, s: SessionDep): ...

    Здесь же выставляется `request.state.user_id` — то самое поле, которое
    `log.py` пишет в технический журнал («id запроса, UUID пользователя»).
    Пока его никто не выставил, в журнале стоит `user=-`.

    **Cookie или Bearer.** Внешний ключ — второй способ
    подтвердить, кто пришёл, и разбирается он здесь, а не вторым
    обработчиком: «обработчик пишется один раз» (`routes`) держится ровно на
    том, что зависимость у обоих входов одна. Сам разбор живёт в `api.auth` —
    там же, где список прав и список входов, куда с ключом нельзя.
    """
    from ..auth import Principal, предъявленный, по_токену

    # Вход `/api/v1` разбирает ключ своей зависимостью и кладёт итог сюда:
    # второй разбор того же заголовка стоил бы второго похода в базу.
    готовый: Principal | None = getattr(request.state, "principal", None)
    if готовый is not None:
        return готовый.user
    строка = предъявленный(request)
    if строка is not None:
        return по_токену(request, s, строка).user

    беда = ApiError(UNAUTHENTICATED, "Authentication required", 401)
    сессия = текущая_сессия(request, s)
    if сессия is None:
        raise беда
    user = s.get(User, сессия.user_id)
    if user is None or user.deleted_at is not None:
        raise беда
    # Блокировка действует на живую сессию, а не только на вход. Сессии
    # заблокированному отзывают там же, где ставят блокировку, — но отзыв
    # спасает лишь от сессий, о которых мы знаем: проверка здесь закрывает и
    # ту, что откроется между отзывом и записью в базу.
    отказать_заблокированному(user)
    продлить(сессия, request.app.state.settings)
    request.state.user_id = user.id
    return user


CurrentUser = Annotated[User, Depends(current_user)]


__all__ = ["on_user_created", "current_user", "CurrentUser", "COOKIE",
           "RATE_LIMITED", "INVALID_CREDENTIALS", "EMAIL_NOT_CONFIRMED",
           "UNAUTHENTICATED", "INVALID_TOKEN", "TOKEN_EXPIRED",
           "CONFIRM_HOURS", "RESET_HOURS", "PASSWORD_MIN", "PASSWORD_MAX",
           "захешировать", "проверить_пароль", "потратить_время_впустую",
           "нормальная_почта", "годная_почта", "новый_токен", "хеш_токена",
           "нормальный_ник", "ключ_ника", "годный_ник", "проверить_ник",
           "ник_занят", "требовать_свободный_ник", "занять_ник",
           "ник_из_почты", "NICKNAME_TAKEN",
           "INVALID_NICKNAME", "NICK_MIN",
           "выдать_токен", "взять_токен", "найти_по_почте",
           "создать_пользователя", "client_ip", "посчитать_регистрацию",
           "заперт", "заблокирован", "отказать_заблокированному",
           "ACCOUNT_BLOCKED",
           "отметить_неудачу", "очистить_неудачи", "открыть_сессию",
           "cookie_флаги", "поставить_cookie", "снять_cookie", "отозвать_все",
           "текущая_сессия", "продлить", "в_utc", "сутки_utc", "событие",
           "события", "CONFIRM", "RESET"]
