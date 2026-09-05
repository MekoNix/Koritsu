"""
Сквозной сценарий второго этапа: очередь, модель, поток, ключ, выгрузка.

Продолжение `test_e2e.py` и по той же причине. Каждый кусок проверен своим
тестом: очередь — `test_jobs`, прогоны — `test_runs`, потоки — `test_sse`,
ключи — `test_v1`, выгрузка — `test_export`. Ломается же не кусок, а стык между
кусками, и стыков здесь восемь:

* загрузка отвечает `202`, и материала в этот миг **нет**; карточка появляется
  только после того, как воркер взял задание;
* прогон берёт ключ, заведённый другим маршрутом, и платит по лимиту, который
  считает третий;
* события задания читаются двумя способами — списком и потоком, — и оба обязаны
  показывать одно и то же;
* уведомление о конце задания пишет воркер, а показывает его колокольчик;
* откат тега поверх значения, записанного моделью, — это две части службы в
  одной строке;
* блок-схема строится по материалу, разобранному очередью;
* архив выгрузки складывается заданием, а скачивается общим маршрутом
  артефактов;
* тот же путь проходится второй раз внешним ключом, под `/api/v1`.

Что здесь настоящее: вошедший (почта, пароль, cookie, заслон CSRF), очередь
(`Worker.run_once(inline=True)` — тот же обработчик, только без подпроцесса),
ключ модели (шифруется и расшифровывается `resolve_key`), тома, архивы и
события. Подделан ровно один шов — провод к модели (`b_fixtures`): сети в
тестах нет, а всё, что за проводом, — лестница, лимит, журнал, склейка
текста — своё.

**Отказы собираются, а не проверяются по месту** — то же правило, что в
`test_e2e`: всякий ответ с кодом 400 и выше ложится в общий список, и его форму
проверяет один тест на весь сценарий. Проверка по месту закрепляла бы форму тех
отказов, о которых тест помнил.
"""
from __future__ import annotations

import dataclasses
import io
import json
import re
import zipfile

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from api import Settings, create_app
from api.accounts.models import User
from api.export import handlers as выгрузка
from api.tokens import service as ключи

from .b_fixtures import (КЛЮЧ, ПОСТАВЩИК, модель, прогнать,  # noqa: F401
                         сценарий, _чистый_реестр)
from .c_fixtures import docx_байты, войти_по_настоящему
from .d_fixtures import докрутить, файл

# Почта человека, который проходит весь сценарий. Одна на файл: разные тесты
# заводят свои приложения и свои тома, и пересечься им негде.
ПОЧТА = "этап2@пример.рф"

# Что модель «отвечает» на просьбу заполнить тег «цель». Разбирает этот ответ
# настоящая лестница оркестратора, поэтому форма — та, которую она ждёт.
ЦЕЛЬ = {"type": "markdown", "text": "Цель работы — сравнить сортировки."}

# Исходник материала: он же попадёт в блок-схему. Ветвление в нём есть
# намеренно — схема из линейного кода вышла бы одинаковой при любой поломке
# разборщика.
ИСХОДНИК = ("def выбрать(n):\n"
            "    if n > 0:\n"
            "        return 'плюс'\n"
            "    return 'минус'\n")

ИМЯ_ИСХОДНИКА = "solver.py"

КОД_RE = re.compile(r"\A[a-z][a-z0-9_]*\Z")


# ── оснастка ─────────────────────────────────────────────────────────────────

@pytest.fixture
def правки(request) -> dict:
    """Правки настроек для теста (`parametrize(..., indirect=True)`).

    Через фикстуру, а не присваиванием полю: `Settings` заморожены намеренно, и
    тест, обходящий заморозку, проверял бы поведение, которого в работе нет.
    """
    return dict(getattr(request, "param", {}) or {})


@pytest.fixture
def settings(tmp_path, правки) -> Settings:
    return Settings.for_tests(tmp_path / "том", **правки)


@pytest.fixture
def app(settings):
    """Приложение на своём томе. Потоки в нём опрашивают базу часто и живут
    недолго: `TestClient` собирает ответ целиком, и поток, который не кончается
    сам, в тесте не кончится никогда (`test_sse` разбирает это подробно)."""
    собрано = create_app(settings)
    собрано.state.settings = dataclasses.replace(собрано.state.settings,
                                                 sse_poll_s=0.01, sse_max_s=10.0)
    return собрано


