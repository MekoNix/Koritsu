"""
Builder — генерирует draw.io XML для UML-диаграммы классов.
"""
import html as _html
import re as _re
from dataclasses import dataclass, field as dc_field

from .extractor import ClassInfo, FieldInfo, MethodInfo

from ._bbox import (enforce_row_gap, label_box, label_dirs, label_size, place_label,
                    spread_row, stack_rows)
from ._routing import (CorridorGrid, Rect, abs_point, assign_ports, path_clear, plan_route,
                       points_xml, side_of)
from ._text import text_width
from .styles import get_layout, get_theme

_LABEL_FONT = 10                    # px, подпись у ребра (кратность)

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
    # python / typing: обобщения пишутся квадратными скобками — list[T], dict[str, T]
    "dict", "tuple", "frozenset", "defaultdict", "deque", "Tuple", "Set", "FrozenSet",
    "DefaultDict", "Deque", "Sequence", "MutableSequence", "Mapping", "MutableMapping",
    "Iterable", "Iterator", "Collection",
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


def _last_seg(name: str) -> str:
    """`std.shared_ptr` → `shared_ptr`: обёртку узнаём по последнему сегменту."""
    return name.rsplit(".", 1)[-1]


def _type_refs(type_str: str, known) -> list[TypeRef]:
    """
    Все известные классы, упомянутые в типе, с учётом обёрток:
      `List<Task>`, `Task[]`, `list[Task]`  → many
      `Task*`, `Task&`, `shared_ptr<Task>`  → ptr (агрегация)
      `Task`, `unique_ptr<Task>`, `Optional[Task]` → по значению (композиция)

    Квадратная скобка неоднозначна: `Task[]`/`Task[10]` — массив (many),
    а `Optional[Task]`/`Callable[[int], Task]` — обобщение по-питоновски,
    и many зависит только от имени обёртки (`list`, `dict`, … из _COLLECTIONS).

    `known` — множество имён или функция «написанное имя → uid класса» (None,
    если такого класса на диаграмме нет). Квалифицированное имя (`N1.Prim`,
    `geom::Prim`) остаётся одним токеном: без namespace его не разрешить.
    """
    resolve = known if callable(known) else (lambda w: w if w in known else None)
    s = _re.sub(r'\{.*\}', '', type_str)          # { get; set; }
    s = _re.sub(r'\s*(?:::|\.)\s*', '.', s)        # std::vector, System.Collections.List
    tokens = _re.findall(r'[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*|\d+|<|>|\[|\]|[*&]', s)
    refs: list[TypeRef] = []
    stack: list[str] = []                           # обёртки generic'ов
    prev, prev_ref = "", False
    for i, tok in enumerate(tokens):
        nxt = tokens[i + 1] if i + 1 < len(tokens) else ""
        uid = None
        if tok == "<":
            stack.append(prev)
        elif tok == "[":
            if nxt == "]" or nxt.isdigit():          # массив: Task[] / Task[10]
                if refs and (prev_ref or prev in ("*", "&", ">")):
                    refs[-1].many = True
                stack.append("[]")
            else:                                    # обобщение: Optional[Task]
                stack.append(prev)
        elif tok in (">", "]"):
            if stack:
                stack.pop()
        else:
            uid = resolve(tok)
            if uid is not None:
                many = any(_last_seg(w) in _COLLECTIONS for w in stack)
                ptr = nxt in ("*", "&") or any(_last_seg(w) in _SHARED_PTRS for w in stack)
                owned = not ptr
                refs.append(TypeRef(uid, many=many, ptr=ptr, owned=owned))
        prev, prev_ref = tok, uid is not None
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
    """`+ name() const: const std::string&` — const у сигнатуры, не у типа возврата."""
    sym = _ACCESS.get(mth.access, "#")
    sig = f"{sym} {mth.name}{mth.params}"
    if mth.is_const:
        sig += " const"
    if mth.is_constructor or mth.is_destructor or not mth.return_type:
        return sig
    return f"{sig}: {mth.return_type}"


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


def _header_h(cls: ClassInfo, cfg: dict) -> int:
    """
    Высота заголовка: у стереотипа («interface», «enumeration») он в две строки.

    Постоянные 32 px хватало только на одну: у интерфейса имя класса вылезало
    из шапки на первую строку членов и наезжало на неё.
    """
    lines = 2 if cls.kind in _STEREOTYPE else 1
    return cfg["header_h"] + (lines - 1) * int(cfg["header_font"] * 1.4)


