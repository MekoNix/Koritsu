"""
Таблицы аккаунтов: пользователь, токены почты, сессии, счётчик регистраций.

Четыре таблицы, и три из них существуют потому, что решения владельца §7 иначе
не выполняются:

* **сессии в базе, а не только в подписанном cookie** — иначе «выход со всех
  устройств» невозможен: подписанный cookie на чужом ноутбуке остаётся годным
  до самого срока, отозвать его негде;
* **токены почты — таблицей** и хешами, а не подписью: токен, который нельзя
  отметить использованным, работает столько раз, сколько его перешлют;
* **счётчик регистраций по IP** — в базе, а не в памяти процесса: счётчик в
  памяти обнуляется перезапуском, то есть обходится ожиданием выката.

**Токены хранятся хешем** (`sha256`), как пароли. Причина та же: снимок базы,
попавший не туда, не должен давать вход в чужой аккаунт. Токен подтверждения —
это одноразовый пароль, и хранить его открытым значит хранить открытым пароль.

**Время в SQLite приезжает без зоны.** `DateTime(timezone=True)` на SQLite —
просьба, а не обещание: колонка хранит строку, и обратно приходит наивное
`datetime`. Сравнивать его с `db.now()` (в зоне) нельзя — Python бросает
`TypeError`. Поэтому всё, что прочитано из базы, проходит через
`service.в_utc()`, а не сравнивается напрямую. Хранится при этом UTC — другого
времени `db.now()` не выдаёт.

Почему счётчик неудачных входов лежит **в строке пользователя**, а не отдельной
таблицей: запирается аккаунт, а не запрос, — значит, и жить счётчику там же, где
аккаунт, и очищаться вместе с ним. Отдельная таблица потребовала бы уборки за
удалёнными пользователями и второго места, где «сколько раз ошиблись».
"""
from __future__ import annotations

import datetime

from sqlalchemy import (JSON, Boolean, DateTime, ForeignKey, Integer, String,
                        UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Row

# Длины строк — не украшение: на SQLite они ни на что не влияют, но миграция
# читается человеком, а Postgres (если служба однажды переедет) их применит.
EMAIL_LEN = 320          # 64 + @ + 255, предел из RFC 5321
HASH_LEN = 128           # argon2id укладывается в ~100 знаков
TOKEN_HASH_LEN = 64      # sha256 в hex
IP_LEN = 45              # IPv6 с зоной, самая длинная форма
UA_LEN = 200             # User-Agent режется: полный бывает в килобайт

# Сколько неудач подряд запирают аккаунт и насколько. Десять — не догадка: это
# заведомо больше, чем ошибается человек с раскладкой, и заведомо мало для
# перебора (после десятой попытки перебор идёт со скоростью четыре пароля в час).
FAILS_BEFORE_LOCK = 10
LOCK_MINUTES = 15

# Назначения токена. Одна таблица на два случая, а не две одинаковых: разница
# между ними — только срок жизни и что делать после.
CONFIRM = "confirm"
RESET = "reset"


class User(Row):
    """Пользователь: почта, пароль, подтверждение, план, поля TOTP.

    `email` хранится **нормализованным** (нижний регистр, без пробелов по краям)
    — иначе `Ivan@x.ru` и `ivan@x.ru` заведут два аккаунта, а войти человек
    сможет только в один и не поймёт, в какой. Нормализует
    `service.нормальная_почта`, и другого пути к этому полю нет.

    `plan` — строка, а не таблица подписок: решение владельца §7 «подписку
    включает владелец в админке», а платёжка встанет вебхуком позже. Поле
    заводится сразу, чтобы этот вебхук не потребовал правки модели.

    `totp_secret` и `totp_enabled` — «заложить, интерфейса нет» (§7). Секрет
    хранится как есть: шифровать его тем же `KORITSU_SECRET`, которым
    расшифровывается всё остальное на этой же машине, — защита от того, кто уже
    и так забрал том целиком.

    `deleted_at` — корзина аккаунта (§7: 10 дней, потом полное удаление). Сама
    уборка не здесь: её место рядом с уборкой корзины проектов.
    """

    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(EMAIL_LEN), unique=True,
                                       index=True)
    password_hash: Mapped[str] = mapped_column(String(HASH_LEN))
    email_confirmed_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), default=None)
    plan: Mapped[str] = mapped_column(String(32), default="free")
    # Админ службы (§11: «флаг `is_admin`»). Поле, а не таблица ролей: роль
    # здесь ровно одна, и она у одного человека — владельца. Ставится не через
    # API, а руками в базе (`api.admin` его только читает): маршрут «сделай
    # меня админом» пришлось бы защищать тем же флагом, которого ещё нет.
    # Второй заслон — на прокси, белым списком IP (см. `api/admin/__init__.py`).
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    # Личные лимиты, которые владелец ставит в админке поверх плана и настроек
    # (`PATCH /api/admin/users/{id}`). Мешок JSON, а не колонка на каждый
    # лимит: планы и цены владелец ещё не закрыл, и колонка на лимит означала
    # бы миграцию на каждое его решение. Читают его через
    # `admin.service.лимит(user, ключ, умолчание)` и только через неё — второй
    # читатель разошёлся бы с первым на пустом значении. Ключи, заведённые на
    # сегодня: `monthly_units` (расход модели, агент B), `quota_bytes` (место
    # на томе). Пустой мешок означает «как у всех», а не «ноль».
    limits: Mapped[dict] = mapped_column(JSON, default=dict)
    totp_secret: Mapped[str | None] = mapped_column(String(64), default=None)
    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    # Перебор пароля: счётчик подряд идущих неудач и до какого времени заперто.
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), default=None)
    deleted_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), default=None)


