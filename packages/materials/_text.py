"""
_text — разбор текстовых материалов и общие приёмы работы со строками.

Текст и разметка (`.md`, `.txt`, `.csv`, исходники любых языков) берутся как
есть: содержимое не переписывается, только разбивается на строки — строка тут
единица нумерации, по ней потом строится якорь «файл X, строки 40–80».
"""
from __future__ import annotations

import re

from .model import (KIND_TEXT, LANG_CYRILLIC, LANG_LATIN, LANG_MIXED, UNIT_LINE,
                    Parsed)

# Кодировки по очереди: UTF-8 — норма, cp1251 — старые русские выгрузки из Windows.
_ENCODINGS = ("utf-8", "cp1251")

_CYRILLIC = re.compile(r"[а-яёА-ЯЁ]")
_LATIN = re.compile(r"[a-zA-Z]")


def decode(data: bytes) -> str:
    """Байты → текст. Последняя попытка — с заменой битых знаков, чтобы не падать."""
    for enc in _ENCODINGS:
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def looks_like_text(data: bytes, probe: int = 4096) -> bool:
    """
    Похоже ли на текст: нет нулевых байтов и почти нет управляющих знаков.
    Нужно для файлов с незнакомым расширением — расширение врёт чаще, чем
    содержимое, а `.pas` или `.f90` перечислять в списках можно бесконечно.
    """
    head = data[:probe]
    if not head:
        return False
    if b"\x00" in head:
        return False
    text = decode(head)
    printable = sum(1 for ch in text if ch.isprintable() or ch in "\n\r\t")
    return printable / len(text) > 0.95


def detect_lang(text: str, probe: int = 4000) -> str:
    """
    Язык текста грубо: `cyrillic`, `latin` или `mixed` — код, а не подпись
    (значение уезжает в карточку службы, подписи лежат в `model.LANG_WORDS`).
    Настоящий определитель языка тут не нужен — это подсказка модели, а не
    классификация.
    """
    head = text[:probe]
    cyr = len(_CYRILLIC.findall(head))
    lat = len(_LATIN.findall(head))
    if cyr == 0 and lat == 0:
        return ""
    if cyr > lat * 3:
        return LANG_CYRILLIC
    if lat > cyr * 3:
        return LANG_LATIN
    return LANG_MIXED


def first_lines(units: list[str], count: int = 3, width: int = 90) -> list[str]:
    """
    Первые осмысленные строки: пустые и декоративные (`---`, `===`, `###`)
    пропускаем — в карточке от них нет пользы, а место они занимают.
    """
    out: list[str] = []
    for raw in units:
        for line in raw.splitlines() or [raw]:
            s = " ".join(line.split())
            if not s or not re.search(r"\w", s.replace("_", "")):
                continue
            if len(s) > width:
                s = s[:width - 1].rstrip() + "…"
            out.append(s)
            if len(out) >= count:
                return out
    return out


def parse_text(data: bytes, note: str = "") -> Parsed:
    """Текстовый материал: строки как есть, единица нумерации — строка."""
    text = decode(data)
    lines = text.splitlines()
    return Parsed(kind=KIND_TEXT, unit=UNIT_LINE, units=lines,
                  lang=detect_lang(text), notes=[note] if note else [])
