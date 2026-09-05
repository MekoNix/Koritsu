"""
Колокольчик: что появляется, когда, ровно ли один раз и кому видно.

Писем нет (§11), поэтому эта таблица — единственное, что переживает закрытую
вкладку. Отсюда и предмет проверки: уведомление обязано появиться **вместе** с
терминальным статусом задания, ровно одно на задание, и только своему хозяину.

Отдельным видом идёт `limit_exhausted`: «прогон не удался» и «кончились деньги»
для человека — разные события с разными действиями (первое повторяют, второе
нет), и различать их разбором `data.code` в клиенте значило бы завести второе
описание того же различия.
"""
from __future__ import annotations

from sqlalchemy import select

from api.jobs.models import Job
from api.notifications.models import Notification
from api.notifications.service import артефакты, при_завершении

from .b_fixtures import прогнать, _чистый_реестр  # noqa: F401
from .c_fixtures import войти, клиент, сосед, хозяин  # noqa: F401


def уведомления(app, user_id: str) -> list[Notification]:
    with app.state.db.session_scope() as s:
        строки = list(s.scalars(select(Notification)
                                .where(Notification.user_id == user_id)
                                .order_by(Notification.created_at)))
        for n in строки:
            s.expunge(n)
        return строки


def поставить(клиент, **payload) -> str:
    ответ = клиент.post("/api/jobs", json={"kind": "probe", "payload": payload})
    assert ответ.status_code == 202, ответ.text
    return ответ.json()["id"]


# ── заведение ────────────────────────────────────────────────────────────────

def test_уведомление_появляется_ровно_при_терминальном_статусе(app, клиент,
                                                               хозяин):
    """Ждущее задание уведомления не имеет: сообщать «готово» о работе, которой
    ещё не было, — это ровно то враньё, ради которого статус ставит родитель."""
    job_id = поставить(клиент, echo="проба")
    assert уведомления(app, хозяин.id) == []

    прогнать(app)
    строки = уведомления(app, хозяин.id)
    assert len(строки) == 1
    n = строки[0]
    assert n.kind == "job_done" and n.job_id == job_id
    assert n.read_at is None
    assert n.data["status"] == "done" and n.data["job_kind"] == "probe"


def test_уведомление_о_задании_ровно_одно(app, клиент, хозяин):
    """Единственность держится `UNIQUE` на `job_id`, а не проверкой в коде: два
    воркера, закрывшие одно задание, столкнулись бы, а не разъехались двумя
    строками в колокольчике."""
    job_id = поставить(клиент)
    прогнать(app)

    with app.state.db.session_scope() as s:
        задание = s.get(Job, job_id)
        # Второй вызов того же хука — то самое, что случилось бы при повторном
        # закрытии задания. Он обязан ничего не сделать и не упасть.
        assert при_завершении(s, задание) is None
    assert len(уведомления(app, хозяин.id)) == 1


def test_упавшее_задание_даёт_свой_вид(app, клиент, хозяин):
    job_id = поставить(клиент, fail=True)
    прогнать(app)
    n = уведомления(app, хозяин.id)[0]
    assert n.kind == "job_failed" and n.job_id == job_id
    assert n.data["code"] == "handler_failed"


def test_отменённое_на_ходу_задание_даёт_свой_вид(app, клиент, хозяин):
    """Отменённое во время работы закрывает воркер, и он же уведомляет."""
    job_id = поставить(клиент)
    with app.state.db.session_scope() as s:
        s.get(Job, job_id).cancel_requested = True
    прогнать(app)
    n = уведомления(app, хозяин.id)[0]
    assert n.kind == "job_cancelled" and n.job_id == job_id


def test_отмена_ждущего_задания_тоже_уведомляет(app, клиент, хозяин):
    """§12: уведомлять и при отмене ждущего. Воркер такое задание не увидит
    вовсе — оно кончается в маршруте отмены, — и без этой строки оно было бы
    единственным терминальным состоянием службы без строки в колокольчике."""
    job_id = поставить(клиент)
    assert клиент.post(f"/api/jobs/{job_id}/cancel").status_code == 200

    строки = уведомления(app, хозяин.id)
    assert len(строки) == 1
    assert строки[0].kind == "job_cancelled" and строки[0].job_id == job_id
    assert строки[0].data["status"] == "cancelled"

    # Воркеру брать нечего, и второго уведомления не появляется.
    assert прогнать(app) is None
    assert len(уведомления(app, хозяин.id)) == 1


def test_потерянное_дважды_задание_уведомляет(app, клиент, хозяин):
    """§12: уведомлять и при `worker_lost`. Воркер, которого не стало, ничего
    человеку не скажет — скажет тот, кто признал задание потерянным."""
    import datetime                                          # noqa: PLC0415

    from api.db import now                                   # noqa: PLC0415
    from api.jobs.models import RUNNING                      # noqa: PLC0415
    from api.jobs.worker import Worker                       # noqa: PLC0415

    job_id = поставить(клиент)
    воркер = Worker(app.state.settings, db=app.state.db)

    for _ in range(2):
        with app.state.db.session_scope() as s:
            строка = s.get(Job, job_id)
            строка.status = RUNNING
            строка.worker_id = "чужой:1:deadbeef"
            строка.started_at = now() - datetime.timedelta(days=1)
            строка.heartbeat_at = строка.started_at
        assert воркер.поднять_потерянные() == [job_id]

    строки = уведомления(app, хозяин.id)
    assert len(строки) == 1
    assert строки[0].kind == "job_failed" and строки[0].job_id == job_id
    assert строки[0].data["code"] == "worker_lost"


