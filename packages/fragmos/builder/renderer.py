"""
renderer.py — Двухпроходный рендерер списка узлов в draw.io XML.

Проход 1, `layout()`  — строит дерево Item/Block: размеры фигур и все
                        вертикальные/горизонтальные смещения внутри узла.
                        Единственное место с формулами раскладки.
Проход 2, `Renderer`  — обходит дерево и создаёт фигуры/рёбра по готовым
                        смещениям. Ничего не вычисляет, кроме абсолютных
                        координат = (cx, y) + смещение из Item.

Все размеры фигур — из shapes.Shape.dims, один источник для обоих проходов.
"""

from .shapes import (
    SHAPES, Execute, IfShape, WhileShape, ForDefault,
    WaypointShape, LabelShape, BBoxShape, LoopLimitEnd,
    _edge, _bot, _cx,
    _DOWN, _FROM_BOTTOM, _FROM_RIGHT, _FROM_LEFT,
    _RIGHT_TO_TOP, _LEFT_TO_TOP, _SWITCH_CASE, _BACK_WHILE, _BACK_FOR,
    _RETURN_JUMP, _BACK_DO,
)
from .config import DEFAULT_CFG

# Узлы без детей: просто фигура на оси + стрелка сверху.
_SIMPLE = frozenset(('start', 'stop', 'process', 'execute', 'io',
                     'loop_limit_start', 'loop_limit_end'))
_LOOPS = frozenset(('while', 'for_default'))
_DO = 'do_while'
_LIMIT = 'loop_limit'


# ═══════════════════════════════════════════════════════════════════════════
# ПРОХОД 1 — LAYOUT
# ═══════════════════════════════════════════════════════════════════════════

class Block:
    """Вертикальная цепочка узлов на одной оси."""
    __slots__ = ('items', 'L', 'R', 'H')

    def __init__(self, items, L, R, H):
        self.items, self.L, self.R, self.H = items, L, R, H

    def __bool__(self):
        return bool(self.items)


class Item:
    """
    Один узел с разметкой. Все *_dy — смещения вниз от верха фигуры,
    все *_dx — смещения вправо от оси (отрицательные — влево).

    L / R — вылет поддерева влево/вправо от оси,
    H     — высота поддерева от верха фигуры до точки, где продолжится
            следующий узел (без межузлового gap).
    """
    __slots__ = ('node', 'type', 'cls', 'w', 'h', 'L', 'R', 'H', 'top_dy',
                 'yes', 'no', 'd', 'branch_dy', 'merge_dy',          # if
                 'cases', 'case_dy',                                   # switch
                 'body', 'body_dy', 'back_dx', 'exit_dx', 'exit_dy', 'wc',   # loops
                 'end_w', 'end_h', 'end_dy', 'has_break')                    # loop_limit

    def __init__(self, node, cls, cfg):
        self.node = node
        self.type = node['type']
        self.cls = cls
        self.w, self.h = cls.dims(node.get('value', ''), cfg)
        self.L = self.R = self.w // 2
        self.H = self.h
        self.top_dy = 0     # отступ фигуры от верха item (зона стыка back-arrow)


class Case:
    """Колонка switch: прямоугольник с образцом + тело."""
    __slots__ = ('pattern', 'rw', 'rh', 'body', 'half', 'dx')

    def __init__(self, pattern, rw, rh, body, half):
        self.pattern, self.rw, self.rh, self.body, self.half = pattern, rw, rh, body, half
        self.dx = 0


def _corridor(cfg, depth):
    """Ширина коридора для WHILE/FOR на заданной глубине вложенности."""
    val = cfg["while_corridor_base"] - depth * cfg["while_corridor_step"]
    return max(val, cfg["while_corridor_min"])


