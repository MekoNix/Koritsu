"""
catalog — какие модели есть у поставщика. Спрашиваем его самого.

Пресет `llm` знает одно имя модели — то, которым работали до появления выбора.
Имён у поставщика больше, они меняются без предупреждения, и держать их список
в коде означало бы узнавать переименование отказом на боевом прогоне. Поэтому
список спрашивается у поставщика ключом самого человека:

    GET <base_url>/v1/models     →  {"data": [{"id": …, "display_name": …}]}

Отвечают так оба протокола: openai-совместимые (`deepseek`, `openrouter`) и
`anthropic`. У кого пути нет (`cli`), список не спрашивается вовсе.

**Ключ нужен и здесь.** Список моделей поставщики отдают только по ключу, и это
кстати: ответ `auth` на этот запрос — ровно тот случай, ради которого человек
пришёл в настройки, и сказать ему «ключ не принят» надо здесь, а не через
десять минут посреди прогона.

**Запасной список — имя из пресета.** Поставщик не ответил (сеть, лимит, ключ)
— отдаём то единственное, что знаем наверняка: модель пресета, помеченную
`source: "preset"`. Пустой список вместо неё оставил бы человека без выбора
вовсе, хотя рабочая модель у него есть.

**Кэш на полчаса, в памяти процесса.** Список меняется у поставщика раз в
месяцы, а экран настроек открывают подряд; полчаса — это «не ходить на каждый
рендер», и при этом человеку не надо ждать сутки, чтобы увидеть новую модель.
В памяти, а не в базе: кэш переживать перезапуск не обязан, а таблица ради него
— это миграция ради удобства.

Ключ кэша — пара «человек и поставщик», а не один поставщик: ключи у людей
разные, и у поставщика вроде OpenRouter список зависит от того, чей ключ
спросил.
"""
from __future__ import annotations

import contextlib
import os
import time

from sqlalchemy.orm import Session

import llm

from ..log import беды
from ..settings import Settings
from . import service

# Сколько живёт ответ поставщика в памяти процесса.
КЭШ_С = 30 * 60

# Имя переменной окружения, под которым ключ живёт на время одного запроса.
# Своё и одно — по той же причине, что у прогона (`runs/model.ИМЯ_КЛЮЧА`): два
# имени означали бы два места, где ключ можно забыть снять.
ИМЯ_КЛЮЧА = "KORITSU_CATALOG_KEY"

# {(user_id, provider): (когда, {"models": [...], "source": "provider"})}
_кэш: dict[tuple[str, str], tuple[float, dict]] = {}


def сбросить_кэш() -> None:
    """Забыть всё запомненное. Зовут тесты и смена ключа."""
    _кэш.clear()


def забыть(user_id: str, provider: str) -> None:
    """Забыть один ответ: ключ сменился, и список мог смениться с ним."""
    _кэш.pop((user_id, provider), None)


def models(settings: Settings, s: Session, user_id: str, provider: str,
           *, refresh: bool = False) -> dict:
    """Модели поставщика для этого человека.

        {"models": [{"id": "claude-opus-5", "title": "Claude Opus 5"}],
         "source": "provider" | "preset", "note": ""}

    `source` говорит, откуда список: `provider` — сказал сам поставщик,
    `preset` — не ответил, и это имя из пресета. Разница видна человеку: под
    списком из пресета честно стоит «поставщик не ответил», а не молчание,
    выглядящее как полный список.

    `refresh=True` идёт мимо кэша: кнопка «обновить» рядом со списком обязана
    ходить на самом деле, иначе человек нажимает её и не понимает, почему
    ничего не изменилось.
    """
    имя = service.check_provider(provider)
    if service.kind_of(имя) != service.МОДЕЛЬ:
        # Чернила не модель: у распознавания рукописи выбирать нечего, и
        # спрашивать у него список значило бы обещать экрану то, чего нет.
        return {"models": [], "source": "preset", "note": "ink"}

    if not refresh:
        лежит = _кэш.get((user_id, имя))
        if лежит and time.monotonic() - лежит[0] < КЭШ_С:
            return лежит[1]

    ключ = service.resolve_key(settings, s, user_id, имя)
    ответ = _спросить(settings, имя, ключ) if ключ else {
        "models": _из_пресета(имя), "source": "preset", "note": "no_key"}
    _кэш[(user_id, имя)] = (time.monotonic(), ответ)
    return ответ


