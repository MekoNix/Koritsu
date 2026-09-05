"""
Воркер: захват, слоты, исполнение, отмена, таймаут, потерянные, уборка.

Почти всё здесь гоняется в режиме `inline` — обработчик в том же процессе,
без подпроцесса. Это не «облегчённая проверка вместо настоящей»: подпроцесс
стоит секунду на запуск (импорт FastAPI и SQLAlchemy заново), и полсотни таких
тестов превратили бы набор в минутный. Через настоящий подпроцесс проверяется
ровно то, ради чего он и заведён и что `inline` не умеет по определению:

* работа действительно уезжает в другой процесс и возвращается оттуда;
* таймаут исполняется — убитый по нему ребёнок не оставляет задание в
  наполовину поставленном состоянии;
* окружение вычищено — `KORITSU_SECRET` в подпроцесс не попадает, а виду с
  `needs_secret=True` он приходит каналом.

Обработчик для всего этого — `probe`, проба очереди, живущая в самом пакете
(`api/jobs/probe.py`). Своего обработчика тесты в реестр не подсовывают
намеренно: подсунутый живёт в процессе теста, а в настоящий подпроцесс, который
импортирует пакет заново, не попадает вовсе.
"""
from __future__ import annotations

import dataclasses
import datetime
import threading
import time

from sqlalchemy import select

from api.db import now
from api.jobs import registry
from api.jobs.models import (CANCELLED, DONE, FAILED, Job, JobEvent, QUEUED,
                             RUNNING)
from api.jobs.service import enqueue
from api.jobs.worker import (СЕКРЕТ_ЗАГЛУШКА, TIMEOUT, WORKER_LOST, Worker,
                             окружение)

from .c_fixtures import (docx_байты, войти, клиент, личное_id,  # noqa: F401
                         создать_проект, сосед, хозяин)


def воркер(app, settings=None, **правки) -> Worker:
    """Воркер на базе приложения. Настройки — те же, если не сказано иного."""
    s = settings or app.state.settings
    if правки:
        s = dataclasses.replace(s, **правки)
    return Worker(s, db=app.state.db)


def поставить(клиент, **тело) -> str:
    ответ = клиент.post("/api/jobs", json={"kind": "probe", **тело})
    assert ответ.status_code == 202, ответ.text
    return ответ.json()["id"]


def задание(app, job_id: str) -> Job:
    """Свежая строка задания из базы, отвязанная от сессии."""
    with app.state.db.session_scope() as s:
        строка = s.get(Job, job_id)
        s.expunge(строка)
        return строка


def события(app, job_id: str) -> list[JobEvent]:
    with app.state.db.session_scope() as s:
        строки = list(s.scalars(select(JobEvent)
                                .where(JobEvent.job_id == job_id)
                                .order_by(JobEvent.seq)))
        for е in строки:
            s.expunge(е)
        return строки


# ── обычный ход ──────────────────────────────────────────────────────────────

def test_воркер_делает_задание_и_кладёт_результат(app, клиент, хозяин):
    """Полный шаг: взял ждущее, исполнил, закрыл `done` с результатом."""
    job_id = поставить(клиент, payload={"echo": {"кто": "проба"}, "steps": 2})
    w = воркер(app)
    assert w.run_once(inline=True) == job_id
    assert w.run_once(inline=True) is None, "второй раз брать нечего"

    строка = задание(app, job_id)
    assert строка.status == DONE
    assert строка.result == {"echo": {"кто": "проба"}, "steps": 2}
    assert строка.error is None
    assert строка.started_at is not None and строка.finished_at is not None
    assert строка.worker_id == w.worker_id
    # Сердцебиение снято: задание кончилось, и «живой воркер» на нём — ложь,
    # из-за которой уборщик потерянных однажды поднял бы сделанное.
    assert строка.heartbeat_at is None


def test_прогресс_ложится_и_в_колонку_и_в_поток(app, клиент, хозяин):
    """Карточка нужна тому, кто открыл страницу минуту спустя, поток — тому,
    кто смотрит сейчас. Просить обработчик написать дважды значило бы однажды
    получить их разошедшимися."""
    job_id = поставить(клиент, payload={"steps": 3})
    воркер(app).run_once(inline=True)

    assert задание(app, job_id).progress == {"step": 3, "total": 3,
                                             "note": "step 3"}
    шаги = [e for e in события(app, job_id) if e.kind == "progress"]
    assert [e.data["step"] for e in шаги] == [1, 2, 3]


