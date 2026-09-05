"""
db — база службы: движок, сессии, общая основа таблиц и миграции.

Здесь нет ни одной таблицы, и это не заготовка «на потом»: таблицы заводят
подпакеты — аккаунты и сессии, workspace с проектами и корзиной, материалы и
ключи, — каждый в своём модуле. Общее у них ровно то, что лежит тут, — и лежит
один раз, потому что вторая `Base` в проекте означает две метаданных, из которых
`--autogenerate` видит одну и молча выписывает `DROP TABLE` для чужой.

**SQLite**: второй сервер, если появится, — исполнитель
задач без своей базы, так что Postgres не нужен. Отсюда две настройки, которые
на SQLite не умолчание, а необходимость:

* `PRAGMA foreign_keys=ON` — SQLite **по умолчанию не проверяет внешние ключи**.
  Без прагмы `ON DELETE CASCADE` не сработает, и удаление пользователя оставит
  его сессии и проекты висеть на несуществующем владельце. Прагма ставится на
  каждое соединение: она соединения не переживает;
* `PRAGMA journal_mode=WAL` — читатель не ждёт писателя. Без него любой
  `POST` держит весь сайт: SQLite в обычном журнале блокирует базу целиком.

**Как подпакеты добавляют свои модели**

Модель — подкласс `Row` (`id`, `created_at`, `updated_at` уже есть) в своём
модуле пакета. Пять строк целиком:

    # packages/api/accounts/models.py
    from sqlalchemy.orm import Mapped, mapped_column
    from ..db import Row

    class User(Row):
        __tablename__ = "users"
        email: Mapped[str] = mapped_column(unique=True)

Модуль с моделями обязан быть **импортирован к моменту миграции** — иначе
`Base.metadata` его не знает, и `--autogenerate` выпишет пустую миграцию (а на
следующем прогоне — `DROP TABLE`, если таблица уже создана руками). Место для
импорта одно: `models.py` пакета (`from .accounts.models import *`). Его и
читает `migrations/env.py`.

`Row` даёт `id` строкой uuid4 (`ids.new_id`) — это и есть форма
идентификатора наружу; таблице-связке (workspace × пользователь) он не нужен,
такая наследует `Base` напрямую и объявляет составной ключ.

**Как добавляют миграции**

Один файл миграции на подпакет, не больше: два файла об одном и том же — это
две ветки, которые придётся сливать. Порядок:

    PYTHONPATH=packages KORITSU_DATA_DIR=/tmp/koritsu-mig \\
      KORITSU_SECRET=$(python -c "import secrets;print(secrets.token_hex(32))") \\
      alembic -c packages/api/migrations/alembic.ini \\
      revision --autogenerate -m "accounts"

`down_revision` в получившемся файле — тот head, который был на момент создания.
У миграций, написанных параллельно, `down_revision` окажется одинаковым — это
несколько голов, а не беда: их сливает одна команда
`alembic merge -m "a5" <head> <head> <head>`. Именно поэтому никто не правит
`down_revision` в чужом файле руками: правка выглядит как слияние, но теряет
порядок, в котором миграции уже применились на чужой машине.

Пустая корневая миграция (`0001_root`) — якорь этой цепочки. Без неё первые
три миграции были бы тремя корнями, и `alembic merge` их не свёл бы.

**Миграции применяет код, а не человек.** `migrate(settings)` зовут и тесты, и
`create_app`: схема, обновляемая руками при выкате, расходится с кодом ровно
один раз — на том выкате, когда про неё забыли.
"""
from __future__ import annotations

import datetime
import os
from contextlib import contextmanager
from typing import Annotated, Iterator

from alembic import command
from alembic.config import Config
from fastapi import Depends, Request
from sqlalchemy import DateTime, MetaData, String, create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from .ids import ID_LEN, new_id
from .settings import Settings

# Каталог миграций внутри пакета: у службы и её схемы одна судьба, и переезд
# пакета не должен оставлять миграции на прежнем месте.
MIGRATIONS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "migrations")

# Имена ограничений задаём сами. Без этого SQLite называет их как хочет (а чаще
# никак), и `--autogenerate` на SQLite не может выписать `DROP CONSTRAINT` —
# правка внешнего ключа превращается в ручную пересборку таблицы.
NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def now() -> datetime.datetime:
    """Время в UTC, с зоной. Наивное время в базе — это спор о часовом поясе
    через полгода, когда сервер и разработчик окажутся в разных."""
    return datetime.datetime.now(datetime.timezone.utc)


class Base(DeclarativeBase):
    """Общие метаданные всех таблиц службы. Вторая такая в проекте запрещена."""

    metadata = MetaData(naming_convention=NAMING)


class Row(Base):
    """Строка с идентификатором и двумя отметками времени.

    Абстрактная: своей таблицы нет, `__tablename__` объявляет наследник.
    `updated_at` двигает сам SQLAlchemy (`onupdate`) — правка, забывшая тронуть
    отметку, была бы правкой, которой нет в списке изменений.
    """

    __abstract__ = True

    id: Mapped[str] = mapped_column(String(ID_LEN), primary_key=True,
                                    default=new_id)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=now, onupdate=now)


# ── движок ───────────────────────────────────────────────────────────────────

