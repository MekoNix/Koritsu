"""
Очередь заданий: постановка, свои и чужие, отмена, события, реестр видов.

Работу воркера проверяет соседний файл (`test_worker.py`); здесь — договор с
клиентом. Три вещи, которые тут закрепляются и которые ломаются молча:

1. **чужое задание — 404, а не 403.** Разные ответы на «нет такого» и «не твоё»
   превращают перебор идентификаторов в способ узнать, какие из них заняты;
2. **вид задания — закрытый список.** Постановка неизвестного вида обязана
   отказать сразу: строка в базе с видом, которого никто не исполняет, лежала бы
   в очереди вечно и выглядела бы как «воркер не работает»;
3. **лимит на человека — свойство захвата, а не постановки.** Второе задание
   ложится в очередь и ждёт («остальные ждут»), а не получает отказ.
"""
from __future__ import annotations

import datetime

import pytest
from sqlalchemy import select

from api.db import now
from api.jobs import registry
from api.jobs.models import CANCELLED, DONE, Job, JobEvent, QUEUED
from api.jobs.service import убрать_старые
from api.workspaces import EDITOR, VIEWER

from .c_fixtures import (docx_байты, войти, клиент, личное_id,  # noqa: F401
                         создать_проект, сосед, хозяин)


def поставить(клиент, вид: str = "probe", **тело):
    """Постановка задания одной строкой. `probe` — проба очереди, без проекта."""
    return клиент.post("/api/jobs", json={"kind": вид, **тело})


# ── постановка ───────────────────────────────────────────────────────────────

def test_постановка_отвечает_202_и_карточкой(клиент, хозяин):
    """`202`, а не `201`: задание принято, но не сделано.

    `201 Created` обещал бы, что за ним лежит готовый результат, и клиент вправе
    был бы не опрашивать состояние — а опрашивать придётся.
    """
    ответ = поставить(клиент, payload={"echo": 1})
    assert ответ.status_code == 202, ответ.text
    карточка = ответ.json()
    assert карточка["kind"] == "probe"
    assert карточка["status"] == QUEUED
    assert карточка["payload"] == {"echo": 1}
    assert карточка["spent_units"] == 0
    assert карточка["started_at"] is None and карточка["finished_at"] is None


def test_карточка_не_рассказывает_про_воркер(клиент, хозяин):
    """`worker_id`, `heartbeat_at` и `attempt` — наше внутреннее дело.

    Чьей машиной и с какой попытки сделана работа, клиенту знать незачем; те же
    поля покажет админка, у неё другой договор.
    """
    карточка = поставить(клиент).json()
    for поле in ("worker_id", "heartbeat_at", "attempt"):
        assert поле not in карточка, поле


def test_неизвестный_вид_это_400(клиент, хозяин):
    """Список видов закрыт. Строка с неизвестным видом лежала бы в очереди
    вечно и выглядела бы как «воркер не работает»."""
    ответ = поставить(клиент, "починить_всё")
    assert ответ.status_code == 400
    беда = ответ.json()["error"]
    assert беда["code"] == "unknown_job_kind"
    assert беда["where"] == "body.kind"
    # Текст называет годные виды: клиент, набравший опечатку, должен узнать
    # правильное имя из ответа, а не из документации.
    assert "probe" in беда["message"]


def test_вид_с_проектом_требует_проект(клиент, хозяин):
    """`parse` привязан к проекту, и без него это `400`, а не пятисотка воркера."""
    ответ = поставить(клиент, "parse")
    assert ответ.status_code == 400
    assert ответ.json()["error"]["code"] == "project_required"
    assert ответ.json()["error"]["where"] == "body.project_id"


def test_проба_обходится_без_проекта(клиент, хозяин):
    """Проба, которой нужен проект, была бы непригодна ровно тогда, когда нужнее
    всего — когда проверяют службу, у которой ещё нет ни одного проекта."""
    ответ = поставить(клиент)
    assert ответ.status_code == 202
    assert ответ.json()["project_id"] is None


