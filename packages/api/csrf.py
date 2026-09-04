"""
csrf — заслон от чужого сайта, посылающего запрос за вошедшего человека.

**Чем это лечится и почему одного `SameSite` мало.** Cookie сессии выдаётся с
`SameSite=Lax` (агент B, `accounts.service.cookie_флаги`), и это уже отсекает
почти всё: браузер не приложит её к `POST`, отправленному с чужой страницы.
Почти — потому что `Lax` держится на браузере, а браузеры бывают старые; потому
что «почти» перестаёт работать, если однажды понадобится `SameSite=None` (форма
оплаты, встроенный виджет); и потому что подзапрос с того же сайта — например,
со страницы, которую кто-то сумел встроить, — для браузера не чужой. Двойная
отправка (`double submit`) не зависит ни от одного из этих «если»: чужая
страница не может прочитать нашу cookie, значит не может и повторить её
значение в заголовке.

**Как устроено.** Cookie `koritsu_csrf` — случайная строка, видимая JavaScript
(`HttpOnly` тут нельзя: сайт обязан её прочитать, чтобы положить в заголовок).
На каждом изменяющем запросе с cookie-сессией обязателен заголовок
`X-CSRF-Token`, равный этой cookie; иначе `403 csrf_failed`.

Что мимо заслона, и почему каждое — не послабление:

* **запрос с `Authorization: Bearer`** — у него нет cookie-сессии вовсе, и
  чужая страница не может подставить чужой ключ: она его не знает. CSRF — про
  cookie, которую браузер прикладывает сам;
* **вход, регистрация, подтверждение почты, сброс пароля** — до них сессии ещё
  нет, а значит нечего и подделывать: у чужой страницы, пославшей `POST
  /api/auth/login`, получится только вход в аккаунт, пароль от которого она уже
  знает;
* **`/api/v1`** — там ключ, а не cookie (см. первый пункт).

Заслон стоит **middleware**, а не зависимостью на маршруте, и это существенно:
зависимость вешается на маршруты, а маршруты пишут четверо, и первый же
забытый `POST` — это дыра. Middleware не знает про маршруты вовсе и потому не
может забыть ни одного.

Он идёт **внутри** журнала запросов (`log.install`): отказ по CSRF обязан
попасть в журнал и унести `X-Request-Id`, иначе жалобу «у меня не сохраняется»
не с чем связать. Порядок в Starlette такой: middleware, добавленный **позже**,
оказывается снаружи, — поэтому `install` зовётся до `log.install`, а не после
(проверено, а не выведено из докстроки).

Ошибка из middleware отдаётся ответом, а не броском: обработчики исключений
(`errors.install`) живут внутри стека middleware и до внешнего слоя не
достают — брошенный отсюда `ApiError` уехал бы клиенту пятисоткой.
"""
from __future__ import annotations

import secrets

from fastapi import FastAPI, Request, Response

from .errors import ApiError
from .settings import Settings

COOKIE = "koritsu_csrf"
ЗАГОЛОВОК = "X-CSRF-Token"

CSRF_FAILED = "csrf_failed"

# Методы, у которых бывают последствия. `GET` и `HEAD` не проверяются не по
# доброте: запрос, меняющий что-то по `GET`, — сам по себе беда, и лечится он
# не заслоном, а тем, что таких маршрутов у службы нет.
ИЗМЕНЯЮЩИЕ = ("POST", "PUT", "PATCH", "DELETE")

# Куда можно без заголовка: там ещё нет сессии, которую стоило бы подделывать.
# Список закрыт и лежит здесь целиком — «мимо заслона» обязано читаться в одном
# месте, а не собираться из флагов по маршрутам.
БЕЗ_ЗАСЛОНА = (
    "/api/auth/login",
    "/api/auth/register",
    "/api/auth/confirm",
    "/api/auth/password/forgot",
    "/api/auth/password/reset",
)

# Длина случайной части cookie. 32 байта — столько же, сколько у внешнего
# ключа: подбирать её никто не станет, но и экономить тут не на чем.
БАЙТ = 32


def новое_значение() -> str:
    """Случайная строка cookie. `secrets`, а не `random`, — см. `tokens`."""
    return secrets.token_urlsafe(БАЙТ)


