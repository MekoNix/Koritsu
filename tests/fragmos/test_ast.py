"""
Юнит-тесты AST-слоя: tree-sitter → унифицированный AST (ast_generators)
и AST → узлы схемы (parser). Запуск из корня репозитория:

    python -m unittest discover -s fragmos/tests -t .
"""

import unittest

from fragmos.ast_generators import get_ast_generator
from fragmos.parser import parse_ast_to_flowchart


def ast(lang, code):
    return get_ast_generator(lang).generate(code)['body']


def func_body(lang, code, name=None):
    """Тело первой (или названной) функции/метода, где бы она ни лежала."""
    def walk(nodes):
        for n in nodes:
            if n['type'] == 'function_def' and (name is None or n['name'] == name):
                return n['body']
            if n['type'] == 'class_def':
                r = walk(n['body'])
                if r is not None:
                    return r
        return None
    return walk(ast(lang, code))


def types(nodes):
    return [n['type'] for n in nodes]


def flow(lang, code, mode='default'):
    """(тип, подпись) блоков схемы — то, что реально попадёт в XML.

    Проверять только AST мало: подпись и фигуру блок получает в parser,
    и узел из AST не обязан доехать до схемы.
    """
    _cfg, nodes = parse_ast_to_flowchart(get_ast_generator(lang).generate(code), mode)
    return [(n['type'], n['value']) for n in nodes]


class PythonAST(unittest.TestCase):
    def test_if_elif_else(self):
        body = func_body('python', '''
def f(x):
    if x > 0:
        a = 1
    elif x < 0:
        a = 2
    else:
        a = 3
''')
        self.assertEqual(types(body), ['if'])
        top = body[0]
        self.assertEqual(top['value'], 'x > 0')
        self.assertEqual(types(top['body']), ['assignment'])
        self.assertEqual(types(top['else_body']), ['if'])
        self.assertEqual(top['else_body'][0]['value'], 'x < 0')
        self.assertEqual(top['else_body'][0]['else_body'][0]['value'], 'a = 3')

    def test_loops_break_continue(self):
        body = func_body('python', '''
def f(xs):
    for x in xs:
        if x:
            continue
        break
    while True:
        pass
''')
        self.assertEqual(types(body), ['for', 'while'])
        self.assertEqual(body[0]['value'], 'x in xs')
        self.assertEqual(types(body[0]['body']), ['if', 'break'])
        self.assertEqual(types(body[0]['body'][0]['body']), ['continue'])
        self.assertEqual(body[1]['body'], [])

    def test_loop_else_after_loop(self):
        """`for … else` / `while … else`: тело else выполняется после цикла,
        а не внутри него."""
        body = func_body('python', '''
def f(xs):
    for x in xs:
        g(x)
    else:
        h()
''')
        self.assertEqual(types(body), ['for', 'call'])
        self.assertEqual(types(body[0]['body']), ['call'])
        self.assertEqual(body[1]['value'], 'h()')

        body = func_body('python', '''
def f(n):
    while n:
        n = n - 1
    else:
        h()
''')
        self.assertEqual(types(body), ['while', 'call'])
        self.assertEqual(types(body[0]['body']), ['assignment'])

    def test_return_and_ternary(self):
        body = func_body('python', '''
def f(x):
    y = 1 if x else 2
    return y
''')
        self.assertEqual(types(body), ['if', 'return'])
        self.assertEqual(body[0]['value'], 'x')
        self.assertEqual(body[0]['body'][0]['value'], 'y = 1')
        self.assertEqual(body[0]['else_body'][0]['value'], 'y = 2')
        self.assertEqual(body[1]['value'], 'y')

    def test_io_and_calls(self):
        body = func_body('python', '''
def f():
    """doc"""
    print("hi")
    name = input()
    g()
    x = 1
''')
        self.assertEqual(types(body), ['io', 'io', 'call', 'assignment'])

    def test_comprehension(self):
        body = func_body('python', '''
def f(xs):
    ys = [x * 2 for x in xs if x]
''')
        self.assertEqual(types(body), ['assignment', 'for'])
        self.assertEqual(body[0]['value'], 'ys = []')
        self.assertEqual(body[1]['body'][0]['type'], 'if')
        self.assertEqual(body[1]['body'][0]['body'][0]['value'], 'ys.append(x * 2)')

    def test_match(self):
        body = func_body('python', '''
def f(c):
    match c:
        case 1:
            a = 1
        case _:
            a = 0
''')
        self.assertEqual(types(body), ['match'])
        self.assertEqual([c['pattern'] for c in body[0]['cases']], ['1', '_'])

    def test_try(self):
        body = func_body('python', '''
def f():
    try:
        a = 1
    except ValueError:
        a = 2
    finally:
        a = 3
''')
        self.assertEqual(types(body), ['try', 'assignment'])      # finally — после try
        self.assertEqual(len(body[0]['body']), 1)
        self.assertEqual(len(body[0]['else_body']), 1)
        self.assertEqual(body[1]['value'], 'a = 3')

    def test_syntax_error(self):
        with self.assertRaises(SyntaxError):
            ast('python', 'def f(:\n  pass')