@pytest.fixture
def отказы() -> list:
    """Все ответы с кодом 400 и выше, случившиеся за сценарий."""
    return []


@pytest.fixture
def клиент(app, отказы):
    """Клиент со своими cookie. Никаких подмен зависимостей: вход настоящий."""
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def шаг(клиент, отказы, метод: str, путь: str, **kwargs):
    """Запрос, у которого отказ не теряется — см. докстроку модуля."""
    ответ = getattr(клиент, метод)(путь, **kwargs)
    if ответ.status_code >= 400:
        отказы.append((метод.upper(), путь, ответ.status_code, ответ.json()))
    return ответ


def строка_человека(app, email: str) -> User:
    """Строка пользователя из базы — по почте, как её видит владелец службы."""
    with app.state.db.session_scope() as s:
        user = s.scalar(select(User).where(User.email == email))
        s.expunge(user)
    return user


def сделать_админом(app, user_id: str) -> None:
    """Флаг ставится руками в базе — маршрута «сделай меня админом» нет и не
    будет: его пришлось бы защищать тем же флагом, которого ещё нет."""
    with app.state.db.session_scope() as s:
        s.get(User, user_id).is_admin = True


def кадры_потока(клиент, путь: str) -> list[dict]:
    """Прочитать поток `text/event-stream` до конца. → кадры полями.

    Разбор свой и нарочно наивный — тот же, что в `test_sse`: проверяется
    именно то, что служба написала в провод, а библиотека простила бы нам и
    лишний перенос строки, и пропущенный `id`.
    """
    кадры: list[dict] = []
    текущий: dict = {}
    with клиент.stream("GET", путь) as ответ:
        assert ответ.status_code == 200
        assert ответ.headers["content-type"].startswith("text/event-stream")
        for строка in ответ.iter_lines():
            if строка.startswith(":"):
                текущий["comment"] = строка[1:].strip()
                continue
            if not строка:
                if текущий:
                    кадры.append(текущий)
                    текущий = {}
                continue
            поле, _, значение = строка.partition(":")
            текущий[поле.strip()] = значение.strip()
    if текущий:
        кадры.append(текущий)
    return [к for к in кадры if "event" in к]


# ── весь второй этап одним человеком ─────────────────────────────────────────

