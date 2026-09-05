"""
models — таблица ключей моделей.

Одна таблица: `model_keys`. Строка — «этот человек дал нам этот ключ вот для
этого поставщика», и главное её свойство в том, чего в ней нет: **самого ключа**.
На диске лежит шифртекст (`crypto.py`) и четыре последних знака для человека;
всё остальное — `provider`, кто и когда — открыто и нужно, чтобы показать список
и найти нужный ключ, не расшифровывая ни одного.

**Отзыв, а не удаление.** `revoked_at` вместо `DELETE`, потому что отозванный
ключ — это событие безопасности («ключ утёк, я его сменил»), и запись о нём
переживает саму строку. Расшифровка отозванного не делается никогда
(`service.secret_for` его не видит), так что оставшийся шифртекст не работает, а
рассказывает: тогда-то был заведён, тогда-то отозван.

**Внешний ключ на `users.id` с `ON DELETE CASCADE`.** Пока таблицы писались
параллельно, его здесь намеренно не было: таблицу `users` заводит другая
миграция, и объявленный отсюда `ForeignKey` означал бы, что две миграции
требуют друг друга. После слияния ветвей ключ поставлен (миграция
`c3a71f0d94e6_model_keys_user_fk`), и поставлен он не для порядка: при удалении
аккаунта удаляется всё, что с ним связано, а без каскада
шифртексты ушедшего человека остались бы лежать на томе навсегда — строками, до
которых уже никому не добраться, потому что владельца больше нет.
"""
from __future__ import annotations

import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Row
from ..ids import ID_LEN

# Длина имени поставщика: это имя пресета `llm.presets`, а не свободный текст.
PROVIDER_MAX = 64

# Шифртекст Fernet на ключе поставщика: base64 от «версия + метка времени +
# IV + шифр + HMAC». Для ключей длиной в сотню знаков это сотни байт; 1024 — с
# запасом на длинные ключи и на смену схемы шифрования.
CIPHERTEXT_MAX = 1024


class ModelKey(Row):
    """Ключ поставщика, принадлежащий человеку.

    `id`, `created_at`, `updated_at` — от `Row` (uuid4 наружу, `ids.py`).
    """

    __tablename__ = "model_keys"

    # Без `index=True`: индекс по паре ниже начинается с этого же столбца, и
    # второй, по одному, SQLite не использовал бы никогда — только писал бы.
    # `CASCADE`: удалили аккаунт, значит и ключей его нет.
    user_id: Mapped[str] = mapped_column(
        String(ID_LEN), ForeignKey("users.id", ondelete="CASCADE"))

    # Имя пресета из `llm.presets` (deepseek, anthropic, openrouter), а не имя
    # компании: ключ привязан к endpoint'у, а у одной компании их бывает
    # несколько. Список закрыт и проверяется в `service.PROVIDERS`.
    provider: Mapped[str] = mapped_column(String(PROVIDER_MAX))

    # Шифртекст с версией схемы впереди (`v1:…`). Читается только
    # `crypto.расшифровать`, и только из `service.secret_for`.
    ciphertext: Mapped[str] = mapped_column(String(CIPHERTEXT_MAX))

    # Последние четыре знака — единственное, что видит человек.
    last4: Mapped[str] = mapped_column(String(8), default="")

    revoked_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), default=None)

    # Искать всегда одинаково: «живой ключ этого человека для этого
    # поставщика». Индекс по паре, а не два по одному, потому что запрос один.
    __table_args__ = (
        Index("ix_model_keys_user_provider", "user_id", "provider"),
    )

    @property
    def active(self) -> bool:
        return self.revoked_at is None

    def to_dict(self) -> dict:
        """Наружу. Ни `ciphertext`, ни `user_id`: первое — секрет, второе клиент
        и так про себя знает, а в чужом ответе ему делать нечего."""
        return {
            "id": self.id,
            "provider": self.provider,
            "last4": self.last4,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "revoked_at": self.revoked_at.isoformat() if self.revoked_at else None,
        }


__all__ = ["ModelKey", "PROVIDER_MAX", "CIPHERTEXT_MAX"]