def _class_height(cls: ClassInfo, cfg: dict) -> int:
    fields, methods = _member_rows(cls)
    h = _header_h(cls, cfg) + len(fields) * cfg["row_h"] + len(methods) * cfg["row_h"]
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


def _shared_scope(uid: str, scope: str) -> int:
    """Сколько ведущих сегментов области видимости общие — «чей namespace ближе»."""
    a, b = uid.split("."), scope.split(".") if scope else []
    n = 0
    while n < len(a) - 1 and n < len(b) and a[n] == b[n]:
        n += 1
    return n


def _resolve_ref(written: str, scope: str, by_uid: dict[str, ClassInfo],
                 tails: dict[str, list[str]]) -> str | None:
    """
    Написанное имя типа → uid класса диаграммы.

    Ищем изнутри наружу: `Prim` внутри `Rendering` — это `Rendering.Prim`, а не
    первый попавшийся `Prim`. Затем по хвосту полного имени (`N1.Prim`), затем
    отбрасывая ведущие сегменты (`mod.Base` в Python, `global::N.C` в C#).
    """
    parts = [p for p in written.replace("::", ".").split(".") if p]
    segs = scope.split(".") if scope else []
    while parts:
        for i in range(len(segs), -1, -1):
            cand = ".".join(segs[:i] + parts)
            if cand in by_uid:
                return cand
        hits = tails.get(".".join(parts))
        if hits:
            best = hits[0]
            for u in hits[1:]:
                if _shared_scope(u, scope) > _shared_scope(best, scope):
                    best = u
            return best
        parts = parts[1:]
    return None


def _resolver(by_uid: dict[str, ClassInfo]):
    """
    `resolve(имя, область) -> uid`. Индекс хвостов и кеш: без них каждое имя типа
    (`int`, `string`, …) стоило бы прохода по всем классам диаграммы.
    """
    tails: dict[str, list[str]] = {}
    for u in by_uid:
        segs = u.split(".")
        for i in range(1, len(segs)):
            tails.setdefault(".".join(segs[i:]), []).append(u)
    cache: dict[tuple[str, str], str | None] = {}

    def resolve(written: str, scope: str) -> str | None:
        key = (written, scope)
        if key not in cache:
            cache[key] = _resolve_ref(written, scope, by_uid, tails)
        return cache[key]
    return resolve


def _detect_relations(classes: list[ClassInfo]) -> list[Relation]:
    by_uid: dict[str, ClassInfo] = {}
    for c in classes:
        by_uid.setdefault(c.uid, c)      # одноимённые в одной области — первый объявленный
    lookup = _resolver(by_uid)
    best: dict[tuple[str, str], Relation] = {}

    def _add(src: str, tgt: str | None, kind: str, label: str = ""):
        if tgt is None or tgt not in by_uid or tgt == src:
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
        src = cls.uid
        def resolve(w, _scope=cls.scope):
            return lookup(w, _scope)
        for parent in cls.parents:
            tgt = resolve(parent)
            pc = by_uid.get(tgt)
            _add(src, tgt, "realization" if (pc and pc.is_interface) else "inheritance")
        if cls.outer is not None:
            _add(src, cls.scope, "nesting")     # область видимости вложенного = uid внешнего
        for fld in cls.fields:
            for ref in _type_refs(fld.type_str, resolve):
                if ref.name == src:
                    continue
                label = "0..*" if ref.many else ""
                kind = "aggregation" if (ref.ptr or ref.many) else "composition"
                _add(src, ref.name, kind, label)
        for mth in cls.methods:
            types = ([mth.return_type] if mth.return_type else []) + _param_types(mth.params)
            for t in types:
                for ref in _type_refs(t, resolve):
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
    # (родитель, вид связи) → потомки, слитые в один ствол с точкой слияния
    merged:        dict            = dc_field(default_factory=dict)
    junctions:     dict            = dc_field(default_factory=dict)   # та же пара → (x, y) точки


def _keys(classes: list[ClassInfo]) -> list[str]:
    """
    Ключ раскладки для каждого класса — полный идентификатор (`Rendering.Prim`),
    он же `src`/`tgt` связей. Совпасть он может только у двух объявлений в одной
    области видимости (Python: класс переопределён в модуле); второму и далее
    ключ получает суффикс, а связи достаются первому — как и раньше.
    """
    seen: dict[str, int] = {}
    out: list[str] = []
    for c in classes:
        n = seen.get(c.uid, 0) + 1
        seen[c.uid] = n
        out.append(c.uid if n == 1 else f"{c.uid}#{n}")
    return out


