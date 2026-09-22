"""model_keys.model — выбранная модель поставщика.

Один столбец на существующей таблице. Пусто у всех прежних строк, и это
осмысленное значение, а не «не заполнено»: пусто означает умолчание пресета
`llm`, то есть ровно ту модель, которой человек работал до появления выбора.

Столбец рядом с ключом, а не отдельной таблицей, потому что без ключа
поставщик недоступен вовсе и применить выбранную для него модель было бы некуда
(`keys/models.py`).

SQLite умеет `ALTER TABLE ADD COLUMN` с умолчанием, поэтому обходной таблицы
здесь нет. `server_default` остаётся и после заполнения: в `model_keys` пишут не
только через ORM (миграции и проверки кладут строки голым SQL), и столбец
`NOT NULL` без умолчания базы сломал бы им вставку на ровном месте.

Revision ID: a7f31c9b2604
Revises: c5e2b7d91a40
Create Date: 2026-09-22
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'a7f31c9b2604'
down_revision = 'c5e2b7d91a40'
branch_labels = None
depends_on = None

# Копия длины из `keys.models.MODEL_MAX`, а не импорт: миграция применяется той
# версией правил, при которой её написали.
MODEL_MAX = 128


def upgrade() -> None:
    op.add_column('model_keys',
                  sa.Column('model', sa.String(length=MODEL_MAX),
                            nullable=False, server_default=''))


def downgrade() -> None:
    with op.batch_alter_table('model_keys') as batch:
        batch.drop_column('model')
