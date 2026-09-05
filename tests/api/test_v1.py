"""
Внешний вход `/api/v1`: тот же обработчик, другой способ сказать, кто ты.

Здесь проверяется ровно то, ради чего вход заведён отдельным:

* **один и тот же сценарий** — проект, материал, значение тега — проходит через
  `/api/v1` с ключом так же, как через `/api` с сессией. Не «маршрут отвечает
  200», а вся цепочка: иначе разъезд между входами обнаружился бы на третьем
  запросе внешнего клиента, а не здесь;
* **без ключа туда нельзя**, и отказ говорит, чего не хватило;
* **права ключа проверяются** — на записи, на загрузке, на запуске заданий;
* **аккаунты, ключи и админка ключом не открываются**;
* **отозванный ключ мёртв сразу**, а не с ближайшего перезапуска;
* **60 запросов в минуту** — потолок, а не пожелание;
* `operation_id` под вторым входом отличаются суффиксом `_v1` — иначе клиент,
  сгенерированный из документа, получит один метод вместо двух.
"""
from __future__ import annotations

import re

import pytest

from api.tokens import service as ключи

from .c_fixtures import (войти, клиент, личное_id,  # noqa: F401
                         создать_проект, сосед, хозяин)
from .d_fixtures import сделано, файл

ПУТЬ_V1 = "/api/v1"


@pytest.fixture(autouse=True)
def _чистые_счётчики():
    """Окна лимита живут в памяти процесса, а тесты идут один за другим."""
    ключи.забыть_лимиты()
    yield
    ключи.забыть_лимиты()


def выдать(клиент, права) -> str:
    """Завести ключ через сайт и вернуть его строку — как это делает человек."""
    ответ = клиент.post("/api/tokens", json={"name": "скрипт", "scopes": права})
    assert ответ.status_code == 201, ответ.text
    return ответ.json()["token"]


def на_ключ(app, клиент, строка: str) -> None:
    """Снять подмену `current_user` и предъявлять дальше только ключ.

    Без снятия тест проверял бы подмену, а не ключ: `current_user` подменён
    объектом пользователя, и до разбора заголовка дело не дошло бы.
    """
    app.dependency_overrides.clear()
    клиент.headers["Authorization"] = f"Bearer {строка}"


@pytest.fixture
def связка(app, клиент, хозяин):
    """Ключ на все права и личное пространство; клиент уже ходит ключом."""
    ws = личное_id(клиент)
    строка = выдать(клиент, list(ключи.ПРАВА))
    на_ключ(app, клиент, строка)
    return {"token": строка, "workspace_id": ws, "params": {"workspace_id": ws}}


# ── тот же сценарий, другой вход ─────────────────────────────────────────────

def test_проект_материал_значение_через_ключ(app, клиент, связка):
    """Сквозной путь внешнего клиента: завёл проект, положил файл, записал тег."""
    проект = клиент.post(f"{ПУТЬ_V1}/projects",
                         data={"workspace_id": связка["workspace_id"],
                               "name": "через ключ"})
    assert проект.status_code == 201, проект.text
    ид = проект.json()["id"]

    видно = клиент.get(f"{ПУТЬ_V1}/projects", params=связка["params"])
    assert видно.status_code == 200, видно.text
    assert [p["id"] for p in видно.json()["projects"]] == [ид]

    загрузка = клиент.post(f"{ПУТЬ_V1}/projects/{ид}/materials",
                           files=файл("solver.py", b"def f():\n    return 1\n"))
    assert загрузка.status_code == 202, загрузка.text
    assert загрузка.json()["job"]["kind"] == "parse"

    # Значение — по форме своего типа: `PUT` разбирает его тем же
    # `hokoku.value_from_json`, которым его прочтёт сборщик отчёта.
    значение = клиент.put(f"{ПУТЬ_V1}/projects/{ид}/values/цель",
                          json={"type": "text", "text": "проверить ключ"})
    assert значение.status_code == 200, значение.text
    assert значение.json()["source"] == "manual"

    прочитано = клиент.get(f"{ПУТЬ_V1}/projects/{ид}/values")
    assert прочитано.status_code == 200
    assert "цель" in прочитано.json()["values"]


