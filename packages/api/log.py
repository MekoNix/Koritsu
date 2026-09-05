"""
log — технический журнал запросов и метка, по которой жалобу находят в нём.

Потоков два. Технический — id запроса, UUID пользователя, маршрут, код,
длительность; события безопасности — отдельно (отказ входа, превышение
лимита). Здесь первый, и правило у него жёсткое:
**содержимое тел не пишется никогда**. Ни тела запроса, ни тела ответа, ни
заголовков (в них cookie сессии и Bearer-токен), ни строки запроса — в ней
уезжает токен подтверждения почты. Отладочный флаг это не отменяет: он про
метаданные.

`X-Request-Id` — то, чем жалоба «у меня всё сломалось» связывается с
трассировкой. Приходит от прокси, а если не пришёл — заводится здесь. Чужой
заголовок **не берётся как есть**: в журнал уходит строка, и перенос строки
внутри неё дорисовывает в журнал поддельную запись (лишний ключ в разборщике,
лишний «успешный вход» глазами человека). Поэтому чужая метка либо совпадает с
разрешённой формой, либо заменяется своей.

Необработанное исключение ловится здесь, а не обработчиком `Exception` у
FastAPI, по одной причине: ответ обязан нести тот же `X-Request-Id`, что и
запись в журнале. Обработчик FastAPI отдаёт ответ выше нашего middleware —
заголовка на нём не будет, и пятисотка окажется без метки, то есть ровно та
беда, ради которой метка и заведена, останется неразысканной.

Что читать подпакетам: `request.state.request_id` — метка текущего запроса
(кладите её в события безопасности), `request.state.user_id` — UUID вошедшего,
если обработчик его выставил. Каркас его не выставляет: это дело `accounts`.
Пока не выставлен, в журнале стоит `user=-`.
"""
from __future__ import annotations

import logging
import re
import time

from fastapi import FastAPI, Request

from .errors import ApiError, INTERNAL, INTERNAL_MESSAGE
from .ids import new_id
from .settings import Settings

ЗАГОЛОВОК = "X-Request-Id"

# Разрешённая форма чужой метки: буквы, цифры, точка, дефис, подчёркивание.
# Ни пробела, ни переноса строки, ни двоеточия — журнал разбирается по полям.
МЕТКА_RE = re.compile(r"\A[A-Za-z0-9._-]{1,64}\Z")

журнал = logging.getLogger("api.request")
беды = logging.getLogger("api.error")


def метка(request: Request) -> str:
    """Метка запроса: чужая, если она приличной формы, иначе своя."""
    чужая = request.headers.get(ЗАГОЛОВОК, "")
    return чужая if МЕТКА_RE.match(чужая) else new_id()


def setup(settings: Settings) -> None:
    """Настроить журнал под режим.

    В `dev` — `DEBUG` и время в строке, чтобы читать глазами; в `prod` — `INFO`.
    Настраиваются только наши логгеры: перенастраивать корневой значило бы
    молча менять журнал всему, что окажется в процессе, — например, alembic'у
    во время миграции при старте.
    """
    уровень = logging.DEBUG if settings.env == "dev" else logging.INFO
    for log in (журнал, беды):
        log.setLevel(уровень)
        if not log.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(logging.Formatter(
                "%(asctime)s %(levelname)s %(name)s %(message)s"))
            log.addHandler(handler)


def install(app: FastAPI, settings: Settings) -> None:
    """Повесить журнал запросов. Зовётся из `create_app`."""
    setup(settings)

    @app.middleware("http")
    async def _request_log(request: Request, call_next):
        rid = метка(request)
        request.state.request_id = rid
        request.state.user_id = None
        начало = time.perf_counter()

        try:
            response = await call_next(request)
        except Exception:
            # Подробности — сюда, и только сюда. Наружу уедет постоянный текст:
            # в сообщении исключения бывает кусок SQL, путь на томе или значение
            # ключа, и всё это клиенту знать незачем.
            беды.exception("rid=%s method=%s path=%s — необработанное исключение",
                           rid, request.method, request.url.path)
            response = ApiError(INTERNAL, INTERNAL_MESSAGE, 500).response()

        мс = (time.perf_counter() - начало) * 1000
        response.headers[ЗАГОЛОВОК] = rid
        журнал.info(
            "rid=%s user=%s method=%s path=%s status=%s ms=%.1f",
            rid, getattr(request.state, "user_id", None) or "-",
            request.method, request.url.path, response.status_code, мс)
        return response


__all__ = ["install", "setup", "метка", "ЗАГОЛОВОК", "журнал", "беды"]
