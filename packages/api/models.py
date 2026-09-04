"""
models — одно место, где пакет узнаёт про все свои таблицы.

Таблиц здесь нет и не будет: тут только импорты модулей B, C и D. Смысл файла в
том, что `Base.metadata` наполняется импортом, а не объявлением. Модуль с
моделями, который никто не импортировал, для Alembic не существует:
`--autogenerate` сравнивает базу с метаданными и, не увидев таблицу в них,
выпишет `DROP TABLE` — то есть удалит живые строки, а не заметит новую модель.

Поэтому правило простое: **завёл модуль с моделями — допиши сюда строку**.
Читают этот файл двое: `migrations/env.py` (перед сравнением схем) и
`app.create_app` (перед первым запросом).

Как это выглядит, когда B, C и D закончат:

    from .accounts.models import *   # noqa: F401,F403  — B: пользователи, сессии
    from .spaces.models import *     # noqa: F401,F403  — C: workspace, проекты
    from .files.models import *      # noqa: F401,F403  — D: материалы, ключи

Порядок строк не важен: SQLAlchemy разрешает ссылки между таблицами по именам,
а не по порядку импорта.
"""
from __future__ import annotations

from .db import Base, Row

# ── сюда B/C/D дописывают свои модули ────────────────────────────────────────
from .accounts.models import *    # noqa: F401,F403  — B: люди, сессии, токены
from .admin.models import *       # noqa: F401,F403  — C5.1: события безопасности
from .jobs.models import *       # noqa: F401,F403  — A5.1: очередь и события
from .tokens.models import *      # noqa: F401,F403  — C5.1: внешние ключи
from .keys.models import *        # noqa: F401,F403  — D: ключи моделей
from .notifications.models import *  # noqa: F401,F403  — B5.1: колокольчик
from .projects.models import *    # noqa: F401,F403  — C: проекты и корзина
from .workspaces.models import *  # noqa: F401,F403  — C: workspace и участники

__all__ = ["Base", "Row"]