class EmailToken(Row):
    """Одноразовый токен, ушедший в письмо: подтверждение почты или сброс пароля.

    `used_at`, а не удаление строки: использованный токен обязан отличаться от
    несуществующего в журнале — «перешли ссылку второй раз» и «подобрал токен»
    выглядят одинаково, пока строки нет.
    """

    __tablename__ = "email_tokens"

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(TOKEN_HASH_LEN),
                                            unique=True, index=True)
    purpose: Mapped[str] = mapped_column(String(16))
    expires_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True))
    used_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), default=None)


class UserSession(Row):
    """Сессия сайта: то, на что ссылается cookie `koritsu_session`.

    Имя класса не `Session` намеренно: `Session` в этом проекте — сессия
    SQLAlchemy, и два одинаковых имени в одном модуле означали бы, что однажды
    в базу положат не то. Таблица при этом называется `sessions` — снаружи речь
    именно о сессиях пользователя.

    `user_agent` режется до 200 знаков (`UA_LEN`): он нужен человеку, который
    смотрит список своих устройств, а не разбору версий, и килобайтная строка в
    каждой строке таблицы — это база, растущая ни на чём.
    """

    __tablename__ = "sessions"

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True)
    last_seen_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True))
    expires_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True))
    revoked_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), default=None)
    user_agent: Mapped[str] = mapped_column(String(UA_LEN), default="")
    ip: Mapped[str] = mapped_column(String(IP_LEN), default="")


class RegistrationAttempt(Row):
    """Сколько регистраций пришло с этого адреса за эти сутки (§7).

    Сутки — строкой `YYYY-MM-DD` по UTC, а не отметкой времени: так «сколько
    сегодня» — это чтение одной строки по ключу, без арифметики с окном. Старые
    строки убираются вместе с прочей уборкой; пока их некому убирать, они стоят
    по 40 байт в сутки на адрес.
    """

    __tablename__ = "registration_attempts"
    __table_args__ = (UniqueConstraint("ip", "day", name="ip_day"),)

    ip: Mapped[str] = mapped_column(String(IP_LEN), index=True)
    day: Mapped[str] = mapped_column(String(10))
    count: Mapped[int] = mapped_column(Integer, default=0)


__all__ = ["User", "EmailToken", "UserSession", "RegistrationAttempt",
           "CONFIRM", "RESET", "FAILS_BEFORE_LOCK", "LOCK_MINUTES",
           "EMAIL_LEN", "HASH_LEN", "TOKEN_HASH_LEN", "IP_LEN", "UA_LEN"]
