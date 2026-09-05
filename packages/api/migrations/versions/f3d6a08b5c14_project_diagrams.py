"""project_diagrams — чем построена сохранённая схема.

Одна таблица: код, язык и параметры отрисовки той схемы, которая уже записана в
журнал запусков работы. Схема сохраняется в работу сама, без кнопки, и человек
возвращается к ней назавтра — значит, вместе с картинкой обязаны храниться
исходник и настройки, иначе «открыть» показывает XML рядом с пустым полем кода.

**Строка привязана к записи журнала, а не к работе.** `run_id` — внешний ключ на
`project_runs` с `ON DELETE CASCADE` и `UNIQUE`: имя, номер, время и модуль у
схемы уже есть там, а удаление схемы — это удаление записи журнала, и снимает
оно обе строки разом. Второго маршрута удаления и второго порядка вызовов,
который однажды переставят местами, при таком ключе не бывает.

Артефакты (XML схемы, JSON исходников) остаются на томе: они адресуются
содержимым и могут стоять значением тега — снести их вслед за строкой значило бы
выбить картинку из готового документа. Место освобождает уборка работы целиком.

Индекса своего у таблицы нет. Спрашивают её двумя способами — по `run_id`
(уникальный ключ, индекс у него уже есть) и соединением с журналом работы, где
отбор идёт по индексу `ix_project_runs_project_created`.

Revision ID: f3d6a08b5c14
Revises: e7a4c19b3d02
Create Date: 2026-09-05
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'f3d6a08b5c14'
down_revision = 'e7a4c19b3d02'
branch_labels = None
depends_on = None

# Копии длин из `modules.models` и `projects.models`, а не импорт: миграция
# применяется той версией правил, при которой её написали.
ID_LEN = 36
PARAM_LEN = 32
ARTIFACT_LEN = 32


def upgrade() -> None:
    op.create_table(
        'project_diagrams',
        sa.Column('run_id', sa.String(length=ID_LEN), nullable=False),
        sa.Column('kind', sa.String(length=PARAM_LEN), nullable=False),
        sa.Column('lang', sa.String(length=PARAM_LEN), nullable=False),
        sa.Column('mode', sa.String(length=PARAM_LEN), nullable=False),
        sa.Column('theme', sa.String(length=PARAM_LEN), nullable=False),
        sa.Column('source_id', sa.String(length=ARTIFACT_LEN), nullable=False),
        sa.Column('id', sa.String(length=ID_LEN), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ['run_id'], ['project_runs.id'],
            name=op.f('fk_project_diagrams_run_id_project_runs'),
            ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_project_diagrams')),
        sa.UniqueConstraint('run_id', name=op.f('uq_project_diagrams_run_id')),
    )


def downgrade() -> None:
    op.drop_table('project_diagrams')
