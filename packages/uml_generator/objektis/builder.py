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
import re as _re

from .model import ObjectGraph, ObjectInstance, ObjectLink

from .._bbox import (Box, label_box, label_dirs, label_size, place_label, spread_row,
                     stack_rows)
from .._routing import CorridorGrid, Rect, abs_point, assign_ports, plan_route, points_xml, side_of
from ..styles import get_layout, get_theme
from .._text import text_width


_LABEL_FONT = 10                    # px, подпись у ребра (имя поля)


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


def _instance_width(inst: ObjectInstance, cfg: dict) -> int:
    w = max([text_width(_header_text(inst), cfg["header_font"], bold=True)]
            + [text_width(_slot_text(s), cfg["member_font"]) for s in inst.slots])
    g = cfg["size_grid"]
    return max(cfg["min_w"], int(-(-(w + cfg["pad_x"]) // g) * g))


def _instance_height(inst: ObjectInstance, cfg: dict) -> int:
    return max(cfg["header_h"] + len(inst.slots) * cfg["row_h"], cfg["min_h"])


# ── Layout ────────────────────────────────────────────────────────────────────

def _levels(instances: list[ObjectInstance], links: list[ObjectLink]) -> dict[str, int]:
    """Владелец выше владеемого: уровень = 1 + max(уровень источников ссылок)."""
    names = [i.name for i in instances]
    incoming: dict[str, list[str]] = {n: [] for n in names}
    for l in links:
        if l.source in incoming and l.target in incoming and l.source != l.target:
            incoming[l.target].append(l.source)
    level = {n: 0 for n in names}
    for _ in range(len(names)):          # защита от циклов
        changed = False
        for n in names:
            src_levels = [level[s] for s in incoming[n]]
            if src_levels and level[n] < max(src_levels) + 1 <= len(names):
                level[n] = max(src_levels) + 1
                changed = True
        if not changed:
            break
    return level


def _layout(instances: list[ObjectInstance], links: list[ObjectLink],
            widths: dict[str, int], heights: dict[str, int], cfg: dict):
    """
    Ряды по уровню владения, внутри ряда — порядок по барицентру источников.

    Расстановка идёт по рамкам (`_bbox`): ширина блока — по самой длинной строке
    слота, высота — по их числу, а ряды разводятся так, чтобы рамки не
    пересекались с зазором. Иначе длинные значения слотов («путь к файлу»,
    длинное имя узла) делают блок шире шага сетки, и соседи наезжают друг на друга.
    """
    level = _levels(instances, links)
    names = [i.name for i in instances]
    index = {n: i for i, n in enumerate(names)}
    h_gap, v_gap = cfg["h_gap"], cfg["v_gap"]

    rows: list[list[str]] = []
    prev_x: dict[str, float] = {}
    for lvl in sorted(set(level.values())):
        nodes = [n for n in names if level[n] == lvl]
        srcs = {n: [l.source for l in links if l.target == n and l.source in prev_x] for n in nodes}
        nodes.sort(key=lambda n: (sum(prev_x[s] for s in srcs[n]) / len(srcs[n])
                                  if srcs[n] else float("inf"), index[n]))
        cur, cur_w = [], 0
        for n in nodes:
            if cur and cur_w + widths[n] > cfg["max_row_w"]:
                rows.append(cur)
                cur, cur_w = [], 0
            cur.append(n)
            cur_w += widths[n] + h_gap
        if cur:
            rows.append(cur)
        x = 0
        for n in nodes:
            prev_x[n] = x + widths[n] / 2
            x += widths[n] + h_gap

    xs: dict[str, int] = {}
    for row in rows:
        xs.update(spread_row(row, widths, cfg["start_x"], h_gap))
    rects, _tops, _bottoms, row_corridors = stack_rows(
        rows, xs, widths, heights, cfg["start_y"], [v_gap] * len(rows))
    col_corridors: list[int] = []
    for row in rows:
        for n in row:
            col_corridors.append(xs[n] + widths[n] + h_gap // 2)
            col_corridors.append(xs[n] - h_gap // 2)
    return rects, row_corridors, col_corridors


# ── Edge style ─────────────────────────────────────────────────────────────────

def _edge_style(kind: str, color: str, ex: float, ey: float, nx: float, ny: float) -> str:
    base = (
        f"html=1;rounded=0;orthogonalLoop=1;jettySize=auto;edgeStyle=orthogonalEdgeStyle;"
        f"exitX={ex:.3f};exitY={ey:.3f};exitDx=0;exitDy=0;"
        f"entryX={nx:.3f};entryY={ny:.3f};entryDx=0;entryDy=0;"
        f"strokeColor={color};strokeWidth=1.5;labelBackgroundColor=none;"
    )
    if kind == "containment":
        return base + "endArrow=open;endFill=1;startArrow=none;"
    return base + "endArrow=open;endFill=0;startArrow=none;"


# ── Collapse коллекций ────────────────────────────────────────────────────────

def _collapse_collections(graph: ObjectGraph, min_items: int = 4) -> ObjectGraph:
    """
    Свернуть коллекции в один summary-инстанс с multiplicity.

    Правило: если от одного источника идёт ≥min_items containment-link к инстансам
    одного типа с общим label-префиксом ('tasks[0]', 'tasks[1]', ...), с одинаковыми
    слотами, и все targets — листья (нет других связей), оставляем только один target-инстанс
    (помечен is_summary=True, multiplicity='N'), остальные скрываем. Все N
    рёбер заменяются на одно с label = префикс ('tasks').

    Защита для случая cyclic-refs: проверка "все targets — листья" исключает
    инстансы с другими связями (parent/child графы и т.п.) — они остаются как
    есть, потому что для них коллапс потерял бы информацию.
    """
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
        if len(indices) < min_items:
            continue
        targets = [graph.links[i].target for i in indices]
        target_insts = [by_name.get(t) for t in targets]
        if any(t is None for t in target_insts):
            continue
        if len({t.type_name for t in target_insts}) != 1:
            continue  # коллекция гетерогенна — не сворачиваем
        if len({tuple((s.name, s.value) for s in t.slots) for t in target_insts}) != 1:
            continue  # элементы различаются — показываем каждый
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

def build_xml(graph: ObjectGraph, theme: str = "dark",
              cfg_overrides: dict | None = None) -> str:
    if graph.is_empty():
        return _EMPTY_XML
    cfg = get_layout(cfg_overrides)
    pal = get_theme(theme)

    graph = _collapse_collections(graph, cfg["collapse_min"])
    instances = graph.instances
    inst_names = {i.name for i in instances}
    links = [l for l in graph.links if l.source in inst_names and l.target in inst_names]

    widths  = {i.name: _instance_width(i, cfg)  for i in instances}
    heights = {i.name: _instance_height(i, cfg) for i in instances}
    rects, row_corridors, col_corridors = _layout(instances, links, widths, heights, cfg)

    cells: list[str] = []
    ids = {inst.name: f"o{i}" for i, inst in enumerate(instances)}
    row_style = (
        f'text;html=1;strokeColor=none;fillColor=none;align=left;'
        f'verticalAlign=middle;spacingLeft=6;fontSize={cfg["member_font"]};fontColor={pal["slot_font"]};'
    )
    for inst in instances:
        cid = ids[inst.name]
        x, y, w, h = rects[inst.name]
        p = pal["summary"] if inst.is_summary else pal["object"]
        # Заголовок подчёркнут (<u>) — двойной escape: HTML внутри XML-атрибута.
        label = _esc(f"<u>{_esc(_header_text(inst))}</u>")
        cells.append(
            f'<mxCell id="{cid}" value="{label}" '
            f'style="swimlane;html=1;fontStyle=1;align=center;startSize={cfg["header_h"]};'
            f'fillColor={p["fill"]};strokeColor={p["stroke"]};'
            f'fontColor={pal["header_font"]};fontSize={cfg["header_font"]};rounded=1;arcSize=4;" '
            f'vertex="1" parent="1">'
            f'<mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry"/>'
            f'</mxCell>'
        )
        cur_y = cfg["header_h"]
        for j, slot in enumerate(inst.slots):
            cells.append(
                # двойной escape: стиль строки — html=1, поэтому `a<b` иначе
                # съедается разбором HTML (как и в заголовке выше)
                f'<mxCell id="{cid}_s{j}" value="{_esc(_esc(_slot_text(slot)))}" '
                f'style="{row_style}" vertex="1" parent="{cid}">'
                f'<mxGeometry y="{cur_y}" width="{w}" height="{cfg["row_h"]}" as="geometry"/>'
                f'</mxCell>'
            )
            cur_y += cfg["row_h"]

    keys = [((l.source, l.target, l.label), l.source, l.target) for l in links]
    ports = assign_ports(keys, rects)
    m = cfg["route_margin"]
    # сетка коридоров на всю диаграмму: по ней ищется обход, когда прямого и
    # L/U-образного маршрута нет, — без неё линия шла бы сквозь блоки
    grid = CorridorGrid(list(rects.values()), row_corridors, col_corridors, m)
    taken: list[Box] = list(rects.values())     # рамки, занятые блоками и подписями
    for ei, l in enumerate(links):
        key = (l.source, l.target, l.label)
        ex_f, ey_f, nx_f, ny_f = ports.get(key, (0.5, 1.0, 0.5, 0.0))
        ex, ey = abs_point(rects[l.source], ex_f, ey_f)
        nx, ny = abs_point(rects[l.target], nx_f, ny_f)
        obstacles = [r for n, r in rects.items() if n not in (l.source, l.target)]
        vertical = ey_f in (0.0, 1.0) and ny_f in (0.0, 1.0)
        wps = plan_route(ex, ey, nx, ny, obstacles, row_corridors, col_corridors, m,
                         prefer_corridor=vertical, grid=grid,
                         exit_side=side_of(ex_f, ey_f), entry_side=side_of(nx_f, ny_f))
        color = pal["containment"] if l.kind == "containment" else pal["edge"]
        cells.append(
            f'<mxCell id="e{ei}" value="" '
            f'style="{_edge_style(l.kind, color, ex_f, ey_f, nx_f, ny_f)}" '
            f'edge="1" source="{ids[l.source]}" target="{ids[l.target]}" parent="1">'
            f'{points_xml(wps)}</mxCell>'
        )
        # Подпись у начала ребра (имя поля), сбоку от первого сегмента: у рёбер,
        # идущих по общему коридору, середины совпадают, а начала — разные.
        # Место ищется по рамкам: имя поля бывает длиннее прежнего постоянного
        # отступа в 14 px, и подпись ложилась прямо на блок.
        size = label_size(l.label, _LABEL_FONT)
        off = place_label((ex, ey), size, label_dirs(ex_f, ey_f), taken)
        taken.append(label_box((ex, ey), off, size))
        cells.append(
            f'<mxCell id="e{ei}_l" value="{_esc(l.label)}" '
            f'style="edgeLabel;html=1;align=center;verticalAlign=middle;resizable=0;'
            f'fontSize={_LABEL_FONT};fontColor={pal["slot_font"]};" vertex="1" connectable="0" parent="e{ei}">'
            f'<mxGeometry x="-1" relative="1" as="geometry">'
            f'<mxPoint x="{off[0]}" y="{off[1]}" as="offset"/></mxGeometry></mxCell>'
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


_EMPTY_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<mxGraphModel><root>'
    '<mxCell id="0"/><mxCell id="1" parent="0"/>'
    '</root></mxGraphModel>'
)
