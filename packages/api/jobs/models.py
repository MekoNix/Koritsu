"""
models — две таблицы очереди: `jobs` (задания) и `job_events` (их события).

Очередь — таблица в базе. Не Redis и не очередь в памяти, и довод короткий:
она переживает перезапуск. Довод стоит развернуть, потому что он же объясняет
половину полей ниже: очередь в
памяти означает, что перезапуск воркера теряет всё, что в ней лежало, и человек,
нажавший «собрать отчёт» за минуту до выката, не узнаёт об этом никогда — ни
ошибки, ни результата, задание просто не существует. Таблица же переживает и
перезапуск, и падение: задание, брошенное умершим воркером, видно в базе как
`running` без сердцебиения, и его можно поднять (см. `worker.поднять_потерянные`).

**Что в этой таблице есть и чего в ней нет.** Есть — состояние задания и то, что
клиенту показать: чьё, к какому проекту, чем занято, сколько сделано, чем
кончилось. Нет — ни одного байта работы: ни текста модели, ни собранного DOCX,
ни разобранного материала. Всё это лежит на томе в каталоге проекта, а в
`result` попадает только то, чем это найти (идентификатор артефакта, ключ тега).
Правило то же, по которому значения тегов остались файлами: база держит
индекс, том держит содержимое. Иначе первый же отчёт на сорок страниц окажется
строкой в SQLite, а резервная копия базы — бесполезной без тома и наоборот.

    jobs         id, user_id, project_id, kind, status, payload, result, error,
                 progress, cancel_requested, created_at, started_at,
                 finished_at, last_seen_at, heartbeat_at, spent_units,
                 worker_id, attempt
    job_events   id, job_id, seq, kind, data, created_at

**Состояния и переходы.** Их пять, и переходы между ними закрыты:

    queued ──захват воркером──> running ──> done | failed | cancelled
      └──отмена до захвата──> cancelled

Обратных переходов нет ни одного, кроме единственного, ради которого заведён
`attempt`: `running` без сердцебиения дольше `job_timeout_s` возвращается в
`queued` (воркер умер, не доделав). Это не ретрай упавшего обработчика: повтор
упавшего — только вручную, и это правило здесь соблюдено: подъём
случается ровно тогда, когда обработчик ничего не сказал, потому что его вместе с
процессом не стало. Подъём один: после него `attempt` равен 1, и второй потерянный
воркер закрывает задание `failed` с кодом `worker_lost`. Без этого потолка задание,
роняющее воркер (а такое бывает — обработчик, съедающий память машины), поднималось
бы вечно и роняло бы очередь по кругу.

**`last_seen_at` — не «когда трогали строку», а «когда о задании спрашивали».**
Срок хранения — 90 дней с последнего обращения; потом удаляются и запись
задания, и её артефакты. Отсюда поле отдельное от `updated_at`: `updated_at`
двигает любая запись, включая сердцебиение воркера, и по нему срок хранения
считался бы от конца работы, а не от последнего интереса человека. Двигают его
двое: постановка и `GET` карточки (`service.карточка`).

**`payload`, `result`, `error`, `progress` — JSON, и без единого поля внутри.**
Форму `payload` знает обработчик своего вида, и только он: у `fill_tag` там ключ
тега и пресет модели, у `export` — что класть в архив. Расписать эти формы
колонками значило бы завести в таблице очереди знание про прогоны модели и про
архивы, то есть ровно то, от чего `api` отделён от `orchestrator`. Договор один
и он снаружи: `error` — это `{code, message}` (та же пара, что у `ApiError`),
`progress` — `{step, total, note}`.

**JSON-поля присваиваются целиком.** SQLAlchemy не следит за правкой словаря
внутри колонки `JSON` (`MutableDict` мы не включаем намеренно: он стоит
сравнения словаря на каждом сбросе). Поэтому `job.progress["step"] = 3` в базу
не попадёт, а `job.progress = {...}` попадёт. Все места записи в службе
присваивают целиком; это не стиль, это единственный работающий способ.
"""
from __future__ import annotations

