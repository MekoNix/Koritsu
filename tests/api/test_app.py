"""
Приложение: здоровье, два входа, метка запроса, журнал без содержимого.

`/health` проверяется вместе с базой не для полноты: процесс, живой при мёртвой
базе, — худший случай для прокси, потому что он остаётся
под нагрузкой и отвечает пятисотыми на каждый запрос.
"""
from __future__ import annotations

import logging

from api.log import ЗАГОЛОВОК


# ── здоровье ─────────────────────────────────────────────────────────────────

def test_здоровье_отвечает_и_называет_режим(client):
    ответ = client.get("/health")
    assert ответ.status_code == 200
    assert ответ.json() == {"status": "ok", "env": "dev", "db": "ok"}


def test_здоровье_смотрит_в_базу_а_не_подразумевает_её(client, app):
    """База отвечать перестала — прокси обязан узнать об этом от нас."""
    from sqlalchemy import create_engine

    app.state.db.dispose()
    # База «переехала» в несуществующий каталог: соединиться нечем.
    app.state.db.engine = create_engine("sqlite:////нет-такого-каталога/k.db")
    ответ = client.get("/health")
    assert ответ.status_code == 503
    assert ответ.json()["db"] == "error"


# ── два входа ────────────────────────────────────────────────────────────────

def test_внешний_вход_заведён_с_первого_дня(client):
    """`/api/v1/` версионируется и документируется наружу, поэтому версия
    должна стоять в URL до первого внешнего клиента, а не после."""
    ответ = client.get("/api/v1/ping")
    assert ответ.status_code == 200
    assert ответ.json() == {"pong": True, "api": "v1"}


def test_вход_сайта_отвечает_на_несуществующее(client):
    """Беда на несуществующем маршруте `/api` — той же формы, что у всех прочих.

    Адрес намеренно ничей: `/api/projects` и `/api/workspaces` заводит другой
    подпакет, и проверять на них «маршрута нет» значило бы проверять, что его
    ещё не написали. Проверяем то, что и проверяли: вход `/api` есть, и незнакомый
    адрес на нём отвечает `{code, message}`, а не голым текстом Starlette.
    """
    ответ = client.get("/api/нет-такого-маршрута")
    assert ответ.status_code == 404
    assert ответ.json()["error"]["code"] == "not_found"


def test_описание_апи_собирается(client):
    """OpenAPI — из него генерируется клиент сайта; если он не собирается,
    расходиться сайту и API будет уже негде."""
    схема = client.get("/openapi.json").json()
    assert "/api/v1/ping" in схема["paths"]


# ── метка запроса ────────────────────────────────────────────────────────────

def test_метка_есть_в_каждом_ответе(client):
    метка = client.get("/health").headers[ЗАГОЛОВОК]
    assert метка
    # Вторая — другая: метка про запрос, а не про процесс.
    assert client.get("/health").headers[ЗАГОЛОВОК] != метка


def test_чужая_метка_сохраняется(client):
    """Её ставит прокси; переписав её, мы порвали бы связь со его журналом."""
    ответ = client.get("/health", headers={ЗАГОЛОВОК: "caddy-42_a.b"})
    assert ответ.headers[ЗАГОЛОВОК] == "caddy-42_a.b"


def test_чужая_метка_дурной_формы_заменяется(client):
    """Перенос строки внутри метки дорисовал бы в журнал поддельную запись."""
    подделка = "caddy-1 status=200 user=admin"   # пробел: журнал идёт по полям
    ответ = client.get("/health", headers={ЗАГОЛОВОК: подделка})
    assert ответ.headers[ЗАГОЛОВОК] != подделка


def test_метка_есть_и_на_пятисотке(client):
    """Ровно тот случай, ради которого метка заведена: жалоба «всё сломалось»
    обязана находиться в журнале по метке из ответа."""
    ответ = client.get("/_test/boom", headers={ЗАГОЛОВОК: "zhaloba-1"})
    assert ответ.status_code == 500
    assert ответ.headers[ЗАГОЛОВОК] == "zhaloba-1"


# ── журнал ───────────────────────────────────────────────────────────────────

def test_журнал_пишет_метку_маршрут_код_и_длительность(client, caplog):
    with caplog.at_level(logging.INFO, logger="api.request"):
        client.get("/health", headers={ЗАГОЛОВОК: "proba-1"})
    строка = "\n".join(r.getMessage() for r in caplog.records)
    for поле in ("rid=proba-1", "method=GET", "path=/health", "status=200",
                 "ms="):
        assert поле in строка, f"нет поля {поле}: {строка}"


def test_журнал_не_пишет_ни_строки_запроса_ни_заголовков(client, caplog):
    """Содержимое тел не пишется никогда. Строка запроса
    и заголовки — то же самое: в них уезжают cookie сессии и токен
    подтверждения почты."""
    with caplog.at_level(logging.INFO, logger="api.request"):
        client.get("/_test/number?n=1234567",
                   headers={"Cookie": "koritsu=tayna-sessii"})
    строка = "\n".join(r.getMessage() for r in caplog.records)
    assert "1234567" not in строка
    assert "tayna-sessii" not in строка
    assert "path=/_test/number" in строка


def test_подробности_пятисотки_остаются_в_журнале(client, caplog):
    """Наружу — постоянный текст, внутрь — трассировка: иначе беду не починить."""
    from .conftest import СЕКРЕТ_В_ИСКЛЮЧЕНИИ

    with caplog.at_level(logging.ERROR, logger="api.error"):
        client.get("/_test/boom")
    assert СЕКРЕТ_В_ИСКЛЮЧЕНИИ in caplog.text