def make_engine(settings: Settings) -> Engine:
    """Движок по `settings.db_url`. Для SQLite — прагмы на каждое соединение."""
    kwargs: dict = {}
    if settings.is_sqlite:
        # FastAPI отдаёт синхронные обработчики в пул потоков, поэтому
        # соединение живёт не в том потоке, где заведено. Проверка потока в
        # SQLite про однопоточность старых сборок, а не про нашу безопасность:
        # за одновременный доступ отвечает пул SQLAlchemy.
        kwargs["connect_args"] = {"check_same_thread": False}

    engine = create_engine(settings.db_url, future=True, **kwargs)

    if settings.is_sqlite:
        @event.listens_for(engine, "connect")
        def _pragmas(dbapi_connection, record):        # noqa: ANN001
            cur = dbapi_connection.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA journal_mode=WAL")
            # Ждать освободившуюся базу пять секунд, а не падать сразу:
            # «database is locked» на живом сайте — это отказ обслуживания из-за
            # чужого коммита длиной в миллисекунду.
            cur.execute("PRAGMA busy_timeout=5000")
            cur.close()

    return engine


class Db:
    """Движок и фабрика сессий одного приложения.

    Живёт в `app.state.db`, а не глобальной переменной модуля: глобальный движок
    означает, что два приложения в одном процессе (а тесты — это ровно они)
    делят одну базу и видят чужие строки.
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self.engine = make_engine(settings)
        # `expire_on_commit=False`: иначе после коммита обработчик, читающий
        # поля возвращаемого объекта, молча идёт в базу ещё раз — а сессия к
        # этому моменту уже закрыта, и получается `DetachedInstanceError` на
        # ровном месте.
        self.sessions = sessionmaker(self.engine, expire_on_commit=False,
                                     class_=Session)

    @contextmanager
    def session_scope(self) -> Iterator[Session]:
        """Сессия на кусок работы: коммит на выходе, откат на исключении.

        Форма для кода вне запроса — уборка корзины, консольные команды, тесты.
        Внутри запроса берут зависимость `session` (ниже): она делает то же
        самое, но одну сессию на запрос, а не одну на вызов.
        """
        s = self.sessions()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    def alive(self) -> bool:
        """Отвечает ли база. Для `/health`, который опрашивает прокси."""
        try:
            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return True
        except Exception:
            return False

    def dispose(self) -> None:
        self.engine.dispose()


# ── сессия на запрос ─────────────────────────────────────────────────────────

def session(request: Request) -> Iterator[Session]:
    """Зависимость FastAPI: одна сессия на запрос, коммит при успехе.

    Одна на запрос, а не одна на обработчик: иначе два вызова в одном запросе
    коммитят по отдельности, и половина записи остаётся при беде во второй
    половине. Исключение из обработчика прилетает сюда (`session_scope` его и
    ловит), поэтому `ApiError`, брошенный после `s.add(...)`, откатывает
    добавленное — без единой строки про откат в самом обработчике.

    Берётся так:

        from ..db import SessionDep

        @router.get("/projects")
        def список(s: SessionDep):
            return s.scalars(select(Project)).all()
    """
    with request.app.state.db.session_scope() as s:
        yield s


# `scope="function"`, а не умолчание `"request"`. С FastAPI 0.118 код после
# `yield` в зависимости по умолчанию выполняется **после того, как ответ уже
# отправлен**; для нас это значило бы «браузер получил 200 и cookie сессии, а
# строка сессии ещё не закоммичена». Сайт после входа тут же спрашивает
# `/api/auth/me` — и в этом окне получал 401 (найдено сквозной проверкой
# `web/e2e/tests/flow.spec.ts`, шаг «выход → вход»). То же окно есть у любой
# записи с немедленным чтением: поставить задание и сразу открыть карточку.
# `"function"` закрывает окно: коммит происходит до отправки ответа. Потоки SSE
# (`events/routes.py`) от этого не страдают: сессию запроса они закрывают сами
# до начала потока, а опрашивают базу своей `session_scope` на каждый цикл.
SessionDep = Annotated[Session, Depends(session, scope="function")]


# ── миграции ─────────────────────────────────────────────────────────────────

def alembic_config(settings: Settings) -> Config:
    """Конфигурация Alembic для этих настроек.

    `settings` кладётся в `attributes`, а не только в `sqlalchemy.url`, потому
    что `env.py` берёт URL из них: два источника URL разошлись бы ровно тогда,
    когда это дороже всего, — при выкате с непривычным `KORITSU_DB_URL`.
    """
    cfg = Config()
    cfg.set_main_option("script_location", MIGRATIONS_DIR)
    cfg.attributes["settings"] = settings
    return cfg


def ensure_volume(settings: Settings) -> None:
    """Завести каталог тома, если его ещё нет.

    SQLite недостающих каталогов не создаёт, и первый запуск на пустом томе
    падал бы «unable to open database file» — самой невнятной из возможных бед о
    том, что каталога нет. Зовут это оба пути к миграции: `migrate` (код) и
    `migrations/env.py` (командная строка, то есть `--autogenerate` руками).
    """
    os.makedirs(settings.data_dir, exist_ok=True)


def migrate(settings: Settings) -> None:
    """Довести базу до последней миграции. Идемпотентно: на уже поднятой базе
    ничего не делает."""
    ensure_volume(settings)
    command.upgrade(alembic_config(settings), "head")


def current_revision(settings: Settings) -> str | None:
    """Какая миграция стоит на базе. Для проверок и диагностики."""
    from alembic.runtime.migration import MigrationContext

    db = Db(settings)
    try:
        with db.engine.connect() as conn:
            return MigrationContext.configure(conn).get_current_revision()
    finally:
        db.dispose()


__all__ = ["Base", "Row", "Db", "make_engine", "session", "SessionDep",
           "migrate", "ensure_volume", "current_revision", "alembic_config",
           "now", "MIGRATIONS_DIR", "NAMING"]