def test_задание_в_проекте(клиент, хозяин):
    проект = создать_проект(клиент, личное_id(клиент), шаблон=docx_байты())
    ответ = поставить(клиент, "parse", project_id=проект["id"],
                      payload={"material": "abc"})
    assert ответ.status_code == 202, ответ.text
    assert ответ.json()["project_id"] == проект["id"]


def test_чужой_проект_это_404(app, клиент, хозяин, сосед):
    """Не участник пространства не узнаёт даже, что такой проект есть."""
    проект = создать_проект(клиент, личное_id(клиент), шаблон=docx_байты())
    войти(app, сосед)
    ответ = поставить(клиент, "parse", project_id=проект["id"])
    assert ответ.status_code == 404
    assert ответ.json()["error"]["code"] == "not_found"


def test_читателю_проекта_ставить_нельзя(app, клиент, хозяин, сосед):
    """`viewer` видит проект, но работы в нём не заводит: задание тратит деньги
    и переписывает теги, то есть это запись, а не чтение."""
    ws = клиент.post("/api/workspaces", json={"name": "кафедра"}).json()["id"]
    проект = создать_проект(клиент, ws, шаблон=docx_байты())
    клиент.post(f"/api/workspaces/{ws}/members",
                json={"email": сосед.email, "role": VIEWER})

    войти(app, сосед)
    отказ = поставить(клиент, "parse", project_id=проект["id"])
    assert отказ.status_code == 403
    assert отказ.json()["error"]["code"] == "forbidden"

    войти(app, хозяин)
    клиент.patch(f"/api/workspaces/{ws}/members/{сосед.id}",
                 json={"role": EDITOR})
    войти(app, сосед)
    assert поставить(клиент, "parse", project_id=проект["id"]).status_code == 202


def test_в_проект_из_корзины_задание_не_поставить(клиент, хозяин):
    """Каталог ещё на томе, но работа в нём кончилась: задание на удалённый
    проект доехало бы до воркера и упало там, где этого никто не увидит."""
    проект = создать_проект(клиент, личное_id(клиент), шаблон=docx_байты())
    клиент.delete(f"/api/projects/{проект['id']}")
    ответ = поставить(клиент, "parse", project_id=проект["id"])
    assert ответ.status_code == 409
    assert ответ.json()["error"]["code"] == "in_trash"


def test_второе_задание_ложится_в_очередь_а_не_в_отказ(клиент, хозяин):
    """Остальные ждут в очереди.

    Отказ заставил бы интерфейс писать «попробуйте позже»; очередь позволяет
    написать «второе в очереди». Сам лимит держит захват — `test_worker`.
    """
    for _ in range(3):
        assert поставить(клиент).status_code == 202
    assert len(клиент.get("/api/jobs").json()["jobs"]) == 3


# ── список и карточка ────────────────────────────────────────────────────────

def test_список_только_свои(app, клиент, хозяин, сосед):
    """Чужое задание не показывается никому, кроме автора, даже в общем
    пространстве: в `payload` лежит то, что он написал."""
    моё = поставить(клиент).json()["id"]
    войти(app, сосед)
    чужое = поставить(клиент).json()["id"]
    assert [j["id"] for j in клиент.get("/api/jobs").json()["jobs"]] == [чужое]

    войти(app, хозяин)
    assert [j["id"] for j in клиент.get("/api/jobs").json()["jobs"]] == [моё]


def test_список_фильтруется_по_проекту_и_состоянию(клиент, хозяин):
    проект = создать_проект(клиент, личное_id(клиент), шаблон=docx_байты())
    в_проекте = поставить(клиент, "parse", project_id=проект["id"]).json()["id"]
    поставить(клиент)

    только = клиент.get("/api/jobs", params={"project_id": проект["id"]}).json()
    assert [j["id"] for j in только["jobs"]] == [в_проекте]

    ждущие = клиент.get("/api/jobs", params={"status": QUEUED}).json()
    assert len(ждущие["jobs"]) == 2
    сделанные = клиент.get("/api/jobs", params={"status": DONE}).json()
    assert сделанные["jobs"] == []


