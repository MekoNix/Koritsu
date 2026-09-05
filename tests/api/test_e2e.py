"""
Сквозные сценарии: путь человека от письма до выхода, одним клиентом.

Отличие от всех прочих тестов службы — в том, чего здесь **нет**. Нет
`dependency_overrides`: вошедшего не подставляют, он входит сам — почтой,
паролем и подписанной cookie, которую держит клиент. Нет подделанных строк в
базе: пользователь заводится регистрацией, проект — маршрутом, материал —
загрузкой. Нет и подмены почты: ссылка подтверждения берётся оттуда же, откуда
её взял бы разработчик, — из журнала консольного `Mailer`: наружу писем служба
не шлёт.

Зачем это, если каждый кусок уже проверен своим тестом. Затем, что склейка
ломается не внутри кусков, а между ними, и ровно там, где её никто не проверяет:
подтверждение выдаёт токен, но вход требует ещё и личного пространства; проект
заводится в пространстве, но каталог его лежит у владельца; квота считается по
владельцу, а не по пришедшему. Каждое из этих «но» лежит на стыке двух
пакетов, и ни один из них не закрепит его у себя.

Что проверяется по порядку:

    (а) регистрация → письмо → подтверждение → вход → личное пространство →
        проект без шаблона → материал → карточка и текст → ключ модели →
        корзина → восстановление → выход отовсюду → 401
    (б) второй человек: чужое не видно (404); позван viewer'ом — читает, но
        не пишет (403); повышен до editor — пишет
    (в) квота владельца: второй файл не влезает (413)
    (г) уборка корзины: до срока каталог на месте, после срока его нет
    (д) все отказы за все сценарии — одной формой с ASCII-кодом
    (е) правило разреза: служба не тянет `hokoku`

**Отказы собираются, а не проверяются по месту.** Каждый запрос идёт через
`шаг`, и всякий ответ с кодом 400 и выше попадает в общий список, который
проверяет `test_все_отказы_одной_формы`. Проверка по месту закрепляла бы форму
тех отказов, о которых тест помнил; общий список закрепляет **все**, включая те,
что случились по дороге и никого не интересовали.
"""
from __future__ import annotations

import datetime
import logging
import os
import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from api import Settings, create_app
from api.accounts.models import User
from api.projects.models import Project
from api.projects.service import dir_for, purge_expired
from api.workspaces.models import Workspace

from .c_fixtures import ПАРОЛЬ, docx_байты
from .d_fixtures import докрутить

# Все журналы службы. Ключ модели не должен попасть ни в один из них, и
# список закрыт, чтобы «ни в один» было проверяемым, а не подразумеваемым.
ЖУРНАЛЫ = ("api.request", "api.error", "api.mail",
           "api.security")

# Ссылка из письма: `{base_url}/confirm?token=…` (`accounts.mail.confirm_link`).
ССЫЛКА_RE = re.compile(r"https?://\S+/confirm\?token=([A-Za-z0-9._\-]+)")

# Ключ поставщика, похожий на настоящий. Ищется потом по всем ответам и журналам.
КЛЮЧ_МОДЕЛИ = "sk-e2e0123456789abcdef0123456789ab"

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
    return create_app(settings)


@pytest.fixture
def ящик():
    """Журналы службы целиком, строками. Это и почтовый ящик, и место, куда
    ключ модели попасть не должен.

    Свой обработчик, а не `caplog`: `caplog` вешается на корневой логгер и живёт
    его уровнем, а нам нужны именно эти четыре потока и именно то, что в них
    написано — вместе с текстом письма, который лежит в теле записи.
    """
    собрано: list[str] = []

    class Сбор(logging.Handler):
        def emit(self, запись):                     # noqa: ANN001
            собрано.append(self.format(запись))

    ловушка = Сбор()
    ловушка.setFormatter(logging.Formatter("%(name)s %(message)s"))
    логгеры = [logging.getLogger(имя) for имя in ЖУРНАЛЫ]
    for л in логгеры:
        л.addHandler(ловушка)
        л.setLevel(logging.DEBUG)
    try:
        yield собрано
    finally:
        for л in логгеры:
            л.removeHandler(ловушка)


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
    """Запрос, у которого отказ не теряется.

    Всё, что вернулось с кодом 400 и выше, ложится в общий список: форму отказа
    проверяет один тест на все сценарии сразу, а не каждый по своему поводу.
    """
    ответ = getattr(клиент, метод)(путь, **kwargs)
    if ответ.status_code >= 400:
        отказы.append((метод.upper(), путь, ответ.status_code, ответ.json()))
    return ответ


