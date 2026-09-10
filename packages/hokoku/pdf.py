"""pdf — DOCX → PDF через LibreOffice headless (отдельный профиль в tmp, timeout).

Два варианта одного и того же: по путям (удобно из руки и из лаборатории) и по байтам
(документ уже лежит в памяти — `RenderResult.data`, и писать его на диск ради
LibreOffice, а потом читать обратно, значит завести три лишних действия и три места,
где остаётся мусор).

Закладки документа выгружаются в PDF именованными назначениями. Это и есть способ
показать человеку блоки работы прямо на странице: превью спрашивает у PDF назначение
по имени закладки блока (`live.bookmark_name`) и узнаёт страницу и высоту, с которой
блок начинается. Без назначений PDF остаётся картинкой, и указать в нём кусок работы
нечем."""
from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import tempfile

from .model import HokokuError


def libreoffice_available() -> bool:
    return bool(shutil.which("libreoffice") or shutil.which("soffice"))


# Настройки фильтра PDF. Заданные настройки отменяют умолчания LibreOffice целиком,
# поэтому здесь стоят и те две, что и без нас работали, — иначе отчёт молча потерял бы
# разметку и вид при открытии:
#   ExportBookmarksToPDFDestination — закладки документа наружу именованными
#       назначениями. Ради этого настройки и появились: без назначений PDF не несёт
#       закладок вовсе, и указать в нём кусок работы нечем.
#   UseTaggedPDF — размеченный PDF: порядок чтения и структура для экранного диктора
#       и для копирования текста.
#   InitialView=1 — открывать с панелью закладок: по ней читатель ходит по разделам.
_PDF_OPTIONS = ('{"ExportBookmarksToPDFDestination":{"type":"boolean","value":"true"},'
                '"UseTaggedPDF":{"type":"boolean","value":"true"},'
                '"InitialView":{"type":"long","value":"1"}}')

# Вид вывода для `--convert-to`. JSON-настройки фильтра понимает LibreOffice 7.4 и новее.
PDF_FILTER = "pdf:writer_pdf_Export:" + _PDF_OPTIONS


def docx_to_pdf(docx_path: str, pdf_path: str, timeout: float = 90.0) -> str:
    """timeout — секунды на LibreOffice (серверу нужны свои, короче умолчания)."""
    exe = shutil.which("libreoffice") or shutil.which("soffice")
    if not exe:
        raise HokokuError("LibreOffice не установлен — PDF недоступен")
    os.makedirs(os.path.dirname(os.path.abspath(pdf_path)), exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="hokoku_pdf_") as tmp:
        profile = pathlib.Path(tmp, "profile").as_uri()
        produced = os.path.join(tmp, os.path.splitext(os.path.basename(docx_path))[0] + ".pdf")
        # Второй заход без настроек фильтра — на случай LibreOffice старше 7.4, который
        # разберёт JSON как имя фильтра и не соберёт ничего. Такой PDF выйдет без
        # именованных назначений (блоки на превью не выделить), но документ человек
        # получит: отдать пустую страницу вместо отчёта было бы хуже.
        for convert_to in (PDF_FILTER, "pdf"):
            try:
                r = subprocess.run(
                    [exe, f"-env:UserInstallation={profile}", "--headless", "--norestore",
                     "--nofirststartwizard", "--convert-to", convert_to, "--outdir", tmp,
                     docx_path],
                    capture_output=True, text=True, timeout=timeout)
            except subprocess.TimeoutExpired:
                raise HokokuError(f"LibreOffice не уложился в {timeout:g} с")
            if r.returncode == 0 and os.path.isfile(produced):
                break
        else:
            raise HokokuError(f"LibreOffice не создал PDF: {(r.stderr or r.stdout).strip()[-400:]}")
        shutil.move(produced, pdf_path)
    return pdf_path


def docx_bytes_to_pdf(data: bytes, *, timeout: float = 90.0) -> bytes:
    """DOCX в памяти → PDF в памяти.

    Внутри — тот же docx_to_pdf во временном каталоге, который убирается всегда,
    в том числе при таймауте и отсутствии LibreOffice. Имя внутри каталога
    фиксированное: LibreOffice кладёт PDF рядом с входным и по его имени.
    """
    if not isinstance(data, (bytes, bytearray)):
        raise HokokuError(f"docx_bytes_to_pdf: нужны байты DOCX, а не {type(data).__name__}")
    with tempfile.TemporaryDirectory(prefix="hokoku_docx_") as tmp:
        docx_path = os.path.join(tmp, "report.docx")
        pdf_path = os.path.join(tmp, "report.pdf")
        with open(docx_path, "wb") as f:
            f.write(data)
        docx_to_pdf(docx_path, pdf_path, timeout=timeout)
        with open(pdf_path, "rb") as f:
            return f.read()
