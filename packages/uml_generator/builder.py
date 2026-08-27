"""
Builder — генерирует draw.io XML для UML-диаграммы классов.
"""
import html as _html
import re as _re
from .extractor import ClassInfo, FieldInfo, MethodInfo

# ── Layout constants ───────────────────────────────────────────────────────────
CHAR_W       = 7     # оценка px/символ при font-size 11
PAD_X        = 28    # суммарный горизонтальный padding внутри swimlane
MIN_W        = 160   # минимальная ширина блока
H_GAP        = 80    # горизонтальный зазор между блоками
V_GAP        = 100   # вертикальный зазор между рядами
HEADER_H     = 32    # высота заголовка swimlane
ROW_H        = 22    # высота строки (поле/метод)
SEP_H        = 8     # разделитель полей/методов
MIN_H        = 70    # минимальная высота блока
START_X      = 60
START_Y      = 60
MAX_PER_ROW  = 4     # макс. классов в одном ряду
ROUTE_MARGIN = 18    # зазор вокруг блоков при построении маршрута

# ── Dark-theme palette ─────────────────────────────────────────────────────────
_CLASS_FILL    = "#1e293b"
_IFACE_FILL    = "#0f1729"
_STRUCT_FILL   = "#172033"
_CLASS_STROKE  = "#475569"
_IFACE_STROKE  = "#6366f1"
_STRUCT_STROKE = "#0ea5e9"
_HEADER_FONT   = "#f1f5f9"
_MEMBER_FONT   = "#94a3b8"
_EDGE_COLOR    = "#64748b"

_ACCESS = {"public": "+", "protected": "#", "private": "-", "internal": "~"}

_COLOR_INHERIT   = "#cbd5e1"
_COLOR_REALIZE   = "#cbd5e1"
_COLOR_COMPOSE   = "#cbd5e1"
_COLOR_AGGREGATE = "#cbd5e1"
_COLOR_DEPEND    = "#cbd5e1"


# ── Helpers ────────────────────────────────────────────────────────────────────

def _esc(s: str) -> str:
    return _html.escape(s, quote=True)


def _bare_type(type_str: str) -> str:
    s = type_str
    s = _re.sub(r'\b(const|volatile|static|mutable|explicit|inline)\b', '', s)
    m = _re.search(r'<([^<>]+)>', s)
    if m:
        s = m.group(1)
    s = _re.sub(r'[*&\[\]\s]', '', s)
    return s.strip()


def _method_types(mth: MethodInfo) -> list[str]:
    types = []
    if mth.return_type:
        types.append(_bare_type(mth.return_type))
    params = mth.params.strip("()")
    for part in params.split(","):
        part = part.strip()
        if not part:
            continue
        tokens = part.split()
        type_part = " ".join(tokens[:-1]) if len(tokens) >= 2 else (tokens[0] if tokens else "")
        types.append(_bare_type(type_part))
    return [t for t in types if t]


def _is_pointer_or_ref(type_str: str) -> bool:
    return bool(_re.search(r'[*&]', type_str))


# ── Dynamic sizing ─────────────────────────────────────────────────────────────

def _class_width(cls: ClassInfo) -> int:
    """Ширина блока по самой длинной строке текста."""
    lines: list[str] = [cls.name]
    for fld in cls.fields:
        sym = _ACCESS.get(fld.access, "~")
        lines.append(f"{sym} {fld.name}: {fld.type_str}")
    for mth in cls.methods:
        sym = _ACCESS.get(mth.access, "~")
        if mth.is_constructor:
            lines.append(f"{sym} {mth.name}{mth.params}")
        else:
            lines.append(f"{sym} {mth.name}{mth.params}: {mth.return_type}")
    longest = max(len(s) for s in lines) if lines else 0
    return max(MIN_W, longest * CHAR_W + PAD_X)


def _class_height(cls: ClassInfo) -> int:
    h = HEADER_H
    if cls.fields:
        h += len(cls.fields) * ROW_H
    if cls.fields and cls.methods:
        h += SEP_H
    if cls.methods:
        h += len(cls.methods) * ROW_H
    return max(h, MIN_H)


# ── Relations ──────────────────────────────────────────────────────────────────

