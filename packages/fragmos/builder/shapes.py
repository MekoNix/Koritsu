"""
shapes.py — Все фигуры draw.io для flowchart-диаграмм, измерение текста
и вспомогательные утилиты рёбер.

Размер фигуры вычисляется ТОЛЬКО здесь (`Shape.dims`): layout и эмиттер
в renderer.py берут размеры отсюда, поэтому разметка и реальные фигуры
никогда не расходятся.
"""

import html
import math

from kyotsu.text import text_width

from ._drawpyo import drawpyo


def _esc(s) -> str:
    """Подпись фигуры → HTML-текст.

    Все стили фигур содержат `html=1`, поэтому draw.io разбирает `value`
    как HTML: `i<n` показывалось как «i» (`<n` съедалось как начало тега),
    `vector<int>` — как «vector». XML-экранирование делает сам drawpyo,
    здесь — именно HTML-слой поверх него. Кавычки не трогаем: в тексте
    они безопасны, а подпись остаётся читаемой.
    """
    return html.escape(str(s if s is not None else ''), quote=False)


# ═══════════════════════════════════════════════════════════════════════════
# ИЗМЕРЕНИЕ ТЕКСТА
# ═══════════════════════════════════════════════════════════════════════════
#
# draw.io рендерит текст Helvetica/Arial; таблица ширин символов — общая
# (`kyotsu.text`), потому что тот же шрифт меряет uml_generator. Погрешность
# на строке из 30 символов — единицы px, что перекрывается pad_x.
# Запас на подстановку шрифта здесь не берётся: блок-схема считает ширину
# фигуры сама и переносит текст, лишние px уехали бы в раскладку страницы.
# `text_width` импортируется наверху и переэкспортируется отсюда: renderer.py
# берёт её из `shapes`, потому что размер фигуры считается только здесь.


def wrap_text(s: str, max_w: float, font_px: float) -> list:
    """
    Перенос по словам в ширину max_w px — так же, как draw.io при
    whiteSpace=wrap. Слово длиннее строки ломается по символам.
    """
    lines = []
    for para in str(s).split('\n'):
        words = para.split(' ')
        cur = ''
        for word in words:
            cand = word if not cur else f'{cur} {word}'
            if text_width(cand, font_px) <= max_w or not cur:
                cur = cand
            else:
                lines.append(cur)
                cur = word
            # слово шире строки — ломаем посимвольно
            while text_width(cur, font_px) > max_w and len(cur) > 1:
                cut = len(cur)
                while cut > 1 and text_width(cur[:cut], font_px) > max_w:
                    cut -= 1
                lines.append(cur[:cut])
                cur = cur[cut:]
        lines.append(cur)
    return lines


def text_box(value, cfg):
    """(ширина px, число строк) текста с переносом по cfg['max_text_w']."""
    font = cfg['font_size']
    lines = wrap_text(value, cfg['max_text_w'], font)
    return max(text_width(l, font) for l in lines), len(lines)


def _snap(v, grid):
    return int(math.ceil(v / grid) * grid) if grid else int(math.ceil(v))


# ═══════════════════════════════════════════════════════════════════════════
# ФИГУРЫ
# ═══════════════════════════════════════════════════════════════════════════

