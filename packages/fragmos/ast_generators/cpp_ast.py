from copy import deepcopy

from .base import ASTGenerator
from .query import NodeQueries

_COND = '(condition_clause initializer: (_)? @init value: (_) @cond)'   # C++17 if-init
Q = NodeQueries('cpp', {
    'if':        f'(if_statement condition: {_COND} consequence: (_) @then alternative: (else_clause (_) @else)?)',
    'for':       '(for_statement initializer: (_)? @init condition: (_)? @cond update: (_)? @upd body: (_) @body)',
    'for_range': '(for_range_loop type: (_)? @type declarator: (_) @var right: (_) @iter body: (_) @body)',
    'while':     f'(while_statement condition: {_COND} body: (_) @body)',
    'do':        '(do_statement body: (_) @body condition: (_) @cond)',
    'switch':    f'(switch_statement condition: {_COND} body: (_) @body)',
    'case':      '(case_statement value: (_)? @value)',
})

_IO_FUNCS = {'printf', 'scanf', 'cout', 'cin', 'fprintf', 'fscanf', 'puts', 'gets',
             'fwrite', 'fread', 'getline'}

# Statement-ы, после которых поток из case не проваливается в следующий.
_CLOSING_STMTS = frozenset(('return_statement', 'goto_statement',
                            'throw_statement', 'continue_statement',
                            'co_return_statement'))


def _apply_fallthrough(cases: list) -> None:
    """case без break продолжается телом следующего — дописываем копию.

    Обратный проход: цепочка case1 → case2 → case3 разворачивается за
    один заход, без рекурсии. Схема с дублем блоков честнее, чем схема,
    где после case 1 поток молча уходит на слияние.
    """
    for i in range(len(cases) - 2, -1, -1):
        if cases[i].pop('falls', False) and cases[i]['body']:
            cases[i]['body'].extend(deepcopy(cases[i + 1]['body']))
    for c in cases:
        c.pop('falls', None)

