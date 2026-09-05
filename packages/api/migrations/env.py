"""
env.py — как Alembic узнаёт, куда ходить и с чем сравнивать.

URL берётся из `Settings`, а не из `alembic.ini`: путь тома задаётся снаружи.
Два источника URL — это ровно та беда, ради которой
умолчания у тома нет: миграция, применённая не к той базе, обнаруживается
пустым сайтом.

Настройки приходят двумя путями, и оба нужны:

* `config.attributes["settings"]` — когда миграцию зовёт код
  (`api.db.migrate`, то есть тесты и старт приложения);
* `Settings.from_env()` — когда Alembic зовут из командной строки
  (`alembic revision --autogenerate`), например когда заводят новые таблицы.

`render_as_batch=True` — не украшение. SQLite почти не умеет `ALTER TABLE`:
чтобы поменять тип колонки или снять ограничение, таблицу надо пересоздать и
перелить. Alembic делает это сам в «batch»-режиме; без флага любая правка
существующей колонки падает на выкате, а не в разработке.
"""
from __future__ import annotations

import os
import sys

from alembic import context
from sqlalchemy import engine_from_config, pool

# Пакеты в этом проекте не устанавливаются: импорт идёт
# через `packages/` в пути. Из-под кода это уже сделано (`tests/conftest.py` или
# `PYTHONPATH`), а из-под `alembic` в командной строке — нет, и без этих трёх
# строк CLI не смог бы импортировать `api`.
_ПАКЕТЫ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ПАКЕТЫ not in sys.path:
    sys.path.insert(0, _ПАКЕТЫ)

from api.db import Base, ensure_volume     # noqa: E402
from api.settings import Settings          # noqa: E402
import api.models                          # noqa: E402,F401  (наполняет metadata)

config = context.config

# С чем сравнивать при `--autogenerate`. Метаданные одни на службу; всё, что в
# них не попало (не импортированный модуль моделей), Alembic считает лишним в
# базе — и выписывает удаление таблицы.
target_metadata = Base.metadata

_настройки: Settings = config.attributes.get("settings") or Settings.from_env()
ensure_volume(_настройки)


def run_migrations_offline() -> None:
    """Режим `--sql`: миграции печатаются, а не применяются. Нужен админу
    базы, который хочет посмотреть на SQL до выката."""
    context.configure(url=_настройки.db_url, target_metadata=target_metadata,
                      literal_binds=True, render_as_batch=True,
                      dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Обычный режим: соединиться и применить."""
    section = config.get_section(config.config_ini_section) or {}
    section["sqlalchemy.url"] = _настройки.db_url
    engine = engine_from_config(section, prefix="sqlalchemy.",
                                poolclass=pool.NullPool)
    try:
        with engine.connect() as connection:
            context.configure(connection=connection,
                              target_metadata=target_metadata,
                              render_as_batch=True)
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
