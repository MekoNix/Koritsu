import re
from copy import deepcopy

from .base import ASTGenerator
from .query import NodeQueries

# `goto case 2;` / `goto default;` — переход к телу другого случая switch.
_GOTO_CASE_RE = re.compile(r'^goto\s+(?:case\s+(?P<pat>.+?)|(?P<default>default))\s*;?$')

Q = NodeQueries('c_sharp', {
    'if':      '(if_statement condition: (_) @cond consequence: (_) @then alternative: (_)? @else)',
    'for':     '(for_statement initializer: (_)? @init condition: (_)? @cond update: (_)? @upd body: (_) @body)',
    'foreach': '(foreach_statement type: (_)? @type left: (_) @var right: (_) @iter body: (_) @body)',
    'while':   '(while_statement condition: (_) @cond body: (_) @body)',
    'do':      '(do_statement body: (_) @body condition: (_) @cond)',
    'switch':  '(switch_statement value: (_) @cond body: (_) @body)',
    'method':  '(method_declaration name: (_) @name parameters: (_) @params body: (_)? @body)',
})

_IO_METHODS = {'write', 'writeline', 'readline', 'read', 'readalltext', 'readalllines'}

class CSharpAST(ASTGenerator):
    """C# AST generator using tree-sitter."""

    GRAMMAR = 'c_sharp'
    LANGUAGE = 'csharp'
    BLOCK_TYPES = frozenset(('block', 'declaration_list'))

    # ── helpers ──────────────────────────────────────────────────────────────

    def _extract_function_body(self, body_node) -> list:
        """Тело метода/конструктора/аксессора. Помимо обычного `block`,
        умеет `arrow_expression_clause` (expression-bodied member,
        `int M() => x * 2;`): возвращаем единственное выражение как
        return-узел, чтобы flowchart показал как обычный START → return → STOP.
        """
        if body_node is None:
            return []
        if body_node.type == 'arrow_expression_clause':
            inner = body_node.named_children[0] if body_node.named_children else None
            if inner is None:
                return []
            text = self._t(inner).rstrip(';')
            return [{'type': 'return', 'value': text}]
        # одиночный statement (редко для методов, но возможно для accessor)
        return self._visit_body(body_node)

    # ── node visitors ─────────────────────────────────────────────────────────

    def _visit(self, node) -> dict | list | None:
        t = node.type

        # ── Top-level / структурные ─────────────────────────────────────────

        # namespace и file-scoped namespace — прозрачно «разворачиваем»,
        # возвращая список их детей. Иначе классы внутри namespace
        # никогда не посещаются и AST.body остаётся пустым.
        if t in ('namespace_declaration', 'file_scoped_namespace_declaration'):
            body_node = self._field(node, 'body')
            if body_node is not None:
                return self._visit_block(body_node)
            # fallback: file-scoped без body — пройдём по named_children
            # (отбросив name) вручную
            return self._visit_block(node, skip=frozenset(('qualified_name', 'identifier')))

        # Top-level statements (C# 9+): `Console.WriteLine(...);`
        # без оборачивания в class/Main.
        if t == 'global_statement':
            inner = node.named_children[0] if node.named_children else None
            if inner is None:
                return None
            return self._visit(inner)

        if t in ('class_declaration', 'record_declaration',
                 'struct_declaration', 'interface_declaration'):
            return self._visit_class(node)

        # ── Member declarations ─────────────────────────────────────────────

        if t == 'method_declaration':
            return self._visit_method(node)
        if t in ('constructor_declaration', 'destructor_declaration'):
            return self._visit_constructor(node)
        if t == 'local_function_statement':
            # Локальная функция (вложенная в другой метод) — обычный
            # function_def: parser оставит в теле родителя заголовок-process,
            # а саму функцию вынесет отдельной страницей в конец.
            name_node = self._field(node, 'name')
            params_node = self._field(node, 'parameters')
            name = self._t(name_node) if name_node else 'local'
            params = self._t(params_node) if params_node else '()'
            return {'type': 'function_def',
                    'name': name,
                    'value': f'{name}{params}',
                    'body': self._extract_function_body(self._field(node, 'body'))}
        if t == 'property_declaration':
            return self._visit_property(node)

        # ── Statements ──────────────────────────────────────────────────────

        if t in self.BLOCK_TYPES:
            return self._visit_block(node)
        if t == 'if_statement':
            return self._visit_if(node)
        if t == 'for_statement':
            return self._visit_for(node)
        if t in ('foreach_statement', 'for_each_statement'):
            return self._visit_foreach(node)
        if t == 'while_statement':
            return self._visit_while(node)
        if t == 'do_statement':
            return self._visit_do(node)
        if t == 'switch_statement':
            return self._visit_switch(node)
        if t == 'return_statement':
            return self._visit_return(node)
        if t == 'try_statement':
            return self._visit_try(node)
        if t == 'throw_statement':
            return {'type': 'process', 'value': self._t(node).rstrip(';')}
        if t == 'yield_statement':
            return {'type': 'process', 'value': self._t(node).rstrip(';')}
        if t == 'break_statement':
            return {'type': 'break'}
        if t == 'continue_statement':
            return {'type': 'continue'}
        if t == 'goto_statement':
            return {'type': 'process', 'value': self._t(node).rstrip(';')}
        if t == 'labeled_statement':
            # `label: stmt;` — пропускаем метку, визитим сам statement
            for c in node.named_children:
                if c.type == 'identifier':
                    continue
                return self._visit(c)
            return None

        # «Прозрачные» statements с body — using/lock/checked/fixed/unsafe.
        # У using есть variable_declaration перед block (показываем как
        # assignment), у lock — identifier (не визуализируем). В остальных
        # случаях просто возвращаем содержимое тела.
        if t in ('using_statement', 'lock_statement',
                 'checked_statement', 'unchecked_statement',
                 'fixed_statement', 'unsafe_statement'):
            return self._visit_blocked_stmt(node)

        if t == 'expression_statement':
            return self._visit_expression(node)
        if t == 'local_variable_declaration':
            return self._assignment(node)
        if t == 'local_declaration_statement':
            inner = node.named_children[0] if node.named_children else None
            if inner:
                return self._assignment(inner)

        return None

    # ── visitors implementation ─────────────────────────────────────────────

    def _visit_class(self, node) -> dict:
        name_node = self._field(node, 'name')
        name = self._t(name_node) if name_node else ''
        body_node = self._field(node, 'body')
        return {
            'type': 'class_def',
            'name': name,
            'value': name,
            'body': self._visit_block(body_node) if body_node else [],
        }

    def _visit_method(self, node) -> dict:
        c = Q.caps('method', node)
        return {
            'type': 'function_def',
            'name': c.text('name'),
            'value': f"{c.text('name')}{c.text('params', '()')}",
            'body': self._extract_function_body(c.one('body')),
        }
    def _visit_constructor(self, node) -> dict:
        name_node = self._field(node, 'name')
        name = self._t(name_node) if name_node else ''
        params_node = self._field(node, 'parameters')
        params = self._t(params_node) if params_node else '()'
        body_node = self._field(node, 'body')
        return {
            'type': 'function_def',
            'name': name,
            'value': f'{name}{params}',
            'body': self._extract_function_body(body_node),
        }

    def _visit_property(self, node):
        """Свойство C# может иметь логику в одном из видов:
            int X => 42;                       — arrow-bodied get
            int X { get => x; set => x = value; }
            int X { get { return _x; } set { _x = value; } }
            int X { get; set; }                — auto-impl, тел нет
        Возвращаем список function_def-узлов (один или несколько). Для
        auto-implemented свойств возвращаем None.
        """
        name_node = self._field(node, 'name')
        name = self._t(name_node) if name_node else 'property'

        # Arrow-bodied property: `int X => 42;`
        arrow = self._field(node, 'value')
        if arrow is not None and arrow.type == 'arrow_expression_clause':
            body = self._extract_function_body(arrow)
            if not body:
                return None
            return [{
                'type': 'function_def',
                'name':  f'{name}.get',
                'value': f'{name}.get',
                'body':  body,
            }]

        # Accessor list: `int X { get { ... } set { ... } }`
        funcs: list = []
        for child in node.named_children:
            if child.type != 'accessor_list':
                continue
            for acc in child.named_children:
                if acc.type != 'accessor_declaration':
                    continue
                acc_body_node = self._field(acc, 'body')
                if acc_body_node is None:
                    continue  # auto-impl
                acc_name_node = self._field(acc, 'name')
                acc_name = self._t(acc_name_node) if acc_name_node else 'accessor'
                body = self._extract_function_body(acc_body_node)
                if not body:
                    continue
                funcs.append({
                    'type':  'function_def',
                    'name':  f'{name}.{acc_name}',
                    'value': f'{name}.{acc_name}',
                    'body':  body,
                })
        return funcs or None

    def _visit_if(self, node) -> dict:
        c = Q.caps('if', node)
        alt = c.one('else')
        if alt is not None and alt.type == 'else_clause':      # старая грамматика
            alt = alt.named_children[0] if alt.named_children else None
        if alt is None:
            else_body = []
        elif alt.type == 'if_statement':
            else_body = [self._visit_if(alt)]
        else:
            else_body = self._visit_body(alt)
        return {
            'type': 'if',
            'value': c.text('cond'),
            'body': self._visit_body(c.one('then')),
            'else_body': else_body,
        }
    def _visit_for(self, node) -> dict:
        c = Q.caps('for', node)
        parts = [self._clean(c.text(k)) for k in ('init', 'cond', 'upd') if c.one(k) is not None]
        return {'type': 'for', 'value': '; '.join(parts), 'body': self._visit_body(c.one('body'))}
    def _visit_foreach(self, node) -> dict:
        c = Q.caps('foreach', node)
        header = ' '.join(t for t in (c.text('type'), c.text('var')) if t)
        return {'type': 'for', 'value': f"{header} in {c.text('iter')}",
                'body': self._visit_body(c.one('body'))}
    def _visit_while(self, node) -> dict:
        c = Q.caps('while', node)
        return {'type': 'while', 'value': c.text('cond'), 'body': self._visit_body(c.one('body'))}
    def _visit_do(self, node) -> dict:
        """do { ... } while (cond);  — условие проверяется после тела."""
        c = Q.caps('do', node)
        return {'type': 'do_while', 'value': c.text('cond'), 'body': self._visit_body(c.one('body'))}
    def _visit_switch(self, node) -> dict:
        """C# switch → fragmos `match`-узел.

        В parser'е fragmos `match` уже умеет разворачиваться в цепочку
        if/else (default mode) или в полноценный switch-блок (GOST mode).
        Поддерживаем:
          • case-label с const-литералом
          • несколько case-label подряд (fall-through fan-in) → объединяем
            в один pattern через ' | '
          • default_switch_label
          • case_pattern_switch_label с when-clause
          • break_statement в конце секции игнорируется (это маркер конца
            case, не имеет визуального смысла в flowchart)
        """
        c = Q.caps('switch', node)
        subj, body_node = c.text('cond'), c.one('body')
        cases: list = []
        if body_node is not None:
            pending: list[str] = []      # паттерны пустых секций (fall-through)
            for sec in body_node.named_children:
                if sec.type != 'switch_section':
                    continue
                patterns: list[str] = list(pending)
                pending = []
                stmts: list = []
                for ch in sec.children:
                    if not ch.is_named:
                        # tree-sitter-c-sharp >= 0.21: `default:` — только
                        # ключевое слово, именованного label-узла нет.
                        if ch.type == 'default':
                            patterns.append('_')
                        continue
                    if ch.type in ('case_switch_label', 'case_pattern_switch_label'):
                        # старая грамматика: label-обёртка вокруг pattern (+ when)
                        patterns.append(self._case_label_text(ch))
                    elif ch.type == 'default_switch_label':
                        patterns.append('_')
                    elif ch.type.endswith('_pattern'):
                        # новая грамматика: pattern — прямой ребёнок секции
                        patterns.append(self._pattern_text(ch))
                    elif ch.type == 'when_clause':
                        if patterns:
                            patterns[-1] = f'{patterns[-1]} {self._t(ch)}'
                    elif ch.type == 'break_statement':
                        continue                     # маркер конца case
                    else:
                        stmts.extend(self._as_list(self._visit(ch)))
                if patterns and not stmts and not self._has_break(sec):
                    pending = patterns   # `case 1: case 2: …` — секция без тела
                elif patterns:
                    cases.append({'pattern': ' | '.join(patterns), 'body': stmts})
            if pending:
                cases.append({'pattern': ' | '.join(pending), 'body': []})
            self._resolve_goto_cases(cases)
        return {
            'type': 'match',
            'value': subj,
            'cases': cases,
        }

    def _resolve_goto_cases(self, cases: list) -> None:
        """`goto case N` / `goto default` — переход к телу другого случая.

        Блок «goto case N» сам по себе ничего не говорит о потоке: раньше
        схема на нём просто обрывалась. Подставляем вместо него копию тела
        цели — так поток на схеме честный. Если цель не нашлась или case-ы
        ссылаются друг на друга по кругу, блок остаётся как был.
        """
        by_pattern: dict = {}
        for c in cases:
            for pat in c['pattern'].split(' | '):
                by_pattern.setdefault(pat.strip(), c)

        def resolve(case, seen):
            body = case['body']
            if not body or body[-1].get('type') != 'process':
                return
            m = _GOTO_CASE_RE.match((body[-1].get('value') or '').strip())
            if m is None:
                return
            target = by_pattern.get('_' if m.group('default') else m.group('pat').strip())
            if target is None or id(target) in seen:
                return
            resolve(target, seen | {id(target)})
            body[-1:] = deepcopy(target['body'])

        for c in cases:
            resolve(c, {id(c)})

    @staticmethod
    def _has_break(sec) -> bool:
        return any(c.type == 'break_statement' for c in sec.named_children)

    def _pattern_text(self, pat) -> str:
        """constant_pattern → сам литерал; остальные паттерны — как есть."""
        if pat.type == 'constant_pattern' and pat.named_children:
            return self._t(pat.named_children[0])
        return self._t(pat)

    def _case_label_text(self, label) -> str:
        """Старая грамматика: case_switch_label / case_pattern_switch_label."""
        pat_text, when_text = '', ''
        for k in label.named_children:
            if k.type == 'when_clause':
                when_text = self._t(k)
            else:
                pat_text = self._pattern_text(k)
        return (pat_text + (f' {when_text}' if when_text else '')).strip()

    def _visit_blocked_stmt(self, node):
        """`using (...) { body }`, `lock (obj) { body }`, `fixed (...) { body }`,
        `checked { body }`, `unchecked { body }`, `unsafe { body }`.

        Возвращаем уплощённый список узлов: сначала пометка-присваивание
        (для using — открытие ресурса; для lock — пометка), затем тело.
        Если своей семантики не несёт (checked/unchecked/unsafe) — просто
        возвращаем содержимое body.
        """
        out: list = []
        t = node.type

        # Заголовок: для using — variable_declaration перед body; для lock —
        # identifier (lock target); для fixed — variable_declaration.
        body_node = self._field(node, 'body')
        if body_node is None:
            # Найти block среди детей вручную (lock_statement, fixed, и т.п.
            # не имеют 'body' field).
            for c in node.named_children:
                if c.type == 'block':
                    body_node = c
                    break

        if t == 'using_statement':
            for c in node.named_children:
                if c.type == 'variable_declaration':
                    out.append({'type': 'assignment',
                                'value': f'using {self._t(c)}'})
        elif t == 'lock_statement':
            for c in node.named_children:
                if c.type in ('identifier', 'member_access_expression',
                              'this_expression'):
                    out.append({'type': 'process',
                                'value': f'lock ({self._t(c)})'})
                    break
        elif t == 'fixed_statement':
            for c in node.named_children:
                if c.type == 'variable_declaration':
                    out.append({'type': 'assignment',
                                'value': f'fixed {self._t(c)}'})
                    break

        # Содержимое тела.
        if body_node is not None:
            out.extend(self._visit_body(body_node))
        return out or None

    def _visit_expression(self, node) -> dict | None:
        child = node.named_children[0] if node.named_children else None
        if child is None:
            return None
        text = self._t(child).rstrip(';')
        # Для await-выражений снимаем обёртку, чтобы внутренний invocation
        # классифицировался корректно (Console.WriteLine → io и т.д.).
        if child.type == 'await_expression' and child.named_children:
            child = child.named_children[0]
        if child.type == 'invocation_expression':
            func_node = child.child_by_field_name('function')
            func_name = self._t(func_node).split('.')[-1].lower() if func_node else ''
            if func_name in _IO_METHODS or 'console' in self._t(child).lower():
                return {'type': 'io', 'value': text}
            return {'type': 'call', 'value': text}
        if child.type == 'assignment_expression':
            return self._assignment(child)
        if child.type in ('postfix_unary_expression', 'prefix_unary_expression'):
            # `i++`, `++i`, `i--`, `!flag` как expression-statement
            return {'type': 'expression', 'value': text}
        if child.type == 'object_creation_expression':
            return {'type': 'call', 'value': text}
        return {'type': 'expression', 'value': text}
