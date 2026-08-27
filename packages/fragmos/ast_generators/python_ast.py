import re

from .base import ASTGenerator
from .query import NodeQueries

# Поля statement-узлов — через tree-sitter Query (см. query.py): ошибка в
# имени поля/типа проявляется при импорте, а не как потерянная ветка.
Q = NodeQueries('python', {
    'function': '(function_definition name: (_) @name parameters: (_) @params body: (_) @body)',
    'class':    '(class_definition name: (_) @name body: (_) @body)',
    'if':       '(if_statement condition: (_) @cond consequence: (_) @then)',
    'elif':     '(elif_clause condition: (_) @cond consequence: (_) @then)',
    'else':     '(else_clause body: (_) @body)',
    'for':      '(for_statement left: (_) @var right: (_) @iter body: (_) @body)',
    'while':    '(while_statement condition: (_) @cond body: (_) @body)',
    'match':    '(match_statement subject: (_) @subject body: (_) @body)',
    'case':     '(case_clause guard: (_)? @guard consequence: (_) @body)',
})

_IO_FUNCS = {'print', 'input', 'open', 'write', 'read', 'readline', 'readlines'}
_INPUT_RE = re.compile(r'\binput\s*\(')

class PythonAST(ASTGenerator):
    """Python AST generator using tree-sitter."""

    GRAMMAR = 'python'
    LANGUAGE = 'python'
    BLOCK_TYPES = frozenset(('block', 'module'))
    TRY_CLAUSES = ('except_clause', 'except_group_clause')

    # ── node visitors ─────────────────────────────────────────────────────────

    def _visit(self, node) -> dict | list | None:
        t = node.type

        # ── Definitions ─────────────────────────────────────────────────────

        if t == 'function_definition':
            return self._visit_function(node)
        if t == 'class_definition':
            return self._visit_class(node)
        if t == 'decorated_definition':
            for child in node.named_children:
                if child.type in ('function_definition', 'class_definition'):
                    return self._visit(child)
            return None

        # ── Control flow ────────────────────────────────────────────────────

        if t == 'if_statement':
            return self._visit_if(node)
        if t == 'for_statement':
            return self._visit_for(node)
        if t == 'while_statement':
            return self._visit_while(node)
        if t == 'with_statement':
            return self._visit_with(node)
        if t == 'match_statement':
            return self._visit_match(node)
        if t == 'try_statement':
            return self._visit_try(node)
        if t == 'return_statement':
            return self._visit_return(node)
        if t == 'raise_statement':
            return {'type': 'process', 'value': self._t(node)}
        if t == 'break_statement':
            return {'type': 'break'}
        if t == 'continue_statement':
            return {'type': 'continue'}
        if t == 'pass_statement':
            return None  # пустой no-op
        if t == 'delete_statement':
            return {'type': 'process', 'value': self._t(node)}
        if t in ('global_statement', 'nonlocal_statement',
                 'import_statement', 'import_from_statement',
                 'future_import_statement'):
            return None  # для flowchart нерелевантно

        # ── Expressions / assignments ───────────────────────────────────────

        if t == 'expression_statement':
            return self._visit_expression(node)
        if t in ('assignment', 'augmented_assignment'):
            return self._assignment(node, self._t(node))

        return None

    def _assignment(self, node, full_text: str):
        """assignment → io / if (тернарник) / for (comprehension) / assignment."""
        if _INPUT_RE.search(full_text):
            return {'type': 'io', 'value': full_text}
        comp = self._split_comprehension(node)
        if comp is not None:
            return comp
        return super()._assignment(node, full_text)

    _COMP_TYPES = ('list_comprehension', 'set_comprehension',
                   'dictionary_comprehension', 'generator_expression')

    def _split_comprehension(self, node):
        """
        `xs = [f(x) for x in it if c]` → xs = []; for x in it: if c: xs.append(f(x))
        Вложенные `for` в comprehension → вложенные циклы.
        """
        if node.type != 'assignment':
            return None
        left, right = self._field(node, 'left'), self._field(node, 'right')
        if right is None or right.type not in self._COMP_TYPES:
            return None
        return self._comprehension_nodes(self._t(left), right)

    def _comprehension_nodes(self, lhs, right) -> list:
        """Узлы, наполняющие `lhs` содержимым comprehension-узла `right`."""
        elem = self._field(right, 'body')
        if right.type == 'dictionary_comprehension':
            key, val = self._field(elem, 'key'), self._field(elem, 'value')
            init = f'{lhs} = {{}}'
            step = f'{lhs}[{self._t(key)}] = {self._t(val)}'
        elif right.type == 'set_comprehension':
            init = f'{lhs} = set()'
            step = f'{lhs}.add({self._t(elem)})'
        else:
            init = f'{lhs} = []'
            step = f'{lhs}.append({self._t(elem)})'

        inner = [{'type': 'assignment', 'value': step}]
        clauses = [c for c in right.named_children if c.type in ('for_in_clause', 'if_clause')]
        for clause in reversed(clauses):
            if clause.type == 'for_in_clause':
                inner = [{'type': 'for',
                          'value': f"{self._t(self._field(clause, 'left'))} in {self._t(self._field(clause, 'right'))}",
                          'body': inner}]
            else:
                cond = clause.named_children[0] if clause.named_children else None
                inner = [{'type': 'if', 'value': self._t(cond) if cond else '',
                          'body': inner, 'else_body': []}]
        return [{'type': 'assignment', 'value': init}, *inner]

    def _visit_function(self, node) -> dict:
        c = Q.caps('function', node)
        name, body_node = c.text('name'), c.one('body')
        # Docstring (первый expression_statement со строкой) для схемы
        # бесполезен — _visit_expression его отбрасывает.
        return {
            'type': 'function_def',
            'name': name,
            'value': f"{name}{c.text('params')}",
            'body': self._visit_block(body_node) if body_node else [],
        }

    def _visit_class(self, node) -> dict:
        c = Q.caps('class', node)
        body_node = c.one('body')
        return {
            'type': 'class_def',
            'name': c.text('name'),
            'value': c.text('name'),
            'body': self._visit_block(body_node) if body_node else [],
        }
    def _visit_if(self, node) -> dict:
        c = Q.caps('if', node)
        # tree-sitter-python: все elif/else — плоские дети if_statement
        alternatives = [k for k in node.named_children
                        if k.type in ('elif_clause', 'else_clause')]
        return {
            'type': 'if',
            'value': c.text('cond'),
            'body': self._visit_block(c.one('then')),
            'else_body': self._build_elif_chain(alternatives),
        }
    def _build_elif_chain(self, alternatives: list) -> list:
        if not alternatives:
            return []
        first, rest = alternatives[0], alternatives[1:]
        if first.type == 'elif_clause':
            c = Q.caps('elif', first)
            return [{'type': 'if', 'value': c.text('cond'),
                     'body': self._visit_block(c.one('then')),
                     'else_body': self._build_elif_chain(rest)}]
        return self._visit_block(Q.caps('else', first).one('body'))
    def _visit_for(self, node) -> dict | list:
        c = Q.caps('for', node)
        left, right_node = c.text('var'), c.one('iter')
        right = self._t(right_node)
        body = self._visit_block(c.one('body'))
        # `for x in [f(y) for y in ys if c]` — comprehension в итераторе
        # разворачиваем в отдельный цикл, наполняющий временный список.
        prelude = []
        if right_node.type in self._COMP_TYPES:
            tmp = f"{left.replace(',', '_').replace(' ', '')}_list"
            prelude = self._comprehension_nodes(tmp, right_node)
            right = tmp
        # for-else: хвостовой блок (без учёта break) дописываем в тело —
        # содержимое важнее, чем точная семантика.
        body.extend(self._loop_else(node))
        loop = {'type': 'for', 'value': f'{left} in {right}', 'body': body}
        return [*prelude, loop] if prelude else loop
    def _loop_else(self, node) -> list:
        for k in node.named_children:
            if k.type == 'else_clause':
                return self._visit_block(Q.caps('else', k).one('body'))
        return []

    def _visit_while(self, node) -> dict:
        c = Q.caps('while', node)
        body = self._visit_block(c.one('body'))
        body.extend(self._loop_else(node))
        return {'type': 'while', 'value': c.text('cond'), 'body': body}
    def _visit_with(self, node) -> list:
        """`with X() as y:` → пометка-assignment + тело.

        with-item обычно содержит as_pattern (с переменной) или просто
        выражение. Вне зависимости — печатаем «with <text>» как assignment,
        чтобы видно было что ресурс открыт.
        """
        items: list[str] = []
        for c in node.named_children:
            if c.type == 'with_clause':
                for it in c.named_children:
                    if it.type == 'with_item':
                        items.append(self._t(it))

        body_node = self._field(node, 'body')
        body = self._visit_block(body_node) if body_node else []

        out: list = []
        if items:
            out.append({'type': 'assignment',
                        'value': 'with ' + ', '.join(items)})
        out.extend(body)
        return out or None

    def _visit_expression(self, node) -> dict | None:
        child = node.named_children[0] if node.named_children else None
        if child is None:
            return None

        # `await x()` / `await x` — распаковываем, чтобы внутренний call
        # классифицировался как call/io.
        if child.type == 'await' and child.named_children:
            inner = child.named_children[0]
            classified = self._classify_inner(inner, full_text=self._t(child))
            if classified is not None:
                return classified

        # `yield ...` / `yield from ...` — это expression, но семантически
        # это передача значения наружу; рисуем как process.
        if child.type == 'yield':
            return {'type': 'process', 'value': self._t(child)}

        # Голая строка-литерал в начале body — это docstring. Не рисуем.
        if child.type == 'string':
            return None

        return self._classify_inner(child, full_text=self._t(child))

    def _classify_inner(self, child, *, full_text: str):
        """Классифицирует внутренний child expression_statement-а как
        call/io/assignment/expression. Используется и для распакованных
        await-expressions."""
        if child.type == 'call':
            func_node = child.child_by_field_name('function')
            func_name = self._t(func_node).split('.')[-1] if func_node else ''
            if func_name in _IO_FUNCS:
                return {'type': 'io', 'value': full_text}
            return {'type': 'call', 'value': full_text}
        if child.type in ('assignment', 'augmented_assignment'):
            return self._assignment(child, full_text)
        return {'type': 'expression', 'value': full_text}

    # ── match / case (Python 3.10+) ───────────────────────────────────────

    def _visit_match(self, node) -> dict | None:
        c = Q.caps('match', node)
        block_node = c.one('body')
        if block_node is None:
            return None
        cases = []
        for case in (k for k in block_node.named_children if k.type == 'case_clause'):
            cc = Q.caps('case', case)
            patterns = [k for k in case.named_children if k.type == 'case_pattern']
            # `case _:` и `case X | Y:` — паттерны как в коде; пустой → default
            is_default = not patterns or all(self._t(p) == '_' for p in patterns)
            text = '_' if is_default else ' | '.join(self._t(p) for p in patterns)
            if cc.one('guard') is not None:              # `case X if cond:`
                text = f"{text} {cc.text('guard')}"
            cases.append({'pattern': text, 'body': self._visit_block(cc.one('body'))})
        return {'type': 'match', 'value': c.text('subject'), 'cases': cases} if cases else None