"""model.py — модели набора, потолки и ключи карточек.

**Ключ карточки** — то, к чему привязан прогресс человека. Если у карточки есть `id`, ключ —
этот id: автор сам обещает, что карточка та же, даже когда формулировка поменялась. Без id
ключ — `q:` + первые 16 знаков sha1 от нормализованного вопроса (NFC, невидимые символы
убраны, пробелы схлопнуты, регистр снят). Вопрос берётся целиком: две карточки «Найдите
первообразную» с разными формулами — разные карточки.

Регистр снимается намеренно: «Что такое предел?» и «что такое предел?» — один вопрос, а
формула, отличающаяся только регистром переменной, в двух карточках одного набора почти
всегда опечатка. Совпадение показывается проблемой с подсказкой дать карточкам `id`.

**id вида `q-<16 hex>`** выдаёт сам тренажёр, когда отдаёт набор файлом: у карточки без id
ключ `q:…` в id не помещается (двоеточие в id запрещено), поэтому при записи двоеточие
становится дефисом, а при чтении — обратно. Скачанный и загруженный заново файл сохраняет
прогресс. Такой id — не авторский: карточка с ним читается как карточка без id
(`explicit_id=False`), и запись с чтением дают тот же набор.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass

ORDERS = ("file", "random", "topic_seq", "topic_random", "topics_shuffled")
INCLUDE = ("all", "unknown", "wrong")

FILE_BYTES = 5 * 1024 * 1024
MAX_CARDS = 10_000
MAX_TOPICS = 500
TEXT_LIMIT = 20_000
TITLE_LIMIT = 200
DESCRIPTION_LIMIT = 2_000

DEFAULT_TITLE = "Набор карточек"
DEFAULT_LANGUAGE = "ru"

FORMAT = "koritsu.cards"
FORMAT_VERSION = 1

ID_RE = re.compile(r"[A-Za-z0-9._-]{1,64}")
_GENERATED_ID = re.compile(r"q-([0-9a-f]{16})")
LANGUAGE_RE = re.compile(r"[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})?")


@dataclass(frozen=True)
class Topic:
    id: str             # slug от заголовка, уникальный в наборе
    title: str


@dataclass(frozen=True)
class Card:
    key: str            # id из {#…} или 'q:' + sha1(нормализованный вопрос)[:16]
    q: str
    a: str
    topic: str | None = None    # Topic.id; None — карточка без темы
    note: str | None = None
    explicit_id: bool = False


@dataclass(frozen=True)
class Defaults:
    session_size: int = 20      # 0 — все карточки
    order: str = "topic_random"
    topics: list[str] | None = None     # Topic.id; None — все темы
    include: str = "all"
    repeat_wrong: bool = True


@dataclass(frozen=True)
class CardSet:
    title: str
    description: str
    language: str
    topics: list[Topic]
    cards: list[Card]
    defaults: Defaults


@dataclass(frozen=True)
class Problem:
    line: int | None    # строка источника с 1: битый JSON и CSV; None — строк нет
    code: str           # 'empty_answer'
    text: str           # 'у карточки нет ответа'
    card: int | None = None     # номер карточки в источнике с 0; проблема отклоняет эту карточку
    path: str | None = None     # путь JSON: 'cards[12].a', 'defaults.order'; None — пути нет
    column: int | None = None   # столбец в строке `line` с 1: битый JSON; None — столбца нет


# ── текст ────────────────────────────────────────────────────────────────────

_INVISIBLE = dict.fromkeys(map(ord, "\u200b\u200c\u200d\u2060\ufeff"), None)


def normalize_input(text: str) -> str:
    """Вход любого источника: без BOM, концы строк `\\n`, NFC."""
    if text.startswith("\ufeff"):
        text = text[1:]
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return unicodedata.normalize("NFC", text)


def normalize_question(q: str) -> str:
    t = unicodedata.normalize("NFC", q).translate(_INVISIBLE)
    t = " ".join(t.split())
    return unicodedata.normalize("NFC", t.casefold())


def question_key(q: str) -> str:
    return "q:" + hashlib.sha1(normalize_question(q).encode("utf-8")).hexdigest()[:16]


def id_to_key(card_id: str) -> str:
    m = _GENERATED_ID.fullmatch(card_id)
    return "q:" + m.group(1) if m else card_id


def key_to_id(key: str) -> str:
    return "q-" + key[2:] if key.startswith("q:") else key


def generated_id(card_id: str) -> bool:
    """id выдан тренажёром (`q-<16 hex>`), а не автором."""
    return bool(_GENERATED_ID.fullmatch(card_id))


def same_text(a: str | None, b: str | None) -> bool:
    """Тексты равны с точностью до NFC и пробелов; регистр значим."""
    def norm(s: str | None) -> str:
        return " ".join(unicodedata.normalize("NFC", s or "").split())
    return norm(a) == norm(b)


def title_norm(title: str) -> str:
    return " ".join(unicodedata.normalize("NFC", title).split()).casefold()


_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh", "з": "z",
    "и": "i", "й": "i", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r",
    "с": "s", "т": "t", "у": "u", "ф": "f", "х": "h", "ц": "c", "ч": "ch", "ш": "sh",
    "щ": "sch", "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}


def slug(title: str) -> str:
    """Латинский slug заголовка темы: id уезжает в адреса и JSON."""
    t = unicodedata.normalize("NFC", title).lower()
    t = "".join(_TRANSLIT.get(ch, ch) for ch in t)
    t = unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode("ascii")
    t = re.sub(r"[^a-z0-9]+", "-", t).strip("-")[:48].strip("-")
    if not t:
        t = "t-" + hashlib.sha1(title.encode("utf-8")).hexdigest()[:8]
    return t


def number(n: int) -> str:
    return f"{n:,}".replace(",", " ")
