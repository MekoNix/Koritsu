"""
cs_static — диаграмма объектов из C#-кода БЕЗ компиляции и выполнения.

Трассируется тело `Main()` (первого найденного) по tree-sitter:

  var x = new Foo(1, name: "a");   Foo x = new(...);   — экземпляр; слоты из полей
      класса с инициализаторами и из конструктора (`X = x;`, `this.X = x;`)
  new Foo { A = 1, B = y }                              — object initializer
  x.A = <выражение>                                     — слот / связь
  x.Items.Add(y);  list.Add(y)                          — элемент коллекции `Items[i]`
  new List<Foo> { a, b };  Foo[] xs = { new Foo() };    — коллекции
  x.Method(args)                                        — простые методы:
      `field = p;`, `this.field = p;`, `field.Add(p);`

Циклы, условия и прочее — пропускаются с заметкой.
"""
from ._trace import ClassDef, Method, Obj, TraceState
from .model import ObjectGraph

_LANG = "objektis/csharp"


def _named(node, *types):
    return [c for c in node.named_children if c.type in types]


def _first(node, *types):
    for c in node.named_children:
        if c.type in types:
            return c
    return None


class _Tracer(TraceState):
    def __init__(self, src: bytes):
        super().__init__(src)
        self.main = None
        self.top: list = []          # операторы верхнего уровня (C# 9), если Main() нет

    def ma_parts(self, node):
        """member_access_expression → (узел базы | "this", имя члена)."""
        name = node.child_by_field_name("name") or node.named_children[-1]
        base = node.child_by_field_name("expression")
        if base is None:
            others = [c for c in node.named_children if not (c.start_byte == name.start_byte)]
            base = others[0] if others else "this"
        return base, self.text(name)

    # ── классы ──
    def collect(self, node):
        if node.type == "global_statement":      # C# 9: код без class Program / Main()
            if node.named_children:
                self.top.append(node.named_children[0])
            return
        if node.type in ("class_declaration", "struct_declaration", "record_declaration"):
            self._collect_class(node)
        for c in node.named_children:
            if node.type not in ("class_declaration", "struct_declaration", "record_declaration"):
                self.collect(c)

    def _params(self, plist):
        params, defaults = [], {}
        for p in (plist.named_children if plist is not None else []):
            if p.type != "parameter":
                continue
            ids = _named(p, "identifier")
            name_node = p.child_by_field_name("name") or (ids[-1] if ids else None)
            if name_node is None:
                continue
            params.append(self.text(name_node))
            eq = _first(p, "equals_value_clause")
            if eq is not None and eq.named_children:
                defaults[self.text(name_node)] = self.text(eq.named_children[0])
            elif p.named_children and p.named_children[-1].start_byte > name_node.end_byte:
                defaults[self.text(name_node)] = self.text(p.named_children[-1])   # `bool done = false`
        return params, defaults

    def _collect_class(self, node):
        name = self.text(node.child_by_field_name("name") or _first(node, "identifier"))
        bases = []
        bl = node.child_by_field_name("bases") or _first(node, "base_list")
        if bl is not None:
            bases = [self.text(b).split("<")[0] for b in bl.named_children
                     if b.type in ("identifier", "generic_name")]
        cls = ClassDef(name, bases, ctor=name)
        body = node.child_by_field_name("body") or _first(node, "declaration_list")
        for m in (body.named_children if body is not None else []):
            mods = {self.text(c) for c in m.children if c.type == "modifier"}
            if m.type in ("field_declaration", "property_declaration") and mods & {"static", "const"}:
                continue
            if m.type == "field_declaration":
                vd = _first(m, "variable_declaration")
                for d in (_named(vd, "variable_declarator") if vd else []):
                    dn = d.child_by_field_name("name") or _first(d, "identifier")
                    init = d.named_children[-1] if len(d.named_children) > 1 else None
                    cls.attrs[self.text(dn)] = self._default(init, vd)
            elif m.type == "property_declaration":
                pn = m.child_by_field_name("name") or _named(m, "identifier")[-1]
                init = _first(m, "equals_value_clause")
                cls.attrs[self.text(pn)] = self._default(
                    init.named_children[0] if init and init.named_children else None, m)
            elif m.type in ("constructor_declaration", "method_declaration"):
                mname = self.text(m.child_by_field_name("name") or _named(m, "identifier")[-1])
                params, defaults = self._params(
                    m.child_by_field_name("parameters") or _first(m, "parameter_list"))
                body_node = m.child_by_field_name("body") or _first(m, "block")
                if m.type == "method_declaration" and mname == "Main":
                    self.main = self.main or body_node
                    continue
                cls.methods[mname] = Method(params, defaults, body_node, m)
            elif m.type in ("class_declaration", "struct_declaration", "record_declaration"):
                self._collect_class(m)
        self.classes[name] = cls

    def _default(self, init, type_owner) -> str:
        if init is None:
            t = type_owner.child_by_field_name("type") or (type_owner.named_children[0]
                                                            if type_owner.named_children else None)
            ts = self.text(t) if t is not None else ""
            if ts in ("int", "long", "double", "float", "decimal", "short", "byte"):
                return "0"
            if ts == "bool":
                return "false"
            if ts == "string":
                return "null"
            return "null"
        if init.type in ("object_creation_expression", "implicit_object_creation_expression"):
            t = init.child_by_field_name("type")
            if t is None or self.text(t).split("<")[0] not in self.classes:
                return "[]" if (t is None or "<" in self.text(t) or "[" in self.text(t)) else self.text(init)
        return self.text(init)

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
        if t in ("this", "this_expression") and self_obj is not None:
            return self_obj.name
        if t == "member_access_expression":
            base, attr = self.ma_parts(node)
            owner = self.obj_of(base, env, self_obj)
            if owner is not None and attr in owner.slots:
                return owner.slots[attr]
            return self.text(node)
        if t in ("object_creation_expression", "implicit_object_creation_expression"):
            tn = node.child_by_field_name("type")
            cls = self.text(tn).split("<")[0] if tn is not None else ""
            args = node.child_by_field_name("arguments") or _first(node, "argument_list")
            init = node.child_by_field_name("initializer") or _first(node, "initializer_expression")
            if cls in self.classes:
                obj = self.construct(self.auto_name(cls), cls, args, env, self_obj)
                self.object_init(obj, init, env, self_obj)
                return obj.name
            if init is not None:                          # new List<T> { a, b }
                items = [self.value(c, env, self_obj) for c in init.named_children]
                return "[" + ", ".join(self.fmt(i) for i in items) + "]"
            if tn is not None and ("<" in self.text(tn) or "[" in self.text(tn)):
                return "[]"
            return self.text(node)
        if t in ("initializer_expression", "array_creation_expression"):
            init = node if t == "initializer_expression" else _first(node, "initializer_expression")
            items = [self.value(c, env, self_obj) for c in init.named_children] if init else []
            return "[" + ", ".join(self.fmt(i) for i in items) + "]"
        return self.text(node)

    def items_of(self, node, env, self_obj) -> list[str] | None:
        """Список элементов для коллекции-литерала или None."""
        init = None
        if node.type in ("object_creation_expression", "implicit_object_creation_expression"):
            init = node.child_by_field_name("initializer") or _first(node, "initializer_expression")
            tn = node.child_by_field_name("type")
            if tn is not None and self.text(tn).split("<")[0] in self.classes:
                return None
        elif node.type == "initializer_expression":
            init = node
        elif node.type == "array_creation_expression":
            init = _first(node, "initializer_expression")
        if init is None:
            return None
        return [self.value(c, env, self_obj) for c in init.named_children]

    def bind(self, m: Method, arglist, env, self_obj) -> dict[str, str]:
        bound = dict(m.defaults)
        pos = 0
        for a in (arglist.named_children if arglist is not None else []):
            if a.type != "argument":
                continue
            name = a.child_by_field_name("name")
            if name is None and len(a.named_children) >= 2 and a.named_children[0].type == "identifier" \
                    and ":" in self.text(a):
                name = a.named_children[0]
            expr = a.named_children[-1]
            if name is not None:
                bound[self.text(name)] = self.value(expr, env, self_obj)
            else:
                if pos < len(m.params):
                    bound[m.params[pos]] = self.value(expr, env, self_obj)
                pos += 1
        return bound

    # ── вызовы ──
    def construct(self, name, cls, args, env, self_obj=None) -> Obj:
        obj = self.new_obj(name, cls)
        self.run_ctor(obj, cls, args, env, self_obj)
        return obj

    def run_ctor(self, obj: Obj, cls: str, args, env, self_obj):
        ctor = self.classes[cls].methods.get(cls) if cls in self.classes else None
        if ctor is None:                              # нет своего — конструктор базового
            for b in self.classes[cls].bases if cls in self.classes else []:
                if b in self.classes:
                    self.run_ctor(obj, b, args, env, self_obj)
                    return
            return
        local = self.bind(ctor, args, env, self_obj)
        init = _first(ctor.node, "constructor_initializer")
        if init is not None and "base" in self.text(init).split("(")[0]:
            for b in self.classes[cls].bases:
                if b in self.classes:
                    self.run_ctor(obj, b, _first(init, "argument_list"), local, obj)
                    break
        self.run_method(obj, ctor, local)

    def object_init(self, obj: Obj, init, env, self_obj):
        if init is None:
            return
        for a in init.named_children:
            if a.type == "assignment_expression":
                left, right = a.child_by_field_name("left"), a.child_by_field_name("right")
                if left is not None and left.type == "identifier":
                    self.assign_slot(obj, self.text(left), right, env, self_obj)

    def assign_slot(self, obj: Obj, attr: str, right, env, self_obj):
        items = self.items_of(right, env, self_obj)
        if items is not None:
            self.set_list(obj, attr, items)
        else:
            self.set_slot(obj, attr, self.value(right, env, self_obj))

    def run_method(self, obj: Obj, m: Method, local: dict[str, str]):
        if not self.enter_call():
            return
        try:
            env = dict(local)
            for st in (m.body.named_children if m.body is not None else []):
                self.statement(st, env, obj, in_method=True)
        finally:
            self.leave_call()

    def obj_of(self, node, env, self_obj: Obj | None) -> Obj | None:
        if node is None:
            return None
        if node == "this" or node.type in ("this", "this_expression"):
            return self_obj
        if node.type == "identifier":
            n = self.text(node)
            if n in env:
                return self.resolve(env[n])
            if self_obj is not None and n in self_obj.slots and self.is_obj(self_obj.slots[n]):
                return self.resolve(self_obj.slots[n])
            return self.resolve(n)
        if node.type == "member_access_expression":
            v = self.value(node, env, self_obj)
            return self.resolve(v) if self.is_obj(v) else None
        return None

    def invoke(self, node, env, self_obj: Obj | None, in_method: bool):
        fn = node.child_by_field_name("function") or node.named_children[0]
        args = node.child_by_field_name("arguments") or _first(node, "argument_list")
        if fn.type != "member_access_expression":
            return
        base, mname = self.ma_parts(fn)
        arg_nodes = [a.named_children[-1] for a in (args.named_children if args else []) if a.type == "argument"]
        owner = self.obj_of(base, env, self_obj)
        if owner is not None and self.find_method(owner.type, mname) is not None:
            m = self.find_method(owner.type, mname)
            self.run_method(owner, m, self.bind(m, args, env, self_obj))
            return
        if mname in ("Add", "Push", "Enqueue", "AddLast"):
            # field.Add(x) внутри метода / this.field.Add(x) / obj.Field.Add(x) / list.Add(x)
            if base != "this" and base.type == "member_access_expression":
                b2, attr = self.ma_parts(base)
                owner = self.obj_of(b2, env, self_obj)
            elif base != "this" and base.type == "identifier" and self_obj is not None and self.text(base) in self_obj.slots \
                    and self.text(base) not in env:
                owner, attr = self_obj, self.text(base)
            else:
                if arg_nodes and base != "this" and base.type == "identifier":
                    self.note(f"{_LANG}: {self.text(base)}.Add(…) — локальная коллекция не привязана к объекту")
                return
            if owner is not None and arg_nodes:
                self.append(owner, attr, self.value(arg_nodes[0], env, self_obj))
            return
        owner = self.obj_of(base, env, self_obj)
        if owner is None:
            return
        m = self.find_method(owner.type, mname)
        if m is None:
            self.note(f"{_LANG}: метод {owner.type}.{mname} не найден")

    # ── операторы ──
    def statement(self, st, env: dict[str, str], self_obj: Obj | None, in_method=False):
        t = st.type
        if t == "local_declaration_statement":
            vd = _first(st, "variable_declaration")
            for d in (_named(vd, "variable_declarator") if vd else []):
                name = self.text(d.child_by_field_name("name") or _first(d, "identifier"))
                init = d.named_children[-1] if len(d.named_children) > 1 else None
                if init is None:
                    continue
                tn = vd.child_by_field_name("type") or vd.named_children[0]
                self.declare(name, init, env, self_obj, in_method,
                             decl_type=self.text(tn).split("<")[0])
        elif t == "expression_statement" and st.named_children:
            e = st.named_children[0]
            if e.type == "assignment_expression":
                self.assign(e, env, self_obj, in_method)
            elif e.type == "invocation_expression":
                self.invoke(e, env, self_obj, in_method)
        elif t in ("for_statement", "for_each_statement", "while_statement", "do_statement"):
            self.note(f"{_LANG}: циклы не трассируются")
        elif t in ("if_statement", "switch_statement"):
            self.note(f"{_LANG}: условия не трассируются (ветки не выбираются)")
        elif t in ("return_statement", "comment", "empty_statement", "block"):
            pass
        else:
            self.note(f"{_LANG}: пропущено: {t}")

    def declare(self, name, init, env, self_obj, in_method, decl_type=""):
        if init.type in ("object_creation_expression", "implicit_object_creation_expression"):
            tn = init.child_by_field_name("type")
            cls = self.text(tn).split("<")[0] if tn is not None else decl_type
            if cls in self.classes and not in_method:
                obj = self.construct(name, cls, init.child_by_field_name("arguments")
                                     or _first(init, "argument_list"), env, self_obj)
                self.object_init(obj, init.child_by_field_name("initializer")
                                 or _first(init, "initializer_expression"), env, self_obj)
                return
        items = self.items_of(init, env, self_obj)
        if items is not None:
            env[name] = "[" + ", ".join(self.fmt(i) for i in items) + "]"
            return
        env[name] = self.value(init, env, self_obj)

    def _assign_value(self, left, val, env, self_obj, in_method):
        if left.type == "identifier":
            n = self.text(left)
            if in_method and self_obj is not None and n not in env:
                self.set_slot(self_obj, n, val)
            else:
                env[n] = val
        elif left.type == "member_access_expression":
            base, attr = self.ma_parts(left)
            owner = self.obj_of(base, env, self_obj)
            if owner is not None:
                self.set_slot(owner, attr, val)

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
            if in_method and self_obj is not None and n not in env:
                self.assign_slot(self_obj, n, right, env, self_obj)
            else:
                env[n] = self.value(right, env, self_obj)
        elif left.type == "member_access_expression":
            base, attr = self.ma_parts(left)
            owner = self.obj_of(base, env, self_obj)
            if owner is not None:
                self.assign_slot(owner, attr, right, env, self_obj)


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
    root = get_parser("c_sharp").parse(src).root_node
    tr = _Tracer(src)
    tr.collect(root)
    if not tr.classes:
        return ObjectGraph(notes=[f"{_LANG}: в коде нет классов"])
    if tr.main is None and not tr.top:
        return ObjectGraph(notes=[f"{_LANG}: ни Main(), ни операторов верхнего уровня не найдено"])
    where = "Main()" if tr.main is not None else "операторах верхнего уровня"
    body = list(tr.main.named_children) if tr.main is not None else tr.top
    env: dict[str, str] = {}
    try:
        for st in body:
            tr.statement(st, env, None)
    except Exception as e:  # noqa: BLE001 — уже построенные объекты не выбрасываем
        tr.note(f"{_LANG}: трассировка прервана ({type(e).__name__})")
    return tr.graph(f"{_LANG}: в {where} не создаются экземпляры пользовательских классов")
