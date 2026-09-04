"""
service — что можно делать с ключами моделей и где ключ снова становится текстом.

Решение владельца §3: **и свой, и общий**. У человека может быть собственный
ключ поставщика; если его нет, работает общий ключ владельца сервиса (по
подписке, с лимитами через `llm.journal`). Оба пути сходятся в одной функции —
`resolve_key`, — и это не удобство, а условие: два места, решающих «чьим ключом
платим», разошлись бы, и разошлись бы в сторону «бесплатно всем».

    resolve_key(settings, session, user_id, provider)
        свой ключ  → secret_for(...)               строка из базы, расшифрованная
        иначе      → KORITSU_PROVIDER_KEY_<PROVIDER>   общий ключ владельца
        иначе      → None                          платить нечем

**Расшифровка живёт ровно в одном месте** — `secret_for`. Это и есть исполнение
§3 («расшифровывать в памяти только в момент вызова поставщика»): чтобы вызвать
поставщика, надо позвать эту функцию, и другого пути к тексту ключа в службе
нет. Никакой маршрут её не зовёт: наружу уходит `last4`, и только он.

**В журнал ключ не попадает ни в каком виде** — ни текстом, ни шифртекстом.
Отсюда и правило про сообщения бед: они говорят про поставщика и про
пользователя, но никогда не показывают строку. Это проверяется тестом, а не
обещается.

**Список поставщиков — те пресеты `llm`, у которых объявлен `api_key_env`**
(решение главной сессии 2026-09-03). Не весь `PRESETS`: `claude_cli_proba` зовёт
локальную команду и ключа не имеет, и предлагать человеку завести ключ для него
значило бы предлагать бессмыслицу. Список считается из пресетов, а не пишется
руками, чтобы новый пресет появлялся в настройках сам.
"""
from __future__ import annotations

import os
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

import llm

from ..db import now
from ..errors import ApiError
from ..log import беды
from ..settings import Settings
from . import crypto
from .models import ModelKey

UNKNOWN_PROVIDER = "unknown_provider"
INVALID_KEY = "invalid_key"
NOT_FOUND = "not_found"

# Переменная окружения с общим ключом владельца: `KORITSU_PROVIDER_KEY_DEEPSEEK`.
ОБЩИЙ_ПРЕФИКС = "KORITSU_PROVIDER_KEY_"

# Что вообще может быть ключом поставщика: печатные знаки без пробелов.
# Проверка от опечатки (скопировали вместе с переводом строки), а не от злого
# умысла: настоящую пригодность ключа покажет первый вызов поставщика.
КЛЮЧ_RE = re.compile(r"\A[\x21-\x7e]{8,512}\Z")


def providers() -> tuple[str, ...]:
    """Имена пресетов, для которых ключ вообще имеет смысл. По алфавиту."""
    годные = []
    for имя, фабрика in llm.presets.PRESETS.items():
        try:
            spec = фабрика()
        except Exception:                                    # noqa: BLE001
            continue                     # сломанный пресет не роняет настройки
        if getattr(spec, "api_key_env", None):
            годные.append(имя)
    return tuple(sorted(годные))


def check_provider(provider: str, *, where: str = "body.provider") -> str:
    """Имя поставщика или отказ `400 unknown_provider`.

    Список в тексте ошибки называется намеренно: это не секрет (пресеты видны
    в настройках аккаунта), а клиенту иначе нечего показать человеку, кроме
    «нет».
    """
    имя = (provider or "").strip().lower()
    годные = providers()
    if имя not in годные:
        raise ApiError(UNKNOWN_PROVIDER,
                       f"Unknown provider; expected one of: {', '.join(годные)}",
                       400, where=where)
    return имя


# ── свои ключи ───────────────────────────────────────────────────────────────

def list_keys(s: Session, user_id: str, *,
              include_revoked: bool = False) -> list[ModelKey]:
    """Ключи человека, новые сверху. Отозванные — по просьбе.

    По умолчанию их нет: список в настройках показывает, чем сейчас можно
    платить, а история отзывов — другой разговор и другой экран.
    """
    запрос = select(ModelKey).where(ModelKey.user_id == user_id)
    if not include_revoked:
        запрос = запрос.where(ModelKey.revoked_at.is_(None))
    return list(s.scalars(запрос.order_by(ModelKey.created_at.desc())))


def add_key(s: Session, settings: Settings, user_id: str, provider: str,
            ключ: str) -> ModelKey:
    """Завести ключ. Прежний живой ключ того же поставщика отзывается.

    Отзыв прежнего, а не два живых рядом: «какой из двух сейчас работает» —
    вопрос, на который у человека нет ответа, а у нас нет причины его задавать.
    Прежний остаётся строкой с `revoked_at`, то есть история сохраняется.

    Сам ключ в объект не кладётся и из этой функции не возвращается: на выходе
    строка базы, у которой есть только шифртекст и `last4`.
    """
    имя = check_provider(provider)
    очищенный = (ключ or "").strip()
    if not КЛЮЧ_RE.match(очищенный):
        # Про сам ключ в сообщении ни знака — оно уедет в ответ и в журнал
        # клиента.
        raise ApiError(INVALID_KEY,
                       "Provider key must be 8 to 512 printable characters "
                       "without spaces", 400, where="body.key")

    for прежний in list_keys(s, user_id):
        if прежний.provider == имя:
            прежний.revoked_at = now()

    строка = ModelKey(user_id=user_id, provider=имя,
                      ciphertext=crypto.зашифровать(settings.secret, очищенный),
                      last4=crypto.хвост(очищенный))
    s.add(строка)
    s.flush()                    # `id` и `created_at` — до ответа клиенту
    return строка