def layout(nodes, cfg, depth=0) -> Block:
    """Строит разметку для списка узлов на одной оси."""
    gap = cfg['gap_y']
    items = []
    for node in nodes:
        t = node['type']
        cls = SHAPES.get(t)
        if cls is None:
            continue
        it = Item(node, cls, cfg)
        if t == 'if':
            _layout_if(it, cfg, depth)
        elif t == 'switch':
            _layout_switch(it, cfg, depth)
        elif t == _LIMIT:
            _layout_limit(it, cfg, depth)
        elif t in _LOOPS or t == _DO:
            if t == _DO:
                _layout_do(it, cfg, depth)
            else:
                _layout_loop(it, cfg, depth)
            # Back-arrow у while / do-while стыкуется с входящей линией НАД
            # первой фигурой цикла. Если цикл первый в блоке (ветка IF: зазор
            # всего if_branch_vgap), резервируем эту зону внутри его
            # собственного bbox, иначе стрелка ложится на родительский ромб.
            if t != 'for_default' and it.body and not items:
                it.top_dy = cfg['while_back_top_gap'] + cfg['label_gap']
                it.H += it.top_dy
        items.append(it)

    L = max((it.L for it in items), default=0)
    R = max((it.R for it in items), default=0)
    H = sum(it.H for it in items) + gap * max(len(items) - 1, 0)
    return Block(items, L, R, H)


def _layout_if(it, cfg, depth):
    gap = cfg['gap_y']
    half = cfg['if_empty_branch_half']

    it.yes = layout(it.node.get('children', []), cfg, depth)
    it.no = layout(it.node.get('else_children', []), cfg, depth)
    yl, yr, yh = (it.yes.L, it.yes.R, it.yes.H) if it.yes else (half, half, 0)
    nl, nr, nh = (it.no.L, it.no.R, it.no.H) if it.no else (half, half, 0)

    # Центры веток: не ближе, чем bbox-ы позволяют, и не ближе угла ромба.
    d_bbox = (yl + nr + cfg['if_branch_min_gap']) / 2
    d_rh = it.w // 2 + cfg['if_branch_gap']
    it.d = int(max(d_bbox, d_rh)) + 1

    it.branch_dy = it.h + cfg['if_branch_vgap']
    it.merge_dy = it.branch_dy + max(yh, nh) + gap
    it.L = max(it.L, it.d + nl)
    it.R = max(it.R, it.d + yr)
    it.H = it.merge_dy


