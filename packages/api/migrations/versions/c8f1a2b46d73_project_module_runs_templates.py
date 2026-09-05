"""Модуль работы, журнал запусков и шаблоны работы.

Три изменения одним куском, потому что это одна вещь: работа перестала быть
папкой с файлами и стала местом, где видно сделанное.

`projects.module` — каким модулем работа делается. Поле, а не догадка: до него
модуль выводили косвенно (есть ли теги шаблона, есть ли запись kadai на томе), и
догадка врала на любой работе, где сделано и то, и другое. Заводится с
`server_default=''`: колонка `NOT NULL` на непустой таблице без умолчания не
добавляется вовсе, а пустая строка и означает «не назначен» — то самое
состояние, в котором находятся все уже заведённые работы.

`project_runs` — журнал запусков: какой модуль, когда, как называется, что
произвёл. Без него карточка работы отвечала только на вопрос «куда можно
пойти», а на работе с двумя схемами это бесполезный ответ. `user_id` с
`ON DELETE SET NULL`, а не `CASCADE`: журнал — свойство работы, и уход человека
из службы не должен стирать историю проекта, которым пользуются другие
участники пространства. Индекс по паре `(project_id, created_at)` — это и есть
единственный запрос к таблице: «журнал этой работы, новые сверху».

`project_templates` — какие бланки приложены к работе. Связка, а не копия
строки: один и тот же DOCX прикладывают к нескольким работам, и второй список
файлов рядом с первым разошёлся бы с ним на первом же удалении. Пара уникальна
— приложить тот же шаблон второй раз означает то же состояние, а не второй
пункт списка.

Revision ID: c8f1a2b46d73
Revises: b2d7c1a54e39
Create Date: 2026-09-05 15:40:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'c8f1a2b46d73'
down_revision = 'b2d7c1a54e39'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('projects', schema=None) as batch_op:
        batch_op.add_column(sa.Column('module', sa.String(length=32),
                                      nullable=False, server_default=''))

    op.create_table(
        'project_runs',
        sa.Column('project_id', sa.String(length=36), nullable=False),
        sa.Column('user_id', sa.String(length=36), nullable=True),
        sa.Column('module', sa.String(length=32), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('n', sa.Integer(), nullable=False),
        sa.Column('artifact_id', sa.String(length=32), nullable=True),
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'],
                                name=op.f('fk_project_runs_project_id_projects'),
                                ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'],
                                name=op.f('fk_project_runs_user_id_users'),
                                ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_project_runs')),
    )
    with op.batch_alter_table('project_runs', schema=None) as batch_op:
        batch_op.create_index('ix_project_runs_project_created',
                              ['project_id', 'created_at'], unique=False)

    op.create_table(
        'project_templates',
        sa.Column('project_id', sa.String(length=36), nullable=False),
        sa.Column('template_id', sa.String(length=36), nullable=False),
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ['project_id'], ['projects.id'],
            name=op.f('fk_project_templates_project_id_projects'),
            ondelete='CASCADE'),
        sa.ForeignKeyConstraint(
            ['template_id'], ['templates.id'],
            name=op.f('fk_project_templates_template_id_templates'),
            ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_project_templates')),
        sa.UniqueConstraint('project_id', 'template_id',
                            name='uq_project_templates_pair'),
    )
    with op.batch_alter_table('project_templates', schema=None) as batch_op:
        batch_op.create_index('ix_project_templates_project',
                              ['project_id', 'created_at'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('project_templates', schema=None) as batch_op:
        batch_op.drop_index('ix_project_templates_project')
    op.drop_table('project_templates')

    with op.batch_alter_table('project_runs', schema=None) as batch_op:
        batch_op.drop_index('ix_project_runs_project_created')
    op.drop_table('project_runs')

    with op.batch_alter_table('projects', schema=None) as batch_op:
        batch_op.drop_column('module')
