"""
worker — процесс, который берёт задания из таблицы и делает их.

Отдельный процесс (`python -m api worker`, второй контейнер в compose,
решение владельца §11), а не поток внутри веб-сервера. Довод не про
производительность: прогон модели длится минуты, и поток, занятый им внутри
uvicorn, — это воркер, который нельзя перезапустить, не уронив сайт. Разделив
их, мы получаем ещё и правду про нагрузку: слоты считает воркер, и «очередь
встала» перестаёт выглядеть как «сайт тормозит».

    Один шаг воркера
    ----------------

`run_once()` — полный шаг и единственное место, где что-то происходит:

1. поднять потерянные (`running` без сердцебиения дольше `job_timeout_s`);
2. захватить одно задание — **атомарно**, одним `UPDATE`, и тем же запросом
   списать цену его вида (§12, `runs/limits`);
3. исполнить его: подпроцесс с лимитами (или в этом же процессе, `inline=True`,
   ради тестов);
4. закрыть: `done`, `failed` или `cancelled` — и событие в поток.

`run_forever()` — `job_slots` потоков, каждый крутит `run_once`, плюс хозяйство
(уборка раз в час). Потоки, а не процессы: работа-то всё равно в подпроцессе, а
поток здесь только ждёт его и раз в несколько секунд пишет сердцебиение.

    Почему захват — один `UPDATE`, а не «прочитал и записал»
    -------------------------------------------------------

Два воркера (или два потока одного) читают очередь одновременно и видят одно и
то же ждущее задание. Прочитавший первым не мешает второму: между чтением и
записью проходит время, и оба записывают «беру». Задание делается дважды —
дважды тратятся деньги на модель и дважды переписывается тег.

Поэтому захват — один запрос, и условия слотов стоят **внутри** него
подзапросами:

    UPDATE jobs SET status='running', worker_id=…
     WHERE id=? AND status='queued'
       AND (SELECT count(*) FROM jobs WHERE status='running') < job_slots
       AND (SELECT count(*) FROM jobs WHERE status='running'
                                        AND user_id=?) < jobs_per_user

Пока запрос идёт, база держит замок на запись, значит подсчёт работающих и сама
запись случаются в один момент, а не «сначала посчитали, потом кто-то взял, а
потом записали мы». `rowcount == 1` — взяли; `0` — опоздали или слот занят.
Считать слоты в Python нельзя ровно по этой причине: два процесса насчитали бы
по одному свободному слоту каждый.

    Отмена: флаг, потом сила
    ------------------------

§11: «отмена — закрытые теги остаются». Значит, сначала просьба: обработчик
видит `ctx.cancelled()` между шагами и останавливается сам, дописав сделанное.
Воркер лишь смотрит на флаг, пока ждёт подпроцесс, и добивает его, если тот не
послушался за `ГРАЦИЯ_ОТМЕНЫ_С`. Убивать сразу значило бы отменить обещание про
закрытые теги: незакрытая запись на диске — это как раз то, что обработчик
дописывает в последнюю секунду.

    Потерянный воркер
    -----------------

Воркер, которого не стало (`kill -9`, кончилась память машины, выдернули
питание), оставляет задание в `running` навсегда. Отличить его от работающего
можно одним: сердцебиением. Взявший задание пишет `heartbeat_at` раз в
`СЕРДЦЕБИЕНИЕ_С`, и `running` без сердцебиения дольше `job_timeout_s` — это
задание без воркера.

Такое задание поднимается **один раз** (`attempt` 0 → 1, обратно в `queued`);
второй раз — `failed` с кодом `worker_lost`. Это не ретрай упавшего обработчика
(§7 обещает «повтор упавшего только вручную»): обработчик, который упал, сказал
об этом сам, и его беда закрывает задание сразу. Поднимается только то, о чём
не сказал никто.

    Мягкая остановка
    ----------------

`SIGTERM` (то, что шлёт `docker compose stop`) — это «доделай и не бери
новых», а не «умри». Задание, брошенное посередине, стоило человеку денег у
поставщика и всё равно вернулось бы через сердцебиение — то есть выкат службы
означал бы повтор половины очереди. Ждать при этом можно долго: время даёт
`docker stop --timeout`, и в compose его ставят по `job_timeout_s`.
"""
from __future__ import annotations