def test_путь_второго_этапа_целиком(app, клиент, отказы, caplog, модель):
    """Регистрация → материал через очередь → прогон → поток → версии → схема →
    выгрузка → ключ → тот же путь под `/api/v1` → отмена → админка → выход.

    Один тест на всю дорогу, а не двадцать: разваливается она на стыках, и стык
    виден только тогда, когда оба его конца настоящие.
    """
    # ── (1) вход: почта, ссылка из журнала, пароль, cookie ───────────────────
    войти_по_настоящему(клиент, caplog, ПОЧТА)
    я = строка_человека(app, ПОЧТА)

    ws = шаг(клиент, отказы, "get", "/api/workspaces/personal")
    assert ws.status_code == 200, ws.text
    ws_id = ws.json()["id"]

    # ── (2) проект с шаблоном: теги «цель» и «выводы» ────────────────────────
    создан = шаг(клиент, отказы, "post", "/api/projects",
                 data={"workspace_id": ws_id, "name": "второй этап"},
                 files={"template": ("шаблон.docx", docx_байты(),
                                     "application/vnd.openxmlformats-"
                                     "officedocument.wordprocessingml.document")})
    assert создан.status_code == 201, создан.text
    pid = создан.json()["id"]
    материалы = f"/api/projects/{pid}/materials"

    # ── (3) материал: 202 сейчас, карточка — после воркера ───────────────────
    загрузка = шаг(клиент, отказы, "post", материалы,
                   files=файл(ИМЯ_ИСХОДНИКА, ИСХОДНИК.encode()))
    assert загрузка.status_code == 202, загрузка.text
    assert загрузка.json()["job"]["kind"] == "parse"
    # Материала ещё нет — и это не задержка, а договор: путь один, через
    # очередь, и синхронной ветки для маленьких файлов не осталось.
    assert шаг(клиент, отказы, "get", материалы).json() == []

    докрутить(app)

    опись = шаг(клиент, отказы, "get", материалы)
    assert опись.status_code == 200, опись.text
    карточки = опись.json()
    assert len(карточки) == 1, карточки
    mid = карточки[0]["id"]
    assert шаг(клиент, отказы, "get", f"{материалы}/{mid}").status_code == 200

    # ── (4) ключ модели: наружу только четыре последние цифры ────────────────
    ключ = шаг(клиент, отказы, "post", "/api/keys",
               json={"provider": ПОСТАВЩИК, "key": КЛЮЧ})
    assert ключ.status_code == 201, ключ.text
    assert ключ.json()["last4"] == КЛЮЧ[-4:]
    assert КЛЮЧ not in ключ.text

    # ── (5) прогон одного тега через очередь ─────────────────────────────────
    подделка = модель(сценарий(json.dumps(ЦЕЛЬ, ensure_ascii=False), частей=4))
    поставлено = шаг(клиент, отказы, "post", "/api/jobs",
                     json={"kind": "fill_tag", "project_id": pid,
                           "payload": {"key": "цель", "endpoint": ПОСТАВЩИК}})
    assert поставлено.status_code == 202, поставлено.text
    job_id = поставлено.json()["id"]
    assert поставлено.json()["status"] == "queued"

    assert прогнать(app) == job_id
    сделано = шаг(клиент, отказы, "get", f"/api/jobs/{job_id}")
    assert сделано.status_code == 200, сделано.text
    assert сделано.json()["status"] == "done", сделано.json()["error"]
    assert сделано.json()["spent_units"] > 0
    assert подделка.backend is not None, "модель так и не позвали"

    # Значение легло на том, а не осталось в ответе задания.
    значения = шаг(клиент, отказы, "get", f"/api/projects/{pid}/values")
    assert значения.status_code == 200, значения.text
    assert значения.json()["values"]["цель"]["text"] == ЦЕЛЬ["text"]

    # ── (6) события: списком и потоком — одно и то же ────────────────────────
    списком = шаг(клиент, отказы, "get", f"/api/jobs/{job_id}/events")
    assert списком.status_code == 200, списком.text
    виды_списком = [е["kind"] for е in списком.json()["events"]]
    assert {"text", "tag_closed", "done"} <= set(виды_списком), виды_списком
    assert списком.json()["status"] == "done"

    виды_потоком = [к["event"] for к in
                    кадры_потока(клиент, f"/api/jobs/{job_id}/stream")]
    assert виды_потоком == виды_списком, "поток и список разошлись"

    # ── (7) колокольчик: писем нет, уведомление есть ─────────────────────────
    колокольчик = шаг(клиент, отказы, "get", "/api/notifications")
    assert колокольчик.status_code == 200, колокольчик.text
    assert колокольчик.json()["unread_count"] >= 1
    моё = [у for у in колокольчик.json()["notifications"]
           if у["job_id"] == job_id]
    assert моё and моё[0]["kind"] == "job_done", колокольчик.json()

    # ── (8) версии тега и откат ──────────────────────────────────────────────
    рукой = шаг(клиент, отказы, "put", f"/api/projects/{pid}/values/цель",
                json={"type": "markdown", "text": "переписано рукой"})
    assert рукой.status_code == 200, рукой.text

    история = шаг(клиент, отказы, "get",
                  f"/api/projects/{pid}/values/цель/versions")
    assert история.status_code == 200, история.text
    assert len(история.json()["versions"]) >= 2

    возврат = шаг(клиент, отказы, "post",
                  f"/api/projects/{pid}/values/цель/rollback", json={"n": 1})
    assert возврат.status_code == 200, возврат.text
    assert возврат.json()["restored_from"] == 1
    # Возврат ничего не удаляет: он дописывает, и номер в ответе больше.
    assert возврат.json()["version"]["n"] > 2
    вернулось = шаг(клиент, отказы, "get", f"/api/projects/{pid}/values")
    assert вернулось.json()["values"]["цель"]["text"] == ЦЕЛЬ["text"]

    # ── (9) блок-схема по материалу и общий маршрут артефактов ───────────────
    схема = шаг(клиент, отказы, "post", f"/api/projects/{pid}/flowcharts",
                json={"material_id": mid, "lang": "py"})
    assert схема.status_code == 201, схема.text
    рисунок = шаг(клиент, отказы, "get",
                  f"/api/projects/{pid}/artifacts/{схема.json()['artifact']}")
    assert рисунок.status_code == 200, рисунок.text
    assert b"mxGraphModel" in рисунок.content or b"<mxfile" in рисунок.content

    модули = шаг(клиент, отказы, "get", "/api/modules")
    assert модули.status_code == 200, модули.text
    assert {"flowcharts", "uml"} <= {м["id"] for м in модули.json()}

    # ── (10) выгрузка: задание → артефакт → zip ──────────────────────────────
    выгрузили = шаг(клиент, отказы, "post", f"/api/projects/{pid}/export")
    assert выгрузили.status_code == 202, выгрузили.text
    export_id = выгрузили.json()["job"]["id"]
    докрутить(app)
    итог = шаг(клиент, отказы, "get", f"/api/jobs/{export_id}")
    assert итог.json()["status"] == "done", итог.json()["error"]
    архив_id = итог.json()["result"]["artifact"]

    архив = шаг(клиент, отказы, "get",
                f"/api/projects/{pid}/artifacts/{архив_id}")
    assert архив.status_code == 200, архив.text
    assert архив.headers["content-type"] == "application/zip"
    внутри = zipfile.ZipFile(io.BytesIO(архив.content))
    assert f"{выгрузка.ПАПКА_МАТЕРИАЛОВ}/{ИМЯ_ИСХОДНИКА}" in внутри.namelist()
    assert внутри.read(
        f"{выгрузка.ПАПКА_МАТЕРИАЛОВ}/{ИМЯ_ИСХОДНИКА}") == ИСХОДНИК.encode()
    в_архиве = json.loads(внутри.read(выгрузка.ЗНАЧЕНИЯ))
    assert в_архиве["цель"]["text"] == ЦЕЛЬ["text"]

    # ── (11) внешний ключ: показывается один раз ─────────────────────────────
    выдан = шаг(клиент, отказы, "post", "/api/tokens",
                json={"name": "ночной скрипт", "scopes": list(ключи.ПРАВА)})
    assert выдан.status_code == 201, выдан.text
    строка_ключа = выдан.json()["token"]
    assert строка_ключа.startswith("kor_")
    список_ключей = шаг(клиент, отказы, "get", "/api/tokens")
    assert строка_ключа not in список_ключей.text, "ключ показан второй раз"

    # ── (12) тот же путь под `/api/v1`, только ключом ────────────────────────
    клиент.headers["Authorization"] = f"Bearer {строка_ключа}"

    свои = шаг(клиент, отказы, "get", "/api/v1/projects",
               params={"workspace_id": ws_id})
    assert свои.status_code == 200, свои.text
    assert pid in [p["id"] for p in свои.json()["projects"]]

    чужими_глазами = шаг(клиент, отказы, "get", f"/api/v1{материалы[4:]}")
    assert чужими_глазами.status_code == 200, чужими_глазами.text
    assert mid in [м["id"] for м in чужими_глазами.json()]

    ключом = шаг(клиент, отказы, "post", "/api/v1/jobs",
                 json={"kind": "probe", "payload": {"charge": 7}})
    assert ключом.status_code == 202, ключом.text
    проба_id = ключом.json()["id"]
    assert прогнать(app) == проба_id
    события_ключом = шаг(клиент, отказы, "get",
                         f"/api/v1/jobs/{проба_id}/events")
    assert события_ключом.status_code == 200, события_ключом.text
    assert события_ключом.json()["status"] == "done"

    выгрузка_ключом = шаг(клиент, отказы, "post",
                          f"/api/v1/projects/{pid}/export")
    assert выгрузка_ключом.status_code == 202, выгрузка_ключом.text
    докрутить(app)

    # ── (13) отказ без права ─────────────────────────────────────────────────
    del клиент.headers["Authorization"]
    только_чтение = шаг(клиент, отказы, "post", "/api/tokens",
                        json={"name": "только читать",
                              "scopes": [ключи.PROJECTS_READ]})
    assert только_чтение.status_code == 201, только_чтение.text
    клиент.headers["Authorization"] = f"Bearer {только_чтение.json()['token']}"

    нельзя = шаг(клиент, отказы, "post", "/api/v1/projects",
                 data={"workspace_id": ws_id, "name": "мимо"})
    assert нельзя.status_code == 403, нельзя.text
    assert нельзя.json()["error"]["code"] == "insufficient_scope"
    del клиент.headers["Authorization"]

    # ── (14) отмена задания, которое ещё ждёт ────────────────────────────────
    ждёт = шаг(клиент, отказы, "post", "/api/jobs",
               json={"kind": "probe", "payload": {"sleep": 30}})
    assert ждёт.status_code == 202 and ждёт.json()["status"] == "queued"
    отменено = шаг(клиент, отказы, "post", f"/api/jobs/{ждёт.json()['id']}/cancel")
    assert отменено.status_code == 200, отменено.text
    assert отменено.json()["status"] == "cancelled"
    # Отменённое воркер не берёт: следующим он возьмёт то, чего ещё нет.
    assert прогнать(app) is None

    # ── (15) владелец службы: очередь, журнал, одно число расхода ────────────
    промах = шаг(клиент, отказы, "post", "/api/auth/login",
                 json={"email": ПОЧТА, "password": "не тот пароль"})
    assert промах.status_code == 401, промах.text

    сделать_админом(app, я.id)
    очередь = шаг(клиент, отказы, "get", "/api/admin/queue")
    assert очередь.status_code == 200, очередь.text
    assert очередь.json()["slots"]["per_machine"] >= 1

    журнал = шаг(клиент, отказы, "get", "/api/admin/security")
    assert журнал.status_code == 200, журнал.text
    assert "login_failed" in {е["kind"] for е in журнал.json()["events"]}

    # Расход считает одно место на всю службу — `jobs.service.расход_за_месяц`.
    свой = шаг(клиент, отказы, "get", "/api/usage").json()
    люди = шаг(клиент, отказы, "get", "/api/admin/users").json()["users"]
    мой = next(ч for ч in люди if ч["id"] == я.id)
    assert свой["spent_units"] > 0
    assert мой["spent_units"] == свой["spent_units"]

    # ── (16) выход отовсюду ──────────────────────────────────────────────────
    вышел = шаг(клиент, отказы, "post", "/api/auth/logout-all")
    assert вышел.status_code == 200, вышел.text
    assert шаг(клиент, отказы, "get", "/api/auth/me").status_code == 401


