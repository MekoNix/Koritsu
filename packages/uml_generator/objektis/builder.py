"""
Builder — генерирует draw.io XML для UML-диаграммы объектов.

Конвенции UML Object Diagram:
  • Заголовок инстанса: подчёркнутый "name : Type"
  • Тело: список slot-ов "field = value" (без префиксов видимости)
  • Рёбра: сплошные линии (label = имя поля); containment — закрашенный наконечник.
  • Multi-instance (свёрнутая коллекция/цикл): добавляется суффикс "[N]" / "[*]".

Layout — flat-grid (объекты не имеют иерархии в отличие от классов),
но используем тот же bbox-routing для рёбер, что и в klassis.
"""
import html as _html

from .model import ObjectGraph, ObjectInstance, ObjectLink

# ── Layout constants (синхронны с klassis/builder.py для визуальной пары) ───
CHAR_W       = 7
PAD_X        = 28
MIN_W        = 160
H_GAP        = 80
V_GAP        = 100
HEADER_H     = 32
ROW_H        = 22
MIN_H        = 60
START_X      = 60
START_Y      = 60
MAX_PER_ROW  = 4
ROUTE_MARGIN = 18

# ── Палитра (отлична от klassis, чтобы пара диаграмм визуально различалась) ──
_INST_FILL    = "#1f2a44"   # синевато-фиолетовый — отличие от слейтового klassis
_SUMMARY_FILL = "#2a1f44"   # для multi-instance — иной оттенок
_INST_STROKE  = "#7c84a8"
_SUMMARY_STROKE = "#a87cc4"
_HEADER_FONT  = "#f1f5f9"
_SLOT_FONT    = "#cbd5e1"
_EDGE_COLOR   = "#94a3b8"
_CONTAIN_COLOR = "#c4b5fd"


# ── Sizing ─────────────────────────────────────────────────────────────────────

def _esc(s: str) -> str:
    return _html.escape(s, quote=True)


def _header_text(inst: ObjectInstance) -> str:
    """Чистая строка заголовка (без HTML) для оценки ширины."""
    base = f"{inst.name} : {inst.type_name}"
    if inst.multiplicity:
        base += f" [{inst.multiplicity}]"
    return base


def _slot_text(slot) -> str:
    return f"{slot.name} = {slot.value}"


def _instance_width(inst: ObjectInstance) -> int:
    lines = [_header_text(inst)]
    lines.extend(_slot_text(s) for s in inst.slots)
    longest = max(len(s) for s in lines) if lines else 0
    return max(MIN_W, longest * CHAR_W + PAD_X)


def _instance_height(inst: ObjectInstance) -> int:
    h = HEADER_H + len(inst.slots) * ROW_H
    return max(h, MIN_H)


# ── Layout: flat grid ──────────────────────────────────────────────────────────

