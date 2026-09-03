"""
query.py — извлечение полей узлов через tree-sitter Query.

Зачем: `child_by_field_name('x')` при опечатке или смене грамматики
молча возвращает None, и ветка/условие теряются без ошибки. Запрос
компилируется при импорте генератора: несуществующий тип узла или поле
→ QueryError сразу, на всех входах.

Соглашение: запрос описывает ОДИН узел (якорь) и его поля; перечисление
соседей/детей (case-секции, elif-цепочки) остаётся на Python — с
квантификаторами `(_)*` tree-sitter дробит совпадения непредсказуемо.
"""

from tree_sitter import Query, QueryCursor

from kyotsu.ts import get_language


class Caps(dict):
    """Захваты одного совпадения: имя → [Node, ...]."""

    def one(self, name):
        v = self.get(name)
        return v[0] if v else None

    def text(self, name, default: str = '') -> str:
        n = self.one(name)
        return n.text.decode('utf-8') if n is not None else default


class NodeQueries:
    """Именованные запросы одной грамматики (компилируются при создании)."""

    def __init__(self, grammar: str, patterns: dict):
        lang = get_language(grammar)
        self._q = {}
        for name, src in patterns.items():
            try:
                self._q[name] = Query(lang, src)
            except Exception as e:                   # QueryError
                raise ValueError(f"tree-sitter query {grammar}/{name}: {e}") from e

    def caps(self, name: str, node) -> Caps:
        """Захваты первого совпадения, ЯКОРЬ которого — сам `node`."""
        cur = QueryCursor(self._q[name])
        cur.set_max_start_depth(0)
        for _pid, captures in cur.matches(node):
            return Caps(captures)
        return Caps()
