"""
routes — два входа службы и место, куда подпакеты вешают свои маршруты.

Не две службы, а **один код обработчиков и два входа**. `/api/` — для сайта
(cookie-сессия, CSRF), `/api/v1/` — для внешних скриптов и агентов (Bearer-токен
со scope'ами и своим лимитом). Довод стоит того, чтобы повторить его здесь, где
соблазн разъехаться живёт: две отдельные службы означали бы два набора правил
про проекты и файлы, и они разошлись бы молча. Наружу документируется и
версионируется только `/api/v1/`.

Отсюда единственное правило этого файла: **обработчик пишется один раз**.
Функция, отвечающая на `/api/projects`, — та же самая, что отвечает на
`/api/v1/projects`; различаются они только тем, кто проверил, чей это запрос
(cookie или токен), а это зависимость, а не второй обработчик. Копия
обработчика под второй вход — и есть тот самый молчаливый разъезд.

**Как подпакет добавляет маршруты.** Свой роутер в своём модуле, потом одна
строка в `collect()`:

    # packages/api/accounts/routes.py
    router = APIRouter(prefix="/accounts", tags=["accounts"])

    @router.post("/register")
    def register(тело: Регистрация, s: SessionDep): ...

    # здесь, в collect():
    from .accounts.routes import router as accounts
    site.include_router(accounts)

Префикса `/api` в своём роутере писать не надо — его несёт `site`.

**Как маршрут выставляется под `/api/v1/`.** Одна строка — имя роутера
в списке `ПОД_V1` внутри `collect()`. Дальше всё делается само:

    под_v1 = [projects, project_files, jobs, *modules.routers()]

Тот же объект роутера включается вторым входом, с зависимостью
`auth.внешний_вход` (Bearer и проверка права), а `operation_id` у копий
получают суффикс `_v1`. Копии обработчика не заводится ни одной — включение
роутера дважды создаёт вторые объекты маршрутов, а функция за ними остаётся та
же самая.

Суффикс нужен не для красоты: `operation_id` уникален по всему документу, из
него генератор делает имя метода клиента, и два входа с одинаковыми именами
дали бы один метод вместо двух (`test_openapi` это ловит). Право маршрута при
этом ищется по имени **без** суффикса — маршрут-то один и тот же (`auth`).

Что под `/api/v1/` не выставляется: аккаунты, ключи моделей, сами внешние ключи
и админка («Аккаунты и ключи моделей через токен не даём»). Отказ там —
`401 token_not_allowed`, и стоит он не здесь, а в `auth.deny_bearer`: список
закрытых входов должен читаться целиком в одном месте, а не собираться из
аргументов четырёх включений.

`ping` остаётся открытым: он отвечает, жив ли вход, и ключа для этого не
просит — всё, что открыто наружу, обязано молчать про внутренности.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.routing import APIRoute

# Вход сайта (`site`, cookie-сессия, не версионируется — сайт и API едут вместе)
# собирается ВНУТРИ `collect()`, а не здесь. Роутер уровня модуля накапливал бы
# включения: FastAPI включает роутеры по ссылке, `collect()` зовётся на каждое
# приложение (в тестах — сотни), и к третьей сборке в `site` лежали маршруты трёх
# приложений, а OpenAPI ругался на дубли operation id.

# Открытая часть внешнего входа: то, что отвечает без ключа. Ровно один
# маршрут. Уровень модуля тут безопасен: сюда ничего не включается, маршрут
# объявлен декоратором один раз при импорте. Префикса нет — его несёт сам вход,
# который собирается в `collect()` (накопить включения он не может, потому что
# заводится заново на каждое приложение).
открытый_v1 = APIRouter(tags=["v1"])

# Суффикс `operation_id` у маршрутов под вторым входом — см. докстроку модуля.
СУФФИКС_V1 = "_v1"

# Описание входов для документа OpenAPI. Здесь, а не в `app`: что такое `/api`
# и что такое `/api/v1`, знает этот файл.
ТЕГИ = [
    {"name": "v1",
     "description": (
         "External entrance for scripts and agents. Takes an API token: "
         "`Authorization: Bearer kor_...`, issued at `POST /api/tokens` from "
         "the site and shown once. Every token carries scopes "
         "(`projects:read`, `projects:write`, `materials:write`, `runs:run`) "
         "and is limited to 60 requests per minute. The handlers are the very "
         "same ones the site calls; only the way the caller is identified "
         "differs, so operation ids here carry a `_v1` suffix. Accounts, "
         "provider keys, tokens themselves and the admin area are not "
         "reachable with a token.")},
]


@открытый_v1.get("/ping", operation_id="ping",
                 summary="Liveness probe for external clients",
                 description=(
                     "Answers while the external entrance is up. Needs no "
                     "token and discloses nothing about the service."))
def ping() -> dict:
    """Простейший маршрут внешнего входа: есть ли служба и та ли это версия.

    Ничего не проверяет и ничего не рассказывает: без токена он открыт, а всё,
    что открыто наружу, обязано молчать про внутренности.
    """
    return {"pong": True, "api": "v1"}


def collect() -> list[APIRouter]:
    """Все роутеры службы по порядку. Сюда подпакеты дописывают свои — по строке.

    Функция, а не список на уровне модуля: импорт модуля с маршрутами тянет за
    собой модели, а те — `db`, и на уровне модуля это замкнутый круг импортов в
    первый же день. Внутри функции круга нет, потому что к моменту вызова пакет
    уже собран.
    """
    # Свежий роутер на каждое приложение — см. пояснение у `v1` выше.
    site = APIRouter(prefix="/api")

    # ── сюда подпакеты дописывают свои роутеры ──────────────────────────────
    from .accounts.routes import router as accounts        # Вход и сессии
    from .projects.routes import router as projects        # Проекты, корзина
    from .projects.runs import router as project_runs      # Журнал запусков
    from .workspaces.routes import router as workspaces    # Workspace, роли
    from .workspaces.service import register_hooks         # Личное при регистрации

    # Хук ставится здесь, а не при импорте модуля: импорт случается один раз на
    # процесс, а приложений в процессе бывает много (тесты собирают по штуке на
    # тест). Вызов идемпотентен.
    register_hooks()

    site.include_router(accounts)
    site.include_router(workspaces)
    site.include_router(projects)
    site.include_router(project_runs)

    from .keys.routes import router as keys                 # Ключи моделей
    from .materials.routes import router as project_files   # Материалы проекта

    site.include_router(keys)
    site.include_router(project_files)

    from .jobs.routes import router as jobs                 # Очередь заданий

    site.include_router(jobs)

    # Прогоны (расход и лимит), потоки событий, колокольчик, версии тегов.
    from .events import job_router as job_stream, user_router as user_stream
    from .notifications.routes import router as notifications
    from .runs.routes import router as usage
    from .versions.routes import router as versions

    site.include_router(usage)
    site.include_router(job_stream)
    site.include_router(user_stream)
    site.include_router(notifications)
    site.include_router(versions)

    from . import billing                                   # Заглушка платёжки
    from .admin.routes import router as admin               # Админка
    from .tokens.routes import router as tokens             # Внешние ключи

    site.include_router(tokens)
    site.include_router(admin)
    site.include_router(billing.router)

    from .bootstrap import router as bootstrap              # Сводка первого экрана
    from .export.routes import router as export             # Выгрузка файлов
    from .search.routes import router as search             # Поиск по именам

    site.include_router(bootstrap)

    site.include_router(export)
    site.include_router(search)

    from .templates.routes import project_router as project_templates
    from .templates.routes import router as templates       # Шаблоны отчётов

    site.include_router(templates)
    site.include_router(project_templates)

    # Модули (реестр, блок-схемы, UML) и общее скачивание артефактов. Одной
    # строкой намеренно: новый модуль заводится строкой в `modules/__init__.py`,
    # а не правкой этого файла — иначе каркас правят все, кто добавляет модуль.
    from . import modules

    модули = modules.routers()
    for роутер in модули:
        site.include_router(роутер)

    # ── что видно и внешнему входу ──────────────────────────────────────────
    #
    # Список, а не флаг на роутере: «что выставлено наружу» — решение,
    # принимаемое глазами, и читаться оно должно одной строкой целиком.
    # Аккаунтов, ключей моделей, самих ключей и админки здесь нет намеренно.
    # Потоки событий здесь есть: внешнему клиенту обещаны не только задания,
    # но и события. Права им не объявлены и не нужны — оба `GET`, то есть
    # `projects:read` по умолчанию: читать события — чтение, а не запуск.
    #
    # Выгрузка (`export`) выставлена наружу. Довод — тот
    # самый, ради которого внешний вход и заведён: «скрипт, который раз в
    # неделю забирает архив проекта» — это и есть внешний клиент, а собрать
    # архив он и сегодня может (`POST /api/v1/jobs` вида `export`), только
    # окольно и с правом `runs:run`, которое ему ни к чему. Своё право у неё
    # умолчанием по методу — `projects:write`: архив ложится на том, в квоту
    # владельца проекта, и это запись, а не чтение. Скачивается он маршрутом
    # артефактов, который под `/api/v1` уже есть (он в `модули`).
    # Журнал запусков выставлен наружу вместе с проектами: «скрипт, который раз
    # в неделю смотрит, что в работе делали» — тот же внешний клиент, ради
    # которого второй вход и заведён, а прав ему хватает тех же
    # (`projects:read` на чтение, `projects:write` на запись). Шаблонов здесь
    # нет — ни своих, ни приложенных: это личные файлы аккаунта, и ключом в них
    # не ходят.
    ПОД_V1 = [projects, project_runs, project_files, jobs, job_stream,
              user_stream, export, *модули]

    return [site, внешний_вход(ПОД_V1)]


def зеркало(роутер: APIRouter) -> APIRouter:
    """Тот же роутер, но с именами операций под вторым входом.

    **Обработчик не копируется** — копируется только объявление маршрута:
    `add_api_route` получает ту же самую функцию (`маршрут.endpoint`), тот же
    путь, те же формы запроса и ответа, и отличается ровно одним полем —
    `operation_id` с суффиксом. Правило «обработчик пишется один раз» тем
    самым соблюдено: функция в службе одна, объявлений у неё два.

    Почему не `include_router` того же объекта дважды. С FastAPI 0.141
    включение стало ленивым: роутер запоминается по ссылке
    (`_IncludedRouter`), настоящие маршруты собираются при первом запросе, и
    `operation_id` у них берётся из **исходного** маршрута. Два включения
    одного объекта дают два пути с одним именем операции — то есть дубль в
    OpenAPI, о котором FastAPI честно предупреждает, и один метод вместо двух в
    сгенерированном клиенте. Переименовать копию негде: её просто нет.

    Вложенных включений в зеркалимых роутерах не бывает и быть не должно —
    маршруты службы объявляются декоратором на своём роутере. Если такое
    появится, здесь будет внятный отказ при сборке приложения, а не тихо
    пропавшая половина маршрутов.
    """
    зеркальный = APIRouter()
    for маршрут in роутер.routes:
        if not isinstance(маршрут, APIRoute):
            raise TypeError(
                f"под /api/v1 попал не маршрут, а {type(маршрут).__name__}: "
                "вложенные include_router здесь не поддержаны")
        зеркальный.add_api_route(
            маршрут.path, маршрут.endpoint,
            response_model=маршрут.response_model,
            status_code=маршрут.status_code,
            tags=list(маршрут.tags),
            dependencies=list(маршрут.dependencies),
            summary=маршрут.summary,
            description=маршрут.description,
            response_description=маршрут.response_description,
            responses=dict(маршрут.responses),
            deprecated=маршрут.deprecated,
            methods=sorted(маршрут.methods),
            operation_id=(маршрут.operation_id + СУФФИКС_V1
                          if маршрут.operation_id else None),
            response_model_include=маршрут.response_model_include,
            response_model_exclude=маршрут.response_model_exclude,
            response_model_by_alias=маршрут.response_model_by_alias,
            response_model_exclude_unset=маршрут.response_model_exclude_unset,
            response_model_exclude_defaults=маршрут.response_model_exclude_defaults,
            response_model_exclude_none=маршрут.response_model_exclude_none,
            include_in_schema=маршрут.include_in_schema,
            response_class=маршрут.response_class,
            name=маршрут.name,
            callbacks=маршрут.callbacks,
            openapi_extra=маршрут.openapi_extra,
            generate_unique_id_function=маршрут.generate_unique_id_function)
    return зеркальный


def внешний_вход(роутеры: list[APIRouter]) -> APIRouter:
    """Собрать `/api/v1`: те же обработчики, но за ключом и под своими именами.

    Заводится заново на каждое приложение — по той же причине, что и `site`:
    роутер уровня модуля накапливал бы включения, и к третьей сборке в нём
    лежали бы маршруты трёх приложений.

    Зависимость `auth.внешний_вход` вешается на вход целиком, а не на маршрут:
    вход, где защищён каждый маршрут, кроме одного забытого, — это
    незащищённый вход. `ping` при этом остаётся открытым: он включается до
    зависимости и своего имени не меняет — операция с таким именем в документе
    одна.
    """
    from . import auth

    вход = APIRouter(prefix="/api/v1", tags=["v1"])
    вход.include_router(открытый_v1)
    for роутер in роутеры:
        вход.include_router(зеркало(роутер),
                            dependencies=[Depends(auth.внешний_вход)])
    return вход


__all__ = ["открытый_v1", "внешний_вход", "зеркало", "collect", "ТЕГИ",
           "СУФФИКС_V1"]