def test_задания_видны_ключом(app, клиент, связка):
    """Внешнему клиенту обещаны задания, а не только проекты."""
    список = клиент.get(f"{ПУТЬ_V1}/jobs")
    assert список.status_code == 200
    assert список.json()["jobs"] == []


def test_модули_и_схемы_отвечают_и_под_вторым_входом(app, клиент, связка):
    """Зеркало маршрута — это тот же обработчик, а не только строка в документе.

    Проверяется настоящим запросом намеренно: копия объявления, потерявшая
    форму ответа или зависимость, в схеме выглядела бы целой.
    """
    assert клиент.get(f"{ПУТЬ_V1}/modules").status_code == 200
    assert клиент.get(f"{ПУТЬ_V1}/flowcharts/modes").status_code == 200
    assert клиент.get(f"{ПУТЬ_V1}/uml/themes").status_code == 200


def test_выгрузка_и_скачивание_архива_через_ключ(app, клиент, хозяин):
    """Скрипт, забирающий архив проекта, — это и есть внешний клиент.

    Полный путь через второй вход: поставил задание, дождался, скачал артефакт.
    Скачивание проверяется настоящим запросом, а не строкой в документе: у
    выгрузки нет своего маршрута для этого, и архив достаётся общим маршрутом
    артефактов — тем самым, которым достаются схемы и собранные отчёты.
    """
    проект = создать_проект(клиент, личное_id(клиент), name="выгрузка")
    на_ключ(app, клиент, выдать(клиент, list(ключи.ПРАВА)))

    ответ = клиент.post(f"{ПУТЬ_V1}/projects/{проект['id']}/export")
    assert ответ.status_code == 202, ответ.text
    assert ответ.json()["job"]["kind"] == "export"

    art = сделано(app, ответ)["artifact"]
    архив = клиент.get(
        f"{ПУТЬ_V1}/projects/{проект['id']}/artifacts/{art}")
    assert архив.status_code == 200, архив.text
    assert архив.headers["content-type"] == "application/zip"


def test_выгрузка_просит_право_записи(app, клиент, хозяин):
    """Архив ложится на том, в квоту владельца проекта, — значит это запись.

    Ключу на чтение её не дают, хотя всё, что попадает в архив, он и так может
    прочитать по одному файлу: право потратить чужие байты — отдельное право.
    """
    проект = создать_проект(клиент, личное_id(клиент), name="выгрузка")
    на_ключ(app, клиент, выдать(клиент, [ключи.PROJECTS_READ, ключи.RUNS_RUN]))

    ответ = клиент.post(f"{ПУТЬ_V1}/projects/{проект['id']}/export")
    assert ответ.status_code == 403, ответ.text
    assert ответ.json()["error"]["code"] == "insufficient_scope"
    assert "projects:write" in ответ.json()["error"]["message"]


# ── без ключа и не тем ключом ────────────────────────────────────────────────

def test_без_ключа_не_пускает(клиент):
    """Вход `/api/v1` берёт только ключ: cookie туда не годится намеренно —
    он идёт мимо Anubis и мимо CSRF."""
    ответ = клиент.get(f"{ПУТЬ_V1}/projects", params={"workspace_id": "х"})
    assert ответ.status_code == 401
    assert ответ.json()["error"]["code"] == "token_required"


def test_ping_открыт_и_без_ключа(клиент):
    """Единственный маршрут входа, который отвечает всем, — и он молчит про
    внутренности."""
    ответ = клиент.get(f"{ПУТЬ_V1}/ping")
    assert ответ.status_code == 200
    assert ответ.json() == {"pong": True, "api": "v1"}


def test_выдуманный_ключ_401(клиент):
    клиент.headers["Authorization"] = "Bearer kor_no-such-token"
    ответ = клиент.get(f"{ПУТЬ_V1}/projects", params={"workspace_id": "х"})
    assert ответ.status_code == 401
    assert ответ.json()["error"]["code"] == "invalid_token"