def test_весь_текст_задания_доезжает_в_том_же_порядке(app, клиент, хозяин):
    """Сколько бы строк ни вышло после склейки, текст в них — тот же и по
    порядку. Склейка вправе объединять куски, но не терять и не переставлять."""
    job_id = поставить(клиент, payload={"steps": 3})
    воркер(app).run_once(inline=True)

    тексты = [e.data["text"] for e in события(app, job_id) if e.kind == "text"]
    assert "".join(тексты) == "step 1 step 2 step 3 "


# ── склейка и потолок событий (сам `JobContext`) ─────────────────────────────

def контекст(app, job_id: str, **правки):
    from api.jobs.context import JobContext

    return JobContext(app.state.db, app.state.settings, job_id, **правки)


def test_куски_текста_подряд_ложатся_одной_строкой(app, клиент, хозяин):
    """Склейка — на стороне записи (~100 мс). Сделанная при чтении, она
    обязывала бы каждого читателя склеивать одинаково, и один из них склеивал
    бы иначе."""
    job_id = поставить(клиент)
    ctx = контекст(app, job_id)
    for кусок in ("ку", "со", "к"):
        ctx.emit({"kind": "text", "text": кусок})
    ctx.close()

    строки = события(app, job_id)
    assert [(e.kind, e.data) for e in строки] == [("text", {"text": "кусок"})]


def test_нетекстовое_событие_не_обгоняет_текст(app, клиент, хозяин):
    """Иначе `tag_closed` оказался бы раньше текста, которым тег закрыли."""
    job_id = поставить(клиент)
    ctx = контекст(app, job_id)
    ctx.emit({"kind": "text", "text": "до"})
    ctx.emit({"kind": "tag_closed", "key": "цель"})
    ctx.emit({"kind": "text", "text": "после"})
    ctx.close()

    assert [(e.kind, e.data) for e in события(app, job_id)] == [
        ("text", {"text": "до"}),
        ("tag_closed", {"key": "цель"}),
        ("text", {"text": "после"}),
    ]


def test_потолок_событий_обрезает_поток_и_говорит_об_этом(app, клиент, хозяин):
    """Обработчик, зациклившийся в шаге с `emit`, иначе кладёт том: миллион
    строк в SQLite — это база, которую перестаёт открывать сайт.

    Молчание было бы хуже обрезки: клиент решил бы, что поток оборвался сам.
    """
    job_id = поставить(клиент)
    ctx = контекст(app, job_id, потолок=3)
    for n in range(10):
        ctx.emit({"kind": "tag_closed", "key": f"тег {n}"})
    ctx.close()

    строки = события(app, job_id)
    assert len(строки) == 4, "три события и одно о том, что дальше обрезано"
    assert строки[-1].kind == "events_truncated"
    assert строки[-1].data == {"limit": 3}


def test_поднятое_задание_продолжает_свой_поток(app, клиент, хозяин):
    """Задание, поднятое после потерянного воркера, не начинает нумерацию
    заново: иначе у клиента в потоке оказались бы два события с одним номером,
    и дочитывание с `after=` пропустило бы половину."""
    job_id = поставить(клиент)
    первый = контекст(app, job_id)
    первый.emit({"kind": "tag_closed", "key": "цель"})
    первый.close()

    второй = контекст(app, job_id)
    второй.emit({"kind": "tag_closed", "key": "выводы"})
    второй.close()

    assert [e.seq for e in события(app, job_id)] == [1, 2]


def test_последнее_событие_говорит_чем_кончилось(app, клиент, хозяин):
    """Клиент, читающий поток, обязан увидеть конец: иначе он останется ждать
    продолжения, которого не будет."""
    job_id = поставить(клиент)
    воркер(app).run_once(inline=True)
    assert события(app, job_id)[-1].kind == DONE


def test_списание_копится_по_ходу(app, клиент, хозяин):
    """Расход наружу во внутренних единицах. Списывается по ходу, а не в
    конце: отменённое задание всё равно потратило то, что успело."""
    job_id = поставить(клиент, payload={"charge": 250})
    воркер(app).run_once(inline=True)
    assert задание(app, job_id).spent_units == 250


