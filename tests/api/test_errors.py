"""
Один формат ошибки — на все четыре источника беды.

Источников четыре, и они разные по природе: наш `ApiError`, отсутствующий
маршрут (Starlette), непрошедшая проверка типа (pydantic) и необработанное
исключение (что угодно). Пока формат один, интерфейс разбирает ответ одним
куском кода; стоит одному из четырёх ответить по-своему — и разбора станет два,
причём второй заведётся молча, первым же обработчиком, вернувшим голый
`HTTPException`.

Отдельно и главное: **пятисотка не выносит наружу ничего**. Текст исключения
SQLAlchemy содержит кусок запроса, текст `KeyError` — имя ключа, а бывает, и
значение; путь в `FileNotFoundError` — раскладку тома.
"""
from __future__ import annotations

import pytest

from api.errors import ApiError
from api.ids import check_id, new_id

from .conftest import СЕКРЕТ_В_ИСКЛЮЧЕНИИ


# ── четыре источника, одна форма ─────────────────────────────────────────────

def test_ошибка_обработчика(client):
    ответ = client.get("/_test/api-error")
    assert ответ.status_code == 418
    assert ответ.json() == {"error": {"code": "teapot", "message": "I am a teapot",
                                      "where": "query.tea"}}


def test_неизвестный_маршрут(client):
    ответ = client.get("/такого-нет")
    assert ответ.status_code == 404
    беда = ответ.json()["error"]
    assert беда["code"] == "not_found"
    # Места у этой беды нет — и `null` вместо него читался бы как «спрашивали».
    assert "where" not in беда


def test_не_тот_метод(client):
    ответ = client.post("/health")
    assert ответ.status_code == 405
    assert ответ.json()["error"]["code"] == "method_not_allowed"


def test_проверка_типа_называет_место(client):
    """`where` тут — весь смысл ответа: клиенту нужен адрес правки."""
    ответ = client.get("/_test/number?n=не-число")
    assert ответ.status_code == 422
    беда = ответ.json()["error"]
    assert беда["code"] == "validation_failed"
    assert беда["where"] == "query.n"


def test_необработанное_исключение_становится_пятисоткой(client):
    ответ = client.get("/_test/boom")
    assert ответ.status_code == 500
    assert ответ.json() == {"error": {"code": "internal_error",
                                      "message": "Internal server error"}}


def test_пятисотка_не_выносит_подробностей(client):
    """Ни текста исключения, ни имени класса, ни трассировки."""
    ответ = client.get("/_test/boom")
    тело = ответ.text
    assert СЕКРЕТ_В_ИСКЛЮЧЕНИИ not in тело
    assert "RuntimeError" not in тело
    assert "Traceback" not in тело


def test_все_четыре_отвечают_одной_формой(client):
    """Разбор в интерфейсе — один кусок кода, и это проверяется, а не обещается."""
    for путь in ("/_test/api-error", "/такого-нет", "/_test/number?n=x",
                 "/_test/boom"):
        беда = client.get(путь).json()["error"]
        assert set(беда) <= {"code", "message", "where"}, путь
        assert isinstance(беда["code"], str) and беда["code"], путь
        assert isinstance(беда["message"], str) and беда["message"], путь


def test_коды_и_тексты_по_английски(client):
    """Наружу — английский, перевод делает интерфейс."""
    for путь in ("/такого-нет", "/_test/boom"):
        беда = client.get(путь).json()["error"]
        assert беда["code"].isascii(), путь
        assert беда["message"].isascii(), путь


# ── сама форма ───────────────────────────────────────────────────────────────

def test_пустое_место_не_занимает_места():
    assert ApiError("gone", "Gone", 410).to_dict() == {
        "error": {"code": "gone", "message": "Gone"}}


def test_ошибка_остаётся_исключением():
    with pytest.raises(ApiError) as беда:
        raise ApiError("nope", "No", 400)
    assert беда.value.code == "nope"


# ── идентификаторы наружу ────────────────────────────────────────────────────

def test_свой_идентификатор_проходит():
    ид = new_id()
    assert check_id(ид, where="path.project_id") == ид


@pytest.mark.parametrize("чужое", [
    "",
    "не-идентификатор",
    "../../etc/passwd",
    "/data/users/1/projects/2",
    "0123456789abcdef",                                  # 16-hex материала
    "00000000-0000-0000-0000-000000000000",              # не версия 4
    None,
])
def test_чужая_форма_отвергается_до_похода_в_базу(чужое):
    """Заодно и путь: пока клиент не называет путь, `../` ему негде написать."""
    with pytest.raises(ApiError) as беда:
        check_id(чужое, where="path.project_id")
    assert беда.value.code == "invalid_id"
    assert беда.value.where == "path.project_id"
    assert беда.value.status == 400