def ссылка_подтверждения(ящик: list[str]) -> str:
    """Токен из письма — оттуда же, откуда его взял бы разработчик в dev."""
    for строка in reversed(ящик):
        найдено = ССЫЛКА_RE.search(строка)
        if найдено:
            return найдено.group(1)
    raise AssertionError(f"письма с ссылкой в журнале нет: {ящик}")


def войти_по_настоящему(клиент, отказы, ящик, email: str) -> dict:
    """Регистрация → письмо → подтверждение → вход. → профиль вошедшего.

    Четыре шага одной функцией, потому что дальше во всех сценариях нужен именно
    вошедший человек, а не повторение этих четырёх строк.
    """
    заведён = шаг(клиент, отказы, "post", "/api/auth/register",
                  json={"email": email, "password": ПАРОЛЬ,
                        # Ник обязателен; берём из почты — он у каждого
                        # сценария свой, как и сама почта.
                        "nickname": email.split("@")[0]})
    assert заведён.status_code == 201, заведён.text
    assert заведён.json() == {"status": "confirmation_sent"}

    токен = ссылка_подтверждения(ящик)
    подтверждён = шаг(клиент, отказы, "post", "/api/auth/confirm",
                      json={"token": токен})
    assert подтверждён.status_code == 200, подтверждён.text

    вошёл = шаг(клиент, отказы, "post", "/api/auth/login",
                json={"email": email, "password": ПАРОЛЬ})
    assert вошёл.status_code == 200, вошёл.text
    return вошёл.json()["user"]


def завести_проект(клиент, отказы, workspace_id: str, name: str = "работа") -> dict:
    """Проект без шаблона: оркестратор строит документ с нуля."""
    ответ = шаг(клиент, отказы, "post", "/api/projects",
                data={"workspace_id": workspace_id, "name": name})
    assert ответ.status_code == 201, ответ.text
    return ответ.json()


# ── (а) весь путь одного человека ────────────────────────────────────────────

