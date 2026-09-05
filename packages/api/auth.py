"""
auth — кто пришёл: cookie сайта или Bearer-ключ скрипта, и что ему можно.

**Один код обработчиков и два входа.** Значит, у службы обязано быть одно
место, где «чей это запрос» отвечается для обоих входов сразу, — иначе у
каждого обработчика окажется по две ветки, и разойдутся они молча. Это место
здесь.

    Principal          кто пришёл: пользователь, каким входом, с какими правами
    current_principal  зависимость «cookie или Bearer»
    внешний_вход       зависимость входа `/api/v1`: только Bearer
    require_scope      объявить право маршрута явно
    deny_bearer        сюда с ключом нельзя (аккаунты, ключи моделей, админка)

**Права проверяются один раз и для всех.** Проверка живёт не в маршруте, а в
разборе ключа (`по_токену`): маршрут, забывший объявить право, всё равно
получает проверку по умолчанию — чтение для `GET`, запись для всего
изменяющего. Обратный порядок (право объявляет маршрут, а забывший его маршрут
не проверяется) означал бы, что дыру открывает не ошибка, а забывчивость, — и
находилась бы она снаружи.

**Как B/D вешают право на свой маршрут.** Два способа, и оба однострочные:

    # по умолчанию — ничего не делать: GET → projects:read, POST → projects:write

    # если умолчание не то — строка в СКОПЫ, по operation_id маршрута:
    СКОПЫ["jobs_create"] = RUNS_RUN

    # или прямо в маршруте, если так виднее:
    @router.post("/…", dependencies=[Depends(require_scope(RUNS_RUN))])

Объявленное в маршруте старше `СКОПЫ`, `СКОПЫ` старше умолчания по методу.
Тремя ступенями, а не одной, потому что маршруты пишутся в разных файлах: тот,
кто правит `jobs/routes.py`, объявит право там, где смотрит, а тот, кто вешает
чужой роутер под `/api/v1`, — в словаре, не трогая чужой файл.

**Как маршрут выставляется под `/api/v1`.** Одна строка в `routes.ПОД_V1` — и
всё: тот же объект роутера включается вторым входом с зависимостью
`внешний_вход`, а `operation_id` там получают суффикс `_v1` (см. `routes`).
Копии обработчика не заводится ни одной.

**Куда с ключом нельзя** (аккаунты и ключи моделей через токен не даём):
`/api/auth`, `/api/keys`, `/api/tokens`, `/api/admin`. Отказ там —
`401 token_not_allowed`, а не «не туда попал»: человек, положивший ключ в
скрипт, обязан узнать, что ключом это не делается, а не гадать, почему сессии
нет. Довод владельца — свой: ключ живёт в конфиге скрипта на чужой машине, и
если им можно завести второй ключ или сменить почту, то утёкший ключ уже не
отзывается.

Коды отказа этого модуля:

    unauthenticated     401  ни cookie, ни ключа
    invalid_token       401  ключа с таким хешем нет
    token_revoked       401  ключ отозван
    token_required      401  вход `/api/v1` — только по ключу
    token_not_allowed   401  сюда ключом нельзя, только сессией сайта
    insufficient_scope  403  у ключа нет нужного права
    rate_limited        429  больше 60 запросов в минуту одним ключом
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Annotated

from fastapi import Depends, Request

# Зависимость «кто вошёл» берётся из `accounts` и не заводится второй раз: подмена
# в тестах работает по объекту функции, и второе имя того же дало бы второй ключ
# в `dependency_overrides` — подменённую зависимость в одном маршруте и
# настоящую в соседнем (тот же довод, что в `workspaces/deps.py`). Круга
# импортов тут нет: `accounts.service` зовёт `auth` только внутри функций.
from .accounts.service import CurrentUser
from .db import SessionDep
from .errors import ApiError
from .tokens import service as ключи
from .tokens.models import ApiToken
from .tokens.service import (MATERIALS_WRITE, PROJECTS_READ, PROJECTS_WRITE,
                             RUNS_RUN)

# ── коды отказа ──────────────────────────────────────────────────────────────

UNAUTHENTICATED = "unauthenticated"
TOKEN_REQUIRED = "token_required"
TOKEN_NOT_ALLOWED = "token_not_allowed"

СХЕМА = "bearer"          # `Authorization: Bearer kor_…`

# Входы, куда с ключом нельзя. Списком путей, а не флагом на роутере:
# роутеров в службе много, а список закрытых входов должен читаться в одном
# месте целиком.
# `/api/templates` здесь по той же причине, что и ключи: это личные файлы
# аккаунта, а не работа над проектом. Внешнему клиенту они и не нужны — DOCX он
# приносит телом создания проекта, как и раньше.
ТОЛЬКО_СЕССИЯ = ("/api/auth", "/api/keys", "/api/tokens", "/api/admin",
                 "/api/templates")


# ── кто пришёл ───────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Principal:
    """Кто пришёл и чем это подтверждено.

    Не «пользователь»: у запроса сайта и запроса скрипта один и тот же
    пользователь, но разные права и разные правила (CSRF — только для сессии,
    лимит 60/мин — только для ключа). Обработчику это обычно не нужно, и он
    берёт `CurrentUser`; нужно это тем немногим местам, которые ведут себя
    по-разному, — и им честнее видеть `via`, чем гадать по заголовкам.
    """

    user: object                       # `accounts.models.User`
    via: str                           # "session" | "token"
    scopes: tuple[str, ...] = ()
    token: ApiToken | None = field(default=None, repr=False)

    @property
    def by_token(self) -> bool:
        return self.via == "token"


# ── какое право нужно этому маршруту ─────────────────────────────────────────

# Умолчание по методу. Читающие методы просят чтение, изменяющие — запись:
# маршрут, забывший объявить право, оказывается строже, а не свободнее.
ПО_МЕТОДУ = {
    "GET": PROJECTS_READ, "HEAD": PROJECTS_READ, "OPTIONS": PROJECTS_READ,
    "POST": PROJECTS_WRITE, "PUT": PROJECTS_WRITE, "PATCH": PROJECTS_WRITE,
    "DELETE": PROJECTS_WRITE,
}

# Маршруты, у которых умолчание не то. Ключ — `operation_id` (он уникален по
# всей службе и не меняется, в отличие от пути); значение — право.
СКОПЫ: dict[str, str] = {
    # Загрузка материала — своё право: ключ CI, который льёт файлы, не
    # обязан уметь переименовывать проекты.
    "upload_material": MATERIALS_WRITE,
    # Постановка задания — это и есть «запуск прогонов».
    "jobs_create": RUNS_RUN,
    # Предпросмотр схемы ничего не пишет: ни проекта, ни артефакта. `POST` у
    # него потому, что исходник не влезает в строку запроса, а не потому, что
    # он что-то меняет.
    "flowcharts_preview": PROJECTS_READ,
    "uml_classes_preview": PROJECTS_READ,
    "uml_objects_preview": PROJECTS_READ,
}


def _операция(request: Request) -> str | None:
    """`operation_id` маршрута, на который попал запрос, без суффикса `_v1`.

    Суффикс снимается, потому что маршрут один и тот же: под `/api/v1` он
    называется `jobs_create_v1` ровно затем, чтобы у клиента сайта и у
    внешнего клиента не совпали имена методов, — а право у него то же самое.
    """
    route = request.scope.get("route")
    имя = getattr(route, "operation_id", None)
    if имя and имя.endswith("_v1"):
        имя = имя[:-len("_v1")]
    return имя


def нужное_право(request: Request) -> str:
    """Право, без которого этот запрос ключом делать нельзя.

    Три ступени, от самой явной к самой общей: объявленное в маршруте, потом
    `СКОПЫ`, потом умолчание по методу. Ступени не складываются: объявленное
    заменяет умолчание, а не добавляется к нему, — иначе `require_scope`
    у `POST`-маршрута молча потребовал бы ещё и `projects:write`.
    """
    route = request.scope.get("route")
    for зависимость in getattr(route, "dependencies", ()) or ():
        право = getattr(getattr(зависимость, "dependency", None), "право", None)
        if право:
            return право
    имя = _операция(request)
    if имя and имя in СКОПЫ:
        return СКОПЫ[имя]
    return ПО_МЕТОДУ.get(request.method.upper(), PROJECTS_WRITE)


# ── ключ из заголовка ────────────────────────────────────────────────────────

def предъявленный(request: Request) -> str | None:
    """Строка ключа из `Authorization: Bearer …`, если она там есть.

    Схема сравнивается без регистра (`bearer`, `Bearer`, `BEARER` — одно и то
    же по RFC 7235), а сама строка не режется и не чистится: ключ, который
    «почти совпал», — это ключ, который не совпал.
    """
    заголовок = request.headers.get("authorization", "")
    схема, _, остаток = заголовок.partition(" ")
    if схема.lower() != СХЕМА or not остаток.strip():
        return None
    return остаток.strip()


def по_токену(request: Request, s, строка: str) -> Principal:
    """Разобрать предъявленный ключ: чей он, годен ли, хватает ли прав.

    Порядок проверок не случаен. Сначала «есть ли такой ключ» и «не отозван
    ли» — то, что относится к самому ключу; потом лимит запросов — он считается
    и для запроса, которому не хватит прав (иначе перебором прав можно ходить
    без счёта); и только потом право. Событие безопасности пишется на двух из
    них: отозванный ключ (кто-то пользуется тем, что человек уже забрал) и
    превышение лимита.
    """
    from .admin import models as виды              # круг импортов: только внутри
    from .admin import service as журнал

    deny_bearer(request)
    ключ = ключи.найти(s, строка)
    if ключ is None:
        raise ApiError(ключи.INVALID_TOKEN, "Invalid API token", 401)
    if ключ.revoked:
        журнал.событие(request, виды.TOKEN_REVOKED, user=ключ.user_id,
                       prefix=ключ.prefix)
        raise ApiError(ключи.TOKEN_REVOKED, "API token has been revoked", 401)

    if not ключи.в_пределах(ключ.id):
        журнал.событие(request, виды.RATE_LIMITED, user=ключ.user_id,
                       prefix=ключ.prefix)
        raise ApiError(ключи.RATE_LIMITED,
                       f"More than {ключи.ЛИМИТ_В_МИНУТУ} requests per minute "
                       "with this token", 429)

    user = _пользователь(s, ключ.user_id)
    право = нужное_право(request)
    if not ключи.даёт(ключ.scopes, право):
        raise ApiError(ключи.INSUFFICIENT_SCOPE,
                       f"This token has no {право} scope", 403)

    ключи.отметить_использование(ключ)
    request.state.user_id = user.id
    principal = Principal(user=user, via="token",
                          scopes=tuple(ключ.scopes or ()), token=ключ)
    request.state.principal = principal
    return principal


def _пользователь(s, user_id: str):
    """Владелец ключа. Удалённый — то же самое, что несуществующий: ключ
    пережил аккаунт только в корзине, и работать он не должен.

    Заблокированный отличается: ему отвечают `403 account_blocked`, а не
    «ключ не годится». Ключ у него как раз годный, и человек, которому сказали
    «invalid token», пошёл бы выпускать новый — и получил бы тот же ответ.
    Отзывать ключи при блокировке служба не стала бы всё равно: разблокировка
    вернула бы человека без единого рабочего ключа.
    """
    from .accounts.models import User
    from .accounts.service import отказать_заблокированному

    user = s.get(User, user_id)
    if user is None or user.deleted_at is not None:
        raise ApiError(ключи.INVALID_TOKEN, "Invalid API token", 401)
    отказать_заблокированному(user)
    return user


# ── зависимости ──────────────────────────────────────────────────────────────

def внешний_вход(request: Request, s: SessionDep) -> Principal:
    """Зависимость входа `/api/v1`: только ключ, только со своим правом.

    Вешается на весь вход разом (`routes.collect`), а не на маршрут: вход, где
    защищён каждый маршрут, кроме одного забытого, — это незащищённый вход.

    Cookie здесь не годится намеренно, хотя технически сработала бы. `/api/v1`
    идёт мимо Anubis и не проверяет CSRF: пускать туда сессию сайта
    значило бы отдать все изменяющие маршруты сайта в обход обеих защит —
    достаточно поменять `/api/` на `/api/v1/` в адресе.
    """
    строка = предъявленный(request)
    if строка is None:
        raise ApiError(TOKEN_REQUIRED,
                       "The /api/v1 entrance takes an API token: "
                       "Authorization: Bearer kor_...", 401)
    return по_токену(request, s, строка)


def current_principal(request: Request, user: CurrentUser) -> Principal:
    """Кто пришёл — cookie сайта или Bearer-ключ.

    Обработчику обычно нужен не `Principal`, а пользователь, и он берёт
    `CurrentUser`. Эта зависимость — для тех мест, которым важно, чем
    подтверждён запрос.

    Ключ здесь не разбирается: его разбирает `current_user` (и вход `/api/v1`
    до него), а сюда кладёт готовый `Principal` в `request.state`. Второй
    разбор того же заголовка стоил бы второго похода в базу, а главное —
    разошёлся бы с первым: два места, отвечающие «кто пришёл», это ровно то,
    от чего заведён этот модуль.

    Пользователь берётся **зависимостью**, а не прямым вызовом. Разница видна
    в тестах: подмена `app.dependency_overrides[current_user]` действует на
    зависимость и не действует на вызов из кода, и маршрут с `require_scope`
    вёл бы себя не так, как соседний без неё.
    """
    готовый = getattr(request.state, "principal", None)
    if готовый is not None:
        return готовый

    # У сессии сайта прав столько же, сколько у человека: scope'ы придуманы
    # для ключа, лежащего в чужом скрипте, а не для владельца, сидящего в
    # своём браузере (права — у ключа).
    return Principal(user=user, via="session", scopes=tuple(ключи.ПРАВА))


CurrentPrincipal = Annotated[Principal, Depends(current_principal)]


def require_scope(право: str):
    """Объявить, какое право нужно этому маршруту. Для cookie-сессии — ничего.

        @router.post("/run", dependencies=[Depends(require_scope(RUNS_RUN))])

    Возвращается новая функция на каждый вызов, и на ней стоит метка `право` —
    по ней `нужное_право` узнаёт объявленное, не заглядывая в замыкание. Метка,
    а не разбор замыкания: замыкание — это подробность реализации, а метка —
    договор, и он проверяется тестом.
    """
    if право not in ключи.ПРАВА:
        raise ValueError(f"неизвестное право: {право!r}")

    def проверка(principal: CurrentPrincipal) -> None:
        """Хватает ли прав. Сессии сайта хватает всегда — см. докстроку."""
        if principal.by_token and not ключи.даёт(principal.scopes, право):
            raise ApiError(ключи.INSUFFICIENT_SCOPE,
                           f"This token has no {право} scope", 403)

    проверка.право = право
    return проверка


def deny_bearer(request: Request) -> None:
    """Сюда ключом нельзя — только сессией сайта.

    Проверяется по пути (`ТОЛЬКО_СЕССИЯ`), а не по флагу на роутере, и зовётся
    из одного места — разбора ключа. Флаг пришлось бы ставить на четыре разных
    роутера, и пятый, заведённый под тем же префиксом, оказался бы без него
    молча. Путь же не забывается: он в списке
    или нет, и список читается целиком.

    Отказ отдельным кодом, а не общим `unauthenticated`: разница между «ключ не
    подошёл» и «ключом это не делается» — это разница между «перевыпущу ключ» и
    «пойду в браузер», и угадывать её человек не должен.
    """
    if предъявленный(request) is None:
        return
    путь = request.url.path
    if any(путь == п or путь.startswith(п + "/") for п in ТОЛЬКО_СЕССИЯ):
        raise ApiError(TOKEN_NOT_ALLOWED,
                       "This endpoint takes a site session, not an API token",
                       401)


__all__ = ["Principal", "CurrentPrincipal", "current_principal", "require_scope",
           "внешний_вход", "deny_bearer", "предъявленный", "по_токену",
           "нужное_право", "СКОПЫ", "ПО_МЕТОДУ", "ТОЛЬКО_СЕССИЯ",
           "UNAUTHENTICATED", "TOKEN_REQUIRED", "TOKEN_NOT_ALLOWED",
           "PROJECTS_READ", "PROJECTS_WRITE", "MATERIALS_WRITE", "RUNS_RUN"]