import datetime

from sqlalchemy import (JSON, Boolean, DateTime, ForeignKey, Index, Integer,
                        String)
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base, Row, now
from ..ids import ID_LEN, new_id

# Длины строковых колонок. Числами в одном месте, а не по месту: `String(32)`,
# написанный дважды, однажды окажется написан как `String(16)`.
KIND_MAX = 32          # имя вида задания: `fill_tag`, `kadai_rework`
STATUS_MAX = 16        # самое длинное — `cancelled`
WORKER_MAX = 64        # `<хост>:<pid>:<8 hex>`, см. `worker.новое_имя`
EVENT_KIND_MAX = 32    # имя вида события: `text`, `tag_closed`, `done`

# Состояния. Список закрыт и лежит здесь, а не в сервисе: по нему строятся и
# проверка параметра `status` в маршруте списка, и захват воркером.
QUEUED = "queued"
RUNNING = "running"
DONE = "done"
FAILED = "failed"
CANCELLED = "cancelled"

STATUSES = (QUEUED, RUNNING, DONE, FAILED, CANCELLED)

# Состояния, из которых задание уже не выйдет. Ими же меряется срок хранения:
# 90 дней считаются только для законченных, `queued` не убирается никогда —
# задание, не дождавшееся воркера, обязано дождаться его и через сутки.
TERMINAL = (DONE, FAILED, CANCELLED)


class Job(Row):
    """Одно задание очереди.

    `id`, `created_at`, `updated_at` — от `Row` (uuid4 наружу, `ids.py`).
    """

    __tablename__ = "jobs"

    # Чьё задание. `CASCADE`: удалили аккаунт, значит и заданий
    # его нет. Без каскада после удаления человека в очереди остались бы строки
    # с `payload`, в котором лежит его работа, и владельца у них уже нет.
    user_id: Mapped[str] = mapped_column(
        String(ID_LEN), ForeignKey("users.id", ondelete="CASCADE"))

    # К какому проекту. Необязателен: вид задания сам говорит, нужен ли ему
    # проект (`registry.register(..., needs_project=False)`), и заводить
    # фиктивный проект ради задания без проекта было бы хуже, чем пустая ссылка.
    project_id: Mapped[str | None] = mapped_column(
        String(ID_LEN), ForeignKey("projects.id", ondelete="CASCADE"),
        default=None)

    # Вид задания. Строка, а не Enum базы: перечисление в схеме SQLite означает
    # `CHECK`-ограничение, а новый вид — пересборку таблицы. Список закрыт в
    # `registry.ВИДЫ`, и проверяется он при постановке (400 `unknown_job_kind`).
    kind: Mapped[str] = mapped_column(String(KIND_MAX))

    status: Mapped[str] = mapped_column(String(STATUS_MAX), default=QUEUED)

    # Что делать. Форму знает обработчик своего вида — см. докстроку модуля.
    payload: Mapped[dict] = mapped_column(JSON, default=dict)

    # Чем кончилось. `result` — при `done`, `error` — при `failed`, и оба сразу
    # не бывают: задание либо сделано, либо нет.
    result: Mapped[dict | None] = mapped_column(JSON, default=None)

    # `{code, message}` — та же пара, что у `ApiError`, и по той же причине:
    # интерфейс различает случаи по `code`, а `message` переписывается. Ни
    # трассировки, ни пути на томе тут не бывает никогда (`worker.беда_наружу`).
    error: Mapped[dict | None] = mapped_column(JSON, default=None)

    # `{step, total, note}`. Пишет обработчик через `ctx.progress(...)`.
    progress: Mapped[dict | None] = mapped_column(JSON, default=None)

    # Просьба остановиться. Флаг, а не убийство процесса: закрытые теги обязаны
    # остаться, а это возможно только если обработчик остановится сам —
    # между шагами, дописав то, что уже сделал.
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)

    started_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), default=None)
    finished_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), default=None)

    # Когда о задании последний раз спрашивали — см. докстроку модуля.
    last_seen_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=now)

    # Сердцебиение работающего воркера. `None` у всех, кого никто не брал.
    heartbeat_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), default=None)

    # Внутренние единицы, которыми человек платит за этот запуск: расход
    # наружу во внутренних единицах, за наши инструменты, а не за токены
    # поставщика. Пишет их воркер при захвате — цену вида задания
    # (`runs/limits.ЦЕНЫ`), — потому отменённое и упавшее посреди работы стоит
    # столько же, сколько доделанное: слот и подпроцесс оно заняло. Обработчик
    # может добавить сверху (`ctx.charge`), и сегодня это делает только проба
    # очереди.
    spent_units: Mapped[int] = mapped_column(Integer, default=0)

    # Кто взял. Нужен ровно для одного: понять, чьё сердцебиение пропало.
    worker_id: Mapped[str | None] = mapped_column(String(WORKER_MAX),
                                                  default=None)

    # Сколько раз задание поднимали после потерянного воркера. Не число
    # запусков: захват его не трогает — см. докстроку модуля.
    attempt: Mapped[int] = mapped_column(Integer, default=0)

    __table_args__ = (
        # Что спрашивает воркер: «самое старое из ждущих». Пара, а не два
        # индекса по одному: запрос один и он всегда такой.
        Index("ix_jobs_status_created", "status", "created_at"),
        # Что спрашивает человек: «мои задания, вот такие». Тот же довод.
        Index("ix_jobs_user_status", "user_id", "status"),
        # Что спрашивает страница проекта.
        Index("ix_jobs_project", "project_id"),
    )

    @property
    def terminal(self) -> bool:
        """Кончилось ли задание. Из терминального состояния выхода нет."""
        return self.status in TERMINAL