# ── одно число расхода на две страницы ───────────────────────────────────────

def test_расход_один_и_тот_же_в_usage_и_в_админке(app, клиент, отказы, caplog):
    """`GET /api/usage` и `GET /api/admin/users` называют одно число.

    Считает его одна функция (`jobs.service.расход_за_месяц`), и этот тест —
    её договор. Раньше сумм было две, написанных порознь: одна в
    `runs.limits`, другая в `admin.service`. Разошлись бы они молча, а увидел
    бы это человек, которому отказали по одному числу, тогда как владелец в
    админке видит другое.

    Расход набирается пробой очереди — тем же полем `spent_units`, по которому
    считается месяц, а не подделанной строкой в базе.
    """
    войти_по_настоящему(клиент, caplog, ПОЧТА)
    я = строка_человека(app, ПОЧТА)
    сделать_админом(app, я.id)

    for сколько in (400, 137):
        поставлено = шаг(клиент, отказы, "post", "/api/jobs",
                         json={"kind": "probe", "payload": {"charge": сколько}})
        assert поставлено.status_code == 202, поставлено.text
        прогнать(app)

    свой = шаг(клиент, отказы, "get", "/api/usage").json()
    assert свой["spent_units"] == 537

    люди = шаг(клиент, отказы, "get", "/api/admin/users").json()["users"]
    мой = next(ч for ч in люди if ч["id"] == я.id)
    assert мой["spent_units"] == свой["spent_units"]

    # И та же сумма — в карточке, которую отдаёт правка человека: три страницы,
    # одно число.
    поправлен = шаг(клиент, отказы, "patch", f"/api/admin/users/{я.id}",
                    json={"plan": "free"})
    assert поправлен.status_code == 200, поправлен.text
    assert поправлен.json()["spent_units"] == свой["spent_units"]


