"""images — размеры картинок, вписывание в страницу, draw.io → PNG.

Пиксельной нарезки высоких схем на листы здесь больше нет (2.0.0a2.5): резать
растр вслепую значит рвать фигуры и рисовать соединители «на глаз». Листы даёт
сам генератор схемы — многостраничный mxfile, где разрыв стоит в нужном месте.
"""
from __future__ import annotations

import io
import re

from PIL import Image as PILImage

EMU_PER_CM = 360000


def to_raster(data: bytes) -> bytes:
    """SVG → PNG (cairosvg, если установлен); растровые форматы — как есть."""
    head = data[:512].lstrip()
    if head.startswith(b"<") and b"<svg" in head.lower():
        try:
            import cairosvg
        except ImportError:
            raise ValueError("SVG требует пакет cairosvg (pip install cairosvg)")
        return cairosvg.svg2png(bytestring=data, dpi=192)
    return data


def size_px(data: bytes) -> tuple[int, int]:
    with PILImage.open(io.BytesIO(data)) as im:
        return im.size


def natural_width_cm(data: bytes, default_dpi: float = 96.0) -> float:
    """Ширина «как есть»: по DPI из файла, иначе 96 dpi (экранная)."""
    with PILImage.open(io.BytesIO(data)) as im:
        w_px = im.size[0]
        dpi = im.info.get("dpi", (default_dpi, default_dpi))[0] or default_dpi
    return w_px / dpi * 2.54


def fit(data: bytes, max_w_cm: float, max_h_cm: float, want_w_cm: float | None = None) -> tuple[float, float]:
    """Ширина и высота (см), вписанные в max_w × max_h с сохранением пропорций."""
    w_px, h_px = size_px(data)
    if want_w_cm:
        w = min(want_w_cm, max_w_cm)
    else:
        w = min(max_w_cm, max(natural_width_cm(data), 4.0))
    h = w * h_px / w_px
    if h > max_h_cm:
        h = max_h_cm
        w = h * w_px / h_px
    return w, h


_PNG_CACHE: dict = {}                # ключ по содержимому → PNG
_PNG_CACHE_MAX = 16                  # схем; при переполнении выбрасывается самая старая


def clear_png_cache() -> None:
    _PNG_CACHE.clear()


_DIAGRAM_RE = re.compile(r"<diagram\b")


def count_pages(xml: str) -> int:
    """Сколько страниц в mxfile. Генератор схемы (fragmos) сам режет длинный алгоритм
    на страницы и ставит на разрывах соединители — здесь достаточно их сосчитать."""
    return max(1, len(_DIAGRAM_RE.findall(xml)))


def drawio_to_png(xml: str, page: int | None = None, scale: float = 2.0, timeout: float = 120,
                  cache: bool = True) -> bytes:
    """draw.io XML → PNG через drawio CLI (+ xvfb-run, если есть). Ошибка, если CLI нет.
    Зовётся с `--no-sandbox`: Electron без него в контейнере падает (см. ниже).
    page — номер страницы mxfile, считая с 1 (None — первая). CLI при выходе за границу
    молча отдаёт последнюю страницу, поэтому номер проверяется здесь.

    Запуск стоит ~3 с (Electron под xvfb) и не зависит ни от чего, кроме содержимого,
    поэтому результат кэшируется по хешу XML: одна и та же схема в двух тегах и повторная
    сборка того же отчёта больше не платят. cache=False — считать заново."""
    import hashlib
    total = count_pages(xml)
    if page is not None and not 1 <= page <= total:
        raise ValueError(f"в схеме {total} стр., запрошена {page}")
    key = (hashlib.sha1(xml.encode("utf-8")).hexdigest(), page, scale)
    if cache and key in _PNG_CACHE:
        return _PNG_CACHE[key]
    import os
    import shutil
    import subprocess
    import tempfile
    exe = shutil.which("drawio")
    if not exe:
        raise ValueError("draw.io CLI (`drawio`) не найден — Diagram недоступен")
    with tempfile.TemporaryDirectory(prefix="hokoku_drawio_") as tmp:
        src = os.path.join(tmp, "d.drawio")
        out = os.path.join(tmp, "d.png")
        with open(src, "w", encoding="utf-8") as f:
            f.write(xml)
        # `--no-sandbox` — не небрежность и не «чтобы заработало». draw.io CLI
        # это Electron, то есть Chromium, а его песочница берётся либо из
        # setuid-помощника, либо из пространств имён пользователя; в контейнере
        # (мы ходим там непривилегированным UID 10001) нет ни того ни другого, и
        # Chromium падает с «Trace/breakpoint trap (core dumped)» — ровно та
        # беда, из-за которой схема не попадала в собранный DOCX. Проверено
        # прогоном в контейнере: без флага — падение, с флагом — PNG.
        # Опасности здесь меньше, чем кажется: свой процесс мы и так закрываем
        # снаружи (`subproc`, потолки памяти и времени), а рисуется не чужая
        # страница, а наш собственный XML.
        cmd = [exe, "-x", "-f", "png", "-s", str(scale), "--no-sandbox", "-o", out]
        if page is not None:
            cmd += ["-p", str(page)]
        cmd.append(src)
        if shutil.which("xvfb-run"):
            cmd = ["xvfb-run", "-a"] + cmd
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            raise ValueError(f"drawio не уложился в {timeout:g} с")
        if not os.path.isfile(out):
            raise ValueError(f"drawio не создал PNG: {(r.stderr or r.stdout).strip()[-300:]}")
        with open(out, "rb") as f:
            png = f.read()
    if cache:
        if len(_PNG_CACHE) >= _PNG_CACHE_MAX:
            del _PNG_CACHE[next(iter(_PNG_CACHE))]
        _PNG_CACHE[key] = png
    return png
