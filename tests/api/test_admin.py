"""
Админка: кого пускает, что показывает и откуда берёт события безопасности.

    GET   /api/admin/users            люди: план, квота, расход за месяц
    PATCH /api/admin/users/{id}       план, лимиты, флаг владельца
    GET   /api/admin/queue            очередь: сколько ждёт, слоты, воркеры
    GET   /api/admin/security         события безопасности, новые сверху

Главное, что здесь проверяется, — не форма ответов, а два запрета: не-админ не
проходит **ни на один** маршрут (защищённая админка — та, где нельзя забыть
маршрут), и ключом сюда не ходят вовсе (§11).

И третье: события безопасности **и правда пишутся** — не «функция вызвана», а
строка в таблице после настоящего отказа входа. Журнал, который никто не
проверил на живом отказе, обнаруживается пустым тогда, когда он нужен.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from api.accounts.models import User
from api.admin import service as админ
from api.jobs.models import QUEUED, RUNNING, Job
from api.tokens import service as ключи

from .c_fixtures import (войти, завести, клиент, личное_id,  # noqa: F401
                         создать_проект, сосед, хозяин)

МАРШРУТЫ = ("/api/admin/users", "/api/admin/queue", "/api/admin/security")


def сделать_админом(app, user):
    """Флаг ставится руками в базе — маршрута «сделай меня админом» нет и не
    будет: его пришлось бы защищать тем же флагом, которого ещё нет."""
    with app.state.db.session_scope() as s:
        строка = s.get(User, user.id)
        строка.is_admin = True
    user.is_admin = True
    return user


@pytest.fixture
def владелец(app, клиент, хозяин):
    """Вошедший админ."""
    return сделать_админом(app, хозяин)


# ── кого пускает ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("путь", МАРШРУТЫ)
def test_не_админ_403(клиент, хозяин, путь):
    """`403`, а не `404`: `/api/admin` — известный всем адрес, прятать его
    бессмысленно, а `403` честно говорит вошедшему, что он не туда."""
    ответ = клиент.get(путь)
    assert ответ.status_code == 403, ответ.text
    assert ответ.json()["error"]["code"] == "forbidden"


def test_не_админ_не_правит_людей(клиент, хозяин):
    ответ = клиент.patch(f"/api/admin/users/{хозяин.id}", json={"plan": "pro"})
    assert ответ.status_code == 403


@pytest.mark.parametrize("путь", МАРШРУТЫ)
def test_админ_проходит(клиент, владелец, путь):
    assert клиент.get(путь).status_code == 200


def test_ключом_в_админку_нельзя(app, клиент, владелец):
    """§11: админка меняет планы и права, а ключ живёт в конфиге скрипта."""
    строка = клиент.post("/api/tokens",
                         json={"name": "скрипт",
                               "scopes": list(ключи.ПРАВА)}).json()["token"]
    app.dependency_overrides.clear()
    клиент.headers["Authorization"] = f"Bearer {строка}"

    ответ = клиент.get("/api/admin/users")
    assert ответ.status_code == 401
    assert ответ.json()["error"]["code"] == "token_not_allowed"


# ── люди ─────────────────────────────────────────────────────────────────────

def test_список_людей_с_планом_квотой_и_расходом(клиент, владелец, сосед):
    люди = клиент.get("/api/admin/users").json()["users"]
    по_ид = {ч["id"]: ч for ч in люди}
    assert {владелец.id, сосед.id} <= set(по_ид)

    карточка = по_ид[сосед.id]
    assert карточка["plan"] == "free"
    assert карточка["is_admin"] is False
    assert карточка["spent_units"] == 0
    assert карточка["bytes_used"] >= 0
    assert карточка["quota_bytes"] > 0
    assert карточка["limits"] == {}


def test_расход_за_месяц_считается_по_заданиям(app, клиент, владелец):
    """Расход считается, а не хранится: счётчик разошёлся бы с правдой на
    первом же прогоне, упавшем до записи итога."""
    with app.state.db.session_scope() as s:
        s.add(Job(user_id=владелец.id, kind="fill_tag", status="done",
                  spent_units=1234))

    люди = {ч["id"]: ч for ч in клиент.get("/api/admin/users").json()["users"]}
    assert люди[владелец.id]["spent_units"] == 1234


def test_расход_в_админке_это_цены_видов_а_не_токены(app, клиент, владелец):
    """§12: платят за запуски нашего кода, и админка показывает ровно их.

    Число берётся из общего места (`jobs.service.расход_за_месяц`), поэтому оно
    обязано совпасть с тем, что называет человеку `GET /api/usage`: два запроса,
    написанные порознь, разошлись бы там, где это дороже всего видно.
    """
    from api.jobs.worker import Worker                        # noqa: PLC0415

    ответ = клиент.post("/api/jobs", json={"kind": "probe"})
    assert ответ.status_code == 202, ответ.text
    Worker(app.state.settings, db=app.state.db).run_once(inline=True)

    люди = {ч["id"]: ч for ч in клиент.get("/api/admin/users").json()["users"]}
    # Проба бесплатна по построению: платная проверка «жив ли воркер» — это
    # проверка, которую перестают делать.
    assert люди[владелец.id]["spent_units"] == 0
    assert клиент.get("/api/usage").json()["spent_units"] == 0

    with app.state.db.session_scope() as s:
        s.add(Job(user_id=владелец.id, kind="agent", status="done",
                  spent_units=app.state.settings.price_agent))
    люди = {ч["id"]: ч for ч in клиент.get("/api/admin/users").json()["users"]}
    свой = клиент.get("/api/usage").json()
    assert люди[владелец.id]["spent_units"] == app.state.settings.price_agent
    assert свой["spent_units"] == люди[владелец.id]["spent_units"]
    assert свой["prices"]["agent"] == app.state.settings.price_agent


def test_смена_плана_и_лимитов(app, клиент, владелец, сосед):
    """§11: «пользователи, смена плана, лимиты»."""
    ответ = клиент.patch(f"/api/admin/users/{сосед.id}",
                         json={"plan": "pro",
                               "limits": {"monthly_units": 10, "quota_bytes": 99}})
    assert ответ.status_code == 200, ответ.text
    тело = ответ.json()
    assert тело["plan"] == "pro"
    assert тело["limits"] == {"monthly_units": 10, "quota_bytes": 99}
    assert тело["quota_bytes"] == 99          # личный лимит старше настройки

    with app.state.db.session_scope() as s:
        строка = s.get(User, сосед.id)
        assert строка.plan == "pro"
        assert админ.лимит(строка, "monthly_units", 5) == 10
        assert админ.лимит(строка, "нет такого", 5) == 5


def test_не_названное_поле_не_трогается(клиент, владелец, сосед):
    """Правка «сменить план» не должна молча обнулять лимиты прошлой правки."""
    клиент.patch(f"/api/admin/users/{сосед.id}", json={"limits": {"quota_bytes": 7}})
    ответ = клиент.patch(f"/api/admin/users/{сосед.id}", json={"plan": "pro"})
    assert ответ.json()["limits"] == {"quota_bytes": 7}


def test_несуществующий_человек_404(клиент, владелец):
    ответ = клиент.patch("/api/admin/users/0f2a5f4e-0000-0000-0000-000000000000",
                         json={"plan": "pro"})
    assert ответ.status_code == 404


# ── очередь ──────────────────────────────────────────────────────────────────

def test_очередь_показывает_виды_слоты_и_воркеров(app, клиент, владелец):
    """Страница отвечает на вопрос «жива ли машина», а не «что с моим отчётом»."""
    with app.state.db.session_scope() as s:
        s.add(Job(user_id=владелец.id, kind="parse", status=QUEUED))
        s.add(Job(user_id=владелец.id, kind="parse", status=QUEUED))
        s.add(Job(user_id=владелец.id, kind="fill_report", status=RUNNING,
                  worker_id="машина:1:abcdef01"))

    тело = клиент.get("/api/admin/queue").json()
    assert тело["queued"] == 2 and тело["running"] == 1
    assert тело["by_kind"]["parse"] == {"queued": 2, "running": 0}
    assert тело["by_kind"]["fill_report"] == {"queued": 0, "running": 1}
    assert тело["slots"] == {"per_machine": app.state.settings.job_slots,
                             "per_user": app.state.settings.jobs_per_user}
    assert [в["worker_id"] for в in тело["workers"]] == ["машина:1:abcdef01"]
    assert тело["lost_after_s"] == app.state.settings.job_timeout_s


def test_пустая_очередь_это_нули_а_не_беда(клиент, владелец):
    тело = клиент.get("/api/admin/queue").json()
    assert тело["queued"] == 0 and тело["running"] == 0
    assert тело["by_kind"] == {} and тело["workers"] == []


# ── события безопасности ─────────────────────────────────────────────────────

def test_отказ_входа_попадает_в_таблицу(app, клиент, владелец):
    """Не «функция вызвана», а строка после настоящего отказа входа."""
    завести(app, клиент, "жертва@пример.рф")
    отказ = клиент.post("/api/auth/login",
                        json={"email": "жертва@пример.рф", "password": "не тот"})
    assert отказ.status_code in (401, 403), отказ.text

    события = клиент.get("/api/admin/security").json()["events"]
    виды = [с["kind"] for с in события]
    assert "login_failed" in виды


def test_событие_не_несёт_ни_почты_ни_пароля(app, клиент, владелец):
    """§7: почта — то, что при удалении аккаунта обязано исчезнуть, и в журнале
    ей делать нечего. Пароль — тем более."""
    завести(app, клиент, "жертва@пример.рф")
    клиент.post("/api/auth/login",
                json={"email": "жертва@пример.рф", "password": "не тот"})

    целиком = клиент.get("/api/admin/security").text
    assert "жертва@пример.рф" not in целиком
    assert "не тот" not in целиком


def test_события_отбираются_по_виду(app, клиент, владелец):
    завести(app, клиент, "жертва@пример.рф")
    клиент.post("/api/auth/login",
                json={"email": "жертва@пример.рф", "password": "не тот"})

    отобрано = клиент.get("/api/admin/security",
                          params={"kind": "login_failed"}).json()["events"]
    assert отобрано and {с["kind"] for с in отобрано} == {"login_failed"}


def test_секреты_из_подробностей_вырезаются():
    """Место, пишущее событие, однажды передаст `token=…` — и лучше, если это
    отсечёт код, а не обещание в докстроке."""
    from api.admin.service import _почистить

    очищено = _почистить({"fails": 3, "token": "kor_секрет",
                          "email": "к@т.рф", "password": "п"})
    assert очищено == {"fails": 3}


def test_событие_переживает_удаление_аккаунта_обезличенным(app, клиент,
                                                           владелец):
    """§7 дословно: «для журнала безопасности оставить только обезличенную
    запись».

    Каскад унёс бы след «с этого адреса ломились» вместе с аккаунтом — то есть
    ровно то, чего добивался бы тот, кто ломился. Поэтому ключ снимает связь
    (`SET NULL`), а не строку.
    """
    from api.admin.models import SecurityEvent

    жертва = завести(app, клиент, "жертва@пример.рф")
    клиент.post("/api/auth/login",
                json={"email": "жертва@пример.рф", "password": "не тот"})

    with app.state.db.session_scope() as s:
        s.delete(s.get(User, жертва.id))

    with app.state.db.session_scope() as s:
        строки = list(s.scalars(select(SecurityEvent)
                                .where(SecurityEvent.kind == "login_failed")))
    assert строки, "событие исчезло вместе с аккаунтом"
    assert all(с.user_id is None for с in строки)
    assert all(с.ip for с in строки)


def test_события_переживают_откат_запроса(app, клиент, владелец):
    """Отказ откатывает сессию запроса; событие обязано остаться.

    Ради этого журнал и пишется своей транзакцией после ответа: событие,
    записанное сессией запроса, откатилось бы вместе с тем самым отказом, о
    котором оно и рассказывает.
    """
    from api.admin.models import SecurityEvent

    завести(app, клиент, "жертва@пример.рф")
    клиент.post("/api/auth/login",
                json={"email": "жертва@пример.рф", "password": "не тот"})

    with app.state.db.session_scope() as s:
        строки = list(s.scalars(select(SecurityEvent)
                                .where(SecurityEvent.kind == "login_failed")))
    assert строки and строки[0].ip