def test_неизвестное_состояние_это_400(клиент, хозяин):
    ответ = клиент.get("/api/jobs", params={"status": "почти_готово"})
    assert ответ.status_code == 400
    assert ответ.json()["error"]["code"] == "unknown_job_status"


def test_карточка_чужого_задания_это_404(app, клиент, хозяин, сосед):
    """403 сообщил бы, что задание с таким идентификатором существует."""
    чужое = поставить(клиент).json()["id"]
    войти(app, сосед)
    ответ = клиент.get(f"/api/jobs/{чужое}")
    assert ответ.status_code == 404
    assert ответ.json()["error"]["code"] == "not_found"


def test_кривой_идентификатор_это_400(клиент, хозяин):
    """Форма проверяется до похода в базу: иначе `../../etc` уехал бы в `s.get`
    и вернулся бы пятисоткой вместо отказа."""
    ответ = клиент.get("/api/jobs/не-uuid")
    assert ответ.status_code == 400
    assert ответ.json()["error"]["code"] == "invalid_id"


def test_карточка_двигает_срок_хранения(app, клиент, хозяин):
    """Срок хранения — 90 дней с последнего обращения. Значит, обращение обязано двигать
    отметку, иначе отчёт, который человек открывает раз в месяц, однажды
    исчезнет у него на глазах."""
    job_id = поставить(клиент).json()["id"]
    давно = now() - datetime.timedelta(days=200)
    with app.state.db.session_scope() as s:
        s.get(Job, job_id).last_seen_at = давно

    assert клиент.get(f"/api/jobs/{job_id}").status_code == 200

    with app.state.db.session_scope() as s:
        стало = s.get(Job, job_id).last_seen_at
    assert стало > давно.replace(tzinfo=None)


# ── отмена ───────────────────────────────────────────────────────────────────

def test_отмена_ждущего_сразу_отменяет(клиент, хозяин):
    """Его никто не брал — останавливать нечего, и просьба тут же становится
    ответом."""
    job_id = поставить(клиент).json()["id"]
    ответ = клиент.post(f"/api/jobs/{job_id}/cancel")
    assert ответ.status_code == 200, ответ.text
    карточка = ответ.json()
    assert карточка["status"] == CANCELLED
    assert карточка["cancel_requested"] is True
    assert карточка["finished_at"] is not None


def test_отмена_работающего_ставит_флаг(app, клиент, хозяин):
    """Работающее не убивается сразу: закрытые теги обязаны остаться, а
    это возможно только если обработчик остановится сам, между шагами."""
    job_id = поставить(клиент).json()["id"]
    with app.state.db.session_scope() as s:
        s.get(Job, job_id).status = "running"

    карточка = клиент.post(f"/api/jobs/{job_id}/cancel").json()
    assert карточка["status"] == "running"
    assert карточка["cancel_requested"] is True


def test_отмена_законченного_это_409(app, клиент, хозяин):
    """Молчаливое «хорошо» на отмену сделанной работы заставило бы интерфейс
    показать «отменено» на готовом отчёте."""
    job_id = поставить(клиент).json()["id"]
    with app.state.db.session_scope() as s:
        s.get(Job, job_id).status = DONE

    ответ = клиент.post(f"/api/jobs/{job_id}/cancel")
    assert ответ.status_code == 409
    assert ответ.json()["error"]["code"] == "already_finished"


def test_отменить_чужое_нельзя(app, клиент, хозяин, сосед):
    чужое = поставить(клиент).json()["id"]
    войти(app, сосед)
    assert клиент.post(f"/api/jobs/{чужое}/cancel").status_code == 404


# ── события ──────────────────────────────────────────────────────────────────

