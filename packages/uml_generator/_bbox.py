"""
_bbox — ограничивающие рамки диаграммы: узлы, подписи, ряды.

Рамка — `(x, y, w, h)` в координатах draw.io (ось y вниз). Раскладка обязана
расставить рамки так, чтобы они не пересекались: без этого блоки наезжают друг
на друга, а подписи рёбер ложатся поверх блоков — на собранной диаграмме это
видно сразу и читать её нельзя.

Почему рамки, а не «примерные» шаги сетки. Размер блока определяется его
содержимым: ширина — самой длинной строкой (заголовок, поля, методы) через
`kyotsu.text`, высота — числом строк и размером шрифта темы. Значит, и проверять
надо настоящий прямоугольник, а не считать, что «блок влезет в клетку». То же с
подписью ребра: у неё есть ширина текста и высота строки, и место ей надо искать
так же, как блоку, — рядом с точкой привязки, но в стороне от чужих рамок.

Здесь только геометрия: ни один потребитель не знает, что рисуется, — это общее
для диаграммы классов (`builder.py`) и диаграммы объектов (`objektis/builder.py`),
а также для проверки уже собранного XML (`boxes_from_xml`).
"""
import re

from ._routing import seg_hits_rect
from ._text import text_width

Box = tuple[float, float, float, float]     # x, y, w, h


# ── Элементарные операции ─────────────────────────────────────────────────────

def inflate(box: Box, m: float) -> Box:
    x, y, w, h = box
    return (x - m, y - m, w + 2 * m, h + 2 * m)


def overlap(a: Box, b: Box, gap: float = 0.0) -> tuple[float, float] | None:
    """Глубина пересечения рамок с требуемым зазором, либо None.

    Зазор считается нарушенным при расстоянии *меньше* gap: соприкосновение
    ровно на gap законно (ряды и стоят на таком расстоянии).
    """
    ox = min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0]) + gap
    oy = min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1]) + gap
    return (ox, oy) if ox > 0 and oy > 0 else None


def find_overlaps(boxes: dict[str, Box], gap: float = 0.0) -> list[tuple[str, str, float, float]]:
    """Все пары пересекающихся рамок: `(имя_a, имя_b, глубина_x, глубина_y)`.

    Перебор парами: узлов на диаграмме десятки, экономить не на чем, а любой
    ускоряющий индекс пришлось бы проверять отдельно.
    """
    items = list(boxes.items())
    bad = []
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            o = overlap(items[i][1], items[j][1], gap)
            if o:
                bad.append((items[i][0], items[j][0], o[0], o[1]))
    return bad


def union(boxes) -> Box:
    """Рамка вокруг всех — холст диаграммы."""
    xs = [b[0] for b in boxes]
    ys = [b[1] for b in boxes]
    x2 = [b[0] + b[2] for b in boxes]
    y2 = [b[1] + b[3] for b in boxes]
    return (min(xs), min(ys), max(x2) - min(xs), max(y2) - min(ys))


# ── Ряды ──────────────────────────────────────────────────────────────────────

def spread_row(row: list[str], widths: dict[str, int], start_x: int, h_gap: int) -> dict[str, int]:
    """x блоков ряда подряд слева направо с зазором h_gap."""
    xs, x = {}, start_x
    for n in row:
        xs[n] = x
        x += widths[n] + h_gap
    return xs


def enforce_row_gap(row: list[str], xs: dict[str, int], widths: dict[str, int],
                    start_x: int, h_gap: int) -> None:
    """
    Развести блоки ряда так, чтобы между ними осталось не меньше h_gap.

    Вызывается после любого сдвига (центрирование родителей над потомками):
    порядок блоков в ряду сохраняется, а тот, кому не хватило места, уезжает
    вправо. Иначе сдвиг «на середину потомков» кладёт блок на соседа.
    """
    x_min = start_x
    for n in row:
        if xs[n] < x_min:
            xs[n] = x_min
        x_min = xs[n] + widths[n] + h_gap


