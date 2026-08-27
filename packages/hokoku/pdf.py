"""pdf — DOCX → PDF через LibreOffice headless (отдельный профиль в tmp, timeout)."""
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
    exe = shutil.which("libreoffice") or shutil.which("soffice")
    if not exe:
        raise HokokuError("LibreOffice не установлен — PDF недоступен")
    os.makedirs(os.path.dirname(os.path.abspath(pdf_path)), exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="hokoku_pdf_") as tmp:
        profile = pathlib.Path(tmp, "profile").as_uri()
        r = subprocess.run(
            [exe, f"-env:UserInstallation={profile}", "--headless", "--norestore",
             "--nofirststartwizard", "--convert-to", "pdf", "--outdir", tmp, docx_path],
            capture_output=True, text=True, timeout=timeout)
        produced = os.path.join(tmp, os.path.splitext(os.path.basename(docx_path))[0] + ".pdf")
        if r.returncode != 0 or not os.path.isfile(produced):
            raise HokokuError(f"LibreOffice не создал PDF: {(r.stderr or r.stdout).strip()[-400:]}")
        shutil.move(produced, pdf_path)
    return pdf_path
