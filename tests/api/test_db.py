"""
База: миграции, прагмы SQLite и две формы сессии.

Проверяется то, из чего B, C и D будут исходить, не перечитывая каркас.
Особенно две вещи, которые на SQLite не умолчание, а необходимость: без
`PRAGMA foreign_keys=ON` каскадное удаление молча не работает (удалённый
пользователь оставляет висеть свои сессии и проекты), без WAL любая запись
держит весь сайт.
"""
from __future__ import annotations

import os

import pytest
from sqlalchemy import String, text
from sqlalchemy.orm import Mapped, mapped_column

from api import Settings
from api.db import Base, Db, Row, current_revision, migrate


class Проба(Row):
    """Единственная таблица во всём каркасе, и та — только в тестах.

    Заведена ради проверки основы `Row`: идентификатор, две отметки времени.
    В `models.py` пакета её нет намеренно — миграции о ней не знают и знать не
    должны, она создаётся руками тем тестом, которому нужна.
    """

    __tablename__ = "_проба_каркаса"

    имя: Mapped[str] = mapped_column(String(50))


# Убрать пробную таблицу из общих метаданных — иначе «миграции о ней не знают»
# остаётся только обещанием докстроки. Объявление подкласса `Row` записывает
# таблицу в `Base.metadata` само, и в том же процессе `alembic check` (а с ним и
# любой `--autogenerate`, запущенный кодом) видит лишнюю таблицу и требует
# миграцию под неё. Нашлось это агентом E: `tests/api/test_migrations.py`
# гоняет `check` в том же процессе, что и этот файл.
#
# Класс после этого работает по-прежнему: `Проба.__table__` никуда не делся, по
# нему тест и создаёт таблицу руками, а `Проба.metadata` — это тот же объект
# `Base.metadata`, что и был (см. `test_метаданные_одни_на_службу`).
Base.metadata.remove(Проба.__table__)


# ── миграции ─────────────────────────────────────────────────────────────────

def test_миграция_поднимает_пустую_базу(settings):
    """База поднялась до **последней** миграции, какой бы она ни была.

    Сверяется с головой цепочки, а не с `0001_root` (правка агента B, ночь 1):
    корень был последней миграцией ровно до первой таблицы. Записанное в тесте
    имя ревизии означало бы, что каждая новая миграция ломает проверку каркаса,
    и чинить её будет тот, кто про неё ничего не знает.
    """
    from alembic.script import ScriptDirectory

    from api.db import alembic_config

    migrate(settings)
    assert os.path.exists(os.path.join(settings.data_dir, "koritsu.db"))
    голова = ScriptDirectory.from_config(
        alembic_config(settings)).get_current_head()
    assert current_revision(settings) == голова


def test_миграция_повторно_ничего_не_делает(settings):
    """Её зовут при каждом старте приложения — второй раз обязан быть тихим."""
    migrate(settings)
    первая = current_revision(settings)
    migrate(settings)
    assert current_revision(settings) == первая


def test_каталог_тома_заводится_сам(tmp_path):
    """SQLite не создаёт недостающих каталогов, и первый запуск на пустом томе
    падал бы «unable to open database file» — самой невнятной из возможных бед
    о том, что каталога нет."""
    том = tmp_path / "нет" / "такого"
    настройки = Settings.for_tests(том)
    assert not том.exists()
    migrate(настройки)
    assert том.exists()


def test_у_цепочки_один_корень():
    """Три агента заводят миграции параллельно; свести три головы `alembic merge`
    может только при общем предке. Больше одного корня — цепочка, которую
    придётся чинить руками."""
    from alembic.script import ScriptDirectory

    from api.db import MIGRATIONS_DIR

    скрипты = ScriptDirectory(MIGRATIONS_DIR)
    корни = [r for r in скрипты.walk_revisions() if r.down_revision is None]
    assert [r.revision for r in корни] == ["0001_root"]


# ── прагмы SQLite ────────────────────────────────────────────────────────────

def test_внешние_ключи_проверяются(settings):
    """SQLite по умолчанию их не проверяет: без прагмы `ON DELETE CASCADE` —
    украшение, а не поведение."""
    migrate(settings)
    db = Db(settings)
    try:
        with db.engine.connect() as conn:
            assert conn.execute(text("PRAGMA foreign_keys")).scalar() == 1
    finally:
        db.dispose()


def test_журнал_базы_в_режиме_wal(settings):
    """Иначе любой POST держит весь сайт: SQLite в обычном журнале блокирует
    базу целиком."""
    migrate(settings)
    db = Db(settings)
    try:
        with db.engine.connect() as conn:
            assert conn.execute(text("PRAGMA journal_mode")).scalar() == "wal"
    finally:
        db.dispose()


# ── сессия ───────────────────────────────────────────────────────────────────

@pytest.fixture
def db(settings):
    migrate(settings)
    подключение = Db(settings)
    Проба.__table__.create(подключение.engine, checkfirst=True)
    yield подключение
    подключение.dispose()


def test_основа_даёт_идентификатор_и_отметки(db):
    from api.ids import is_id

    with db.session_scope() as s:
        строка = Проба(имя="первая")
        s.add(строка)

    assert is_id(строка.id)                     # uuid4, а не счётчик
    assert строка.created_at is not None
    assert строка.updated_at is not None


def test_session_scope_коммитит_на_выходе(db):
    with db.session_scope() as s:
        s.add(Проба(имя="вторая"))

    with db.session_scope() as s:
        assert s.query(Проба).count() == 1


def test_session_scope_откатывает_на_беде(db):
    """Половина записи хуже, чем её отсутствие: её никто не заметит."""
    with pytest.raises(RuntimeError):
        with db.session_scope() as s:
            s.add(Проба(имя="третья"))
            raise RuntimeError("что-то пошло не так посреди работы")

    with db.session_scope() as s:
        assert s.query(Проба).count() == 0


def test_у_каждого_приложения_своя_база(tmp_path):
    """Движок живёт на приложении, а не в глобальной переменной: иначе два
    приложения в одном процессе (то есть два теста) видят чужие строки."""
    первая = Settings.for_tests(tmp_path / "один")
    вторая = Settings.for_tests(tmp_path / "два")
    assert первая.db_url != вторая.db_url


def test_метаданные_одни_на_службу():
    """Вторая `Base` означала бы, что `--autogenerate` видит половину таблиц, а
    для второй половины выписывает `DROP TABLE`."""
    assert Проба.metadata is Base.metadata