def stack_rows(rows: list[list[str]], xs: dict[str, int], widths: dict[str, int],
               heights: dict[str, int], start_y: int, gaps: list[int]
               ) -> tuple[dict[str, Box], list[int], list[int], list[int]]:
    """
    Разложить ряды по вертикали: высота ряда — по самому высокому блоку,
    под рядом остаётся `gaps[i]` (у каждого ряда свой: в зазоре живут коридоры
    маршрутов и точки слияния наследования, и им бывает нужно больше места).

    Возвращает (рамки, верх рядов, низ рядов, y коридоров под рядами).
    """
    rects: dict[str, Box] = {}
    tops, bottoms, corridors = [], [], []
    y = start_y
    for ri, row in enumerate(rows):
        row_h = max(heights[n] for n in row)
        tops.append(y)
        for n in row:
            rects[n] = (xs[n], y, widths[n], heights[n])
        bottoms.append(y + row_h)
        corridors.append(y + row_h + gaps[ri] // 2)
        y += row_h + gaps[ri]
    return rects, tops, bottoms, corridors


# ── Подписи ───────────────────────────────────────────────────────────────────

def label_size(text: str, font: int) -> tuple[float, float]:
    """Рамка подписи: ширина по тексту, высота — строка шрифта с интерлиньяжем."""
    return (text_width(text, font) + 6, font * 1.4)


def label_box(anchor: tuple[float, float], off: tuple[int, int],
              size: tuple[float, float]) -> Box:
    """
    Рамка подписи ребра по точке привязки и смещению.

    draw.io рисует `edgeLabel` по центру: точка привязки (конец ребра) плюс
    смещение — это центр текста, а не его угол. Здесь тот же расчёт, что и в
    рендере, чтобы проверка рамок совпадала с тем, что видно на картинке.
    """
    w, h = size
    return (anchor[0] + off[0] - w / 2, anchor[1] + off[1] - h / 2, w, h)


def place_label(anchor: tuple[float, float], size: tuple[float, float],
                dirs: list[tuple[int, int]], obstacles: list[Box],
                near: int = 12, step: int = 14, tries: int = 5) -> tuple[int, int]:
    """
    Смещение подписи от точки привязки: первое место, где её рамка никого не задевает.

    Пробуем направления в порядке предпочтения (первым — «наружу» от блока, куда
    ребро входит), отодвигая подпись всё дальше. Раньше смещение было постоянным
    (±12 px), и подпись у входа сбоку неизбежно ложилась на сам блок: её ширина
    больше смещения.

    Свободного места может не найтись совсем (подпись зажата между блоками). Тогда
    берём наименее плохое из проверенных мест — то, где рамка перекрыта меньше
    всего: подпись, задевшая угол соседа, читается, а уехавшая вслепую по первому
    направлению может лечь ровно на середину чужого блока.
    """
    half_w, half_h = size[0] / 2, size[1] / 2

    def offset(dx: int, dy: int, k: int) -> tuple[int, int]:
        return (int(dx * (near + half_w + k * step)) if dx else 0,
                int(dy * (near + half_h + k * step)) if dy else 0)

    best, best_cost = None, float("inf")
    for k in range(tries):
        for dx, dy in dirs:
            off = offset(dx, dy, k)
            box = label_box(anchor, off, size)
            cost = sum(o[0] * o[1] for o in
                       (overlap(box, ob) for ob in obstacles) if o)
            if cost == 0:
                return off
            if cost < best_cost:
                best, best_cost = off, cost
    return best if best is not None else offset(*dirs[0], tries)


def label_dirs(nx: float, ny: float) -> list[tuple[int, int]]:
    """Порядок направлений для подписи по стороне входа/выхода ребра (доли 0..1)."""
    if ny >= 1.0:
        return [(0, 1), (1, 1), (-1, 1), (1, 0), (-1, 0)]
    if ny <= 0.0:
        return [(0, -1), (1, -1), (-1, -1), (1, 0), (-1, 0)]
    if nx <= 0.0:
        return [(-1, 0), (-1, -1), (-1, 1), (0, -1), (0, 1)]
    return [(1, 0), (1, -1), (1, 1), (0, -1), (0, 1)]


# ── Проверка готового XML ─────────────────────────────────────────────────────

_CELL = re.compile(r'<mxCell\b.*?(?:/>|</mxCell>)', re.S)
_GEOM = re.compile(r'<mxGeometry x="(-?\d+)" y="(-?\d+)" width="(\d+)" height="(\d+)"')
_OFFSET = re.compile(r'<mxPoint x="(-?\d+)" y="(-?\d+)" as="offset"')
_POINT = re.compile(r'<mxPoint x="(-?\d+)" y="(-?\d+)"/>')


def _attr(cell: str, name: str) -> str:
    m = re.search(rf'\b{name}="([^"]*)"', cell)
    return m.group(1) if m else ""


def _parse_cells(xml: str):
    """Разбор ячеек draw.io XML: (узлы, рёбра, сырые подписи)."""
    nodes: dict[str, Box] = {}
    edges: dict[str, dict] = {}
    # (id, id ребра, доля вдоль ребра, смещение, текст, размер шрифта)
    labels: list[tuple[str, str, float, tuple[int, int], str, int]] = []
    for cell in _CELL.findall(xml):
        cid, style, parent = _attr(cell, "id"), _attr(cell, "style"), _attr(cell, "parent")
        if 'vertex="1"' in cell and "edgeLabel" not in style and parent == "1":
            g = _GEOM.search(cell)
            if g:
                nodes[cid] = tuple(int(v) for v in g.groups())
        elif 'edge="1"' in cell:
            ex = re.search(r'exitX=([-\d.]+);exitY=([-\d.]+)', style)
            en = re.search(r'entryX=([-\d.]+);entryY=([-\d.]+)', style)
            edges[cid] = {
                "src": _attr(cell, "source"), "tgt": _attr(cell, "target"),
                "exit": tuple(float(v) for v in ex.groups()) if ex else (0.5, 1.0),
                "entry": tuple(float(v) for v in en.groups()) if en else (0.5, 0.0),
                "pts": [(int(a), int(b)) for a, b in _POINT.findall(cell)],
            }
        elif "edgeLabel" in style:
            off = _OFFSET.search(cell)
            rel = re.search(r'<mxGeometry x="(-?[\d.]+)"', cell)
            font = re.search(r'fontSize=(\d+)', style)
            labels.append((cid, parent, float(rel.group(1)) if rel else 1.0,
                           (int(off.group(1)), int(off.group(2))) if off else (0, 0),
                           _attr(cell, "value"), int(font.group(1)) if font else 10))

    return nodes, edges, labels


def _anchor(edge: dict, rel: float, nodes: dict[str, Box]) -> tuple[float, float] | None:
    """Точка привязки подписи: конец ребра у цели (rel > 0) или у источника."""
    src, tgt = nodes.get(edge["src"]), nodes.get(edge["tgt"])
    if rel > 0:
        if tgt is None:
            return None
        return (tgt[0] + edge["entry"][0] * tgt[2], tgt[1] + edge["entry"][1] * tgt[3])
    if src is None:
        return None
    return (src[0] + edge["exit"][0] * src[2], src[1] + edge["exit"][1] * src[3])


def boxes_from_xml(xml: str) -> tuple[dict[str, Box], dict[str, Box]]:
    """
    Рамки узлов и подписей по готовому draw.io XML.

    Возвращает `(узлы, подписи)`: две карты «идентификатор ячейки → рамка».
    Считается по тому же XML, который уходит в drawio, — проверка не верит
    раскладке на слово, а меряет то, что нарисуется.

    Подпись ребра позиционируется относительно ребра: `x="1"` — конец у цели,
    `x="-1"` — начало у источника; к этой точке прибавляется смещение, и центр
    рамки оказывается там же, где draw.io нарисует текст.
    """
    nodes, edges, labels = _parse_cells(xml)
    out: dict[str, Box] = {}
    for cid, parent, rel, off, value, font in labels:
        edge = edges.get(parent)
        if edge is None:
            continue
        anchor = _anchor(edge, rel, nodes)
        if anchor is None:
            continue
        out[cid] = label_box(anchor, off, label_size(value, font))
    return nodes, out


def paths_from_xml(xml: str) -> dict[str, tuple[str, str, list[tuple[float, float]]]]:
    """
    Ломаные рёбер по готовому XML: `id ребра → (источник, цель, точки)`.

    Точки — от порта выхода через промежуточные до порта входа, ровно так, как
    их нарисует draw.io по `exitX/entryX` и `<Array as="points">`.
    """
    nodes, edges, _ = _parse_cells(xml)
    out = {}
    for cid, e in edges.items():
        src, tgt = nodes.get(e["src"]), nodes.get(e["tgt"])
        if src is None or tgt is None:
            continue
        pts = [(src[0] + e["exit"][0] * src[2], src[1] + e["exit"][1] * src[3])]
        pts += [(float(x), float(y)) for x, y in e["pts"]]
        pts.append((tgt[0] + e["entry"][0] * tgt[2], tgt[1] + e["entry"][1] * tgt[3]))
        out[cid] = (e["src"], e["tgt"], pts)
    return out


def find_crossings(xml: str) -> list[tuple[str, str]]:
    """
    Рёбра, проходящие сквозь чужие блоки: `[(id ребра, id блока), …]`.

    Свои концы ребру не в счёт: линия выходит из рамки источника и входит в
    рамку цели. Проверяются только ось-параллельные звенья — других раскладка
    не строит, а draw.io рисует ломаную ровно по ним.
    """
    nodes, _, _ = _parse_cells(xml)
    bad = []
    for eid, (src, tgt, pts) in paths_from_xml(xml).items():
        for i in range(len(pts) - 1):
            (x1, y1), (x2, y2) = pts[i], pts[i + 1]
            for nid, r in nodes.items():
                if nid in (src, tgt) or (eid, nid) in bad:
                    continue
                if seg_hits_rect(x1, y1, x2, y2, r, 0):
                    bad.append((eid, nid))
    return bad
