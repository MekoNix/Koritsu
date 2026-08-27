"""
Builder — генерирует draw.io XML для UML-диаграммы классов.
"""
import html as _html
import re as _re
from dataclasses import dataclass, field as dc_field

from .extractor import ClassInfo, FieldInfo, MethodInfo

from ._routing import (Rect, abs_point, assign_ports, path_clear, plan_route, points_xml)
from ._text import text_width
from .styles import get_layout, get_theme

_ACCESS = {"public": "+", "protected": "#", "private": "-", "internal": "~",
           "protected internal": "#", "private protected": "#"}


# ── Helpers ────────────────────────────────────────────────────────────────────

def _esc(s: str) -> str:
    return _html.escape(s, quote=True)


_COLLECTIONS = {
    "List", "IList", "IEnumerable", "ICollection", "IReadOnlyList", "IReadOnlyCollection",
    "HashSet", "ISet", "Queue", "Stack", "LinkedList", "ObservableCollection",
    "Dictionary", "IDictionary", "SortedDictionary", "SortedList", "IReadOnlyDictionary",
    "vector", "list", "deque", "array", "set", "map", "multiset", "multimap",
    "unordered_set", "unordered_map", "forward_list", "span", "initializer_list",
}
_SHARED_PTRS = {"shared_ptr", "weak_ptr"}
_OWNING_PTRS = {"unique_ptr"}
_PARAM_MODIFIERS = {"ref", "out", "in", "params", "this", "const", "volatile",
                    "static", "mutable", "explicit", "inline", "readonly", "scoped"}


@dataclass
class TypeRef:
    """Ссылка на класс диаграммы из строки типа."""
    name:  str
    many:  bool = False   # внутри коллекции или массив
    ptr:   bool = False   # raw pointer / reference / shared_ptr / weak_ptr
    owned: bool = True    # по значению или unique_ptr


def _type_refs(type_str: str, names: set[str]) -> list[TypeRef]:
    """
    Все известные классы, упомянутые в типе, с учётом обёрток:
      `List<Task>`, `Task[]`            → many
      `Task*`, `Task&`, `shared_ptr<Task>` → ptr (агрегация)
      `Task`, `unique_ptr<Task>`        → по значению (композиция)
    """
    s = _re.sub(r'\{.*\}', '', type_str)          # { get; set; }
    tokens = _re.findall(r'[A-Za-z_]\w*|<|>|\[\]|[*&]', s)
    refs: list[TypeRef] = []
    stack: list[str] = []                           # обёртки generic'ов
    prev = ""
    has_array = "[" in s
    for i, tok in enumerate(tokens):
        if tok == "<":
            stack.append(prev)
        elif tok == ">":
            if stack:
                stack.pop()
        elif tok in names:
            nxt = tokens[i + 1] if i + 1 < len(tokens) else ""
            many = has_array or any(w.split("::")[-1] in _COLLECTIONS for w in stack)
            ptr = nxt in ("*", "&") or any(w in _SHARED_PTRS for w in stack)
            owned = not ptr and not any(w in _SHARED_PTRS for w in stack)
            refs.append(TypeRef(tok, many=many, ptr=ptr, owned=owned))
        prev = tok
    return refs


def _param_types(params: str) -> list[str]:
    """Типы параметров без имён, значений по умолчанию и модификаторов."""
    inner = params.strip()
    if inner.startswith("(") and inner.endswith(")"):
        inner = inner[1:-1]
    out = []
    depth = 0
    cur = ""
    for ch in inner + ",":
        if ch in "<([":
            depth += 1
        elif ch in ">)]":
            depth -= 1
        if ch == "," and depth == 0:
            part = cur.split("=")[0].strip()
            toks = [t for t in part.split() if t not in _PARAM_MODIFIERS]
            if len(toks) >= 2:
                out.append(" ".join(toks[:-1]))
            elif toks:
                out.append(toks[0])
            cur = ""
        else:
            cur += ch
    return out


# ── Member text ────────────────────────────────────────────────────────────────

_STEREOTYPE = {"interface": "«interface»", "struct": "«struct»", "enum": "«enumeration»",
               "record": "«record»", "union": "«union»"}


def _field_text(fld: FieldInfo) -> str:
    sym = _ACCESS.get(fld.access, "#")
    return f"{sym} {fld.name}: {fld.type_str}" if fld.type_str else f"{sym} {fld.name}"


