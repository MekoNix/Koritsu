"""
_docx_safe — проверка недоверенного DOCX ДО того, как его откроет парсер.

DOCX — это zip с XML внутри, и приносит его пользователь. Без этой проверки
достаточно одного файла на 300 КБ, чтобы разбор съел всю память машины
(zip-бомба), или чтобы XML-парсер по `<!DOCTYPE>` полез читать `/etc/passwd`
и ходить в сеть (XXE). Цена ошибки — не «плохой отчёт», а упавший или
разболтавший лишнее процесс на файле, который пользователь считает методичкой.

Почему проверка своя, а не общая с `hokoku.safety`:

  * пакеты не связаны ни одним импортом — это правило проекта, и вопрос
    вынесения общего кода в отдельный пакет решает владелец, а не разбор;
  * угрозы у пакетов РАЗНЫЕ, и одинаковый код был бы неверен в обе стороны.
    hokoku берёт шаблон и отдаёт его байт в байт в собранный отчёт, поэтому
    макросы VBA для него — отказ. materials файл только читает: макросы здесь
    не выполняются и наружу не уезжают, поэтому они пометка, а не отказ, —
    решение отдать такой файл дальше принимает тот, кто отдаёт.
  * zip-slip (член архива с именем `../../x`) здесь не угроза вовсе: ничего
    никуда не распаковывается, члены читаются в память по имени, а исходник
    хранилище кладёт под именем от хеша. Подозрительное имя мы всё равно
    считаем отказом — не как защиту пути, а как признак, что файл собран не Word.

Потолки меряются РАСПАКОВКОЙ с ранним выходом, а не заголовками архива:
заголовок пишет тот же, кто прислал файл. Отдельная проверка степени сжатия
не нужна — абсолютный потолок на распакованное ловит ту же бомбу и не спорит
с честным XML, который сжимается в 200 раз.
"""
from __future__ import annotations

import io
import os
import re
import zipfile

# Потолки. Считаны от того, что реально приносят: методичка с фотографиями —
# единицы мегабайт, 100 МБ распакованного уже заведомо не учебный материал.
MAX_MEMBERS = 2000
MAX_MEMBER_BYTES = 50 * 1024 * 1024
MAX_TOTAL_BYTES = 100 * 1024 * 1024
# Весь XML пакета — это то, что парсер держит в памяти целиком и разворачивает
# в дерево объектов, то есть вдесятеро дороже своего размера.
MAX_XML_BYTES = 32 * 1024 * 1024
READ_CHUNK = 1024 * 1024
# Хватит начала члена: DOCTYPE и объявления сущностей стоят до корневого тега.
XXE_PROBE = 64 * 1024

ZIP_MAGIC = b"PK\x03\x04"
# Сигнатура OLE2 — старый .doc, а также docx под паролем (шифрованный контейнер).
OLE2_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"

_DOCTYPE_RE = re.compile(rb"<!DOCTYPE\b", re.IGNORECASE)
_ENTITY_RE = re.compile(rb"<!ENTITY\b", re.IGNORECASE)

# Макросы: часть с кодом VBA и объявление главной части .docm в описи типов.
_VBA_NAMES = ("vbaproject.bin", "vbadata.xml")
_VBA_CT_RE = re.compile(rb"vnd\.ms-office\.vbaProject", re.IGNORECASE)
_MACRO_MAIN_RE = re.compile(rb"macroEnabled(?:Template)?\.main\+xml", re.IGNORECASE)


class DocxUnsafe(Exception):
    """Файл не годится к разбору. Текст — пользовательский, он уйдёт в карточку."""


def _name_ok(name: str) -> bool:
    if not name or "\x00" in name or "\\" in name:
        return False
    if name.startswith("/") or os.path.isabs(name):
        return False
    return not any(p in ("..", ".") or ":" in p for p in name.split("/"))


