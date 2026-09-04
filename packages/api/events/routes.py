"""
routes — два потока `text/event-stream`: один про задание, один про человека.

    GET /api/jobs/{id}/stream   200  события задания, закрывается по финалу
    GET /api/events             200  уведомления и «задание кончилось»

**Почему потоков два, а не один.** Решение владельца §11 записано так: «`GET
/api/jobs/{id}/events` — прогресс и текст одного задания; `GET /api/events` —
один поток на пользователя для уведомлений и колокольчика». Разница не в
удобстве: поток задания открывают на экране прогона и закрывают вместе с ним, а
поток человека висит всё время, пока открыт сайт, и несёт на порядок меньше
кадров. Слить их значило бы гонять текст модели в каждую открытую вкладку.

**Курсор — `after`, он же `Last-Event-ID`.** Заголовок сильнее параметра
намеренно: параметр ставит наш код при первом подключении, заголовок ставит
браузер при **пере**подключении, и переподключение — как раз тот случай, когда
клиент знает лучше. Поток задания считает курсором `seq`, поток человека — время
создания уведомления (`sse.py` объясняет, почему у них разные курсоры).

**Поток задания закрывается сам** — по терминальному статусу и не раньше, чем
отдаст последнее событие. Событие это пишет воркер в той же транзакции, что
ставит статус (`jobs/worker._закрыть`), поэтому «статус терминальный» и «все
события видны» — одно и то же состояние, если прочитать их одной сессией. Порядок
чтения внутри опроса поэтому такой: сначала события, потом статус.

Коды отказа свои: нет. `404 not_found` на чужое задание приходит из
`jobs.service.получить` — до того, как поток начался.
"""
from __future__ import annotations

import datetime
import time

from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import StreamingResponse

from ..db import SessionDep, now
from ..ids import check_id
from ..jobs import service as jobs
from ..jobs.models import Job, TERMINAL
from ..notifications import service as notifications
from ..workspaces.deps import CurrentUser
from . import sse

# Сколько событий берётся за один опрос. Полтысячи — тот же потолок, что у
# маршрута-списка (`jobs/routes.py`): поток и список читают одну выборку, и
# разные потолки означали бы, что дочитывание с обрыва ведёт себя по-разному в
# зависимости от того, чем дочитывают.
ПАЧКА = 500

# Роутер потока задания несёт тот же префикс, что и роутер очереди. Два роутера
# на один префикс — обычное дело для FastAPI и здесь оно правильное: поток
# принадлежит событиям, а не очереди, и класть его в `jobs/routes.py` значило бы
# завести в очереди знание про `text/event-stream`.
job_router = APIRouter(prefix="/jobs", tags=["events"])
user_router = APIRouter(prefix="/events", tags=["events"])


# ── поток одного задания ─────────────────────────────────────────────────────

@job_router.get("/{job_id}/stream", operation_id="jobs_stream",
                summary="Server-sent stream of one job",
                description=(
                    "Events of one job as `text/event-stream`: `id` is the "
                    "sequence number, the event name is the event kind, the "
                    "data is one JSON line. Starts after `after` (or after the "
                    "`Last-Event-ID` header) and closes itself once the job "
                    "reaches a final state. 400 invalid_id, 404 not_found."),
                response_class=StreamingResponse)
def поток_задания(job_id: str, request: Request, s: SessionDep,
                  user: CurrentUser,
                  after: int = Query(0, ge=0,
                                     description="Resume after this sequence number"),
                  last_event_id: str | None = Header(
                      None, alias="Last-Event-ID",
                      description="Sequence number to resume after; wins over `after`"),
                  ) -> StreamingResponse:
    """События задания потоком. Закрывается сам, когда задание кончится."""
    задание = jobs.получить(s, user.id, check_id(job_id, where="path.job_id"))
    задание.last_seen_at = now()
    свой = задание.id
    _отпустить(s)
    начало = _курсор(after, last_event_id)
    db = request.app.state.db
    settings = request.app.state.settings
    user_id = user.id

    def кадры():
        # Сессия запроса отпущена выше; генератор открывает свою на каждый
        # опрос и закрывает её перед сном — см. докстроку `sse.py`.
        yield from _качать(settings, _опрос_задания(db, user_id, свой), начало)

    return StreamingResponse(кадры(), media_type=sse.MEDIA_TYPE,
                             headers=dict(sse.ЗАГОЛОВКИ))


