"""
Аккаунты: круг «регистрация → подтверждение → вход → выход» и всё, что вокруг.

Здесь проверяется не столько то, что вход работает, сколько то, что он **не**
работает там, где не должен, и молчит там, где должен молчать. Половина тестов
этого файла — про утечки и лимиты, и это соразмерно: неработающий вход
обнаруживается за минуту, а форма регистрации, по которой перебирают чужие
адреса, не обнаруживается никогда.

Письма в тестах читаются из журнала `api.mail` — это и есть консольный бэкенд:
наружу служба писем не шлёт. Ссылку с токеном берём оттуда же, откуда её взял
бы разработчик.
"""
from __future__ import annotations

import datetime
import logging
import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from api import Settings, create_app
from api.accounts import service
from api.accounts.models import (FAILS_BEFORE_LOCK, EmailToken, User,
                                       UserSession)
from api.db import now

ПОЧТА = "ivan@example.org"
НИК = "ivan"
ПАРОЛЬ = "длинный-пароль-1"
НОВЫЙ_ПАРОЛЬ = "другой-длинный-пароль-2"


# ── оснастка ─────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def журнал_почты(caplog):
    """Письма и события безопасности — на уровне INFO, иначе их не видно."""
    caplog.set_level(logging.INFO)
    return caplog


def письма(caplog) -> list[str]:
    return [з.getMessage() for з in caplog.records if з.name == "api.mail"]


def токен_из_письма(caplog) -> str:
    """Токен из последней ушедшей ссылки — ровно так его берёт человек."""
    assert письма(caplog), "письма не было вовсе"
    найден = re.search(r"token=([A-Za-z0-9_-]+)", письма(caplog)[-1])
    assert найден, f"в письме нет ссылки с токеном: {письма(caplog)[-1]!r}"
    return найден.group(1)


def зарегистрировать(client, caplog, почта=ПОЧТА, пароль=ПАРОЛЬ,
                     ник=НИК) -> str:
    """Регистрация и токен подтверждения из письма."""
    ответ = client.post("/api/auth/register",
                        json={"email": почта, "password": пароль,
                              "nickname": ник})
    assert ответ.status_code == 201, ответ.text
    return токен_из_письма(caplog)


def завести_и_подтвердить(client, caplog, почта=ПОЧТА, пароль=ПАРОЛЬ,
                          ник=НИК) -> None:
    токен = зарегистрировать(client, caplog, почта, пароль, ник)
    assert client.post("/api/auth/confirm",
                       json={"token": токен}).status_code == 200


def войти(client, почта=ПОЧТА, пароль=ПАРОЛЬ):
    return client.post("/api/auth/login",
                       json={"email": почта, "password": пароль})


def приложение(tmp_path, **правки):
    """Своё приложение на своих настройках — для prod и для «за прокси»."""
    имя = "том-" + "-".join(f"{k}{v}" for k, v in правки.items())[:40]
    return create_app(Settings.for_tests(tmp_path / имя, **правки))


# ── полный круг ──────────────────────────────────────────────────────────────

def test_круг_регистрация_подтверждение_вход_я_выход(client, caplog):
    """То, ради чего всё: человек заводится, подтверждается, входит и выходит."""
    завести_и_подтвердить(client, caplog)

    вход = войти(client)
    assert вход.status_code == 200, вход.text
    assert service.COOKIE in вход.cookies

    я = client.get("/api/auth/me")
    assert я.status_code == 200
    тело = я.json()["user"]
    assert тело["email"] == ПОЧТА
    assert тело["email_confirmed"] is True
    assert тело["plan"] == "free"          # поле подписки заложено сразу
    assert тело["totp_enabled"] is False   # второй фактор заложен, но выключен

    assert client.post("/api/auth/logout").status_code == 200
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/auth/me").json()["error"]["code"] == "unauthenticated"


