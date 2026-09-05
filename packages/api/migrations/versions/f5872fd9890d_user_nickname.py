"""user_nickname — ник у пользователя.

Две колонки в `users` и уникальный ключ по одной из них. Имени и фамилии у
аккаунта нет, есть **ник**, и именно он показывается вместо
почты — в приветствии, в меню, в списке участников, в админке.

**Почему колонок две.** Ник обязан быть уникальным без учёта регистра, а
потребовать это от базы можно только ключом по приведённому значению.
Выражение `lower(nickname)` для ключа не годится: `lower()` в SQLite приводит
один ASCII, то есть `Ник` и `ник` остались бы для базы разными строками, — а
кириллица владельцем разрешена прямо. Приводит поэтому Python (`str.casefold`),
а в базе лежит результат: `nickname_key`, и уникальный ключ стоит на нём.
`nickname` хранит написание как есть — показывать `КириСу` как `курису` значит
переименовать человека без его ведома.

**Старые строки.** Ник ставится из почты до `@` (`ivan@x.ru` → `ivan`), при
столкновении — с числом (`ivan2`). Второй возможный путь — оставить `NULL` и
заставить задать ник при первом входе — отвергнут: он стоит целого состояния
«вошёл, но ещё не человек» (маршрут, экран, заслон на каждом другом маршруте),
а тестовых аккаунтов на сегодня десяток, и ник им нужен только затем, чтобы
экран не показывал пустоту. Кому ник из почты не понравится, тот поменяет его в
`/settings/profile` — маршрут для этого есть.

Порядок шагов — тоже не вкус: колонки добавляются **пустыми**, потом
заполняются, и только потом становятся `NOT NULL` с ключом. Добавить `NOT NULL`
сразу нельзя — на таблице с людьми это отказ, а `server_default` поставил бы
всем один и тот же ник, который уникальный ключ тут же и отвергнет.

Правка чужой цепочки здесь ни при чём: `down_revision` — голова на момент
создания (`a1c47b30f5e2`, блокировка аккаунта), миграция
создана на чистом томе, поднятом до head, и голова после неё одна.

Revision ID: f5872fd9890d
Revises: a1c47b30f5e2
Create Date: 2026-09-05
"""
from __future__ import annotations

import re

from alembic import op
import sqlalchemy as sa


revision = 'f5872fd9890d'
down_revision = 'a1c47b30f5e2'
branch_labels = None
depends_on = None

# Границы и знаки ника. Копия `accounts.service`, а не импорт: миграция обязана
# применяться той версией правил, при которой её написали, — иначе завтрашняя
# правка предела длины меняет то, что уже легло в базу вчера.
NICK_MIN = 2
NICK_LEN = 32
ЗНАК = re.compile(r"\A[\w-]\Z", re.UNICODE)

ИМЯ_КЛЮЧА = "ix_users_nickname_key"


def _ник_из_почты(email: str) -> str:
    """`ivan@x.ru` → `ivan`. Знаки не из набора выбрасываются, короткое
    дополняется: `a@x.ru` даёт `auser`, а не однобуквенный ник."""
    основа = "".join(з for з in (email or "").split("@")[0] if ЗНАК.match(з))
    основа = основа[:NICK_LEN]
    if len(основа) < NICK_MIN:
        основа = (основа + "user")[:NICK_LEN]
    return основа


def upgrade() -> None:
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('nickname', sa.String(length=NICK_LEN),
                                      nullable=True))
        batch_op.add_column(sa.Column('nickname_key',
                                      sa.String(length=NICK_LEN),
                                      nullable=True))

    связь = op.get_bind()
    занято: set[str] = set()
    # Порядок по дате: если два адреса дают один ник, число достаётся тому, кто
    # завёлся позже. Иначе номера зависели бы от порядка строк в файле базы.
    строки = связь.execute(sa.text(
        "SELECT id, email FROM users ORDER BY created_at, id")).all()
    for айди, email in строки:
        основа = _ник_из_почты(email or "")
        ник, номер = основа, 1
        while ник.casefold() in занято:
            номер += 1
            хвост = str(номер)
            ник = основа[:NICK_LEN - len(хвост)] + хвост
        занято.add(ник.casefold())
        связь.execute(sa.text("UPDATE users SET nickname = :n, "
                              "nickname_key = :k WHERE id = :i"),
                      {"n": ник, "k": ник.casefold(), "i": айди})

    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.alter_column('nickname',
                              existing_type=sa.String(length=NICK_LEN),
                              nullable=False)
        batch_op.alter_column('nickname_key',
                              existing_type=sa.String(length=NICK_LEN),
                              nullable=False)
        batch_op.create_index(ИМЯ_КЛЮЧА, ['nickname_key'], unique=True)


def downgrade() -> None:
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_index(ИМЯ_КЛЮЧА)
        batch_op.drop_column('nickname_key')
        batch_op.drop_column('nickname')
