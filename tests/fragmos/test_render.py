"""
Тесты слоя раскладки: код → draw.io XML. В отличие от test_ast.py здесь
проверяется то, что реально видно в схеме — атрибут `value` фигуры,
координаты точек рёбер и состав объектов страницы.
"""

import os
import re
import subprocess
import sys
import tempfile
import unittest

from fragmos import generate_from_code

_PACKAGES = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))) + os.sep + 'packages'


def xml(code, language='python', mode_id='default', **cfg):
    """XML схемы для кода (файл — во временном каталоге)."""
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, 'out.xml')
        generate_from_code(code, language, out, mode_id, cfg or None)
        with open(out, encoding='utf-8') as f:
            return f.read()


def values(code, language='python', mode_id='default', **cfg):
    """Подписи всех фигур схемы — как их увидит draw.io в `value`."""
    return re.findall(r'value="([^"]*)"', xml(code, language, mode_id, **cfg))


def points(text):
    """Все точки рёбер (mxPoint) в порядке появления."""
    return [(int(x), int(y)) for x, y in
            re.findall(r'<mxPoint x="(-?\d+)" y="(-?\d+)"', text)]


class Deterministic(unittest.TestCase):
    """Одинаковый вход → побайтно одинаковый файл."""

    CODE = '''
def f(n):
    s = 0
    for i in range(n):
        s = s + i
    return s
'''

    def test_two_runs_identical(self):
        self.assertEqual(xml(self.CODE), xml(self.CODE))

    def test_no_memory_addresses(self):
        # id объектов — сквозная нумерация, а не адрес в памяти
        ids = re.findall(r'<mxCell id="([^"]+)"', xml(self.CODE))
        self.assertEqual(ids[:4], ['0', '1', 'n1', 'n2'])

    def test_modified_is_fixed(self):
        self.assertIn('modified="1970-01-01T00:00:00"', xml(self.CODE))


class HtmlEscape(unittest.TestCase):
    """Все фигуры идут со стилем html=1: подпись — HTML, а не голый текст."""

    def test_condition_with_less_than(self):
        # `i<n` без пробелов: draw.io съедал `<n` как начало тега
        x = xml('def f(i, n):\n    if i<n:\n        i = n\n')
        self.assertIn('value="i&amp;lt;n"', x)
        self.assertNotIn('value="i<n"', x)

    def test_cpp_template_type(self):
        x = xml('void f() { std::vector<int> v = g(); }', 'cpp')
        self.assertIn('&amp;lt;int&amp;gt;', x)

    def test_ampersand_not_broken(self):
        x = xml('void f() { if (a && b) { c(); } }', 'cpp')
        self.assertIn('value="a &amp;amp;&amp;amp; b"', x)

    def test_label_shape_escaped(self):
        # текстовые подписи (LabelShape) идут тем же путём
        from fragmos.builder.shapes import LabelShape

        class _Page:
            def __init__(self):
                self.objects = []

            def add_object(self, obj):
                self.objects.append(obj)

        self.assertEqual(LabelShape(_Page(), 'a<b', 0, 0).value, 'a&lt;b')

    def test_size_measured_by_raw_text(self):
        # ширина считается по сырому тексту, а не по вставленным `&lt;`
        from fragmos.builder.config import DEFAULT_CFG
        from fragmos.builder.shapes import IfShape

        cond = 'aaaaaaaaaa<bbbbbbbbbb<cccccccccc<dddddddddd'
        x = xml(f'def f(a):\n    if {cond}:\n        a = 1\n')
        w = re.search(r'value="aaaaaaaaaa[^"]*"[^>]*>\s*<mxGeometry[^>]*width="(\d+)"', x)
        self.assertIsNotNone(w)
        self.assertEqual(int(w.group(1)), IfShape.dims(cond, DEFAULT_CFG)[0])