import dataclasses
import datetime
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import uuid

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ..db import Db, now
from ..log import беды, журнал
from ..settings import Settings
from ..subproc import ПРОЛОГ, каталог_пакетов, окружение
from . import registry
from .child import BAD_RESULT, HANDLER_FAILED, NO_HANDLER, позвать
from .context import JobContext
from .models import (CANCELLED, DONE, FAILED, Job, JobEvent, QUEUED, RUNNING)
from .service import убрать_старые

# Коды бед, которые называет родитель. Ребёнок про них сказать не может: о
# первом ему уже некогда, о втором — некому.
TIMEOUT = "timeout"
WORKER_LOST = "worker_lost"
HANDLER_CRASHED = "handler_crashed"

# Как часто воркер пишет сердцебиение работающего задания. Много меньше
# `job_timeout_s`, по которому задание признаётся потерянным: иначе живое
# задание успевало бы выглядеть мёртвым между двумя ударами.
СЕРДЦЕБИЕНИЕ_С = 5.0

# Шаг ожидания подпроцесса. Он же — точность, с которой замечаются и таймаут, и
# отмена. Пятая доля секунды: дешёвый системный вызов, зато отмена доходит
# быстрее, чем человек успевает перечитать страницу.
ШАГ_ОЖИДАНИЯ_С = 0.2

# Как часто, ожидая подпроцесс, спрашивать «не отменили ли». Реже, чем шаг
# ожидания: это запрос в базу, и делать его пять раз в секунду на каждое
# работающее задание незачем.
ПРОВЕРКА_ОТМЕНЫ_С = 1.0

# Сколько ждать после просьбы остановиться, прежде чем убить процесс. Пять
# секунд — время дописать закрытый тег на диск, но не время доделать шаг.
ГРАЦИЯ_ОТМЕНЫ_С = 5.0

# Раз в час — уборка (§11: «уборка заданий старше 90 дней и корзины тем же
# воркером раз в час»).
УБОРКА_С = 3600.0

# Сколько ждущих заданий смотреть за один заход. Больше одного, потому что
# первое может не пройти по слоту пользователя, а второе, чужое, — пройти.
# Двадцати хватает: очередь, где двадцать первых заданий принадлежат одному
# человеку, всё равно упирается в его слот, и заглядывать глубже незачем.
КАНДИДАТОВ = 20

# Секрет, который получают виды заданий без `needs_secret`. Длиннее 32 байт (без
# этого `Settings` не соберётся) и заведомо ничей: расшифровать им чужой ключ
# нельзя, и это ровно то, что нужно, — `parse` не должен мочь.
СЕКРЕТ_ЗАГЛУШКА = "no-secret-for-this-job-kind-" + "0" * 40

# Тело подпроцесса. Дописывается к `subproc.ПРОЛОГ`, где уже разобрано
# `задание`, поставлен `RLIMIT_AS` (до первого импорта службы — иначе самая
# дорогая часть работы осталась бы без потолка), добавлен путь к пакетам и
# заведена функция `ответ`.
#
# Запуск здесь свой, а не `subproc.выполнить`, и это единственное место, где
# общий механизм не подошёл: тот ждёт подпроцесс одним `subprocess.run` с
# таймаутом, а воркеру, пока идёт работа, надо ещё писать сердцебиение и
# спрашивать «не отменили ли». Всё остальное — пролог, чистое окружение, путь к
# пакетам — берётся оттуда, чтобы список того, что можно передать чужому коду,
# остался в проекте один.
ТЕЛО = r"""
from api.jobs.child import выполнить

ответ(выполнить(задание))
"""


def новое_имя() -> str:
    """Имя воркера: хост, номер процесса и случайный хвост.

    Хост и pid — чтобы по строке `running` можно было пойти и посмотреть, что за
    процесс; случайный хвост — потому что pid переиспользуются, и без него
    перезапущенный воркер назвался бы так же, как тот, чьи задания он как раз
    обязан признать потерянными.
    """
    хост = socket.gethostname()[:24]
    return f"{хост}:{os.getpid()}:{uuid.uuid4().hex[:8]}"


