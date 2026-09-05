"""
keys — ключи моделей: свой ключ человека и общий ключ владельца.

И свой ключ, и общий по подписке. Свой ключ лежит на диске
зашифрованным секретом сервера, расшифровывается только в момент вызова
поставщика, никогда не пишется в журнал и не отдаётся клиенту — человек видит
последние четыре знака. Общий ключ владельца берётся из окружения
(`KORITSU_PROVIDER_KEY_<PROVIDER>`) и тратится по подписке с лимитами через
`llm.journal`.

    таблица  model_keys        id, user_id, provider, ciphertext, last4,
                               created_at, updated_at, revoked_at
    схема    HKDF-SHA256(settings.secret, соль пакета) → Fernet, метка `v1:`
    маршруты /api/keys         список, поставщики, завести, отозвать

Две функции, которые нужны соседям:

    keys.secret_for(session, settings, user_id, provider) -> str | None
        свой ключ текстом. **Единственное место расшифровки во всей службе.**

    keys.resolve_key(settings, session, user_id, provider) -> str | None
        чем платим: свой ключ, иначе общий, иначе ничем.

Правило, которое этот подпакет держит и за всех остальных: **ключ не попадает в
журнал ни в каком виде** — ни текстом, ни шифртекстом, ни куском. Сообщения об
ошибках здесь называют поставщика и идентификатор строки, но никогда не
показывают содержимое; на это есть тест, а не обещание.
"""
from .crypto import КлючНеЧитается, зашифровать, расшифровать, хвост
from .models import ModelKey
from .service import (add_key, check_provider, common_key, list_keys, providers,
                      resolve_key, revoke, secret_for, source_of)
from .routes import router

__all__ = ["ModelKey", "router", "secret_for", "resolve_key", "common_key",
           "source_of", "add_key", "revoke", "list_keys", "providers",
           "check_provider", "зашифровать", "расшифровать", "хвост",
           "КлючНеЧитается"]