def test_кончившийся_лимит_это_отдельный_вид(app, клиент, хозяин):
    """`limit_exhausted` вместо `job_failed`: человек различает эти два случая
    действием, а не текстом."""
    job_id = поставить(клиент)
    прогнать(app)
    with app.state.db.session_scope() as s:
        задание = s.get(Job, job_id)
        # Задание закрыто; подделываем ровно ту беду, ради которой заведён вид.
        задание.status = "failed"
        задание.error = {"code": "limit_exhausted", "message": "…"}
        s.query(Notification).filter(Notification.job_id == job_id).delete()
        s.flush()
        при_завершении(s, задание)
    assert уведомления(app, хозяин.id)[0].kind == "limit_exhausted"


# ── ссылка на файл ───────────────────────────────────────────────────────────

def test_артефакты_разбирают_оба_договора():
    """`export` кладёт один архив, `build` — пару выходов; читаются оба.

    Разбор, а не одно поле, потому что договоров два и оба уже написаны:
    менять их ради колокольчика значило бы переписать два обработчика и их
    результаты, уже лежащие в базе.
    """
    assert артефакты({"artifact": "0123456789abcdef"}) == {
        "file": "0123456789abcdef"}
    assert артефакты({"artifacts": {"docx": "aa", "pdf": "bb"}}) == {
        "docx": "aa", "pdf": "bb"}
    # Ничего не скачивается — и поля не будет: пустой словарь в `data` означал
    # бы «файл есть, но пустой».
    assert артефакты({"ok": True}) == {}
    assert артефакты(None) == {}
    assert артефакты({"artifact": "", "artifacts": {"docx": None}}) == {}


def test_уведомление_о_выгрузке_несёт_ссылку_на_архив(app, клиент, хозяин):
    """Скачивание из уведомления (решение владельца §3): идентификатор архива
    лежит в `data.artifacts`, а не разыскивается по карточке задания."""
    job_id = поставить(клиент)
    прогнать(app)
    with app.state.db.session_scope() as s:
        задание = s.get(Job, job_id)
        задание.kind = "export"
        задание.result = {"artifact": "0123456789abcdef", "bytes": 42}
        s.query(Notification).filter(Notification.job_id == job_id).delete()
        s.flush()
        при_завершении(s, задание)

    данные = уведомления(app, хозяин.id)[0].data
    assert данные["artifacts"] == {"file": "0123456789abcdef"}
    # Проект нужен рядом со ссылкой: артефакт скачивается маршрутом проекта.
    assert "project_id" in данные


def test_упавшее_задание_ссылки_не_несёт(app, клиент, хозяин):
    """Файла нет — и поля нет: строка колокольчика не должна предлагать
    скачать то, чего служба не построила."""
    поставить(клиент, fail=True)
    прогнать(app)
    assert "artifacts" not in уведомления(app, хозяин.id)[0].data


# ── маршруты ─────────────────────────────────────────────────────────────────

def test_список_отдаёт_свои_и_считает_непрочитанные(app, клиент, хозяин):
    поставить(клиент)
    прогнать(app)
    поставить(клиент, fail=True)
    прогнать(app)

    тело = клиент.get("/api/notifications").json()
    assert тело["unread_count"] == 2
    # Новые сверху: колокольчик открывают ради последнего.
    assert [n["kind"] for n in тело["notifications"]] == ["job_failed", "job_done"]
    # Число и список приходят вместе: иначе «2» нарисовалось бы рядом с пятью
    # строками.
    assert len(тело["notifications"]) == тело["unread_count"]


def test_фильтр_unread(app, клиент, хозяин):
    поставить(клиент)
    прогнать(app)
    nid = клиент.get("/api/notifications").json()["notifications"][0]["id"]
    клиент.post(f"/api/notifications/{nid}/read")

    assert клиент.get("/api/notifications?unread=true").json()["notifications"] == []
    прочитанные = клиент.get("/api/notifications?unread=false").json()
    assert len(прочитанные["notifications"]) == 1
    assert прочитанные["unread_count"] == 0


def test_пометка_прочитанным_не_переписывает_время(app, клиент, хозяин):
    """«Когда человек это увидел» — единственный ответ, и вторая пометка не
    делает его вторым."""
    поставить(клиент)
    прогнать(app)
    nid = клиент.get("/api/notifications").json()["notifications"][0]["id"]

    первый = клиент.post(f"/api/notifications/{nid}/read").json()
    assert первый["read_at"] is not None
    второй = клиент.post(f"/api/notifications/{nid}/read").json()
    assert второй["read_at"] == первый["read_at"]


def test_прочитать_все_одним_запросом(app, клиент, хозяин):
    for _ in range(3):
        поставить(клиент)
        прогнать(app)

    итог = клиент.post("/api/notifications/read-all").json()
    assert итог["marked"] == 3 and итог["unread_count"] == 0
    assert клиент.get("/api/notifications").json()["unread_count"] == 0
    # Повторный вызов помечать нечего — и это не беда.
    assert клиент.post("/api/notifications/read-all").json()["marked"] == 0


def test_чужое_уведомление_это_404_а_не_403(app, клиент, хозяин, сосед):
    """`403` сообщал бы, что строка с таким идентификатором есть (§3)."""
    поставить(клиент)
    прогнать(app)
    nid = клиент.get("/api/notifications").json()["notifications"][0]["id"]

    войти(app, сосед)
    assert клиент.get("/api/notifications").json()["notifications"] == []
    ответ = клиент.post(f"/api/notifications/{nid}/read")
    assert ответ.status_code == 404
    assert ответ.json()["error"]["code"] == "not_found"
