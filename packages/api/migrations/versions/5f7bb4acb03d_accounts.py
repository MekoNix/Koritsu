"""accounts — люди, сессии, токены почты, счётчик регистраций.

Revision ID: 5f7bb4acb03d
Revises: 0001_root
Create Date: 2026-09-03

Четыре таблицы подпакета `api.accounts`; почему именно они — в докстроке
`accounts/models.py`. `down_revision` — корень `0001_root`: у соседних миграций
он такой же, это три головы, и сводит их слияние (см. `alembic merge`), а не
правка чужого
`down_revision` руками.

Внешние ключи `email_tokens.user_id` и `sessions.user_id` стоят с
`ondelete=CASCADE`, и это не украшение: удаление пользователя обязано уносить
его сессии, иначе cookie удалённого человека ссылается на строку, за которой
никого нет. Работает это только при `PRAGMA foreign_keys=ON` — прагму ставит
`db.make_engine` на каждое соединение.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = '5f7bb4acb03d'
down_revision = '0001_root'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('registration_attempts',
    sa.Column('ip', sa.String(length=45), nullable=False),
    sa.Column('day', sa.String(length=10), nullable=False),
    sa.Column('count', sa.Integer(), nullable=False),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_registration_attempts')),
    sa.UniqueConstraint('ip', 'day', name='ip_day')
    )
    with op.batch_alter_table('registration_attempts', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_registration_attempts_ip'), ['ip'], unique=False)

    op.create_table('users',
    sa.Column('email', sa.String(length=320), nullable=False),
    sa.Column('password_hash', sa.String(length=128), nullable=False),
    sa.Column('email_confirmed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('plan', sa.String(length=32), nullable=False),
    sa.Column('totp_secret', sa.String(length=64), nullable=True),
    sa.Column('totp_enabled', sa.Boolean(), nullable=False),
    sa.Column('failed_logins', sa.Integer(), nullable=False),
    sa.Column('locked_until', sa.DateTime(timezone=True), nullable=True),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_users'))
    )
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_users_email'), ['email'], unique=True)

    op.create_table('email_tokens',
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('purpose', sa.String(length=16), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_email_tokens_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_email_tokens'))
    )
    with op.batch_alter_table('email_tokens', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_email_tokens_token_hash'), ['token_hash'], unique=True)
        batch_op.create_index(batch_op.f('ix_email_tokens_user_id'), ['user_id'], unique=False)

    op.create_table('sessions',
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('user_agent', sa.String(length=200), nullable=False),
    sa.Column('ip', sa.String(length=45), nullable=False),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_sessions_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_sessions'))
    )
    with op.batch_alter_table('sessions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_sessions_user_id'), ['user_id'], unique=False)



def downgrade() -> None:
    with op.batch_alter_table('sessions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_sessions_user_id'))

    op.drop_table('sessions')
    with op.batch_alter_table('email_tokens', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_email_tokens_user_id'))
        batch_op.drop_index(batch_op.f('ix_email_tokens_token_hash'))

    op.drop_table('email_tokens')
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_users_email'))

    op.drop_table('users')
    with op.batch_alter_table('registration_attempts', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_registration_attempts_ip'))

    op.drop_table('registration_attempts')