# ── лимит по плану ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("правки", [{"free_monthly_units": 300}], indirect=True)
def test_исчерпанный_лимит_плана_отказывает_402(app, клиент, отказы, caplog,
                                                settings):
    """`402 Payment Required`: кончилась месячная квота, и ждать бесполезно.

    Потолок приходит настройкой (`KORITSU_FREE_MONTHLY_UNITS`), а не
    правкой поля на живом приложении: настройки заморожены, и тест, обходящий
    заморозку, проверял бы поведение, которого в работе нет.
    """
    assert settings.free_monthly_units == 300
    войти_по_настоящему(клиент, caplog, ПОЧТА)
    ws_id = шаг(клиент, отказы, "get", "/api/workspaces/personal").json()["id"]
    создан = шаг(клиент, отказы, "post", "/api/projects",
                 data={"workspace_id": ws_id, "name": "дорого"})
    assert создан.status_code == 201, создан.text

    # Расход набирается настоящим заданием, а не строкой в базе.
    шаг(клиент, отказы, "post", "/api/jobs",
        json={"kind": "probe", "payload": {"charge": 500}})
    прогнать(app)

    ответ = шаг(клиент, отказы, "post", "/api/jobs",
                json={"kind": "fill_tag", "project_id": создан.json()["id"],
                      "payload": {"key": "цель", "endpoint": ПОСТАВЩИК}})
    assert ответ.status_code == 402, ответ.text
    беда = ответ.json()["error"]
    assert беда["code"] == "limit_exhausted"
    # Отказ с цифрами: без них человек уходит гадать, сколько ему не хватило.
    assert "300" in беда["message"] and "500" in беда["message"]

    # Задание без модели ставится по-прежнему: лимит про деньги, а не про очередь.
    ещё = шаг(клиент, отказы, "post", "/api/jobs", json={"kind": "probe"})
    assert ещё.status_code == 202, ещё.text


