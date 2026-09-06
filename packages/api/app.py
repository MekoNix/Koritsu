"""
app — сборка приложения: настройки, база, журнал, ошибки, маршруты.

`create_app(settings)` — фабрика, а не приложение на уровне модуля. Разница не
стилистическая: глобальное `app = FastAPI()` означает одно приложение на
процесс, то есть один том и одну базу, и тест, которому нужен свой временный
том, вынужден чинить глобальное состояние. Тесты заводят приложение по штуке
на тест — на это фабрика и рассчитана.

Порядок сборки закреплён и важен:

1. `log.setup` — журнал настроен раньше всего, включая миграцию;
2. `migrate` — база доведена до последней миграции **до** первого запроса;
3. `Db` — движок и фабрика сессий, они же в `app.state.db`;
4. `log.install` — метка запроса и запись о нём;
5. `errors.install` — один формат ответа на все беды;
6. `routes.collect()` — маршруты обоих входов.

Миграция при сборке, а не в `lifespan`: приложение, собранное на непригодной
базе, обязано не собраться. В `lifespan` беда случилась бы после того, как порт
уже открыт, и прокси успел бы отправить туда живые запросы.

Модели импортируются модулем `models` (см. его докстроку) — импорт нужен раньше
`migrate`, иначе `Base.metadata` пуст и `--autogenerate` выпишет `DROP TABLE`
вместо новой таблицы.

Порядок middleware в Starlette: добавленный **позже** оказывается снаружи
(проверено на живом приложении, а не выведено). Поэтому журнал добавляется
последним — он обязан видеть и время, и код ответа, и исключение, включая отказ
чужого middleware. Своё (CSRF, лимит запросов) добавляют **до** `log.install`;
добавленное после уедет клиенту без метки запроса и без строки в журнале.

Чего здесь нет намеренно: очереди и воркера, SSE, внешних токенов, CORS. CORS
не нужен: сайт и API на одном домене за Caddy; исключение — админка, у неё
отдельный origin, и её здесь тоже нет.
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from . import csrf, errors, log, models, routes      # noqa: F401  (models — ради метаданных)
from .admin import service as admin_service          # журнал безопасности в базу
from .db import Db, migrate
from .settings import Settings, предупредить_о_подмене

ВЕРСИЯ = "2.0.0b1.1"

TITLE = "Koritsu API"

DESCRIPTION = (
    "Two entrances, one set of handlers: `/api` for the site (cookie session) "
    "and `/api/v1` for external clients (bearer token). Only `/api/v1` is "
    "versioned and documented.")


class HealthOut(BaseModel):
    """Ответ `/health` — единственный маршрут службы, чей отказ не `ErrorOut`.

    Исключение намеренное и ровно одно. `/health` отвечает не клиенту, а прокси,
    и в обоих случаях — и когда жив, и когда база не отвечает — отдаёт одно и то
    же тело: прокси читает не `code`, а статус. Завернуть 503 в форму ошибки
    значило бы описать `/health` двумя телами вместо одного, ничего не выиграв.
    """

    status: str = Field(description="ok when the process serves requests")
    env: str = Field(description="dev or prod")
    db: str = Field(description="ok when the database answers")


def create_app(settings: Settings) -> FastAPI:
    """Собрать приложение на этих настройках.

    Единственный аргумент — настройки: всё остальное служба берёт из них, и
    второго пути настроить её нет. `Settings.from_env()` зовёт тот, кто
    поднимает процесс (`uvicorn`), а не сама фабрика: иначе тест, собирающий
    приложение на временном томе, зависел бы от окружения машины.
    """
    log.setup(settings)
    # До миграции и до первого запроса: подменённый адрес модели — это то, что
    # оператор обязан увидеть в первых строках журнала, а не найти по странному
    # поведению прогонов.
    предупредить_о_подмене(settings)
    migrate(settings)
    db = Db(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        # Соединения закрываются при остановке. На SQLite это ещё и снятие
        # файловых замков: без него в тестах временный каталог удаляется
        # вместе с открытой базой, а на Windows — не удаляется вовсе.
        db.dispose()

    app = FastAPI(title=TITLE, version=ВЕРСИЯ, description=DESCRIPTION,
                  lifespan=lifespan)
    # Настройки и база — на приложении, а не в глобальных переменных: два
    # приложения в одном процессе (тесты) не должны видеть чужой том.
    app.state.settings = settings
    app.state.db = db
    # Описание входов для документа: что такое `/api/v1` и чем он берётся.
    # Живёт в `routes`, потому что про входы знает он (наружу
    # документируется и версионируется только `/api/v1`).
    app.openapi_tags = routes.ТЕГИ

    # Заслон CSRF — до журнала, а не после: middleware, добавленный позже,
    # оказывается снаружи (проверено), а отказ по CSRF обязан попасть в журнал
    # и унести `X-Request-Id`.
    csrf.install(app, settings)
    # Сброс журнала безопасности в базу — снаружи заслона: отказ по CSRF сам
    # пишет событие и до обработчика не доходит, а сбросить его должен кто-то
    # снаружи (см. `admin.service.install`).
    admin_service.install(app)
    log.install(app, settings)
    errors.install(app)

    # `responses=` — на входе, а не в каждом декораторе: форма отказа у службы
    # одна (`errors.ErrorOut`), и повторять её по маршрутам значило бы завести
    # сорок мест, где её однажды забудут. Заодно она вытесняет чужой
    # `HTTPValidationError`, который FastAPI дописывает сам, — см. `errors`.
    for router in routes.collect():
        app.include_router(router, responses=errors.ОТВЕТЫ_БЕД)

    @app.get("/health", operation_id="health", response_model=HealthOut,
             summary="Health probe for the reverse proxy",
             description=(
                 "Reports whether the process serves requests and the database "
                 "answers. Both answers carry the same body; the proxy reads "
                 "the status code. 503 when the database does not answer."),
             responses={503: {"model": HealthOut,
                              "description": "The database does not answer"}})
    def health() -> JSONResponse:
        """Жив ли процесс и отвечает ли база.

        База проверяется, а не подразумевается: процесс, живой при мёртвой
        базе, — худший случай для прокси, потому что он отвечает пятисотыми на
        каждый запрос вместо того, чтобы быть выведенным из-под нагрузки.
        Метрики сюда не кладём: их место в админке.
        """
        ok = db.alive()
        тело = {"status": "ok" if ok else "error", "env": settings.env,
                "db": "ok" if ok else "error"}
        return JSONResponse(status_code=200 if ok else 503, content=тело)

    return app


def app_from_env() -> FastAPI:
    """Приложение из окружения — точка входа для `uvicorn`.

    Пишется в команде запуска как `api.app:app_from_env` с флагом
    `--factory`. Отдельной функцией, а не модульным `app = ...`, по той же
    причине, что и всё здесь: импорт модуля не должен трогать том.
    """
    return create_app(Settings.from_env())


__all__ = ["create_app", "app_from_env", "HealthOut", "ВЕРСИЯ", "TITLE"]