def _method_text(mth: MethodInfo) -> str:
    sym = _ACCESS.get(mth.access, "#")
    if mth.is_constructor or mth.is_destructor or not mth.return_type:
        base = f"{sym} {mth.name}{mth.params}"
    else:
        base = f"{sym} {mth.name}{mth.params}: {mth.return_type}"
    if mth.is_const:
        base += " const"
    return base


def _member_rows(cls: ClassInfo) -> tuple[list[tuple[str, bool, bool]], list[tuple[str, bool, bool]]]:
    """(текст, static, abstract) для полей и методов; у enum поля — значения."""
    if cls.kind == "enum":
        return [(v, False, False) for v in cls.enum_values], []
    fields  = [(_field_text(f), f.is_static, False) for f in cls.fields]
    methods = [(_method_text(m), m.is_static, m.is_abstract) for m in cls.methods]
    return fields, methods


def _member_label(text: str, static: bool, abstract: bool) -> str:
    """HTML-подпись строки: static — подчёркнуто, abstract — курсив (draw.io html=1)."""
    h = _esc(text)
    if static:
        h = f"<u>{h}</u>"
    if abstract:
        h = f"<i>{h}</i>"
    return _esc(h)


# ── Dynamic sizing ─────────────────────────────────────────────────────────────

def _class_width(cls: ClassInfo, cfg: dict) -> int:
    """Ширина блока по самой длинной строке текста."""
    fields, methods = _member_rows(cls)
    w = max([text_width(cls.display_name, cfg["header_font"], bold=True),
             text_width(_STEREOTYPE.get(cls.kind, ""), cfg["header_font"], bold=True)]
            + [text_width(t, cfg["member_font"]) for t, _, _ in fields + methods])
    return max(cfg["min_w"], _grid(w + cfg["pad_x"], cfg["size_grid"]))


