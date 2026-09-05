"""
models — одна таблица: `security_events`, второй журнал службы в базе.

Журналов два — технический (id запроса, UUID пользователя, маршрут, код,
длительность) и **события безопасности** (отказ входа, замок, превышение
лимита, отказ CSRF, отозванный ключ). Сначала второй поток писался только в
`logging`-логгер `api.security`; показывать его надо в админке, а показать
поток, ушедший в stderr контейнера, нельзя — значит, у него появляется таблица.

**Таблица не отменяет логгер, а дублирует его намеренно.** Строки stderr
забирает то, что собирает логи с машины, и они переживают потерю базы; строки
таблицы читает владелец в админке и переживают перезапуск контейнера. Пишутся
оба одним вызовом (`accounts.service.событие`), поэтому разойтись они не могут:
второго места, где событие «отказ входа» превращается в запись, в службе нет.

**`user_id` необязателен и на удалении обнуляется** (`ondelete="SET NULL"`).
При удалении аккаунта журнал с его UUID уходит: для журнала безопасности
остаётся только обезличенная запись. Каскад стёр бы саму запись —
то есть след «с этого адреса ломились в аккаунт» исчез бы вместе с аккаунтом,
чего как раз и добивался бы тот, кто ломился.

**`detail` — JSON без единого обязательного поля.** Форму знает то место, что
пишет событие: у `login_failed` там счётчик неудач, у `rate_limited` — приставка
ключа. Общее правило одно, и оно строгое: **секретов внутри не бывает** — ни
пароля, ни строки токена, ни значения cookie, ни почты (почта — то, что при
удалении аккаунта обязано исчезнуть, и в журнале ей делать нечего). Проверяет
это `service.почистить`, а не обещание в докстроке.

**Наследует `Base`, а не `Row`** — как `jobs.JobEvent`, и по той же причине:
событие написано и больше не меняется, а колонка `updated_at`, которую никто
никогда не тронет, врёт читающему схему.
"""
from __future__ import annotations

import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base, now
from ..ids import ID_LEN, new_id

IP_LEN = 45          # IPv6 с зоной, самая длинная форма (как у `accounts`)
KIND_LEN = 32        # `login_failed`, `csrf_failed`, `token_revoked`

# Виды событий, которые пишет служба. Список открыт (новое место — новое имя),
# но именами из него пользуются и админка, и тесты, поэтому они здесь, а не
# строками по месту: строка, написанная дважды, однажды написана с опечаткой.
LOGIN_FAILED = "login_failed"
ACCOUNT_LOCKED = "account_locked"
# Блокировка владельцем — не то же, что `ACCOUNT_LOCKED`: тот замок ставит
# сама служба за перебор пароля и снимает временем.
ACCOUNT_BLOCKED = "account_blocked"
ACCOUNT_UNBLOCKED = "account_unblocked"
USER_CREATED_BY_ADMIN = "user_created_by_admin"
REGISTRATION_RATE_LIMITED = "registration_rate_limited"
RATE_LIMITED = "rate_limited"
CSRF_FAILED = "csrf_failed"
TOKEN_REVOKED = "token_revoked"


class SecurityEvent(Base):
    """Одно событие безопасности: когда, с какого адреса, что случилось."""

    __tablename__ = "security_events"

    id: Mapped[str] = mapped_column(String(ID_LEN), primary_key=True,
                                    default=new_id)

    # Необязателен: «отказ входа по несуществующей почте» не про пользователя,
    # а про адрес. `SET NULL` — обезличивание при удалении аккаунта, см. выше.
    user_id: Mapped[str | None] = mapped_column(
        String(ID_LEN), ForeignKey("users.id", ondelete="SET NULL"),
        default=None, index=True)

    ip: Mapped[str] = mapped_column(String(IP_LEN), default="")
    kind: Mapped[str] = mapped_column(String(KIND_LEN), index=True)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=now)

    __table_args__ = (
        # Единственный запрос к этой таблице: «последние события, новые
        # сверху», иногда с отбором по виду. Пара, а не два индекса по одному.
        Index("ix_security_events_kind_created", "kind", "created_at"),
    )


__all__ = ["SecurityEvent", "IP_LEN", "KIND_LEN", "LOGIN_FAILED",
           "ACCOUNT_LOCKED", "ACCOUNT_BLOCKED", "ACCOUNT_UNBLOCKED",
           "USER_CREATED_BY_ADMIN", "REGISTRATION_RATE_LIMITED",
           "RATE_LIMITED", "CSRF_FAILED", "TOKEN_REVOKED"]
