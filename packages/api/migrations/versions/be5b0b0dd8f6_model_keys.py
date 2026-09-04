"""model keys — таблица ключей моделей (агент D).

Revision ID: be5b0b0dd8f6
Revises: d89510c0e548
Create Date: 2026-09-03

Одна таблица, `model_keys`: чей ключ, для какого поставщика, шифртекст, четыре
последних знака и отметка отзыва. Самого ключа здесь нет ни в каком столбце —
на диске он лежит зашифрованным секретом сервера (§3, `api/keys/crypto.py`).

Столбцов у материалов нет и не будет: материал адресуется хешем содержимого и
живёт файлом в каталоге проекта (`orchestrator.Project.store`). Строка в базе
была бы вторым списком материалов и разошлась бы с первым на первом же
прерванном разборе.

Индекс один и по паре `(user_id, provider)`: запрос к этой таблице ровно один —
«живой ключ этого человека для этого поставщика». Второй индекс, по одному
`user_id`, SQLite не использовал бы никогда, потому что составной начинается с
того же столбца, — а писать пришлось бы оба.

**Внешнего ключа на `users.id` здесь намеренно нет.** Таблицу `users` заводит
агент B, и объявленный отсюда `ForeignKey` означал бы, что миграции двух агентов
одной ночи требуют друг друга. Ключ с `ON DELETE CASCADE` ставится отдельной
миграцией при сведении веток — и поставить его нужно: §7 обещает при удалении
аккаунта полное удаление всего, что с ним связано, а ключ модели — ровно то, что
не должно пережить своего хозяина.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'be5b0b0dd8f6'
down_revision = 'd89510c0e548'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'model_keys',
        sa.Column('user_id', sa.String(length=36), nullable=False),
        sa.Column('provider', sa.String(length=64), nullable=False),
        sa.Column('ciphertext', sa.String(length=1024), nullable=False),
        sa.Column('last4', sa.String(length=8), nullable=False),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_model_keys')),
    )
    with op.batch_alter_table('model_keys', schema=None) as batch_op:
        batch_op.create_index('ix_model_keys_user_provider',
                              ['user_id', 'provider'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('model_keys', schema=None) as batch_op:
        batch_op.drop_index('ix_model_keys_user_provider')
    op.drop_table('model_keys')
