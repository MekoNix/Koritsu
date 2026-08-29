"""
safety — защита при работе с чужими DOCX и именами файлов.

validate_docx(source): DOCX — это ZIP с XML, через него возможны
  zip-slip (имя члена `../../x`), zip-bomb (ratio 10000:1), XXE / billion-laughs
  (<!DOCTYPE …> с external entity). python-docx парсит XML через lxml без
  secure-настроек, поэтому проверяем сырой ZIP ДО открытия.
  Бомбу считаем по архиву целиком, а не по каждому члену: 1900 членов по 50 КБ нулей
  дают 344 КБ на диске и 97 МБ в памяти, и каждый член по отдельности «чистый».
  Размеры берём распаковкой с потолком, а не из заголовков: заголовок пишет
  тот же, кто прислал файл.
  Степень сжатия проверяем только у бинарных членов: XML в 200 раз сжимается и у честной
  методички (5000 одинаковых абзацев дают 223), поэтому XML ограничен абсолютным
  размером — он и есть то, что целиком читает lxml.
safe_name / safe_join: имя файла от пользователя не должно выводить за каталог.
"""
from __future__ import annotations

import io
import os
import re
import zipfile

MAX_TOTAL_UNCOMPRESSED = 100 * 1024 * 1024
MAX_PER_MEMBER         = 50 * 1024 * 1024
MAX_XML_UNCOMPRESSED   = 32 * 1024 * 1024    # весь XML пакета: его целиком читает lxml
MAX_FILE_COUNT         = 2000
MAX_COMPRESSION_RATIO  = 200                 # на один бинарный член
MAX_TOTAL_RATIO        = 200                 # на бинарную часть архива целиком
ALLOWED_METHODS        = (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)   # что кладёт Word
MIN_COMPRESSED_BYTES   = 1024
RATIO_MIN_TOTAL        = 1024 * 1024         # ниже — соотношение шумит, не проверяем
READ_CHUNK             = 1024 * 1024

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
        declared = 0
        has_document = False
        for info in infos:                                    # дешёвая проверка по заголовкам
            name = info.filename
            if not _member_name_ok(name):
                raise DocxValidationError(f"подозрительное имя в архиве: {name!r}")
            if info.file_size > MAX_PER_MEMBER:
                raise DocxValidationError(f"{name!r} слишком большой: {info.file_size} байт")
            declared += info.file_size
            if declared > MAX_TOTAL_UNCOMPRESSED:
                raise DocxValidationError("суммарный размер распакованных файлов > 100 МБ")
            if info.compress_type not in ALLOWED_METHODS:
                raise DocxValidationError(
                    f"{name!r}: неподдерживаемый метод сжатия ({info.compress_type})")
            if not name.endswith((".xml", ".rels")) and info.compress_size >= MIN_COMPRESSED_BYTES:
                if info.file_size / max(1, info.compress_size) > MAX_COMPRESSION_RATIO:
                    raise DocxValidationError(f"подозрительная компрессия в {name!r} (zip-bomb)")
            if name == "word/document.xml":
                has_document = True
        if not has_document:
            raise DocxValidationError("в архиве нет word/document.xml")
        _scan_contents(zf, infos)


def _scan_contents(zf: zipfile.ZipFile, infos) -> None:
    """Распаковать всё с потолками: реальные размеры, доля XML, XXE. Ранний выход по лимиту."""
    total = compressed = xml_total = bin_total = 0
    for info in infos:
        name = info.filename
        is_xml = name.endswith((".xml", ".rels"))
        size = 0
        try:
            fh = zf.open(info)
        except (zipfile.BadZipFile, OSError, NotImplementedError, RuntimeError) as e:
            raise DocxValidationError(f"член архива {name!r} не читается: {e}")
        with fh:
            while True:
                try:
                    chunk = fh.read(READ_CHUNK)
                except (zipfile.BadZipFile, OSError, EOFError,
                        NotImplementedError, RuntimeError) as e:
                    # соврали в заголовке о размере — zipfile ловит это на CRC
                    raise DocxValidationError(f"член архива {name!r} не читается: {e}")
                if not chunk:
                    break
                if size == 0 and is_xml and (_DOCTYPE_RE.search(chunk[:65536])
                                             or _ENTITY_RE.search(chunk[:65536])):
                    raise DocxValidationError(f"XML в {name!r} содержит DOCTYPE/ENTITY (XXE)")
                size += len(chunk)
                if size > MAX_PER_MEMBER:
                    raise DocxValidationError(f"{name!r} распаковывается больше 50 МБ (zip-bomb)")
                if total + size > MAX_TOTAL_UNCOMPRESSED:
                    raise DocxValidationError("суммарный размер распакованных файлов > 100 МБ")
                if is_xml and xml_total + size > MAX_XML_UNCOMPRESSED:
                    raise DocxValidationError("XML пакета больше 32 МБ (zip-bomb)")
        total += size
        if is_xml:
            xml_total += size
        else:
            bin_total += size
            compressed += info.compress_size
    if bin_total > RATIO_MIN_TOTAL and bin_total / max(1, compressed) > MAX_TOTAL_RATIO:
        raise DocxValidationError(
            f"вложения архива разворачиваются в {bin_total // (1024 * 1024)} МБ "
            f"из {compressed // 1024} КБ (zip-bomb)")


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