def test_наружу_не_уезжает_ни_хеш_ни_секрет_второго_фактора(client, caplog):
    """Список полей профиля закрыт: поле, дописанное в таблицу, не должно
    уезжать наружу само."""
    завести_и_подтвердить(client, caplog)
    тело = войти(client).json()["user"]
    assert set(тело) == {"id", "email", "nickname", "plan", "email_confirmed",
                         "totp_enabled", "is_admin", "default_endpoint",
                         "agent_overwrite", "created_at"}


def test_профиль_отдаёт_признак_админа_как_он_есть_в_базе(client, caplog, app):
    """Интерфейс скрывает `/admin` по этому полю, поэтому оно обязано быть и
    обязано отражать колонку, а не всегда врать «нет».

    Проверяются оба значения: поле, у которого один из двух ответов никогда не
    встречается в тестах, — это поле, про которое неизвестно, работает ли оно.
    """
    завести_и_подтвердить(client, caplog)
    войти(client)

    assert client.get("/api/auth/me").json()["user"]["is_admin"] is False

    # Флаг ставится руками в базе: маршрута «сделай меня админом» нет и не
    # будет (так же делает `tests/api/test_admin.py`).
    with app.state.db.session_scope() as s:
        строка = s.execute(select(User).where(User.email == ПОЧТА)).scalar_one()
        строка.is_admin = True

    assert client.get("/api/auth/me").json()["user"]["is_admin"] is True


def test_вход_без_подтверждения_не_пускает(client, caplog):
    """Входят только подтверждённые."""
    зарегистрировать(client, caplog)
    ответ = войти(client)
    assert ответ.status_code == 403
    assert ответ.json()["error"]["code"] == "email_not_confirmed"
    assert service.COOKIE not in ответ.cookies


def test_не_тот_пароль_и_незнакомая_почта_отвечают_одинаково(client, caplog):
    """Разные ответы превратили бы форму входа в проверялку чужих адресов."""
    завести_и_подтвердить(client, caplog)
    чужой = войти(client, почта="никого@example.org", пароль=ПАРОЛЬ)
    свой = войти(client, пароль="совсем-другой-пароль")
    assert чужой.status_code == свой.status_code == 401
    assert чужой.json() == свой.json()
    assert чужой.json()["error"]["code"] == "invalid_credentials"


# ── утечки ───────────────────────────────────────────────────────────────────

def test_повторная_регистрация_отвечает_ровно_тем_же(client, caplog):
    """Главная утечка регистрации: по разнице ответов перебирают, у кого из
    списка почт есть аккаунт."""
    первый = client.post("/api/auth/register",
                         json={"email": ПОЧТА, "password": ПАРОЛЬ,
                               "nickname": НИК})
    # Ник у повторов свой: занятый ник — отказ независимо от почты (так и
    # задумано, см. `register`), и одинаковый ник спрятал бы саму проверку.
    второй = client.post("/api/auth/register",
                         json={"email": ПОЧТА, "password": "какой-то-другой",
                               "nickname": "ivan-два"})

    # Третий — уже по подтверждённой почте: это тот случай, ради которого всё и
    # делается, потому что «есть аккаунт» и «есть подтверждённый аккаунт» —
    # разные сведения, и оба чужие.
    client.post("/api/auth/confirm", json={"token": токен_из_письма(caplog)})
    третий = client.post("/api/auth/register",
                         json={"email": ПОЧТА, "password": "и-ещё-один-такой",
                               "nickname": "ivan-три"})

    assert первый.status_code == второй.status_code == третий.status_code == 201
    assert первый.json() == второй.json() == третий.json()

    # И пароль повторной попытки не подменил настоящий: чужой человек,
    # приславший ту же почту, не должен получить вход в чужой аккаунт.
    assert войти(client, пароль="какой-то-другой").status_code == 401
    assert войти(client, пароль="и-ещё-один-такой").status_code == 401
    assert войти(client).status_code == 200


def test_забытый_пароль_отвечает_одинаково_знакомой_и_незнакомой_почте(
        client, caplog):
    завести_и_подтвердить(client, caplog)
    свой = client.post("/api/auth/password/forgot", json={"email": ПОЧТА})
    чужой = client.post("/api/auth/password/forgot",
                        json={"email": "никого@example.org"})
    assert свой.status_code == чужой.status_code == 200
    assert свой.json() == чужой.json()


