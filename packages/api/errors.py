"""
errors — один формат ошибки на всю службу.

Наружу уходит `{code, message, where}` — тот же дух, что у
`kyotsu.Notice` (кто, чем это называется в коде, что показать человеку). Причина
та же, что была у четырёх каналов предупреждений: два формата ошибки означают
два разбора в интерфейсе, и второй заводится молча — первым же обработчиком,
который вернул голый `HTTPException`.

Языки разведены намеренно, и это не небрежность:

* **наружу — английский** («коды, тексты ошибок,
  документация API — на английском»). Перевод делает интерфейс, по `code`;
* **внутрь — русский**, как у соседей (`OrchestratorError`, `MaterialsError`).
  `ConfigError` читает оператор, поднимающий контейнер, а не клиент API, и
  сообщение «том не задан» ему полезнее, чем `data_dir is required`.

`code` — короткое слово с подчёркиваниями (`not_found`, `quota_exceeded`), по
которому интерфейс различает случаи. Оно, а не текст, — договор: текст можно
переписать, код нельзя, поэтому коды перечисляются в докстроке того модуля,
который их выдаёт.

`where` — необязательное указание на место: имя поля (`body.email`), имя
параметра, идентификатор. Необязательное по той же причине, что `file` у
`Notice`: у «сессия истекла» никакого места нет и не будет.

Наружу не уезжает ни одна необработанная подробность: `500` отдаёт
`internal_error` с постоянным текстом, а настоящее исключение с трассировкой
уходит в журнал (`log.py`). Обратное — это утечка: текст исключения SQLAlchemy
содержит кусок запроса, текст `KeyError` — имя ключа, а иногда и значение.

**Та же форма — и в OpenAPI** (`ErrorOut`, `ОТВЕТЫ_БЕД`). Схема нужна не ради
красоты документа: из неё генерируется клиент сайта, и без неё генератор
выписал бы для каждого отказа `unknown`, а разбор ошибки в интерфейсе оказался
бы написан руками — то есть вторым описанием того же формата, которое разойдётся
с этим молча. Ответ описан один, под ключом `default`: он покрывает все коды
разом, и это правда — других форм отказа у службы нет. Заодно он вытесняет
`HTTPValidationError`, который FastAPI дописывает сам: наш `422` выглядит не так,
и оставить в документе чужую форму значило бы соврать про единственный отказ,
который клиент видит чаще прочих.
"""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException


class ApiError(Exception):
    """Своя беда службы. Как `OrchestratorError` у соседа — чтобы вызывающий
    отличал «службу позвали неправильно» от «упал чужой пакет»."""


class ConfigError(ApiError):
    """Служба настроена так, что работать нельзя: нет тома, короткий секрет.

    Отдельно от `ApiError`, потому что случается до первого запроса и читает её
    оператор. Ответа HTTP у неё нет: контейнер с такой ошибкой обязан не
    подняться, а не отвечать пятисотыми на каждый запрос.
    """


class ApiError(ApiError):
    """Ошибка, у которой есть форма ответа: код, текст, место, статус HTTP.

    Бросается из обработчика; в JSON её переводит `install`. Текст — по-английски
    и без подробностей, которых клиенту знать не нужно (путей на диске,
    идентификаторов чужих строк, кусков SQL).
    """

    def __init__(self, code: str, message: str, status: int = 400,
                 where: str | None = None):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.status = status
        self.where = where

    def to_dict(self) -> dict:
        """Тело ответа. Пустое `where` не занимает места — как в `Notice.to_dict`.

        `{"where": null}` читалось бы как «место спрашивали, и его нет», а правда
        другая: место к этой беде не относится.
        """
        body = {"code": self.code, "message": self.message}
        if self.where is not None:
            body["where"] = self.where
        return {"error": body}

    def response(self) -> JSONResponse:
        return JSONResponse(status_code=self.status, content=self.to_dict())


