"""
_pdf — разбор PDF: текст по страницам, встроенные картинки, таблицы.

PDF — источник, из которого тащат содержимое, а не единый ком текста. Поэтому
разбор даёт три вещи по отдельности:

  * текст с номерами страниц — страница здесь единица нумерации и якоря;
  * встроенные картинки — самостоятельные материалы со ссылкой на страницу,
    чтобы схему с четвёртой страницы можно было вставить в отчёт;
  * таблицы — только те, что извлеклись осмысленно (две строки и непустые ячейки).

Сканированный PDF (текстового слоя нет) прогоняется через OCR постранично.
Без tesseract разбор не падает: страницы остаются пустыми, а материал получает
честную пометку.
"""
from __future__ import annotations

import contextlib
import io
import os

import pymupdf

from . import ocr
from ._text import detect_lang
from .model import KIND_PDF, UNIT_PAGE, Derived, Parsed

# Меньше этого картинку считаем украшением (линейка, логотип, маркер списка).
MIN_IMAGE_SIDE = 48
# Меньше этого знаков на странице — текстового слоя на ней нет (пустая или скан).
SCAN_MIN_CHARS = 10
# Разрешение отрисовки страницы под OCR: 200 dpi — компромисс скорости и качества.
OCR_DPI = 200


def _page_tables(page) -> list[list[list[str]]]:
    """
    Таблицы со страницы. pymupdf на этом месте любит писать подсказку в stdout —
    глушим, чтобы разбор не сорил в вывод программы.
    """
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            found = page.find_tables()
        tables = list(getattr(found, "tables", ()))
    except Exception:                       # разметка таблиц — эвристика, она вправе не сработать
        return []
    out = []
    for t in tables:
        try:
            rows = [["" if c is None else str(c).strip() for c in row] for row in t.extract()]
        except Exception:
            continue
        # «Осмысленно» — это хотя бы две строки и хоть что-то в ячейках.
        if len(rows) >= 2 and any(any(c for c in row) for row in rows):
            out.append(rows)
    return out


def parse_pdf(data: bytes, name: str = "документ.pdf", extract_images: bool = True,
              do_ocr: bool = True) -> Parsed:
    """Разобрать PDF из байтов. Имя нужно только для имён вынутых картинок."""
    stem = os.path.splitext(os.path.basename(name))[0] or "pdf"
    notes: list[str] = []
    extra: dict = {}
    pages: list[str] = []
    derived: list[Derived] = []
    tables: list[dict] = []
    seen_xrefs: set[int] = set()

    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception as exc:
        return Parsed(kind=KIND_PDF, unit=UNIT_PAGE,
                      notes=[f"PDF не открывается: {exc}"])

    with doc:
        title = (doc.metadata or {}).get("title") or ""
        if title.strip():
            extra["title"] = title.strip()

        raw_pages = [page.get_text() or "" for page in doc]
        # Скан — это когда текстового слоя нет нигде. Одна короткая страница
        # ещё ничего не значит, поэтому смотрим на документ целиком.
        scanned = bool(raw_pages) and not any(len(t.strip()) >= SCAN_MIN_CHARS for t in raw_pages)
        if scanned:
            extra["scanned"] = True
        recognized = False

        for number, page in enumerate(doc, start=1):
            text = raw_pages[number - 1].rstrip()
            page_blank = len(text.strip()) < SCAN_MIN_CHARS
            page_read_by_ocr = page_blank and do_ocr and ocr.available()
            if page_read_by_ocr:
                # Страницу без текстового слоя отрисовываем и читаем через OCR.
                png = page.get_pixmap(dpi=OCR_DPI).tobytes("png")
                text = ocr.recognize(png, ext=".png").rstrip()
                recognized = recognized or bool(text.strip())
            pages.append(text)

            for row in _page_tables(page):
                tables.append({"page": number, "rows": row})

            if not extract_images:
                continue
            for info in page.get_images(full=True):
                xref = info[0]
                if xref in seen_xrefs:      # одна картинка на многих страницах — материал один
                    continue
                seen_xrefs.add(xref)
                try:
                    img = doc.extract_image(xref)
                except Exception:
                    continue
                if img.get("width", 0) < MIN_IMAGE_SIDE or img.get("height", 0) < MIN_IMAGE_SIDE:
                    continue
                ext = "." + (img.get("ext") or "png")
                derived.append(Derived(
                    name=f"{stem}-стр{number}-{len(derived) + 1}{ext}",
                    data=img["image"], ext=ext,
                    # Если страницу уже прочитали через OCR целиком — повторно
                    # гонять ту же картинку через tesseract незачем. А если OCR не
                    # было вовсе, картинка должна попробовать сама и честно
                    # сказать в карточке, почему не вышло.
                    origin={"page": number, "ocr": not page_read_by_ocr}))

    if scanned:
        if not do_ocr or not ocr.available():
            notes.append("PDF без текстового слоя (скан): " + ocr.NOT_INSTALLED)
        elif recognized:
            notes.append("PDF без текстового слоя (скан): текст получен через OCR")
        else:
            notes.append("PDF без текстового слоя (скан): " + ocr.NOT_RECOGNIZED)

    if tables:
        extra["tables"] = tables
    if derived:
        extra["images"] = len(derived)

    return Parsed(kind=KIND_PDF, unit=UNIT_PAGE, units=pages,
                  lang=detect_lang("\n".join(pages)), notes=notes,
                  extra=extra, derived=derived)
