"""
models — что тренажёр помнит о человеке: заходы, попытки, прогресс, настройки.

    cards_session   id, user_id, set_id, version, keys_json, pos, settings_json,
                    started_at, ended_at, created_at, updated_at
    cards_attempt   id, user_id, set_id, card_key, session_id, answer, shown,
                    ms, client_seq, corrects_id, at
    cards_progress  user_id, set_id, card_key, last_answer, yes, no, last_at
    cards_settings  user_id, set_id, settings_json, updated_at

**Содержимое набора — на томе, человек — в базе.** Карточки лежат каноническим
набором в каталоге решения, а всё, что про одного человека, — здесь: эти строки
видны только ему самому, их не видят ни участники пространства, ни автор набора.

**`set_id` — запись журнала набора** (`project_runs.id`) с `ON DELETE CASCADE`:
удаление набора — это удаление его записи, и строки захода, попыток, прогресса
и настроек уходят вместе с ней; уборка работы из корзины сносит записи журнала
тем же каскадом. `user_id` — каскадом от `users`, как остальные данные человека.

**Попытки пишутся с первого дня и не правятся.** Исправление оценки — новая
попытка с `corrects_id` на исправленную, а не правка строки: история ответов
остаётся честной. `UNIQUE(session_id, client_seq)` — идемпотентность повтора
из офлайн-очереди вкладки: тот же ответ, отправленный дважды, — одна строка.

**Прогресс — производное от попыток.** Строка на карточку пересчитывается из
попыток этой карточки после каждого ответа: `last_answer` — ответ последней
неисправленной попытки, `yes`/`no` — счёт неисправленных. Держится он строкой,
а не считается на лету, потому что библиотека наборов спрашивает «сколько я
знаю» по каждому набору пространства разом.
"""
from __future__ import annotations

import datetime

from sqlalchemy import (JSON, Boolean, DateTime, ForeignKey, Index, Integer,
                        String, UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column

from ...db import Base, Row, now
from ...ids import ID_LEN, new_id

# Ключ карточки: id из `{#…}` до 64 знаков или `q:` и 16 hex. С запасом.
KEY_MAX = 80
# `yes` или `no`.
ANSWER_MAX = 3
YES = "yes"
NO = "no"
ANSWERS = (YES, NO)


class CardsSession(Row):
    """Один заход человека по набору: план ключей и сколько из них отвечено."""

    __tablename__ = "cards_session"

    user_id: Mapped[str] = mapped_column(
        String(ID_LEN), ForeignKey("users.id", ondelete="CASCADE"))
    set_id: Mapped[str] = mapped_column(
        String(ID_LEN), ForeignKey("project_runs.id", ondelete="CASCADE"))
    # Версия набора, по которой составлен план. Заход по заменённому набору
    # продолжить нельзя: ключи плана могли уйти из набора.
    version: Mapped[int] = mapped_column(Integer, default=1)
    keys_json: Mapped[list] = mapped_column(JSON, default=list)
    # Сколько ключей плана уже отвечено хотя бы раз.
    pos: Mapped[int] = mapped_column(Integer, default=0)
    settings_json: Mapped[dict] = mapped_column(JSON, default=dict)
    started_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=now)
    ended_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), default=None)

    __table_args__ = (
        Index("ix_cards_session_user_set", "user_id", "set_id"),
    )


class CardsAttempt(Base):
    """Одна оценка карточки. Неизменяемая: написана — и лежит."""

    __tablename__ = "cards_attempt"

    id: Mapped[str] = mapped_column(String(ID_LEN), primary_key=True,
                                    default=new_id)
    user_id: Mapped[str] = mapped_column(
        String(ID_LEN), ForeignKey("users.id", ondelete="CASCADE"))
    set_id: Mapped[str] = mapped_column(
        String(ID_LEN), ForeignKey("project_runs.id", ondelete="CASCADE"))
    card_key: Mapped[str] = mapped_column(String(KEY_MAX))
    session_id: Mapped[str] = mapped_column(
        String(ID_LEN), ForeignKey("cards_session.id", ondelete="CASCADE"))
    answer: Mapped[str] = mapped_column(String(ANSWER_MAX))
    # Был ли показан ответ до оценки.
    shown: Mapped[bool] = mapped_column(Boolean, default=False)
    ms: Mapped[int] = mapped_column(Integer, default=0)
    # Номер ответа во вкладке: по нему повтор из офлайн-очереди узнаётся.
    client_seq: Mapped[int] = mapped_column(Integer)
    corrects_id: Mapped[str | None] = mapped_column(
        String(ID_LEN), ForeignKey("cards_attempt.id", ondelete="SET NULL"),
        default=None)
    at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=now)

    __table_args__ = (
        UniqueConstraint("session_id", "client_seq",
                         name="uq_cards_attempt_session_seq"),
        Index("ix_cards_attempt_user_set", "user_id", "set_id"),
        Index("ix_cards_attempt_user_set_key", "user_id", "set_id", "card_key"),
    )


class CardsProgress(Base):
    """Прогресс человека по одной карточке — пересчитывается из попыток."""

    __tablename__ = "cards_progress"

    user_id: Mapped[str] = mapped_column(
        String(ID_LEN), ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True)
    set_id: Mapped[str] = mapped_column(
        String(ID_LEN), ForeignKey("project_runs.id", ondelete="CASCADE"),
        primary_key=True)
    card_key: Mapped[str] = mapped_column(String(KEY_MAX), primary_key=True)
    last_answer: Mapped[str | None] = mapped_column(String(ANSWER_MAX),
                                                    default=None)
    yes: Mapped[int] = mapped_column(Integer, default=0)
    no: Mapped[int] = mapped_column(Integer, default=0)
    last_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), default=None)

    __table_args__ = (
        Index("ix_cards_progress_user_set", "user_id", "set_id"),
    )


class CardsSettings(Base):
    """Личные настройки захода человека по набору. Нет строки — рекомендуемые."""

    __tablename__ = "cards_settings"

    user_id: Mapped[str] = mapped_column(
        String(ID_LEN), ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True)
    set_id: Mapped[str] = mapped_column(
        String(ID_LEN), ForeignKey("project_runs.id", ondelete="CASCADE"),
        primary_key=True)
    settings_json: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=now, onupdate=now)

    __table_args__ = (
        Index("ix_cards_settings_user_set", "user_id", "set_id"),
    )


__all__ = ["CardsSession", "CardsAttempt", "CardsProgress", "CardsSettings",
           "KEY_MAX", "YES", "NO", "ANSWERS"]