class ProcessNodes(unittest.TestCase):
    def test_raise_is_drawn(self):
        vals = values('''
def f(x):
    if x < 0:
        raise ValueError('neg')
    return x
''')
        self.assertIn("raise ValueError(&apos;neg&apos;)", vals)


class LoopLimitJumps(unittest.TestCase):
    """break и continue из одной (правой) ветки идут разными коридорами."""

    CODE = '''
def f(xs):
    for x in xs:
        if x == 1:
            continue
        if x == 2:
            break
    return 0
'''

    def _vertical_runs(self):
        """{x: [(y0, y1), …]} — вертикальные участки маршрутов переходов."""
        runs = {}
        for chain in re.findall(r'edge="1".*?</mxCell>', xml(self.CODE, mode_id='loopLimit'),
                                re.S):
            pts = points(chain)
            for (ax, ay), (bx, by) in zip(pts, pts[1:]):
                if ax == bx:
                    runs.setdefault(ax, []).append((min(ay, by), max(ay, by)))
        return runs

    def test_jump_corridors_do_not_overlap(self):
        for x, segs in self._vertical_runs().items():
            for i, (a0, a1) in enumerate(segs):
                for b0, b1 in segs[i + 1:]:
                    self.assertTrue(a1 <= b0 or b1 <= a0,
                                    f'вертикаль x={x}: отрезки {(a0, a1)} и {(b0, b1)} '
                                    f'наложились')

    def test_continue_inner_break_outer(self):
        # continue — во внутренней полосе коридора, break — во внешней
        xs = sorted(self._vertical_runs())
        self.assertEqual(len(set(xs[-2:])), 2)
        self.assertEqual(xs[-1] - xs[-2], 40)     # while_corridor_base // 2


class ShowBbox(unittest.TestCase):
    """Отладочный флаг show_bbox не должен менять саму схему."""

    CODE = '''
def f(xs):
    for x in xs:
        if x > 0:
            break
        else:
            continue
    return 0
'''

    def test_routes_unchanged(self):
        off = xml(self.CODE, mode_id='loopLimit')
        on = xml(self.CODE, mode_id='loopLimit', show_bbox=True)
        self.assertEqual(points(off), points(on))

    def test_only_bboxes_added(self):
        off = xml(self.CODE, mode_id='loopLimit')
        on = xml(self.CODE, mode_id='loopLimit', show_bbox=True)
        self.assertGreater(on.count('pointerEvents=0'), 0)     # рамки появились
        self.assertEqual(off.count('<mxCell'),
                         on.count('<mxCell') - on.count('pointerEvents=0'))


class SwitchCaseLabels(unittest.TestCase):
    """Метки case — подписи на линиях от «решения», а не прямоугольники."""

    CODE = '''
def f(x):
    match x:
        case 1:
            g()
        case _:
            h()
'''

    def styles(self, code=None, lang='python'):
        """{подпись: стиль} по фигурам страницы."""
        return dict(re.findall(r'value="([^"]*)" style="([^"]*)"',
                               xml(code or self.CODE, lang, 'loopLimit')))

    def test_pattern_is_a_label_not_a_process_box(self):
        style = self.styles()['1']
        self.assertTrue(style.startswith('text;'))   # LabelShape
        self.assertIn('strokeColor=none', style)     # без рамки

    def test_default_named_else(self):
        vals = values(self.CODE, mode_id='loopLimit')
        self.assertIn('иначе', vals)
        self.assertNotIn('_', vals)

    def test_default_label_in_all_languages(self):
        cases = [
            ('cpp', 'int f(int x){ switch (x) { case 1: g(); break; '
                    'default: h(); break; } return 0; }'),
            ('csharp', 'class K { void M(int x){ switch (x) { case 1: G(); break; '
                       'default: H(); break; } } }'),
        ]
        for lang, code in cases:
            with self.subTest(lang):
                self.assertIn('иначе', values(code, lang, 'loopLimit'))

    def test_empty_case_goes_straight_to_merge(self):
        code = self.CODE.replace('            g()', '            pass')
        x = xml(code, mode_id='loopLimit')
        self.assertIn('1', values(code, mode_id='loopLimit'))   # метка осталась
        # ветка без тела — ребро от ромба сразу на линию слияния
        chains = [points(c) for c in re.findall(r'edge="1".*?</mxCell>', x, re.S)]
        self.assertTrue(any(len(p) == 4 and p[0][1] == p[1][1] and p[2][1] == p[3][1]
                            for p in chains))


