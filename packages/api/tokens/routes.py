"""
routes — внешние ключи в настройках аккаунта: `/api/tokens`.

    POST   /api/tokens             201  завести; строка ключа — только здесь
    GET    /api/tokens             200  свои ключи: приставка, имя, права, даты
    DELETE /api/tokens/{token_id}  200  отозвать

**`201` и строка ключа один раз.** Тело ответа на создание — единственное
место во всей службе, где строка ключа существует; в списке её нет, в базе
хеш, в журнале приставка: строка ключа показывается один раз при создании.

**Отзыв отвечает карточкой, а не `204`.** У ключей моделей `204` уместен —
там отозванный ключ исчезает из списка. Здесь наоборот: отозванный ключ
остаётся видимым (иначе непонятно, отозвал ли ты его или он пропал), и человеку
полезно увидеть `revoked_at` тем же ответом, не перезапрашивая список.

**Сюда нельзя ключом** — только сессией сайта (`auth.ТОЛЬКО_СЕССИЯ`).
Иначе утёкший ключ выписывает себе второй, и отзыв первого ничего не даёт.
"""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..db import SessionDep
from ..workspaces.deps import CurrentUser
from . import service

router = APIRouter(prefix="/tokens", tags=["tokens"])


class ApiTokenIn(BaseModel):
    """Тело `POST /api/tokens`: как назвать и что этим ключом можно."""

    name: str = Field(..., max_length=64,
                      description="Human-readable name, e.g. 'CI' or 'laptop'")
    scopes: list[str] = Field(
        ...,
        description=("What the token may do; at least one of: "
                     + ", ".join(service.ПРАВА)))


class ApiTokenOut(BaseModel):
    """Карточка ключа. Строки ключа в ней нет и быть не может."""

    id: str = Field(description="Token id, used to revoke it")
    name: str = Field(description="Human-readable name")
    prefix: str = Field(description="First characters, to tell tokens apart")
    scopes: list[str] = Field(description="What this token may do")
    created_at: str | None = Field(default=None, description="When it was issued")
    last_used_at: str | None = Field(
        default=None,
        description="Last use, written at most once a minute")
    revoked_at: str | None = Field(default=None,
                                   description="When it was revoked, if it was")


class ApiTokenCreated(ApiTokenOut):
    """Ответ на создание: карточка и сама строка ключа, в первый и последний раз."""

    token: str = Field(
        description="The token string; shown once and never stored in clear")


@router.post("", status_code=201, operation_id="create_api_token",
             response_model=ApiTokenCreated,
             summary="Create an API token",
             description=(
                 "Issues a token for the /api/v1 entrance and returns its "
                 "string once: the service keeps only a hash, so a lost token "
                 "is revoked and reissued, never recovered. "
                 "400 unknown_scope, 401 token_not_allowed."))
def завести(тело: ApiTokenIn, s: SessionDep, user: CurrentUser) -> dict:
    """Завести ключ и отдать его строку — единственный раз за его жизнь."""
    ключ, строка = service.выдать(s, user.id, тело.name, тело.scopes)
    return {**service.карточка(ключ), "token": строка}


@router.get("", operation_id="list_api_tokens",
            response_model=list[ApiTokenOut],
            summary="List your API tokens",
            description=(
                "Your tokens, newest first: prefix, name, scopes and dates. "
                "Revoked ones stay in the list, marked with revoked_at. The "
                "token string is never listed. 401 token_not_allowed."))
def список(s: SessionDep, user: CurrentUser) -> list[dict]:
    """Свои ключи. Отозванные остаются — см. докстроку модуля."""
    return [service.карточка(k) for k in service.мои(s, user.id)]


@router.delete("/{token_id}", operation_id="revoke_api_token",
               response_model=ApiTokenOut,
               summary="Revoke an API token",
               description=(
                   "Revokes one of your tokens at once; requests carrying it "
                   "answer 401 token_revoked from then on. A token that "
                   "belongs to someone else and one that never existed answer "
                   "alike. 404 not_found, 401 token_not_allowed."))
def отозвать(token_id: str, s: SessionDep, user: CurrentUser) -> dict:
    """Отозвать свой ключ. Чужой и несуществующий — одинаково `404`."""
    return service.карточка(service.отозвать(s, user.id, token_id))


__all__ = ["router", "ApiTokenIn", "ApiTokenOut", "ApiTokenCreated"]
