"""
routes — `/api/notifications`: колокольчик.

    GET    /api/notifications            200  свои, новые сверху (фильтр unread)
    POST   /api/notifications/{id}/read  200  пометить одно
    POST   /api/notifications/read-all   200  пометить все
    DELETE /api/notifications/{id}       200  убрать одно

«Прочитать все» одним запросом — не роскошь: это одна транзакция вместо
пятидесяти, а после ночного прогона непрочитанных бывает именно столько.

Удаление есть потому, что колокольчик — не архив: прочитанную строку человек
вправе убрать с глаз. Уносит она с собой только себя — ни задание, ни его файлы
за ней не идут.

`unread_count` кладётся в ответ списка, чтобы колокольчик рисовался без второго
запроса: число на нём и сам список показываются вместе, и разделять их значило
бы показать «3» рядом с пятью строками.

Коды отказа: `404 not_found` — чужое или несуществующее уведомление (одинаково,
см. `service.получить`).
"""
from __future__ import annotations

from fastapi import APIRouter, Query

from ..db import SessionDep
from ..workspaces.deps import CurrentUser
from . import service

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", operation_id="list_notifications",
            summary="Your notifications",
            description=(
                "Your own notifications, newest first, with the unread count. "
                "There are no emails: this list and the event stream are the "
                "only ways a finished job announces itself."))
def список(s: SessionDep, user: CurrentUser,
           unread: bool | None = Query(
               None, description="true for unread only, false for read only"),
           limit: int = Query(100, ge=1, le=500)) -> dict:
    """Свои уведомления и число непрочитанных."""
    строки = service.мои(s, user.id, unread=unread, limit=limit)
    return {"notifications": [service.карточка(n) for n in строки],
            "unread_count": service.непрочитанных(s, user.id)}


@router.post("/{notification_id}/read", operation_id="read_notification",
             summary="Mark one notification read",
             description=(
                 "Marks one notification of yours as read. Reading twice keeps "
                 "the first timestamp. 400 invalid_id, 404 not_found."))
def прочитать(notification_id: str, s: SessionDep, user: CurrentUser) -> dict:
    строка = service.получить(s, user.id, notification_id)
    return service.карточка(service.прочитать(s, строка))


@router.delete("/{notification_id}", operation_id="delete_notification",
               summary="Delete one notification",
               description=(
                   "Deletes one notification of yours for good. The job it "
                   "announced and its files stay where they were. "
                   "400 invalid_id, 404 not_found."))
def удалить(notification_id: str, s: SessionDep, user: CurrentUser) -> dict:
    строка = service.получить(s, user.id, notification_id)
    service.убрать(s, строка)
    return {"deleted": notification_id,
            "unread_count": service.непрочитанных(s, user.id)}


@router.post("/read-all", operation_id="read_all_notifications",
             summary="Mark every unread notification read",
             description=(
                 "Marks all your unread notifications read in one go and "
                 "answers with how many were marked."))
def прочитать_все(s: SessionDep, user: CurrentUser) -> dict:
    return {"marked": service.прочитать_все(s, user.id),
            "unread_count": 0}


__all__ = ["router"]
