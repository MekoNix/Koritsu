"""
text_style.py — Движок текстовых стилей из styles.yaml.

TextStyle применяет упорядоченные правила (regex / literal) к тексту
блока. Семантика описана в шапке styles.yaml.
"""

import re


class _Rule:
    __slots__ = ('rx', 'find', 'replace', 'all', 'start', 'end', 'translate')

    def __init__(self, raw: dict, section: str):
        self.find = raw.get('find')
        self.rx = re.compile(raw['match'], re.DOTALL) if 'match' in raw else None
        if self.rx is None and self.find is None:
            raise ValueError(f"styles.yaml [{section}]: правило без match/find: {raw}")
        self.replace = raw.get('replace', '')
        self.all = bool(raw.get('all', False)) or self.find is not None
        self.start = raw.get('start')
        self.end = raw.get('end')
        self.translate = bool(raw.get('translate', False))

    def apply(self, text: str):
        """Возвращает (новый текст, сработало ли правило)."""
        if self.find is not None:
            return text.replace(self.find, self.replace), self.find in text
        if self.all:
            new, n = self.rx.subn(self.replace, text)
            return new, n > 0
        m = self.rx.search(text)
        if not m:
            return text, False
        return m.expand(self.replace), True

    def expand_pair(self, text: str):
        """Для секции for: (start, end) или None, если не совпало."""
        m = self.rx.search(text)
        if not m:
            return None
        return m.expand(self.start or ''), m.expand(self.end or '')


class TextStyle:
    """Скомпилированный стиль: секции → списки правил."""

    _RULE_SECTIONS = ('io', 'execute', 'process', 'condition', 'for')

    def __init__(self, name: str, raw: dict):
        self.name = name
        self.labels = dict(raw.get('labels') or {})
        self.while_tpl = dict(raw.get('while') or {})
        # Фигура блока `return X`: execute (прямоугольник) | io (параллелограмм)
        self.return_shape = raw.get('return_shape', 'execute')
        self._rules = {}
        for sec in self._RULE_SECTIONS:
            val = raw.get(sec)
            if isinstance(val, str):          # ссылка на другую секцию
                val = raw.get(val) or []
            self._rules[sec] = [_Rule(r, sec) for r in (val or [])]

    # ── применение ────────────────────────────────────────────────────

    def apply(self, section: str, text: str) -> str:
        """Прогоняет text через правила секции."""
        text = str(text)
        for rule in self._rules.get(section, ()):
            text, hit = rule.apply(text)
            if hit and not rule.all:
                break
        return text

    def label(self, key: str, *, name: str = '', signature: str = '', value: str = '') -> str:
        default = {'return': '{value}', 'return_void': 'return',
                   'break': 'break', 'continue': 'continue'}.get(key, '{signature}')
        tpl = self.labels.get(key, default)
        return tpl.format(name=name, signature=signature or name, value=value)

    def for_labels(self, header: str) -> tuple:
        """(start, end) для заголовка for."""
        for rule in self._rules['for']:
            pair = rule.expand_pair(header)
            if pair is None:
                continue
            start, end = pair
            if rule.translate:
                start = self.apply('condition', start)
                end = self.apply('condition', end)
            return start, end
        return header, header

    # Переменная цикла: идентификатор в начале условия. Группа 2 ловит
    # следующую за ним `(` — тогда это вызов функции (`next(i)`), а не
    # переменная, и подпись «Цикл next» была бы враньём.
    _LOOP_VAR = re.compile(r'\s*([A-Za-z_]\w*)\s*(\()?')

    def while_labels(self, condition: str) -> tuple:
        """(start, end) для while в режиме loop_limit.

        Переменную цикла ищем в ИСХОДНОМ условии, до перевода в
        псевдокод: после перевода первым словом оказывается, например,
        «не» (из `!flag`). Если переменной цикла нет — берём шаблоны
        start_novar / end_novar (по умолчанию — обычные, без {var}).
        """
        cond = self.apply('condition', condition)
        m = self._LOOP_VAR.match(condition or '')
        var = m.group(1) if m and not m.group(2) else ''
        start_tpl = self.while_tpl.get('start', '{cond}')
        end_tpl = self.while_tpl.get('end', '{cond}')
        if not var:
            start_tpl = self.while_tpl.get('start_novar', start_tpl)
            end_tpl = self.while_tpl.get('end_novar', end_tpl)
        return (start_tpl.format(var=var, cond=cond),
                end_tpl.format(var=var, cond=cond))


def build_styles(raw_styles: dict) -> dict:
    """Разворачивает `extends` и компилирует все стили из YAML."""
    resolved: dict = {}

    def resolve(name, chain=()):
        if name in resolved:
            return resolved[name]
        if name in chain:
            raise ValueError(f"styles.yaml: циклический extends: {' → '.join(chain + (name,))}")
        raw = raw_styles.get(name)
        if raw is None:
            raise ValueError(f"styles.yaml: неизвестный стиль {name!r}")
        merged = {}
        parent = raw.get('extends')
        if parent:
            merged.update(resolve(parent, chain + (name,)))
        merged.update({k: v for k, v in raw.items() if k not in ('extends', 'description')})
        resolved[name] = merged
        return merged

    return {name: TextStyle(name, resolve(name)) for name in raw_styles}