def test_события_отдаются_с_места_обрыва(app, клиент, хозяин):
    """`after`, а не смещение: клиент дочитывает поток с номера, и уборка
    старых событий не сдвигает ему точку возврата."""
    job_id = поставить(клиент).json()["id"]
    with app.state.db.session_scope() as s:
        for n in range(1, 4):
            s.add(JobEvent(job_id=job_id, seq=n, kind="text",
                           data={"text": f"кусок {n}"}))

    всё = клиент.get(f"/api/jobs/{job_id}/events").json()
    assert [e["seq"] for e in всё["events"]] == [1, 2, 3]
    assert всё["status"] == QUEUED and всё["job_id"] == job_id

    хвост = клиент.get(f"/api/jobs/{job_id}/events", params={"after": 2}).json()
    assert [e["seq"] for e in хвост["events"]] == [3]
    assert хвост["events"][0]["data"] == {"text": "кусок 3"}


def test_события_чужого_задания_это_404(app, клиент, хозяин, сосед):
    чужое = поставить(клиент).json()["id"]
    войти(app, сосед)
    assert клиент.get(f"/api/jobs/{чужое}/events").status_code == 404


# ── реестр видов ─────────────────────────────────────────────────────────────

def test_реестр_знает_только_свой_список():
    """Список закрыт: `known` отвечает по нему, а не по наличию обработчика."""
    assert registry.known("probe") and registry.known("fill_tag")
    assert not registry.known("починить_всё")


def test_регистрация_вне_списка_это_беда_настройки():
    """Обработчик вида, которого нет в списке, — код, который невозможно
    позвать: постановка такого задания всё равно отказала бы."""
    from api.errors import ConfigError

    with pytest.raises(ConfigError) as беда:
        registry.register("починить_всё")(lambda ctx: {})
    assert "починить_всё" in str(беда.value)


def test_второй_обработчик_того_же_вида_это_беда():
    """Два обработчика одного вида означают, что задание делает то один, то
    другой, — в зависимости от порядка импорта."""
    from api.errors import ConfigError

    registry.load_handlers()
    with pytest.raises(ConfigError) as беда:
        registry.register("probe")(lambda ctx: {})
    assert "probe" in str(беда.value)
    # Реестр не испорчен: настоящая проба на месте.
    registry.load_handlers()
    assert registry.handler_for("probe") is not None


def test_повторная_регистрация_той_же_функции_молчит():
    """`load_handlers` зовут на каждом шаге воркера; беда на второй вызов
    останавливала бы очередь на ровном месте."""
    registry.load_handlers()
    registry.load_handlers()
    assert "probe" in registry.registered()


def test_умолчания_реестра_строже_незнания():
    """Неизвестный вид: проект — нужен, секрет — не нужен. Оба умолчания
    трактуют незнание как «меньше прав»."""
    assert registry.needs_project("нет_такого") is True
    assert registry.needs_secret("нет_такого") is False
    registry.load_handlers()
    assert registry.needs_project("probe") is False
    assert registry.needs_secret("probe") is False


# ── уборка ───────────────────────────────────────────────────────────────────

def test_уборка_сносит_старые_с_событиями_и_не_трогает_свежие(app, клиент,
                                                              хозяин, settings):
    """90 дней с последнего обращения; потом удаляются и запись задания, и её
    артефакты. Считается `last_seen_at`, а не конец работы."""
    старое = поставить(клиент).json()["id"]
    свежее = поставить(клиент).json()["id"]
    ждущее = поставить(клиент).json()["id"]
    давно = now() - datetime.timedelta(days=settings.jobs_retention_days + 1)

    with app.state.db.session_scope() as s:
        for job_id, состояние, когда in ((старое, DONE, давно),
                                         (свежее, DONE, now()),
                                         (ждущее, QUEUED, давно)):
            задание = s.get(Job, job_id)
            задание.status = состояние
            задание.last_seen_at = когда
        s.add(JobEvent(job_id=старое, seq=1, kind="text", data={"text": "…"}))

    with app.state.db.session_scope() as s:
        убрано = убрать_старые(s, settings)
    assert убрано == [старое]

    with app.state.db.session_scope() as s:
        осталось = set(s.scalars(select(Job.id)))
        событий = list(s.scalars(select(JobEvent.id)))
    # Ждущее не убирается никогда: задание, не дождавшееся воркера девяносто
    # дней, — беда очереди, и стирать её значило бы прятать.
    assert осталось == {свежее, ждущее}
    assert событий == []