def _опрос_задания(db, user_id: str, job_id: str):
    """Один опрос базы: кадры и признак «поток кончился». Замыкание, не класс.

    Возвращает функцию `(курсор) -> (кадры, новый курсор, конец)`. Замыкание
    здесь честнее класса с тремя полями: у опроса нет состояния, кроме курсора,
    а курсор принадлежит качающему циклу, общему на оба потока.
    """
    def опрос(курсор):
        with db.session_scope() as s:
            задание = s.get(Job, job_id)
            if задание is None or задание.user_id != user_id:
                # Задание убрали (срок хранения) или оно перестало быть своим.
                # Молча закрываем поток: рассказывать в кадре, что случилось,
                # значило бы отвечать телом на вопрос доступа.
                return [], курсор, True
            строки = jobs.события(s, job_id, after=int(курсор), limit=ПАЧКА)
            терминально = задание.status in TERMINAL
        кадры = [sse.кадр(id=e.seq, event=e.kind,
                          data=jobs.карточка_события(e)) for e in строки]
        новый = строки[-1].seq if строки else курсор
        # Пачка набралась целиком — значит есть ещё; спать нельзя.
        полная = len(строки) >= ПАЧКА
        return кадры, новый, (терминально and not полная)
    return опрос


# ── поток человека ───────────────────────────────────────────────────────────

@user_router.get("", operation_id="user_events",
                 summary="Server-sent stream of your notifications",
                 description=(
                     "One stream per person: `notification` for anything worth "
                     "a bell, `job_finished` when a job of yours reaches a "
                     "final state. `id` is the creation time, which the browser "
                     "sends back as `Last-Event-ID` on reconnect. There are no "
                     "emails; this stream and `GET /api/notifications` are the "
                     "only announcements."),
                 response_class=StreamingResponse)
def поток_человека(request: Request, s: SessionDep, user: CurrentUser,
                   after: str | None = Query(
                       None, description="ISO time to resume after"),
                   last_event_id: str | None = Header(
                       None, alias="Last-Event-ID",
                       description="ISO time to resume after; wins over `after`"),
                   ) -> StreamingResponse:
    """Уведомления и «задание кончилось» потоком. Не закрывается сам."""
    _отпустить(s)
    начало = _момент(last_event_id or after) or now()
    db = request.app.state.db
    settings = request.app.state.settings
    user_id = user.id

    def кадры():
        yield from _качать(settings, _опрос_человека(db, user_id), начало)

    return StreamingResponse(кадры(), media_type=sse.MEDIA_TYPE,
                             headers=dict(sse.ЗАГОЛОВКИ))


def _опрос_человека(db, user_id: str):
    """Один опрос: новые уведомления этого человека кадрами."""
    def опрос(курсор):
        with db.session_scope() as s:
            строки = notifications.после(s, user_id, курсор)
            карточки = [notifications.карточка(n) for n in строки]
            времена = [n.created_at for n in строки]
        кадры = []
        for карточка, момент in zip(карточки, времена):
            # `job_finished` — то же уведомление, но названное так, как его ждёт
            # интерфейс: «обнови карточку задания» и «покажи точку на
            # колокольчике» — разные действия, и различать их по содержимому
            # `data` значило бы завести второй разбор того же различия.
            вид = ("job_finished" if карточка["kind"] in notifications.JOB_KINDS
                   else "notification")
            кадры.append(sse.кадр(id=момент.isoformat(), event=вид,
                                  data=карточка))
        новый = времена[-1] if времена else курсор
        return кадры, новый, False
    return опрос