def _detect_relations(classes: list[ClassInfo]) -> list[tuple[str, str, str]]:
    names  = {c.name for c in classes}
    by_name = {c.name: c for c in classes}
    PRIO = {"inheritance": 0, "realization": 1,
            "composition": 2, "aggregation": 3, "dependency": 4}
    best: dict[tuple[str, str], str] = {}

    def _add(src: str, tgt: str, rel: str):
        if tgt not in names or tgt == src:
            return
        key = (src, tgt)
        if key not in best or PRIO[rel] < PRIO[best[key]]:
            best[key] = rel

    for cls in classes:
        src = cls.name
        for parent in cls.parents:
            if parent not in names:
                continue
            parent_cls = by_name.get(parent)
            _add(src, parent, "realization" if (parent_cls and parent_cls.is_interface) else "inheritance")
        for fld in cls.fields:
            tgt = _bare_type(fld.type_str)
            if tgt in names and tgt != src:
                _add(src, tgt, "aggregation" if _is_pointer_or_ref(fld.type_str) else "composition")
        for mth in cls.methods:
            for tgt in _method_types(mth):
                if tgt in names and tgt != src:
                    _add(src, tgt, "dependency")

    return [(src, tgt, rel) for (src, tgt), rel in best.items()]


# ── Layout ─────────────────────────────────────────────────────────────────────