def test_весь_путь_от_письма_до_выхода(app, клиент, отказы, ящик, settings):
    """Регистрация, подтверждение, вход, работа, ключ, корзина, выход отовсюду.

    Один тест на всю дорогу, а не восемь: разваливается она именно на стыках, и
    стык виден только тогда, когда предыдущий шаг был настоящим.
    """
    профиль = войти_по_настоящему(клиент, отказы, ящик, "первый@пример.рф")
    assert профиль["email_confirmed"] is True

    # Cookie сессии клиент получил и держит — второй запрос идёт уже вошедшим.
    я = шаг(клиент, отказы, "get", "/api/auth/me")
    assert я.status_code == 200, я.text
    assert я.json()["user"]["id"] == профиль["id"]

    # Личное пространство завёл хук регистрации, а не этот тест.
    личное = шаг(клиент, отказы, "get", "/api/workspaces/personal")
    assert личное.status_code == 200, личное.text
    assert личное.json()["personal"] is True and личное.json()["role"] == "owner"
    ws_id = личное.json()["id"]

    список = шаг(клиент, отказы, "get", "/api/workspaces").json()["workspaces"]
    assert [w["id"] for w in список] == [ws_id]

    # ── проект без шаблона ───────────────────────────────────────────────────
    проект = завести_проект(клиент, отказы, ws_id, "методичка")
    assert проект["workspace_id"] == ws_id
    assert проект["owner_id"] == профиль["id"]
    # Путей наружу нет — только число байт.
    assert "path" not in проект and "dir" not in проект
    assert проект["bytes_used"] > 0

    # ── материал ─────────────────────────────────────────────────────────────
    материалы = f"/api/projects/{проект['id']}/materials"
    загружен = шаг(клиент, отказы, "post", материалы,
                   files={"file": ("пособие.docx", docx_байты(("цель", "итог")),
                                   "application/octet-stream")})
    # `202`, а не `201`: разбор чужого файла уехал в очередь, и материала
    # в момент ответа ещё нет — есть ключ, под которым он появится, и задание.
    assert загружен.status_code == 202, загружен.text
    mid = загружен.json()["pending_id"]
    ждут = шаг(клиент, отказы, "get", f"{материалы}/pending")
    assert [ж["pending_id"] for ж in ждут.json()] == [mid]

    # Оборот воркера — здесь, в сценарии, а не за кулисами: путь человека
    # проходит через очередь, и сквозной тест обязан пройти его так же.
    докрутить(app)
    assert шаг(клиент, отказы, "get", f"{материалы}/pending").json() == []
    assert шаг(клиент, отказы, "get",
               f"{материалы}/{mid}").json()["units"] > 0

    карточка = шаг(клиент, отказы, "get", f"{материалы}/{mid}")
    assert карточка.status_code == 200, карточка.text
    assert карточка.json()["id"] == mid

    текст = шаг(клиент, отказы, "get", f"{материалы}/{mid}/text")
    assert текст.status_code == 200, текст.text
    assert "цель" in текст.json()["text"]
    assert текст.json()["anchor"]

    опись = шаг(клиент, отказы, "get", материалы)
    assert [m["id"] for m in опись.json()] == [mid]

    # ── ключ модели ──────────────────────────────────────────────────────────
    ключ = шаг(клиент, отказы, "post", "/api/keys",
               json={"provider": "deepseek", "key": КЛЮЧ_МОДЕЛИ})
    assert ключ.status_code == 201, ключ.text
    assert ключ.json()["last4"] == КЛЮЧ_МОДЕЛИ[-4:]
    свои = шаг(клиент, отказы, "get", "/api/keys")
    assert [k["id"] for k in свои.json()] == [ключ.json()["id"]]

    # ── корзина ──────────────────────────────────────────────────────────────
    удалён = шаг(клиент, отказы, "delete", f"/api/projects/{проект['id']}")
    assert удалён.status_code == 200, удалён.text
    assert удалён.json()["deleted_at"] and удалён.json()["purge_after"]

    живые = шаг(клиент, отказы, "get", "/api/projects",
                params={"workspace_id": ws_id})
    assert живые.json()["projects"] == []

    в_корзине = шаг(клиент, отказы, "get", "/api/projects",
                    params={"workspace_id": ws_id, "trash": "true"})
    assert [p["id"] for p in в_корзине.json()["projects"]] == [проект["id"]]

    возвращён = шаг(клиент, отказы, "post",
                    f"/api/projects/{проект['id']}/restore")
    assert возвращён.status_code == 200, возвращён.text
    assert возвращён.json()["deleted_at"] is None

    снова = шаг(клиент, отказы, "get", "/api/projects",
                params={"workspace_id": ws_id})
    assert [p["id"] for p in снова.json()["projects"]] == [проект["id"]]

    # ── выход отовсюду ───────────────────────────────────────────────────────
    вышел = шаг(клиент, отказы, "post", "/api/auth/logout-all")
    assert вышел.status_code == 200, вышел.text

    закрыто = шаг(клиент, отказы, "get", "/api/auth/me")
    assert закрыто.status_code == 401
    assert закрыто.json()["error"]["code"] == "unauthenticated"


