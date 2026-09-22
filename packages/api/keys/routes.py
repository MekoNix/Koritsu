"""
routes — ключи моделей в настройках аккаунта: `/api/keys`.

    GET    /api/keys                      200  свои живые ключи
    GET    /api/keys/providers            200  кому нужен ключ и что выбрано
    POST   /api/keys                      201  завести ключ модели
    PUT    /api/keys/{provider}/model     200  выбрать модель поставщика
    GET    /api/keys/{provider}/models    200  какие модели у него есть
    PUT    /api/keys/ink                  200  пара ключей распознавания разом
    DELETE /api/keys/ink                  204  отозвать пару разом
    DELETE /api/keys/{key_id}             204  отозвать ключ модели

Проекта в пути нет намеренно: ключ принадлежит человеку, а не работе. Он и есть
тот случай из докстроки пакета, ради которого службе разрешено импортировать
`llm` напрямую, — список поставщиков нужен там, где никакого проекта ещё нет.

**Ключи распознавания рукописи заводятся только парой** (`PUT /api/keys/ink`).
Подпись вызова MyScript строится из двух ключей сразу: `applicationKey` едет в
адресе сокета, `hmacKey` подписывает. Один без другого не работает, поэтому
дверь на двоих одна, и отзыв тоже общий: оставить половину пары значило бы
показывать человеку заведённый ключ там, где распознавание всё равно молчит.
`POST /api/keys` чернила не принимает вовсе — отказ называет нужную дверь.

**Ни один маршрут не возвращает ключ и не может его вернуть.** Возвращается
`ModelKey.to_dict`, а в нём шифртекста нет вовсе; расшифровка живёт в
`service.secret_for`, и её отсюда не зовут. Показать ключ один раз при
создании — обычай токенов внешнего API, и к ключу поставщика он не
относится: этот ключ человек уже держит в руках, он его сюда и принёс.
"""
from __future__ import annotations

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field

from ..db import SessionDep
from ..errors import ApiError
from ..workspaces.deps import CurrentUser
from . import catalog, service
from .models import MODEL_MAX

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


class InkKeysIn(BaseModel):
    """Тело `PUT /api/keys/ink` — пара ключей MyScript.

    Два поля в одном теле, а не два запроса: пара и есть единица настройки.
    Имена полей — те же, что у MyScript в личном кабинете (`applicationKey`,
    `hmacKey`), только в змеином регистре: человек переносит их глазами, и
    переименовывать их по дороге значит заставлять его гадать.
    """

    application_key: str = Field(..., max_length=512,
                                 description="MyScript applicationKey")
    hmac_key: str = Field(..., max_length=512, description="MyScript hmacKey")


class ModelIn(BaseModel):
    """Тело `PUT /api/keys/{provider}/model`. Пусто — умолчание пресета."""

    model: str = Field("", max_length=MODEL_MAX,
                       description="Model name at the provider; empty resets")


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
                "Lists the providers a key can be stored for. `has_key` says "
                "whether you have a working key for each one; a run goes on "
                "your own key and on no other, so a provider without a key "
                "cannot be used. `kind` says what the key is for: `model` pays "
                "for a model run, `ink` recognises handwriting on a board. "
                "`model` carries the model chosen for that provider, empty "
                "meaning the preset default. 401 unauthenticated."))
def поставщики(request: Request, s: SessionDep, user: CurrentUser) -> dict:
    """Для каких пресетов ключ имеет смысл и чем по каждому платить.

    Открытый маршрут по содержанию (список имён пресетов — не секрет), но
    закрытый по месту: он под `/api`, то есть за той же cookie-сессией, что и
    остальное. Ключ этот список не раскрывает ничей.

    **`has_key` — не удобство, а условие работы экрана.** Поставщик выбирается
    перед прогоном, и выбрать того, у кого ключа нет, значит получить отказ
    вместо работы. Ответ при этом двоичный, потому что источников ключа ровно
    один — свой: общего ключа службы нет, и «работает на чужие деньги» больше не
    бывает.

    Тем же ответом, а не соседним маршрутом: список пресетов без того, чем по
    ним платить, — это половина ответа, за которой всё равно идут вторым
    запросом. Тем же ответом едет и выбранная модель: экран рисует её строкой
    того же поставщика.

    **`kind` — тем же ответом и по той же причине.** Поставщики двух видов:
    модель и распознавание рукописи. Заводятся они одинаково, но спрашиваются в
    разных местах, и настройки рисуют их разными подразделами. Решать, какой
    поставщик к какому подразделу относится, по имени в браузере значило бы
    завести второй список чернильных поставщиков — тот, что разойдётся с первым
    при третьем поставщике.
    """
    settings = request.app.state.settings
    имена = list(service.providers())
    return {"providers": имена,
            "has_key": {имя: service.has_key(settings, s, user.id, имя)
                        for имя in имена},
            "kind": {имя: service.kind_of(имя) for имя in имена},
            "model": {имя: service.model_of(s, user.id, имя) for имя in имена}}