def test_пароль_не_виден_ни_в_ответе_ни_в_журнале(client, caplog):
    """Содержимое тел не пишется никогда. Пароль — в первую очередь."""
    завести_и_подтвердить(client, caplog)
    ответы = [войти(client), client.get("/api/auth/me"),
              client.post("/api/auth/logout"),
              войти(client, пароль="не-тот-пароль-вовсе")]
    for ответ in ответы:
        assert ПАРОЛЬ not in ответ.text

    строки = "\n".join(з.getMessage() for з in caplog.records)
    assert ПАРОЛЬ not in строки
    assert "не-тот-пароль-вовсе" not in строки
    # И хеша тоже: он не секрет, но и рассказывать его незачем.
    assert "argon2" not in строки


def test_токен_в_базе_лежит_хешем(client, app, caplog):
    """Снимок базы, попавший не туда, не должен давать вход в чужой аккаунт."""
    токен = зарегистрировать(client, caplog)
    with app.state.db.session_scope() as s:
        строка = s.scalars(select(EmailToken)).one()
        assert строка.token_hash != токен
        assert строка.token_hash == service.хеш_токена(токен)


# ── токены ───────────────────────────────────────────────────────────────────

def test_протухший_токен_отличается_от_негодного(client, app, caplog):
    """Интерфейсу нужны разные кнопки: «попросите новую ссылку» и «ссылка не
    годится»."""
    токен = зарегистрировать(client, caplog)
    with app.state.db.session_scope() as s:
        строка = s.scalars(select(EmailToken)).one()
        строка.expires_at = now() - datetime.timedelta(minutes=1)

    ответ = client.post("/api/auth/confirm", json={"token": токен})
    assert ответ.status_code == 400
    assert ответ.json()["error"]["code"] == "token_expired"
    assert ответ.json()["error"]["where"] == "body.token"

    чужой = client.post("/api/auth/confirm", json={"token": "выдуманный"})
    assert чужой.json()["error"]["code"] == "invalid_token"


def test_токен_одноразовый(client, caplog):
    токен = зарегистрировать(client, caplog)
    assert client.post("/api/auth/confirm",
                       json={"token": токен}).status_code == 200
    второй = client.post("/api/auth/confirm", json={"token": токен})
    assert второй.status_code == 400
    assert второй.json()["error"]["code"] == "invalid_token"


def test_новое_письмо_гасит_прежний_токен(client, caplog):
    """Два годных письма «подтвердите почту» — это два входа в аккаунт."""
    первый = зарегистрировать(client, caplog)
    # Ник у второй попытки другой: свой же ник занят, и регистрация с ним
    # отвечает `nickname_taken` — так и задумано (см. `register`), потому что
    # иначе ответ разошёлся бы для занятой и свободной почты.
    второй = зарегистрировать(client, caplog, ник="ivan-ещё")
    assert первый != второй
    assert client.post("/api/auth/confirm",
                       json={"token": первый}).status_code == 400
    assert client.post("/api/auth/confirm",
                       json={"token": второй}).status_code == 200


# ── сброс пароля ─────────────────────────────────────────────────────────────

def test_сброс_пароля_меняет_пароль_и_гасит_сессии(client, caplog):
    """Пароль меняют, когда его увели: сессия, взятая старым паролем, не должна
    пережить смену."""
    завести_и_подтвердить(client, caplog)
    assert войти(client).status_code == 200
    assert client.get("/api/auth/me").status_code == 200

    assert client.post("/api/auth/password/forgot",
                       json={"email": ПОЧТА}).status_code == 200
    токен = токен_из_письма(caplog)
    ответ = client.post("/api/auth/password/reset",
                        json={"token": токен, "password": НОВЫЙ_ПАРОЛЬ})
    assert ответ.status_code == 200, ответ.text

    assert client.get("/api/auth/me").status_code == 401
    assert войти(client, пароль=ПАРОЛЬ).status_code == 401
    assert войти(client, пароль=НОВЫЙ_ПАРОЛЬ).status_code == 200