def _layout(
    classes: list[ClassInfo],
    widths:  dict[str, int],
    heights: dict[str, int],
) -> tuple[dict[str, tuple[int, int]], list[int], list[int]]:
    """
    Топологическая раскладка блоков.
    Возвращает:
      positions      — {name: (x, y)}
      row_corridors  — y-координаты горизонтальных коридоров (между рядами)
      col_corridors  — x-координаты вертикальных коридоров  (между столбцами)
    """
    names   = {c.name for c in classes}
    by_name = {c.name: c for c in classes}

    children:   dict[str, list[str]] = {c.name: [] for c in classes}
    parents_in: dict[str, list[str]] = {}
    for cls in classes:
        in_diag = [p for p in cls.parents if p in names]
        parents_in[cls.name] = in_diag
        for p in in_diag:
            children[p].append(cls.name)

    levels: dict[str, int] = {}
    roots   = [c.name for c in classes if not parents_in.get(c.name)]
    queue   = list(roots)
    for n in queue:
        levels[n] = 0
    visited = set(queue)
    while queue:
        nxt = []
        for n in queue:
            for child in children.get(n, []):
                lvl = levels[n] + 1
                if levels.get(child, -1) < lvl:
                    levels[child] = lvl
                if child not in visited:
                    visited.add(child)
                    nxt.append(child)
        queue = nxt
    for cls in classes:
        if cls.name not in levels:
            levels[cls.name] = 0

    groups: dict[int, list[str]] = {}
    for n, lvl in levels.items():
        groups.setdefault(lvl, []).append(n)

    positions:     dict[str, tuple[int, int]] = {}
    row_corridors: list[int] = []
    col_corridors: list[int] = []
    current_y = START_Y

    for lvl in sorted(groups):
        group = groups[lvl]
        for row_start in range(0, len(group), MAX_PER_ROW):
            sub   = group[row_start: row_start + MAX_PER_ROW]
            row_h = max(heights[n] for n in sub)

            # Расставляем блоки слева направо с их индивидуальной шириной
            current_x = START_X
            for name in sub:
                positions[name] = (current_x, current_y)
                # вертикальный коридор справа от этого блока
                col_corridors.append(current_x + widths[name] + H_GAP // 2)
                current_x += widths[name] + H_GAP

            # горизонтальный коридор под строкой
            row_corridors.append(current_y + row_h + V_GAP // 2)
            current_y += row_h + V_GAP

    return positions, row_corridors, col_corridors


# ── BBox-based routing (по образцу compute_bbox из fragmos) ────────────────────

def _seg_hits_rect(
    x1: int, y1: int, x2: int, y2: int,
    rx: int, ry: int, rw: int, rh: int,
    m: int,
) -> bool:
    """Проверяет, пересекает ли ось-параллельный отрезок прямоугольник (с отступом m)."""
    lx, rx2 = rx - m, rx + rw + m
    ly, ry2 = ry - m, ry + rh + m
    if x1 == x2:        # вертикальный отрезок
        x = x1
        sy1, sy2 = min(y1, y2), max(y1, y2)
        return lx < x < rx2 and sy1 < ry2 and sy2 > ly
    if y1 == y2:        # горизонтальный отрезок
        y = y1
        sx1, sx2 = min(x1, x2), max(x1, x2)
        return ly < y < ry2 and sx1 < rx2 and sx2 > lx
    return False


def _path_clear(
    pts: list[tuple[int, int]],
    obstacles: list[tuple[int, int, int, int]],
    m: int,
) -> bool:
    """True, если ни один отрезок ломаной не пересекает ни один препятствующий bbox."""
    for i in range(len(pts) - 1):
        x1, y1 = pts[i]
        x2, y2 = pts[i + 1]
        for rx, ry, rw, rh in obstacles:
            if _seg_hits_rect(x1, y1, x2, y2, rx, ry, rw, rh, m):
                return False
    return True


def _plan_route(
    ex: int, ey: int,
    nx: int, ny: int,
    obstacles: list[tuple[int, int, int, int]],
    row_corridors: list[int],
    col_corridors: list[int],
    m: int = ROUTE_MARGIN,
) -> list[tuple[int, int]]:
    """
    Строит ортогональный маршрут из (ex,ey) в (nx,ny), обходя препятствия.
    Возвращает список промежуточных точек (waypoints).

    Стратегии (в порядке приоритета):
      1. L-образный маршрут: горизонтально → вертикально
      2. L-образный маршрут: вертикально → горизонтально
      3. U-маршрут через горизонтальный коридор (между рядами)
      4. U-маршрут через вертикальный коридор (между столбцами)
      5. Аварийный выход: уход выше всех блоков
    """
    if ex == nx and ey == ny:
        return []

    # 1. L-горизонтальное → вертикальное
    wp = (nx, ey)
    if _path_clear([(ex, ey), wp, (nx, ny)], obstacles, m):
        return [wp] if wp != (ex, ey) and wp != (nx, ny) else []

    # 2. L-вертикальное → горизонтальное
    wp = (ex, ny)
    if _path_clear([(ex, ey), wp, (nx, ny)], obstacles, m):
        return [wp] if wp != (ex, ey) and wp != (nx, ny) else []

    best: list[tuple[int, int]] | None = None
    best_cost = float("inf")

    # 3. U через горизонтальные коридоры
    for cy in row_corridors:
        pts = [(ex, ey), (ex, cy), (nx, cy), (nx, ny)]
        if _path_clear(pts, obstacles, m):
            cost = abs(ey - cy) + abs(ny - cy)
            if cost < best_cost:
                best_cost = cost
                best = [(ex, cy), (nx, cy)]

    # 4. U через вертикальные коридоры
    for cx in col_corridors:
        pts = [(ex, ey), (cx, ey), (cx, ny), (nx, ny)]
        if _path_clear(pts, obstacles, m):
            cost = abs(ex - cx) + abs(nx - cx)
            if cost < best_cost:
                best_cost = cost
                best = [(cx, ey), (cx, ny)]

    if best:
        return best

    # 5. Аварийный: обход над всеми блоками
    all_tops = [ry for _, ry, _, _ in obstacles]
    safe_y   = (min(all_tops) - 3 * m) if all_tops else (min(ey, ny) - 3 * m)
    return [(ex, safe_y), (nx, safe_y)]


# ── Port assignment ────────────────────────────────────────────────────────────

def _edge_side(
    sx: int, sy: int, sw: int, sh: int,
    tx: int, ty: int, tw: int, th: int,
) -> tuple[str, str]:
    dx = (tx + tw / 2) - (sx + sw / 2)
    dy = (ty + th / 2) - (sy + sh / 2)
    if abs(dy) >= abs(dx):
        return ("top", "bottom") if dy <= 0 else ("bottom", "top")
    return ("left", "right") if dx <= 0 else ("right", "left")


def _assign_ports(
    relations: list[tuple[str, str, str]],
    positions: dict[str, tuple[int, int]],
    widths:    dict[str, int],
    heights:   dict[str, int],
) -> dict[tuple[str, str], tuple[float, float, float, float]]:
    exit_map:  dict[tuple[str, str], list[tuple[str, str]]] = {}
    entry_map: dict[tuple[str, str], list[tuple[str, str]]] = {}

    for src, tgt, _ in relations:
        if src not in positions or tgt not in positions:
            continue
        sx, sy = positions[src]
        tx, ty = positions[tgt]
        ex_side, en_side = _edge_side(
            sx, sy, widths[src], heights[src],
            tx, ty, widths[tgt], heights[tgt],
        )
        exit_map.setdefault((src, ex_side), []).append((src, tgt))
        entry_map.setdefault((tgt, en_side), []).append((src, tgt))

    def _spread(side: str, i: int, n: int) -> tuple[float, float]:
        f = (i + 1) / (n + 1)
        if side == "top":    return (f, 0.0)
        if side == "bottom": return (f, 1.0)
        if side == "left":   return (0.0, f)
        return (1.0, f)

    exit_pt:  dict[tuple[str, str], tuple[float, float]] = {}
    entry_pt: dict[tuple[str, str], tuple[float, float]] = {}

    for (_, side), edges in exit_map.items():
        for i, (s, t) in enumerate(edges):
            exit_pt[(s, t)] = _spread(side, i, len(edges))
    for (_, side), edges in entry_map.items():
        for i, (s, t) in enumerate(edges):
            entry_pt[(s, t)] = _spread(side, i, len(edges))

    result: dict[tuple[str, str], tuple[float, float, float, float]] = {}
    for src, tgt, _ in relations:
        ex, ey = exit_pt.get((src, tgt), (0.5, 1.0))
        nx, ny = entry_pt.get((src, tgt), (0.5, 0.0))
        result[(src, tgt)] = (ex, ey, nx, ny)
    return result


# ── Edge style ─────────────────────────────────────────────────────────────────

def _edge_style(rel: str, color: str,
                ex: float, ey: float,
                nx: float, ny: float) -> str:
    pts = (
        f"exitX={ex:.3f};exitY={ey:.3f};exitDx=0;exitDy=0;"
        f"entryX={nx:.3f};entryY={ny:.3f};entryDx=0;entryDy=0;"
    )
    base = (
        f"html=1;rounded=0;orthogonalLoop=1;jettySize=auto;"
        f"edgeStyle=orthogonalEdgeStyle;{pts}"
        f"strokeColor={color};strokeWidth=1.5;"
    )
    if rel == "inheritance":
        return base + "endArrow=block;endFill=0;startArrow=none;"
    if rel == "realization":
        return base + "endArrow=block;endFill=0;startArrow=none;dashed=1;"
    if rel == "composition":
        return base + "startArrow=diamond;startFill=1;endArrow=none;"
    if rel == "aggregation":
        return base + "startArrow=diamond;startFill=0;endArrow=none;"
    return base + "endArrow=open;endFill=0;dashed=1;startArrow=none;"


# ── XML generation ─────────────────────────────────────────────────────────────

def build_xml(classes: list[ClassInfo]) -> str:
    _EMPTY = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<mxGraphModel><root>'
        '<mxCell id="0"/><mxCell id="1" parent="0"/>'
        '</root></mxGraphModel>'
    )
    if not classes:
        return _EMPTY

    widths  = {cls.name: _class_width(cls)  for cls in classes}
    heights = {cls.name: _class_height(cls) for cls in classes}
    by_name = {cls.name: cls for cls in classes}

    positions, row_corridors, col_corridors = _layout(classes, widths, heights)
    relations = _detect_relations(classes)
    ports     = _assign_ports(relations, positions, widths, heights)

    # BBox всех блоков для obstacle-avoidance
    all_rects: dict[str, tuple[int, int, int, int]] = {
        name: (x, y, widths[name], heights[name])
        for name, (x, y) in positions.items()
    }

    cells:     list[str]       = []
    class_ids: dict[str, str]  = {}

    # ── Блоки классов ─────────────────────────────────────────────────────────
    for i, cls in enumerate(classes):
        cid = f"c{i}"
        class_ids[cls.name] = cid
        x, y = positions.get(cls.name, (START_X + i * (MIN_W + H_GAP), START_Y))
        w    = widths[cls.name]
        h    = heights[cls.name]

        if cls.is_interface:
            fill, stroke = _IFACE_FILL, _IFACE_STROKE
            label = f"«interface»&#xa;{_esc(cls.name)}"
        elif cls.is_struct:
            fill, stroke = _STRUCT_FILL, _STRUCT_STROKE
            label = f"«struct»&#xa;{_esc(cls.name)}"
        else:
            fill, stroke = _CLASS_FILL, _CLASS_STROKE
            label = _esc(cls.name)

        cells.append(
            f'<mxCell id="{cid}" value="{label}" '
            f'style="swimlane;fontStyle=1;align=center;startSize={HEADER_H};'
            f'fillColor={fill};strokeColor={stroke};'
            f'fontColor={_HEADER_FONT};fontSize=12;rounded=1;arcSize=4;" '
            f'vertex="1" parent="1">'
            f'<mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry"/>'
            f'</mxCell>'
        )

        cur_y = HEADER_H

        for j, fld in enumerate(cls.fields):
            sym   = _ACCESS.get(fld.access, "~")
            label = _esc(f"{sym} {fld.name}: {fld.type_str}")
            cells.append(
                f'<mxCell id="{cid}_f{j}" value="{label}" '
                f'style="text;strokeColor=none;fillColor=none;align=left;'
                f'verticalAlign=middle;spacingLeft=6;fontSize=11;'
                f'fontColor={_MEMBER_FONT};" '
                f'vertex="1" parent="{cid}">'
                f'<mxGeometry y="{cur_y}" width="{w}" height="{ROW_H}" as="geometry"/>'
                f'</mxCell>'
            )
            cur_y += ROW_H

        if cls.fields and cls.methods:
            cells.append(
                f'<mxCell id="{cid}_sep" value="" '
                f'style="line;strokeWidth=1;fillColor=none;strokeColor={stroke};" '
                f'vertex="1" parent="{cid}">'
                f'<mxGeometry y="{cur_y}" width="{w}" height="{SEP_H}" as="geometry"/>'
                f'</mxCell>'
            )
            cur_y += SEP_H

        for j, mth in enumerate(cls.methods):
            sym = _ACCESS.get(mth.access, "~")
            if mth.is_constructor:
                label = _esc(f"{sym} {mth.name}{mth.params}")
            else:
                label = _esc(f"{sym} {mth.name}{mth.params}: {mth.return_type}")
            cells.append(
                f'<mxCell id="{cid}_m{j}" value="{label}" '
                f'style="text;strokeColor=none;fillColor=none;align=left;'
                f'verticalAlign=middle;spacingLeft=6;fontSize=11;'
                f'fontColor={_MEMBER_FONT};" '
                f'vertex="1" parent="{cid}">'
                f'<mxGeometry y="{cur_y}" width="{w}" height="{ROW_H}" as="geometry"/>'
                f'</mxCell>'
            )
            cur_y += ROW_H

    # ── Рёбра с маршрутизацией ────────────────────────────────────────────────
    _REL_COLOR = {
        "inheritance": _COLOR_INHERIT,
        "realization": _COLOR_REALIZE,
        "composition": _COLOR_COMPOSE,
        "aggregation": _COLOR_AGGREGATE,
        "dependency":  _COLOR_DEPEND,
    }

    for ei, (src, tgt, rel) in enumerate(relations):
        if src not in class_ids or tgt not in class_ids:
            continue
        sid = class_ids[src]
        tid = class_ids[tgt]

        ex_f, ey_f, nx_f, ny_f = ports.get((src, tgt), (0.5, 1.0, 0.5, 0.0))
        color = _REL_COLOR.get(rel, _EDGE_COLOR)
        style = _edge_style(rel, color, ex_f, ey_f, nx_f, ny_f)

        # Абсолютные координаты точек выхода/входа
        sx, sy = positions[src]
        tx, ty = positions[tgt]
        sw, sh = widths[src], heights[src]
        tw, th = widths[tgt], heights[tgt]
        ex_abs = sx + int(ex_f * sw)
        ey_abs = sy + int(ey_f * sh)
        nx_abs = tx + int(nx_f * tw)
        ny_abs = ty + int(ny_f * th)

        # Препятствия — все блоки кроме src и tgt
        obstacles = [v for k, v in all_rects.items() if k not in (src, tgt)]

        # Маршрут через bbox-пространство
        waypoints = _plan_route(
            ex_abs, ey_abs, nx_abs, ny_abs,
            obstacles, row_corridors, col_corridors,
        )

        if waypoints:
            pts_xml = "".join(f'<mxPoint x="{px}" y="{py}"/>' for px, py in waypoints)
            geo = (
                f'<mxGeometry relative="1" as="geometry">'
                f'<Array as="points">{pts_xml}</Array>'
                f'</mxGeometry>'
            )
        else:
            geo = '<mxGeometry relative="1" as="geometry"/>'

        cells.append(
            f'<mxCell id="e{ei}" value="" style="{style}" '
            f'edge="1" source="{sid}" target="{tid}" parent="1">{geo}</mxCell>'
        )

    body = "\n    ".join(cells)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<mxGraphModel dx="1422" dy="762" grid="1" gridSize="10" guides="1" '
        'tooltips="1" connect="1" arrows="1" fold="1" page="0" pageScale="1" '
        'pageWidth="1654" pageHeight="1169" math="0" shadow="0">\n'
        '  <root>\n'
        '    <mxCell id="0"/>\n'
        '    <mxCell id="1" parent="0"/>\n'
        f'    {body}\n'
        '  </root>\n'
        '</mxGraphModel>'
    )
