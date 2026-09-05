"""
Админка: кого пускает, что показывает и откуда берёт события безопасности.

    GET   /api/admin/users            люди: план, квота, расход за месяц
    PATCH /api/admin/users/{id}       план, лимиты, флаг владельца
    GET   /api/admin/queue            очередь: сколько ждёт, слоты, воркеры
    GET   /api/admin/security         события безопасности, новые сверху
    GET   /api/admin/stats            расход, задания и регистрации по дням

Главное, что здесь проверяется, — не форма ответов, а два запрета: не-админ не
проходит **ни на один** маршрут (защищённая админка — та, где нельзя забыть
маршрут), и ключом сюда не ходят вовсе.

И третье: события безопасности **и правда пишутся** — не «функция вызвана», а
строка в таблице после настоящего отказа входа. Журнал, который никто не
проверил на живом отказе, обнаруживается пустым тогда, когда он нужен.
"""
from __future__ import annotations

import datetime

import pytest
from sqlalchemy import select

from api.accounts.models import User
from api.admin import service as админ
from api.jobs.models import QUEUED, RUNNING, Job
from api.tokens import service as ключи

from fastapi.testclient import TestClient

from .c_fixtures import (войти, завести, клиент, личное_id,  # noqa: F401
                         создать_проект, сосед, хозяин)