class RootLogger(unittest.TestCase):
    """Импорт fragmos не перехватывает корневой логгер процесса."""

    SCRIPT = '''
import logging, sys, tempfile, os
sys.path.insert(0, %r)
import fragmos
root = logging.getLogger()
print("HANDLERS", len(root.handlers))
with tempfile.TemporaryDirectory() as tmp:
    fragmos.generate_from_code("x = 1", "python", os.path.join(tmp, "o.xml"))
logging.getLogger("host").info("сообщение хост-программы")
'''

    def test_no_basic_config_and_no_info_spam(self):
        r = subprocess.run([sys.executable, '-c', self.SCRIPT % _PACKAGES],
                           capture_output=True, text=True, check=True)
        self.assertIn('HANDLERS 0', r.stdout)
        self.assertEqual(r.stderr, '')


class TestGenerateXml(unittest.TestCase):
    """Схема отдаётся строкой: файл на диске — способ сохранения, а не контракт.

    Умолчание `/tmp/fragmos_out.xml` убрано: два вызова писали в один и тот же файл
    и затирали друг друга без единой ошибки.
    """

    CODE = 'def f(x):\n    return x + 1\n'
    OTHER = 'def g(y):\n    return y * 2\n'

    def test_string_equals_saved_file(self):
        import fragmos
        xml_str = fragmos.generate_xml(self.CODE, 'python')
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'o.xml')
            self.assertEqual(fragmos.generate_from_code(self.CODE, 'python', path), path)
            with open(path, encoding='utf-8') as f:
                self.assertEqual(f.read(), xml_str)
        self.assertIn('<mxfile', xml_str)

    def test_calls_do_not_share_state(self):
        """Разный код — разные схемы, и первая не портится второй."""
        import fragmos
        a = fragmos.generate_xml(self.CODE, 'python')
        b = fragmos.generate_xml(self.OTHER, 'python')
        self.assertNotEqual(a, b)
        self.assertEqual(a, fragmos.generate_xml(self.CODE, 'python'))

    def test_files_variant(self):
        import fragmos
        xml_str = fragmos.generate_xml(None, 'python',
                                       files=[('a.py', self.CODE), ('b.py', self.OTHER)])
        self.assertIn('f(x)', xml_str)
        self.assertIn('g(y)', xml_str)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'o.xml')
            fragmos.generate_from_files([{'filename': 'a.py', 'code': self.CODE},
                                         {'filename': 'b.py', 'code': self.OTHER}],
                                        'python', path)
            with open(path, encoding='utf-8') as f:
                self.assertEqual(f.read(), xml_str)

    def test_code_and_files_are_exclusive(self):
        import fragmos
        with self.assertRaises(ValueError):
            fragmos.generate_xml(self.CODE, 'python', files=[('a.py', self.CODE)])
        with self.assertRaises(ValueError):
            fragmos.generate_xml()

    def test_out_path_has_no_default(self):
        """Общий /tmp не должен быть путём наименьшего сопротивления."""
        import inspect

        import fragmos
        for fn in (fragmos.generate_from_code, fragmos.generate_from_files):
            self.assertIs(inspect.signature(fn).parameters['out_path'].default,
                          inspect.Parameter.empty)

    def test_cfg_overrides_and_mode_reach_xml(self):
        import fragmos
        plain = fragmos.generate_xml(self.CODE, 'python', mode_id='gost_19_701_90')
        self.assertNotEqual(plain, fragmos.generate_xml(self.CODE, 'python'))


if __name__ == '__main__':
    unittest.main()