def check_zip(data: bytes) -> dict:
    """
    Осмотреть zip перед разбором. Возвращает {"macros": bool} — то, о чём разбор
    обязан сказать в карточке. Всё, из-за чего разбирать нельзя, бросает
    DocxUnsafe с человеческой причиной.
    """
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except (zipfile.BadZipFile, OSError) as exc:
        raise DocxUnsafe(f"файл не открывается как DOCX (битый zip): {exc}")

    macros = False
    with zf:
        infos = zf.infolist()
        if len(infos) > MAX_MEMBERS:
            raise DocxUnsafe(f"слишком много файлов внутри документа ({len(infos)})")
        has_document = False
        for info in infos:
            if not _name_ok(info.filename):
                raise DocxUnsafe(f"подозрительное имя внутри документа: {info.filename!r}")
            # Заголовкам не верим, но заведомо огромное отсекаем до распаковки —
            # это бесплатно и снимает большую часть бомб.
            if info.file_size > MAX_MEMBER_BYTES:
                raise DocxUnsafe(f"часть документа {info.filename!r} слишком велика")
            if info.filename == "word/document.xml":
                has_document = True
            if info.filename.rsplit("/", 1)[-1].lower() in _VBA_NAMES:
                macros = True
        if not has_document:
            raise DocxUnsafe("внутри нет word/document.xml — это не документ Word")
        macros = _scan(zf, infos) or macros
    return {"macros": macros}


def _scan(zf: zipfile.ZipFile, infos) -> bool:
    """Распаковать всё с потолками: настоящие размеры, XXE, объявленные макросы."""
    total = xml_total = 0
    macros = False
    for info in infos:
        name = info.filename
        is_xml = name.endswith((".xml", ".rels"))
        # Опись типов и связи копим целиком: `<Override>` с макро-частью можно
        # спрятать в конце длинного файла, за пределами первого куска.
        keep = bytearray() if (name == "[Content_Types].xml" or name.endswith(".rels")) else None
        size = 0
        try:
            fh = zf.open(info)
        except (zipfile.BadZipFile, OSError, NotImplementedError, RuntimeError) as exc:
            raise DocxUnsafe(f"часть документа {name!r} не читается: {exc}")
        with fh:
            while True:
                try:
                    chunk = fh.read(READ_CHUNK)
                except (zipfile.BadZipFile, OSError, EOFError,
                        NotImplementedError, RuntimeError) as exc:
                    # Соврали о размере или методе сжатия — zipfile ловит это на CRC.
                    raise DocxUnsafe(f"часть документа {name!r} не читается: {exc}")
                if not chunk:
                    break
                if size == 0 and is_xml and (_DOCTYPE_RE.search(chunk[:XXE_PROBE])
                                             or _ENTITY_RE.search(chunk[:XXE_PROBE])):
                    raise DocxUnsafe(f"XML внутри ({name}) объявляет DOCTYPE или сущности — "
                                     f"так делают не редакторы, а атаки (XXE)")
                if keep is not None and len(keep) < XXE_PROBE * 64:
                    keep += chunk[:XXE_PROBE * 64 - len(keep)]
                size += len(chunk)
                total += len(chunk)
                if is_xml:
                    xml_total += len(chunk)
                if size > MAX_MEMBER_BYTES:
                    raise DocxUnsafe(f"часть документа {name!r} разворачивается "
                                     f"больше {MAX_MEMBER_BYTES // (1024 * 1024)} МБ (zip-бомба)")
                if total > MAX_TOTAL_BYTES:
                    raise DocxUnsafe(f"документ разворачивается больше "
                                     f"{MAX_TOTAL_BYTES // (1024 * 1024)} МБ (zip-бомба)")
                if xml_total > MAX_XML_BYTES:
                    raise DocxUnsafe(f"XML документа больше "
                                     f"{MAX_XML_BYTES // (1024 * 1024)} МБ (zip-бомба)")
        if keep is not None and (_VBA_CT_RE.search(bytes(keep)) or _MACRO_MAIN_RE.search(bytes(keep))):
            macros = True
    return macros