# ── та же беда, но для OpenAPI ───────────────────────────────────────────────
#
# Имена классов по-английски, как у форм запроса: они уезжают в схему и
# становятся именами типов в клиенте сайта.

class ErrorBody(BaseModel):
    """Тело ошибки: что случилось и, если это применимо, где."""

    code: str = Field(description="Stable machine-readable code, e.g. not_found")
    message: str = Field(description="Human-readable text, English")
    where: str | None = Field(
        default=None,
        description="Field or parameter the error is about, e.g. body.email")


class ErrorOut(BaseModel):
    """Единственная форма отказа службы. Другой нет ни у одного маршрута."""

    error: ErrorBody


# Что дописывается к каждому маршруту обоих входов (`app.create_app`).
# `default`, а не перечень кодов у каждого маршрута: такой перечень пришлось бы
# держать в согласии с докстроками пяти модулей, а разошёлся бы он молча —
# первым же новым отказом. Общий список кодов службы всё же есть (`КОДЫ`), но
# он один на всю службу и его держит в согласии проверка, а не внимательность.
ОТВЕТЫ_БЕД: dict = {
    "default": {"model": ErrorOut,
                "description": "Any refusal: one shape, machine-readable code"},
}


# Коды, которые выдаёт сам каркас. Подпакеты заводят свои и перечисляют у себя.
NOT_FOUND = "not_found"
METHOD_NOT_ALLOWED = "method_not_allowed"
VALIDATION_FAILED = "validation_failed"
INVALID_ID = "invalid_id"
INTERNAL = "internal_error"
HTTP_ERROR = "http_error"

# Постоянный текст пятисотки. Никогда не подменяется текстом исключения.
INTERNAL_MESSAGE = "Internal server error"


# ── перечень кодов ───────────────────────────────────────────────────────────
#
# Код — договор, и у каждого договора есть вторая сторона: интерфейс, который
# показывает человеку, что случилось и что делать. Пока перечня не было, эта
# сторона держалась на внимательности — новый код доезжал до экрана английским
# текстом службы посреди русской страницы, и замечал это человек, а не проверка.
#
# Отсюда список ниже. Он не подменяет докстроки модулей («какой маршрут чем
# отказывает» по-прежнему написано у маршрута) — он отвечает на другой вопрос:
# какие коды у службы есть вообще. Держат его в согласии с кодом две проверки:
#
# * `tests/api/test_error_codes.py` — каждый код, брошенный где-нибудь в
#   `packages/api`, записан здесь;
# * проверка сайта — у каждого записанного кода есть перевод.
#
# Наружу перечень уезжает полем `x-error-codes` документа OpenAPI (`install`):
# так сайту не приходится читать питон, чтобы узнать список.

# Отказы: сюда попадает всё, что служба бросает `ApiError`.
КОДЫ_ОТКАЗОВ: tuple[str, ...] = (
    "account_blocked", "agent_refused", "already_finished", "already_member",
    "bad_outputs", "bad_template", "build_failed", "csrf_failed",
    "diagram_failed", "email_not_confirmed", "email_taken",
    "endpoint_required", "export_too_large", "file_too_large", "forbidden",
    "http_error", "in_trash", "insufficient_scope", "internal_error",
    "invalid_credentials", "invalid_id", "invalid_key", "invalid_name",
    "invalid_nickname", "invalid_source", "invalid_token", "invalid_value",
    "kadai_failed", "key_required", "last_owner", "limit_exhausted",
    "method_not_allowed", "nickname_taken", "no_file", "no_invite", "no_key",
    "no_such_user", "not_found", "not_implemented", "not_in_trash",
    "not_ready", "note_required", "parse_failed", "personal_workspace",
    "project_exists", "project_required", "quota_exceeded", "rate_limited",
    "run_failed", "source_too_large", "tag_refused", "task_too_long",
    "token_expired", "token_not_allowed", "token_required", "token_revoked",
    "unauthenticated", "unauthorized", "unknown_job_kind",
    "unknown_job_status", "unknown_lang", "unknown_mode", "unknown_module",
    "unknown_plan", "unknown_provider", "unknown_role", "unknown_scope",
    "unknown_stage", "unknown_tag", "unknown_theme", "unsupported_type",
    "validation_failed",
)

