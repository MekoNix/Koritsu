"""model_keys.user_id → users.id ON DELETE CASCADE

Миграция слияния. Столбец `model_keys.user_id` и таблицу `users` завели разные
миграции, писавшиеся параллельно: объявленный тогда внешний ключ означал бы,
что одна из них не применяется без другой, а её тесты не проходят без чужой
таблицы. Столбец поэтому был заведён готовым к ключу (тот же тип и длина), а
сам ключ отложен до слияния ветвей — то есть до этого файла.

Ставится он не для порядка: удалили аккаунт — удалено всё, что с ним
связано. Без каскада шифртексты ушедшего человека остались бы лежать в базе
строками, у которых больше нет владельца: найти их не по чему, а секретом
сервера они по-прежнему расшифровываются.

`batch_alter_table` — потому что SQLite не умеет `ADD CONSTRAINT`: Alembic
пересоздаёт таблицу и переливает данные (`render_as_batch=True` в `env.py`).
`naming_convention` передаётся сюда же и повторяет `db.NAMING` буквой в букву:
при пересоздании Alembic отражает таблицу из SQLite, где имён у ограничений нет
вовсе, и без соглашения он не смог бы ни назвать новый ключ, ни найти его при
откате. Импортом из `api.db` тут не обойтись: миграция обязана читаться и
применяться той версией кода, при которой её написали, а не той, что окажется в
пакете через год.

revision: c3a71f0d94e6
down_revision: be5b0b0dd8f6
"""
from alembic import op


revision = 'c3a71f0d94e6'
down_revision = 'be5b0b0dd8f6'
branch_labels = None
depends_on = None

# Копия `api.db.NAMING` — см. докстроку о том, почему копия, а не импорт.
СОГЛАШЕНИЕ = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

ИМЯ_КЛЮЧА = "fk_model_keys_user_id_users"


def upgrade() -> None:
    with op.batch_alter_table('model_keys', schema=None,
                              naming_convention=СОГЛАШЕНИЕ) as batch_op:
        batch_op.create_foreign_key(ИМЯ_КЛЮЧА, 'users', ['user_id'], ['id'],
                                    ondelete='CASCADE')


def downgrade() -> None:
    with op.batch_alter_table('model_keys', schema=None,
                              naming_convention=СОГЛАШЕНИЕ) as batch_op:
        batch_op.drop_constraint(ИМЯ_КЛЮЧА, type_='foreignkey')
