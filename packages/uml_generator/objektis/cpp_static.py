"""
cpp_static — диаграмма объектов из C++-кода БЕЗ компиляции и выполнения.

Трассируется тело `main()` по tree-sitter:

  Foo x(1, "a");  Foo x{1};  auto x = Foo(1);  Foo* p = new Foo(1);   — экземпляры;
      слоты из полей с умолчаниями (`int z = 0;`), init-list конструктора
      (`: x(x), y(y)`) и его тела (`this->a = p;`, `a = p;`)
  x.a = v;  p->a = v;  x.a = &y;                                      — слот / связь
  x.items.push_back(y);  v.push_back(y)                               — элемент коллекции
  x.method(args); p->method(args)   — простые методы: `a = p;`, `this->a = p;`,
      `items.push_back(p);`

Циклы, условия и прочее — пропускаются с заметкой.
"""
from ._trace import ClassDef, Method, Obj, TraceState
from .model import ObjectGraph

_LANG = "objektis/cpp"
_PUSH = {"push_back", "push", "push_front", "emplace_back", "emplace", "insert", "append"}
_WRAP = {"pointer_declarator", "reference_declarator", "init_declarator",
         "parenthesized_declarator", "array_declarator"}


def _first(node, *types):
    for c in node.named_children:
        if c.type in types:
            return c
    return None


def _inner_name(decl):
    node = decl
    for _ in range(10):
        if node is None:
            return None
        if node.type in ("identifier", "field_identifier"):
            return node
        node = node.child_by_field_name("declarator") or _first(node, *_WRAP, "identifier", "field_identifier")
    return None


