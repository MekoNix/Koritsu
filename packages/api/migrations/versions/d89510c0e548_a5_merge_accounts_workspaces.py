"""a5_merge_accounts_workspaces — свести две ветви в одну голову.

Revision ID: d89510c0e548
Revises: 5f7bb4acb03d, 70d001e82586
Create Date: 2026-09-03

Пустая намеренно: слияние ничего не создаёт и не удаляет, оно только говорит
alembic'у, что две ветви от `0001_root` дальше идут вместе.

Почему слияние сделано сразу, а не в конце. Как только голов становится две,
`db.migrate` перестаёт работать вовсе: `command.upgrade(cfg, "head")` на двух
головах бросает `Multiple head revisions are present`, а `migrate` зовёт
`create_app` — то есть падает каждый тест, собирающий приложение, и падает он
не там, где беда. Пока голова одна, работа идёт; отложенное слияние остановило
бы всех сразу.

Отсюда правило для того, кто заводит миграцию следующим: поднять
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