def test_сброс_подтверждает_почту(client, caplog):
    """Человек прочитал письмо по этому адресу — это и есть подтверждение."""
    зарегистрировать(client, caplog)
    client.post("/api/auth/password/forgot", json={"email": ПОЧТА})
    client.post("/api/auth/password/reset",
                json={"token": токен_из_письма(caplog),
                      "password": НОВЫЙ_ПАРОЛЬ})
    assert войти(client, пароль=НОВЫЙ_ПАРОЛЬ).status_code == 200


def test_токен_подтверждения_не_годится_для_сброса(client, caplog):
    """Назначение токена — часть самого токена: иначе ссылка «подтвердите
    почту» меняет пароль."""
    токен = зарегистрировать(client, caplog)
    ответ = client.post("/api/auth/password/reset",
                        json={"token": токен, "password": НОВЫЙ_ПАРОЛЬ})
    assert ответ.status_code == 400
    assert ответ.json()["error"]["code"] == "invalid_token"


# ── сессии ───────────────────────────────────────────────────────────────────

def test_выход_отовсюду_убивает_вторую_сессию(app, client, caplog):
    """То, ради чего сессии лежат в базе, а не только в подписанном cookie."""
    завести_и_подтвердить(client, caplog)
    войти(client)

    with TestClient(app) as второй:
        assert войти(второй).status_code == 200
        assert второй.get("/api/auth/me").status_code == 200

        assert client.post("/api/auth/logout-all").status_code == 200
        # Второе устройство узнаёт об этом на первом же запросе.
        assert второй.get("/api/auth/me").status_code == 401

    assert client.get("/api/auth/me").status_code == 401


def test_выход_отовсюду_требует_входа(client):
    ответ = client.post("/api/auth/logout-all")
    assert ответ.status_code == 401
    assert ответ.json()["error"]["code"] == "unauthenticated"


def test_выход_без_сессии_всё_равно_удаётся(client):
    """«Выйти» обязано удаваться всегда — иначе человек остаётся с cookie,
    которую нечем убрать."""
    assert client.post("/api/auth/logout").status_code == 200


def test_протухшая_сессия_не_пускает(app, client, caplog):
    завести_и_подтвердить(client, caplog)
    войти(client)
    with app.state.db.session_scope() as s:
        сессия = s.scalars(select(UserSession)).one()
        сессия.expires_at = now() - datetime.timedelta(minutes=1)
    assert client.get("/api/auth/me").status_code == 401


def test_сессия_продлевается_но_не_чаще_раза_в_час(app, client, caplog):
    """Продление на каждый запрос — это запись в базу на каждое движение мышью;
    на SQLite с одним писателем это стоит всему сайту."""
    завести_и_подтвердить(client, caplog)
    войти(client)

    def срок():
        with app.state.db.session_scope() as s:
            return s.scalars(select(UserSession)).one().expires_at

    было = срок()
    client.get("/api/auth/me")
    assert срок() == было              # прошла секунда — двигать нечего

    with app.state.db.session_scope() as s:
        сессия = s.scalars(select(UserSession)).one()
        сессия.last_seen_at = now() - datetime.timedelta(hours=2)
    client.get("/api/auth/me")
    assert срок() > было               # прошло два часа — сессия продлилась


# ── cookie ───────────────────────────────────────────────────────────────────

def _cookie(ответ) -> str:
    установка = [з for и, з in ответ.headers.multi_items()
                 if и.lower() == "set-cookie" and з.startswith(service.COOKIE)]
    assert установка, ответ.headers
    return установка[0]


def test_флаги_cookie_в_dev(client, caplog):
    """`Secure` в dev не ставится: сайт живёт на `http://localhost`, и cookie с
    этим флагом браузер попросту не сохранит."""
    завести_и_подтвердить(client, caplog)
    печенье = _cookie(войти(client))
    assert "HttpOnly" in печенье
    assert "samesite=lax" in печенье.lower()
    assert "Secure" not in печенье
    assert "Domain" not in печенье          # домен не задаём: поддомены чужие
    assert "Path=/" in печенье


