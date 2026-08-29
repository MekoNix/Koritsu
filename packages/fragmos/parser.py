"""
parser.py — Трансформирует унифицированный AST (от ast_generators) в список nodes
для Builder, применяя режим отображения (modes.yaml) и текстовый стиль
(styles.yaml).

Здесь нет ни одного regex по тексту кода: всё преобразование подписей
живёт в styles.yaml и выполняется через TextStyle.
"""

from .builder import DEFAULT_CFG
from .builder.modes import get_mode, get_style


# ═══════════════════════════════════════════════════════════════════════════
# ЕДИНАЯ ТОЧКА ВХОДА
# ═══════════════════════════════════════════════════════════════════════════

def parse_ast_to_flowchart(ast_dict: dict, mode_id: str = 'default') -> tuple[dict, list]:
    """
    Преобразует унифицированный AST в (cfg, nodes) для Builder.

    Args:
        ast_dict: {'type': 'program', 'body': [...], 'metadata': {...}}
        mode_id:  ID режима из modes.yaml ('plain' | 'default' | 'loopLimit')

    Returns:
        (cfg, nodes) — конфигурация и список блоков для Builder.

    Raises:
        ValueError: если mode_id не найден.
    """
    mode = get_mode(mode_id)
    converter = _Converter(mode)
    nodes = converter.convert_program(ast_dict)
    cfg = dict(DEFAULT_CFG)
    # Подписи выходов «решения» (Да/Нет) берём из стиля — рендерер читает cfg.
    labels = converter.style.labels
    cfg['label_yes'] = labels.get('yes', cfg['label_yes'])
    cfg['label_no'] = labels.get('no', cfg['label_no'])
    cfg['label_else'] = labels.get('else', cfg['label_else'])
    return cfg, nodes


# ═══════════════════════════════════════════════════════════════════════════
# КОНВЕРТЕР
# ═══════════════════════════════════════════════════════════════════════════

