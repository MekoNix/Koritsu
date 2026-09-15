"""cards — заходы, попытки, прогресс и личные настройки тренажёра карточек.

Четыре таблицы, все про одного человека и один набор. Набор — запись журнала
работы (`project_runs`), поэтому `set_id` у всех — внешний ключ на неё с
`ON DELETE CASCADE`: удаление набора и уборка работы из корзины снимают его
строки разом. `user_id` — каскадом от `users`.

`cards_attempt` несёт `UNIQUE(session_id, client_seq)`: ответ, повторённый
офлайн-очередью вкладки, ложится одной строкой. Индексы `(user_id, set_id)` —
под «мой прогресс по набору» и «мои наборы пространства»; у попыток ещё
`(user_id, set_id, card_key)` — под пересчёт прогресса карточки после ответа.

Revision ID: c5e2b7d91a40
Revises: b6d3f0a17c92
Create Date: 2026-09-15
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'c5e2b7d91a40'
down_revision = 'b6d3f0a17c92'
branch_labels = None
depends_on = None

# Копии длин из `modules.cards.models`, а не импорт: миграция применяется той
# версией правил, при которой её написали.
ID_LEN = 36
KEY_MAX = 80
ANSWER_MAX = 3


def upgrade() -> None:
    op.create_table(
        'cards_session',
        sa.Column('user_id', sa.String(length=ID_LEN), nullable=False),
        sa.Column('set_id', sa.String(length=ID_LEN), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('keys_json', sa.JSON(), nullable=False),
        sa.Column('pos', sa.Integer(), nullable=False),
        sa.Column('settings_json', sa.JSON(), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('id', sa.String(length=ID_LEN), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ['user_id'], ['users.id'],
            name=op.f('fk_cards_session_user_id_users'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(
            ['set_id'], ['project_runs.id'],
            name=op.f('fk_cards_session_set_id_project_runs'),
            ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_cards_session')),
    )
    op.create_index('ix_cards_session_user_set', 'cards_session',
                    ['user_id', 'set_id'])

    op.create_table(
        'cards_attempt',
        sa.Column('id', sa.String(length=ID_LEN), nullable=False),
        sa.Column('user_id', sa.String(length=ID_LEN), nullable=False),
        sa.Column('set_id', sa.String(length=ID_LEN), nullable=False),
        sa.Column('card_key', sa.String(length=KEY_MAX), nullable=False),
        sa.Column('session_id', sa.String(length=ID_LEN), nullable=False),
        sa.Column('answer', sa.String(length=ANSWER_MAX), nullable=False),
        sa.Column('shown', sa.Boolean(), nullable=False),
        sa.Column('ms', sa.Integer(), nullable=False),
        sa.Column('client_seq', sa.Integer(), nullable=False),
        sa.Column('corrects_id', sa.String(length=ID_LEN), nullable=True),
        sa.Column('at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ['user_id'], ['users.id'],
            name=op.f('fk_cards_attempt_user_id_users'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(
            ['set_id'], ['project_runs.id'],
            name=op.f('fk_cards_attempt_set_id_project_runs'),
            ondelete='CASCADE'),
        sa.ForeignKeyConstraint(
            ['session_id'], ['cards_session.id'],
            name=op.f('fk_cards_attempt_session_id_cards_session'),
            ondelete='CASCADE'),
        sa.ForeignKeyConstraint(
            ['corrects_id'], ['cards_attempt.id'],
            name=op.f('fk_cards_attempt_corrects_id_cards_attempt'),
            ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_cards_attempt')),
        sa.UniqueConstraint('session_id', 'client_seq',
                            name='uq_cards_attempt_session_seq'),
    )
    op.create_index('ix_cards_attempt_user_set', 'cards_attempt',
                    ['user_id', 'set_id'])
    op.create_index('ix_cards_attempt_user_set_key', 'cards_attempt',
                    ['user_id', 'set_id', 'card_key'])

    op.create_table(
        'cards_progress',
        sa.Column('user_id', sa.String(length=ID_LEN), nullable=False),
        sa.Column('set_id', sa.String(length=ID_LEN), nullable=False),
        sa.Column('card_key', sa.String(length=KEY_MAX), nullable=False),
        sa.Column('last_answer', sa.String(length=ANSWER_MAX), nullable=True),
        sa.Column('yes', sa.Integer(), nullable=False),
        sa.Column('no', sa.Integer(), nullable=False),
        sa.Column('last_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ['user_id'], ['users.id'],
            name=op.f('fk_cards_progress_user_id_users'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(
            ['set_id'], ['project_runs.id'],
            name=op.f('fk_cards_progress_set_id_project_runs'),
            ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('user_id', 'set_id', 'card_key',
                                name=op.f('pk_cards_progress')),
    )
    op.create_index('ix_cards_progress_user_set', 'cards_progress',
                    ['user_id', 'set_id'])

    op.create_table(
        'cards_settings',
        sa.Column('user_id', sa.String(length=ID_LEN), nullable=False),
        sa.Column('set_id', sa.String(length=ID_LEN), nullable=False),
        sa.Column('settings_json', sa.JSON(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ['user_id'], ['users.id'],
            name=op.f('fk_cards_settings_user_id_users'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(
            ['set_id'], ['project_runs.id'],
            name=op.f('fk_cards_settings_set_id_project_runs'),
            ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('user_id', 'set_id',
                                name=op.f('pk_cards_settings')),
    )
    op.create_index('ix_cards_settings_user_set', 'cards_settings',
                    ['user_id', 'set_id'])


def downgrade() -> None:
    op.drop_index('ix_cards_settings_user_set', table_name='cards_settings')
    op.drop_table('cards_settings')
    op.drop_index('ix_cards_progress_user_set', table_name='cards_progress')
    op.drop_table('cards_progress')
    op.drop_index('ix_cards_attempt_user_set_key', table_name='cards_attempt')
    op.drop_index('ix_cards_attempt_user_set', table_name='cards_attempt')
    op.drop_table('cards_attempt')
    op.drop_index('ix_cards_session_user_set', table_name='cards_session')
    op.drop_table('cards_session')