def test_флаги_cookie_в_prod(tmp_path, caplog):
    app = приложение(tmp_path, env="prod")
    with TestClient(app) as прод:
        завести_и_подтвердить(прод, caplog)
        печенье = _cookie(войти(прод))
    assert "Secure" in печенье
    assert "HttpOnly" in печенье
    assert "Domain" not in печенье


def test_secure_снимается_настройкой(tmp_path, caplog):
    """`KORITSU_COOKIE_SECURE=no` в prod — ради дней теста без домена.

    Домена пока нет, сайт живёт по HTTP на IP машины, а cookie с флагом
    `Secure` браузер по HTTP не сохраняет — человек вошёл бы и
    тут же снова увидел форму входа. Выбор был между «поднять боевую машину как
    dev» (и разом потерять `trust_proxy` и всё прочее, что различает режимы) и
    одной настройкой; проверяется здесь именно она, а не режим.
    """
    app = приложение(tmp_path, env="prod", cookie_secure=False)
    with TestClient(app) as прод:
        завести_и_подтвердить(прод, caplog)
        печенье = _cookie(войти(прод))
    assert "Secure" not in печенье
    # Всё остальное на месте: снимается ровно один флаг, а не защита целиком.
    assert "HttpOnly" in печенье
    assert "samesite=lax" in печенье.lower()


def test_secure_ставится_настройкой_и_в_dev(tmp_path, caplog):
    """И наоборот: `yes` в dev. Настройка сильнее режима в обе стороны —
    иначе она была бы не настройкой, а поблажкой."""
    app = приложение(tmp_path, env="dev", cookie_secure=True)
    with TestClient(app) as дев:
        завести_и_подтвердить(дев, caplog)
        печенье = _cookie(войти(дев))
    assert "Secure" in печенье


def test_cookie_csrf_берёт_тот_же_флаг(tmp_path, caplog):
    """Заслон CSRF выдаёт свою cookie флагами соседа (`csrf.поставить`).

    Разошедшись, две cookie стали бы для браузера разными по области действия, и
    сайт молча перестал бы находить токен на половине страниц.
    """
    from api import csrf

    app = приложение(tmp_path, env="prod", cookie_secure=False)
    with TestClient(app) as прод:
        завести_и_подтвердить(прод, caplog)
        ответ = войти(прод)
    csrf_печенье = [з for и, з in ответ.headers.multi_items()
                    if и.lower() == "set-cookie" and з.startswith(csrf.COOKIE)]
    assert csrf_печенье, ответ.headers
    assert "Secure" not in csrf_печенье[0]


# ── лимиты ───────────────────────────────────────────────────────────────────

def test_лимит_регистраций_по_адресу(tmp_path, caplog):
    """Заслон от массовой регистрации. Считается любая попытка, включая
    повторную с занятой почтой, — иначе счётчик обходится одним и тем же
    адресом."""
    app = приложение(tmp_path, trust_proxy=True,
                     registrations_per_ip_per_day=3)
    with TestClient(app) as c:
        свой = {"x-forwarded-for": "203.0.113.7"}
        for н in range(3):
            ответ = c.post("/api/auth/register", headers=свой,
                           json={"email": f"кто{н}@example.org",
                                 "password": ПАРОЛЬ, "nickname": f"кто{н}"})
            assert ответ.status_code == 201

        лишний = c.post("/api/auth/register", headers=свой,
                        json={"email": "ещё@example.org", "password": ПАРОЛЬ,
                              "nickname": "ещё"})
        assert лишний.status_code == 429
        assert лишний.json()["error"]["code"] == "rate_limited"

        # Сосед по интернету за чужой лимит не отвечает.
        другой = c.post("/api/auth/register",
                        headers={"x-forwarded-for": "203.0.113.8"},
                        json={"email": "сосед@example.org",
                              "password": ПАРОЛЬ, "nickname": "сосед"})
        assert другой.status_code == 201