# ── общий насос ──────────────────────────────────────────────────────────────

def _качать(settings, опрос, курсор):
    """Один цикл на оба потока: опросить, отдать, поспать, повторить.

    Общий намеренно. Различий у потоков ровно три — что читать, чем считать
    курсор и когда кончиться, — и все три вынесены в `опрос`. Написанный
    дважды, цикл разошёлся бы там, где это дороже всего: в пульсе и в потолке
    жизни соединения, то есть в поведении при плохой сети.

    Оба числа — из настроек (`sse_poll_s`, `sse_max_s`), а не константами по
    месту: и то, и другое подбирается под живой прокси, а не под наш вкус, и
    подбирается строкой в `.env`, а не выкатом.
    """
    пауза = float(settings.sse_poll_s)
    часы = sse.Часы(потолок=float(settings.sse_max_s))
    # Первым делом — пульс, ещё до первого опроса базы. Он не украшение: пока
    # из генератора не вышло ни байта, ответ висит без заголовков, и клиент не
    # знает, открылся ли поток вообще. Комментарий клиент выбрасывает, а
    # соединение с этого мгновения считается установленным.
    yield sse.пульс()
    while True:
        кадры, курсор, конец = опрос(курсор)
        for кадр in кадры:
            yield кадр
        if кадры:
            часы.отметить()
        if конец:
            return
        if часы.вышло_время:
            # Не беда и не ошибка: клиент переподключится с `Last-Event-ID` и
            # продолжит с того же места. Потолок нужен, чтобы забытая вкладка
            # не держала соединение и его сессии сутками.
            return
        if not кадры:
            if часы.пора_пульс():
                yield sse.пульс()
            time.sleep(пауза)


# ── мелочи ───────────────────────────────────────────────────────────────────

def _отпустить(s) -> None:
    """Закрыть сессию запроса до того, как начнётся поток.

    Без этой строки обещание «сессия не держится на весь поток» было бы
    неправдой. FastAPI (0.141) закрывает зависимости с `yield` **после** того,
    как ответ отдан целиком: стек `fastapi_inner_astack` обёрнут вокруг
    `await response(...)` (`fastapi/routing.py`). Для обычного маршрута это ровно
    то, что нужно, а для `text/event-stream` означает соединение к базе,
    занятое на всё время потока: десяток открытых вкладок выбирает пул целиком,
    и служба перестаёт отвечать всем остальным.

    Порядок — коммит, потом закрытие: закрытие откатывает несохранённое, а мы
    только что двинули `last_seen_at`. Сессия после этого не сломана — обёртка
    `db.session_scope` в конце запроса сделает свой (пустой) коммит и закроет её
    ещё раз; оба действия на закрытой сессии законны и дёшевы.
    """
    s.commit()
    s.close()



def _курсор(after: int, last_event_id: str | None) -> int:
    """Номер, с которого дочитывать. Заголовок сильнее параметра.

    Мусор в заголовке — это не отказ: заголовок ставит браузер, и уронить
    переподключение из-за его причуды значило бы оставить человека без потока
    там, где достаточно начать сначала.
    """
    if last_event_id:
        try:
            return max(0, int(str(last_event_id).strip()))
        except ValueError:
            return int(after)
    return int(after)


def _момент(сырое: str | None) -> datetime.datetime | None:
    """ISO-время курсора или `None`. Мусор — тоже `None`, см. `_курсор`."""
    if not сырое:
        return None
    try:
        м = datetime.datetime.fromisoformat(str(сырое).strip())
    except ValueError:
        return None
    return м if м.tzinfo else м.replace(tzinfo=datetime.timezone.utc)


__all__ = ["job_router", "user_router"]
