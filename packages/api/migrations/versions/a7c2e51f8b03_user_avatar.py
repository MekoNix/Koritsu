"""user_avatar — счётчик замен своей картинки у аккаунта.

Одна колонка: `users.avatar_version`. Ноль — своей картинки нет, аватар рисует
сайт из идентификатора аккаунта; больше нуля — на томе лежит
`users/<uuid>/avatar.png`, и само число уезжает в адрес картинки, чтобы браузер
не показывал прежнюю после замены.

Байты в базу не кладутся: картинка живёт файлом на томе, как материалы и
шаблоны. Строка в базе нужна затем, чтобы «есть ли аватар» отвечалось без
похода на диск — этот вопрос задаётся на каждой загрузке страницы.

`server_default='0'` — ради существующих строк: колонка не пустая, а у
заведённых раньше людей аватара нет.

Revision ID: a7c2e51f8b03
Revises: f3d6a08b5c14
Create Date: 2026-09-05
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'a7c2e51f8b03'
down_revision = 'f3d6a08b5c14'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('users', schema=None) as batch:
        batch.add_column(sa.Column('avatar_version', sa.Integer(),
                                   nullable=False, server_default='0'))


def downgrade() -> None:
    with op.batch_alter_table('users', schema=None) as batch:
        batch.drop_column('avatar_version')
