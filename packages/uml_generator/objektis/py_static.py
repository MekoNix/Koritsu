"""
py_static — диаграмма объектов из Python-кода БЕЗ его выполнения.

Трассируется «прямолинейный» сценарий: код уровня модуля, блок
`if __name__ == "__main__":` и тело `main()`, если её вызывают. Понимает:

  x = Foo(1, name="a")      — экземпляр x; слоты из __init__: self.a = <параметр|литерал>
  x.attr = <выражение>      — слот; если справа известный экземпляр — связь
  x.items.append(y)         — элемент коллекции (containment) `items[i]`
  xs = [Foo(1), Foo(2)]     — экземпляры xs[0], xs[1]
  x.method(args)            — простые методы: внутри `self.a = p`, `self.a.append(p)`
  m = Manager(Engine(5))    — вложенный вызов → автоимя engine1

Циклы, условия (кроме `__main__`) и всё, что не перечислено, пропускаются
с заметкой в ObjectGraph.notes.
"""
from ._trace import ClassDef, Method, Obj, TraceState
from .model import ObjectGraph


class _Tracer(TraceState):
    def __init__(self, src: bytes):
        super().__init__(src)
        self.functions: dict[str, object] = {}

    # ── сбор классов ──
    def collect(self, root):
        for node in root.named_children:
            if node.type == "class_definition":
                self._collect_class(node)
            elif node.type == "function_definition":
                self.functions[self.text(node.child_by_field_name("name"))] = \
                    node.child_by_field_name("body")

    def _collect_class(self, node):
        name = self.text(node.child_by_field_name("name"))
        sup = node.child_by_field_name("superclasses")
        bases = [self.text(a) for a in sup.named_children if a.type == "identifier"] if sup else []
        cls = ClassDef(name, bases)
        body = node.child_by_field_name("body")
        for st in (body.named_children if body is not None else []):
            if st.type == "expression_statement" and st.named_children \
                    and st.named_children[0].type == "assignment":
                a = st.named_children[0]
                left, right = a.child_by_field_name("left"), a.child_by_field_name("right")
                if left is not None and left.type == "identifier" and right is not None:
                    cls.attrs[self.text(left)] = self.text(right)
            elif st.type == "function_definition":
                params, defaults = [], {}
                for p in st.child_by_field_name("parameters").named_children:
                    if p.type == "identifier":
                        params.append(self.text(p))
                    elif p.type in ("default_parameter", "typed_default_parameter"):
                        pn = self.text(p.child_by_field_name("name"))
                        params.append(pn)
                        defaults[pn] = self.text(p.child_by_field_name("value"))
                    elif p.type == "typed_parameter":
                        params.append(self.text(p.named_children[0]))
                if params and params[0] in ("self", "cls"):
                    params = params[1:]
                cls.methods[self.text(st.child_by_field_name("name"))] = \
                    Method(params, defaults, st.child_by_field_name("body"), st)
        self.classes[name] = cls

    # ── значения ──
    def value(self, node, env: dict[str, str], self_obj: Obj | None = None) -> str:
        t = node.type
        if t == "identifier":
            name = self.text(node)
            if name == "self" and self_obj is not None:
                return self_obj.name
            return env.get(name, name)
        if t == "call":
            fn = node.child_by_field_name("function")
            if fn is not None and fn.type == "identifier" and self.text(fn) in self.classes:
                cls = self.text(fn)
                return self.construct(self.auto_name(cls), cls,
                                      node.child_by_field_name("arguments"), env).name
            return self.text(node)
        if t == "list":
            items = [self.value(c, env) for c in node.named_children]
            return "[" + ", ".join(self.fmt(i) for i in items) + "]"
        return self.text(node)

    def bind(self, m: Method, arglist, env: dict[str, str]) -> dict[str, str]:
        bound = dict(m.defaults)
        pos = 0
        for a in (arglist.named_children if arglist is not None else []):
            if a.type == "keyword_argument":
                bound[self.text(a.child_by_field_name("name"))] = \
                    self.value(a.child_by_field_name("value"), env)
            elif a.type in ("list_splat", "dictionary_splat"):
                self.note("objektis/python: *args/**kwargs при вызове не раскрываются")
            else:
                if pos < len(m.params):
                    bound[m.params[pos]] = self.value(a, env)
                pos += 1
        return bound

    # ── вызовы ──
    def construct(self, name: str, cls: str, arglist, env) -> Obj:
        obj = self.new_obj(name, cls)
        init = self.find_method(cls, "__init__")
        if init is not None:
            self.run_method(obj, init, self.bind(init, arglist, env))
        return obj

    def run_method(self, obj: Obj, m: Method, local: dict[str, str]):
        env = dict(local)
        for st in (m.body.named_children if m.body is not None else []):
            if st.type != "expression_statement" or not st.named_children:
                if st.type not in ("pass_statement", "comment", "return_statement"):
                    self.note(f"objektis/python: в методах трассируются только присваивания "
                              f"и append (пропущено: {st.type})")
                continue
            e = st.named_children[0]
            if e.type == "assignment":
                left, right = e.child_by_field_name("left"), e.child_by_field_name("right")
                if left is None or right is None:
                    continue
                if left.type == "attribute":
                    owner = self.obj_of(left.child_by_field_name("object"), env, obj)
                    if owner is not None:
                        self.set_slot(owner, self.text(left.child_by_field_name("attribute")),
                                      self.value(right, env, obj))
                elif left.type == "identifier":
                    env[self.text(left)] = self.value(right, env)
            elif e.type == "call":
                self.call(e, env, self_obj=obj)

    def obj_of(self, node, env, self_obj: Obj | None) -> Obj | None:
        if node is None or node.type != "identifier":
            return None
        name = self.text(node)
        if name == "self" and self_obj is not None:
            return self_obj
        return self.resolve(env.get(name, name))

    def call(self, node, env: dict[str, str], self_obj: Obj | None = None):
        fn = node.child_by_field_name("function")
        args = node.child_by_field_name("arguments")
        if fn is None:
            return
        if fn.type == "identifier":
            name = self.text(fn)
            if name in self.classes:
                self.construct(self.auto_name(name), name, args, env)
            elif name in self.functions and self_obj is None:
                self.run_block(self.functions[name])
            return
        if fn.type != "attribute":
            return
        target = fn.child_by_field_name("object")
        mname = self.text(fn.child_by_field_name("attribute"))
        if mname in ("append", "add") and target.type == "attribute":       # x.items.append(y)
            owner = self.obj_of(target.child_by_field_name("object"), env, self_obj)
            if owner is not None and args is not None and args.named_children:
                self.append(owner, self.text(target.child_by_field_name("attribute")),
                            self.value(args.named_children[0], env))
            return
        owner = self.obj_of(target, env, self_obj)
        if owner is None:
            return
        m = self.find_method(owner.type, mname)
        if m is None:
            self.note(f"objektis/python: метод {owner.type}.{mname} не найден")
            return
        self.run_method(owner, m, self.bind(m, args, env))

    # ── верхний уровень ──
    def run_block(self, block):
        for st in (block.named_children if block is not None else []):
            self.statement(st)

    def statement(self, st):
        t = st.type
        if t == "expression_statement" and st.named_children:
            e = st.named_children[0]
            if e.type == "assignment":
                self.assign(e)
            elif e.type == "call":
                self.call(e, {})
            elif e.type == "augmented_assignment":
                self.note("objektis/python: `+=` не трассируется")
        elif t == "if_statement":
            cond = st.child_by_field_name("condition")
            if cond is not None and "__name__" in self.text(cond):
                self.run_block(st.child_by_field_name("consequence"))
            else:
                self.note("objektis/python: условия не трассируются (ветки не выбираются)")
        elif t in ("for_statement", "while_statement"):
            self.note("objektis/python: циклы не трассируются")
        elif t in ("class_definition", "function_definition", "import_statement",
                   "import_from_statement", "comment", "pass_statement"):
            pass
        else:
            self.note(f"objektis/python: пропущено: {t}")

    def _ctor_of(self, node):
        if node.type == "call" and node.child_by_field_name("function").type == "identifier" \
                and self.text(node.child_by_field_name("function")) in self.classes:
            return self.text(node.child_by_field_name("function")), node.child_by_field_name("arguments")
        return None

    def assign(self, e):
        left, right = e.child_by_field_name("left"), e.child_by_field_name("right")
        if left is None or right is None:
            return
        if left.type == "identifier":
            name = self.text(left)
            ctor = self._ctor_of(right)
            if ctor:
                self.construct(name, ctor[0], ctor[1], {})
            elif right.type in ("list", "tuple"):
                for i, item in enumerate(right.named_children):
                    c = self._ctor_of(item)
                    if c:
                        self.construct(f"{name}[{i}]", c[0], c[1], {})
            elif right.type == "identifier":
                self.alias(name, self.text(right))
        elif left.type == "attribute":
            owner = self.obj_of(left.child_by_field_name("object"), {}, None)
            if owner is not None:
                self.set_slot(owner, self.text(left.child_by_field_name("attribute")),
                              self.value(right, {}))
        elif left.type in ("pattern_list", "tuple_pattern"):
            self.note("objektis/python: распаковка кортежей не трассируется")


def extract(source: str, *, files=None) -> ObjectGraph:
    if not source or not source.strip():
        return ObjectGraph(notes=["objektis/python: пустой исходник"])
    from .._ts import get_parser
    src = source.encode("utf-8")
    root = get_parser("python").parse(src).root_node
    tr = _Tracer(src)
    tr.collect(root)
    if not tr.classes:
        return ObjectGraph(notes=["objektis/python: в коде нет классов"])
    tr.run_block(root)
    return tr.graph("objektis/python: экземпляры пользовательских классов не найдены")