class CppAST(unittest.TestCase):
    def test_control_flow(self):
        body = func_body('cpp', '''
int f(int n) {
    int i = 0;
    do { i++; if (i == 5) break; } while (i < n);
    for (int k = 0; k < n; k++) { if (k % 2) continue; printf("%d", k); }
    while (n > 0) n--;
    return n > 0 ? 1 : 0;
}
''')
        self.assertEqual(types(body), ['assignment', 'do_while', 'for', 'while', 'if'])
        self.assertEqual(body[1]['value'], 'i < n')
        self.assertEqual(types(body[1]['body']), ['expression', 'if'])
        self.assertEqual(types(body[1]['body'][1]['body']), ['break'])
        self.assertEqual(body[2]['value'], 'int k = 0; k < n; k++')
        self.assertEqual(types(body[2]['body']), ['if', 'io'])
        self.assertEqual(types(body[2]['body'][0]['body']), ['continue'])
        self.assertEqual(body[3]['body'][0]['type'], 'expression')
        # тернарник в return → if с двумя return
        self.assertEqual(body[4]['value'], 'n > 0')
        self.assertEqual(body[4]['body'][0], {'type': 'return', 'value': '1'})

    def test_do_while_keeps_inner_parens(self):
        """`strip('()')` снимал скобки с обоих концов: `next(i)` → `next(i`."""
        for src, cond in [('do { i++; } while (next(i));', 'next(i)'),
                          ('do { i++; } while ((a) && (b));', '(a) && (b)'),
                          ('do { i++; } while (i < 3);', 'i < 3')]:
            with self.subTest(src):
                body = func_body('cpp', 'int f(int i, int a, int b) { %s return i; }' % src)
                self.assertEqual(body[0]['value'], cond)

    def test_for_range_header(self):
        """range-for подписывался сырым «auto x : v»."""
        src = 'void f() { for (const auto& x : items) { g(x); } }'
        self.assertEqual(func_body('cpp', src)[0]['value'], 'x in items')
        # …и стиль собирает из этого человеческую подпись границы цикла
        _, nodes = parse_ast_to_flowchart(get_ast_generator('cpp').generate(src),
                                          'gost_19_701_90')
        self.assertEqual(nodes[1]['value'], 'Цикл x, x из items')

    def test_switch_fallthrough(self):
        body = func_body('cpp', '''
void f(int c) {
    switch (c) {
        case 1:
        case 2: c = 0; break;
        default: c = 9;
    }
}
''')
        self.assertEqual(types(body), ['match'])
        self.assertEqual([x['pattern'] for x in body[0]['cases']], ['1 | 2', '_'])
        self.assertEqual(len(body[0]['cases'][0]['body']), 1)

    def test_switch_real_fallthrough(self):
        """case без break проваливается в следующий: тело дописывается копией,
        иначе после case 1 поток молча уходил на слияние."""
        def cases(src):
            body = func_body('cpp', 'int f(int x) { %s return 0; }' % src)
            return [(c['pattern'], [n['value'] for n in c['body']])
                    for c in body[0]['cases']]

        self.assertEqual(
            cases('switch (x) { case 1: a(); case 2: b(); break; default: c(); break; }'),
            [('1', ['a()', 'b()']), ('2', ['b()']), ('_', ['c()'])])
        # цепочка из трёх разворачивается за один проход
        self.assertEqual(
            cases('switch (x) { case 1: a(); case 2: b(); case 3: c(); break; }'),
            [('1', ['a()', 'b()', 'c()']), ('2', ['b()', 'c()']), ('3', ['c()'])])
        # return / throw закрывают case — провала нет
        self.assertEqual(
            cases('switch (x) { case 1: return 1; case 2: b(); break; }'),
            [('1', ['1']), ('2', ['b()'])])
        # `case 3: break;` — пустой случай, а не вход в default
        self.assertEqual(
            cases('switch (x) { case 3: break; default: c(); break; }'),
            [('3', []), ('_', ['c()'])])

    def test_io_stream(self):
        body = func_body('cpp', '''
int main() { int x; std::cin >> x; std::cout << x << std::endl; return 0; }
''')
        # `int x;` — объявление без инициализатора, тоже отдельный блок.
        self.assertEqual(types(body), ['assignment', 'io', 'io', 'return'])

    def test_class_methods_and_if_init(self):
        nodes = ast('cpp', '''
class A { public: void m() { if (int r = g(); r) { x = r; } } };
void A::n() {}
''')
        self.assertEqual(types(nodes), ['class_def', 'function_def'])
        m = nodes[0]['body'][0]
        self.assertEqual(m['name'], 'm')
        self.assertEqual(types(m['body']), ['assignment', 'if'])
        self.assertEqual(nodes[1]['name'], 'A::n')