МАРШРУТЫ = ("/api/admin/users", "/api/admin/queue", "/api/admin/security",
            "/api/admin/stats")


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
    """Админка меняет планы и права, а ключ живёт в конфиге скрипта."""
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
    """Платят за запуски нашего кода, и админка показывает ровно их.

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
    """Пользователи, смена плана, лимиты."""
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


# ── сводка для графиков ──────────────────────────────────────────────────────

def test_пустая_сводка_это_нули_а_не_беда(клиент, владелец):
    """Свежая база — не повод отвечать бедой: у графика просто нет столбцов."""
    тело = клиент.get("/api/admin/stats").json()
    assert тело["days"] == 30
    assert тело["jobs_by_kind"] == []
    assert тело["active_users"] == 0
    assert len(тело["usage_by_day"]) == 30
    assert len(тело["registrations_by_day"]) == 30
    assert {т["units"] for т in тело["usage_by_day"]} == {0}
    # Регистрация владельца случилась сегодня, поэтому нулей ждём от всех дней,
    # кроме последнего.
    assert {т["count"] for т in тело["registrations_by_day"][:-1]} == {0}


def test_дни_идут_подряд_и_пустые_среди_них_есть(клиент, владелец):
    """Ряд с пропущенными днями график рисует ровной линией, то есть неправдой."""
    дни = [т["day"] for т in клиент.get("/api/admin/stats",
                                        params={"days": 7}).json()["usage_by_day"]]
    assert len(дни) == 7
    подряд = [datetime.date.fromisoformat(д) for д in дни]
    assert all((б - а).days == 1 for а, б in zip(подряд, подряд[1:]))
    assert подряд[-1] == datetime.datetime.now(datetime.timezone.utc).date()


def test_расход_и_виды_считаются_за_период(app, клиент, владелец):
    """Задание сегодня попадает в сегодняшний столбец и в свой вид."""
    with app.state.db.session_scope() as s:
        s.add(Job(user_id=владелец.id, kind="fill_tag", status="done",
                  spent_units=300))
        s.add(Job(user_id=владелец.id, kind="fill_tag", status="failed",
                  spent_units=200))
        s.add(Job(user_id=владелец.id, kind="build", status=QUEUED))

    тело = клиент.get("/api/admin/stats").json()
    сегодня = тело["usage_by_day"][-1]
    assert сегодня["day"] == datetime.datetime.now(
        datetime.timezone.utc).date().isoformat()
    assert сегодня["units"] == 500
    по_видам = {в["kind"]: в for в in тело["jobs_by_kind"]}
    assert по_видам["fill_tag"] == {"kind": "fill_tag", "count": 2, "failed": 1}
    assert по_видам["build"] == {"kind": "build", "count": 1, "failed": 0}
    # «Активные» — кто хоть что-то запускал, а не все заведённые.
    assert тело["active_users"] == 1


def test_регистрация_попадает_в_свой_день(клиент, владелец, сосед):
    тело = клиент.get("/api/admin/stats").json()
    сегодня = тело["registrations_by_day"][-1]
    assert сегодня["count"] == 2          # владелец и сосед
    assert sum(т["count"] for т in тело["registrations_by_day"]) == 2


def test_старое_в_период_не_попадает(app, клиент, владелец):
    """Окно — именно окно: задание месячной давности из недельной сводки уходит."""
    давно = (datetime.datetime.now(datetime.timezone.utc)
             - datetime.timedelta(days=40))
    with app.state.db.session_scope() as s:
        s.add(Job(user_id=владелец.id, kind="fill_tag", status="done",
                  spent_units=777, created_at=давно))

    неделя = клиент.get("/api/admin/stats", params={"days": 7}).json()
    assert неделя["jobs_by_kind"] == []
    assert sum(т["units"] for т in неделя["usage_by_day"]) == 0

    год = клиент.get("/api/admin/stats", params={"days": 90}).json()
    assert sum(т["units"] for т in год["usage_by_day"]) == 777


def test_период_за_потолком_не_принимается(клиент, владелец):
    """Без потолка `?days=100000` заставляет службу перебрать всю жизнь базы."""
    assert клиент.get("/api/admin/stats", params={"days": 0}).status_code == 422
    assert клиент.get("/api/admin/stats",
                      params={"days": 100000}).status_code == 422


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
    """Почта — то, что при удалении аккаунта обязано исчезнуть, и в журнале
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
    """Для журнала безопасности остаётся только обезличенная запись.

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


# ── блокировка аккаунта ──────────────────────────────────────────────────────

def завести_и_поставить_пароль(клиент, email: str, пароль: str,
                               **поля) -> dict:
    """Владелец заводит человека, тот ставит пароль по ссылке. → карточка.

    Проходит ровно тем путём, которым это делается на живом сайте: `POST
    /api/admin/users` даёт `reset_url`, из него берётся токен, и пароль
    ставится обычным `/auth/password/reset`. Отдельного механизма
    «приглашение» у службы нет, и тест это подтверждает, а не обходит.
    """
    ответ = клиент.post("/api/admin/users", json={"email": email, **поля})
    assert ответ.status_code == 201, ответ.text
    тело = ответ.json()

    токен = тело["reset_url"].split("token=")[1]
    сброс = клиент.post("/api/auth/password/reset",
                        json={"token": токен, "password": пароль})
    assert сброс.status_code == 200, сброс.text
    return тело["user"]


def test_заблокированного_не_пускают_по_паролю(app, клиент, владелец):
    """Пароль верный, а вход отказан — и код у отказа свой (`account_blocked`),
    чтобы сайт сказал не «неверный пароль», а «аккаунт заблокирован»."""
    пароль = "очень-длинный-пароль"
    карточка = завести_и_поставить_пароль(клиент, "гость@пример.рф", пароль)
    вход = {"email": "гость@пример.рф", "password": пароль}
    assert клиент.post("/api/auth/login", json=вход).status_code == 200

    правка = клиент.patch(f"/api/admin/users/{карточка['id']}",
                          json={"blocked": True})
    assert правка.status_code == 200, правка.text
    assert правка.json()["blocked_at"]

    отказ = клиент.post("/api/auth/login", json=вход)
    assert отказ.status_code == 403, отказ.text
    assert отказ.json()["error"]["code"] == "account_blocked"

    снятие = клиент.patch(f"/api/admin/users/{карточка['id']}",
                          json={"blocked": False})
    assert снятие.status_code == 200
    assert снятие.json()["blocked_at"] is None
    assert клиент.post("/api/auth/login", json=вход).status_code == 200


def test_блокировка_отзывает_все_сессии(app, клиент, владелец):
    """Иначе заблокированный дорабатывает в открытой вкладке до конца cookie."""
    from api.accounts.models import UserSession

    пароль = "очень-длинный-пароль"
    карточка = завести_и_поставить_пароль(клиент, "гость@пример.рф", пароль)
    assert клиент.post("/api/auth/login",
                       json={"email": "гость@пример.рф",
                             "password": пароль}).status_code == 200

    клиент.patch(f"/api/admin/users/{карточка['id']}", json={"blocked": True})

    with app.state.db.session_scope() as s:
        сессии = list(s.scalars(select(UserSession)
                                .where(UserSession.user_id == карточка["id"])))
    assert сессии, "сессия входа не завелась — тест ничего не проверил"
    assert all(с.revoked_at is not None for с in сессии)


def test_живая_сессия_заблокированного_получает_403(app, клиент, владелец):
    """Проверка в `current_user`, а не только отзыв сессий: сессия, открытая
    между отзывом и записью, обязана упереться в неё же."""
    пароль = "очень-длинный-пароль"
    карточка = завести_и_поставить_пароль(клиент, "гость@пример.рф", пароль)
    assert клиент.post("/api/auth/login",
                       json={"email": "гость@пример.рф",
                             "password": пароль}).status_code == 200

    # Блокировка ставится прямо в базе — мимо `поправить`, который сессии
    # отзывает: иначе проверять было бы нечего, отказ пришёл бы `401`.
    with app.state.db.session_scope() as s:
        s.get(User, карточка["id"]).blocked_at = datetime.datetime.now(
            datetime.timezone.utc)

    app.dependency_overrides.clear()
    ответ = клиент.get("/api/auth/me")
    assert ответ.status_code == 403, ответ.text
    assert ответ.json()["error"]["code"] == "account_blocked"


def test_ключ_заблокированного_не_работает(app, клиент, владелец):
    """`/api/v1` — третий вход, и блокировка обязана действовать и на нём.

    Отказ именно `account_blocked`, а не «ключ не годится»: ключ как раз
    годный, и человек, услышавший «invalid token», пошёл бы выпускать новый.
    """
    строка = клиент.post("/api/tokens",
                         json={"name": "скрипт",
                               "scopes": list(ключи.ПРАВА)}).json()["token"]
    with app.state.db.session_scope() as s:
        s.get(User, владелец.id).blocked_at = datetime.datetime.now(
            datetime.timezone.utc)

    app.dependency_overrides.clear()
    клиент.headers["Authorization"] = f"Bearer {строка}"
    ответ = клиент.get("/api/v1/projects", params={"workspace_id": "х"})
    assert ответ.status_code == 403, ответ.text
    assert ответ.json()["error"]["code"] == "account_blocked"


def test_блокировка_пишет_событие_безопасности(app, клиент, владелец, сосед):
    """Блокировка и снятие — события журнала: «кто и когда закрыл аккаунт» не
    должно восстанавливаться по памяти владельца."""
    from api.admin.models import SecurityEvent

    клиент.patch(f"/api/admin/users/{сосед.id}", json={"blocked": True})
    клиент.patch(f"/api/admin/users/{сосед.id}", json={"blocked": False})

    with app.state.db.session_scope() as s:
        виды = [с.kind for с in s.scalars(
            select(SecurityEvent).where(SecurityEvent.user_id == сосед.id))]
    assert "account_blocked" in виды
    assert "account_unblocked" in виды


def test_повторная_блокировка_не_плодит_событий(app, клиент, владелец, сосед):
    """`blocked: true` у уже заблокированного — не событие: журнал, в котором
    одно и то же повторяется от каждого сохранения формы, читать нельзя."""
    from api.admin.models import SecurityEvent

    клиент.patch(f"/api/admin/users/{сосед.id}", json={"blocked": True})
    первый = клиент.patch(f"/api/admin/users/{сосед.id}",
                          json={"blocked": True}).json()["blocked_at"]
    второй = клиент.patch(f"/api/admin/users/{сосед.id}",
                          json={"plan": "pro"}).json()["blocked_at"]
    assert первый == второй, "отметка времени переставилась на пустой правке"

    with app.state.db.session_scope() as s:
        сколько = len([с for с in s.scalars(select(SecurityEvent))
                       if с.kind == "account_blocked"])
    assert сколько == 1


# ── заведение человека владельцем ────────────────────────────────────────────

def test_заведённый_человек_подтверждён_и_с_личным_пространством(app, клиент,
                                                                 владелец):
    """Почта подтверждена сразу (владелец знает, кого заводит), а хуки
    регистрации отработали — то есть заведённый ничем не отличается от
    зарегистрировавшегося."""
    from api.workspaces.models import Workspace

    ответ = клиент.post("/api/admin/users",
                        json={"email": "новый@пример.рф", "plan": "pro",
                              "nickname": "новичок"})
    assert ответ.status_code == 201, ответ.text
    тело = ответ.json()
    assert тело["user"]["email"] == "новый@пример.рф"
    assert тело["user"]["nickname"] == "новичок"
    assert тело["user"]["plan"] == "pro"
    assert тело["user"]["email_confirmed"] is True
    assert тело["reset_url"].startswith("http")
    assert "token=" in тело["reset_url"]

    with app.state.db.session_scope() as s:
        свои = list(s.scalars(select(Workspace)
                              .where(Workspace.owner_id == тело["user"]["id"])))
    assert свои


def test_ссылка_сброса_и_правда_даёт_войти(app, клиент, владелец):
    """Тот же механизм, что у «забыл пароль»: своего «приглашения» нет."""
    пароль = "очень-длинный-пароль"
    завести_и_поставить_пароль(клиент, "новый@пример.рф", пароль)
    вход = клиент.post("/api/auth/login",
                       json={"email": "новый@пример.рф", "password": пароль})
    assert вход.status_code == 200, вход.text


def test_дубль_почты_409(клиент, владелец, сосед):
    ответ = клиент.post("/api/admin/users", json={"email": сосед.email})
    assert ответ.status_code == 409, ответ.text
    assert ответ.json()["error"]["code"] == "email_taken"


def test_занятый_ник_409(клиент, владелец, сосед):
    ответ = клиент.post("/api/admin/users",
                        json={"email": "другой@пример.рф",
                              "nickname": сосед.nickname})
    assert ответ.status_code == 409, ответ.text
    assert ответ.json()["error"]["code"] == "nickname_taken"


def test_без_ника_он_берётся_из_почты(клиент, владелец):
    тело = клиент.post("/api/admin/users",
                       json={"email": "марина@пример.рф"}).json()
    assert тело["user"]["nickname"] == "марина"


def test_не_почта_422(клиент, владелец):
    ответ = клиент.post("/api/admin/users", json={"email": "не почта"})
    assert ответ.status_code == 422, ответ.text


# ── справочник планов ────────────────────────────────────────────────────────

def test_справочник_планов(клиент, владелец, settings):
    from api.runs.limits import ПЛАНЫ

    ответ = клиент.get("/api/admin/plans")
    assert ответ.status_code == 200, ответ.text
    планы = ответ.json()["plans"]
    assert [п["plan"] for п in планы] == list(ПЛАНЫ)
    for план in планы:
        assert план["monthly_units"] > 0
        assert план["quota_bytes"] > 0
    по_имени = {п["plan"]: п for п in планы}
    assert по_имени["free"]["monthly_units"] == settings.free_monthly_units
    assert по_имени["free"]["quota_bytes"] == settings.user_quota_bytes
    assert по_имени["pro"]["quota_bytes"] == settings.pro_quota_bytes


def test_неизвестный_план_не_ставится(клиент, владелец, сосед):
    """До справочника план вписывался строкой, и «pr0» молча оставлял человека
    на потолке `free`."""
    ответ = клиент.patch(f"/api/admin/users/{сосед.id}", json={"plan": "pr0"})
    assert ответ.status_code == 400, ответ.text
    assert ответ.json()["error"]["code"] == "unknown_plan"

    заведение = клиент.post("/api/admin/users",
                            json={"email": "х@пример.рф", "plan": "pr0"})
    assert заведение.status_code == 400
    assert заведение.json()["error"]["code"] == "unknown_plan"


def test_план_меняет_потолок_и_квоту(клиент, владелец, сосед, settings):
    """Смена плана обязана менять оба числа, а не одно: до справочника квота
    была одна на всех, и «pro» не давал ни байта сверх `free`."""
    было = {ч["id"]: ч for ч in
            клиент.get("/api/admin/users").json()["users"]}[сосед.id]
    assert было["quota_bytes"] == settings.user_quota_bytes

    стало = клиент.patch(f"/api/admin/users/{сосед.id}",
                         json={"plan": "pro"}).json()
    assert стало["plan"] == "pro"
    assert стало["quota_bytes"] == settings.pro_quota_bytes

    # Личный лимит по-прежнему старше плана.
    личный = клиент.patch(f"/api/admin/users/{сосед.id}",
                          json={"limits": {"quota_bytes": 42}}).json()
    assert личный["quota_bytes"] == 42


def test_потолок_плана_виден_в_расходе(app, клиент, владелец, сосед, settings):
    """`GET /api/usage` считает по тому же справочнику, что и админка."""
    from api.runs.limits import расход

    клиент.patch(f"/api/admin/users/{сосед.id}", json={"plan": "team"})
    with app.state.db.session_scope() as s:
        сводка = расход(s, settings, s.get(User, сосед.id))
    assert сводка.plan == "team"
    assert сводка.limit_units == settings.team_monthly_units


# ── имя, на котором админка живёт ────────────────────────────────────────────
#
# Админка вынесена на домен третьего уровня. Заданное имя означает, что на
# всяком другом маршрутов `/api/admin/*` **не существует** — и здесь
# проверяется именно это: не «отказ», а `404`, и раньше всякого разбора сессии.
#
# Приложение в этих проверках своё: `admin_domain` — настройка, а фикстура
# `app` собирает службу на умолчаниях, где имени нет вовсе (это состояние
# dev-машины, и его проверяет `test_без_имени_домена_всё_как_раньше`).

def служба_с_доменом(tmp_path, домен: str, **правки):
    """Приложение, у которого админка живёт на этом имени."""
    from api import Settings, create_app

    return create_app(Settings.for_tests(tmp_path / "том",
                                         admin_domain=домен, **правки))


def вошедший_владелец(app, c):
    """Завести человека, войти им и дать ему право владельца.

    Имя длинное намеренно: короткое `админ` в этом файле уже занято журналом
    безопасности (`from api.admin import service as админ`), и подмена его
    функцией ломает соседний тест молча.
    """
    user = завести(app, c, "владелец@пример.рф")
    войти(app, user)
    return сделать_админом(app, user)


def test_чужой_хост_админки_не_видит(tmp_path):
    """`Host` не тот — маршрута нет. `404`, а не `403`: с имени сайта админки
    не существует вовсе."""
    app = служба_с_доменом(tmp_path, "admin.koritsu.example")
    with TestClient(app, raise_server_exceptions=False) as c:
        вошедший_владелец(app, c)
        for путь in МАРШРУТЫ:
            ответ = c.get(путь)                     # Host: testserver
            assert ответ.status_code == 404, (путь, ответ.text)
            assert ответ.json()["error"]["code"] == "not_found"


def test_на_своём_хосте_админка_работает(tmp_path):
    """То же приложение, тот же человек — но по имени админки."""
    app = служба_с_доменом(tmp_path, "admin.koritsu.example")
    with TestClient(app, base_url="http://admin.koritsu.example",
                    raise_server_exceptions=False) as c:
        вошедший_владелец(app, c)
        for путь in МАРШРУТЫ:
            assert c.get(путь).status_code == 200, путь


def test_порт_и_схема_в_имени_не_мешают(tmp_path):
    """Имя пишут по-разному: со схемой, с портом, с косой. Приведение к одному
    виду сделано один раз в настройках, и `Host` с портом ему не помеха — 80 и
    443 это один и тот же домен."""
    app = служба_с_доменом(tmp_path, "https://admin.koritsu.example/")
    assert app.state.settings.admin_domain == "admin.koritsu.example"
    with TestClient(app, base_url="http://admin.koritsu.example:8443",
                    raise_server_exceptions=False) as c:
        вошедший_владелец(app, c)
        assert c.get("/api/admin/users").status_code == 200


def test_за_прокси_имя_берётся_из_forwarded_host(tmp_path):
    """За Caddy в `Host` приезжает имя, с которым прокси пошёл в службу, а не
    то, что набрал человек. Заголовок читается **только** при `trust_proxy` —
    иначе админка отдавалась бы одной строкой в curl."""
    заголовок = {"X-Forwarded-Host": "admin.koritsu.example"}

    доверчивая = служба_с_доменом(tmp_path / "да", "admin.koritsu.example",
                                  trust_proxy=True)
    with TestClient(доверчивая, raise_server_exceptions=False) as c:
        вошедший_владелец(доверчивая, c)
        assert c.get("/api/admin/users", headers=заголовок).status_code == 200

    строгая = служба_с_доменом(tmp_path / "нет", "admin.koritsu.example",
                               trust_proxy=False)
    with TestClient(строгая, raise_server_exceptions=False) as c:
        вошедший_владелец(строгая, c)
        assert c.get("/api/admin/users", headers=заголовок).status_code == 404


def test_чужой_хост_старше_прав(tmp_path):
    """Не-админ на чужом имени получает `404`, а не `403`: на этом имени
    маршрута нет ни для кого, и отвечать по-разному разным людям значило бы
    рассказывать, что он есть."""
    app = служба_с_доменом(tmp_path, "admin.koritsu.example")
    with TestClient(app, raise_server_exceptions=False) as c:
        войти(app, завести(app, c, "обычный@пример.рф"))
        assert c.get("/api/admin/users").status_code == 404


def test_без_имени_домена_всё_как_раньше(app, клиент, хозяин):
    """Умолчание — пусто: на dev-машине и на стенде имени у сайта нет вовсе, и
    делить там нечего. Пускает флаг `is_admin`, как и до разделения."""
    assert клиент.get("/api/admin/users").status_code == 403
    сделать_админом(app, хозяин)
    assert клиент.get("/api/admin/users").status_code == 200


def test_имя_домена_едет_сайту_в_профиле(tmp_path):
    """Сайт узнаёт имя админки из `GET /api/auth/me` — первого запроса всякой
    загрузки страницы. Рядом с профилем, а не внутри: это настройка машины, а
    не поле человека."""
    app = служба_с_доменом(tmp_path, "admin.koritsu.example")
    with TestClient(app, raise_server_exceptions=False) as c:
        войти(app, завести(app, c, "кто@пример.рф"))
        тело = c.get("/api/auth/me").json()
    assert тело["admin_domain"] == "admin.koritsu.example"
    assert "admin_domain" not in тело["user"]


def test_без_домена_в_профиле_пусто(клиент, хозяин):
    """Пустая строка, а не отсутствие поля: сайту нужно отличать «домена нет»
    от «поле не пришло», и пустая строка говорит это прямо."""
    assert клиент.get("/api/auth/me").json()["admin_domain"] == ""


@pytest.mark.parametrize("написано, вышло", [
    ("admin.koritsu.example", "admin.koritsu.example"),
    ("https://admin.koritsu.example/", "admin.koritsu.example"),
    ("http://ADMIN.koritsu.example:8443", "admin.koritsu.example"),
    ("  admin.koritsu.example  ", "admin.koritsu.example"),
    ("[2001:db8::1]:8443", "[2001:db8::1]"),
    ("", ""),
])
def test_имя_хоста_приводится_к_одному_виду(написано, вышло):
    """Один разбор на оба конца сравнения — и на настройку, и на заголовок
    `Host`. Два разбора «почти одинаково» — это ровно тот случай, когда
    проверка доступа однажды пропускает не того.

    Адрес в квадратных скобках разбирается по скобке, а не по последнему
    двоеточию: иначе `[2001:db8::1]` потерял бы половину себя.
    """
    from api.settings import имя_хоста

    assert имя_хоста(написано) == вышло
