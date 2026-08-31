"""
ocr — распознавание текста через системный tesseract.

Почему подпроцессом, а не библиотекой: pytesseract и тем более torch/paddle —
это либо лишняя зависимость, либо гигабайты ради одной функции. tesseract, если
он установлен, умеет всё нужное сам: `tesseract вход stdout -l rus+eng`.

Почему вообще OCR, а не зрение модели: изображений в проекте бывает 40–60,
и прогонять их через модель дорого и медленно. С картинки берём текст, а сама
картинка остаётся файлом и вставляется в отчёт по идентификатору.

Если tesseract не установлен — модуль не падает: `available()` вернёт False,
`recognize()` вернёт пустую строку, а материал получит честную пометку.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile

# Пометка в карточке, когда распознать было нечем.
NOT_INSTALLED = "текст не распознан: tesseract не установлен"
NOT_RECOGNIZED = "текст не распознан: на картинке не нашлось букв"

# Языки по умолчанию: материалы русские, но формулы и подписи часто латиницей.
DEFAULT_LANGS = ("rus", "eng")


def _exe() -> str | None:
    return shutil.which("tesseract")


def available() -> bool:
    """Есть ли tesseract в системе."""
    return _exe() is not None


def languages(timeout: float = 15.0) -> list[str]:
    """Установленные языковые пакеты (`tesseract --list-langs`)."""
    exe = _exe()
    if not exe:
        return []
    try:
        r = subprocess.run([exe, "--list-langs"], capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return []
    out = (r.stdout or "") + "\n" + (r.stderr or "")
    # Первая строка — «List of available languages…», дальше по одному коду в строке.
    return [ln.strip() for ln in out.splitlines() if ln.strip() and " " not in ln.strip()]


def _lang_arg(want: tuple[str, ...]) -> list[str]:
    """
    `-l` только из тех языков, что реально стоят: просьба про отсутствующий пакет
    роняет tesseract, а разбор из-за этого падать не должен.
    """
    have = languages()
    if not have:
        return []
    chosen = [code for code in want if code in have]
    return ["-l", "+".join(chosen)] if chosen else []


def recognize(data: bytes, ext: str = ".png", langs: tuple[str, ...] = DEFAULT_LANGS,
              timeout: float = 120.0) -> str:
    """
    Распознать текст с картинки (байты). Возвращает пустую строку, если
    tesseract не установлен или ничего не нашлось — исключений не бросает.
    """
    exe = _exe()
    if not exe:
        return ""
    with tempfile.TemporaryDirectory(prefix="materials_ocr_") as tmp:
        src = os.path.join(tmp, "in" + (ext or ".png"))
        with open(src, "wb") as f:
            f.write(data)
        cmd = [exe, src, "stdout", *_lang_arg(langs)]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        except (OSError, subprocess.SubprocessError):
            return ""
    if r.returncode != 0:
        return ""
    return (r.stdout or "").strip()