class CSharpAST(unittest.TestCase):
    def test_lock_header(self):
        """Заголовок `lock (...)` не должен пропадать.

        `this` в грамматике tree-sitter — безымянный узел-ключевое слово,
        и перебор named_children его не находил: блокировка исчезала из
        схемы молча. Проверяем слой AST — именно там терялся заголовок;
        `process`-узлы parser доносит до схемы (починено в main, afb2f0a).
        """
        for target in ('this', 'obj', 'a.b', 'GetLock()', 'items[i]'):
            with self.subTest(target=target):
                body = func_body('csharp',
                                 'class C { void M() { lock (%s) { x = 1; } } }' % target)
                self.assertEqual(body[0],
                                 {'type': 'process', 'value': f'lock ({target})'})

    def test_control_flow(self):
        body = func_body('csharp', '''
class P {
    static int F(int n) {
        int i = 0;
        do { i++; } while (i < n);
        foreach (var x in xs) { if (x == 0) break; Console.WriteLine(x); }
        for (int k = 0; k < n; k++) continue;
        return i;
    }
}
''')
        self.assertEqual(types(body), ['assignment', 'do_while', 'for', 'for', 'return'])
        self.assertEqual(body[1]['value'], 'i < n')
        self.assertEqual(body[2]['value'], 'var x in xs')
        self.assertEqual(types(body[2]['body']), ['if', 'io'])
        self.assertEqual(types(body[2]['body'][0]['body']), ['break'])
        self.assertEqual(types(body[3]['body']), ['continue'])

    def test_switch(self):
        body = func_body('csharp', '''
class P { static void F(int c) {
    switch (c) {
        case 1: case 2: c = 0; break;
        case int n when n > 5: c = n; break;
        default: c = 9; break;
    }
} }
''')
        self.assertEqual(types(body), ['match'])
        pats = [x['pattern'] for x in body[0]['cases']]
        self.assertEqual(pats, ['1 | 2', 'int n when n > 5', '_'])
        self.assertTrue(all(len(x['body']) == 1 for x in body[0]['cases']))

    def test_goto_case(self):
        """`goto case N` раньше просто выбрасывался — поток на схеме обрывался."""
        def cases(src):
            body = func_body('csharp', 'class P { void M(int x) { %s } }' % src)
            return [(c['pattern'], [n['value'] for n in c['body']])
                    for c in body[0]['cases']]

        self.assertEqual(
            cases('switch (x) { case 1: A(); goto case 2; case 2: B(); break; }'),
            [('1', ['A()', 'B()']), ('2', ['B()'])])
        self.assertEqual(
            cases('switch (x) { case 1: A(); goto default; default: C(); break; }'),
            [('1', ['A()', 'C()']), ('_', ['C()'])])
        # цикл `goto case` друг на друга — блок остаётся, рекурсия не виснет
        self.assertIn('goto case 1',
                      cases('switch (x) { case 1: A(); goto case 2; '
                            'case 2: B(); goto case 1; }')[0][1])

    def test_members(self):
        nodes = ast('csharp', '''
namespace N {
    class A {
        int P { get { return 1; } }
        int E => 3;
        A() { x = 1; }
        void M() => Console.WriteLine("x");
    }
}
''')
        self.assertEqual(types(nodes), ['class_def'])
        names = [m['name'] for m in nodes[0]['body'] if m['type'] == 'function_def']
        self.assertIn('A', names)
        self.assertIn('M', names)