def test_ключ_модели_не_попал_ни_в_ответ_ни_в_журнал(клиент, отказы, ящик):
    """Наружу — четыре последних знака, и больше ничего.

    Проверяются оба пути утечки разом: тело любого ответа и все четыре журнала
    службы. Достаточно одной строки `беды.exception(строка)` с объектом ключа
    внутри, чтобы секрет уехал в журнал, и заметить это без проверки нельзя.
    """
    войти_по_настоящему(клиент, отказы, ящик, "ключник@пример.рф")

    ответы = [
        шаг(клиент, отказы, "post", "/api/keys",
            json={"provider": "deepseek", "key": КЛЮЧ_МОДЕЛИ}),
        шаг(клиент, отказы, "get", "/api/keys"),
        шаг(клиент, отказы, "get", "/api/keys/providers"),
        # Кривой ключ: текст отказа тоже не должен его пересказывать.
        шаг(клиент, отказы, "post", "/api/keys",
            json={"provider": "deepseek", "key": "с пробелом"}),
    ]
    for ответ in ответы:
        assert КЛЮЧ_МОДЕЛИ not in ответ.text
        assert "ciphertext" not in ответ.text
    for строка in ящик:
        assert КЛЮЧ_МОДЕЛИ not in строка, строка


def test_пароль_не_попал_ни_в_ответ_ни_в_журнал(клиент, отказы, ящик):
    """Тот же заслон для пароля: он не уезжает никуда, кроме argon2."""
    войти_по_настоящему(клиент, отказы, ящик, "тихий@пример.рф")
    # Неудачный вход: текст отказа не пересказывает присланное.
    промах = шаг(клиент, отказы, "post", "/api/auth/login",
                 json={"email": "тихий@пример.рф", "password": ПАРОЛЬ + "!"})
    assert промах.status_code == 401
    assert ПАРОЛЬ not in промах.text
    for строка in ящик:
        assert ПАРОЛЬ not in строка, строка


# ── (б) второй человек: доступ и роли ────────────────────────────────────────

def test_чужое_не_видно_а_приглашённый_видит_но_не_пишет(app, клиент, отказы,
                                                         ящик):
    """404 на чужое, 403 на `viewer` с `PUT`, и `PUT` проходит после повышения.

    404, а не 403, на чужой проект: 403 сообщал бы, что проект с
    таким идентификатором существует, то есть отвечал бы на вопрос, задавать
    который спрашивающему не позволено.
    """
    хозяин = войти_по_настоящему(клиент, отказы, ящик, "хозяин@пример.рф")
    общее = шаг(клиент, отказы, "post", "/api/workspaces", json={"name": "общее"})
    assert общее.status_code == 201, общее.text
    ws_id = общее.json()["id"]
    проект = завести_проект(клиент, отказы, ws_id, "общая работа")
    ключ_тега = "цель"

    # Владелец кладёт значение — потом его читает приглашённый.
    поставил = шаг(клиент, отказы, "put",
                   f"/api/projects/{проект['id']}/values/{ключ_тега}",
                   json={"type": "text", "text": "написал хозяин"})
    assert поставил.status_code == 200, поставил.text

    # Второй человек входит по-настоящему, в том же клиенте: cookie сменилась.
    шаг(клиент, отказы, "post", "/api/auth/logout")
    сосед = войти_по_настоящему(клиент, отказы, ящик, "сосед@пример.рф")
    assert сосед["id"] != хозяин["id"]

    # Чужого проекта для него не существует.
    чужой = шаг(клиент, отказы, "get", f"/api/projects/{проект['id']}")
    assert чужой.status_code == 404
    assert чужой.json()["error"]["code"] == "not_found"
    чужое_место = шаг(клиент, отказы, "get", f"/api/workspaces/{ws_id}")
    assert чужое_место.status_code == 404

    # Хозяин зовёт его читателем.
    шаг(клиент, отказы, "post", "/api/auth/logout")
    войти_обратно(клиент, отказы, "хозяин@пример.рф")
    позван = шаг(клиент, отказы, "post", f"/api/workspaces/{ws_id}/members",
                 json={"email": "сосед@пример.рф", "role": "viewer"})
    assert позван.status_code == 201, позван.text

    # Читает — но не пишет.
    шаг(клиент, отказы, "post", "/api/auth/logout")
    войти_обратно(клиент, отказы, "сосед@пример.рф")
    читает = шаг(клиент, отказы, "get", f"/api/projects/{проект['id']}")
    assert читает.status_code == 200, читает.text
    значения = шаг(клиент, отказы, "get",
                   f"/api/projects/{проект['id']}/values")
    assert значения.status_code == 200
    assert значения.json()["values"][ключ_тега]["text"] == "написал хозяин"

    нельзя = шаг(клиент, отказы, "put",
                 f"/api/projects/{проект['id']}/values/{ключ_тега}",
                 json={"type": "text", "text": "правит сосед"})
    assert нельзя.status_code == 403
    assert нельзя.json()["error"]["code"] == "forbidden"

    # Повысили до editor — тот же запрос проходит.
    шаг(клиент, отказы, "post", "/api/auth/logout")
    войти_обратно(клиент, отказы, "хозяин@пример.рф")
    повышен = шаг(клиент, отказы, "patch",
                  f"/api/workspaces/{ws_id}/members/{сосед['id']}",
                  json={"role": "editor"})
    assert повышен.status_code == 200, повышен.text

    шаг(клиент, отказы, "post", "/api/auth/logout")
    войти_обратно(клиент, отказы, "сосед@пример.рф")
    теперь_можно = шаг(клиент, отказы, "put",
                       f"/api/projects/{проект['id']}/values/{ключ_тега}",
                       json={"type": "text", "text": "правит сосед"})
    assert теперь_можно.status_code == 200, теперь_можно.text
    assert теперь_можно.json()["source"] == "manual"
    assert теперь_можно.json()["version"] == 2