class JobEvent(Base):
    """Одно событие задания: строка потока, которую увидит человек.

    Наследует `Base`, а не `Row`, и это единственное отличие от прочих таблиц
    службы. `Row` даёт `updated_at`, а событие неизменяемо по смыслу: написано
    — и лежит. Колонка, которая никогда не меняется, на тысяче строк на задание
    стоит тысячи записанных и никем не прочитанных значений, а главное — врёт
    читающему схему: раз есть `updated_at`, значит что-то правится.

    `seq` — номер события внутри задания, с единицы. По нему клиент дочитывает
    поток с места обрыва (`GET …/events?after=seq`), и по нему же он понимает,
    что ничего не пропустил. Времени для этого мало: два события в одну
    миллисекунду неразличимы, а SQLite хранит время строкой.
    """

    __tablename__ = "job_events"

    id: Mapped[str] = mapped_column(String(ID_LEN), primary_key=True,
                                    default=new_id)
    job_id: Mapped[str] = mapped_column(
        String(ID_LEN), ForeignKey("jobs.id", ondelete="CASCADE"))
    seq: Mapped[int] = mapped_column(Integer)

    # Вид события: `progress`, `text`, `tag_closed`, `done`, `failed`,
    # `cancelled`, `events_truncated`. Список открыт намеренно — его пополняют
    # обработчики, и закрывать его здесь значило бы править очередь ради
    # каждого нового события прогона.
    kind: Mapped[str] = mapped_column(String(EVENT_KIND_MAX))

    data: Mapped[dict] = mapped_column(JSON, default=dict)

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=now)

    __table_args__ = (
        # Уникальность пары — не украшение: она и есть заслон от двух писателей
        # одного задания. Два процесса, взявшие один номер, здесь столкнутся,
        # а не разъедутся молча, оставив клиенту дыру в потоке.
        Index("ix_job_events_job_seq", "job_id", "seq", unique=True),
    )


__all__ = ["Job", "JobEvent", "QUEUED", "RUNNING", "DONE", "FAILED",
           "CANCELLED", "STATUSES", "TERMINAL", "KIND_MAX", "STATUS_MAX",
           "WORKER_MAX", "EVENT_KIND_MAX"]
