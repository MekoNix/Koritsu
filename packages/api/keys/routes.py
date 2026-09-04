"""
routes — ключи моделей в настройках аккаунта: `/api/keys`.

    GET    /api/keys             200  свои живые ключи: provider, last4, когда
    GET    /api/keys/providers   200  для каких поставщиков ключ вообще нужен
    POST   /api/keys             201  завести (прежний того же поставщика отзовётся)
    DELETE /api/keys/{key_id}    204  отозвать

Проекта в пути нет намеренно: ключ принадлежит человеку, а не работе. Он и есть
тот случай из докстроки пакета, ради которого службе разрешено импортировать
`llm` напрямую, — список поставщиков нужен там, где никакого проекта ещё нет.

**Ни один маршрут не возвращает ключ и не может его вернуть.** Возвращается
`ModelKey.to_dict`, а в нём шифртекста нет вовсе; расшифровка живёт в
`service.secret_for`, и её отсюда не зовут. Показать ключ один раз при
создании — обычай токенов внешнего API (§7), и к ключу поставщика он не
относится: этот ключ человек уже держит в руках, он его сюда и принёс.
"""
from __future__ import annotations

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field

from ..db import SessionDep
from ..workspaces.deps import CurrentUser
from . import service

router = APIRouter(prefix="/keys", tags=["keys"])


class ModelKeyIn(BaseModel):
    """Тело `POST /api/keys`.

    Поле называется `key`, а не `secret`: человек несёт сюда то, что у
    поставщика называется API key, и переименовывать это по дороге значит
    заставлять его гадать, туда ли он вставил.
    """

    provider: str = Field(..., max_length=64,
                          description="Preset name from the model layer")
    key: str = Field(..., max_length=512, description="Provider API key")


@router.get("", operation_id="list_model_keys",
            summary="List your provider keys",
            description=(
                "Lists your live provider keys: provider, last four characters "
                "and dates. The key itself is never returned. "
                "401 unauthenticated."))
def список(s: SessionDep, user: CurrentUser) -> list[dict]:
    """Живые ключи. Отозванные не показываются: экран отвечает на вопрос «чем я
    сейчас плачу», а не «что у меня когда-то было»."""
    return [k.to_dict() for k in service.list_keys(s, user.id)]


@router.get("/providers", operation_id="list_key_providers",
            summary="Providers that accept a key",
            description=(
                "Lists the model providers a key can be stored for. "
                "401 unauthenticated."))
def поставщики() -> dict:
    """Для каких пресетов ключ имеет смысл.

    Открытый маршрут по содержанию (список имён пресетов — не секрет), но
    закрытый по месту: он под `/api`, то есть за той же cookie-сессией, что и
    остальное. Ключ этот список не раскрывает ничей.
    """
    return {"providers": list(service.providers())}


@router.post("", status_code=201, operation_id="add_model_key",
             summary="Add a provider key",
             description=(
                 "Stores a provider key encrypted; a previous key of the same "
                 "provider is revoked. The response carries the last four "
                 "characters only. 422 validation_failed."))
def завести(тело: ModelKeyIn, request: Request, s: SessionDep,
            user: CurrentUser) -> dict:
    """Зашифровать и положить. В ответе — `last4`, и ничего больше про ключ."""
    строка = service.add_key(s, request.app.state.settings, user.id,
                             тело.provider, тело.key)
    return строка.to_dict()


@router.delete("/{key_id}", status_code=204, operation_id="revoke_model_key",
               summary="Revoke a provider key",
               description=(
                   "Revokes one of your keys. A key that belongs to someone "
                   "else and a key that never existed answer alike. "
                   "404 not_found."))
def отозвать(key_id: str, s: SessionDep, user: CurrentUser) -> Response:
    """Отозвать свой ключ. Чужой и несуществующий — одинаково `404` (§3)."""
    service.revoke(s, user.id, key_id)
    return Response(status_code=204)


__all__ = ["router", "ModelKeyIn"]