def _grid(v: float, g: int) -> int:
    return int(-(-v // g) * g)


def _class_height(cls: ClassInfo, cfg: dict) -> int:
    fields, methods = _member_rows(cls)
    h = cfg["header_h"] + len(fields) * cfg["row_h"] + len(methods) * cfg["row_h"]
    if fields and methods:
        h += cfg["sep_h"]
    return max(h, cfg["min_h"])


# ── Relations ──────────────────────────────────────────────────────────────────

@dataclass
class Relation:
    src:   str
    tgt:   str
    kind:  str           # inheritance | realization | composition | aggregation | dependency | nesting
    label: str = ""      # кратность / роль у конца tgt

    def __iter__(self):  # совместимость с кортежами (src, tgt, kind)
        return iter((self.src, self.tgt, self.kind))


_REL_PRIO = {"inheritance": 0, "realization": 1, "nesting": 2,
             "composition": 3, "aggregation": 4, "dependency": 5}


def _detect_relations(classes: list[ClassInfo]) -> list[Relation]:
    names   = {c.name for c in classes}
    by_name = {c.name: c for c in classes}
    best: dict[tuple[str, str], Relation] = {}

    def _add(src: str, tgt: str, kind: str, label: str = ""):
        if tgt not in names or tgt == src:
            return
        key = (src, tgt)
        cur = best.get(key)
        if cur is None:
            best[key] = Relation(src, tgt, kind, label)
            return
        if _REL_PRIO[kind] < _REL_PRIO[cur.kind]:
            cur.kind = kind
        if label and not cur.label and cur.kind in ("composition", "aggregation"):
            cur.label = label            # кратность сохраняем при любом виде владения

    for cls in classes:
        src = cls.name
        for parent in cls.parents:
            pc = by_name.get(parent)
            _add(src, parent, "realization" if (pc and pc.is_interface) else "inheritance")
        if cls.outer in names:
            _add(src, cls.outer, "nesting")
        for fld in cls.fields:
            for ref in _type_refs(fld.type_str, names):
                if ref.name == src:
                    continue
                label = "0..*" if ref.many else ""
                kind = "aggregation" if (ref.ptr or ref.many) else "composition"
                _add(src, ref.name, kind, label)
        for mth in cls.methods:
            types = ([mth.return_type] if mth.return_type else []) + _param_types(mth.params)
            for t in types:
                for ref in _type_refs(t, names):
                    if ref.name != src:
                        _add(src, ref.name, "dependency")

    return list(best.values())


# ── Layout ─────────────────────────────────────────────────────────────────────

_HIER = ("inheritance", "realization")


@dataclass
class Layout:
    rects:         dict[str, Rect] = dc_field(default_factory=dict)
    row_of:        dict[str, int]  = dc_field(default_factory=dict)
    row_bottoms:   list[int]       = dc_field(default_factory=list)   # y низа каждого ряда
    row_tops:      list[int]       = dc_field(default_factory=list)
    row_corridors: list[int]       = dc_field(default_factory=list)   # y середины зазора под рядом
    col_corridors: list[int]       = dc_field(default_factory=list)


def _levels(classes: list[ClassInfo], relations: list[Relation]) -> dict[str, int]:
    """
    Уровень (ряд) каждого класса.
      1. По наследованию/реализации: родитель выше потомка (длиннейший путь от корня).
      2. Классы вне иерархии опускаются под те, на кого ссылаются (поля, параметры,
         внешний тип) — «использующий» ниже «используемого».
    """
    names = [c.name for c in classes]
    parents: dict[str, list[str]] = {n: [] for n in names}
    children: dict[str, list[str]] = {n: [] for n in names}
    refs: dict[str, list[str]] = {n: [] for n in names}
    for r in relations:
        if r.kind in _HIER:
            parents[r.src].append(r.tgt)
            children[r.tgt].append(r.src)
        else:
            refs[r.src].append(r.tgt)

    level = {n: 0 for n in names}
    in_hier = {n for n in names if parents[n] or children[n]}
    # длиннейший путь; защита от циклов — не больше len(names) итераций
    for _ in range(len(names)):
        changed = False
        for n in names:
            for p in parents[n]:
                if level[n] < level[p] + 1:
                    level[n] = level[p] + 1
                    changed = True
        if not changed:
            break

    free = [n for n in names if n not in in_hier]
    for _ in range(len(names)):
        changed = False
        for n in free:
            tgt_levels = [level[t] for t in refs[n] if t != n]
            if tgt_levels and level[n] < max(tgt_levels) + 1:
                level[n] = max(tgt_levels) + 1
                changed = True
        if not changed:
            break
    return level


def _order_level(level_nodes: list[str], prev_x: dict[str, float],
                 relations: list[Relation], index: dict[str, int]) -> list[str]:
    """Порядок внутри уровня — по барицентру связанных блоков предыдущих уровней."""
    links: dict[str, list[str]] = {n: [] for n in level_nodes}
    for r in relations:
        if r.src in links and r.tgt in prev_x:
            links[r.src].append(r.tgt)

    def key(n):
        xs = [prev_x[t] for t in links[n]]
        return (sum(xs) / len(xs) if xs else float("inf"), index[n])
    return sorted(level_nodes, key=key)


def _layout(classes: list[ClassInfo], relations: list[Relation],
            widths: dict[str, int], heights: dict[str, int], cfg: dict) -> Layout:
    names = [c.name for c in classes]
    index = {n: i for i, n in enumerate(names)}
    level = _levels(classes, relations)
    h_gap, v_gap = cfg["h_gap"], cfg["v_gap"]

    # ряды: уровень → упорядоченный список, при переполнении по ширине — новые ряды
    rows: list[list[str]] = []
    prev_x: dict[str, float] = {}
    for lvl in sorted(set(level.values())):
        nodes = _order_level([n for n in names if level[n] == lvl], prev_x, relations, index)
        cur: list[str] = []
        cur_w = 0
        for n in nodes:
            if cur and cur_w + widths[n] > cfg["max_row_w"]:
                rows.append(cur)
                cur, cur_w = [], 0
            cur.append(n)
            cur_w += widths[n] + h_gap
        if cur:
            rows.append(cur)
        x = 0
        for n in nodes:                       # грубые x для барицентра следующего уровня
            prev_x[n] = x + widths[n] / 2
            x += widths[n] + h_gap

    # x внутри ряда — последовательно
    xs: dict[str, int] = {}
    for row in rows:
        x = cfg["start_x"]
        for n in row:
            xs[n] = x
            x += widths[n] + h_gap

    # центрирование родителей над потомками (снизу вверх), без наложений в ряду
    row_of = {n: ri for ri, row in enumerate(rows) for n in row}
    children: dict[str, list[str]] = {n: [] for n in names}
    for r in relations:
        if r.kind in _HIER and row_of[r.src] > row_of[r.tgt]:
            children[r.tgt].append(r.src)
    for ri in range(len(rows) - 2, -1, -1):
        row = rows[ri]
        want: dict[str, int] = {}
        for n in row:
            kids = children[n]
            if kids:
                cx = sum(xs[k] + widths[k] / 2 for k in kids) / len(kids)
                want[n] = int(cx - widths[n] / 2)
        if not want:
            continue
        x_min = cfg["start_x"]
        for n in row:
            target = max(want.get(n, xs[n]), x_min)
            xs[n] = target
            x_min = target + widths[n] + h_gap

    # y рядов и коридоры
    lay = Layout()
    y = cfg["start_y"]
    for ri, row in enumerate(rows):
        row_h = max(heights[n] for n in row)
        lay.row_tops.append(y)
        for n in row:
            lay.rects[n] = (xs[n], y, widths[n], heights[n])
            lay.row_of[n] = ri
        lay.row_bottoms.append(y + row_h)
        lay.row_corridors.append(y + row_h + v_gap // 2)
        y += row_h + v_gap
    for row in rows:
        for n in row:
            lay.col_corridors.append(xs[n] + widths[n] + h_gap // 2)
    lay.col_corridors.append(cfg["start_x"] - h_gap // 2)
    return lay


# ── Edge style ─────────────────────────────────────────────────────────────────

def _edge_base(color: str, ex: float, ey: float, nx: float, ny: float) -> str:
    return (
        f"html=1;rounded=0;orthogonalLoop=1;jettySize=auto;edgeStyle=orthogonalEdgeStyle;"
        f"exitX={ex:.3f};exitY={ey:.3f};exitDx=0;exitDy=0;"
        f"entryX={nx:.3f};entryY={ny:.3f};entryDx=0;entryDy=0;"
        f"strokeColor={color};strokeWidth=1.5;"
    )


def _edge_arrows(rel: str) -> str:
    if rel == "inheritance":
        return "endArrow=block;endFill=0;startArrow=none;"
    if rel == "realization":
        return "endArrow=block;endFill=0;startArrow=none;dashed=1;"
    if rel == "composition":
        return "startArrow=diamond;startFill=1;endArrow=none;"
    if rel == "aggregation":
        return "startArrow=diamond;startFill=0;endArrow=none;"
    if rel == "nesting":
        return "endArrow=circlePlus;endFill=0;startArrow=none;"
    return "endArrow=open;endFill=0;dashed=1;startArrow=none;"


def _edge_style(rel: str, color: str, ex: float, ey: float, nx: float, ny: float) -> str:
    return _edge_base(color, ex, ey, nx, ny) + _edge_arrows(rel)


# ── XML generation ─────────────────────────────────────────────────────────────

_EMPTY_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<mxGraphModel><root>'
    '<mxCell id="0"/><mxCell id="1" parent="0"/>'
    '</root></mxGraphModel>'
)


def _wrap_xml(cells: list[str]) -> str:
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


def _class_cells(cls: ClassInfo, cid: str, rect: Rect, theme: dict, cfg: dict) -> list[str]:
    x, y, w, h = rect
    pal = theme["interface"] if cls.kind == "interface" else (
        theme["struct"] if cls.kind in ("struct", "record", "union", "enum") else theme["class"])
    fill, stroke = pal["fill"], pal["stroke"]

    name_html = _esc(cls.display_name)
    if cls.is_abstract and cls.kind == "class":
        name_html = f"<i>{name_html}</i>"
    stereo = _STEREOTYPE.get(cls.kind)
    label = _esc(f"{stereo}<br>{name_html}" if stereo else name_html)

    cells = [
        f'<mxCell id="{cid}" value="{label}" '
        f'style="swimlane;html=1;fontStyle=1;align=center;startSize={cfg["header_h"]};'
        f'fillColor={fill};strokeColor={stroke};'
        f'fontColor={theme["header_font"]};fontSize={cfg["header_font"]};rounded=1;arcSize=4;" '
        f'vertex="1" parent="1">'
        f'<mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry"/>'
        f'</mxCell>'
    ]
    fields, methods = _member_rows(cls)
    row_style = (
        f'text;html=1;strokeColor=none;fillColor=none;align=left;'
        f'verticalAlign=middle;spacingLeft=6;fontSize={cfg["member_font"]};fontColor={theme["member_font"]};'
    )
    cur_y = cfg["header_h"]
    for prefix, rows in (("f", fields), ("m", methods)):
        if prefix == "m" and fields and methods:
            cells.append(
                f'<mxCell id="{cid}_sep" value="" '
                f'style="line;strokeWidth=1;fillColor=none;strokeColor={stroke};" '
                f'vertex="1" parent="{cid}">'
                f'<mxGeometry y="{cur_y}" width="{w}" height="{cfg["sep_h"]}" as="geometry"/>'
                f'</mxCell>'
            )
            cur_y += cfg["sep_h"]
        for j, (text, st, ab) in enumerate(rows):
            cells.append(
                f'<mxCell id="{cid}_{prefix}{j}" value="{_member_label(text, st, ab)}" '
                f'style="{row_style}" vertex="1" parent="{cid}">'
                f'<mxGeometry y="{cur_y}" width="{w}" height="{cfg["row_h"]}" as="geometry"/>'
                f'</mxCell>'
            )
            cur_y += cfg["row_h"]
    return cells


def _edge_label_cell(edge_id: str, text: str, nx_f: float, ny_f: float, color: str) -> str:
    """Подпись у конца ребра (кратность): снаружи блока, со стороны входа."""
    if ny_f >= 1.0:
        off = (12, 12)          # вход снизу → подпись ниже блока, правее линии
    elif ny_f <= 0.0:
        off = (12, -12)         # вход сверху
    elif nx_f <= 0.0:
        off = (-16, -10)        # вход слева
    else:
        off = (16, -10)
    return (
        f'<mxCell id="{edge_id}_l" value="{_esc(text)}" '
        f'style="edgeLabel;html=1;align=center;verticalAlign=middle;resizable=0;'
        f'fontSize=10;fontColor={color};" vertex="1" connectable="0" parent="{edge_id}">'
        f'<mxGeometry x="1" relative="1" as="geometry">'
        f'<mxPoint x="{off[0]}" y="{off[1]}" as="offset"/></mxGeometry>'
        f'</mxCell>'
    )


def _hier_groups(relations: list[Relation], lay: Layout) -> tuple[dict, list[Relation]]:
    """
    Группы для junction: (parent, kind) → [child, …] при ≥2 потомках, лежащих ниже
    родителя. Остальные иерархические рёбра — как одиночные.
    """
    groups: dict[tuple[str, str], list[str]] = {}
    for r in relations:
        if r.kind in _HIER and lay.row_of.get(r.src, 0) > lay.row_of.get(r.tgt, 0):
            groups.setdefault((r.tgt, r.kind), []).append(r.src)
    merged = {k: v for k, v in groups.items() if len(v) >= 2}
    singles = [r for r in relations
               if not (r.kind in _HIER and (r.tgt, r.kind) in merged and r.src in merged[(r.tgt, r.kind)])]
    return merged, singles


def build_xml(classes: list[ClassInfo], theme: str = "dark",
              cfg_overrides: dict | None = None) -> str:
    if not classes:
        return _EMPTY_XML
    cfg = get_layout(cfg_overrides)
    pal = get_theme(theme)

    widths  = {c.name: _class_width(c, cfg)  for c in classes}
    heights = {c.name: _class_height(c, cfg) for c in classes}
    relations = _detect_relations(classes)
    lay = _layout(classes, relations, widths, heights, cfg)
    merged, singles = _hier_groups(relations, lay)

    cells: list[str] = []
    ids = {c.name: f"c{i}" for i, c in enumerate(classes)}
    for cls in classes:
        cells.extend(_class_cells(cls, ids[cls.name], lay.rects[cls.name], pal, cfg))

    edge_color = pal["edge"]
    m = cfg["route_margin"]

    # ── junction: один ствол к родителю, ветки от потомков ────────────────────
    reserved: dict[tuple[str, str], list[int]] = {}
    used_y: dict[int, list[tuple[int, int, int]]] = {}    # ряд → [(x1, x2, y)] занятых горизонталей
    jr = cfg["junction_r"]
    junction_pos: dict[tuple[str, str], tuple[int, int]] = {}
    for gi, ((parent, kind), kids) in enumerate(merged.items()):
        px, py, pw, ph = lay.rects[parent]
        jx = px + pw // 2
        prow = lay.row_of[parent]
        jy = lay.row_corridors[prow]
        span = (min(lay.rects[k][0] + lay.rects[k][2] // 2 for k in kids + [parent]),
                max(lay.rects[k][0] + lay.rects[k][2] // 2 for k in kids + [parent]))
        # второй junction в том же коридоре с перекрывающимся размахом — ниже на шаг
        while any(x1 <= span[1] and span[0] <= x2 and y == jy for x1, x2, y in used_y.get(prow, [])):
            jy += cfg["junction_step"]
        used_y.setdefault(prow, []).append((span[0], span[1], jy))
        junction_pos[(parent, kind)] = (jx, jy)
        reserved.setdefault((parent, "bottom"), []).append(jx)

        jid = f"j{gi}"
        cells.append(
            f'<mxCell id="{jid}" value="" '
            f'style="ellipse;whiteSpace=wrap;html=1;aspect=fixed;'
            f'fillColor={pal["junction"]};strokeColor={pal["junction"]};" '
            f'vertex="1" parent="1">'
            f'<mxGeometry x="{jx - jr}" y="{jy - jr}" width="{2 * jr}" height="{2 * jr}" as="geometry"/>'
            f'</mxCell>'
        )
        cells.append(
            f'<mxCell id="jt{gi}" value="" '
            f'style="{_edge_base(edge_color, 0.5, 0.5, 0.5, 1.0)}{_edge_arrows(kind)}" '
            f'edge="1" source="{jid}" target="{ids[parent]}" parent="1">'
            f'<mxGeometry relative="1" as="geometry"/></mxCell>'
        )
        for ki, kid in enumerate(kids):
            kx, ky, kw, kh = lay.rects[kid]
            cx = kx + kw // 2
            obstacles = [r for n, r in lay.rects.items() if n not in (kid, parent)]
            if lay.row_of[kid] == prow + 1 and path_clear([(cx, ky), (cx, jy), (jx, jy)], obstacles, m):
                wps = [(cx, jy)] if cx != jx else []
            else:
                wps = plan_route(cx, ky, jx, jy, obstacles, lay.row_corridors,
                                 lay.col_corridors, m, prefer_corridor=True)
            cells.append(
                f'<mxCell id="jb{gi}_{ki}" value="" '
                f'style="{_edge_base(edge_color, 0.5, 0.0, 0.5, 0.5)}endArrow=none;startArrow=none;" '
                f'edge="1" source="{ids[kid]}" target="{jid}" parent="1">{points_xml(wps)}</mxCell>'
            )

    # ── остальные рёбра ───────────────────────────────────────────────────────
    edge_keys = [((r.src, r.tgt), r.src, r.tgt) for r in singles]
    ports = assign_ports(edge_keys, lay.rects, reserved)
    for ei, r in enumerate(singles):
        ex_f, ey_f, nx_f, ny_f = ports.get((r.src, r.tgt), (0.5, 1.0, 0.5, 0.0))
        ex, ey = abs_point(lay.rects[r.src], ex_f, ey_f)
        nx, ny = abs_point(lay.rects[r.tgt], nx_f, ny_f)
        obstacles = [rect for n, rect in lay.rects.items() if n not in (r.src, r.tgt)]
        vertical = ey_f in (0.0, 1.0) and ny_f in (0.0, 1.0)
        wps = plan_route(ex, ey, nx, ny, obstacles, lay.row_corridors, lay.col_corridors,
                         m, prefer_corridor=vertical)
        style = _edge_style(r.kind, edge_color, ex_f, ey_f, nx_f, ny_f)
        cells.append(
            f'<mxCell id="e{ei}" value="" style="{style}" '
            f'edge="1" source="{ids[r.src]}" target="{ids[r.tgt]}" parent="1">{points_xml(wps)}</mxCell>'
        )
        if r.label:
            cells.append(_edge_label_cell(f"e{ei}", r.label, nx_f, ny_f, pal["member_font"]))

    return _wrap_xml(cells)