def войти_обратно(клиент, отказы, email: str) -> None:
    """Вход уже подтверждённого человека. Письма второй раз не бывает."""
    ответ = шаг(клиент, отказы, "post", "/api/auth/login",
                json={"email": email, "password": ПАРОЛЬ})
    assert ответ.status_code == 200, ответ.text


# ── (в) квота владельца ──────────────────────────────────────────────────────

# Порог квоты для этих двух сценариев и размер файла под него. Числа маленькие,
# а правило то же: настоящие 250 МБ означали бы четверть гигабайта на томе за
# один тест. Файлы — обычный текст, а не DOCX: под квоту нужен точно известный
# размер, а вес архива зависит от того, как сжались его части.
КВОТА = 300_000
ПОЛФАЙЛА = 150_000


@pytest.mark.parametrize("правки", [{"user_quota_bytes": КВОТА}], indirect=True)
def test_второй_файл_не_влезает_в_квоту(app, клиент, отказы, ящик, settings):
    """Квота на владельца. Второй файл — `413 quota_exceeded`.

    Считается она по владельцу, а не по пространству и не по пришедшему, и
    считается по тому, что лежит на томе, — включая каталог самого проекта,
    поэтому два файла по половине порога в него уже не влезают.
    """
    assert settings.user_quota_bytes == КВОТА
    войти_по_настоящему(клиент, отказы, ящик, "щедрый@пример.рф")
    ws_id = шаг(клиент, отказы, "get", "/api/workspaces/personal").json()["id"]
    проект = завести_проект(клиент, отказы, ws_id, "склад")
    материалы = f"/api/projects/{проект['id']}/materials"

    первый = шаг(клиент, отказы, "post", материалы,
                 files={"file": ("первый.txt", b"z" * ПОЛФАЙЛА,
                                 "application/octet-stream")})
    assert первый.status_code == 202, первый.text
    докрутить(app)

    второй = шаг(клиент, отказы, "post", материалы,
                 files={"file": ("второй.txt", b"w" * ПОЛФАЙЛА,
                                 "application/octet-stream")})
    assert второй.status_code == 413, второй.text
    assert второй.json()["error"]["code"] == "quota_exceeded"
    assert второй.json()["error"]["where"] == "body.file"

    # Первый файл на месте: отказ по квоте — это отказ, а не откат чужой работы.
    опись = шаг(клиент, отказы, "get", материалы)
    assert len(опись.json()) == 1