def test_отозванный_ключ_мёртв_сразу(app, клиент, хозяин):
    """Отзыв — это отзыв, а не «с ближайшего перезапуска»."""
    параметры = {"workspace_id": личное_id(клиент)}
    заведён = клиент.post("/api/tokens",
                          json={"name": "скрипт",
                                "scopes": [ключи.PROJECTS_READ]}).json()
    на_ключ(app, клиент, заведён["token"])
    assert клиент.get(f"{ПУТЬ_V1}/projects",
                      params=параметры).status_code == 200

    # Отзыв делается сессией сайта — ключом в свои же ключи ходить нельзя.
    del клиент.headers["Authorization"]
    войти(app, хозяин)
    assert клиент.delete(f"/api/tokens/{заведён['id']}").status_code == 200

    на_ключ(app, клиент, заведён["token"])
    ответ = клиент.get(f"{ПУТЬ_V1}/projects", params=параметры)
    assert ответ.status_code == 401
    assert ответ.json()["error"]["code"] == "token_revoked"


# ── права ────────────────────────────────────────────────────────────────────

def test_ключ_на_чтение_не_пишет(app, клиент, хозяин):
    """`projects:read` читает и не создаёт: в этом весь смысл разделения."""
    ws = личное_id(клиент)
    на_ключ(app, клиент, выдать(клиент, [ключи.PROJECTS_READ]))

    assert клиент.get(f"{ПУТЬ_V1}/projects",
                      params={"workspace_id": ws}).status_code == 200
    ответ = клиент.post(f"{ПУТЬ_V1}/projects",
                        data={"workspace_id": ws, "name": "нельзя"})
    assert ответ.status_code == 403
    assert ответ.json()["error"]["code"] == "insufficient_scope"
    assert "projects:write" in ответ.json()["error"]["message"]


def test_загрузка_просит_своё_право(app, клиент, хозяин):
    """Ключ CI, который льёт файлы, и ключ, который правит проекты, — разные
    ключи (`materials:write` отдельным правом)."""
    проект = создать_проект(клиент, личное_id(клиент), name="права")
    на_ключ(app, клиент, выдать(клиент, [ключи.PROJECTS_WRITE]))

    ответ = клиент.post(f"{ПУТЬ_V1}/projects/{проект['id']}/materials",
                        files=файл("a.py", b"x = 1\n"))
    assert ответ.status_code == 403
    assert ответ.json()["error"]["code"] == "insufficient_scope"
    assert "materials:write" in ответ.json()["error"]["message"]


def test_постановка_задания_просит_право_запуска(app, клиент, хозяин):
    """`runs:run` — это «тратить деньги владельца», и оно отдельное."""
    проект = создать_проект(клиент, личное_id(клиент), name="права")
    на_ключ(app, клиент,
            выдать(клиент, [ключи.PROJECTS_WRITE, ключи.MATERIALS_WRITE]))

    ответ = клиент.post(f"{ПУТЬ_V1}/jobs",
                        json={"kind": "parse", "project_id": проект["id"],
                              "payload": {}})
    assert ответ.status_code == 403
    assert ответ.json()["error"]["code"] == "insufficient_scope"
    assert "runs:run" in ответ.json()["error"]["message"]


def test_запуск_не_даёт_чтения(app, клиент, хозяин):
    """Умолчание по методу — не «всё можно»: `runs:run` чтения не открывает."""
    ws = личное_id(клиент)
    на_ключ(app, клиент, выдать(клиент, [ключи.RUNS_RUN]))

    ответ = клиент.get(f"{ПУТЬ_V1}/projects", params={"workspace_id": ws})
    assert ответ.status_code == 403
    assert ответ.json()["error"]["code"] == "insufficient_scope"


