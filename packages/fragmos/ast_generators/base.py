from abc import ABC, abstractmethod

from kyotsu import Notice
from kyotsu.ts import get_parser


class ASTGenerator(ABC):
    """
    База языковых генераторов: tree-sitter → унифицированный AST.

    Подкласс задаёт грамматику (`GRAMMAR`, `LANGUAGE`), типы «прозрачных»
    блоков (`BLOCK_TYPES`) и реализует `_visit(node)` — диспетчер по типу
    узла. Всё, что одинаково для всех языков (обход блоков, return,
    присваивание, try, тернарники) — здесь.

    Формат результата:
        {"type": "program", "body": [...], "metadata": {"language": ...}}
    Узлы body: function_def / class_def / if / for / while / do_while /
    match / try / return / break / continue / assignment / call / io /
    expression / process.
    """

    GRAMMAR = ''          # имя грамматики для ts.get_parser
    LANGUAGE = ''         # значение metadata.language
    # Узлы-контейнеры: их дети — statement-ы одного уровня.
    BLOCK_TYPES: frozenset = frozenset()
    # Тело try (первый блок) и поле тела у catch/except-клауз.
    TRY_CLAUSES: tuple = ('catch_clause',)
    FINALLY_CLAUSE = 'finally_clause'

    def __init__(self) -> None:
        # Что разобрать не удалось и потому в схему не вошло. До 2.0.0a4.2
        # такого списка не было вовсе: файл с ошибкой разбора пропускался
        # молча (`builder._merge_files`), `goto case` без цели оставался
        # обрывком, — и узнавал об этом человек, глядя на готовую схему, где
        # ветки просто нет. Записи — `kyotsu.Notice`, та же форма, что у
        # замечаний `hokoku` и службы.
        self.warnings: list[Notice] = []
        # Имя разбираемого файла: при многофайловом входе один генератор
        # проходит по нескольким, и «не разобралось» без имени бесполезно.
        self.filename: str = ''

    def _warn(self, code: str, message: str, *, line: int | None = None) -> None:
        """Замечание о том, что в схему не вошло. Разбор при этом продолжается.

        Бросать здесь нельзя: один невыразимый оператор не повод оставить
        студента без схемы вовсе — остальное рисуется, а о дырке он узнаёт
        словами, а не разглядыванием.
        """
        self.warnings.append(Notice(module="fragmos", level="warning", code=code,
                                    message=message, file=self.filename or None,
                                    line=line))

    def generate(self, code: str) -> dict:
        tree = get_parser(self.GRAMMAR).parse(bytes(code, 'utf-8'))
        root = tree.root_node
        if root.has_error:
            raise SyntaxError(f"{self.LANGUAGE} syntax error in source code")
        return {
            "type": "program",
            "body": self._visit_block(root),
            "metadata": {"language": self.LANGUAGE},
        }

    @abstractmethod
    def _visit(self, node) -> dict | list | None:
        """Один statement/declaration → узел, список узлов или None."""

    # ── helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def _t(node) -> str:
        return node.text.decode('utf-8')

    @staticmethod
    def _field(node, name):
        return node.child_by_field_name(name)

    @staticmethod
    def _as_list(v) -> list:
        if v is None:
            return []
        return v if isinstance(v, list) else [v]

    @staticmethod
    def _clean(text: str) -> str:
        return text.strip().rstrip(';').strip()

    @staticmethod
    def _unwrap_parens(text: str) -> str:
        """Снимает ровно одну внешнюю пару скобок, если она парная.

        `strip('()')` снимал скобки с обоих концов подряд и портил текст:
        `(next(i))` → `next(i`, `((a) && (b))` → `a) && (b`."""
        s = text.strip()
        if not (s.startswith('(') and s.endswith(')')):
            return s
        depth = 0
        for i, ch in enumerate(s):
            if ch == '(':
                depth += 1
            elif ch == ')':
                depth -= 1
                if depth == 0:
                    # внешняя скобка закрылась раньше конца — пара не внешняя
                    return s[1:-1].strip() if i == len(s) - 1 else s
        return s

    def _visit_block(self, node, skip: frozenset = frozenset()) -> list:
        """Все named-дети контейнера → плоский список узлов."""
        result = []
        for child in node.named_children:
            if child.type in skip:
                continue
            result.extend(self._as_list(self._visit(child)))
        return result

    def _visit_body(self, node) -> list:
        """Тело if/цикла: контейнер со скобками или одиночный statement."""
        if node is None:
            return []
        if node.type in self.BLOCK_TYPES:
            return self._visit_block(node)
        return self._as_list(self._visit(node))

    # ── общие statement-ы ────────────────────────────────────────────────

    def _make_return(self, text: str) -> dict:
        val = self._clean(text)
        if val == 'return':
            val = ''
        elif val.startswith('return '):
            val = val[7:].strip()
        return {'type': 'return', 'value': val}

    def _visit_return(self, node) -> dict:
        return self._split_ternary(node, self._make_return) or self._make_return(self._t(node))

    def _make_assignment(self, text: str) -> dict:
        return {'type': 'assignment', 'value': self._clean(text)}

    def _assignment(self, node, full_text: str = None):
        """assignment / declaration → if (тернарник) или assignment."""
        return (self._split_ternary(node, self._make_assignment)
                or self._make_assignment(full_text if full_text is not None else self._t(node)))

    def _visit_try(self, node) -> list:
        """try / catch / finally → узел try (body + else_body), затем узлы
        finally: он выполняется на всех путях, поэтому идёт после слияния
        ветвей, а не внутри одной из них."""
        body: list = []
        except_body: list = []
        finally_body: list = []
        for child in node.named_children:
            if child.type in self.BLOCK_TYPES and not body:
                body = self._visit_block(child)
            elif child.type in self.TRY_CLAUSES:
                except_body.extend(self._clause_body(child))
            elif child.type == self.FINALLY_CLAUSE:
                finally_body.extend(self._clause_body(child))
            elif child.type == 'else_clause':          # Python try/else
                body.extend(self._clause_body(child))
        return [{'type': 'try', 'value': 'try', 'body': body, 'else_body': except_body},
                *finally_body]

    def _clause_body(self, clause) -> list:
        """Тело клаузы: поле body или первый блочный ребёнок."""
        blk = self._field(clause, 'body')
        if blk is None:
            blk = next((k for k in clause.named_children if k.type in self.BLOCK_TYPES), None)
        return self._visit_block(blk) if blk is not None else []

    # ── Desugaring: выражения → блоки схемы ────────────────────────────────
    #
    # Тернарник `x = a if c else b` / `x = c ? a : b` на схеме должен быть
    # ромбом с двумя присваиваниями, а не одним блоком с текстом условия.
    # Генераторы вызывают `_split_ternary` для assignment / return.

    TERNARY_TYPE = 'conditional_expression'
    # Внутрь этих узлов не заглядываем: тернарник в аргументе вызова или
    # в лямбде — часть выражения, а не ветвление statement-а.
    TERNARY_STOP = frozenset((
        'call', 'argument_list', 'arguments', 'lambda',
        'invocation_expression', 'call_expression', 'lambda_expression',
        'parenthesized_expression', 'subscript', 'subscript_expression',
        'element_access_expression', 'list_comprehension', 'set_comprehension',
        'dictionary_comprehension', 'generator_expression',
    ))

    def _find_ternary(self, node):
        """Первый conditional_expression на верхнем уровне statement-а."""
        stack = list(node.named_children)
        while stack:
            n = stack.pop(0)
            if n.type == self.TERNARY_TYPE:
                return n
            if n.type in self.TERNARY_STOP:
                continue
            stack.extend(n.named_children)
        return None

    def _ternary_parts(self, cond):
        """(условие, значение-если-да, значение-если-нет) как текст."""
        c = cond.child_by_field_name('condition')
        a = cond.child_by_field_name('consequence')
        b = cond.child_by_field_name('alternative')
        if c is None or a is None or b is None:
            # tree-sitter-python: полей нет, дети идут как [a, c, b]
            a, c, b = cond.named_children[:3]
        return (self._t(c), self._t(a), self._t(b))

    def _split_ternary(self, stmt, make):
        """
        Если в statement-е есть тернарник — вернуть if-узел с двумя копиями
        statement-а (подставлены обе ветки), иначе None.

        make(text) → dict statement-а из его текста (нормализацию —
        rstrip(';'), снятие `return ` — делает сам вызывающий).
        """
        cond = self._find_ternary(stmt)
        if cond is None:
            return None
        src = stmt.text
        prefix = src[:cond.start_byte - stmt.start_byte].decode('utf-8')
        suffix = src[cond.end_byte - stmt.start_byte:].decode('utf-8')
        c, a, b = self._ternary_parts(cond)
        return {
            'type': 'if',
            'value': c,
            'body': [make(prefix + a + suffix)],
            'else_body': [make(prefix + b + suffix)],
        }