def test_нет_обработчика_это_failed_а_не_вечное_ожидание(app, клиент, хозяин,
                                                        monkeypatch):
    """Вид известен, кода под него ещё нет: задание обязано закрыться с внятным
    кодом, а не остаться в очереди навсегда.

    Отсутствие обработчика приходится **изображать**: сегодня обработчик
    есть у каждого вида из `ВИДЫ`, и настоящего кандидата на этот тест не
    осталось. Изображается оно там же, где смотрит воркер, — `handler_for`; из
    реестра вид не выкинуть, потому что `run_once` начинается с
    `load_handlers()` и вернул бы его обратно.

    Тест при этом не стал бессмысленным: он про то, что делает **воркер**,
    получив `None` вместо обработчика, а не про то, у какого вида его нет.
    """
    monkeypatch.setattr(registry, "handler_for", lambda kind: None)
    job_id = поставить(клиент, payload={})
    воркер(app).run_once(inline=True)

    строка = задание(app, job_id)
    assert строка.status == FAILED
    assert строка.error["code"] == "no_handler"


# ── беда обработчика ─────────────────────────────────────────────────────────

def test_падение_обработчика_даёт_failed_без_трассировки(app, клиент, хозяин):
    """Наружу — две строки: код для интерфейса и постоянный текст для человека.

    Ни трассировки, ни текста исключения: в них бывает и путь на томе, и кусок
    чужого документа. Полное — в журнал бед, и только туда.
    """
    job_id = поставить(клиент, payload={"fail": True})
    воркер(app).run_once(inline=True)

    строка = задание(app, job_id)
    assert строка.status == FAILED
    assert строка.error == {"code": "handler_failed",
                            "message": "The job handler failed"}
    беда = str(строка.error)
    assert "Traceback" not in беда and "нарочная" not in беда
    assert строка.result is None


# ── отмена ───────────────────────────────────────────────────────────────────

def test_отмена_между_шагами_даёт_cancelled(app, клиент, хозяин):
    """Обработчик спрашивает `ctx.cancelled()` перед каждым шагом и
    останавливается сам — сделанное при этом сохраняется («закрытые теги
    остаются»)."""
    job_id = поставить(клиент, payload={"steps": 5, "echo": "успел"})
    with app.state.db.session_scope() as s:
        s.get(Job, job_id).cancel_requested = True

    воркер(app).run_once(inline=True)

    строка = задание(app, job_id)
    assert строка.status == CANCELLED
    assert строка.result == {"echo": "успел", "steps": 0}
    assert строка.finished_at is not None
    assert событий_видов(app, job_id)[-1] == CANCELLED


def событий_видов(app, job_id: str) -> list[str]:
    return [e.kind for e in события(app, job_id)]


# ── слоты ────────────────────────────────────────────────────────────────────

def test_второе_задание_того_же_человека_ждёт(app, клиент, хозяин):
    """Один слот на человека, остальные ждут.

    Проверяется именно захват, а не постановка: обе строки в базе лежат, но в
    работу одновременно уходит одна.
    """
    первое = поставить(клиент, payload={"steps": 1})
    второе = поставить(клиент, payload={"steps": 1})
    w = воркер(app, job_slots=4, jobs_per_user=1)

    взято = w.захватить()
    assert взято is not None and взято[0] == первое
    assert w.захватить() is None, "слот человека занят, второе обязано ждать"

    # Первое кончилось — второе пошло.
    with app.state.db.session_scope() as s:
        s.get(Job, первое).status = DONE
    взято = w.захватить()
    assert взято is not None and взято[0] == второе


