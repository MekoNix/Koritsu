"""
billing — место под платёжку, занятое заглушкой.

    POST /api/billing/webhook   501  not_implemented

Решение владельца §7: «подписку включает владелец в админке; платёжка потом, но
endpoint `POST /billing/webhook` заложить пустым, чтобы платёжка встала без
правки модели». §11 повторяет это цифрой: `501 Not Implemented`.

**Тело не читается.** Ни разбора JSON, ни проверки подписи, ни записи в журнал:
пока обработчика нет, всё это было бы обещанием, которого служба не держит.
Хуже того, читать тело опасно — вебхук платёжки приходит из интернета без
всякого входа, и разбор чужого JSON на маршруте без защиты это то, чем
занимаются первыми. Заглушка отвечает `501` до того, как что-либо прочитано.

**`501`, а не `404` и не `503`.** `404` соврал бы, что адреса нет, — и платёжная
система, настраиваемая по инструкции, показала бы «неверный URL» тому, кто
настроил всё правильно. `503` означает «временно», то есть «повторите», и
платёжка честно повторяла бы вечно. `501` — «этот метод здесь не реализован», и
это ровно правда.

Когда платёжка появится: обработчик пишется здесь же, а не рядом — маршрут,
заведённый вторым местом, оставит эту заглушку отвечать `501` на половину
запросов.
"""
from __future__ import annotations

from fastapi import APIRouter

from .errors import ApiError

NOT_IMPLEMENTED = "not_implemented"

router = APIRouter(prefix="/billing", tags=["billing"])


@router.post("/webhook", operation_id="billing_webhook",
             summary="Payment webhook, not implemented yet",
             description=(
                 "Reserved for the payment provider. Answers 501 "
                 "not_implemented and does not read the request body; "
                 "subscriptions are switched on by the owner in the admin "
                 "area for now."))
def вебхук() -> None:
    """Заглушка платёжки. Тело запроса не читается — см. докстроку модуля."""
    raise ApiError(NOT_IMPLEMENTED,
                   "Billing is not implemented yet", 501)


__all__ = ["router", "NOT_IMPLEMENTED"]
