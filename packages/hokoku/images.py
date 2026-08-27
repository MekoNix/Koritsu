"""images — размеры картинок, вписывание в страницу, нарезка высоких схем."""
from __future__ import annotations

import io

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


def split_tall(data: bytes, max_ratio: float, tolerance: float = 0.25,
               max_ink: float = 0.03, connectors: bool = True) -> list[bytes]:
    """
    Разрезать картинку на куски высотой ≤ max_ratio × ширина, выбирая в окне
    [граница − tolerance·кусок, граница] строку с наименьшим числом «непустых»
    пикселей: между фигурами блок-схемы идут только тонкие соединительные линии
    (доля ≤ max_ink), а по самой фигуре резать не хочется. Если подходящей
    строки нет — режем ровно по границе.
    connectors=True — в месте разрыва рисуется символ «соединитель» ГОСТ 19.701-90
    (кружок с номером) снизу листа и сверху следующего, на оси линии потока.
    """
    with PILImage.open(io.BytesIO(data)) as im:
        im = im.convert("RGB")
        w, h = im.size
        chunk = int(w * max_ratio)
        if h <= chunk or chunk <= 0:
            return [data]
        bg = im.getpixel((0, 0))
        px = im.load()
        xs = range(0, w, max(1, w // 600))

        def ink(y: int) -> int:
            return sum(1 for x in xs if abs(px[x, y][0] - bg[0]) + abs(px[x, y][1] - bg[1])
                       + abs(px[x, y][2] - bg[2]) > 60)

        pieces, top = [], 0
        while h - top > chunk:
            target = top + chunk
            lo = max(top + chunk // 2, int(target - chunk * tolerance))
            # цена строки: число «чернильных» отсчётов (линии) + штраф за удаление
            # от границы: одна лишняя линия стоит как 1/8 листа
            best_y, best_cost, best_ink = target, float("inf"), 1.0
            for y in range(target, lo, -1):
                n = ink(y)
                cost = n + 8.0 * (target - y) / chunk
                if cost < best_cost:
                    best_y, best_cost, best_ink = y, cost, n / len(xs)
                    if n == 0:
                        break
            cut = best_y if best_ink <= max_ink else target
            pieces.append((im.crop((0, top, w, cut)), _line_x(px, w, cut, bg)))
            top = cut
        pieces.append((im.crop((0, top, w, h)), None))
        if connectors:
            pieces = _add_connectors(pieces, w, bg)
        out = []
        for p, _ in pieces:
            buf = io.BytesIO()
            p.save(buf, format="PNG")
            out.append(buf.getvalue())
        return out


def _line_x(px, w: int, y: int, bg) -> int:
    """x линии потока в строке разреза — медиана «чернильных» пикселей (или центр)."""
    xs = [x for x in range(w) if sum(abs(px[x, y][i] - bg[i]) for i in range(3)) > 60]
    return xs[len(xs) // 2] if xs else w // 2


def _add_connectors(pieces, w: int, bg):
    """Кружок с номером: снизу листа k (после разреза) и сверху листа k+1."""
    from PIL import ImageDraw, ImageFont
    d = max(24, int(w * 0.045))            # диаметр кружка ~ высоте строки текста схемы
    pad = d * 2                            # добавляемое поле (линия + кружок)
    lw = max(1, d // 12)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", int(d * 0.6))
    except OSError:
        font = ImageFont.load_default()

    def circle(draw, cx, cy, n):
        draw.ellipse((cx - d // 2, cy - d // 2, cx + d // 2, cy + d // 2), outline="black", width=lw, fill=bg)
        txt = str(n)
        tw, th = draw.textbbox((0, 0), txt, font=font)[2:]
        draw.text((cx - tw / 2, cy - th / 2 - d * 0.05), txt, fill="black", font=font)

    out = []
    for k, (piece, cut_x) in enumerate(pieces):
        pw, ph = piece.size
        top_pad = pad if k > 0 else 0
        bot_pad = pad if cut_x is not None else 0
        canvas = PILImage.new("RGB", (pw, ph + top_pad + bot_pad), bg)
        canvas.paste(piece, (0, top_pad))
        draw = ImageDraw.Draw(canvas)
        if k > 0:                                  # вход: кружок сверху → линия вниз к схеме
            x = pieces[k - 1][1]
            draw.line((x, d, x, top_pad), fill="black", width=lw)
            circle(draw, x, d // 2 + lw, k)
        if cut_x is not None:                      # выход: линия вниз → кружок снизу
            y0 = top_pad + ph
            draw.line((cut_x, y0, cut_x, y0 + pad - d), fill="black", width=lw)
            circle(draw, cut_x, y0 + pad - d // 2 - lw, k + 1)
        out.append((canvas, cut_x))
    return out


def drawio_to_png(xml: str, page: int | None = None, scale: float = 2.0, timeout: float = 120) -> bytes:
    """draw.io XML → PNG через drawio CLI (+ xvfb-run, если есть). Ошибка, если CLI нет."""
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
        cmd = [exe, "-x", "-f", "png", "-s", str(scale), "-o", out]
        if page is not None:
            cmd += ["-p", str(page)]
        cmd.append(src)
        if shutil.which("xvfb-run"):
            cmd = ["xvfb-run", "-a"] + cmd
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if not os.path.isfile(out):
            raise ValueError(f"drawio не создал PNG: {(r.stderr or r.stdout).strip()[-300:]}")
        with open(out, "rb") as f:
            return f.read()