def test_слоты_машины_считаются_на_двоих_воркеров(app, клиент, хозяин, сосед):
    """Два процесса-воркера на одной машине делят те же два слота.

    Считать слоты в Python нельзя: два процесса насчитали бы по одному
    свободному каждый и взяли бы три задания на два слота. Условие живёт внутри
    того же `UPDATE`, которым задание и захватывается.
    """
    первый = поставить(клиент, payload={"steps": 1})
    войти(app, сосед)
    второй = поставить(клиент, payload={"steps": 1})
    третий = поставить(клиент, payload={"steps": 1})
    войти(app, хозяин)
    четвёртый = поставить(клиент, payload={"steps": 1})

    w1 = воркер(app, job_slots=2, jobs_per_user=1)
    w2 = воркер(app, job_slots=2, jobs_per_user=1)
    assert w1.worker_id != w2.worker_id

    взято = [w1.захватить(), w2.захватить()]
    assert all(в is not None for в in взято)
    assert {в[0] for в in взято} == {первый, второй}
    # Оба слота заняты: третье и четвёртое ждут, хотя их хозяева свободны.
    assert w1.захватить() is None and w2.захватить() is None

    with app.state.db.session_scope() as s:
        работают = list(s.scalars(select(Job.id).where(Job.status == RUNNING)))
        ждут = set(s.scalars(select(Job.id).where(Job.status == QUEUED)))
    assert len(работают) == 2
    assert ждут == {третий, четвёртый}


# ── потерянный воркер ────────────────────────────────────────────────────────

def остановилось(app, job_id: str, *, давность: float) -> None:
    """Сделать вид, что задание взял воркер, которого больше нет."""
    with app.state.db.session_scope() as s:
        строка = s.get(Job, job_id)
        строка.status = RUNNING
        строка.worker_id = "чужой:1:deadbeef"
        строка.started_at = now() - datetime.timedelta(seconds=давность)
        строка.heartbeat_at = строка.started_at


def test_потерянное_задание_поднимается_один_раз(app, клиент, хозяин):
    """Первый раз — обратно в очередь, второй — `failed` с `worker_lost`.

    Это не ретрай упавшего обработчика («повтор упавшего только вручную»):
    упавший сказал о себе сам и закрылся сразу. Поднимается только то, о чём не
    сказал никто.
    """
    job_id = поставить(клиент)
    w = воркер(app, job_timeout_s=1)

    остановилось(app, job_id, давность=100)
    assert w.поднять_потерянные() == [job_id]
    строка = задание(app, job_id)
    assert строка.status == QUEUED and строка.attempt == 1
    assert строка.worker_id is None and строка.heartbeat_at is None

    остановилось(app, job_id, давность=100)
    assert w.поднять_потерянные() == [job_id]
    строка = задание(app, job_id)
    assert строка.status == FAILED and строка.attempt == 2
    assert строка.error["code"] == WORKER_LOST
    assert строка.finished_at is not None
    assert событий_видов(app, job_id)[-1] == FAILED


def test_живое_задание_не_поднимают(app, клиент, хозяин):
    """Сердцебиение — единственное, чем работающий отличается от брошенного."""
    job_id = поставить(клиент)
    остановилось(app, job_id, давность=0)
    with app.state.db.session_scope() as s:
        s.get(Job, job_id).heartbeat_at = now()

    assert воркер(app, job_timeout_s=60).поднять_потерянные() == []
    assert задание(app, job_id).status == RUNNING


def test_сердцебиение_пишет_только_свой_воркер(app, клиент, хозяин):
    """Чужое задание чужим воркером не подтверждается: иначе один процесс
    держал бы живым то, чего он не делает."""
    job_id = поставить(клиент)
    остановилось(app, job_id, давность=100)
    было = задание(app, job_id).heartbeat_at

    воркер(app).сердцебиение(job_id)
    assert задание(app, job_id).heartbeat_at == было


# ── уборка ───────────────────────────────────────────────────────────────────

def test_уборка_убирает_и_задания_и_корзину(app, клиент, хозяин, settings):
    """Обе уборки вместе и в одном месте: воркер — единственный процесс службы,
    который работает по времени, а не по запросу («раз в час»)."""
    проект = создать_проект(клиент, личное_id(клиент), шаблон=docx_байты())
    клиент.delete(f"/api/projects/{проект['id']}")
    старое = поставить(клиент)

    from api.projects import Project

    with app.state.db.session_scope() as s:
        s.get(Project, проект["id"]).purge_after = (
            now() - datetime.timedelta(days=1))
        строка = s.get(Job, старое)
        строка.status = DONE
        строка.last_seen_at = now() - datetime.timedelta(
            days=settings.jobs_retention_days + 1)

    убрано = воркер(app).уборка()
    assert убрано["jobs"] == [старое]
    assert убрано["projects"] == [проект["id"]]


