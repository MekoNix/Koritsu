"""
_image — разбор картинок: размеры плюс распознанный текст.

Модели картинку не отдаём — ни исходную, ни уменьшенную. У пользователя их
бывает по полсотни, и зрение на таком объёме стоит слишком дорого. Берём то,
что можно получить бесплатно: размеры и OCR. Сама картинка остаётся файлом в
хранилище и вставляется в отчёт по идентификатору.
"""
from __future__ import annotations

import io

from PIL import Image as PILImage

from . import ocr
from ._text import detect_lang
from .model import KIND_IMAGE, UNIT_LINE, Parsed


def size_px(data: bytes) -> tuple[int, int]:
    """Размеры картинки в пикселях; (0, 0), если формат не читается."""
    try:
        with PILImage.open(io.BytesIO(data)) as im:
            return im.size
    except Exception:                      # битый или незнакомый растр — не повод падать
        return (0, 0)


def parse_image(data: bytes, ext: str = ".png", do_ocr: bool = True) -> Parsed:
    """
    Картинка: размеры в extra, распознанный текст — строками (единица «строка»,
    чтобы кусок из длинного скана можно было запросить по номерам строк).
    Без tesseract материал всё равно сохраняется, но получает честную пометку.
    """
    w, h = size_px(data)
    extra: dict = {"width": w, "height": h}
    notes: list[str] = []
    units: list[str] = []
    lang = ""

    if not do_ocr:
        notes.append("текст не распознавался")
    elif not ocr.available():
        notes.append(ocr.NOT_INSTALLED)
    else:
        text = ocr.recognize(data, ext=ext)
        units = [ln for ln in text.splitlines() if ln.strip()]
        if units:
            lang = detect_lang(text)
        else:
            notes.append(ocr.NOT_RECOGNIZED)

    return Parsed(kind=KIND_IMAGE, unit=UNIT_LINE, units=units, lang=lang,
                  notes=notes, extra=extra)
