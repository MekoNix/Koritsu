"""user_blocked — колонка `users.blocked_at`.

У админки есть блокировка аккаунта и заведение человека со сбросом пароля.
Блокировку надо где-то хранить, и это единственное, что миграция делает: одна
колонка, отметка времени, `NULL` — не заблокирован.

**Отметка времени, а не флаг.** «Когда заблокировали» — первый вопрос при
разборе жалобы, и хранить ответ второй колонкой рядом с флагом значило бы
завести два поля, одно из которых однажды забудут поставить.

**`NULL` для всех, кто уже есть.** Колонка добавляется nullable без умолчания —
это ровно то, что нужно: незаблокированный аккаунт не отличается от аккаунта,
который никто никогда не блокировал, и заводить для этого отдельное значение
незачем.

Пересечения с миграцией ника нет: поля разные, таблица одна.
Порядок ревизий между ними значения не имеет — обе только добавляют колонку.

Revision ID: a1c47b30f5e2
Revises: eef3027c39f2
Create Date: 2026-09-05
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'a1c47b30f5e2'
down_revision = 'eef3027c39f2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('blocked_at', sa.DateTime(timezone=True),
                                      nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('blocked_at')
