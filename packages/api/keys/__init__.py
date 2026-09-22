"""
keys — ключи поставщиков: свой ключ человека и выбранная им модель.

Свой ключ лежит на диске
зашифрованным секретом сервера, расшифровывается только в момент вызова
поставщика, никогда не пишется в журнал и не отдаётся клиенту — человек видит
последние четыре знака. Общего ключа службы нет: прогон идёт на ключе того, кто его завёл, и ни на
чьём другом — расход обязан быть виден там, где его можно проверить.

    таблица  model_keys        id, user_id, provider, ciphertext, last4,
                               model, created_at, updated_at, revoked_at
    схема    HKDF-SHA256(settings.secret, соль пакета) → Fernet, метка `v1:`
    маршруты /api/keys         список, поставщики, завести, отозвать

Две функции, которые нужны соседям:

    keys.secret_for(session, settings, user_id, provider) -> str | None
        свой ключ текстом. **Единственное место расшифровки во всей службе.**

    keys.resolve_key(settings, session, user_id, provider) -> str | None
        чем платим: свой ключ или ничем.

Правило, которое этот подпакет держит и за всех остальных: **ключ не попадает в
журнал ни в каком виде** — ни текстом, ни шифртекстом, ни куском. Сообщения об
ошибках здесь называют поставщика и идентификатор строки, но никогда не
показывают содержимое; на это есть тест, а не обещание.
"""
from .crypto import КлючНеЧитается, зашифровать, расшифровать, хвост
from .models import ModelKey
from . import catalog
from .service import (add_key, check_provider, has_key, list_keys, model_of,
                      model_providers, providers, resolve_key, revoke,
                      secret_for, set_model)
from .routes import router

__all__ = ["ModelKey", "router", "secret_for", "resolve_key", "has_key",
           "add_key", "revoke", "list_keys", "providers", "model_providers",
           "model_of", "set_model", "catalog", "check_provider",
           "зашифровать", "расшифровать", "хвост", "КлючНеЧитается"]
