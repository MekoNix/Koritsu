"""
_routing — общая ортогональная маршрутизация рёбер для диаграмм классов и объектов.

Блоки — прямоугольники (x, y, w, h); коридоры — свободные полосы между рядами
(row_corridors, y) и между столбцами (col_corridors, x). Маршрут — список
промежуточных точек для draw.io (`<Array as="points">`).
"""

Rect = tuple[int, int, int, int]
Pt = tuple[int, int]


def seg_hits_rect(x1: int, y1: int, x2: int, y2: int, rect: Rect, m: int) -> bool:
    """Пересекает ли ось-параллельный отрезок прямоугольник с отступом m."""
    rx, ry, rw, rh = rect
    lx, rx2 = rx - m, rx + rw + m
    ly, ry2 = ry - m, ry + rh + m
    if x1 == x2:
        sy1, sy2 = min(y1, y2), max(y1, y2)
        return lx < x1 < rx2 and sy1 < ry2 and sy2 > ly
    if y1 == y2:
        sx1, sx2 = min(x1, x2), max(x1, x2)
        return ly < y1 < ry2 and sx1 < rx2 and sx2 > lx
    return False


def path_clear(pts: list[Pt], obstacles: list[Rect], m: int) -> bool:
    for i in range(len(pts) - 1):
        x1, y1 = pts[i]
        x2, y2 = pts[i + 1]
        if any(seg_hits_rect(x1, y1, x2, y2, r, m) for r in obstacles):
            return False
    return True


def plan_route(ex: int, ey: int, nx: int, ny: int,
               obstacles: list[Rect],
               row_corridors: list[int], col_corridors: list[int],
               m: int, prefer_corridor: bool = False) -> list[Pt]:
    """
    Ортогональный маршрут (ex,ey) → (nx,ny) в обход препятствий.

    Порядок: прямая → L (гориз.→верт.) → L (верт.→гориз.) → U через ближайший
    горизонтальный/вертикальный коридор → аварийный обход над всеми блоками.
    prefer_corridor=True: U-маршрут через коридор пробуется раньше L-образных
    (для вертикальных связей между рядами — чтобы не идти вдоль верха блоков).
    """
    if ex == nx and ey == ny:
        return []
    if (ex == nx or ey == ny) and path_clear([(ex, ey), (nx, ny)], obstacles, m):
        return []

    def _l_shapes():
        for wp in ((nx, ey), (ex, ny)):
            if wp in ((ex, ey), (nx, ny)):
                continue
            if path_clear([(ex, ey), wp, (nx, ny)], obstacles, m):
                return [wp]
        return None

    def _u_shapes():
        best, best_cost = None, float("inf")
        for cy in row_corridors:
            if not (min(ey, ny) <= cy <= max(ey, ny)):
                continue
            pts = [(ex, ey), (ex, cy), (nx, cy), (nx, ny)]
            if path_clear(pts, obstacles, m):
                cost = abs(ey - cy) + abs(ny - cy)
                if cost < best_cost:
                    best, best_cost = [(ex, cy), (nx, cy)], cost
        for cx in col_corridors:
            pts = [(ex, ey), (cx, ey), (cx, ny), (nx, ny)]
            if path_clear(pts, obstacles, m):
                cost = abs(ex - cx) + abs(nx - cx) + 20     # штраф: обход сбоку хуже
                if cost < best_cost:
                    best, best_cost = [(cx, ey), (cx, ny)], cost
        return best

    order = (_u_shapes, _l_shapes) if prefer_corridor else (_l_shapes, _u_shapes)
    for fn in order:
        r = fn()
        if r:
            return r

    # U через любой коридор без ограничения по диапазону
    for cy in row_corridors:
        pts = [(ex, ey), (ex, cy), (nx, cy), (nx, ny)]
        if path_clear(pts, obstacles, m):
            return [(ex, cy), (nx, cy)]

    tops = [r[1] for r in obstacles]
    safe_y = (min(tops) - 3 * m) if tops else (min(ey, ny) - 3 * m)
    return [(ex, safe_y), (nx, safe_y)]


def edge_sides(src: Rect, tgt: Rect) -> tuple[str, str]:
    """Стороны выхода/входа: вертикально, если блоки в разных рядах, иначе сбоку."""
    sx, sy, sw, sh = src
    tx, ty, tw, th = tgt
    if ty >= sy + sh:
        return "bottom", "top"
    if ty + th <= sy:
        return "top", "bottom"
    return ("left", "right") if (tx + tw / 2) < (sx + sw / 2) else ("right", "left")


def spread(side: str, i: int, n: int) -> tuple[float, float]:
    f = (i + 1) / (n + 1)
    if side == "top":
        return (f, 0.0)
    if side == "bottom":
        return (f, 1.0)
    if side == "left":
        return (0.0, f)
    return (1.0, f)


def assign_ports(edges: list[tuple], rects: dict[str, Rect],
                 reserved: dict[tuple[str, str], list[int]] | None = None
                 ) -> dict[tuple, tuple[float, float, float, float]]:
    """
    Порты (exitX, exitY, entryX, entryY) для рёбер (key, src, tgt).
    На одной стороне блока порты распределяются равномерно и упорядочены по
    x/y другого конца — меньше пересечений. reserved[(node, side)] — абсолютные
    координаты уже занятых точек (например, ствол junction), они участвуют в
    распределении, но не получают порт.
    """
    by_side: dict[tuple[str, str], list[tuple[int, object]]] = {}
    for node_side, coords in (reserved or {}).items():
        for c in coords:
            by_side.setdefault(node_side, []).append((c, None))

    sides: dict[object, tuple[str, str]] = {}
    for key, src, tgt in edges:
        if src not in rects or tgt not in rects:
            continue
        ex_side, en_side = edge_sides(rects[src], rects[tgt])
        sides[key] = (ex_side, en_side)
        sx, sy, sw, sh = rects[src]
        tx, ty, tw, th = rects[tgt]
        s_other = (tx + tw // 2) if ex_side in ("top", "bottom") else (ty + th // 2)
        t_other = (sx + sw // 2) if en_side in ("top", "bottom") else (sy + sh // 2)
        by_side.setdefault((src, ex_side), []).append((s_other, ("x", key)))
        by_side.setdefault((tgt, en_side), []).append((t_other, ("n", key)))

    ports: dict[object, list] = {}
    for (node, side), items in by_side.items():
        items.sort(key=lambda it: it[0])
        n = len(items)
        for i, (_, tag) in enumerate(items):
            if tag is None:
                continue
            which, key = tag
            ports.setdefault(key, [None, None])[0 if which == "x" else 1] = spread(side, i, n)

    result = {}
    for key, (ex, en) in ports.items():
        ex = ex or (0.5, 1.0)
        en = en or (0.5, 0.0)
        result[key] = (ex[0], ex[1], en[0], en[1])
    return result


def abs_point(rect: Rect, fx: float, fy: float) -> Pt:
    x, y, w, h = rect
    return (x + int(round(fx * w)), y + int(round(fy * h)))


def points_xml(waypoints: list[Pt]) -> str:
    if not waypoints:
        return '<mxGeometry relative="1" as="geometry"/>'
    pts = "".join(f'<mxPoint x="{px}" y="{py}"/>' for px, py in waypoints)
    return f'<mxGeometry relative="1" as="geometry"><Array as="points">{pts}</Array></mxGeometry>'