def test_заголовку_прокси_верят_только_когда_велено(tmp_path):
    """Иначе лимит по IP обходится одной строкой заголовка."""
    доверчивое = приложение(tmp_path, trust_proxy=True)
    строгое = приложение(tmp_path, trust_proxy=False)

    class Запрос:
        headers = {"x-forwarded-for": "198.51.100.1, 10.0.0.1"}
        client = type("К", (), {"host": "10.0.0.1"})()

    assert service.client_ip(Запрос(), доверчивое.state.settings) == "198.51.100.1"
    assert service.client_ip(Запрос(), строгое.state.settings) == "10.0.0.1"


def test_умолчание_доверия_прокси_из_режима(tmp_path):
    """За Caddy (prod) заголовок — единственный источник настоящего адреса; на
    открытом порту (dev) он — подделка."""
    assert приложение(tmp_path, env="prod").state.settings.trust_proxy is True
    assert приложение(tmp_path, env="dev").state.settings.trust_proxy is False


def test_перебор_пароля_запирает_аккаунт(client, caplog):
    """После десяти неудач подряд перебор идёт со скоростью четыре пароля в час."""
    завести_и_подтвердить(client, caplog)

    for _ in range(FAILS_BEFORE_LOCK - 1):
        assert войти(client, пароль="не-тот-пароль").status_code == 401

    # Десятая неудача — та же 401, но замок уже повешен.
    assert войти(client, пароль="не-тот-пароль").status_code == 401

    заперто = войти(client, пароль="не-тот-пароль")
    assert заперто.status_code == 429
    assert заперто.json()["error"]["code"] == "rate_limited"

    # И настоящий пароль тоже не пускает: замок на аккаунте, а не на попытке.
    assert войти(client).status_code == 429


def test_удачный_вход_обнуляет_счётчик_неудач(client, app, caplog):
    """Девять забытых паролей за полгода не должны запирать аккаунт на десятой
    опечатке."""
    завести_и_подтвердить(client, caplog)
    for _ in range(3):
        войти(client, пароль="не-тот-пароль")
    assert войти(client).status_code == 200
    with app.state.db.session_scope() as s:
        assert s.scalars(select(User)).one().failed_logins == 0


# ── форма запроса ────────────────────────────────────────────────────────────

def test_короткий_пароль_не_проходит(client):
    ответ = client.post("/api/auth/register",
                        json={"email": ПОЧТА, "password": "коротко",
                              "nickname": НИК})
    assert ответ.status_code == 422
    assert ответ.json()["error"]["code"] == "validation_failed"
    assert ответ.json()["error"]["where"] == "body.password"


def test_не_почта_не_проходит(client):
    ответ = client.post("/api/auth/register",
                        json={"email": "просто строка", "password": ПАРОЛЬ,
                              "nickname": НИК})
    assert ответ.status_code == 422
    assert ответ.json()["error"]["where"] == "body.email"


def test_почта_нормализуется(client, app, caplog):
    """`Ivan@X.RU` и `ivan@x.ru` — один человек, иначе войти он сможет только в
    один из двух своих аккаунтов и не поймёт, в какой."""
    завести_и_подтвердить(client, caplog, почта=" Ivan@Example.ORG ")
    with app.state.db.session_scope() as s:
        assert s.scalars(select(User)).one().email == "ivan@example.org"
    assert войти(client, почта="IVAN@example.org").status_code == 200


# ── хук «пользователь заведён» ───────────────────────────────────────────────

def test_хук_зовут_с_готовым_пользователем(client, caplog):
    """`on_user_created` — то, чем `workspaces` заводит личный workspace. Зовут его
    после `flush`, то есть `user.id` уже есть, и до коммита."""
    позвали = []

    def запомнить(s, user):
        assert user.id, "хук позвали до flush: идентификатора ещё нет"
        позвали.append(user.id)

    service.on_user_created.append(запомнить)
    try:
        зарегистрировать(client, caplog)
        assert len(позвали) == 1
        # Повторная регистрация той же почты нового пользователя не заводит.
        client.post("/api/auth/register",
                    json={"email": ПОЧТА, "password": ПАРОЛЬ,
                          "nickname": "ivan-ещё"})
        assert len(позвали) == 1
    finally:
        service.on_user_created.remove(запомнить)