@pytest.mark.parametrize("правки", [{"user_quota_bytes": КВОТА}], indirect=True)
def test_тот_же_файл_второй_раз_квоту_не_ест(app, клиент, отказы, ящик):
    """Кэш по хешу: та же методичка второй раз не занимает ни байта.

    Соседний по размеру, но другой файл в этот момент уже не влезает: разница
    между ними и есть проверяемое правило — квота меряет том, а не число
    загрузок.
    """
    войти_по_настоящему(клиент, отказы, ящик, "повторный@пример.рф")
    ws_id = шаг(клиент, отказы, "get", "/api/workspaces/personal").json()["id"]
    проект = завести_проект(клиент, отказы, ws_id, "склад")
    материалы = f"/api/projects/{проект['id']}/materials"
    данные = b"z" * ПОЛФАЙЛА

    первый = шаг(клиент, отказы, "post", материалы,
                 files={"file": ("один.txt", данные,
                                 "application/octet-stream")})
    assert первый.status_code == 202, первый.text
    докрутить(app)
    чужой = шаг(клиент, отказы, "post", материалы,
                files={"file": ("иной.txt", b"q" * ПОЛФАЙЛА,
                                "application/octet-stream")})
    assert чужой.status_code == 413, чужой.text

    второй = шаг(клиент, отказы, "post", материалы,
                 files={"file": ("он же.txt", данные,
                                 "application/octet-stream")})
    assert второй.status_code == 202, второй.text
    # Тот же ключ: адрес материала — его содержимое, а не имя и не загрузка.
    assert второй.json()["pending_id"] == первый.json()["pending_id"]


# ── (г) уборка корзины ───────────────────────────────────────────────────────

def test_уборка_сносит_только_просроченное(app, клиент, отказы, ящик, settings):
    """До `purge_after` каталог на месте, после — его нет, и строки тоже.

    Срок двигается в прошлое прямо в базе, а не ожиданием десяти дней. Это
    единственное место всех сценариев, где тест трогает базу руками, и трогает
    он ровно одну колонку — ту, которая в работе двигается сама, временем.
    """
    войти_по_настоящему(клиент, отказы, ящик, "уборщик@пример.рф")
    ws_id = шаг(клиент, отказы, "get", "/api/workspaces/personal").json()["id"]
    проект = завести_проект(клиент, отказы, ws_id, "на снос")

    удалён = шаг(клиент, отказы, "delete", f"/api/projects/{проект['id']}")
    assert удалён.status_code == 200, удалён.text

    каталог = dir_for(settings, проект["owner_id"], проект["id"])
    assert os.path.isdir(каталог)

    # До срока — не трогаем: корзина затем и заведена, чтобы вернуть можно было.
    with app.state.db.session_scope() as s:
        assert purge_expired(s, settings) == []
    assert os.path.isdir(каталог)
    вернулся = шаг(клиент, отказы, "post",
                   f"/api/projects/{проект['id']}/restore")
    assert вернулся.status_code == 200, вернулся.text

    # Снова в корзину, но со сроком в прошлом.
    шаг(клиент, отказы, "delete", f"/api/projects/{проект['id']}")
    просрочить(app, проект["id"])

    with app.state.db.session_scope() as s:
        убрано = purge_expired(s, settings)
    assert убрано == [проект["id"]]
    assert not os.path.exists(каталог)

    with app.state.db.session_scope() as s:
        assert s.get(Project, проект["id"]) is None

    # Строка исчезла, значит и маршрут о проекте больше не знает.
    нет_такого = шаг(клиент, отказы, "get", f"/api/projects/{проект['id']}")
    assert нет_такого.status_code == 404


def test_уборка_пространства_уносит_его_проекты(app, клиент, отказы, ящик,
                                                settings):
    """Пространство в корзине уносит проекты — и с тома, и из базы."""
    войти_по_настоящему(клиент, отказы, ящик, "хозяйка@пример.рф")
    общее = шаг(клиент, отказы, "post", "/api/workspaces", json={"name": "курс"})
    ws_id = общее.json()["id"]
    проект = завести_проект(клиент, отказы, ws_id, "работа курса")
    каталог = dir_for(settings, проект["owner_id"], проект["id"])

    убрано_в_корзину = шаг(клиент, отказы, "delete", f"/api/workspaces/{ws_id}")
    assert убрано_в_корзину.status_code == 200, убрано_в_корзину.text
    просрочить_пространство(app, ws_id)

    with app.state.db.session_scope() as s:
        assert purge_expired(s, settings) == [проект["id"]]
    assert not os.path.exists(каталог)
    with app.state.db.session_scope() as s:
        assert s.get(Workspace, ws_id) is None