class Worker:
    """Один процесс-исполнитель. Имя у него одно и на всю жизнь процесса."""

    def __init__(self, settings: Settings, *, db: Db | None = None,
                 worker_id: str | None = None):
        self.settings = settings
        # Свой движок, если не дали чужой. Чужой берут тесты — тот же, что у
        # приложения, чтобы видеть строки без второго соединения к файлу.
        self.db = db or Db(settings)
        self._свой_движок = db is None
        self.worker_id = worker_id or новое_имя()
        self._стоп = threading.Event()
        self._убрано = 0.0

    # ── шаг ─────────────────────────────────────────────────────────────────

    def run_once(self, *, inline: bool = False) -> str | None:
        """Один полный шаг: поднять потерянные, взять одно задание, сделать его.

        → идентификатор сделанного задания или `None`, если брать было нечего.

        `inline=True` — исполнить обработчик **в этом же процессе**, без
        подпроцесса, лимитов и таймаута. Только для тестов: подпроцесс на
        каждое задание в наборе из полусотни тестов стоит минуты, а проверять
        через него надо не всё, а то, ради чего он заведён (таймаут, убийство,
        вычищенное окружение). Живой воркер `inline` не включает никогда.
        """
        registry.load_handlers()
        self.поднять_потерянные()
        взято = self.захватить()
        if взято is None:
            return None
        job_id, kind = взято
        журнал.info("worker=%s взял задание %s (%s)", self.worker_id, job_id,
                    kind)
        ответ = (self._в_процессе(job_id, kind) if inline
                 else self._в_подпроцессе(job_id, kind))
        self._закрыть(job_id, ответ)
        return job_id

    # ── захват ──────────────────────────────────────────────────────────────

    def захватить(self) -> tuple[str, str] | None:
        """Взять одно ждущее задание. → `(id, kind)` или `None`.

        Одно, а не сколько влезет: поток, взявший два, исполнял бы их по
        очереди, занимая слот вторым, пока делает первый. Слот — это работа,
        которая идёт, а не работа, которую кто-то себе отложил.
        """
        with self.db.session_scope() as s:
            кандидаты = list(s.execute(
                select(Job.id, Job.user_id, Job.kind)
                .where(Job.status == QUEUED)
                .order_by(Job.created_at, Job.id)
                .limit(КАНДИДАТОВ)))
            for job_id, user_id, kind in кандидаты:
                if self._взять(s, job_id, user_id, str(kind)):
                    return str(job_id), str(kind)
        return None

    def _взять(self, s: Session, job_id: str, user_id: str, kind: str) -> bool:
        """Тот самый единственный `UPDATE`. → взяли или нет.

        Подзапросы считают работающих внутри этого же запроса — см. докстроку
        модуля о том, почему в Python это считать нельзя.

        **Здесь же списывается цена вида** (§12, `runs/limits`): захват — это
        момент, когда человек занял слот, подпроцесс и память, и платит он
        именно за это, а не за токены поставщика. Тем же запросом, а не второй
        записью следом: перезапуск между двумя записями оставил бы работающее
        задание неоплаченным. Присваиванием, а не приращением, — потерянное
        задание захватывается второй раз, и вторая попытка не вина человека.
        """
        # Ввозом на месте, а не сверху модуля: `runs.limits` берёт сумму
        # расхода у `jobs.service`, то есть у нашего же пакета, и импорт
        # сверху замкнул бы круг на первом же `import api.jobs`.
        from ..runs.limits import цена                       # noqa: PLC0415

        t = Job.__table__
        всего = t.alias("занято_всего")
        его = t.alias("занято_им")
        работающих = (select(func.count()).select_from(всего)
                      .where(всего.c.status == RUNNING).correlate(None)
                      .scalar_subquery())
        его_работающих = (select(func.count()).select_from(его)
                          .where(его.c.status == RUNNING,
                                 его.c.user_id == user_id).correlate(None)
                          .scalar_subquery())
        момент = now()
        итог = s.execute(
            update(t)
            .where(t.c.id == job_id, t.c.status == QUEUED,
                   работающих < self.settings.job_slots,
                   его_работающих < self.settings.jobs_per_user)
            .values(status=RUNNING, worker_id=self.worker_id,
                    started_at=момент, heartbeat_at=момент,
                    updated_at=момент, spent_units=цена(self.settings, kind)))
        return итог.rowcount == 1

    # ── исполнение ──────────────────────────────────────────────────────────

    def _в_процессе(self, job_id: str, kind: str) -> dict:
        """Обработчик здесь же, без подпроцесса. Только `inline` (см. `run_once`).

        Ни лимита памяти, ни таймаута, ни вычищенного окружения тут нет и быть
        не может: всё трое — свойства отдельного процесса. Поэтому режим и
        назван тестовым, а не «быстрым».
        """
        ctx = JobContext(self.db, self.settings, job_id)
        return позвать(ctx, registry.handler_for(kind))

    def _в_подпроцессе(self, job_id: str, kind: str) -> dict:
        """Обработчик в отдельном процессе с лимитами. Обычный путь.

        Потоки подпроцесса — временные файлы, а не трубы, и это не мелочь:
        труба, которую никто не читает, наполняется на 64 КБ и останавливает
        процесс насмерть. Трассировка упавшего обработчика бывает длиннее.
        """
        спец = self._спец(job_id, kind)
        with (tempfile.TemporaryFile() as вход,
              tempfile.TemporaryFile() as выход,
              tempfile.TemporaryFile() as ошибки):
            вход.write(json.dumps(спец).encode("utf-8"))
            вход.seek(0)
            try:
                процесс = subprocess.Popen(
                    [sys.executable, "-c", ПРОЛОГ + ТЕЛО], stdin=вход, stdout=выход,
                    stderr=ошибки, env=окружение(),
                    # Своя сессия процессов: обработчик зовёт внешние команды
                    # (LibreOffice, tesseract), и убивать надо всю ветку, а не
                    # одного питона, оставив её сиротой на томе.
                    start_new_session=True)
            except OSError as беда:
                беды.exception("задание %s: подпроцесс не запустился: %s",
                               job_id, беда)
                return {"ok": False, "code": HANDLER_CRASHED,
                        "message": "The job could not be started"}

            исход = self._ждать(процесс, job_id)

            выход.seek(0)
            сырое = выход.read().decode("utf-8", "replace").strip()
            ошибки.seek(0)
            # Хвост, а не всё: трассировка чужой библиотеки бывает длиннее
            # самого задания, а в журнал нужна причина, а не роман.
            хвост = ошибки.read().decode("utf-8", "replace").strip()[-4000:]

        if хвост:
            беды.warning("задание %s: подпроцесс сказал в stderr: %s",
                         job_id, хвост)

        if исход == "timeout":
            return {"ok": False, "code": TIMEOUT,
                    "message": "The job did not finish in time"}
        if исход == "cancelled":
            return {"ok": False, "code": CANCELLED, "message": "Cancelled",
                    "отменён_силой": True}

        if not сырое:
            # Ни строки на stdout — процесса не стало без единого слова:
            # кончилась память (`RLIMIT_AS`), убил кто-то снаружи.
            беды.error("задание %s: подпроцесс кончился кодом %s и молча",
                       job_id, процесс.returncode)
            return {"ok": False, "code": HANDLER_CRASHED,
                    "message": "The job stopped without finishing"}
        try:
            ответ = json.loads(сырое)
        except ValueError:
            беды.error("задание %s: подпроцесс ответил не словарём", job_id)
            return {"ok": False, "code": BAD_RESULT,
                    "message": "The job handler returned no result"}
        if not isinstance(ответ, dict):
            return {"ok": False, "code": BAD_RESULT,
                    "message": "The job handler returned no result"}
        return ответ

    def _спец(self, job_id: str, kind: str) -> dict:
        """Что уезжает в подпроцесс каналом (JSON на stdin), а не окружением.

        Секрет и общие ключи поставщиков кладутся сюда **только** видам,
        объявившим `needs_secret=True` (`registry`, решение главной сессии,
        вариант C). Остальные получают настройки с секретом-заглушкой: `parse`
        читает присланный человеком файл чужим разборщиком, и то, чем
        расшифровываются ключи всех остальных, рядом с ним лежать не должно.
        """
        from ..keys.service import ОБЩИЙ_ПРЕФИКС            # noqa: PLC0415

        поля = dataclasses.asdict(self.settings)
        секрет = registry.needs_secret(kind)
        if not секрет:
            поля["secret"] = СЕКРЕТ_ЗАГЛУШКА
        ключи = ({имя: значение for имя, значение in os.environ.items()
                  if имя.startswith(ОБЩИЙ_ПРЕФИКС)} if секрет else {})
        return {"job_id": job_id, "настройки": поля, "ключи_окружения": ключи,
                "пакеты": каталог_пакетов(),
                "память": self.settings.job_memory_bytes}

    def _ждать(self, процесс: subprocess.Popen, job_id: str) -> str:
        """Дождаться подпроцесс. → `ok`, `timeout` или `cancelled`.

        Заодно это единственное место, где пишется сердцебиение: пока идёт
        работа, воркер занят ровно здесь, и писать его откуда-то ещё значило бы
        завести второй ответ на вопрос «жив ли тот, кто взял задание».
        """
        крайний = time.monotonic() + float(self.settings.job_timeout_s)
        пульс = time.monotonic()
        спрошено = 0.0
        попросили = None
        while True:
            try:
                процесс.wait(timeout=ШАГ_ОЖИДАНИЯ_С)
                return "ok"
            except subprocess.TimeoutExpired:
                pass

            сейчас = time.monotonic()
            if сейчас - пульс >= СЕРДЦЕБИЕНИЕ_С:
                пульс = сейчас
                self.сердцебиение(job_id)

            if сейчас >= крайний:
                беды.warning("задание %s: не уложилось в %s с, прерываю",
                             job_id, self.settings.job_timeout_s)
                self._убить(процесс)
                return "timeout"

            if сейчас - спрошено >= ПРОВЕРКА_ОТМЕНЫ_С:
                спрошено = сейчас
                if self._отменяют(job_id):
                    if попросили is None:
                        попросили = сейчас
                    elif сейчас - попросили >= ГРАЦИЯ_ОТМЕНЫ_С:
                        журнал.info("задание %s: не остановилось само, добиваю",
                                    job_id)
                        self._убить(процесс)
                        return "cancelled"

    @staticmethod
    def _убить(процесс: subprocess.Popen) -> None:
        """Снять подпроцесс вместе с его детьми.

        Сначала группа (`start_new_session=True` завела её), потом сам процесс:
        обработчик, позвавший LibreOffice, оставил бы его работать на томе, а
        LibreOffice без родителя не заканчивается сам.
        """
        try:
            os.killpg(os.getpgid(процесс.pid), signal.SIGKILL)
        except (OSError, AttributeError):
            pass
        try:
            процесс.kill()
        except OSError:
            pass
        try:
            процесс.wait(timeout=10)
        except subprocess.TimeoutExpired:                    # pragma: no cover
            pass

    # ── состояние задания ───────────────────────────────────────────────────

    def сердцебиение(self, job_id: str) -> None:
        """«Я ещё жив и это задание моё». По нему считается потерянность."""
        with self.db.session_scope() as s:
            s.execute(update(Job.__table__)
                      .where(Job.__table__.c.id == job_id,
                             Job.__table__.c.worker_id == self.worker_id)
                      .values(heartbeat_at=now()))

    def _отменяют(self, job_id: str) -> bool:
        with self.db.session_scope() as s:
            return bool(s.scalar(select(Job.cancel_requested)
                                 .where(Job.id == job_id)))

    def _закрыть(self, job_id: str, ответ: dict) -> None:
        """Поставить состояние по ответу подпроцесса. Единственное такое место.

        Порядок разбора важен и такой: сначала отмена, потом успех, потом беда.
        Задание, которое доделалось и было отменено в ту же секунду, — это
        `cancelled` с сохранённым результатом: человек нажал «отменить», и
        показывать ему «готово» значило бы соврать про то, что он сделал.
        """
        with self.db.session_scope() as s:
            задание = s.get(Job, job_id)
            if задание is None:                              # убрали, пока шли
                return
            задание.finished_at = now()
            задание.heartbeat_at = None
            if ответ.get("отменён_силой") or (ответ.get("ok")
                                              and ответ.get("cancelled")):
                задание.status = CANCELLED
                if ответ.get("ok"):
                    задание.result = ответ.get("result")
            elif ответ.get("ok"):
                задание.status = DONE
                задание.result = ответ.get("result")
            else:
                задание.status = FAILED
                # Ровно две строки наружу, и обе без подробностей: код для
                # интерфейса, текст для человека. Трассировка осталась в
                # журнале (`беды`), где ей и место.
                задание.error = {
                    "code": str(ответ.get("code") or HANDLER_FAILED),
                    "message": str(ответ.get("message")
                                   or "The job handler failed")}
            _событие(s, job_id, задание.status,
                     {"code": (задание.error or {}).get("code")}
                     if задание.status == FAILED else {})
            # Колокольчик (агент B, §11: писем нет). В той же транзакции, что и
            # терминальный статус: перезапуск между двумя коммитами оставил бы
            # готовое задание без строки в списке уведомлений — то есть ровно
            # тот случай, ради которого таблица и заведена.
            from ..notifications.service import при_завершении  # noqa: PLC0415

            при_завершении(s, задание)
        журнал.info("worker=%s задание %s → %s", self.worker_id, job_id,
                    ответ.get("code") or ("done" if ответ.get("ok") else "?"))

    # ── потерянные ──────────────────────────────────────────────────────────

    def поднять_потерянные(self) -> list[str]:
        """Вернуть в очередь то, чей воркер перестал подавать признаки жизни.

        → идентификаторы тронутых заданий. Подъём один; второй раз — `failed`
        с `worker_lost` (см. докстроку модуля).
        """
        порог = now() - datetime.timedelta(seconds=self.settings.job_timeout_s)
        тронуто: list[str] = []
        with self.db.session_scope() as s:
            зависшие = list(s.scalars(select(Job).where(
                Job.status == RUNNING,
                Job.heartbeat_at.is_not(None), Job.heartbeat_at < порог)))
            # Отдельным запросом — те, кого взяли и не ударили ни разу: SQLite
            # сравнивает NULL ни с чем, и в условии выше они не нашлись бы.
            зависшие += list(s.scalars(select(Job).where(
                Job.status == RUNNING, Job.heartbeat_at.is_(None),
                Job.started_at.is_not(None), Job.started_at < порог)))
            for задание in зависшие:
                задание.attempt = int(задание.attempt or 0) + 1
                задание.heartbeat_at = None
                if задание.attempt > 1:
                    задание.status = FAILED
                    задание.finished_at = now()
                    задание.error = {
                        "code": WORKER_LOST,
                        "message": "The worker running this job disappeared"}
                    _событие(s, задание.id, FAILED, {"code": WORKER_LOST})
                    # Колокольчик — и здесь тоже (решение владельца §12).
                    # Задание, потерянное вместе с воркером, кончилось так же
                    # окончательно, как упавшее, и человек, ждущий отчёта, обязан
                    # узнать об этом от службы, а не по тишине. В той же
                    # транзакции, что и статус, — довод тот же, что у `_закрыть`.
                    from ..notifications.service import (            # noqa: PLC0415
                        при_завершении)

                    при_завершении(s, задание)
                    беды.error("задание %s потеряно дважды (worker=%s) → failed",
                               задание.id, задание.worker_id)
                else:
                    задание.status = QUEUED
                    задание.worker_id = None
                    задание.started_at = None
                    беды.warning("задание %s потеряно (worker=%s) → в очередь",
                                 задание.id, задание.worker_id)
                тронуто.append(задание.id)
        return тронуто

    # ── хозяйство ───────────────────────────────────────────────────────────

    def уборка(self) -> dict:
        """Убрать старые задания, просроченную корзину и забытые байты.

        Раз в час (§11), и все три уборки вместе, а не в трёх местах: воркер —
        единственный процесс службы, который работает по времени, а не по
        запросу, и вторая уборка, повешенная на cron рядом, разошлась бы с этой
        сроками.

        Третья — сырые байты в `incoming/`, за которыми не пришло ни одно живое
        задание `parse` (решение владельца §12). Срок им — `job_timeout_s`, тот
        же, по которому задание признаётся потерянным: раньше него файл может
        принадлежать разбору, который вот-вот начнётся, а позже него не
        принадлежит уже никому. Подробности — `materials.service.убрать_забытые`.
        """
        from ..materials.service import убрать_забытые       # noqa: PLC0415
        from ..projects.service import purge_expired         # noqa: PLC0415

        with self.db.session_scope() as s:
            задания = убрать_старые(s, self.settings)
            проекты = purge_expired(s, self.settings)
            байты = убрать_забытые(s, self.settings,
                                   старше_с=self.settings.job_timeout_s)
        if задания or проекты or байты:
            журнал.info("worker=%s уборка: заданий %s, проектов %s, "
                        "принятых файлов %s", self.worker_id, len(задания),
                        len(проекты), len(байты))
        return {"jobs": задания, "projects": проекты, "incoming": байты}

    def _хозяйство(self) -> None:
        """Что делается по времени, а не по заданию."""
        self.поднять_потерянные()
        сейчас = time.monotonic()
        if сейчас - self._убрано >= УБОРКА_С:
            self._убрано = сейчас
            try:
                self.уборка()
            except Exception:                                # noqa: BLE001
                # Уборка, упавшая на одном каталоге, не должна останавливать
                # очередь: следующий час попробует снова.
                беды.exception("worker=%s уборка не удалась", self.worker_id)

    # ── цикл ────────────────────────────────────────────────────────────────

    def stop(self) -> None:
        """Попросить остановиться: доделать текущее и не брать новых."""
        self._стоп.set()

    @property
    def stopping(self) -> bool:
        return self._стоп.is_set()

    def run_forever(self) -> int:
        """Крутиться, пока не попросят остановиться. → код выхода.

        `job_slots` потоков-исполнителей плюс этот, хозяйственный. Первая
        уборка — сразу на старте, а не через час: перезапускаемый раз в час
        воркер иначе не убирал бы никогда.
        """
        registry.load_handlers()
        self._слушать_сигналы()
        журнал.info("worker=%s поднят: слотов %s, на человека %s, опрос %.1f с",
                    self.worker_id, self.settings.job_slots,
                    self.settings.jobs_per_user, self.settings.worker_poll_s)

        потоки = [threading.Thread(target=self._цикл, name=f"koritsu-job-{n}")
                  for n in range(self.settings.job_slots)]
        for поток in потоки:
            поток.start()
        try:
            while not self._стоп.is_set():
                self._хозяйство()
                self._стоп.wait(self.settings.worker_poll_s)
        finally:
            self._стоп.set()
            for поток in потоки:
                поток.join()
            if self._свой_движок:
                self.db.dispose()
        журнал.info("worker=%s остановлен", self.worker_id)
        return 0

    def _цикл(self) -> None:
        """Один слот: брать и делать, пока не попросят остановиться."""
        while not self._стоп.is_set():
            try:
                взято = self.run_once()
            except Exception:                                # noqa: BLE001
                # Беда самого воркера (база не отвечает, диск полон) не должна
                # убивать слот: очередь без слота молча перестаёт работать.
                беды.exception("worker=%s шаг не удался", self.worker_id)
                взято = None
            if взято is None:
                self._стоп.wait(self.settings.worker_poll_s)

    def _слушать_сигналы(self) -> None:
        """`SIGTERM` и `SIGINT` — «доделай и не бери новых».

        Ставится только в главном потоке процесса: `signal.signal` из другого
        потока падает, а воркер, поднятый как библиотека внутри чужого процесса
        (тесты), чужие обработчики сигналов трогать не должен.
        """
        if threading.current_thread() is not threading.main_thread():
            return
        def остановиться(номер, кадр):                        # noqa: ANN001
            журнал.info("worker=%s сигнал %s: доделываю текущее",
                        self.worker_id, номер)
            self._стоп.set()

        for номер in (signal.SIGTERM, signal.SIGINT):
            try:
                signal.signal(номер, остановиться)
            except (ValueError, OSError):                     # pragma: no cover
                pass


# ── события родителя ─────────────────────────────────────────────────────────

def _событие(s: Session, job_id: str, вид: str, тело: dict) -> None:
    """Последнее событие задания — то, которым кончается поток.

    Пишет родитель, а не `JobContext`: подпроцесса к этому моменту уже нет, а
    клиент, читающий поток, обязан увидеть, чем всё кончилось, — иначе он
    останется ждать продолжения, которого не будет.
    """
    следующий = int(s.scalar(
        select(func.coalesce(func.max(JobEvent.seq), 0))
        .where(JobEvent.job_id == job_id)) or 0) + 1
    s.add(JobEvent(job_id=job_id, seq=следующий, kind=вид,
                   data={k: v for k, v in тело.items() if v is not None}))


__all__ = ["Worker", "новое_имя", "окружение", "каталог_пакетов",
           "TIMEOUT", "WORKER_LOST", "HANDLER_CRASHED", "HANDLER_FAILED",
           "NO_HANDLER", "СЕРДЦЕБИЕНИЕ_С", "ГРАЦИЯ_ОТМЕНЫ_С", "УБОРКА_С",
           "СЕКРЕТ_ЗАГЛУШКА", "ТЕЛО"]