def revoke(s: Session, user_id: str, key_id: str) -> ModelKey:
    """Отозвать свой ключ. Чужой и несуществующий — одинаково `404`.

    Одинаково намеренно: `403` на чужой идентификатор сообщал бы, что такой ключ
    есть, то есть отвечал бы на вопрос, задавать который не позволено (§3).
    Повторный отзыв — не беда: строка уже отозвана, отвечаем ей же.
    """
    строка = s.get(ModelKey, key_id)
    if строка is None or строка.user_id != user_id:
        raise ApiError(NOT_FOUND, "Key not found", 404, where="path.key_id")
    if строка.revoked_at is None:
        строка.revoked_at = now()
    return строка


# ── расшифровка: одно место на всю службу ────────────────────────────────────

def secret_for(s: Session, settings: Settings, user_id: str,
               provider: str) -> str | None:
    """Ключ этого человека для этого поставщика — текстом. `None`, если нет.

    **Единственное место службы, где ключ снова становится текстом.** Зовут её из
    места вызова поставщика (ночь 2), результат живёт в локальной переменной и
    не кладётся ни в объект, ни в журнал, ни в ответ.

    Отозванный ключ не возвращается никогда — на то он и отозван. Нечитаемый
    (сменили `KORITSU_SECRET`, испортили строку) — тоже `None`, но с записью в
    журнал бед: молчаливое «ключа нет» в этом случае увело бы человека искать
    беду в настройках поставщика вместо настроек службы.

    Порядок аргументов отличается от объявленного в задании (`session, user_id,
    provider`) на один: расшифровка невозможна без `settings.secret`, а читать
    окружение по месту вместо настроек — ровно то, что запрещает `settings.py`.
    """
    строка = s.scalars(
        select(ModelKey)
        .where(ModelKey.user_id == user_id, ModelKey.provider == provider,
               ModelKey.revoked_at.is_(None))
        .order_by(ModelKey.created_at.desc())).first()
    if строка is None:
        return None
    try:
        return crypto.расшифровать(settings.secret, строка.ciphertext)
    except crypto.КлючНеЧитается as беда:
        # Идентификатор строки — можно (по нему человек найдёт ключ в настройках
        # и заведёт заново), шифртекст — нельзя ни при каких обстоятельствах.
        беды.error("ключ %s (%s) не расшифровался: %s", строка.id,
                   строка.provider, беда)
        return None


def common_key(provider: str) -> str | None:
    """Общий ключ владельца из окружения: `KORITSU_PROVIDER_KEY_<PROVIDER>`.

    В `Settings` ему не место: там список закрыт, а поставщиков добавляют, не
    пересобирая службу. Зато правило чтения то же — пустая строка это «не
    задано», а не «пустой ключ».
    """
    значение = (os.environ.get(ОБЩИЙ_ПРЕФИКС + provider.upper()) or "").strip()
    return значение or None


def resolve_key(settings: Settings, s: Session, user_id: str,
                provider: str) -> str | None:
    """Чем платим за этот вызов: своим ключом, общим или ничем.

    Свой вперёд общего намеренно. Человек, заведший свой ключ, платит
    поставщику сам, и тратить на него общую квоту владельца было бы и дороже
    нам, и неожиданно ему: он завёл ключ ровно затем, чтобы расход был виден в
    его кабинете у поставщика.

    `None` — «платить нечем»: вызывающий обязан отказать человеку внятно
    («заведите ключ или включите подписку»), а не звать поставщика без ключа и
    показывать его `401`.
    """
    свой = secret_for(s, settings, user_id, provider)
    if свой:
        return свой
    return common_key(provider)


def source_of(settings: Settings, s: Session, user_id: str,
              provider: str) -> str:
    """Откуда взялся бы ключ: `own`, `shared` или `none`. Без самого ключа.

    Нужно интерфейсу и журналу расхода: показать «этот прогон пошёл на общий
    ключ» можно и нужно, а показать сам ключ — нельзя.
    """
    if secret_for(s, settings, user_id, provider):
        return "own"
    return "shared" if common_key(provider) else "none"


__all__ = ["providers", "check_provider", "list_keys", "add_key", "revoke",
           "secret_for", "common_key", "resolve_key", "source_of",
           "UNKNOWN_PROVIDER", "INVALID_KEY", "NOT_FOUND", "ОБЩИЙ_ПРЕФИКС"]