# ── одна форма отказа на весь этап ───────────────────────────────────────────

def test_все_отказы_второго_этапа_одной_формы(app, клиент, отказы, caplog,
                                              модель):
    """Каждый отказ сценария — `{"error": {code, message, where?}}` с кодом из
    латиницы.

    Список собирается по дороге, а не пишется руками: закреплять форму только
    тех отказов, о которых тест помнил, значило бы не закреплять её вовсе.
    Отказы приходят из шести мест сразу — очередь, прогоны, ключи, админка,
    CSRF, внешний вход, — и в каждом свой соблазн ответить по-своему.
    """
    from api.errors import ErrorOut

    test_путь_второго_этапа_целиком(app, клиент, отказы, caplog, модель)

    # Добавим к собранному то, что сценарий не проходит: беды каждой части.
    войти_по_настоящему(клиент, caplog, "второй@пример.рф")
    ещё = [
        ("post", "/api/jobs", {"json": {"kind": "нет такого"}}),
        ("get", "/api/jobs/не-uuid", {}),
        ("post", "/api/jobs/00000000-0000-4000-8000-000000000000/cancel", {}),
        ("get", "/api/notifications/не-uuid", {}),
        ("get", "/api/admin/users", {}),
        ("post", "/api/tokens", {"json": {"name": "х", "scopes": ["нет"]}}),
        ("get", "/api/v1/projects", {"params": {"workspace_id": "х"}}),
        ("post", "/api/projects/не-uuid/export", {}),
        ("post", "/api/flowcharts/preview",
         {"json": {"source": "x = (", "lang": "java"}}),
    ]
    for метод, путь, kwargs in ещё:
        ответ = шаг(клиент, отказы, метод, путь, **kwargs)
        assert ответ.status_code >= 400, f"{метод} {путь} не отказал"

    assert len(отказы) >= len(ещё)
    for метод, путь, код, тело in отказы:
        где = f"{метод} {путь} [{код}]"
        разобрано = ErrorOut.model_validate(тело)
        assert КОД_RE.match(разобрано.error.code), f"{где}: {разобрано.error.code}"
        assert разобрано.error.message.isascii(), f"{где}: {разобрано.error.message}"
        if разобрано.error.where is not None:
            assert разобрано.error.where.isascii(), где