@router.post("", status_code=201, operation_id="add_model_key",
             summary="Add a provider key",
             description=(
                 "Stores a provider key encrypted; a previous key of the same "
                 "provider is revoked. The response carries the last four "
                 "characters only. 422 validation_failed."))
def завести(тело: ModelKeyIn, request: Request, s: SessionDep,
            user: CurrentUser) -> dict:
    """Зашифровать и положить. В ответе — `last4`, и ничего больше про ключ."""
    имя = service.check_provider(тело.provider)
    if service.kind_of(имя) == service.ЧЕРНИЛА:
        raise ApiError(
            service.INVALID_KEY,
            "Handwriting keys come in pairs: use PUT /api/keys/ink", 400,
            where="body.provider")
    строка = service.add_key(s, request.app.state.settings, user.id,
                             имя, тело.key)
    catalog.забыть(user.id, имя)
    return строка.to_dict()


@router.put("/ink", operation_id="set_ink_keys",
            summary="Store both handwriting keys at once",
            description=(
                "Stores the MyScript application key and HMAC key together; "
                "previous ones are revoked. Both are required: a signature is "
                "built from the pair, and half of it recognises nothing. The "
                "response carries the last four characters of each. "
                "400 invalid_key, 422 validation_failed."))
def завести_чернила(тело: InkKeysIn, request: Request, s: SessionDep,
                    user: CurrentUser) -> dict:
    """Пара ключей распознавания одной дверью.

    Обе строки кладутся в одной сессии: половина пары — это не «частично
    настроено», а «не настроено», и оставить её после отказа на второй строке
    значило бы показать человеку ключ, которым ничего не работает.
    """
    settings = request.app.state.settings
    приложение = service.add_key(s, settings, user.id, service.ЧЕРНИЛЬНЫЕ[0],
                                 тело.application_key)
    подпись = service.add_key(s, settings, user.id, service.ЧЕРНИЛЬНЫЕ[1],
                              тело.hmac_key)
    return {"keys": [приложение.to_dict(), подпись.to_dict()]}


@router.delete("/ink", status_code=204, operation_id="revoke_ink_keys",
               summary="Revoke both handwriting keys",
               description=(
                   "Revokes the handwriting key pair. Revoking one of the two "
                   "would leave a key that recognises nothing, so both go. "
                   "Nothing stored answers alike. 401 unauthenticated."))
def отозвать_чернила(s: SessionDep, user: CurrentUser) -> Response:
    """Отозвать пару. Ничего не заведено — тот же 204: состояние то же."""
    for строка in service.list_keys(s, user.id):
        if строка.provider in service.ЧЕРНИЛЬНЫЕ:
            service.revoke(s, user.id, строка.id)
    return Response(status_code=204)


@router.get("/{provider}/models", operation_id="list_provider_models",
            summary="Models this provider offers",
            description=(
                "Asks the provider itself, with your key, which models it has "
                "and caches the answer for half an hour; `refresh=true` goes "
                "past the cache. `source` says where the list came from: "
                "`provider` answered, or `preset` when it did not, and the list "
                "is what we know without it, with `note` saying why. "
                "400 unknown_provider, 401 unauthenticated."))
def модели(provider: str, request: Request, s: SessionDep, user: CurrentUser,
           refresh: bool = False) -> dict:
    """Список моделей поставщика. Беда поставщика — не беда этого маршрута."""
    return catalog.models(request.app.state.settings, s, user.id, provider,
                          refresh=refresh)


@router.put("/{provider}/model", operation_id="set_provider_model",
            summary="Choose the model of a provider",
            description=(
                "Chooses which model of the provider your runs use. An empty "
                "string returns to the preset default. The name is not checked "
                "against the provider catalog: a working name missing from the "
                "catalog is a thing that happens, and refusing it would forbid "
                "a model that works. 400 unknown_provider, 404 not_found."))
def выбрать_модель(provider: str, тело: ModelIn, s: SessionDep,
                   user: CurrentUser) -> dict:
    """Выбрать модель. Нет ключа — `404`: поставщика без ключа у человека нет."""
    имя = service.check_provider(provider, where="path.provider")
    if service.kind_of(имя) == service.ЧЕРНИЛА:
        raise ApiError(service.UNKNOWN_PROVIDER,
                       "Handwriting providers have no model to choose", 400,
                       where="path.provider")
    return {"provider": имя, "model": service.set_model(s, user.id, имя,
                                                        тело.model)}


@router.delete("/{key_id}", status_code=204, operation_id="revoke_model_key",
               summary="Revoke a provider key",
               description=(
                   "Revokes one of your keys. A key that belongs to someone "
                   "else and a key that never existed answer alike. "
                   "404 not_found."))
def отозвать(key_id: str, s: SessionDep, user: CurrentUser) -> Response:
    """Отозвать свой ключ. Чужой и несуществующий — одинаково `404`."""
    service.revoke(s, user.id, key_id)
    return Response(status_code=204)


__all__ = ["router", "ModelKeyIn", "InkKeysIn", "ModelIn"]