class CppAST(ASTGenerator):
    """C++ AST generator using tree-sitter."""

    GRAMMAR = 'cpp'
    LANGUAGE = 'cpp'
    BLOCK_TYPES = frozenset(('compound_statement', 'translation_unit',
                             'declaration_list', 'field_declaration_list'))

    # ── helpers ──────────────────────────────────────────────────────────────

    def _extract_function_body(self, body_node) -> list:
        """Тело функции/метода. Отдельно от _visit_body — здесь не должно
        быть None для пустого тела (хотим показать пустой START→STOP)."""
        if body_node is None:
            return []
        # function-try-block: `int M() try { ... } catch (...) { ... }`
        if body_node.type == 'function_try_block':
            try_body = []
            catch_body = []
            for c in body_node.named_children:
                if c.type == 'compound_statement' and not try_body:
                    try_body = self._visit_block(c)
                elif c.type == 'catch_clause':
                    blk = c.child_by_field_name('body')
                    if blk:
                        catch_body.extend(self._visit_block(blk))
            return [{'type': 'try', 'value': 'try',
                     'body': try_body, 'else_body': catch_body}]
        return self._visit_body(body_node)

    # ── node visitors ─────────────────────────────────────────────────────────

    def _visit(self, node) -> dict | list | None:
        t = node.type

        # ── Top-level / структурные ─────────────────────────────────────────

        # namespace foo { ... }, namespace a::b { ... }, namespace { ... }
        if t == 'namespace_definition':
            body_node = self._field(node, 'body')
            if body_node is not None:
                return self._visit_block(body_node)
            return None

        # template<typename T> class A { ... }   |   template<...> T fn() { ... }
        # Шаблонный декларатор — это «обёртка» над class/function/struct.
        # Прозрачно проходим в дочернюю сущность.
        if t == 'template_declaration':
            for c in node.named_children:
                if c.type in ('template_parameter_list',
                              'requires_clause',
                              'requires_parameter_list'):
                    continue
                return self._visit(c)
            return None

        # extern "C" { ... }
        if t == 'linkage_specification':
            body_node = self._field(node, 'body')
            if body_node is not None:
                return self._visit_block(body_node)
            return None

        if t in ('class_specifier', 'struct_specifier'):
            return self._visit_class(node)
        if t == 'union_specifier':
            return self._visit_class(node)

        # Вложенный класс объявляется через field_declaration:
        #   class Outer { class Inner { … }; };
        # Без этой ветки Inner (и все его методы) терялись целиком.
        if t == 'field_declaration':
            for c in node.named_children:
                if c.type in ('class_specifier', 'struct_specifier', 'union_specifier'):
                    return self._visit_class(c)
            return None

        # Function definition (top-level или in-class inline) и method вне
        # класса (`void A::m() {...}` — declarator = qualified_identifier).
        if t == 'function_definition':
            return self._visit_function(node)

        # Прокидываем содержимое блочных контейнеров.
        if t in self.BLOCK_TYPES:
            return self._visit_block(node)

        # ── Control flow ────────────────────────────────────────────────────

        if t == 'if_statement':
            return self._visit_if(node)
        if t == 'for_statement':
            return self._visit_for(node)
        if t == 'for_range_loop':
            return self._visit_for_range(node)
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
        if t == 'break_statement':
            return {'type': 'break'}
        if t == 'continue_statement':
            return {'type': 'continue'}
        if t == 'goto_statement':
            return {'type': 'process', 'value': self._t(node).rstrip(';')}
        if t == 'labeled_statement':
            # `label: stmt;` — пропускаем метку, визитим сам statement
            for c in node.named_children:
                if c.type == 'statement_identifier':
                    continue
                return self._visit(c)
            return None
        if t == 'co_return_statement':
            val = self._t(node).rstrip(';')
            return {'type': 'return', 'value': val.replace('co_return', '').strip()}
        if t in ('co_yield_statement',):
            return {'type': 'process', 'value': self._t(node).rstrip(';')}

        # ── Expressions / declarations ──────────────────────────────────────

        if t == 'expression_statement':
            return self._visit_expression(node)
        if t == 'declaration':
            return self._visit_declaration(node)

        # ── Игнор: enum, alias, using, preproc, attribute, concept, etc.
        # Возвращаем None — _visit_block их пропустит.
        return None

    # ── visitor implementations ─────────────────────────────────────────────

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

    def _visit_function(self, node) -> dict:
        decl_node = self._field(node, 'declarator')
        name = ''
        params = '()'
        # function_definition.declarator может быть:
        #   • function_declarator (обычный метод)
        #   • pointer_declarator → function_declarator (returns pointer)
        #   • reference_declarator → function_declarator
        # Раскручиваем до function_declarator.
        cur = decl_node
        while cur is not None and cur.type in (
                'pointer_declarator', 'reference_declarator',
                'parenthesized_declarator'):
            cur = self._field(cur, 'declarator')
        if cur is not None and cur.type == 'function_declarator':
            name_node = self._field(cur, 'declarator')
            if name_node is not None:
                name = self._t(name_node)
            params_node = self._field(cur, 'parameters')
            if params_node is not None:
                params = self._t(params_node)
        elif decl_node is not None:
            name = self._t(decl_node)

        # Constructor с initializer-list (`: x(a), y(b)`) — добавляем
        # инициализаторы как assignment-узлы перед body, чтобы они
        # отобразились в схеме.
        init_nodes = []
        for c in node.named_children:
            if c.type == 'field_initializer_list':
                for fi in c.named_children:
                    if fi.type == 'field_initializer':
                        init_nodes.append({
                            'type': 'assignment',
                            'value': self._t(fi),
                        })

        body_node = self._field(node, 'body')
        body = init_nodes + self._extract_function_body(body_node)
        return {
            'type': 'function_def',
            'name': name,
            'value': f'{name}{params}',
            'body': body,
        }

    # ── condition_clause helpers ────────────────────────────────────────────


    def _init_node(self, caps):
        """C++17 if/while/switch-init (`if (auto x = f(); x)`) → assignment перед узлом."""
        init = caps.one('init')
        return self._make_assignment(self._t(init)) if init is not None else None
    def _visit_if(self, node):
        c = Q.caps('if', node)
        alt = c.one('else')
        if alt is None:
            else_body = []
        elif alt.type == 'if_statement':
            else_body = self._as_list(self._visit_if(alt))
        else:
            else_body = self._visit_body(alt)
        if_node = {
            'type': 'if',
            'value': c.text('cond'),
            'body': self._visit_body(c.one('then')),
            'else_body': else_body,
        }
        init = self._init_node(c)
        return [init, if_node] if init else if_node
    def _visit_for(self, node):
        c = Q.caps('for', node)
        parts = [self._clean(c.text(k)) for k in ('init', 'cond', 'upd') if c.one(k) is not None]
        return {'type': 'for', 'value': '; '.join(parts), 'body': self._visit_body(c.one('body'))}
    def _visit_for_range(self, node):
        """`for (const auto& x : items)` → «x in items».

        Раньше подпись была сырой строкой кода («auto x : v»). Тип
        переменной в схеме не нужен (п.4.1.4 ГОСТ 19.701-90 — минимум
        текста), а форма «x in items» — та же, что у Python for-in, и
        стиль собирает из неё «Цикл x, x из items»."""
        c = Q.caps('for_range', node)
        var = c.text('var').replace('&', '').replace('*', '').strip()
        return {'type': 'for', 'value': f"{var} in {c.text('iter')}",
                'body': self._visit_body(c.one('body'))}
    def _visit_while(self, node):
        c = Q.caps('while', node)
        while_node = {'type': 'while', 'value': c.text('cond'),
                      'body': self._visit_body(c.one('body'))}
        init = self._init_node(c)
        return [init, while_node] if init else while_node
    def _visit_do(self, node):
        c = Q.caps('do', node)
        # condition — parenthesized_expression: снимаем одну внешнюю пару
        return {'type': 'do_while', 'value': self._unwrap_parens(c.text('cond')),
                'body': self._visit_body(c.one('body'))}
    def _visit_switch(self, node):
        """C++ switch → fragmos `match`-узел.

        В C++ грамматике (отличие от C#) сами `case_statement` лежат
        прямо в `compound_statement`-теле switch'а, а не объединены в
        switch_section. Несколько case подряд (fall-through) выглядят
        как соседние case_statement с пустыми statement-частями, ведущие
        к одному case со statements.

        Алгоритм: идём по детям compound_statement. Накапливаем
        patterns, пока встречаем «пустой» case (только `value` без
        statements и без break). Когда встречается case со statements
        (или default), собираем pattern и тело в одну запись.

        case со statements, но без break/return/throw/goto — проваливается
        в следующий: его тело дополняется копией тела следующего случая
        (обратный проход в `_apply_fallthrough`), иначе схема молча врала
        бы, показывая слияние сразу после case 1.
        """
        c = Q.caps('switch', node)
        subj = c.text('cond')
        init_node = self._init_node(c)

        body_node = c.one('body')
        cases: list = []
        if body_node is not None:
            pending: list[str] = []  # накопленные fall-through patterns
            for ch in body_node.named_children:
                if ch.type != 'case_statement':
                    continue
                # default — нет field 'value'
                value_node = Q.caps('case', ch).one('value')
                if value_node is not None:
                    pat = self._t(value_node)
                else:
                    pat = '_'

                # Statement-часть case_statement: всё, кроме самого value.
                stmts: list = []
                closed = False          # есть break/return/throw/goto — не проваливается
                for kid in ch.named_children:
                    if kid is value_node:
                        continue
                    if kid.type == 'break_statement':
                        closed = True
                        continue
                    if kid.type in _CLOSING_STMTS:
                        closed = True
                    stmts.extend(self._as_list(self._visit(kid)))

                if not stmts and not closed:
                    # Пустой case → общий вход: запоминаем pattern и
                    # ждём следующий case со statements.
                    pending.append(pat)
                else:
                    pending.append(pat)
                    cases.append({
                        'pattern': ' | '.join(pending),
                        'body': stmts,
                        'falls': not closed,
                    })
                    pending = []
            # Если в конце остались pending без тела — добавим как пустой.
            if pending:
                cases.append({
                    'pattern': ' | '.join(pending),
                    'body': [],
                    'falls': False,
                })
            _apply_fallthrough(cases)

        match_node = {
            'type': 'match',
            'value': subj,
            'cases': cases,
        }
        return [init_node, match_node] if init_node else match_node

    def _visit_expression(self, node):
        child = node.named_children[0] if node.named_children else None
        if child is None:
            return None
        text = self._t(child).rstrip(';')
        # `co_await x;` → expression_statement(co_await_expression)
        if child.type == 'co_await_expression' and child.named_children:
            child = child.named_children[0]
        if child.type == 'call_expression':
            func_node = child.child_by_field_name('function')
            func_name = self._t(func_node).split('::')[-1] if func_node else ''
            # field_expression: obj.method() / obj->method()
            if '.' in func_name or '->' in func_name:
                func_name = func_name.split('.')[-1].split('->')[-1]
            if func_name in _IO_FUNCS:
                return {'type': 'io', 'value': text}
            return {'type': 'call', 'value': text}
        if child.type == 'binary_expression' and ('<<' in text or '>>' in text):
            # cout << / cin >> — тащим как io.
            if 'cout' in text or 'cerr' in text or 'cin' in text:
                return {'type': 'io', 'value': text}
            # шифт-операции с числами — обычная execute.
            return {'type': 'expression', 'value': text}
        if child.type in ('assignment_expression',
                          'compound_assignment_expr'):
            return self._assignment(child)
        if child.type in ('update_expression',):
            # `i++;` `--i;`
            return {'type': 'expression', 'value': text}
        if child.type == 'new_expression':
            return {'type': 'call', 'value': text}
        if child.type == 'delete_expression':
            return {'type': 'process', 'value': text}
        return {'type': 'expression', 'value': text}

    # Объявление переменной: декларатор с инициализатором или без него.
    # Голый `identifier` — это `int a;` / `std::vector<int> v;`: в учебном
    # коде объявление без инициализатора обычно, и терять его нельзя.
    # `function_declarator` в этот список не входит намеренно — прототип
    # функции (`int f(int);`) в схеме не рисуем.
    _DECLARATORS = frozenset((
        'identifier',
        'init_declarator',
        'reference_declarator',
        'pointer_declarator',
        'structured_binding_declarator',
        'array_declarator',
    ))

    def _visit_declaration(self, node):
        for child in node.named_children:
            if child.type in self._DECLARATORS:
                return self._assignment(node)
        return None