class _Converter:
    def __init__(self, mode: dict):
        self._blocks = mode.get('blocks') or {}
        self._style = get_style(mode.get('style', 'default'))
        self._deferred = []       # локальные функции — отдельными страницами
        self._in_function = False

    @property
    def style(self):
        return self._style

    def _text(self, section: str, value) -> str:
        return self._style.apply(section, value or '')

    # ── top level ─────────────────────────────────────────────────────────

    def convert_program(self, ast_dict: dict) -> list:
        """Конвертирует program-узел. Каждая function_def → START…STOP.
        Код уровня модуля (вне функций) — отдельная страница «Схема» со
        своими Начало/Конец, первой по порядку."""
        funcs, loose = [], []
        for node in ast_dict.get('body', []):
            (funcs if node.get('type') in ('function_def', 'class_def') else loose).extend(
                self._convert(node))
        # Локальные функции копятся во время обхода — их страницы идут последними.
        funcs = funcs + self._deferred
        self._deferred = []
        if not loose:
            return funcs
        st = self._style
        page = ([{'type': 'start', 'value': st.label('start_main'), 'page_name': 'Схема'}]
                + loose
                + [{'type': 'stop', 'value': st.label('stop_main')}])
        return page + funcs

    # ── dispatcher ────────────────────────────────────────────────────────

    def _convert(self, node: dict) -> list:
        t = node.get('type')
        val = node.get('value', '')
        if t in ('function_def', 'class_def'):
            build = self._function if t == 'function_def' else self._class_def
            if not self._in_function:
                return build(node)
            # Определение внутри тела функции: в схему тела попадает только
            # заголовок, сама функция — отдельной страницей в конце. Иначе
            # её START/STOP разрезали бы страницу внешней функции пополам.
            self._deferred.extend(build(node))
            return [{'type': 'process', 'value': val or node.get('name', '')}]
        if t in ('if', 'try'):
            return [self._if_node(node)]
        if t == 'for':
            return self._for(node)
        if t == 'while':
            return self._while(node)
        if t == 'do_while':
            return self._do_while(node)
        if t in ('break', 'continue'):
            return [{'type': 'execute', 'value': self._style.label(t), 'jump': t}]
        if t == 'match':
            if self._blocks.get('match', 'ifs') == 'switch':
                return [self._switch_node(node)]
            return self._match_to_ifs(node)
        if t == 'return':
            return self._return(val)
        if t in ('assignment', 'expression'):
            return [{'type': 'execute', 'value': self._text('execute', val)}]
        if t in ('call', 'process'):
            # `process` порождают генераторы для raise / throw / del / yield /
            # goto / delete / co_yield / lock / заголовка локальной функции —
            # без этой ветки все они молча исчезали из схемы.
            return [{'type': 'process', 'value': self._text('process', val)}]
        if t == 'io':
            return [{'type': 'io', 'value': self._text('io', val)}]
        return []

    def _convert_body(self, body: list) -> list:
        result = []
        for node in body:
            result.extend(self._convert(node))
        return result

    # ── function_def ──────────────────────────────────────────────────────

    def _function(self, node: dict) -> list:
        name       = node.get('name', '')
        full_value = node.get('value', name)
        body       = node.get('body', [])
        is_main    = name.lower() in ('main', '__main__')
        st         = self._style

        if is_main:
            start_label = st.label('start_main', name=name, signature=full_value)
            stop_label  = st.label('stop_main',  name=name, signature=full_value)
        else:
            start_label = st.label('start_func', name=name, signature=full_value)
            stop_label  = st.label('stop_func',  name=name, signature=full_value)

        # Имя вкладки страницы — всегда signature/имя функции, чтобы при
        # main вкладка не превращалась в безымянное «Начало».
        page_name = full_value or name or 'Схема'

        # Терминатор «Конец» у функции ровно один — в самом конце. Все
        # return внутри тела — блоки «Вернуть X» со стрелкой к нему.
        prev, self._in_function = self._in_function, True
        body_nodes = self._convert_body(body)
        self._in_function = prev

        nodes = [{'type': 'start', 'value': start_label, 'page_name': page_name}]
        nodes.extend(body_nodes)
        nodes.append({'type': 'stop', 'value': stop_label})
        return nodes

    def _return(self, val) -> list:
        """return X → блок с пометкой returns: поток уходит к «Конец».
        Фигура — из стиля (return_shape): прямоугольник «Вернуть X» или
        параллелограмм вывода с самим значением. `return` без значения —
        всегда прямоугольник с подписью return_void."""
        st = self._style
        if not (val or '').strip():
            return [{'type': 'execute', 'value': st.label('return_void'), 'returns': True}]
        shape = st.return_shape
        section = 'io' if shape == 'io' else 'execute'
        text = st.label('return', value=self._text(section, val)).strip()
        return [{'type': shape, 'value': text, 'returns': True}]

    # ── class_def ─────────────────────────────────────────────────────────

    def _class_def(self, node: dict) -> list:
        """Разворачиваем методы класса как обычные function_def, вложенные
        классы — рекурсивно: раньше брались только прямые дети-function_def,
        и `class Outer { class Inner { void M() } }` терял Inner.M целиком."""
        nodes = []
        for child in node.get('body', []):
            t = child.get('type')
            if t == 'function_def':
                nodes.extend(self._function(child))
            elif t == 'class_def':
                nodes.extend(self._class_def(child))
        return nodes

    # ── if / try ──────────────────────────────────────────────────────────

    def _if_node(self, node: dict) -> dict:
        return {
            'type': 'if',
            'value': self._text('condition', node.get('value', '')),
            'children': self._convert_body(node.get('body', [])),
            'else_children': self._convert_body(node.get('else_body', [])),
        }

    # ── for ───────────────────────────────────────────────────────────────

    def _for(self, node: dict) -> list:
        header = node.get('value', '')
        body = self._convert_body(node.get('body', []))
        start_label, end_label = self._style.for_labels(header)

        if self._blocks.get('for', 'for_default') == 'loop_limit':
            return [self._limit(start_label, end_label, body)]
        return [{'type': 'for_default', 'value': start_label, 'children': body}]

    # ── while ─────────────────────────────────────────────────────────────

    def _while(self, node: dict) -> list:
        condition = node.get('value', '')
        body = self._convert_body(node.get('body', []))

        if self._blocks.get('while', 'while') == 'loop_limit':
            start_label, end_label = self._style.while_labels(condition)
            return [self._limit(start_label, end_label, body)]
        return [{'type': 'while',
                 'value': self._text('condition', condition),
                 'children': body}]

    @staticmethod
    def _limit(start_label, end_label, body) -> dict:
        """Граница цикла (ГОСТ 2.7): верхний и нижний символы + тело между ними.
        Контейнер, а не плоский список — рендереру нужен контекст цикла
        для стрелок break/continue."""
        return {'type': 'loop_limit', 'value': start_label,
                'end_value': end_label, 'children': body}

    def _do_while(self, node: dict) -> list:
        """do … while: тело, затем ромб с условием; в loop_limit-режиме —
        граница цикла с условием в нижнем символе (п.3.2.2.6 ГОСТ)."""
        condition = node.get('value', '')
        body = self._convert_body(node.get('body', []))

        if self._blocks.get('while', 'while') == 'loop_limit':
            start_label, end_label = self._style.while_labels(condition)
            return [self._limit(end_label, start_label, body)]
        return [{'type': 'do_while',
                 'value': self._text('condition', condition),
                 'children': body}]

    # ── match → switch / вложенные IF ─────────────────────────────────────

    def _switch_node(self, node: dict) -> dict:
        """match → switch-блок для специального рендерера."""
        cases = [
            {'pattern': case['pattern'],
             'body': self._convert_body(case.get('body', []))}
            for case in node.get('cases', [])
        ]
        return {'type': 'switch', 'value': node.get('value', ''), 'cases': cases}

    def _match_to_ifs(self, node: dict) -> list:
        """match → цепочка вложенных IF."""
        subject = node.get('value', '')
        cases   = node.get('cases', [])

        def build(cases) -> list:
            """Список flowchart-узлов для хвоста cases (IF или тело default)."""
            if not cases:
                return []
            case, rest = cases[0], cases[1:]
            body    = self._convert_body(case.get('body', []))
            if case['pattern'] == '_':
                return body
            return [{
                'type': 'if',
                'value': self._text('condition', f"{subject} == {case['pattern']}"),
                'children': body,
                'else_children': build(rest),
            }]

        return build(cases)
