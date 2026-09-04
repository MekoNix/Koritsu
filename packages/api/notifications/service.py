"""
service — кто заводит уведомления, кто их читает и кто помечает прочитанными.

    при_завершении(s, задание)   заводит одно уведомление по терминальному статусу
    мои(s, user_id, unread=)     список, новые сверху
    после(s, user_id, момент)    что появилось позже этого — для потока событий
    прочитать / прочитать_все    пометить

**Заводит уведомление родитель, а не обработчик.** Строку пишет тот, кто ставит
терминальный статус, и в той же транзакции, что и статус. Причина та же, по
которой статус ставит родитель: обработчик могут убить по таймауту, по отмене,
по нехватке памяти, и уведомление «готово», написанное им заранее, пережило бы
работу, которой не случилось. Родитель узнаёт исход последним и потому знает
правду.

Мест, где терминальный статус появляется, ровно три, и зовут отсюда все три
(решение владельца §12 добавило два последних):

    jobs/worker.Worker._закрыть            done / failed / cancelled по ответу
    jobs/worker.Worker.поднять_потерянные  failed с `worker_lost`
    jobs/service.отменить                  cancelled ждущего, до захвата

Четвёртого места быть не должно: задание, кончившееся без уведомления, — это
человек, ждущий отчёта, о котором служба ему больше ничего не скажет.

Отсюда же — единственность. Уведомление о задании ровно одно, и держится это
`UNIQUE` на `job_id` (`models.py`), а не проверкой в коде: два воркера, закрывшие
одно задание, столкнулись бы здесь, а не разъехались бы двумя строками в
колокольчике.

    Виды и почему их четыре, а не два
    ---------------------------------

    job_done          задание сделано
    job_cancelled     остановлено по просьбе человека
    job_failed        упало
    limit_exhausted   упало **оттого, что кончились деньги**

Последний вид — не педантизм. «Прогон не удался» и «кончился месячный лимит» для
человека — разные события с разными действиями: первое повторяют, второе нет, и
интерфейс обязан различать их без чтения текста. Разбирать `data.code` в клиенте
значило бы завести второе описание того же различия.

**Писем нет** (§11), и здесь их нет тем более: этот модуль пишет строку в базу и
на этом кончается. Ни SMTP, ни очереди писем, ни поля `email_sent_at`.
"""
from __future__ import annotations

import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import now
from ..errors import ApiError, NOT_FOUND
from ..ids import check_id
from ..workspaces.service import iso
from .models import Notification

JOB_DONE = "job_done"
JOB_FAILED = "job_failed"
JOB_CANCELLED = "job_cancelled"
LIMIT_EXHAUSTED = "limit_exhausted"

# Виды, которые говорят «задание кончилось». По ним поток на пользователя
# отличает `job_finished` от прочего (`api/events`).
JOB_KINDS = (JOB_DONE, JOB_FAILED, JOB_CANCELLED, LIMIT_EXHAUSTED)

KINDS = JOB_KINDS

# Терминальный статус задания → вид уведомления. Словарём, а не цепочкой
# `if`: третий статус, добавленный в очередь, обязан появиться здесь же, а не
# провалиться в `else` под чужим именем.
ПО_СТАТУСУ = {"done": JOB_DONE, "failed": JOB_FAILED,
              "cancelled": JOB_CANCELLED}


# ── заведение ────────────────────────────────────────────────────────────────

def при_завершении(s: Session, задание) -> Notification | None:
    """Уведомление по законченному заданию. → строка или `None`.

    `None` в трёх случаях, и все три законные: задание ещё не кончилось,
    уведомление о нём уже есть, статуса нет в словаре (значит очередь завела
    четвёртый терминальный статус и не сказала — это беда настройки, а не повод
    ронять закрытие задания).

    Зовётся **внутри** транзакции воркера: уведомление и терминальный статус
    обязаны появиться вместе. Иначе перезапуск между двумя коммитами оставил бы
    готовое задание без строки в колокольчике — то есть ровно тот случай, ради
    которого таблица и заведена.
    """
    статус = str(getattr(задание, "status", "") or "")
    вид = ПО_СТАТУСУ.get(статус)
    if вид is None:
        return None
    беда = dict(getattr(задание, "error", None) or {})
    код = str(беда.get("code") or "")
    if вид == JOB_FAILED and код == LIMIT_EXHAUSTED:
        # Отдельный вид, а не `job_failed` с кодом внутри: человек различает эти
        # два случая действием, а не текстом (см. докстроку модуля).
        вид = LIMIT_EXHAUSTED
    if s.scalar(select(Notification.id)
                .where(Notification.job_id == задание.id)) is not None:
        return None
    строка = Notification(
        user_id=задание.user_id, job_id=задание.id, kind=вид,
        data={"job_id": задание.id, "job_kind": задание.kind,
              "status": статус, "project_id": задание.project_id,
              "code": код or None,
              "spent_units": int(getattr(задание, "spent_units", 0) or 0)})
    s.add(строка)
    s.flush()
    return строка


