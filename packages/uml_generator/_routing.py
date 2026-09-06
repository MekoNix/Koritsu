"""
_routing — общая ортогональная маршрутизация рёбер для диаграмм классов и объектов.

Блоки — прямоугольники (x, y, w, h); коридоры — свободные полосы между рядами
(row_corridors, y) и между столбцами (col_corridors, x). Маршрут — список
промежуточных точек для draw.io (`<Array as="points">`).
"""
import heapq

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
               m: int, prefer_corridor: bool = False,
               grid: "CorridorGrid | None" = None,
               exit_side: str = "", entry_side: str = "") -> list[Pt]:
    """
    Ортогональный маршрут (ex,ey) → (nx,ny) в обход препятствий.

    Порядок: прямая → L (гориз.→верт.) → L (верт.→гориз.) → U через ближайший
    горизонтальный/вертикальный коридор → поиск по сетке коридоров (`grid`) →
    аварийный обход над всеми блоками.
    prefer_corridor=True: U-маршрут через коридор пробуется раньше L-образных
    (для вертикальных связей между рядами — чтобы не идти вдоль верха блоков).

    Без `grid` последним средством остаётся линия поверх всех блоков: она их
    режет насквозь. Сетка такой обход находит честно, поэтому её стоит
    передавать всегда, когда рамки блоков известны.
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

    if grid is not None:
        wps = grid.route((ex, ey), exit_side, (nx, ny), entry_side, obstacles)
        if wps is not None:
            return wps

    tops = [r[1] for r in obstacles]
    safe_y = (min(tops) - 3 * m) if tops else (min(ey, ny) - 3 * m)
    return [(ex, safe_y), (nx, safe_y)]


class CorridorGrid:
    """
    Сетка свободных полос: горизонтали между рядами, вертикали между столбцами
    плюс внешнее кольцо вокруг всей диаграммы.

    Зачем она. L- и U-образные попытки в `plan_route` покрывают только соседние
    ряды; когда они не проходят, прежним последним средством была линия поверх
    всех блоков — она резала их насквозь, и это хорошо видно на собранной
    диаграмме. Здесь маршрут ищется по звеньям сетки, а каждое звено заранее
    проверено на пересечение с рамками блоков, поэтому найденный путь блоков не
    задевает. Обход существует всегда: кольцо вокруг диаграммы свободно по
    построению, а горизонтали идут в зазорах между рядами.

    Алгоритм — Дейкстра по узлам сетки с платой за поворот (`_TURN`): без платы
    путь той же длины может оказаться «лесенкой» из десятка изломов. Пишем сами,
    а не берём библиотеку: сетка маленькая (десятки линий), а зависимость ради
    поиска на ней не окупается.
    """

    _TURN = 40          # плата за поворот в единицах длины — ровные пути дешевле

    def __init__(self, rects: list[Rect], row_corridors: list[int],
                 col_corridors: list[int], m: int):
        pad = 2 * m + 10
        left = min(r[0] for r in rects) - pad
        right = max(r[0] + r[2] for r in rects) + pad
        top = min(r[1] for r in rects) - pad
        bottom = max(r[1] + r[3] for r in rects) + pad
        self.xs = sorted({left, right} | {c for c in col_corridors if left < c < right})
        self.ys = sorted({top, bottom} | {c for c in row_corridors if top < c < bottom})
        self.rects = rects
        self.m = m
        # свободность звеньев считаем один раз: она не зависит от ребра, потому
        # что коридоры свободны от всех блоков сразу
        self.h_free = [[path_clear([(self.xs[i], y), (self.xs[i + 1], y)], rects, m)
                        for i in range(len(self.xs) - 1)] for y in self.ys]
        self.v_free = [[path_clear([(x, self.ys[j]), (x, self.ys[j + 1])], rects, m)
                        for j in range(len(self.ys) - 1)] for x in self.xs]

    # ── стыковка порта с сеткой ───────────────────────────────────────────────

    def _stub(self, pt: Pt, side: str, obstacles: list[Rect]):
        """
        Вывести точку порта на ближайшую линию сетки: сначала в сторону `side`,
        а если там ни одна линия не достижима — в любую другую.

        Возвращает (точка на линии, «горизонтальная ли линия», индекс линии).
        Отрезок от порта до линии проверяется без рамок собственных концов ребра:
        порт лежит на границе своего блока и иначе всегда «задевал» бы его.
        Запасной перебор нужен концам, которые лежат не на границе блока, а
        внутри коридора (точка слияния наследования): «наружу» им идти некуда.
        """
        x, y = pt
        vert = [(True, j, v) for j, v in enumerate(self.ys)]      # горизонтальные линии
        horz = [(False, i, v) for i, v in enumerate(self.xs)]     # вертикальные линии
        if side == "bottom":
            first = [c for c in vert if c[2] > y]
        elif side == "top":
            first = [c for c in vert if c[2] < y]
        elif side == "right":
            first = [c for c in horz if c[2] > x]
        else:
            first = [c for c in horz if c[2] < x]
        rest = [c for c in vert + horz if c not in first]
        for horizontal, idx, v in (sorted(first, key=lambda c: abs(c[2] - (y if c[0] else x)))
                                   + sorted(rest, key=lambda c: abs(c[2] - (y if c[0] else x)))):
            end = (x, v) if horizontal else (v, y)
            if end != pt and path_clear([pt, end], obstacles, self.m):
                return end, horizontal, idx
        return None

    def _entries(self, stub: Pt, horizontal: bool, line: int, obstacles: list[Rect]):
        """Узлы сетки, достижимые от точки стыковки по её же линии."""
        out = []
        if horizontal:
            y = self.ys[line]
            for i, x in enumerate(self.xs):
                if path_clear([stub, (x, y)], obstacles, self.m):
                    out.append(((i, line), abs(x - stub[0])))
        else:
            x = self.xs[line]
            for j, y in enumerate(self.ys):
                if path_clear([stub, (x, y)], obstacles, self.m):
                    out.append(((line, j), abs(y - stub[1])))
        return out

    # ── поиск ─────────────────────────────────────────────────────────────────

    def route(self, start: Pt, exit_side: str, end: Pt, entry_side: str,
              obstacles: list[Rect]) -> list[Pt] | None:
        """Промежуточные точки маршрута start → end или None, если пути нет."""
        s = self._stub(start, exit_side, obstacles)
        t = self._stub(end, entry_side, obstacles)
        if s is None or t is None:
            return None
        s_pt, s_h, s_line = s
        t_pt, t_h, t_line = t
        goals = dict(self._entries(t_pt, t_h, t_line, obstacles))
        if not goals:
            return None

        # состояние — (узел, направление прихода): плата за поворот зависит от него
        best: dict[tuple, float] = {}
        heap = []
        for node, cost in self._entries(s_pt, s_h, s_line, obstacles):
            d = "h" if s_h else "v"
            heapq.heappush(heap, (cost, node, d, [s_pt]))
        found = None
        while heap:
            cost, node, d, path = heapq.heappop(heap)
            key = (node, d)
            if key in best and best[key] <= cost:
                continue
            best[key] = cost
            i, j = node
            pt = (self.xs[i], self.ys[j])
            if node in goals:
                found = path + [pt, t_pt]
                break
            for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                ni, nj = i + di, j + dj
                if not (0 <= ni < len(self.xs) and 0 <= nj < len(self.ys)):
                    continue
                if di and not self.h_free[j][min(i, ni)]:
                    continue
                if dj and not self.v_free[i][min(j, nj)]:
                    continue
                nd = "h" if di else "v"
                step = abs(self.xs[ni] - self.xs[i]) + abs(self.ys[nj] - self.ys[j])
                heapq.heappush(heap, (cost + step + (0 if nd == d else self._TURN),
                                      (ni, nj), nd, path + [pt]))
        if found is None:
            return None
        return _simplify([start] + found + [end])[1:-1]


def _simplify(pts: list[Pt]) -> list[Pt]:
    """Убрать повторы и точки на прямой: draw.io рисует по изломам."""
    out: list[Pt] = []
    for p in pts:
        if out and out[-1] == p:
            continue
        out.append(p)
    i = 1
    while i < len(out) - 1:
        a, b, c = out[i - 1], out[i], out[i + 1]
        if (a[0] == b[0] == c[0]) or (a[1] == b[1] == c[1]):
            del out[i]
        else:
            i += 1
    return out


def edge_sides(src: Rect, tgt: Rect) -> tuple[str, str]:
    """Стороны выхода/входа: вертикально, если блоки в разных рядах, иначе сбоку."""
    sx, sy, sw, sh = src
    tx, ty, tw, th = tgt
    if ty >= sy + sh:
        return "bottom", "top"
    if ty + th <= sy:
        return "top", "bottom"
    return ("left", "right") if (tx + tw / 2) < (sx + sw / 2) else ("right", "left")


def side_of(fx: float, fy: float) -> str:
    """Сторона блока по долям порта: куда ребро уходит от блока."""
    if fy >= 1.0:
        return "bottom"
    if fy <= 0.0:
        return "top"
    return "left" if fx <= 0.0 else "right"


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
