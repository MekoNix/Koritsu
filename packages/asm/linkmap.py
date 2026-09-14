"""linkmap.py — `.map` TLINK: сегменты образа и точка входа.

Первая таблица карты (она есть при любых ключах, кроме `/x`):

     Start  Stop   Length Name               Class

     00000H 00010H 00011H _TEXT              CODE
     00012H 00017H 00006H _DATA              DATA
     00020H 0011FH 00100H STACK              STACK

    Program entry point at 0000:0000

Адреса — линейные смещения от начала образа. Подробная карта (`/s`) и списки публичных
имён (`/m`) идут дальше в другом формате и сюда не попадают: их строки таблице не
соответствуют.
"""
from __future__ import annotations

import re

from .model import Segment

_ROW = re.compile(
    r"^\s*(?P<start>[0-9A-F]{5,8})H\s+(?P<stop>[0-9A-F]{5,8})H\s+(?P<len>[0-9A-F]{5,8})H"
    r"\s+(?P<name>\S+)(?:\s+(?P<cls>\S+))?\s*$", re.I)
_ENTRY = re.compile(r"Program entry point at\s+(?P<seg>[0-9A-F]{4}):(?P<off>[0-9A-F]{4})", re.I)


def parse_map(text: str) -> tuple[list[Segment], tuple[int, int] | None]:
    segments: list[Segment] = []
    entry = None
    seen_table = False
    for raw in text.splitlines():
        if raw.lower().lstrip().startswith(("detailed map", "address")):
            if seen_table:
                break
        m = _ROW.match(raw)
        if m:
            seen_table = True
            segments.append(Segment(name=m.group("name").upper(),
                                    cls=(m.group("cls") or "").upper(),
                                    start=f"{int(m.group('start'), 16):05X}",
                                    length=f"{int(m.group('len'), 16):05X}"))
            continue
        e = _ENTRY.search(raw)
        if e:
            entry = (int(e.group("seg"), 16), int(e.group("off"), 16))
    return segments, entry


__all__ = ["parse_map"]