class Shape(drawpyo.diagram.Object):
    """Базовая фигура: центрируется по `cx`, верх — `y`."""

    BASE_W = 120     # минимальная ширина (и базовая для legacy-режима)
    BASE_H = 40      # минимальная высота
    STYLE = ""
    SCALES = True    # False — размер не зависит от текста (legacy-режим)
    # Во сколько раз фигура шире/выше текстового бокса: у ромба и
    # шестиугольника текст занимает только центральную часть.
    TEXT_W_FACTOR = 1.0
    TEXT_H_FACTOR = 1.0

    @classmethod
    def dims(cls, value, cfg=None):
        """(ширина, высота) фигуры для данного текста."""
        value = str(value or '')
        if cfg is None or cfg.get('size_mode', 'text') == 'legacy':
            m = (len(value) // 50) + 1 if cls.SCALES else 1
            return cls.BASE_W * m, cls.BASE_H * m

        tw, n_lines = text_box(value, cfg)
        w = tw * cls.TEXT_W_FACTOR + 2 * cfg['pad_x']
        h = n_lines * cfg['line_h'] * cls.TEXT_H_FACTOR + 2 * cfg['pad_y']
        grid = cfg.get('size_grid', 10)
        return (max(cls.BASE_W, _snap(w, grid)),
                max(cls.BASE_H, _snap(h, grid)))

    def __init__(self, page, value, cx, y, cfg=None):
        super().__init__(page=page)
        # Размер считаем по сырому тексту, в фигуру кладём экранированный.
        self.width, self.height = self.dims(value, cfg)
        self.value = _esc(value)
        self.position = (cx - self.width // 2, y)
        self.apply_style_string(self.STYLE)


class Base(Shape):
    """Начало / Конец (терминатор)."""
    BASE_H = 50
    SCALES = False
    STYLE = "rounded=1;arcSize=50;whiteSpace=wrap;html=1;"


class Execute(Shape):
    STYLE = "rounded=0;whiteSpace=wrap;html=1;"


class Io(Shape):
    TEXT_W_FACTOR = 1.15   # скошенные края параллелограмма
    STYLE = ("shape=parallelogram;perimeter=parallelogramPerimeter;"
             "whiteSpace=wrap;html=1;fixedSize=1;")


class ProcessShape(Shape):
    TEXT_W_FACTOR = 1.15   # двойные боковые линии
    STYLE = "shape=process;whiteSpace=wrap;html=1;backgroundOutline=1;"


class IfShape(Shape):
    BASE_W = 200
    BASE_H = 80
    TEXT_W_FACTOR = 1.6   # в ромб вписывается только центральная область
    TEXT_H_FACTOR = 1.8
    STYLE = "whiteSpace=wrap;html=1;shape=rhombus;"


class WhileShape(IfShape):
    pass


class ForDefault(Shape):
    TEXT_W_FACTOR = 1.25
    STYLE = ("shape=hexagon;perimeter=hexagonPerimeter2;"
             "whiteSpace=wrap;html=1;fixedSize=1;")


class LoopLimitStart(Shape):
    STYLE = "shape=loopLimit;whiteSpace=wrap;html=1;"


class LoopLimitEnd(Shape):
    STYLE = "shape=loopLimit;whiteSpace=wrap;html=1;flipV=1;"


class WaypointShape(drawpyo.diagram.Object):
    """Невидимая точка для маршрутизации стрелок."""
    def __init__(self, page, cx, y):
        super().__init__(page=page)
        self.width = 4
        self.height = 4
        self.position = (cx - 2, y - 2)
        self.apply_style_string(
            "shape=waypoint;sketch=0;fillStyle=solid;size=6;pointerEvents=1;"
            "points=[];fillColor=none;resizable=0;rotatable=0;"
            "perimeter=centerPerimeter;snapToPoint=1;shadow=1;opacity=0;")


class LabelShape(drawpyo.diagram.Object):
    """Текстовая подпись (без рамки)."""
    def __init__(self, page, text, x, y, w=44, h=20):
        super().__init__(page=page)
        self.value = _esc(text)
        self.width = w
        self.height = h
        self.position = (x, y)
        self.apply_style_string(
            "text;html=1;whiteSpace=wrap;strokeColor=none;fillColor=none;"
            "align=center;verticalAlign=middle;rounded=0;fontSize=11;")


class BBoxShape(drawpyo.diagram.Object):
    """Цветной полупрозрачный прямоугольник — визуализация bounding box."""
    def __init__(self, page, x, y, w, h, color="#dae8fc", opacity=25):
        super().__init__(page=page)
        self.width = max(int(w), 4)
        self.height = max(int(h), 4)
        self.position = (int(x), int(y))
        self.apply_style_string(
            f"rounded=0;whiteSpace=wrap;html=1;fillColor={color};"
            f"strokeColor=#888888;opacity={opacity};dashed=1;"
            f"pointerEvents=0;")


# Тип узла → класс фигуры. Единственная таблица соответствия в проекте.
SHAPES = {
    'start':            Base,
    'stop':             Base,
    'execute':          Execute,
    'process':          ProcessShape,
    'io':               Io,
    'if':               IfShape,
    'switch':           IfShape,
    'while':            WhileShape,
    'do_while':         WhileShape,
    'for_default':      ForDefault,
    'loop_limit':       LoopLimitStart,   # контейнер: верх — start, низ — LoopLimitEnd
    'loop_limit_start': LoopLimitStart,
    'loop_limit_end':   LoopLimitEnd,
}


# ═══════════════════════════════════════════════════════════════════════════
# РЁБРА
# ═══════════════════════════════════════════════════════════════════════════

# Базовые стили. Выход/вход задаются в долях фигуры: exitX/exitY — откуда
# стрелка выходит из source, entryX/entryY — куда входит в target.
_E_NONE  = "endArrow=none;html=1;rounded=0;"      # линия без наконечника
_E_ARROW = "endArrow=classic;html=1;rounded=0;"   # с наконечником
_E_BLOCK = "endArrow=block;html=1;rounded=0;"

_DOWN        = _E_NONE + "exitX=0.5;exitY=1;entryX=0.5;entryY=0;"  # вниз по оси
_FROM_BOTTOM = _E_NONE + "exitX=0.5;exitY=1;"                      # низ → куда угодно
_FROM_RIGHT  = _E_NONE + "exitX=1;exitY=0.5;"                      # правый угол ромба
_FROM_LEFT   = _E_NONE + "exitX=0;exitY=0.5;"                      # левый угол ромба
_RIGHT_TO_TOP = _E_NONE + "exitX=1;exitY=0.5;entryX=0.5;entryY=0;" # ромб → верх ветки
_LEFT_TO_TOP  = _E_NONE + "exitX=0;exitY=0.5;entryX=0.5;entryY=0;"
_SWITCH_CASE  = _E_BLOCK + "exitX=0.5;exitY=1;entryX=0.5;entryY=0;"
_BACK_WHILE   = _E_ARROW + "exitX=0.5;exitY=1;"                    # возврат на ось
_BACK_FOR     = _E_ARROW + "exitX=0.5;exitY=1;entryX=0;entryY=0.5;" # возврат в левый бок
_RETURN_JUMP  = _E_NONE + "exitX=0.5;exitY=1;entryX=0.5;entryY=0;"  # «Вернуть» → «Конец» сверху
_BACK_DO      = _E_ARROW + "exitX=0;exitY=0.5;"                    # do-while: левый угол ромба → вверх


def _edge(page, src, dst, style, pts=None, *, waypoints=None):
    """Создать стрелку с заданным стилем и промежуточными точками.

    `waypoints` — drawpyo-стиль маршрутизации (по умолчанию `orthogonal`,
    что добавляет `edgeStyle=orthogonalEdgeStyle` в финальную style-строку).
    Передай `"straight"`, чтобы drawio честно шёл по `pts` и завершался
    в перимитре target'а, не пытаясь auto-route к ближайшему перимитру.
    """
    e = drawpyo.diagram.Edge(page=page)
    e.source = src
    e.target = dst
    if waypoints is not None:
        e.waypoints = waypoints
    e.apply_style_string(style)
    for p in (pts or []):
        e.add_point_pos(p)
    return e


def _bot(obj):
    """Нижняя координата объекта."""
    return obj.position[1] + obj.height


def _cx(obj):
    """Центр объекта по X."""
    return obj.position[0] + obj.width // 2
