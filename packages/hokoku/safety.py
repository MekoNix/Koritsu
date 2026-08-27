"""
safety — защита при работе с чужими DOCX и именами файлов.

validate_docx(source): DOCX — это ZIP с XML, через него возможны
  zip-slip (имя члена `../../x`), zip-bomb (ratio 10000:1), XXE / billion-laughs
  (<!DOCTYPE …> с external entity). python-docx парсит XML через lxml без
  secure-настроек, поэтому проверяем сырой ZIP ДО открытия.
safe_name / safe_join: имя файла от пользователя не должно выводить за каталог.
"""
from __future__ import annotations

import io
import os
import re
import zipfile

MAX_TOTAL_UNCOMPRESSED = 100 * 1024 * 1024
MAX_PER_MEMBER         = 50 * 1024 * 1024
MAX_FILE_COUNT         = 2000
MAX_COMPRESSION_RATIO  = 200
MIN_COMPRESSED_BYTES   = 1024

_DOCTYPE_RE = re.compile(rb"<!DOCTYPE\b", re.IGNORECASE)
_ENTITY_RE  = re.compile(rb"<!ENTITY\b", re.IGNORECASE)


class DocxValidationError(Exception):
    """Файл не прошёл проверку безопасности (текст — пользовательский)."""


def _member_name_ok(name: str) -> bool:
    if not name or "\x00" in name or "\\" in name:
        return False
    if name.startswith("/") or os.path.isabs(name):
        return False
    parts = name.split("/")
    if any(p in ("..", ".") for p in parts) or any(":" in p for p in parts):
        return False
    return True


def validate_docx(source) -> None:
    """source — путь, bytes или file-like. Бросает DocxValidationError."""
    if isinstance(source, (bytes, bytearray)):
        zf_input = io.BytesIO(bytes(source))
    elif isinstance(source, str):
        if not os.path.isfile(source):
            raise DocxValidationError("файл не найден")
        zf_input = source
    else:
        source.seek(0)
        zf_input = io.BytesIO(source.read())
        source.seek(0)
    try:
        zf = zipfile.ZipFile(zf_input)
    except zipfile.BadZipFile:
        raise DocxValidationError("файл не является DOCX (битый zip)")
    with zf:
        infos = zf.infolist()
        if len(infos) > MAX_FILE_COUNT:
            raise DocxValidationError(f"слишком много файлов в архиве ({len(infos)})")
        total = 0
        has_document = False
        for info in infos:
            name = info.filename
            if not _member_name_ok(name):
                raise DocxValidationError(f"подозрительное имя в архиве: {name!r}")
            if info.file_size > MAX_PER_MEMBER:
                raise DocxValidationError(f"{name!r} слишком большой: {info.file_size} байт")
            total += info.file_size
            if total > MAX_TOTAL_UNCOMPRESSED:
                raise DocxValidationError("суммарный размер распакованных файлов > 100 МБ")
            if info.compress_size >= MIN_COMPRESSED_BYTES:
                if info.file_size / max(1, info.compress_size) > MAX_COMPRESSION_RATIO:
                    raise DocxValidationError(f"подозрительная компрессия в {name!r} (zip-bomb)")
            if name == "word/document.xml":
                has_document = True
            if name.endswith((".xml", ".rels")):
                with zf.open(info) as fh:
                    head = fh.read(65536)
                if _DOCTYPE_RE.search(head) or _ENTITY_RE.search(head):
                    raise DocxValidationError(f"XML в {name!r} содержит DOCTYPE/ENTITY (XXE)")
        if not has_document:
            raise DocxValidationError("в архиве нет word/document.xml")


_SAFE_CHARS_RE = re.compile(r"[^\w .\-()]", re.UNICODE)


def safe_name(filename: str, ext: str = ".docx") -> str:
    """Имя файла от пользователя → безопасное базовое имя без путей."""
    base = os.path.basename(filename.replace("\\", "/"))
    base = _SAFE_CHARS_RE.sub("", base).strip(" .")
    if not base or base.lower() in (ext, ext.lstrip(".")):
        base = "file" + ext
    if ext and not base.lower().endswith(ext):
        base += ext
    return base


def safe_join(root: str, *parts: str) -> str:
    """Путь внутри root; `..`, абсолютные и symlink-выходы наружу — ошибка."""
    root_real = os.path.realpath(root)
    target = os.path.realpath(os.path.join(root_real, *parts))
    if target != root_real and not target.startswith(root_real + os.sep):
        raise DocxValidationError(f"путь выходит за пределы каталога: {'/'.join(parts)!r}")
    return target