def test_право_объявленное_в_маршруте_старше_умолчания(app, клиент, хозяин):
    """Второй способ повесить право — прямо в маршруте (`require_scope`).

    Он и проверяется здесь, потому что им пользуются соседние подпакеты: объявленное
    в маршруте обязано **заменять** умолчание по методу, а не добавляться к
    нему, — иначе `POST` с `require_scope(RUNS_RUN)` тихо потребовал бы ещё и
    `projects:write`, и ключ CI перестал бы работать без единой правки в нём.
    """
    from fastapi import Depends

    from api.auth import require_scope

    @app.post("/api/_test/run", operation_id="test_run",
              dependencies=[Depends(require_scope(ключи.RUNS_RUN))],
              summary="Test route", description="Test route.")
    def _прогон() -> dict:
        return {"ok": True}

    личное_id(клиент)
    на_ключ(app, клиент, выдать(клиент, [ключи.RUNS_RUN]))
    assert клиент.post("/api/_test/run").status_code == 200

    ключи.забыть_лимиты()
    del клиент.headers["Authorization"]
    войти(app, хозяин)
    на_ключ(app, клиент, выдать(клиент, [ключи.PROJECTS_WRITE]))
    ответ = клиент.post("/api/_test/run")
    assert ответ.status_code == 403
    assert ответ.json()["error"]["code"] == "insufficient_scope"


def test_сессия_сайта_прав_не_спрашивает(app, клиент, хозяин):
    """Права придуманы для ключа в чужом скрипте, а не для человека в браузере:
    `require_scope` пропускает сессию всегда."""
    from fastapi import Depends

    from api.auth import require_scope

    @app.post("/api/_test/run2", operation_id="test_run2",
              dependencies=[Depends(require_scope(ключи.RUNS_RUN))],
              summary="Test route", description="Test route.")
    def _прогон() -> dict:
        return {"ok": True}

    assert клиент.post("/api/_test/run2").status_code == 200


# ── куда ключом нельзя ───────────────────────────────────────────────────────

@pytest.mark.parametrize("путь", ["/api/auth/me", "/api/keys", "/api/tokens",
                                  "/api/admin/users"])
def test_аккаунты_ключи_и_админка_ключом_не_открываются(app, клиент, хозяин,
                                                        путь):
    """Аккаунты и ключи моделей через токен не даются.

    Отказ своим кодом, а не общим `unauthenticated`: человек, положивший ключ
    в скрипт, обязан узнать, что ключом это не делается, а не гадать.
    """
    на_ключ(app, клиент, выдать(клиент, list(ключи.ПРАВА)))

    ответ = клиент.get(путь)
    assert ответ.status_code == 401, ответ.text
    assert ответ.json()["error"]["code"] == "token_not_allowed"


def test_аккаунтов_нет_и_в_документе(app):
    """Под `/api/v1` их не просто закрыли — их там нет вовсе."""
    пути = [p for p in app.openapi()["paths"] if p.startswith("/api/v1")]
    assert пути
    for кусок in ("/auth", "/keys", "/tokens", "/admin", "/billing"):
        assert not [p for p in пути if кусок in p], кусок


# ── лимит ────────────────────────────────────────────────────────────────────

def test_шестьдесят_запросов_в_минуту(app, клиент, связка):
    """Потолок на ключ. Считается в памяти процесса — см. `tokens`."""
    for номер in range(ключи.ЛИМИТ_В_МИНУТУ):
        ответ = клиент.get(f"{ПУТЬ_V1}/projects", params=связка["params"])
        assert ответ.status_code == 200, (номер, ответ.text)
    ответ = клиент.get(f"{ПУТЬ_V1}/projects", params=связка["params"])
    assert ответ.status_code == 429
    assert ответ.json()["error"]["code"] == "rate_limited"


def test_отметка_использования_пишется_но_не_на_каждый_запрос(app, клиент,
                                                              связка):
    """«Когда ключом пользовались» видно — но чтение списка проектов внешним
    клиентом не должно превращаться в запись в базу на каждый запрос."""
    from sqlalchemy import select

    from api.tokens.models import ApiToken

    def отметка():
        with app.state.db.session_scope() as s:
            return s.scalar(select(ApiToken)).last_used_at

    клиент.get(f"{ПУТЬ_V1}/projects", params=связка["params"])
    было = отметка()
    assert было is not None

    клиент.get(f"{ПУТЬ_V1}/projects", params=связка["params"])
    assert отметка() == было


