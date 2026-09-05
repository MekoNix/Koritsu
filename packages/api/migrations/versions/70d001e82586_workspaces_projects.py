"""workspaces_projects — пространства, участники, проекты.

Revision ID: 70d001e82586
Revises: 0001_root
Create Date: 2026-09-03

Три таблицы: `workspaces`, `workspace_members`, `projects`. Таблицы аккаунтов
(`users`, `sessions`, `email_tokens`, `registration_attempts`) `--autogenerate`
выписал сюда же — они были в метаданных, но не в базе; из файла они убраны
руками: их заводит миграция аккаунтов, и две миграции, создающие одну таблицу, —
это `table users already exists` на первом же выкате.

Ссылки на `users.id` при этом остались настоящими. Порядок применения двух
ветвей до `alembic merge` не определён, и SQLite это переживает:
внешний ключ на ещё не созданную таблицу проходит при `CREATE TABLE` и начинает
проверяться только на первой вставке — а к тому времени обе миграции применены.

`down_revision` — тот head, что стоял в момент создания (`0001_root`). У
соседних миграций он такой же; получившиеся головы сводит `alembic merge`.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = '70d001e82586'
down_revision = '0001_root'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'workspaces',
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('owner_id', sa.String(length=36), nullable=False),
        sa.Column('personal', sa.Boolean(), nullable=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('purge_after', sa.DateTime(timezone=True), nullable=True),
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['owner_id'], ['users.id'],
                                name=op.f('fk_workspaces_owner_id_users'),
                                ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_workspaces')),
    )
    with op.batch_alter_table('workspaces', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_workspaces_deleted_at'), ['deleted_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_workspaces_owner_id'), ['owner_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_workspaces_purge_after'), ['purge_after'], unique=False)

    op.create_table(
        'workspace_members',
        sa.Column('workspace_id', sa.String(length=36), nullable=False),
        sa.Column('user_id', sa.String(length=36), nullable=False),
        sa.Column('role', sa.String(length=16), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'],
                                name=op.f('fk_workspace_members_user_id_users'),
                                ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'],
                                name=op.f('fk_workspace_members_workspace_id_workspaces'),
                                ondelete='CASCADE'),
        # Составной ключ он же и обещанная уникальность пары: второй записи
        # «этот человек в этом пространстве» не бывает по построению.
        sa.PrimaryKeyConstraint('workspace_id', 'user_id',
                                name=op.f('pk_workspace_members')),
    )

    op.create_table(
        'projects',
        sa.Column('workspace_id', sa.String(length=36), nullable=False),
        sa.Column('owner_id', sa.String(length=36), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('purge_after', sa.DateTime(timezone=True), nullable=True),
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['owner_id'], ['users.id'],
                                name=op.f('fk_projects_owner_id_users'),
                                ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'],
                                name=op.f('fk_projects_workspace_id_workspaces'),
                                ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_projects')),
    )
    with op.batch_alter_table('projects', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_projects_deleted_at'), ['deleted_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_projects_owner_id'), ['owner_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_projects_purge_after'), ['purge_after'], unique=False)
        batch_op.create_index(batch_op.f('ix_projects_workspace_id'), ['workspace_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('projects', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_projects_workspace_id'))
        batch_op.drop_index(batch_op.f('ix_projects_purge_after'))
        batch_op.drop_index(batch_op.f('ix_projects_owner_id'))
        batch_op.drop_index(batch_op.f('ix_projects_deleted_at'))
    op.drop_table('projects')

    op.drop_table('workspace_members')

    with op.batch_alter_table('workspaces', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_workspaces_purge_after'))
        batch_op.drop_index(batch_op.f('ix_workspaces_owner_id'))
        batch_op.drop_index(batch_op.f('ix_workspaces_deleted_at'))
    op.drop_table('workspaces')