def test_личное_пространство_не_удаляется(клиент, отказы, ящик):
    """Личное — единственное, чего человек лишиться не может."""
    войти_по_настоящему(клиент, отказы, ящик, "личный@пример.рф")
    ws_id = шаг(клиент, отказы, "get", "/api/workspaces/personal").json()["id"]
    отказ = шаг(клиент, отказы, "delete", f"/api/workspaces/{ws_id}")
    assert отказ.status_code == 409
    assert отказ.json()["error"]["code"] == "personal_workspace"


def просрочить(app, project_id: str) -> None:
    """Отодвинуть `purge_after` проекта в прошлое."""
    with app.state.db.session_scope() as s:
        p = s.get(Project, project_id)
        assert p is not None and p.purge_after is not None
        p.purge_after = (datetime.datetime.now(datetime.timezone.utc)
                         - datetime.timedelta(days=1))


def просрочить_пространство(app, workspace_id: str) -> None:
    with app.state.db.session_scope() as s:
        ws = s.get(Workspace, workspace_id)
        assert ws is not None and ws.purge_after is not None
        ws.purge_after = (datetime.datetime.now(datetime.timezone.utc)
                          - datetime.timedelta(days=1))


# ── (д) одна форма отказа на все сценарии ────────────────────────────────────

def test_все_отказы_одной_формы(клиент, отказы, ящик, app, settings, tmp_path):
    """Каждый отказ службы — `{"error": {"code", "message"}}` с ASCII-кодом.

    Отказы собираются прогоном сценария, а не перечислением заранее: список,
    написанный руками, закрепил бы форму тех бед, о которых тест помнил, а
    прогон закрепляет все — включая проверку формы pydantic и пятисотку.
    """
    # Небольшой прогон, дающий отказы всех видов: проверка формы, отсутствие
    # входа, кривой идентификатор, чужое, конфликт, неизвестный маршрут.
    шаг(клиент, отказы, "get", "/api/auth/me")                      # 401
    шаг(клиент, отказы, "post", "/api/auth/register",
        json={"email": "не почта", "password": "к"})                # 422
    шаг(клиент, отказы, "get", "/api/nothing")                      # 404
    шаг(клиент, отказы, "delete", "/api/auth/me")                   # 405

    войти_по_настоящему(клиент, отказы, ящик, "разный@пример.рф")
    шаг(клиент, отказы, "get", "/api/workspaces/не-uuid")           # 400
    шаг(клиент, отказы, "get",
        "/api/workspaces/00000000-0000-4000-8000-000000000000")     # 404
    ws_id = шаг(клиент, отказы, "get", "/api/workspaces/personal").json()["id"]
    шаг(клиент, отказы, "delete", f"/api/workspaces/{ws_id}")       # 409
    шаг(клиент, отказы, "post", "/api/keys",
        json={"provider": "chatgpt", "key": КЛЮЧ_МОДЕЛИ})           # 400
    проект = завести_проект(клиент, отказы, ws_id, "разное")
    шаг(клиент, отказы, "post", f"/api/projects/{проект['id']}/materials",
        files={"file": ("чужое.exe", b"MZ\x00\x00",
                        "application/octet-stream")})               # 415
    шаг(клиент, отказы, "get",
        f"/api/projects/{проект['id']}/materials/нехеш")            # 400
    шаг(клиент, отказы, "post", "/api/projects",
        data={"workspace_id": ws_id, "name": "с плохим шаблоном"},
        files={"template": ("bad.docx", b"this is not a docx",
                            "application/octet-stream")})           # 400

    коды = set()
    assert len(отказы) >= 10, отказы
    for метод, путь, статус, тело in отказы:
        где = f"{метод} {путь} → {статус}: {тело}"
        assert set(тело) == {"error"}, где
        беда = тело["error"]
        assert set(беда) <= {"code", "message", "where"}, где
        assert {"code", "message"} <= set(беда), где
        assert КОД_RE.match(беда["code"]), где
        assert беда["message"] and беда["message"].isascii(), где
        if "where" in беда:
            assert беда["where"].isascii(), где
        коды.add(беда["code"])

    # Виды бед действительно разные: тест, собравший десять одинаковых отказов,
    # не проверял бы ничего.
    assert len(коды) >= 6, коды