def _layout_switch(it, cfg, depth):
    gap = cfg['gap_y']
    case_gap = cfg['switch_case_gap']
    min_half = cfg['switch_case_min_half']

    it.cases = []
    for raw in it.node.get('cases', []):
        pattern = raw.get('pattern', '')
        rw, rh = Execute.dims(pattern, cfg)
        body = layout(raw.get('body', []), cfg, depth + 1)
        half = max(body.L, body.R, rw // 2, min_half)
        it.cases.append(Case(pattern, rw, rh, body, half))

    if not it.cases:
        return

    total_w = sum(2 * c.half for c in it.cases) + (len(it.cases) - 1) * case_gap
    cur = -(total_w // 2)
    for c in it.cases:
        c.dx = cur + c.half
        cur += 2 * c.half + case_gap

    it.case_dy = it.h + gap
    col_h = max(c.rh + (gap + c.body.H if c.body else 0) for c in it.cases)
    it.merge_dy = it.case_dy + col_h + gap
    it.L = it.R = max(total_w, it.w) // 2
    it.H = it.merge_dy


def _layout_loop(it, cfg, depth):
    gap = cfg['gap_y']
    wc = _corridor(cfg, depth)
    w2 = it.w // 2

    it.body = layout(it.node.get('children', []), cfg, depth + 1)
    bl, br, bh = (it.body.L, it.body.R, it.body.H) if it.body else (w2, w2, 0)

    it.wc = wc
    it.back_dx = max(bl, w2) + wc          # ось возвратной стрелки (слева)
    it.exit_dx = max(br, w2) + wc          # ось выхода «Нет» (справа)
    it.body_dy = it.h + gap
    bottom = it.body_dy + bh if it.body else it.h
    it.exit_dy = bottom + gap * 2
    it.L, it.R, it.H = it.back_dx, it.exit_dx, it.exit_dy


def _attr(o, name, default):
    """Числовой атрибут стиля ребра (exitX и т.п.); None → default."""
    v = getattr(o, name, None)
    return default if v is None else float(v)


def _layout_do(it, cfg, depth):
    """do … while: тело сверху, ромб условия снизу. Возврат («Да») — из
    левого угла ромба вверх по левому коридору к входу в тело; выход
    («Нет») — вниз по оси. Правый коридор — под break-стрелки."""
    gap = cfg['gap_y']
    wc = _corridor(cfg, depth)
    w2 = it.w // 2

    it.body = layout(it.node.get('children', []), cfg, depth + 1)
    bl, br, bh = (it.body.L, it.body.R, it.body.H) if it.body else (w2, w2, 0)

    it.wc = wc
    it.back_dx = max(bl, w2) + wc
    it.exit_dx = max(br, w2) + wc
    it.body_dy = 0
    it.branch_dy = bh + gap if it.body else 0     # верх ромба
    it.exit_dy = it.branch_dy + it.h + gap        # точка стыка break-стрелок
    it.L, it.R, it.H = it.back_dx, it.exit_dx, it.exit_dy


def _jumps(nodes) -> tuple:
    """(есть break, есть continue) в теле цикла, не заглядывая во вложенные циклы."""
    has_b = has_c = False
    for n in nodes:
        j = n.get('jump')
        has_b |= j == 'break'
        has_c |= j == 'continue'
        if n.get('type') in ('while', 'for_default', 'do_while', 'loop_limit'):
            continue
        for key in ('children', 'else_children'):
            b, c = _jumps(n.get(key) or [])
            has_b |= b
            has_c |= c
        for case in n.get('cases') or []:
            b, c = _jumps(case.get('body') or [])
            has_b |= b
            has_c |= c
    return has_b, has_c


def _layout_limit(it, cfg, depth):
    """Граница цикла (ГОСТ 2.7): верхний символ, тело, нижний символ — всё на
    оси. Правый коридор резервируется только если в теле есть break/continue:
    continue идёт во внутренний коридор к верху нижнего символа, break — во
    внешний, к точке под ним."""
    gap = cfg['gap_y']
    wc = _corridor(cfg, depth)
    w2 = it.w // 2
    children = it.node.get('children', [])
    it.body = layout(children, cfg, depth + 1)
    bl, br, bh = (it.body.L, it.body.R, it.body.H) if it.body else (w2, w2, 0)
    it.end_w, it.end_h = LoopLimitEnd.dims(it.node.get('end_value', ''), cfg)
    e2 = it.end_w // 2

    has_b, has_c = _jumps(children)
    it.has_break = has_b
    it.wc = wc
    it.body_dy = it.h + gap
    it.end_dy = it.body_dy + bh + gap if it.body else it.h + gap
    corridor = wc if (has_b or has_c) else 0
    it.exit_dx = max(br, w2, e2) + corridor          # правый коридор
    it.back_dx = max(bl, w2, e2) + corridor          # левый коридор (переходы левее оси)
    it.exit_dy = it.end_dy + it.end_h + (gap // 2 if has_b else 0)
    it.L, it.R, it.H = it.back_dx, it.exit_dx, it.exit_dy


def _terminates(block) -> bool:
    """Поток блока не идёт дальше: return / stop, либо if с двумя такими ветками."""
    if not block:
        return False
    last = block.items[-1]
    if last.type == 'stop' or last.node.get('returns') or last.node.get('jump'):
        return True
    if last.type == 'if':
        return bool(last.yes) and bool(last.no) and _terminates(last.yes) and _terminates(last.no)
    if last.type == 'switch' and last.cases:
        return (any(c.pattern == '_' for c in last.cases)
                and all(_terminates(c.body) for c in last.cases))
    return False


# ═══════════════════════════════════════════════════════════════════════════
# ПРОХОД 2 — ЭМИССИЯ
# ═══════════════════════════════════════════════════════════════════════════

class Renderer:
    """Создаёт фигуры и рёбра draw.io по готовой разметке."""

    def __init__(self, page, cfg=None):
        self.page = page
        self.cfg = cfg or DEFAULT_CFG
        self._returns = []      # блоки «Вернуть …», ждущие стрелки к «Конец»
        self._loops = []        # стек контекстов циклов: {'break': [...], 'continue': [...]}

    # ── публичный вход ───────────────────────────────────────────────────

    def render(self, nodes, cx, y, depth=0):
        """layout + emit одной страницы. Возвращает (first_obj, last_obj)."""
        block = layout(nodes, self.cfg, depth)
        self._returns = []
        first, last = self.emit(block, cx, y)
        if block and block.items[-1].type == 'stop':
            self._connect_returns(last, cx + block.R + self.cfg['while_corridor_base'])
        return first, last

    def _connect_returns(self, stop, jump_x):
        """Стрелки от всех «Вернуть …» к единственному «Конец»: к линии стыка
        над терминатором (gap/2 выше его верха), затем к оси и в «Конец» СВЕРХУ.

        Если колонка под блоком «Вернуть» до линии стыка свободна — идём прямо
        вниз. Иначе — правым обходом по внешнему коридору (jump_x)."""
        gap = self.cfg['gap_y']
        stop_cx = _cx(stop)
        join_y = stop.position[1] - gap // 2
        for obj in self._returns:
            ocx = _cx(obj)
            turn_y = _bot(obj) + gap // 2
            if self._column_free(ocx, _bot(obj), join_y - 1, obj):
                pts = [] if ocx == stop_cx else [(ocx, join_y), (stop_cx, join_y)]
            else:
                pts = [(ocx, turn_y), (jump_x, turn_y),
                       (jump_x, join_y), (stop_cx, join_y)]
            _edge(self.page, obj, stop, _RETURN_JUMP, pts=pts)
        self._returns = []

    def _column_free(self, x, y0, y1, skip=None, pad=6):
        """Свободна ли вертикаль x на отрезке [y0, y1]: не задевает фигур и
        не пересекает горизонтальных / не ложится на вертикальные отрезки рёбер."""
        for o in self.page.objects:
            if o is skip:
                continue
            pos = getattr(o, 'position', None)
            if pos is not None and getattr(o, 'width', None) is not None:
                ox, oy = pos
                if (ox - pad <= x <= ox + o.width + pad
                        and oy <= y1 and oy + o.height >= y0):
                    return False
                continue
            geom = getattr(o, 'geometry', None)
            pts = [(p.x, p.y) for p in getattr(geom, 'points', None) or []]
            if not pts:
                continue
            src, dst = getattr(o, 'source', None), getattr(o, 'target', None)
            if src is not None:
                pts.insert(0, (src.position[0] + src.width * _attr(o, 'exitX', 0.5),
                               src.position[1] + src.height * _attr(o, 'exitY', 1)))
            if dst is not None:
                pts.append((dst.position[0] + dst.width * _attr(o, 'entryX', 0.5),
                            dst.position[1] + dst.height * _attr(o, 'entryY', 0)))
            for (ax, ay), (bx, by) in zip(pts, pts[1:]):
                if ay == by:                                   # горизонталь
                    if min(ax, bx) <= x <= max(ax, bx) and y0 <= ay <= y1:
                        return False
                elif abs(ax - x) <= pad and abs(bx - x) <= pad:  # вертикаль на той же оси
                    if min(ay, by) <= y1 and max(ay, by) >= y0:
                        return False
        return True

    def emit(self, block: Block, cx, y, prev_obj=None):
        """Рисует Block с осью cx и верхом y. Возвращает (first, last)."""
        gap = self.cfg['gap_y']
        first = None
        for it in block.items:
            if it.type == 'if':
                fst, lst = self._emit_if(it, cx, y, prev_obj)
            elif it.type == 'switch':
                fst, lst = self._emit_switch(it, cx, y, prev_obj)
            elif it.type in _LOOPS:
                fst, lst = self._emit_loop(it, cx, y, prev_obj)
            elif it.type == _DO:
                fst, lst = self._emit_do(it, cx, y, prev_obj)
            elif it.type == _LIMIT:
                fst, lst = self._emit_limit(it, cx, y, prev_obj)
            else:
                fst = lst = self._place(it, cx, y, prev_obj)
                jump = it.node.get('jump')
                if jump and self._loops:
                    self._loops[-1][jump].append(lst)   # стрелка нарисуется циклом
                    if it is not block.items[-1]:
                        lst = None                      # код после break/continue недостижим
                elif it.node.get('returns') and it is not self._tail(block, it):
                    self._returns.append(lst)       # прыжок к «Конец»
                    if it is not block.items[-1]:
                        lst = None                  # код после return недостижим
                # хвостовой return перед «Конец» — обычная стрелка вниз
            first = first or fst
            prev_obj = lst
            y += it.H + gap
        return first, prev_obj

    def _tail(self, block, it):
        """Item, если он предпоследний в блоке верхнего уровня перед stop (return в хвосте функции)."""
        items = block.items
        if len(items) >= 2 and items[-1].type == 'stop' and items[-2] is it:
            return it
        return None

    # ── утилиты ──────────────────────────────────────────────────────────

    def _place(self, it, cx, y, prev_obj):
        """Фигура узла на (cx, y) + стрелка от предыдущего объекта."""
        obj = it.cls(self.page, it.node.get('value', ''), cx, y, self.cfg)
        if prev_obj:
            _edge(self.page, prev_obj, obj, _DOWN)
        return obj

    def _label(self, text, x, y):
        cfg = self.cfg
        LabelShape(self.page, text, x, y, cfg['label_w'], cfg['label_h'])

    def _bbox(self, cx, y, it, color, opacity):
        """Отладочный bbox поддерева Item."""
        px, py = self.cfg['bbox_pad_x'], self.cfg['bbox_pad_y']
        BBoxShape(self.page, cx - it.L - px, y - py,
                  it.L + it.R + 2 * px, it.H + 2 * py,
                  color=color, opacity=opacity)

    def _row_free(self, y, x0, x1, skip=None, pad=6):
        """Свободна ли горизонталь y на отрезке [x0, x1]: не задевает фигур
        и не пересекает вертикальных отрезков рёбер."""
        x0, x1 = min(x0, x1), max(x0, x1)
        for o in self.page.objects:
            if o is skip:
                continue
            pos = getattr(o, 'position', None)
            if pos is not None and getattr(o, 'width', None) is not None:
                ox, oy = pos
                if (oy - pad <= y <= oy + o.height + pad
                        and ox <= x1 and ox + o.width >= x0):
                    return False
                continue
            for (ax, ay), (bx, by) in self._edge_segments(o):
                if ax == bx and x0 < ax < x1 and min(ay, by) < y < max(ay, by):
                    return False
        return True

    def _edge_segments(self, o):
        """Отрезки ребра drawpyo вместе с точками выхода/входа."""
        geom = getattr(o, 'geometry', None)
        pts = [(p.x, p.y) for p in getattr(geom, 'points', None) or []]
        if not pts:
            return []
        src, dst = getattr(o, 'source', None), getattr(o, 'target', None)
        if src is not None:
            pts.insert(0, (src.position[0] + src.width * _attr(o, 'exitX', 0.5),
                           src.position[1] + src.height * _attr(o, 'exitY', 1)))
        if dst is not None:
            pts.append((dst.position[0] + dst.width * _attr(o, 'entryX', 0.5),
                        dst.position[1] + dst.height * _attr(o, 'entryY', 0)))
        return list(zip(pts, pts[1:]))

    # ── BREAK / CONTINUE ─────────────────────────────────────────────────

    def _jump_route(self, obj, side_x, join_y, row_y, inner_x=None):
        """Точки маршрута от блока break/continue к линии на высоте join_y
        через боковой коридор side_x. Предпочтения по порядку:
          1. прямо вниз по своей колонке до join_y;
          2. вбок сразу под блоком, затем по коридору side_x;
          3. вниз до ряда row_y (свободная полоса под телом), вбок, по коридору;
          4. вбок к внутреннему коридору inner_x, вниз до row_y, затем к side_x
             (для continue: обход ветки «Нет» справа, а не сквозь неё);
          5. как 2 (с пересечением — лучше, чем ничего).
        Возвращает (pts, x_join) — точки и x, где маршрут выходит на join_y."""
        gap = self.cfg['gap_y']
        bcx, bot = _cx(obj), _bot(obj)
        turn_y = bot + gap // 2
        if self._column_free(bcx, bot, join_y - 1, obj):
            return [(bcx, join_y)], bcx
        if self._row_free(turn_y, bcx, side_x, obj):
            return [(bcx, turn_y), (side_x, turn_y), (side_x, join_y)], side_x
        if (row_y > turn_y and self._column_free(bcx, bot, row_y - 1, obj)
                and self._row_free(row_y, bcx, side_x, obj)):
            return [(bcx, row_y), (side_x, row_y), (side_x, join_y)], side_x
        if (inner_x is not None and row_y > turn_y
                and self._row_free(turn_y, bcx, inner_x, obj)
                and self._column_free(inner_x, turn_y, row_y - 1, obj)
                and self._row_free(row_y, inner_x, side_x, obj)):
            pts = [(bcx, turn_y), (inner_x, turn_y), (inner_x, row_y), (side_x, row_y)]
            if row_y != join_y:
                pts.append((side_x, join_y))
            return pts, side_x
        return [(bcx, turn_y), (side_x, turn_y), (side_x, join_y)], side_x

    def _emit_breaks(self, ctx, cx, exit_x, join_y, row_y, target):
        """break → линия выхода из цикла (горизонталь на join_y, к оси)."""
        for obj in ctx['break']:
            pts, xj = self._jump_route(obj, exit_x, join_y, row_y)
            if xj != cx:
                pts.append((cx, join_y))
            _edge(self.page, obj, target, _RETURN_JUMP, pts=pts)

    # ── IF ───────────────────────────────────────────────────────────────

    def _emit_if(self, it, cx, y, prev_obj):
        cfg = self.cfg
        rh = self._place(it, cx, y, prev_obj)
        w2 = it.w // 2
        mid_y = y + it.h // 2
        yes_cx, no_cx = cx + it.d, cx - it.d
        branch_y = y + it.branch_dy
        merge_y = y + it.merge_dy
        lab_y = mid_y - cfg['label_dy']

        if cfg.get('show_bbox'):
            self._bbox(cx, y, it, "#fff2cc", 25)

        yes_last = no_last = None
        if it.yes:
            yes_first, yes_last = self.emit(it.yes, yes_cx, branch_y)
            _edge(self.page, rh, yes_first, _RIGHT_TO_TOP, pts=[(yes_cx, mid_y)])
        self._label(cfg['label_yes'], cx + w2 + cfg['label_gap'], lab_y)

        self._label(cfg['label_no'], cx - w2 - cfg['label_gap'] - cfg['label_w'], lab_y)
        if it.no:
            no_first, no_last = self.emit(it.no, no_cx, branch_y)
            _edge(self.page, rh, no_first, _LEFT_TO_TOP, pts=[(no_cx, mid_y)])

        if _terminates(it.yes) and _terminates(it.no):
            return rh, None                  # обе ветки ушли к «Конец» — слияния нет
        wp = WaypointShape(self.page, cx, merge_y)
        self._to_merge(rh, yes_last, yes_cx, mid_y, merge_y, cx, wp, _FROM_RIGHT, it.yes)
        self._to_merge(rh, no_last, no_cx, mid_y, merge_y, cx, wp, _FROM_LEFT, it.no)
        return rh, wp

    def _to_merge(self, rh, last, bcx, mid_y, merge_y, cx, wp, from_side, block=None):
        """Стрелка от конца ветки (или от ромба, если ветка пуста) к точке слияния."""
        if block is not None and _terminates(block):
            return                       # ветка кончилась терминатором — потока дальше нет
        if last:
            _edge(self.page, last, wp, _FROM_BOTTOM, pts=[(bcx, merge_y)])
        else:
            _edge(self.page, rh, wp, from_side,
                  pts=[(bcx, mid_y), (bcx, merge_y), (cx, merge_y)])

    # ── SWITCH ───────────────────────────────────────────────────────────

    def _emit_switch(self, it, cx, y, prev_obj):
        cfg = self.cfg
        gap = cfg['gap_y']
        rh = self._place(it, cx, y, prev_obj)
        if not it.cases:
            return rh, rh

        case_y = y + it.case_dy
        merge_y = y + it.merge_dy

        if cfg.get('show_bbox'):
            self._bbox(cx, y, it, "#fff2cc", 22)

        last_objs = []
        fan_y = y + it.h + gap // 2          # явные точки веера: их видят _column_free/_row_free
        for c in it.cases:
            ccx = cx + c.dx
            rect = Execute(self.page, c.pattern, ccx, case_y, cfg)
            _edge(self.page, rh, rect, _SWITCH_CASE, pts=[(cx, fan_y), (ccx, fan_y)])
            if c.body:
                _, last_b = self.emit(c.body, ccx, _bot(rect) + gap, rect)
                if _terminates(c.body):
                    continue                 # return/break — к слиянию не идёт
                last_objs.append(last_b or rect)
            else:
                last_objs.append(rect)

        if not last_objs:
            return rh, None                  # все ветки ушли — слияния нет
        wp = WaypointShape(self.page, cx, merge_y)
        for lo in last_objs:
            _edge(self.page, lo, wp, _FROM_BOTTOM, pts=[(_cx(lo), merge_y), (cx, merge_y)])
        return rh, wp

    # ── WHILE / FOR ──────────────────────────────────────────────────────

    def _emit_loop(self, it, cx, y, prev_obj):
        cfg = self.cfg
        is_while = it.type == 'while'
        y += it.top_dy                       # всё ниже — от верха фигуры
        hd = self._place(it, cx, y, prev_obj)
        w2 = it.w // 2
        mid_y = y + it.h // 2
        bot_y = y + it.h
        back_x, exit_x = cx - it.back_dx, cx + it.exit_dx
        exit_y = y + it.exit_dy

        if cfg.get('show_bbox'):
            self._bbox(cx, y, it, "#dae8fc" if is_while else "#e1d5e7", 22)

        ctx = {'break': [], 'continue': []}
        self._loops.append(ctx)
        last_child = None
        if it.body:
            first_child, last_child = self.emit(it.body, cx, y + it.body_dy)
            _edge(self.page, hd, first_child, _DOWN)
            if is_while:
                self._label(cfg['label_yes'], cx + cfg['label_gap'], bot_y + cfg['label_gap'])
        self._loops.pop()
        if is_while:
            self._label(cfg['label_no'], cx + w2 + cfg['label_gap'], mid_y - cfg['label_dy'])

        entry_y = y - cfg['while_back_top_gap']
        body_bot = y + it.body_dy + it.body.H if it.body else bot_y
        if last_child and not _terminates(it.body):
            turn_y = _bot(last_child) + cfg['while_back_turn_gap']
            if is_while:
                self._back_arrow_while(last_child, cx, back_x, turn_y, entry_y)
            else:
                self._back_arrow_for(last_child, hd, back_x, turn_y, mid_y)

        exit_wp = WaypointShape(self.page, cx, exit_y)
        _edge(self.page, hd, exit_wp, _FROM_RIGHT,
              pts=[(exit_x, mid_y), (exit_x, exit_y), (cx, exit_y)])

        # continue — в горизонталь возвратной стрелки (ряд back-turn под телом);
        # break — в exit-линию. Сначала continue: их ряд выше, break-колонки
        # его учитывают при проверке свободного места.
        back_row = (_bot(last_child) if last_child else body_bot) + cfg['while_back_turn_gap']
        inner_x = exit_x - it.wc // 2
        for obj in ctx['continue']:
            pts, xj = self._jump_route(obj, back_x, back_row, back_row, inner_x)
            if xj != back_x:
                pts.append((back_x, back_row))
            if is_while:
                join = WaypointShape(self.page, cx, entry_y)
                _edge(self.page, obj, join, _BACK_WHILE,
                      pts=pts + [(back_x, entry_y)], waypoints="straight")
            else:
                _edge(self.page, obj, hd, _BACK_FOR, pts=pts + [(back_x, mid_y)])
        self._emit_breaks(ctx, cx, exit_x, exit_y, body_bot + cfg['gap_y'], exit_wp)
        return hd, exit_wp

    # ── DO … WHILE ───────────────────────────────────────────────────────

    def _emit_do(self, it, cx, y, prev_obj):
        cfg = self.cfg
        gap = cfg['gap_y']
        y += it.top_dy
        back_x, exit_x = cx - it.back_dx, cx + it.exit_dx
        entry_y = y - cfg['while_back_top_gap']

        if cfg.get('show_bbox'):
            self._bbox(cx, y, it, "#dae8fc", 22)

        ctx = {'break': [], 'continue': []}
        self._loops.append(ctx)
        first_child = last_child = None
        if it.body:
            first_child, last_child = self.emit(it.body, cx, y, prev_obj)
        self._loops.pop()

        hd_y = y + it.branch_dy
        hd = self._place(it, cx, hd_y, last_child if it.body else prev_obj)
        w2 = it.w // 2
        mid_y = hd_y + it.h // 2
        exit_y = y + it.exit_dy

        # «Да» — из левого угла ромба вверх по коридору к входу в тело.
        if it.body:
            join = WaypointShape(self.page, cx, entry_y)
            _edge(self.page, hd, join, _BACK_DO,
                  pts=[(back_x, mid_y), (back_x, entry_y)], waypoints="straight")
        self._label(cfg['label_yes'], cx - w2 - cfg['label_gap'] - cfg['label_w'],
                    mid_y - cfg['label_dy'])
        self._label(cfg['label_no'], cx + cfg['label_gap'], hd_y + it.h + cfg['label_gap'])

        exit_wp = WaypointShape(self.page, cx, exit_y)
        _edge(self.page, hd, exit_wp, _DOWN)

        # break — в линию под ромбом; continue — к ромбу сверху (линия стыка над ним).
        self._emit_breaks(ctx, cx, exit_x, exit_y, hd_y - gap // 2, exit_wp)
        cont_y = hd_y - gap // 2
        for obj in ctx['continue']:
            pts, xj = self._jump_route(obj, exit_x, cont_y, cont_y)
            if xj != cx:
                pts.append((cx, cont_y))
            _edge(self.page, obj, hd, _RETURN_JUMP, pts=pts)
        return first_child or hd, exit_wp

    # ── ГРАНИЦА ЦИКЛА (loop_limit) ───────────────────────────────────────

    def _emit_limit(self, it, cx, y, prev_obj):
        cfg = self.cfg
        gap = cfg['gap_y']
        top = self._place(it, cx, y, prev_obj)

        if cfg.get('show_bbox'):
            self._bbox(cx, y, it, "#d5e8d4", 22)

        ctx = {'break': [], 'continue': []}
        self._loops.append(ctx)
        last = top
        if it.body:
            _, last = self.emit(it.body, cx, y + it.body_dy, top)
        self._loops.pop()

        end_y = y + it.end_dy
        end = LoopLimitEnd(self.page, it.node.get('end_value', ''), cx, end_y, cfg)
        if last is not None:
            _edge(self.page, last, end, _DOWN)

        # Переходы идут по коридору своей стороны: правее оси — правый,
        # левее — левый. continue — во внутреннюю полосу коридора к верху
        # нижнего символа, break — во внешнюю, под него.
        def side(obj, inner):
            right = _cx(obj) >= cx
            x = cx + it.exit_dx if right else cx - it.back_dx
            return x - it.wc // 2 if right else x + it.wc // 2 if inner else x

        cont_y = end_y - gap // 2
        for obj in ctx['continue']:
            pts, xj = self._jump_route(obj, side(obj, True), cont_y, cont_y)
            if xj != cx:
                pts.append((cx, cont_y))
            _edge(self.page, obj, end, _RETURN_JUMP, pts=pts)
        if not it.has_break:
            return top, end
        exit_y = y + it.exit_dy
        exit_wp = WaypointShape(self.page, cx, exit_y)
        _edge(self.page, end, exit_wp, _DOWN)
        for obj in ctx['break']:
            pts, xj = self._jump_route(obj, side(obj, False), exit_y, exit_y)
            if xj != cx:
                pts.append((cx, exit_y))
            _edge(self.page, obj, exit_wp, _RETURN_JUMP, pts=pts)
        return top, exit_wp

    def _back_arrow_while(self, last_child, cx, back_x, turn_y, entry_y):
        # WHILE: возврат садится на ВХОДЯЩУЮ линию над ромбом. Для этого —
        # невидимый Waypoint на оси, на while_back_top_gap выше верха ромба,
        # и `waypoints="straight"`: иначе orthogonal-роутер drawio спрямляет
        # финальный сегмент в перимитр ромба, игнорируя наш target.
        back_join = WaypointShape(self.page, cx, entry_y)
        _edge(self.page, last_child, back_join, _BACK_WHILE,
              pts=[(_cx(last_child), turn_y), (back_x, turn_y), (back_x, entry_y)],
              waypoints="straight")

    def _back_arrow_for(self, last_child, hd, back_x, turn_y, mid_y):
        # FOR: возврат входит в ЛЕВЫЙ БОК шестиугольника (entryX=0;entryY=0.5).
        # Последняя точка — на высоте середины фигуры: раньше здесь была
        # точка над верхом (как у while), и orthogonal-роутер тянул линию
        # выше шестиугольника, а затем возвращал вниз к боку — «крючок».
        _edge(self.page, last_child, hd, _BACK_FOR,
              pts=[(_cx(last_child), turn_y), (back_x, turn_y), (back_x, mid_y)])
