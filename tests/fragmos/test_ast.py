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

    def test_io_stream(self):
        body = func_body('cpp', '''
int main() { int x; std::cin >> x; std::cout << x << std::endl; return 0; }
''')
        self.assertEqual(types(body), ['io', 'io', 'return'])

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

    def test_labels_from_style(self):
        cfg, _ = parse_ast_to_flowchart({'type': 'program', 'body': []}, 'plain')
        self.assertEqual((cfg['label_yes'], cfg['label_no']), ('Да', 'Нет'))


if __name__ == '__main__':
    unittest.main()