def test_беда_в_хуке_откатывает_регистрацию(client, app):
    """Пользователь без личного workspace хуже, чем незарегистрированный."""
    def сломать(s, user):
        raise RuntimeError("хук не смог")

    service.on_user_created.append(сломать)
    try:
        ответ = client.post("/api/auth/register",
                            json={"email": ПОЧТА, "password": ПАРОЛЬ,
                                  "nickname": НИК})
        assert ответ.status_code == 500
    finally:
        service.on_user_created.remove(сломать)

    with app.state.db.session_scope() as s:
        assert s.scalars(select(User)).all() == []


# ── журнал ───────────────────────────────────────────────────────────────────

def test_события_безопасности_идут_отдельным_потоком(client, caplog):
    """Два потока — технический и события безопасности."""
    завести_и_подтвердить(client, caplog)
    войти(client, пароль="не-тот-пароль")
    события = [з.getMessage() for з in caplog.records
               if з.name == "api.security"]
    assert any("event=login_failed" in с for с in события)
    assert any("event=registered" in с for с in события)
    # Почты в событиях нет: при удалении аккаунта она обязана исчезнуть.
    assert not any(ПОЧТА in с for с in события)


def test_технический_журнал_называет_вошедшего(client, caplog):
    """В техническом потоке — id запроса, UUID пользователя, маршрут.
    UUID туда кладёт `current_user` через `request.state.user_id`; пока его
    никто не выставил, каркас пишет `user=-`."""
    завести_и_подтвердить(client, caplog)
    кто = войти(client).json()["user"]["id"]
    caplog.clear()
    client.get("/api/auth/me")
    строки = [з.getMessage() for з in caplog.records
              if з.name == "api.request"]
    assert any(f"user={кто}" in с for с in строки), строки


def test_письмо_несёт_ссылку_с_адресом_из_настроек(client, caplog):
    """Ссылка собирается из настройки, а не из заголовка `Host`: иначе чужой
    запрос с чужим `Host` уносит настоящий токен на чужой сайт."""
    зарегистрировать(client, caplog)
    assert "http://localhost:8000/confirm?token=" in письма(caplog)[-1]


# ── ник ──────────────────────────────────────────────────────────────────────

def test_ник_обязателен_при_регистрации(client):
    """Без ника аккаунт заводить некому: ник — имя человека на всех экранах."""
    ответ = client.post("/api/auth/register",
                        json={"email": ПОЧТА, "password": ПАРОЛЬ})
    assert ответ.status_code == 422
    assert ответ.json()["error"]["where"] == "body.nickname"


def test_ник_виден_в_профиле_как_набран(client, caplog, app):
    """Регистр не трогается: `КириСу` — так человек себя и назвал."""
    завести_и_подтвердить(client, caplog, ник="КириСу")
    тело = войти(client).json()["user"]
    assert тело["nickname"] == "КириСу"
    with app.state.db.session_scope() as s:
        строка = s.scalars(select(User)).one()
        # А сравнивается ник по приведённому ключу — он и лежит рядом.
        assert строка.nickname_key == "кирису"


def test_ник_занят_без_учёта_регистра(client, caplog):
    """`Ivan` и `IVAN` — один и тот же ник, иначе двух людей в списке
    участников не различить вовсе."""
    зарегистрировать(client, caplog, ник="Ivan")
    ответ = client.post("/api/auth/register",
                        json={"email": "другой@example.org",
                              "password": ПАРОЛЬ, "nickname": "IVAN"})
    assert ответ.status_code == 409
    assert ответ.json()["error"]["code"] == "nickname_taken"
    assert ответ.json()["error"]["where"] == "body.nickname"


def test_ник_занят_без_учёта_регистра_и_на_кириллице(client, caplog):
    """Отдельно от латиницы: `lower()` в SQLite кириллицу не трогает, и
    уникальность держится приведением в Python (`nickname_key`)."""
    зарегистрировать(client, caplog, ник="Курису")
    ответ = client.post("/api/auth/register",
                        json={"email": "другой@example.org",
                              "password": ПАРОЛЬ, "nickname": "КУРИСУ"})
    assert ответ.status_code == 409
    assert ответ.json()["error"]["code"] == "nickname_taken"