def _layout(
    instances: list[ObjectInstance],
    widths:  dict[str, int],
    heights: dict[str, int],
) -> tuple[dict[str, tuple[int, int]], list[int], list[int]]:
    """Раскладка в строки по MAX_PER_ROW. Возвращает позиции + коридоры."""
    positions: dict[str, tuple[int, int]] = {}
    row_corridors: list[int] = []
    col_corridors: list[int] = []
    current_y = START_Y

    for row_start in range(0, len(instances), MAX_PER_ROW):
        sub = instances[row_start: row_start + MAX_PER_ROW]
        row_h = max(heights[i.name] for i in sub) if sub else MIN_H

        current_x = START_X
        for inst in sub:
            positions[inst.name] = (current_x, current_y)
            col_corridors.append(current_x + widths[inst.name] + H_GAP // 2)
            current_x += widths[inst.name] + H_GAP

        row_corridors.append(current_y + row_h + V_GAP // 2)
        current_y += row_h + V_GAP

    return positions, row_corridors, col_corridors


# ── BBox routing (упрощённый, по образцу klassis) ──────────────────────────────

def _seg_hits_rect(x1, y1, x2, y2, rx, ry, rw, rh, m):
    lx, rx2 = rx - m, rx + rw + m
    ly, ry2 = ry - m, ry + rh + m
    if x1 == x2:
        x = x1
        sy1, sy2 = min(y1, y2), max(y1, y2)
        return lx < x < rx2 and sy1 < ry2 and sy2 > ly
    if y1 == y2:
        y = y1
        sx1, sx2 = min(x1, x2), max(x1, x2)
        return ly < y < ry2 and sx1 < rx2 and sx2 > lx
    return False


def _path_clear(pts, obstacles, m):
    for i in range(len(pts) - 1):
        x1, y1 = pts[i]
        x2, y2 = pts[i + 1]
        for rx, ry, rw, rh in obstacles:
            if _seg_hits_rect(x1, y1, x2, y2, rx, ry, rw, rh, m):
                return False
    return True


def _plan_route(ex, ey, nx, ny, obstacles, row_corridors, col_corridors,
                m=ROUTE_MARGIN):
    if ex == nx and ey == ny:
        return []

    wp = (nx, ey)
    if _path_clear([(ex, ey), wp, (nx, ny)], obstacles, m):
        return [wp] if wp != (ex, ey) and wp != (nx, ny) else []

    wp = (ex, ny)
    if _path_clear([(ex, ey), wp, (nx, ny)], obstacles, m):
        return [wp] if wp != (ex, ey) and wp != (nx, ny) else []

    best = None
    best_cost = float("inf")

    for cy in row_corridors:
        pts = [(ex, ey), (ex, cy), (nx, cy), (nx, ny)]
        if _path_clear(pts, obstacles, m):
            cost = abs(ey - cy) + abs(ny - cy)
            if cost < best_cost:
                best_cost = cost
                best = [(ex, cy), (nx, cy)]

    for cx in col_corridors:
        pts = [(ex, ey), (cx, ey), (cx, ny), (nx, ny)]
        if _path_clear(pts, obstacles, m):
            cost = abs(ex - cx) + abs(nx - cx)
            if cost < best_cost:
                best_cost = cost
                best = [(cx, ey), (cx, ny)]

    if best:
        return best

    all_tops = [ry for _, ry, _, _ in obstacles]
    safe_y = (min(all_tops) - 3 * m) if all_tops else (min(ey, ny) - 3 * m)
    return [(ex, safe_y), (nx, safe_y)]


# ── Port assignment ────────────────────────────────────────────────────────────

def _edge_side(sx, sy, sw, sh, tx, ty, tw, th):
    dx = (tx + tw / 2) - (sx + sw / 2)
    dy = (ty + th / 2) - (sy + sh / 2)
    if abs(dy) >= abs(dx):
        return ("top", "bottom") if dy <= 0 else ("bottom", "top")
    return ("left", "right") if dx <= 0 else ("right", "left")


def _assign_ports(links, positions, widths, heights):
    exit_map: dict = {}
    entry_map: dict = {}
    for link in links:
        if link.source not in positions or link.target not in positions:
            continue
        sx, sy = positions[link.source]
        tx, ty = positions[link.target]
        ex_side, en_side = _edge_side(
            sx, sy, widths[link.source], heights[link.source],
            tx, ty, widths[link.target], heights[link.target],
        )
        exit_map.setdefault((link.source, ex_side), []).append((link.source, link.target))
        entry_map.setdefault((link.target, en_side), []).append((link.source, link.target))

    def _spread(side: str, i: int, n: int):
        f = (i + 1) / (n + 1)
        if side == "top":    return (f, 0.0)
        if side == "bottom": return (f, 1.0)
        if side == "left":   return (0.0, f)
        return (1.0, f)

    exit_pt: dict = {}
    entry_pt: dict = {}
    for (_, side), edges in exit_map.items():
        for i, st in enumerate(edges):
            exit_pt[st] = _spread(side, i, len(edges))
    for (_, side), edges in entry_map.items():
        for i, st in enumerate(edges):
            entry_pt[st] = _spread(side, i, len(edges))

    result = {}
    for link in links:
        ex, ey = exit_pt.get((link.source, link.target), (0.5, 1.0))
        nx, ny = entry_pt.get((link.source, link.target), (0.5, 0.0))
        result[(link.source, link.target, link.label)] = (ex, ey, nx, ny)
    return result


# ── Edge style ─────────────────────────────────────────────────────────────────

def _edge_style(kind: str, ex: float, ey: float, nx: float, ny: float) -> str:
    color = _CONTAIN_COLOR if kind == "containment" else _EDGE_COLOR
    pts = (
        f"exitX={ex:.3f};exitY={ey:.3f};exitDx=0;exitDy=0;"
        f"entryX={nx:.3f};entryY={ny:.3f};entryDx=0;entryDy=0;"
    )
    base = (
        f"html=1;rounded=0;orthogonalLoop=1;jettySize=auto;"
        f"edgeStyle=orthogonalEdgeStyle;{pts}"
        f"strokeColor={color};strokeWidth=1.5;"
        # Белая подложка под текстом label'а — чтобы пересекающиеся labels
        # из разных рёбер (на маршрутах через общий коридор) не сливались.
        f"labelBackgroundColor=#ffffff;"
    )
    if kind == "containment":
        return base + "endArrow=open;endFill=1;startArrow=none;"
    return base + "endArrow=open;endFill=0;startArrow=none;"


# ── Collapse коллекций ────────────────────────────────────────────────────────

def _collapse_collections(graph: ObjectGraph) -> ObjectGraph:
    """
    Свернуть коллекции в один summary-инстанс с multiplicity.

    Правило: если от одного источника идёт ≥2 containment-link к инстансам
    одного типа с общим label-префиксом ('tasks[0]', 'tasks[1]', ...), и все
    targets — листья (нет других связей), оставляем только один target-инстанс
    (помечен is_summary=True, multiplicity='N'), остальные скрываем. Все N
    рёбер заменяются на одно с label = префикс ('tasks').

    Защита для случая cyclic-refs: проверка "все targets — листья" исключает
    инстансы с другими связями (parent/child графы и т.п.) — они остаются как
    есть, потому что для них коллапс потерял бы информацию.
    """
    import re as _re

    if not graph.links or len(graph.instances) < 3:
        return graph

    by_name = {i.name: i for i in graph.instances}

    # Сколько связей касается каждого инстанса (входящих или исходящих).
    edge_count: dict[str, int] = {}
    for l in graph.links:
        edge_count[l.source] = edge_count.get(l.source, 0) + 1
        edge_count[l.target] = edge_count.get(l.target, 0) + 1

    # Группируем containment-link по (source, prefix).
    groups: dict[tuple[str, str], list[int]] = {}
    for i, l in enumerate(graph.links):
        if l.kind != "containment":
            continue
        m = _re.match(r"^([^\[]+)\[", l.label)
        if not m:
            continue
        groups.setdefault((l.source, m.group(1)), []).append(i)

    edges_to_drop: set[int] = set()
    targets_to_hide: set[str] = set()
    # link_idx → (new_label, target_multiplicity)
    edge_overrides: dict[int, tuple[str, str]] = {}
    # name → multiplicity (для пометки keeper'а как summary)
    summary_marks: dict[str, str] = {}

    for (src, prefix), indices in groups.items():
        if len(indices) < 2:
            continue
        targets = [graph.links[i].target for i in indices]
        target_insts = [by_name.get(t) for t in targets]
        if any(t is None for t in target_insts):
            continue
        if len({t.type_name for t in target_insts}) != 1:
            continue  # коллекция гетерогенна — не сворачиваем
        # Все targets должны быть листьями: ровно по одной связи каждое.
        if any(edge_count.get(t.name, 0) != 1 for t in target_insts):
            continue

        keeper = targets[0]
        keeper_idx = indices[0]
        edge_overrides[keeper_idx] = (prefix, str(len(indices)))
        summary_marks[keeper] = str(len(indices))
        for idx in indices[1:]:
            edges_to_drop.add(idx)
        targets_to_hide.update(targets[1:])

    if not edges_to_drop and not summary_marks:
        return graph

    new_instances = []
    for inst in graph.instances:
        if inst.name in targets_to_hide:
            continue
        if inst.name in summary_marks:
            new_instances.append(ObjectInstance(
                name=inst.name, type_name=inst.type_name,
                slots=inst.slots,
                multiplicity=summary_marks[inst.name],
                is_summary=True,
            ))
        else:
            new_instances.append(inst)

    new_links = []
    for i, l in enumerate(graph.links):
        if i in edges_to_drop:
            continue
        if l.target in targets_to_hide:
            continue
        if i in edge_overrides:
            new_label, _ = edge_overrides[i]
            new_links.append(ObjectLink(
                source=l.source, target=l.target,
                label=new_label, kind=l.kind,
            ))
        else:
            new_links.append(l)

    return ObjectGraph(
        instances=new_instances,
        links=new_links,
        notes=list(graph.notes),
    )


# ── XML generation ─────────────────────────────────────────────────────────────

def build_xml(graph: ObjectGraph) -> str:
    _EMPTY = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<mxGraphModel><root>'
        '<mxCell id="0"/><mxCell id="1" parent="0"/>'
        '</root></mxGraphModel>'
    )
    if graph.is_empty():
        return _EMPTY

    # Сворачиваем большие коллекции в summary-инстансы с multiplicity.
    graph = _collapse_collections(graph)

    instances = graph.instances
    widths = {inst.name: _instance_width(inst) for inst in instances}
    heights = {inst.name: _instance_height(inst) for inst in instances}

    positions, row_corridors, col_corridors = _layout(instances, widths, heights)

    # Только links между инстансами, реально присутствующими в графе.
    inst_names = {inst.name for inst in instances}
    valid_links = [
        l for l in graph.links
        if l.source in inst_names and l.target in inst_names
    ]
    ports = _assign_ports(valid_links, positions, widths, heights)

    all_rects = {
        name: (x, y, widths[name], heights[name])
        for name, (x, y) in positions.items()
    }

    cells: list[str] = []
    inst_ids: dict[str, str] = {}

    # ── Блоки инстансов ──────────────────────────────────────────────────────
    for i, inst in enumerate(instances):
        cid = f"o{i}"
        inst_ids[inst.name] = cid
        x, y = positions.get(inst.name, (START_X + i * (MIN_W + H_GAP), START_Y))
        w = widths[inst.name]
        h = heights[inst.name]

        if inst.is_summary:
            fill, stroke = _SUMMARY_FILL, _SUMMARY_STROKE
        else:
            fill, stroke = _INST_FILL, _INST_STROKE

        # Заголовок: подчёркнутый через HTML <u> (drawio: html=1).
        # Двухэтапный escape: сначала экранируем сам текст для HTML, затем
        # всю обёртку — для XML-атрибута value (где '<','>' тоже нельзя).
        header_html = f"<u>{_esc(_header_text(inst))}</u>"
        label = _esc(header_html)

        cells.append(
            f'<mxCell id="{cid}" value="{label}" '
            f'style="swimlane;html=1;fontStyle=1;align=center;startSize={HEADER_H};'
            f'fillColor={fill};strokeColor={stroke};'
            f'fontColor={_HEADER_FONT};fontSize=12;rounded=1;arcSize=4;" '
            f'vertex="1" parent="1">'
            f'<mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry"/>'
            f'</mxCell>'
        )

        cur_y = HEADER_H
        for j, slot in enumerate(inst.slots):
            slabel = _esc(_slot_text(slot))
            cells.append(
                f'<mxCell id="{cid}_s{j}" value="{slabel}" '
                f'style="text;strokeColor=none;fillColor=none;align=left;'
                f'verticalAlign=middle;spacingLeft=6;fontSize=11;'
                f'fontColor={_SLOT_FONT};" '
                f'vertex="1" parent="{cid}">'
                f'<mxGeometry y="{cur_y}" width="{w}" height="{ROW_H}" as="geometry"/>'
                f'</mxCell>'
            )
            cur_y += ROW_H

    # ── Рёбра ────────────────────────────────────────────────────────────────
    for ei, link in enumerate(valid_links):
        sid = inst_ids[link.source]
        tid = inst_ids[link.target]

        ex_f, ey_f, nx_f, ny_f = ports.get(
            (link.source, link.target, link.label), (0.5, 1.0, 0.5, 0.0),
        )
        style = _edge_style(link.kind, ex_f, ey_f, nx_f, ny_f)

        sx, sy = positions[link.source]
        tx, ty = positions[link.target]
        sw, sh = widths[link.source], heights[link.source]
        tw, th = widths[link.target], heights[link.target]
        ex_abs = sx + int(ex_f * sw)
        ey_abs = sy + int(ey_f * sh)
        nx_abs = tx + int(nx_f * tw)
        ny_abs = ty + int(ny_f * th)

        obstacles = [
            v for k, v in all_rects.items()
            if k not in (link.source, link.target)
        ]
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

        edge_label = _esc(link.label)
        cells.append(
            f'<mxCell id="e{ei}" value="{edge_label}" style="{style}" '
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