class _Tracer(TraceState):
    def __init__(self, src: bytes):
        super().__init__(src)
        self.main = None

    # ── классы ──
    def collect(self, node):
        if node.type in ("class_specifier", "struct_specifier"):
            if _first(node, "field_declaration_list") is not None:
                self._collect_class(node)
            return
        if node.type == "function_definition":
            fd = node.child_by_field_name("declarator")
            nm = _inner_name(fd)
            if nm is not None and self.text(nm) == "main":
                self.main = node.child_by_field_name("body")
            else:
                self._out_of_line(node)
            return
        for c in node.named_children:
            self.collect(c)

    def _out_of_line(self, node):
        """`void Foo::add(Task t) { … }` — метод, определённый вне класса."""
        fd = node.child_by_field_name("declarator")
        func = fd
        while func is not None and func.type != "function_declarator":
            func = func.child_by_field_name("declarator") or _first(func, *_WRAP, "function_declarator")
        if func is None:
            return
        dn = func.child_by_field_name("declarator")
        if dn is None or dn.type != "qualified_identifier":
            return
        parts = self.text(dn).split("::")
        if len(parts) < 2 or parts[-2] not in self.classes:
            return
        cls, mname = parts[-2], parts[-1]
        self.classes[cls].methods[mname] = Method(
            *self._params(func.child_by_field_name("parameters")),
            node.child_by_field_name("body"), node)

    def _params(self, plist):
        params, defaults = [], {}
        for p in (plist.named_children if plist is not None else []):
            if p.type not in ("parameter_declaration", "optional_parameter_declaration"):
                continue
            nm = _inner_name(p.child_by_field_name("declarator"))
            if nm is None:
                continue
            params.append(self.text(nm))
            dv = p.child_by_field_name("default_value")
            if dv is not None:
                defaults[self.text(nm)] = self.text(dv)
        return params, defaults

    def _collect_class(self, node):
        name = self.text(node.child_by_field_name("name") or _first(node, "type_identifier"))
        bases = []
        bc = _first(node, "base_class_clause")
        if bc is not None:
            bases = [self.text(b).split("<")[0].split("::")[-1] for b in bc.named_children
                     if b.type in ("type_identifier", "qualified_identifier", "template_type")]
        cls = ClassDef(name, bases, ctor=name)
        body = _first(node, "field_declaration_list")
        for m in body.named_children:
            if m.type == "field_declaration":
                tn = m.child_by_field_name("type")
                if any(c.type == "storage_class_specifier" and self.text(c) == "static" for c in m.children):
                    continue
                for d in m.children_by_field_name("declarator"):
                    nm = _inner_name(d)
                    if nm is None or _first(d, "function_declarator") or d.type == "function_declarator":
                        continue
                    dv = m.child_by_field_name("default_value")
                    ts = self.text(tn) if tn is not None else ""
                    if dv is not None:
                        cls.attrs[self.text(nm)] = self.text(dv)
                    elif "vector" in ts or "list" in ts or "set" in ts or "map" in ts or "array" in ts:
                        cls.attrs[self.text(nm)] = "[]"
                    elif d.type == "pointer_declarator":
                        cls.attrs[self.text(nm)] = "nullptr"
                    elif ts in ("int", "long", "double", "float", "short", "unsigned", "size_t"):
                        cls.attrs[self.text(nm)] = "0"
                    elif ts == "bool":
                        cls.attrs[self.text(nm)] = "false"
                    elif "string" in ts:
                        cls.attrs[self.text(nm)] = '""'
                    else:
                        cls.attrs[self.text(nm)] = "?"
                        cls.attr_types[self.text(nm)] = ts.split("::")[-1].split("<")[0]
            elif m.type in ("function_definition", "declaration"):
                fd = m.child_by_field_name("declarator")
                func = fd
                while func is not None and func.type != "function_declarator":
                    func = func.child_by_field_name("declarator") or _first(func, *_WRAP, "function_declarator")
                if func is None:
                    continue
                nm = _inner_name(func.child_by_field_name("declarator"))
                if nm is None:
                    continue
                mname = self.text(nm)
                body_node = m.child_by_field_name("body")
                if body_node is None:
                    continue                    # только объявление; определение — вне класса
                params, defaults = self._params(func.child_by_field_name("parameters"))
                cls.methods[mname] = Method(params, defaults, body_node, m)
            elif m.type in ("class_specifier", "struct_specifier"):
                if _first(m, "field_declaration_list") is not None:
                    self._collect_class(m)
        self.classes[name] = cls

    # ── значения ──
    def value(self, node, env: dict[str, str], self_obj: Obj | None = None) -> str:
        t = node.type
        if t == "identifier":
            n = self.text(node)
            if n in env:
                return env[n]
            if self_obj is not None and n in self_obj.slots:
                return self_obj.slots[n]
            return n
        if t == "this" and self_obj is not None:
            return self_obj.name
        if t == "pointer_expression":                     # &x, *p
            return self.value(node.child_by_field_name("argument") or node.named_children[-1], env, self_obj)
        if t == "field_expression":
            owner = self.obj_of(node.child_by_field_name("argument"), env, self_obj)
            attr = self.text(node.child_by_field_name("field"))
            if owner is not None and attr in owner.slots:
                return owner.slots[attr]
            return self.text(node)
        if t in ("call_expression", "new_expression", "compound_literal_expression"):
            tn = node.child_by_field_name("type") if t != "call_expression" else node.child_by_field_name("function")
            cls = self.text(tn).split("<")[0].split("::")[-1] if tn is not None else ""
            args = node.child_by_field_name("arguments") or _first(node, "argument_list", "initializer_list")
            if cls in self.classes:
                return self.construct(self.auto_name(cls), cls, args, env, self_obj).name
            return self.text(node)
        if t == "initializer_list":
            items = [self.value(c, env, self_obj) for c in node.named_children]
            return "[" + ", ".join(self.fmt(i) for i in items) + "]"
        return self.text(node)

    def bind(self, m: Method, arglist, env, self_obj) -> dict[str, str]:
        bound = dict(m.defaults)
        for i, a in enumerate(arglist.named_children if arglist is not None else []):
            if i < len(m.params):
                bound[m.params[i]] = self.value(a, env, self_obj)
        return bound

    # ── вызовы ──
    def construct(self, name, cls, args, env, self_obj=None) -> Obj:
        obj = self.new_obj(name, cls)
        ctor = self.classes[cls].methods.get(cls) if cls in self.classes else None
        if ctor is not None:
            self.run_ctor(obj, cls, ctor, args, env, self_obj)
        elif args is not None and args.named_children and cls in self.classes:
            # агрегатная инициализация struct {a, b} — по порядку полей
            for k, a in zip(list(self.classes[cls].attrs), args.named_children):
                self.set_slot(obj, k, self.value(a, env, self_obj))
        return obj

    def run_ctor(self, obj: Obj, cls: str, ctor: Method, args, env, self_obj):
        local = self.bind(ctor, args, env, self_obj)
        il = _first(ctor.node, "field_initializer_list")
        for fi in (il.named_children if il is not None else []):
            if fi.type != "field_initializer":
                continue
            fname = self.text(fi.named_children[0]).split("<")[0]
            vals = _first(fi, "argument_list", "initializer_list")
            if fname in self.classes:                           # : Base(args)
                bctor = self.classes[fname].methods.get(fname)
                if bctor is not None:
                    self.run_ctor(obj, fname, bctor, vals, local, obj)
                continue
            if vals is not None and vals.named_children:
                self.set_slot(obj, fname, self.value(vals.named_children[0], local, obj))
        self.run_method(obj, ctor, local)

    def run_method(self, obj: Obj, m: Method, local: dict[str, str]):
        env = dict(local)
        for st in (m.body.named_children if m.body is not None else []):
            self.statement(st, env, obj, in_method=True)

    def obj_of(self, node, env, self_obj: Obj | None) -> Obj | None:
        if node is None:
            return None
        if node.type == "this":
            return self_obj
        if node.type == "pointer_expression":
            return self.obj_of(node.child_by_field_name("argument") or node.named_children[-1], env, self_obj)
        if node.type == "identifier":
            n = self.text(node)
            if n in env:
                return self.resolve(env[n])
            if self_obj is not None and n in self_obj.slots and self.is_obj(self_obj.slots[n]):
                return self.resolve(self_obj.slots[n])
            return self.resolve(n)
        if node.type == "field_expression":
            v = self.value(node, env, self_obj)
            return self.resolve(v) if self.is_obj(v) else None
        return None

    def call(self, node, env, self_obj, in_method):
        fn = node.child_by_field_name("function")
        args = node.child_by_field_name("arguments")
        if fn is None:
            return
        if fn.type == "identifier":
            n = self.text(fn)
            if n in self.classes:
                self.construct(self.auto_name(n), n, args, env, self_obj)
            return
        if fn.type != "field_expression":
            return
        base = fn.child_by_field_name("argument")
        mname = self.text(fn.child_by_field_name("field"))
        owner = self.obj_of(base, env, self_obj)
        if owner is not None:
            m = self.find_method(owner.type, mname)
            if m is not None:
                self.run_method(owner, m, self.bind(m, args, env, self_obj))
                return
        if mname in _PUSH:
            arg_nodes = args.named_children if args is not None else []
            if base.type == "field_expression":
                owner = self.obj_of(base.child_by_field_name("argument"), env, self_obj)
                attr = self.text(base.child_by_field_name("field"))
            elif base.type == "identifier" and self_obj is not None and self.text(base) in self_obj.slots \
                    and self.text(base) not in env:
                owner, attr = self_obj, self.text(base)
            else:
                if base.type == "identifier":
                    self.note(f"{_LANG}: {self.text(base)}.{mname}(…) — локальная коллекция не привязана к объекту")
                return
            if owner is not None and arg_nodes:
                self.append(owner, attr, self.value(arg_nodes[-1], env, self_obj))
            return
        if owner is not None:
            self.note(f"{_LANG}: метод {owner.type}.{mname} не найден")

    # ── операторы ──
    def statement(self, st, env, self_obj: Obj | None, in_method=False):
        t = st.type
        if t == "declaration":
            tn = st.child_by_field_name("type")
            decl_type = self.text(tn).split("<")[0].split("::")[-1] if tn is not None else ""
            for d in st.children_by_field_name("declarator"):
                self.declare(d, decl_type, env, self_obj, in_method)
        elif t == "expression_statement" and st.named_children:
            e = st.named_children[0]
            if e.type == "assignment_expression":
                self.assign(e, env, self_obj, in_method)
            elif e.type == "call_expression":
                self.call(e, env, self_obj, in_method)
        elif t in ("for_statement", "for_range_loop", "while_statement", "do_statement"):
            self.note(f"{_LANG}: циклы не трассируются")
        elif t in ("if_statement", "switch_statement"):
            self.note(f"{_LANG}: условия не трассируются (ветки не выбираются)")
        elif t in ("return_statement", "comment", "compound_statement", "using_declaration"):
            pass
        else:
            self.note(f"{_LANG}: пропущено: {t}")

    def declare(self, d, decl_type, env, self_obj, in_method):
        nm = _inner_name(d)
        if nm is None:
            return
        name = self.text(nm)
        val = None
        node = d
        while node is not None and node.type != "init_declarator":
            node = node.child_by_field_name("declarator") or _first(node, *_WRAP)
        if node is not None:
            val = node.child_by_field_name("value") or _first(node, "argument_list", "initializer_list")
        if decl_type in self.classes and not in_method:
            if val is None or val.type in ("argument_list", "initializer_list"):
                self.construct(name, decl_type, val, env, self_obj)          # Foo x(…); Foo x{…}; Foo x;
                return
            if val.type in ("new_expression", "call_expression", "compound_literal_expression"):
                self.construct(name, decl_type, val.child_by_field_name("arguments")
                               or _first(val, "argument_list", "initializer_list"), env, self_obj)
                return
        if val is None:
            return
        if val.type in ("new_expression", "call_expression") and not in_method:   # auto x = Foo(…)
            tn = val.child_by_field_name("type") or val.child_by_field_name("function")
            cls = self.text(tn).split("<")[0].split("::")[-1] if tn is not None else ""
            if cls in self.classes:
                self.construct(name, cls, val.child_by_field_name("arguments")
                               or _first(val, "argument_list", "initializer_list"), env, self_obj)
                return
        v = self.value(val, env, self_obj)
        if self.is_obj(v) and not in_method and d.type not in ("pointer_declarator", "reference_declarator") \
                and val.type not in ("pointer_expression",):
            self.alias(name, v)               # Foo y = x; — копия, показываем как тот же объект
        env[name] = v

    def _assign_value(self, left, val, env, self_obj, in_method):
        if left.type == "identifier":
            n = self.text(left)
            if in_method and self_obj is not None and n not in env and n in self_obj.slots:
                self.set_slot(self_obj, n, val)
            else:
                env[n] = val
        elif left.type == "field_expression":
            owner = self.obj_of(left.child_by_field_name("argument"), env, self_obj)
            if owner is not None:
                self.set_slot(owner, self.text(left.child_by_field_name("field")), val)

    def assign(self, e, env, self_obj, in_method):
        left, right = e.child_by_field_name("left"), e.child_by_field_name("right")
        if left is None or right is None:
            return
        op = next((c.type for c in e.children if not c.is_named and c.type.endswith("=")), "=")
        if op != "=":                                   # a += b → "a + b"
            old = self.value(left, env, self_obj)
            new = self.value(right, env, self_obj)
            self.note(f"{_LANG}: `{op}` показан как выражение, не вычисляется")
            right = None
            val = f"{old} {op[:-1]} {new}"
            self._assign_value(left, val, env, self_obj, in_method)
            return
        if left.type == "identifier":
            n = self.text(left)
            if in_method and self_obj is not None and n not in env and n in self_obj.slots:
                self.set_slot(self_obj, n, self.value(right, env, self_obj))
            else:
                env[n] = self.value(right, env, self_obj)
        elif left.type == "field_expression":
            owner = self.obj_of(left.child_by_field_name("argument"), env, self_obj)
            if owner is not None:
                attr = self.text(left.child_by_field_name("field"))
                if right.type == "initializer_list":
                    self.set_list(owner, attr, [self.value(c, env, self_obj) for c in right.named_children])
                else:
                    self.set_slot(owner, attr, self.value(right, env, self_obj))


def extract(source: str, *, files=None) -> ObjectGraph:
    parts = []
    if files:
        parts = [f.get("code") or f.get("content") or "" for f in files if isinstance(f, dict)]
    if source:
        parts.insert(0, source)
    code = "\n".join(p for p in parts if p)
    if not code.strip():
        return ObjectGraph(notes=[f"{_LANG}: пустой исходник"])
    from .._ts import get_parser
    src = code.encode("utf-8")
    root = get_parser("cpp").parse(src).root_node
    tr = _Tracer(src)
    tr.collect(root)
    if not tr.classes:
        return ObjectGraph(notes=[f"{_LANG}: в коде нет классов"])
    if tr.main is None:
        return ObjectGraph(notes=[f"{_LANG}: функция main() не найдена"])
    env: dict[str, str] = {}
    for st in tr.main.named_children:
        tr.statement(st, env, None)
    return tr.graph(f"{_LANG}: в main() не создаются экземпляры пользовательских классов")