@pytest.mark.parametrize("ник", ["и", "", " ", "а" * 33, "ник с пробелом",
                                 "ник!", "поч@та", "ник.точка"])
def test_негодный_ник_отвергается_своим_кодом(client, ник):
    """`invalid_nickname`, а не `validation_failed`: сайт показывает под полем
    подсказку про знаки, а не общее «проверьте форму»."""
    ответ = client.post("/api/auth/register",
                        json={"email": ПОЧТА, "password": ПАРОЛЬ,
                              "nickname": ник})
    assert ответ.status_code == 422, ответ.text
    assert ответ.json()["error"]["code"] == "invalid_nickname"
    assert ответ.json()["error"]["where"] == "body.nickname"


@pytest.mark.parametrize("ник", ["ки", "а" * 32, "Ки_ри-Су2", "курису",
                                 "Курису_2026"])
def test_годный_ник_проходит(client, caplog, ник):
    """Границы включительно и кириллица — разрешены прямо."""
    ответ = client.post("/api/auth/register",
                        json={"email": ПОЧТА, "password": ПАРОЛЬ,
                              "nickname": ник})
    assert ответ.status_code == 201, ответ.text


def test_края_ника_обрезаются(client, caplog, app):
    """`  ник  ` и `ник` — один человек: пробелы по краям не имя."""
    завести_и_подтвердить(client, caplog, ник="  курису  ")
    with app.state.db.session_scope() as s:
        assert s.scalars(select(User)).one().nickname == "курису"


def test_правка_профиля_меняет_ник(client, caplog):
    """`PATCH /api/auth/me` — единственный способ переименоваться."""
    завести_и_подтвердить(client, caplog)
    войти(client)

    ответ = client.patch("/api/auth/me", json={"nickname": "Курису"})
    assert ответ.status_code == 200, ответ.text
    assert ответ.json()["user"]["nickname"] == "Курису"
    # И это не только в ответе: `me` рассказывает то же самое.
    assert client.get("/api/auth/me").json()["user"]["nickname"] == "Курису"


def test_правка_профиля_не_даёт_занять_чужой_ник(client, caplog):
    завести_и_подтвердить(client, caplog, почта="сосед@example.org",
                          ник="сосед")
    завести_и_подтвердить(client, caplog)
    войти(client)

    ответ = client.patch("/api/auth/me", json={"nickname": "СОСЕД"})
    assert ответ.status_code == 409
    assert ответ.json()["error"]["code"] == "nickname_taken"


def test_правка_профиля_разрешает_свой_же_ник_в_другом_регистре(client, caplog):
    """Себя же ник не занимает: иначе поменять `ivan` на `Ivan` было бы
    нельзя, а это ровно та правка, за которой в профиль и приходят."""
    завести_и_подтвердить(client, caplog, ник="ivan")
    войти(client)
    ответ = client.patch("/api/auth/me", json={"nickname": "Ivan"})
    assert ответ.status_code == 200, ответ.text
    assert ответ.json()["user"]["nickname"] == "Ivan"


def test_правка_профиля_отвергает_негодный_ник(client, caplog):
    завести_и_подтвердить(client, caplog)
    войти(client)
    ответ = client.patch("/api/auth/me", json={"nickname": "ник с пробелом"})
    assert ответ.status_code == 422
    assert ответ.json()["error"]["code"] == "invalid_nickname"


def test_правка_профиля_без_полей_ничего_не_ломает(client, caplog):
    """Пустое тело — «ничего не менять», а не «стереть всё»."""
    завести_и_подтвердить(client, caplog, ник="ivan")
    войти(client)
    ответ = client.patch("/api/auth/me", json={})
    assert ответ.status_code == 200, ответ.text
    assert ответ.json()["user"]["nickname"] == "ivan"


def test_правка_профиля_без_входа_не_работает(client):
    assert client.patch("/api/auth/me", json={"nickname": "кто"}).status_code == 401