def _спросить(settings: Settings, provider: str, ключ: str) -> dict:
    """Сходить к поставщику. Любая беда — запасной список, а не отказ.

    Отказывать здесь нечем и незачем: экран настроек открывают, чтобы завести
    ключ и выбрать модель, и `502` вместо списка оставил бы человека без обоих
    дел. Причина беды при этом не теряется — она едет полем `note`, и экран
    пишет её словами.
    """
    spec = _пресет(settings, provider)
    backend = llm.backends.make(spec)
    путь = getattr(backend, "models_path", "")
    if not путь:
        return {"models": _из_пресета(provider), "source": "preset",
                "note": "no_catalog"}
    with _ключ_в_окружении(spec, ключ):
        try:
            payload, _rid = backend.transport().get_json(
                путь, endpoint_id=spec.id)
        except llm.LlmError as беда:
            # Ни ключа, ни текста ответа поставщика в журнал: `kind` — это
            # слово из закрытого перечисления, и его достаточно.
            беды.warning("список моделей %s не получен: %s", provider, беда.kind)
            return {"models": _из_пресета(provider), "source": "preset",
                    "note": беда.kind}
        except Exception as беда:                     # noqa: BLE001
            беды.warning("список моделей %s не получен: %s", provider,
                         type(беда).__name__)
            return {"models": _из_пресета(provider), "source": "preset",
                    "note": "error"}
    модели = _разобрать(payload)
    if not модели:
        return {"models": _из_пресета(provider), "source": "preset",
                "note": "empty"}
    return {"models": модели, "source": "provider", "note": ""}


def _разобрать(payload: dict) -> list[dict]:
    """`{"data": [...]}` → `[{"id", "title"}]`, по порядку поставщика.

    Порядок не трогаем: поставщик ставит вперёд то, что считает нужным (у
    Anthropic — свежие модели), и алфавит здесь был бы нашим мнением поверх его.

    Человеческое имя зовут по-разному: `display_name` у Anthropic, `name` у
    OpenRouter, у остальных его нет вовсе — тогда имя и есть идентификатор.
    """
    строки = (payload or {}).get("data") or []
    модели = []
    for m in строки:
        if not isinstance(m, dict):
            continue
        имя = str(m.get("id") or "").strip()
        if not имя:
            continue
        титул = str(m.get("display_name") or m.get("name") or имя).strip()
        модели.append({"id": имя, "title": титул})
    return модели


def _из_пресета(provider: str) -> list[dict]:
    """Что знаем без поставщика: модель пресета и соседи по его таблице.

    У OpenRouter таблица моделей в пресете есть (`OPENROUTER_МОДЕЛИ` — те, для
    которых заполнены цены и окно), у остальных известно одно имя. Больше
    выдумывать нечего, и выдумывать нельзя: имя, которого у поставщика нет,
    человек выберет и получит отказ на прогоне.
    """
    try:
        spec = llm.presets.make(provider)
    except KeyError:
        return []
    имена = [spec.model] if spec.model else []
    таблица = getattr(llm.presets, "OPENROUTER_МОДЕЛИ", {}) if provider == "openrouter" else {}
    for имя in таблица:
        if имя not in имена:
            имена.append(имя)
    return [{"id": имя, "title": имя} for имя in имена]


def _пресет(settings: Settings, provider: str):
    """Пресет поставщика с адресом стенда, если он подменён.

    Подмена — та же, что у прогона (`runs/model.endpoint`): в `dev` адрес
    поставщика перекрывает `KORITSU_LLM_BASE_URL_<ПРЕСЕТ>`, в `prod` она мертва.
    Спрашивать список у настоящего поставщика, когда прогоны идут на поддельный
    сервер стенда, значило бы показывать человеку не тот список.
    """
    подмена = settings.llm_base_url(provider)
    spec = llm.presets.make(provider, **({"base_url": подмена} if подмена else {}))
    spec.id = f"catalog-{provider}"
    spec.api_key_env = ИМЯ_КЛЮЧА
    # Запасной путь пресета (`~/.config/koritsu/<поставщик>.key`) снимаем: на
    # сервере такого файла быть не должно, а если он там окажется, список
    # человека молча поехал бы на чужом ключе.
    spec.api_key_file = None
    return spec


@contextlib.contextmanager
def _ключ_в_окружении(spec, ключ: str):
    """Ключ в переменной окружения на время одного запроса и ни секундой дольше.

    Тем же способом, что и прогон: `EndpointSpec.resolve_key()` читает
    переменную на каждый запрос намеренно — ключ не кэшируется в объекте,
    потому что объект попадает в логи и в repr.
    """
    прежнее = os.environ.get(spec.api_key_env)
    os.environ[spec.api_key_env] = ключ
    try:
        yield
    finally:
        if прежнее is None:
            os.environ.pop(spec.api_key_env, None)
        else:
            os.environ[spec.api_key_env] = прежнее


__all__ = ["models", "сбросить_кэш", "забыть", "КЭШ_С"]
