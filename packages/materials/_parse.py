"""
parse — выбор разбора по типу файла.

Материалы бывают любые: методичка в PDF, таблица продаж в CSV, скриншот
прибора, конспект по химии, исходник программы. Ничего специфичного для одной
предметной области здесь нет и быть не должно — только «чем это открывать».

Незнакомый тип не считается ошибкой: файл сохраняется, разбор остаётся пустым,
а в карточке написано, почему содержимое недоступно.
"""
from __future__ import annotations

import os

from ._docx import parse_word
from ._image import parse_image
from ._pdf import parse_pdf
from ._text import looks_like_text, parse_text
from .model import KIND_UNKNOWN, Parsed

# Текст и разметка. Список заведомо неполон — незнакомые расширения ловятся
# по содержимому (looks_like_text), поэтому гоняться за полнотой не нужно.
TEXT_EXT = {
    ".txt", ".md", ".markdown", ".rst", ".csv", ".tsv", ".log", ".tex", ".bib",
    ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".env", ".xml",
    ".html", ".htm", ".css", ".svg", ".sql", ".diff", ".patch",
    ".py", ".pyi", ".js", ".mjs", ".ts", ".tsx", ".jsx", ".c", ".h", ".cpp",
    ".cc", ".hpp", ".cs", ".java", ".kt", ".go", ".rs", ".rb", ".php", ".swift",
    ".m", ".r", ".jl", ".lua", ".pas", ".f", ".f90", ".asm", ".s", ".sh", ".bat",
    ".ps1", ".vb", ".scala", ".dart", ".pl", ".hs", ".ml", ".erl", ".ex",
}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tif", ".tiff", ".ppm"}
PDF_EXT = {".pdf"}
# Word: и документы, и шаблоны, и версии с макросами, и старый двоичный .doc.
# Все они идут в один разбор — он сам смотрит на сигнатуру файла, потому что
# расширение врёт: `.doc`, сохранённый из LibreOffice, часто оказывается zip.
# Цена пропуска здесь особая: .docx — самый частый формат методички, и раньше
# он попадал в «неизвестный тип», то есть человек видел принятый файл, а модель
# не получала ни строки.
WORD_EXT = {".docx", ".docm", ".dotx", ".dotm", ".doc", ".dot"}


def ext_of(name: str) -> str:
    return os.path.splitext(name)[1].lower()


def parse(data: bytes, name: str, do_ocr: bool = True) -> Parsed:
    """
    Разобрать материал по имени файла и байтам. OCR можно выключить (`do_ocr`) —
    например, для картинки со страницы скана, которую уже прочитали целиком.
    """
    ext = ext_of(name)
    if ext in PDF_EXT:
        return parse_pdf(data, name=name, do_ocr=do_ocr)
    if ext in WORD_EXT:
        return parse_word(data, name=name, ext=ext)
    if ext in IMAGE_EXT:
        return parse_image(data, ext=ext, do_ocr=do_ocr)
    if ext in TEXT_EXT:
        return parse_text(data)
    if looks_like_text(data):
        # Расширение незнакомое, но внутри текст — читаем как текст и говорим об этом.
        return parse_text(data, note=f"тип определён по содержимому (расширение {ext or 'отсутствует'})")
    return Parsed(kind=KIND_UNKNOWN,
                  notes=[f"разбор не выполнен: тип {ext or 'без расширения'} не поддерживается, "
                         f"файл сохранён целиком"])
