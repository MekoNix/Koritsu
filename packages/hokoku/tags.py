"""
tags — синтаксис тегов и их поиск в документе.

  {{ключ}}               {{ключ:Подсказка для пользователя}}
Ключ: буквы (в т.ч. кириллица), цифры, `_`, `.`, `-`; без пробелов.
Зарезервировано на будущее (1.5): `{{ключ|умолчание}}`, `{{#if …}}`, `{{#each …}}` —
парсер их распознаёт как «служебные» и не считает обычными тегами.
"""
from __future__ import annotations

import re
import unicodedata

from .model import Tag


def norm_key(key: str) -> str:
    """Ключ тега в NFC: Word и macOS могут писать «й»/«ё» разложенными (NFD)."""
    return unicodedata.normalize("NFC", key.strip())

TAG_RE = re.compile(r"\{\{\s*(?P<key>[^\s{}:|#/]+)\s*(?::(?P<label>[^{}]*))?\}\}")
DIRECTIVE_RE = re.compile(r"\{\{\s*[#/|][^{}]*\}\}")


def parse_tag(text: str) -> tuple[str, str] | None:
    m = TAG_RE.fullmatch(text.strip())
    if not m:
        return None
    return m.group("key"), (m.group("label") or m.group("key")).strip()


def find_tags(text: str) -> list[re.Match]:
    return list(TAG_RE.finditer(text))


def extract_tags(template) -> list[Tag]:
    """Все теги документа в порядке появления, без повторов (первое место — в `where`)."""
    from .walker import iter_paragraphs, marked_paragraphs, open_document
    doc = open_document(template)
    seen: dict[str, Tag] = {}
    hot = marked_paragraphs(doc, ("{{",))
    for loc in iter_paragraphs(doc):
        if loc.paragraph._p not in hot:
            continue
        text = loc.text()
        if "{{" not in text:
            continue
        for m in TAG_RE.finditer(text):
            key = norm_key(m.group("key"))
            label = (m.group("label") or "").strip()
            tag = seen.get(key)
            if tag is None:
                tag = seen[key] = Tag(key=key, label=label or key, where=loc.where)
            elif label and tag.label == key:
                tag.label = label                     # подсказка может стоять не в первом месте
            tag.count += 1
            if loc.where not in tag.places:
                tag.places.append(loc.where)
    return list(seen.values())