class ParserToFlowchart(unittest.TestCase):
    def test_module_level_code_gets_own_page(self):
        cfg, nodes = parse_ast_to_flowchart(get_ast_generator('python').generate('''
X = 1
def f():
    return X
'''), 'plain')
        self.assertEqual([n['type'] for n in nodes],
                         ['start', 'execute', 'stop', 'start', 'execute', 'stop'])
        self.assertEqual(nodes[0]['page_name'], 'Схема')
        self.assertEqual(nodes[3]['page_name'], 'f()')


    def test_function_pages_and_jumps(self):
        cfg, nodes = parse_ast_to_flowchart(get_ast_generator('python').generate('''
def f(xs):
    for x in xs:
        if x:
            break
    return 1
'''), 'plain')
        self.assertEqual(nodes[0]['type'], 'start')
        self.assertEqual(nodes[-1]['type'], 'stop')
        loop = nodes[1]
        self.assertEqual(loop['type'], 'for_default')
        jump = loop['children'][0]['children'][0]
        self.assertEqual(jump['jump'], 'break')
        self.assertEqual(jump['value'], 'break')
        self.assertTrue(nodes[2]['returns'])

    def test_gost_do_while_to_loop_limit(self):
        cfg, nodes = parse_ast_to_flowchart(get_ast_generator('cpp').generate('''
int f(int i) { do { i++; } while (i < 3); return i; }
'''), 'gost_19_701_90')
        self.assertEqual([n['type'] for n in nodes], ['start', 'loop_limit', 'io', 'stop'])
        self.assertEqual(nodes[1]['value'], 'Цикл i')
        self.assertEqual(nodes[1]['end_value'], 'Цикл i, пока i < 3')
        self.assertEqual(nodes[1]['children'][0]['value'], 'i = i + 1')
        self.assertEqual((nodes[2]['type'], nodes[2]['value']), ('io', 'i'))

    def test_nested_classes_keep_methods(self):
        """`class Outer { class Inner { void M() } }` терял Inner.M целиком."""
        cases = [
            ('csharp', 'class Outer { class Inner { void M() { int a = 1; } } }'),
            ('cpp',    'class Outer { class Inner { public: void M() { int a = 1; } }; };'),
            ('python', 'class Outer:\n    class Inner:\n        def M(self):\n            a = 1\n'),
        ]
        for lang, code in cases:
            with self.subTest(lang):
                _, nodes = parse_ast_to_flowchart(get_ast_generator(lang).generate(code), 'plain')
                self.assertEqual([n['type'] for n in nodes], ['start', 'execute', 'stop'])
                self.assertEqual(nodes[0]['page_name'], 'M()' if lang != 'python' else 'M(self)')

    def test_nested_function_becomes_own_page(self):
        """Вложенная функция: в теле родителя — заголовок, сама она —
        отдельной страницей в конце (её START/STOP раньше разрезали
        страницу родителя пополам)."""
        _, nodes = parse_ast_to_flowchart(get_ast_generator('python').generate('''
def outer(x):
    def inner(y):
        return y + 1
    return inner(x)
'''), 'plain')
        self.assertEqual([n['type'] for n in nodes],
                         ['start', 'process', 'execute', 'stop', 'start', 'execute', 'stop'])
        self.assertEqual(nodes[1]['value'], 'inner(y)')       # заголовок в теле outer
        self.assertEqual(nodes[4]['page_name'], 'inner(y)')   # своя страница

    def test_csharp_local_function_body_visible(self):
        _, nodes = parse_ast_to_flowchart(get_ast_generator('csharp').generate('''
class K { void M() { int Loc(int a) { return a + 1; } N(Loc(1)); } }
'''), 'plain')
        pages = [n['page_name'] for n in nodes if n['type'] == 'start']
        self.assertEqual(pages, ['M()', 'Loc(int a)'])
        self.assertIn('return a + 1', [n.get('value') for n in nodes])

    def test_process_nodes_reach_flowchart(self):
        """raise / del / yield / throw / goto / delete / co_yield / lock /
        заголовок локальной функции — узлы `process`; диспетчер их терял."""
        def flat(lang, code, mode='plain'):
            _, nodes = parse_ast_to_flowchart(get_ast_generator(lang).generate(code), mode)
            out = []

            def walk(ns):
                for n in ns:
                    out.append((n['type'], n.get('value')))
                    walk(n.get('children') or [])
                    walk(n.get('else_children') or [])
            walk(nodes)
            return out

        py = flat('python', '''
def f(x):
    if x < 0:
        raise ValueError('neg')
    del x
    yield 1
''')
        self.assertIn(('process', "raise ValueError('neg')"), py)
        self.assertIn(('process', 'del x'), py)
        self.assertIn(('process', 'yield 1'), py)

        cpp = flat('cpp', 'void f(int* p) { throw 1; delete p; goto end; }')
        for v in ('throw 1', 'delete p', 'goto end'):
            self.assertIn(('process', v), cpp)

        cs = flat('csharp', '''
class K { void M(object o) { lock (o) { N(); } void Loc(int a) { } throw null; } }
''')
        self.assertIn(('process', 'lock (o)'), cs)
        self.assertIn(('process', 'Loc(int a)'), cs)     # заголовок локальной функции
        self.assertIn(('process', 'throw null'), cs)

    def test_cpp_declaration_without_initializer(self):
        """`std::vector<int> v;` рисуется наравне с `int b = 5;`.

        Раньше `_visit_declaration` требовал init_declarator, и объявление
        без инициализатора пропадало из схемы целиком.
        """
        for decl in ('std::vector<int> v', 'int a', 'int c, d',
                     'int *p', 'int arr[10]', 'static int s'):
            with self.subTest(decl=decl):
                self.assertIn(('execute', decl),
                              flow('cpp', 'int main() { %s; return 0; }' % decl))

    def test_cpp_prototypes_stay_out_of_flowchart(self):
        """Прототип функции и typedef — не блоки схемы.

        `struct Foo;` / `class Bar;` сюда не берём: на main forward
        declaration и так становится блоком-заголовком «Foo» (правило
        «определение внутри тела функции → процесс»), и это отдельный
        вопрос, не про объявление переменной.
        """
        for decl in ('int f(int)', 'typedef int myint'):
            with self.subTest(decl=decl):
                self.assertEqual(
                    [t for t, _ in flow('cpp', 'int main() { %s; return 0; }' % decl)],
                    ['start', 'execute', 'stop'])   # только «Вернуть 0»

    def test_cs_using_and_fixed_headers(self):
        """Соседи lock по обработчику: их заголовки тоже в схеме."""
        self.assertIn(('execute', 'using var f = new S()'),
                      flow('csharp', 'class C { void M() '
                                     '{ using (var f = new S()) { x = 1; } } }'))

    def test_gost_loop_without_loop_variable(self):
        """Первое слово условия — не всегда переменная цикла.

        `while (next(i))` давал «Цикл next, пока next(i)» (next — вызов),
        `while (!done)` — «Цикл не» (из псевдокода «не done»). Теперь в
        таких случаях берутся шаблоны start_novar / end_novar.
        """
        cases = [
            ('int f(int i) { while (next(i)) { i++; } return i; }',
             ('Цикл, пока next(i)', 'Цикл')),
            ('int f(int done) { while (!done) { done = 1; } return done; }',
             ('Цикл, пока не done', 'Цикл')),
            ('int f(int i) { while (i < n) { i++; } return i; }',
             ('Цикл i, пока i < n', 'Цикл i')),
        ]
        for code, expected in cases:
            with self.subTest(code=code):
                _cfg, nodes = parse_ast_to_flowchart(
                    get_ast_generator('cpp').generate(code), 'gost_19_701_90')
                loop = nodes[1]
                self.assertEqual((loop['value'], loop['end_value']), expected)

    def test_cpp_do_while_condition_keeps_parens(self):
        """`while (next(i));`: strip('()') съедал скобку вызова — `next(i`."""
        body = func_body('cpp', 'int f(int i) { do { i++; } while (next(i)); return i; }')
        self.assertEqual(body[0]['value'], 'next(i)')
        body = func_body('cpp', 'int f(int i) { do { i++; } while ((a) && (b)); return i; }')
        self.assertEqual(body[0]['value'], '(a) && (b)')

    def test_labels_from_style(self):
        cfg, _ = parse_ast_to_flowchart({'type': 'program', 'body': []}, 'plain')
        self.assertEqual((cfg['label_yes'], cfg['label_no']), ('Да', 'Нет'))


if __name__ == '__main__':
    unittest.main()