def test_уборка_сносит_забытые_байты_и_щадит_ждущее_задание(app, клиент, хозяин,
                                                            settings):
    """Уборщик `incoming/`. Байты без живого задания и старше срока — вон.

    Забытый сырой файл заводится законно: загрузка приняла байты, а постановка
    задания отказала (лимит, корзина) и сессия откатилась. Видимым он при этом
    не становится — в описи материалов его нет, — а квоту владельцу считает.

    Второй файл в том же каталоге проверяет обратное: за ним стоит ждущее
    задание `parse`, и снести его значило бы устроить `parse_failed` работе,
    которая ещё не начиналась.
    """
    import os                                                # noqa: PLC0415

    from api.jobs.registry import PARSE                      # noqa: PLC0415
    from api.jobs.service import enqueue                     # noqa: PLC0415
    from api.materials import service as материалы           # noqa: PLC0415
    from api.projects.service import project_dir             # noqa: PLC0415

    проект = создать_проект(клиент, личное_id(клиент), шаблон=docx_байты())
    забытый = "a" * 16
    ждущий = "b" * 16
    with app.state.db.session_scope() as s:
        каталог = project_dir(s, app.state.settings, проект["id"])
        материалы.положить_сырой(каталог, забытый, b"raw")
        материалы.положить_сырой(каталог, ждущий, b"raw")
        enqueue(s, хозяин, PARSE, {"pending": ждущий, "name": "b.txt"},
                project_id=проект["id"])

    # Свежие байты не трогаются: между приёмом и постановкой задания есть щель,
    # и уборка, работающая по свежему файлу, отбирала бы работу у самой себя.
    assert воркер(app).уборка()["incoming"] == []

    давно = time.time() - settings.job_timeout_s - 60
    for ключ in (забытый, ждущий):
        путь = os.path.join(материалы.каталог_входящих(каталог), ключ)
        os.utime(путь, (давно, давно))

    убрано = воркер(app).уборка()["incoming"]
    assert убрано == [f"{проект['id']}/{забытый}"]
    assert материалы.сырой(каталог, забытый) is None
    assert материалы.сырой(каталог, ждущий) is not None


# ── мягкая остановка ─────────────────────────────────────────────────────────

def test_остановка_прекращает_цикл(app, клиент, хозяин):
    """`SIGTERM` — это «доделай и не бери новых», а не «умри». Здесь тот же
    флаг, что ставит обработчик сигнала: цикл обязан выйти, а не крутиться."""
    w = воркер(app, worker_poll_s=0.05)
    поток = threading.Thread(target=w.run_forever)
    поток.start()
    try:
        time.sleep(0.2)
        assert not w.stopping
        w.stop()
        поток.join(timeout=20)
    finally:
        if поток.is_alive():                                 # pragma: no cover
            w.stop()
            поток.join(timeout=20)
    assert not поток.is_alive(), "воркер не остановился по просьбе"


def test_цикл_доводит_задание_до_конца(app, клиент, хозяин):
    """Живой цикл, а не `run_once`: задание, поставленное в работающую очередь,
    доходит до `done` само.

    Единственный тест, где воркер крутится по-настоящему, — и потому единственный
    с ожиданием по времени. Ждём мало: проба ничего не делает.
    """
    job_id = поставить(клиент, payload={"echo": "цикл"})
    w = воркер(app, worker_poll_s=0.05, job_slots=1)
    поток = threading.Thread(target=w.run_forever)
    поток.start()
    try:
        крайний = time.monotonic() + 60
        while time.monotonic() < крайний:
            if задание(app, job_id).status == DONE:
                break
            time.sleep(0.1)
    finally:
        w.stop()
        поток.join(timeout=60)
    строка = задание(app, job_id)
    assert строка.status == DONE, строка.error
    assert строка.result["echo"] == "цикл"


# ── настоящий подпроцесс ─────────────────────────────────────────────────────

