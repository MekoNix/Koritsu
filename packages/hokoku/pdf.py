"""pdf — DOCX → PDF через LibreOffice headless (отдельный профиль в tmp, timeout).

Два варианта одного и того же: по путям (удобно из руки и из лаборатории) и по байтам
(документ уже лежит в памяти — `RenderResult.data`, и писать его на диск ради
LibreOffice, а потом читать обратно, значит завести три лишних действия и три места,
где остаётся мусор)."""
from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import tempfile

from .model import HokokuError


def libreoffice_available() -> bool:
    return bool(shutil.which("libreoffice") or shutil.which("soffice"))


def docx_to_pdf(docx_path: str, pdf_path: str, timeout: float = 90.0) -> str:
    """timeout — секунды на LibreOffice (серверу нужны свои, короче умолчания)."""
    exe = shutil.which("libreoffice") or shutil.which("soffice")
    if not exe:
        raise HokokuError("LibreOffice не установлен — PDF недоступен")
    os.makedirs(os.path.dirname(os.path.abspath(pdf_path)), exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="hokoku_pdf_") as tmp:
        profile = pathlib.Path(tmp, "profile").as_uri()
        try:
            r = subprocess.run(
                [exe, f"-env:UserInstallation={profile}", "--headless", "--norestore",
                 "--nofirststartwizard", "--convert-to", "pdf", "--outdir", tmp, docx_path],
                capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            raise HokokuError(f"LibreOffice не уложился в {timeout:g} с")
        produced = os.path.join(tmp, os.path.splitext(os.path.basename(docx_path))[0] + ".pdf")
        if r.returncode != 0 or not os.path.isfile(produced):
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
