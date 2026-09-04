"""a5_merge_accounts_workspaces — свести ветви B и C в одну голову.

Revision ID: d89510c0e548
Revises: 5f7bb4acb03d, 70d001e82586
Create Date: 2026-09-03

Пустая намеренно: слияние ничего не создаёт и не удаляет, оно только говорит
alembic'у, что две ветви от `0001_root` дальше идут вместе.

Почему сделано сейчас, а не агентом E в конце (решение главной сессии
2026-09-03). Как только голов становится две, `db.migrate` перестаёт работать
вовсе: `command.upgrade(cfg, "head")` на двух головах бросает
`Multiple head revisions are present`, а `migrate` зовёт `create_app` — то есть
падает каждый тест, собирающий приложение, и падает он не в той зоне, где
беда. Пока голова одна, ночь идёт; сводить в конце было бы нечего сводить —
работать никто бы не смог.

Отсюда правило для того, кто заводит миграцию следующим (агент D): поднять
чистый временный том до `head` **перед** `--autogenerate`, и тогда его
`down_revision` окажется этой ревизией, а не корнем, — третьей головы не
появится и второго слияния не понадобится.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'd89510c0e548'
down_revision = ('5f7bb4acb03d', '70d001e82586')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