# ── чтение ───────────────────────────────────────────────────────────────────

def мои(s: Session, user_id: str, *, unread: bool | None = None,
        limit: int = 100) -> list[Notification]:
    """Уведомления этого человека, новые сверху. `unread=True` — непрочитанные.

    Только свои, и это единственная проверка доступа списка: чужое уведомление
    не показывается никому, потому что в `data` лежит идентификатор чужого
    проекта (§3, то же правило, что у списка заданий).
    """
    запрос = select(Notification).where(Notification.user_id == user_id)
    if unread is True:
        запрос = запрос.where(Notification.read_at.is_(None))
    elif unread is False:
        запрос = запрос.where(Notification.read_at.is_not(None))
    запрос = запрос.order_by(Notification.created_at.desc(),
                             Notification.id).limit(int(limit))
    return list(s.scalars(запрос))


def непрочитанных(s: Session, user_id: str) -> int:
    """Сколько непрочитанных. То число, которое рисуется на колокольчике."""
    from sqlalchemy import func                              # noqa: PLC0415

    return int(s.scalar(select(func.count()).select_from(Notification)
                        .where(Notification.user_id == user_id,
                               Notification.read_at.is_(None))) or 0)


def после(s: Session, user_id: str, момент: datetime.datetime | None, *,
          limit: int = 100) -> list[Notification]:
    """Что появилось строго позже этого момента, старые сверху. Для потока.

    Порядок обратный списку намеренно: список читает человек (ему нужно
    последнее), поток дочитывает клиент (ему нужно следующее). Курсор — время
    создания, а не номер: у уведомлений нет своей последовательности, и заводить
    её ради потока значило бы завести счётчик на таблицу, которая пишется раз в
    несколько минут.
    """
    запрос = select(Notification).where(Notification.user_id == user_id)
    if момент is not None:
        запрос = запрос.where(Notification.created_at > момент)
    return list(s.scalars(запрос.order_by(Notification.created_at,
                                          Notification.id).limit(int(limit))))


# ── пометки ──────────────────────────────────────────────────────────────────

def получить(s: Session, user_id: str, nid: str) -> Notification:
    """Своё уведомление. Чужое и несуществующее — одинаково `404`.

    Одинаково по тому же доводу, что у чужого задания: `403` сообщал бы, что
    строка с таким идентификатором есть.
    """
    строка = s.get(Notification, check_id(nid, where="path.notification_id"))
    if строка is None or строка.user_id != user_id:
        raise ApiError(NOT_FOUND, "Notification not found", 404,
                       where="path.notification_id")
    return строка


def прочитать(s: Session, строка: Notification) -> Notification:
    """Пометить прочитанным. Повторно — не беда: время не переписывается.

    Не переписывается намеренно: «когда человек это увидел» — единственный
    ответ, и вторая пометка не делает его вторым.
    """
    if строка.read_at is None:
        строка.read_at = now()
    return строка


def прочитать_все(s: Session, user_id: str) -> int:
    """Пометить все непрочитанные. → сколько пометили.

    Одним `UPDATE`, а не обходом строк: колокольчик с полусотней непрочитанных
    — обычное дело после ночного прогона, и пятьдесят отдельных записей ради
    одной кнопки база помнить не обязана.
    """
    момент = now()
    итог = s.query(Notification).filter(
        Notification.user_id == user_id,
        Notification.read_at.is_(None)).update({Notification.read_at: момент},
                                               synchronize_session=False)
    return int(итог or 0)


# ── наружу ───────────────────────────────────────────────────────────────────

def карточка(строка: Notification) -> dict:
    """Уведомление наружу. Та же форма, в какой его отдаёт поток событий."""
    return {"id": строка.id, "kind": строка.kind,
            "job_id": строка.job_id, "data": строка.data or {},
            "read_at": iso(строка.read_at), "created_at": iso(строка.created_at)}


__all__ = ["при_завершении", "мои", "непрочитанных", "после", "получить",
           "прочитать", "прочитать_все", "карточка", "KINDS", "JOB_KINDS",
           "JOB_DONE", "JOB_FAILED", "JOB_CANCELLED", "LIMIT_EXHAUSTED",
           "ПО_СТАТУСУ"]