def _levels(names: list[str], relations: list[Relation]) -> dict[str, int]:
    """
    Уровень (ряд) каждого класса.
      1. По наследованию/реализации: родитель выше потомка (длиннейший путь от корня).
      2. Классы вне иерархии опускаются под те, на кого ссылаются (поля, параметры,
         внешний тип) — «использующий» ниже «используемого».
    """
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


def _junction_stacks(merged: dict, xs: dict[str, int], widths: dict[str, int],
                     row_of: dict[str, int]) -> dict[tuple[str, str], int]:
    """
    Этаж точки слияния в коридоре: `(родитель, вид) → номер этажа`.

    Две точки слияния в одном коридоре с пересекающимся размахом по x нельзя
    поставить на одну высоту — стволы наложатся друг на друга, поэтому второй и
    следующие опускаются на этаж ниже. Считаем это до расстановки рядов по y:
    зазор под рядом потом делается таким, чтобы все этажи поместились в нём и
    ни одна точка не легла на блок нижнего ряда.
    """
    stack: dict[tuple[str, str], int] = {}
    used: dict[int, list[tuple[int, int, int]]] = {}       # ряд → [(x1, x2, этаж)]
    for (parent, kind), kids in merged.items():
        prow = row_of[parent]
        span = (min(xs[k] + widths[k] // 2 for k in kids + [parent]),
                max(xs[k] + widths[k] // 2 for k in kids + [parent]))
        k = 0
        while any(x1 <= span[1] and span[0] <= x2 and lvl == k for x1, x2, lvl in used.get(prow, [])):
            k += 1
        used.setdefault(prow, []).append((span[0], span[1], k))
        stack[(parent, kind)] = k
    return stack


def _layout(names: list[str], relations: list[Relation],
            widths: dict[str, int], heights: dict[str, int], cfg: dict) -> Layout:
    index = {n: i for i, n in enumerate(names)}
    level = _levels(names, relations)
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
        xs.update(spread_row(row, widths, cfg["start_x"], h_gap))

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
        for n in row:
            xs[n] = max(want.get(n, xs[n]), cfg["start_x"])
        # сдвиг «на середину потомков» мог наложить блок на соседа в ряду
        enforce_row_gap(row, xs, widths, cfg["start_x"], h_gap)

    # зазор под рядом: обычный v_gap, но если в коридоре несколько этажей точек
    # слияния — ровно столько, чтобы нижний этаж не задел блоки следующего ряда
    merged, _ = _hier_groups(relations, row_of)
    stacks = _junction_stacks(merged, xs, widths, row_of)
    jr, step, m = cfg["junction_r"], cfg["junction_step"], cfg["route_margin"]
    gaps = [v_gap] * len(rows)
    for (parent, _kind), k in stacks.items():
        ri = row_of[parent]
        gaps[ri] = max(gaps[ri], 2 * (k * step + jr + m))

    lay = Layout(merged=merged)
    lay.rects, lay.row_tops, lay.row_bottoms, lay.row_corridors = stack_rows(
        rows, xs, widths, heights, cfg["start_y"], gaps)
    lay.row_of = row_of
    for (parent, kind), k in stacks.items():
        px, _py, pw, _ph = lay.rects[parent]
        lay.junctions[(parent, kind)] = (px + pw // 2,
                                         lay.row_corridors[row_of[parent]] + k * step)
    for row in rows:
        for n in row:
            lay.col_corridors.append(xs[n] + widths[n] + h_gap // 2)
            lay.col_corridors.append(xs[n] - h_gap // 2)
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

    head_h = _header_h(cls, cfg)
    cells = [
        f'<mxCell id="{cid}" value="{label}" '
        f'style="swimlane;html=1;fontStyle=1;align=center;startSize={head_h};'
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
    cur_y = head_h
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


def _edge_label_cell(edge_id: str, text: str, off: tuple[int, int], color: str) -> str:
    """Подпись у конца ребра (кратность). Место ей ищет `place_label` по рамкам."""
    return (
        f'<mxCell id="{edge_id}_l" value="{_esc(text)}" '
        f'style="edgeLabel;html=1;align=center;verticalAlign=middle;resizable=0;'
        f'fontSize=10;fontColor={color};" vertex="1" connectable="0" parent="{edge_id}">'
        f'<mxGeometry x="1" relative="1" as="geometry">'
        f'<mxPoint x="{off[0]}" y="{off[1]}" as="offset"/></mxGeometry>'
        f'</mxCell>'
    )


def _hier_groups(relations: list[Relation], row_of: dict[str, int]) -> tuple[dict, list[Relation]]:
    """
    Группы для junction: (parent, kind) → [child, …] при ≥2 потомках, лежащих ниже
    родителя. Остальные иерархические рёбра — как одиночные.
    """
    groups: dict[tuple[str, str], list[str]] = {}
    for r in relations:
        if r.kind in _HIER and row_of.get(r.src, 0) > row_of.get(r.tgt, 0):
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

    keys = _keys(classes)
    widths  = {k: _class_width(c, cfg)  for k, c in zip(keys, classes)}
    heights = {k: _class_height(c, cfg) for k, c in zip(keys, classes)}
    relations = _detect_relations(classes)
    lay = _layout(keys, relations, widths, heights, cfg)
    merged = lay.merged
    _, singles = _hier_groups(relations, lay.row_of)

    cells: list[str] = []
    ids = {k: f"c{i}" for i, k in enumerate(keys)}
    for k, cls in zip(keys, classes):
        cells.extend(_class_cells(cls, ids[k], lay.rects[k], pal, cfg))

    edge_color = pal["edge"]
    m = cfg["route_margin"]
    # сетка коридоров строится один раз на диаграмму: по ней ищется обход, когда
    # простых L/U-образных маршрутов нет, — иначе линия пошла бы сквозь блоки
    grid = CorridorGrid(list(lay.rects.values()), lay.row_corridors, lay.col_corridors, m)
    jr = cfg["junction_r"]
    # точки слияния — препятствия для чужих линий: линия, прошедшая через чужую
    # точку, читается как связь, которой нет
    jdots = {k: (x - jr, y - jr, 2 * jr, 2 * jr) for k, (x, y) in lay.junctions.items()}
    # занятые рамки: блоки, точки слияния и уже размещённые подписи — подпись,
    # накрывшая точку слияния, прячет узел ветвления наследования
    taken: list[Rect] = list(lay.rects.values()) + list(jdots.values())

    # ── junction: один ствол к родителю, ветки от потомков ────────────────────
    reserved: dict[tuple[str, str], list[int]] = {}
    for gi, ((parent, kind), kids) in enumerate(merged.items()):
        jx, jy = lay.junctions[(parent, kind)]
        prow = lay.row_of[parent]
        reserved.setdefault((parent, "bottom"), []).append(jx)
        # ветка к junction выходит из середины верха потомка; при множественном
        # наследовании остальные рёбра того же потомка должны обойти эту точку
        for kid in kids:
            reserved.setdefault((kid, "top"), []).append(jx)

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
            obstacles = ([r for n, r in lay.rects.items() if n not in (kid, parent)]
                         + [d for gk, d in jdots.items() if gk != (parent, kind)])
            if lay.row_of[kid] == prow + 1 and path_clear([(cx, ky), (cx, jy), (jx, jy)], obstacles, m):
                wps = [(cx, jy)] if cx != jx else []
            else:
                wps = plan_route(cx, ky, jx, jy, obstacles, lay.row_corridors,
                                 lay.col_corridors, m, prefer_corridor=True, grid=grid,
                                 exit_side="top", entry_side="bottom")
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
        obstacles = ([rect for n, rect in lay.rects.items() if n not in (r.src, r.tgt)]
                     + list(jdots.values()))
        vertical = ey_f in (0.0, 1.0) and ny_f in (0.0, 1.0)
        wps = plan_route(ex, ey, nx, ny, obstacles, lay.row_corridors, lay.col_corridors,
                         m, prefer_corridor=vertical, grid=grid,
                         exit_side=side_of(ex_f, ey_f), entry_side=side_of(nx_f, ny_f))
        style = _edge_style(r.kind, edge_color, ex_f, ey_f, nx_f, ny_f)
        cells.append(
            f'<mxCell id="e{ei}" value="" style="{style}" '
            f'edge="1" source="{ids[r.src]}" target="{ids[r.tgt]}" parent="1">{points_xml(wps)}</mxCell>'
        )
        if r.label:
            # подпись стоит у конца ребра: место ищем по рамкам, чтобы кратность
            # не легла на блок, в который ребро входит, и на соседние подписи
            size = label_size(r.label, _LABEL_FONT)
            off = place_label((nx, ny), size, label_dirs(nx_f, ny_f), taken)
            taken.append(label_box((nx, ny), off, size))
            cells.append(_edge_label_cell(f"e{ei}", r.label, off, pal["edge_label"]))

    return _wrap_xml(cells)