def test_лимит_не_трогает_сессию_сайта(app, клиент, хозяин):
    """Лимит придуман для ключа в чужом скрипте, а не для человека в браузере."""
    параметры = {"workspace_id": личное_id(клиент)}
    for _ in range(ключи.ЛИМИТ_В_МИНУТУ + 5):
        assert клиент.get("/api/projects",
                          params=параметры).status_code == 200


# ── документ ─────────────────────────────────────────────────────────────────

def операции(схема):
    методы = ("get", "post", "put", "patch", "delete")
    for путь, узел in схема["paths"].items():
        for метод, операция in узел.items():
            if метод in методы:
                yield путь, метод, операция


def test_у_каждой_операции_v1_свой_суффикс(app):
    """Два входа с одинаковым `operationId` дали бы клиенту один метод вместо
    двух, и какой именно — решил бы порядок обхода генератора."""
    имена = [(путь, о["operationId"])
             for путь, _, о in операции(app.openapi())
             if путь.startswith("/api/v1") and путь != "/api/v1/ping"]
    assert имена
    for путь, имя in имена:
        assert имя.endswith("_v1"), f"{путь}: {имя}"
        assert имя.isascii() and re.match(r"\A[a-z][a-z0-9_]*\Z", имя), имя


def test_имена_без_суффикса_есть_на_входе_сайта(app):
    """Суффикс — это тот же маршрут, а не другой: у каждого `…_v1` обязан быть
    близнец на входе сайта. Иначе наружу уехало то, чего у сайта нет."""
    схема = app.openapi()
    сайт = {о["operationId"] for путь, _, о in операции(схема)
            if not путь.startswith("/api/v1")}
    for путь, _, о in операции(схема):
        if путь.startswith("/api/v1") and путь != "/api/v1/ping":
            assert о["operationId"][:-len("_v1")] in сайт, путь


def test_inline_у_артефакта_есть_на_обоих_входах(app):
    """`?inline=1` — свойство маршрута, а не входа.

    Скачивание артефакта включено под `/api/v1` тем же роутером, что и на входе
    сайта, поэтому новый параметр обязан быть в обоих описаниях: внешний
    клиент, забирающий собранный PDF, показывает его так же, как сайт.
    """
    для_входа = {}
    for путь, _, о in операции(app.openapi()):
        if о["operationId"] in ("download_artifact", "download_artifact_v1"):
            для_входа[о["operationId"]] = {п["name"] for п in о.get("parameters", ())}
    assert set(для_входа) == {"download_artifact", "download_artifact_v1"}
    for имя, поля in для_входа.items():
        assert "inline" in поля, имя


def test_объявленные_права_ссылаются_на_живые_маршруты(app):
    """`auth.СКОПЫ` держится на `operation_id`, а его пишет чужой файл.

    Переименованный маршрут не открыл бы дыру (право свалилось бы к умолчанию
    по методу, то есть стало бы строже), но перестал бы значить то, что
    задумано: загрузка материала снова просила бы `projects:write`. Ловится это
    только так — сверкой словаря с живым документом.
    """
    from api import auth

    имена = {о["operationId"] for _, _, о in операции(app.openapi())}
    for имя in auth.СКОПЫ:
        assert имя in имена, f"в СКОПЫ есть {имя}, а маршрута такого нет"


def test_вход_описан_отдельным_тегом(app):
    """Наружу документируется и версионируется только `/api/v1`, значит у
    него есть своё описание — как им пользоваться и чем он берётся."""
    теги = {т["name"]: т.get("description", "") for т in app.openapi()["tags"]}
    assert "v1" in теги
    описание = теги["v1"]
    assert описание.isascii() and "Bearer" in описание
    for право in ключи.ПРАВА:
        assert право in описание