def test_подпроцесс_делает_задание_по_настоящему(app, клиент, хозяин):
    """Работа уезжает в другой процесс и возвращается оттуда.

    Медленно (подпроцесс импортирует службу заново), поэтому такой тест один на
    обычный ход. Всё остальное гоняется `inline` — см. докстроку модуля.
    """
    job_id = поставить(клиент, payload={"echo": "из подпроцесса", "steps": 2,
                                        "charge": 7})
    assert воркер(app).run_once() == job_id

    строка = задание(app, job_id)
    assert строка.status == DONE, строка.error
    assert строка.result == {"echo": "из подпроцесса", "steps": 2}
    assert строка.spent_units == 7
    # События писал ребёнок своим движком — значит, они доехали до базы.
    assert "text" in событий_видов(app, job_id)


def test_таймаут_даёт_failed_и_не_оставляет_половины(app, клиент, хозяин):
    """Убитый по таймауту ребёнок не может досказать состояние — и не должен.

    Это и есть довод в пользу того, что `queued → running → …` пишет только
    родитель: иначе задание осталось бы `running` навсегда либо `done` при
    недоделанной работе. Проверяется поэтому не только код беды, но и то, что
    строка закрыта целиком: конец проставлен, сердцебиения нет, результата нет.
    """
    job_id = поставить(клиент, payload={"sleep": 5})
    assert воркер(app, job_timeout_s=1).run_once() == job_id

    строка = задание(app, job_id)
    assert строка.status == FAILED
    assert строка.error["code"] == TIMEOUT
    assert строка.result is None
    assert строка.finished_at is not None
    assert строка.heartbeat_at is None
    assert строка.status != RUNNING


def test_окружение_подпроцесса_без_секретов():
    """Список закрыт: всё, чего в нём нет, до обработчика не доходит.

    Тот же список, что у разбора материалов (`api.subproc`), а не второй такой
    же: копия, где забыли вычистить окружение, работает ровно так же, как
    правильная, — до того дня, когда чужой код прочитает `KORITSU_SECRET`.
    """
    чистое = окружение()
    assert "KORITSU_SECRET" not in чистое
    assert not [имя for имя in чистое if имя.startswith("KORITSU_")]


def test_виду_без_нужды_секрет_не_уезжает(app, клиент, хозяин):
    """`parse` читает присланный человеком файл чужим разборщиком: секрет,
    которым расшифровываются ключи всех остальных, рядом с ним лежать не
    должен."""
    w = воркер(app)
    спец = w._спец("job-1", "parse")
    assert спец["настройки"]["secret"] == СЕКРЕТ_ЗАГЛУШКА
    assert спец["настройки"]["secret"] != app.state.settings.secret
    assert спец["ключи_окружения"] == {}


def test_виду_с_нуждой_секрет_и_общие_ключи_уезжают_каналом(app, monkeypatch):
    """`needs_secret=True` — и секрет, и общие ключи поставщиков приходят JSON
    на stdin, а не переменной окружения: окружение наследуют внуки (tesseract,
    LibreOffice), канал не наследует никто."""
    monkeypatch.setenv("KORITSU_PROVIDER_KEY_DEEPSEEK", "общий-ключ-владельца")
    # Реестр чистится ДО подмены: настоящий обработчик `fill_tag` уже
    # зарегистрирован, а `register` на занятый вид — беда настройки, а не
    # «последний побеждает». Проверяется здесь не он, а `_спец`.
    registry._забыть_всё()
    registry.register("fill_tag", needs_secret=True)(lambda ctx: {})
    try:
        спец = воркер(app)._спец("job-1", "fill_tag")
        assert спец["настройки"]["secret"] == app.state.settings.secret
        assert спец["ключи_окружения"] == {
            "KORITSU_PROVIDER_KEY_DEEPSEEK": "общий-ключ-владельца"}
        # И всё же не окружением: в нём этих переменных нет.
        assert "KORITSU_PROVIDER_KEY_DEEPSEEK" not in окружение()
    finally:
        registry._забыть_всё()
        registry.load_handlers()


# ── постановка из кода ───────────────────────────────────────────────────────

def test_задание_ставится_из_кода_одной_строкой(app, клиент, хозяин):
    """Форма для соседей: загрузка материала и кнопка «собрать отчёт» ставят
    задание не через HTTP, а этой функцией."""
    with app.state.db.session_scope() as s:
        задача = enqueue(s, хозяин, "probe", {"echo": "из кода"})
        job_id = задача.id
    assert задание(app, job_id).status == QUEUED

    воркер(app).run_once(inline=True)
    assert задание(app, job_id).result == {"echo": "из кода", "steps": 0}