def test_пятисотка_тоже_этой_формы(app, settings):
    """Необработанное исключение — тот же `{"error": …}` и ни слова о причине.

    Маршрут вешается здесь, а не в пакете: `/_test/boom` на живом сайте — это
    отказ обслуживания в одну строку.
    """
    @app.get("/_test/взрыв")
    def _взрыв():
        raise RuntimeError("путь-к-тому-и-кусок-запроса")

    with TestClient(app, raise_server_exceptions=False) as c:
        ответ = c.get("/_test/взрыв")
    assert ответ.status_code == 500
    assert ответ.json() == {"error": {"code": "internal_error",
                                      "message": "Internal server error"}}
    assert "путь-к-тому" not in ответ.text


# ── (е) правило разреза ──────────────────────────────────────────────────────

def test_служба_не_тянет_hokoku():
    """`api` не импортирует `hokoku` — ни одним файлом.

    Дублирует по духу `tests/kyotsu/test_border.py` (он проверяет весь список
    разрешённых), но проверяет самый близкий случай: служба правит
    `orchestrator` (это можно), а `orchestrator` знает про `hokoku`. Служба,
    потянувшая движок отчётов, перестала бы собираться без
    python-docx — и наоборот: `hokoku` начал бы требовать веб-сервер, чтобы
    построить DOCX.
    """
    import api

    корень = os.path.dirname(os.path.abspath(api.__file__))
    запрет = re.compile(r"^\s*(?:import hokoku\b|from hokoku[.\s])", re.MULTILINE)
    найдено = []
    for каталог, _, файлы in os.walk(корень):
        if "__pycache__" in каталог:
            continue
        for имя in файлы:
            if not имя.endswith(".py"):
                continue
            путь = os.path.join(каталог, имя)
            if запрет.search(open(путь, encoding="utf-8").read()):
                найдено.append(os.path.relpath(путь, корень))
    assert not найдено, найдено


def test_служба_собирается_и_отвечает_без_hokoku(клиент, отказы):
    """Собранное приложение не тащит `hokoku` в процесс само по себе.

    Проверка сильнее грепа: `orchestrator` умеет строить отчёты и импортирует
    `hokoku` внутри функции; если бы служба звала это на сборке или на
    `/health`, модуль оказался бы в `sys.modules` — то есть служба зависела бы
    от движка отчётов, не написав ни одной строки `import hokoku`.
    """
    import sys

    сохранённые = {имя: sys.modules.pop(имя) for имя in list(sys.modules)
                   if имя == "hokoku" or имя.startswith("hokoku.")}
    try:
        assert шаг(клиент, отказы, "get", "/health").status_code == 200
        assert шаг(клиент, отказы, "get", "/api/v1/ping").status_code == 200
        assert "hokoku" not in sys.modules
    finally:
        sys.modules.update(сохранённые)


def test_база_знает_про_вошедшего_а_не_только_ответ(app, клиент, отказы, ящик):
    """Регистрация оставила настоящую строку, а не только удачный ответ.

    Последняя проверка сквозного набора и самая скучная: без неё все сценарии
    выше проходили бы и на службе, которая ничего не сохраняет.
    """
    профиль = войти_по_настоящему(клиент, отказы, ящик, "настоящий@пример.рф")
    with app.state.db.session_scope() as s:
        user = s.get(User, профиль["id"])
        assert user is not None
        assert user.email == "настоящий@пример.рф"
        assert user.email_confirmed_at is not None
        # Пароля в базе нет — есть хеш argon2.
        assert ПАРОЛЬ not in user.password_hash
        assert user.password_hash.startswith("$argon2")

        личных = list(s.scalars(select(Workspace).where(
            Workspace.owner_id == user.id, Workspace.personal.is_(True))))
        assert len(личных) == 1