def мимо(request: Request) -> bool:
    """Проверять ли этот запрос вовсе.

    Три причины пройти мимо, и все три названы в докстроке модуля: метод без
    последствий, вход по ключу (cookie нет), маршрут входа/регистрации.
    """
    if request.method.upper() not in ИЗМЕНЯЮЩИЕ:
        return True
    if request.headers.get("authorization", "").lower().startswith("bearer "):
        return True
    путь = request.url.path.rstrip("/") or "/"
    return путь in БЕЗ_ЗАСЛОНА


def сходится(request: Request) -> bool:
    """Совпал ли заголовок с cookie. Пустое с пустым не совпадает.

    Сравнение постоянного времени: обычное `==` на строках возвращает ответ тем
    быстрее, чем раньше разошлись знаки, и по времени ответа значение cookie
    подбирается по знаку. Для CSRF это натянуто (значение и так известно тому,
    кто может его прочитать), но правило «секреты сравниваются так» дешевле
    держать без исключений.
    """
    из_cookie = request.cookies.get(COOKIE) or ""
    из_заголовка = request.headers.get(ЗАГОЛОВОК) or ""
    if not из_cookie or not из_заголовка:
        return False
    return secrets.compare_digest(из_cookie, из_заголовка)


def _есть_сессия(request: Request) -> bool:
    """Пришёл ли запрос с cookie-сессией сайта."""
    from .accounts.service import COOKIE as СЕССИЯ

    return bool(request.cookies.get(СЕССИЯ))


def _ставит_сессию(response: Response) -> bool:
    """Выдаёт ли этот ответ cookie-сессию (то есть это вход).

    Гашение сессии (выход) сюда не попадает: `delete_cookie` пишет пустое
    значение, а на пустое значение cookie CSRF заводить незачем — заводить её
    надо тому, кто вошёл.
    """
    from .accounts.service import COOKIE as СЕССИЯ

    for строка in response.headers.getlist("set-cookie"):
        имя, _, хвост = строка.partition("=")
        if имя.strip() == СЕССИЯ and хвост[:1] not in ("", ";", '"'):
            return True
    return False


def поставить(response: Response, request: Request, settings: Settings) -> None:
    """Выдать cookie CSRF, если её ещё нет.

    Флаги — те же, что у cookie сессии (`accounts.service.cookie_флаги`), кроме
    одного: `HttpOnly` снят, иначе сайт не сможет прочитать значение и положить
    его в заголовок. Флаги берутся у соседа, а не пишутся заново: две cookie с
    разошедшимся `path` браузер считает разными, и заслон бы молча перестал
    сходиться на половине страниц.

    Значение не перевыпускается, пока оно есть. Перевыпуск на каждом ответе
    ломал бы вкладку, которая открыта давно: страница положила бы в заголовок
    прочитанное при загрузке, а cookie к тому времени была бы уже другой.
    """
    from .accounts.service import cookie_флаги

    if request.cookies.get(COOKIE):
        return
    флаги = dict(cookie_флаги(settings))
    флаги["httponly"] = False
    response.set_cookie(COOKIE, новое_значение(),
                        max_age=settings.session_days * 24 * 3600, **флаги)


def install(app: FastAPI, settings: Settings) -> None:
    """Повесить заслон. Зовётся из `create_app` до `log.install` — см. модуль."""

    @app.middleware("http")
    async def _csrf(request: Request, call_next):
        if not мимо(request) and _есть_сессия(request) and not сходится(request):
            from .admin import service as журнал
            from .admin.models import CSRF_FAILED as ВИД

            журнал.событие(request, ВИД, path=request.url.path)
            return ApiError(CSRF_FAILED,
                            f"Missing or wrong {ЗАГОЛОВОК} header", 403).response()

        response = await call_next(request)

        if _есть_сессия(request) or _ставит_сессию(response):
            поставить(response, request, settings)
        return response


__all__ = ["install", "поставить", "мимо", "сходится", "новое_значение",
           "COOKIE", "ЗАГОЛОВОК", "CSRF_FAILED", "ИЗМЕНЯЮЩИЕ", "БЕЗ_ЗАСЛОНА"]
