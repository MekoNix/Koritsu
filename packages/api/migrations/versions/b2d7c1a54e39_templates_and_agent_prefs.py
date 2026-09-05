"""templates и настройки агента в профиле.

Одна таблица и два столбца — один кусок работы: разделы настроек «Шаблоны
отчётов», «Горячие клавиши» и «Агент и модели» делаются вместе с API.

`templates` — DOCX человека, живущий вне проектов (`api.templates`): в строке
имя, размер, число тегов и срез хеша, сами байты на томе. Внешний ключ на
`users.id` с `CASCADE`: удалили аккаунт, значит и его данных нет; файлы с тома
при этом сносит уборка аккаунта, базе про том знать нечего.
Индекс по паре `(user_id, created_at)` — это и есть единственный запрос,
который к таблице ходит: «мои шаблоны, новые сверху».

`users.default_endpoint` и `users.agent_overwrite` — умолчания панели агента
(«Агент и модели» тех же настроек). Пресет хранится **именем**, а не ссылкой на
строку ключа: пресет — это `llm.presets` (`deepseek`, `anthropic`,
`openrouter`), и общий ключ службы строки в базе не имеет вовсе. `NULL` значит
«ничего не выбрано», и это не то же самое, что «выбрано и потом отозвано»:
первое сайт заменяет своим правилом «свой ключ, потом общий», второе — нет.

`agent_overwrite` заводится с `server_default='0'`: колонка `NOT NULL` на
непустой таблице без умолчания не добавляется вовсе, а умолчание «не
переписывать чужое» — то же самое, с которым панель агента работала до сегодня.

`down_revision` — `f5872fd9890d` (ник), единственная голова на момент слияния:
эта миграция создавалась параллельно с ней и с блокировкой аккаунта
(`a1c47b30f5e2`), поэтому цепочка выстроена по факту, а не по
времени написания. Двух голов у службы не бывает: `migrate` зовётся из
`create_app`, и «Multiple head revisions» означало бы, что приложение не
собирается вовсе.

Revision ID: b2d7c1a54e39
Revises: f5872fd9890d
Create Date: 2026-09-05 02:10:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'b2d7c1a54e39'
down_revision = 'f5872fd9890d'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'templates',
        sa.Column('user_id', sa.String(length=36), nullable=False),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('bytes', sa.Integer(), nullable=False),
        sa.Column('tags', sa.Integer(), nullable=False),
        sa.Column('sha256', sa.String(length=32), nullable=False),
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'],
                                name=op.f('fk_templates_user_id_users'),
                                ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_templates')),
    )
    with op.batch_alter_table('templates', schema=None) as batch_op:
        batch_op.create_index('ix_templates_user_created',
                              ['user_id', 'created_at'], unique=False)

    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('default_endpoint', sa.String(length=64),
                                      nullable=True))
        batch_op.add_column(sa.Column('agent_overwrite', sa.Boolean(),
                                      nullable=False, server_default='0'))


def downgrade() -> None:
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('agent_overwrite')
        batch_op.drop_column('default_endpoint')

    with op.batch_alter_table('templates', schema=None) as batch_op:
        batch_op.drop_index('ix_templates_user_created')

    op.drop_table('templates')