# Беды заданий. Ответом HTTP они не приходят — приходят полем `error` карточки
# задания и событием потока, — но человеку показываются тем же словарём, что и
# отказы, и потому перечислены рядом (`jobs/worker.py`, `jobs/child.py`,
# `runs/handlers/common.py`).
КОДЫ_ЗАДАНИЙ: tuple[str, ...] = (
    "bad_result", "cancelled", "cancelled_before", "handler_crashed",
    "handler_failed", "no_handler", "timeout", "worker_lost",
)

КОДЫ: tuple[str, ...] = tuple(sorted(set(КОДЫ_ОТКАЗОВ) | set(КОДЫ_ЗАДАНИЙ)))

# Что стоит в коде, когда обработчик отдал голый `HTTPException`.
_BY_STATUS = {404: NOT_FOUND, 405: METHOD_NOT_ALLOWED}


def дописать_коды(app: FastAPI) -> None:
    """Положить перечень кодов в документ OpenAPI полем `x-error-codes`.

    Полем документа, а не перечислением в `enum` у `ErrorBody.code`: `enum`
    превратил бы код в закрытый тип в сгенерированном клиенте, и служба,
    отдавшая новый код старому сайту, ломала бы у него разбор ответа. Здесь же
    это справка — список того, что бывает, — и читает её проверка переводов, а
    не рабочий код.
    """
    исходный = app.openapi

    def openapi() -> dict:
        документ = исходный()
        документ.setdefault("x-error-codes", list(КОДЫ))
        return документ

    app.openapi = openapi                                    # type: ignore[method-assign]


def _where_of(loc) -> str | None:
    """Место из `loc` pydantic: `("body", "email")` → `"body.email"`.

    Числа в пути (индекс элемента списка) остаются числами: `body.files.0.name`
    — ровно то, что интерфейс подсветит.
    """
    parts = [str(p) for p in loc or ()]
    return ".".join(parts) if parts else None


def install(app: FastAPI) -> None:
    """Повесить обработчики на приложение. Зовётся из `create_app`.

    Необработанное исключение сюда не попадает намеренно: его ловит middleware
    журнала (`log.py`), потому что ответ с пятисоткой обязан нести тот же
    `X-Request-Id`, что и запись в журнале, — иначе жалобу «у меня всё
    сломалось» не связать с трассировкой.
    """

    дописать_коды(app)

    @app.exception_handler(ApiError)
    async def _api_error(request: Request, exc: ApiError) -> JSONResponse:
        return exc.response()

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request,
                          exc: RequestValidationError) -> JSONResponse:
        # Берём первую беду: клиенту нужен адрес, а не полный список — полный
        # список получится сам, по одной правке за раз.
        first = (exc.errors() or [{}])[0]
        message = str(first.get("msg") or "Request validation failed")
        return ApiError(VALIDATION_FAILED, message, 422,
                        where=_where_of(first.get("loc"))).response()

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request,
                    exc: StarletteHTTPException) -> JSONResponse:
        code = _BY_STATUS.get(exc.status_code, "http_error")
        return ApiError(code, str(exc.detail), exc.status_code).response()


__all__ = ["ApiError", "ConfigError", "ApiError", "install", "дописать_коды",
           "ErrorOut", "ErrorBody", "ОТВЕТЫ_БЕД",
           "КОДЫ", "КОДЫ_ОТКАЗОВ", "КОДЫ_ЗАДАНИЙ",
           "NOT_FOUND", "METHOD_NOT_ALLOWED", "VALIDATION_FAILED",
           "INVALID_ID", "INTERNAL", "HTTP_ERROR", "INTERNAL_MESSAGE"]
