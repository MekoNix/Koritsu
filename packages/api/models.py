"""
models — одно место, где пакет узнаёт про все свои таблицы.

Таблиц здесь нет и не будет: тут только импорты модулей подпакетов. Смысл файла
в том, что `Base.metadata` наполняется импортом, а не объявлением. Модуль с
моделями, который никто не импортировал, для Alembic не существует:
`--autogenerate` сравнивает базу с метаданными и, не увидев таблицу в них,
выпишет `DROP TABLE` — то есть удалит живые строки, а не заметит новую модель.

Поэтому правило простое: **завёл модуль с моделями — допиши сюда строку**.
Читают этот файл двое: `migrations/env.py` (перед сравнением схем) и
`app.create_app` (перед первым запросом).

Как это выглядит:

    from .accounts.models import *   # noqa: F401,F403  — пользователи, сессии
    from .spaces.models import *     # noqa: F401,F403  — workspace, проекты
    from .files.models import *      # noqa: F401,F403  — материалы, ключи

Порядок строк не важен: SQLAlchemy разрешает ссылки между таблицами по именам,
а не по порядку импорта.
"""
from __future__ import annotations

from .db import Base, Row

# ── сюда подпакеты дописывают свои модули ────────────────────────────────────
from .accounts.models import *    # noqa: F401,F403  — люди, сессии, токены
from .admin.models import *       # noqa: F401,F403  — события безопасности
from .jobs.models import *       # noqa: F401,F403  — очередь и события
from .tokens.models import *      # noqa: F401,F403  — внешние ключи
from .keys.models import *        # noqa: F401,F403  — ключи моделей
from .notifications.models import *  # noqa: F401,F403  — колокольчик
from .projects.models import *    # noqa: F401,F403  — проекты и корзина
from .templates.models import *   # noqa: F401,F403  — шаблоны отчётов
from .workspaces.models import *  # noqa: F401,F403  — workspace и участники

__all__ = ["Base", "Row"]
