"""member_status — состояние участия в рабочем пространстве.

Одна колонка в `workspace_members`: `active` у участника, `pending` у
позванного, который ещё не ответил. Приглашение перестало зачислять человека
молча — оно приходит уведомлением с кнопками «принять» и «отклонить», а до
ответа пространства для приглашённого не существует.

**Умолчание — `active`, и оно стоит на стороне базы.** Все строки, что уже
лежат в таблице, — это принятые участия: до этой миграции другого состояния не
было. `server_default` заодно избавляет от отдельного `UPDATE`: колонка
добавляется сразу `NOT NULL` и сразу заполненной.

**`server_default` остаётся и после заполнения.** Убирать его пришлось бы
пересборкой таблицы на SQLite, а вреда от него нет: `status` всегда пишется
явно (`workspaces/routes.py`), и умолчание базы — страховка, а не источник
значения.

Индекса по колонке нет намеренно. Спрашивают её вместе с `user_id` или
`workspace_id`, а те уже в первичном ключе; отдельный индекс по полю с двумя
значениями не сузил бы выборку ни на строку.

Revision ID: e7a4c19b3d02
Revises: c8f1a2b46d73
Create Date: 2026-09-05
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'e7a4c19b3d02'
down_revision = 'c8f1a2b46d73'
branch_labels = None
depends_on = None

# Копия `workspaces.models.STATUS_MAX` и `service.ACTIVE`, а не импорт: миграция
# применяется той версией правил, при которой её написали.
STATUS_MAX = 16
ACTIVE = "active"


def upgrade() -> None:
    with op.batch_alter_table('workspace_members', schema=None) as batch_op:
        batch_op.add_column(sa.Column('status', sa.String(length=STATUS_MAX),
                                      nullable=False, server_default=ACTIVE))


def downgrade() -> None:
    with op.batch_alter_table('workspace_members', schema=None) as batch_op:
        batch_op.drop_column('status')
