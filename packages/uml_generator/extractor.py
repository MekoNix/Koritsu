"""
Extractor — статический разбор C++ и C# через tree-sitter → список ClassInfo.

Код не выполняется: только синтаксическое дерево. Типы без тела (`class Fwd;`)
и объявления вне классов (свободные функции, using, friend) пропускаются.
"""
from dataclasses import dataclass, field as dc_field


# ── Data structures ────────────────────────────────────────────────────────────

@dataclass
class FieldInfo:
    name:        str
    type_str:    str
    access:      str          # public | private | protected | internal |
                              # protected internal | private protected
    is_static:   bool = False
    is_readonly: bool = False # const / readonly / constexpr


@dataclass
class MethodInfo:
    name:           str
    return_type:    str
    params:         str
    access:         str
    is_constructor: bool = False
    is_destructor:  bool = False
    is_static:      bool = False
    is_abstract:    bool = False   # abstract / = 0
    is_virtual:     bool = False   # virtual / override
    is_const:       bool = False   # C++ const-метод


@dataclass
class ClassInfo:
    name:        str
    parents:     list[str]        = dc_field(default_factory=list)
    fields:      list[FieldInfo]  = dc_field(default_factory=list)
    methods:     list[MethodInfo] = dc_field(default_factory=list)
    kind:        str              = "class"   # class | interface | struct | enum | record | union
    is_abstract: bool             = False
    type_params: list[str]        = dc_field(default_factory=list)   # ["T", "U"]
    enum_values: list[str]        = dc_field(default_factory=list)
    outer:       str | None       = None      # имя внешнего типа для вложенных
    scope:       str              = ""        # namespace + внешние типы, через «.»

    @property
    def uid(self) -> str:
        """
        Полный идентификатор класса: `Rendering.Prim`, `Base.Inner`. Одноимённые
        классы из разных namespace различаются только им — по короткому имени
        связи уходят в первый попавшийся блок.
        """
        return f"{self.scope}.{self.name}" if self.scope else self.name

    @property
    def is_interface(self) -> bool:
        return self.kind == "interface"

    @property
    def is_struct(self) -> bool:
        return self.kind == "struct"

    @property
    def display_name(self) -> str:
        if self.type_params:
            return f"{self.name}<{', '.join(self.type_params)}>"
        return self.name


# ── Helpers ────────────────────────────────────────────────────────────────────

def _text(node, src: bytes) -> str:
    return src[node.start_byte:node.end_byte].decode("utf-8", errors="replace").strip()


def _child_of_type(node, *types):
    for c in node.children:
        if c.type in types:
            return c
    return None


def _children_of_type(node, *types):
    return [c for c in node.children if c.type in types]


def _same(a, b) -> bool:
    """Узлы tree-sitter пересоздаются при каждом обращении — `is` не работает."""
    return (a is not None and b is not None and a.type == b.type
            and a.start_byte == b.start_byte and a.end_byte == b.end_byte)


def _has_anon(node, token: str) -> bool:
    return any((not c.is_named) and c.type == token for c in node.children)


def _strip_generics(name: str) -> str:
    i = name.find("<")
    return name[:i].strip() if i >= 0 else name.strip()


def _norm_ws(s: str) -> str:
    return " ".join(s.split())


def _norm_qual(name: str) -> str:
    """`geom::Prim`, `Geometry . Prim` → `Geometry.Prim` — один разделитель на все языки."""
    return "".join(name.split()).replace("::", ".")


def _join_scope(scope: str, part: str) -> str:
    """Вложить область видимости в область видимости: (`N1`, `Outer`) → `N1.Outer`."""
    part = _norm_qual(part)
    if not part:
        return scope
    return f"{scope}.{part}" if scope else part


def _params_text(node, src: bytes) -> str:
    """Список параметров в одну строку, лишние пробелы/переводы строк убраны."""
    if node is None:
        return "()"
    return _norm_ws(_text(node, src))


# ── C++ ────────────────────────────────────────────────────────────────────────

_CPP_SKIP_TYPE_TOKENS = {
    "virtual", "static", "inline", "explicit", "friend", "mutable",
    "constexpr", "consteval", "extern", "thread_local",
}
_CPP_DECL_WRAPPERS = {
    "pointer_declarator", "reference_declarator", "array_declarator",
    "parenthesized_declarator", "function_declarator", "init_declarator",
}
_CPP_NAME_TYPES = {
    "field_identifier", "identifier", "destructor_name", "operator_name",
    "qualified_identifier", "template_function",
}


def _cpp_type_params(tpl_node, src: bytes) -> list[str]:
    out = []
    for p in tpl_node.named_children:
        n = p.child_by_field_name("name") or _child_of_type(
            p, "type_identifier", "identifier")
        if n is not None:
            out.append(_text(n, src))
        else:
            out.append(_text(p, src))
    return out


def _cpp_find_name(decl, src: bytes):
    """Имя внутри цепочки declarator'ов (pointer/ref/array/function/paren)."""
    node = decl
    for _ in range(12):
        if node is None:
            return None
        if node.type in _CPP_NAME_TYPES:
            return node
        nxt = node.child_by_field_name("declarator")
        if nxt is None:
            nxt = next((c for c in node.named_children
                        if c.type in _CPP_DECL_WRAPPERS or c.type in _CPP_NAME_TYPES), None)
        node = nxt
    return None


def _cpp_find_function(decl):
    """function_declarator в цепочке (для методов), иначе None."""
    node = decl
    for _ in range(12):
        if node is None:
            return None
        if node.type == "function_declarator":
            return node
        node = node.child_by_field_name("declarator") or next(
            (c for c in node.named_children if c.type in _CPP_DECL_WRAPPERS), None)
    return None


def _cpp_base_type(node, type_node, src: bytes) -> str:
    """Тип с квалификаторами (`const std::string`), без storage-спецификаторов."""
    parts = []
    for c in node.children:
        if _same(c, type_node):
            parts.append(_text(c, src))
        elif (c.type == "type_qualifier" and c.start_byte < type_node.end_byte
              and _text(c, src) in ("const", "volatile")):
            parts.append(_text(c, src))
    return _norm_ws(" ".join(parts))


def _cpp_decl_type(base: str, decl, name_node, src: bytes) -> str:
    """Тип поля с учётом обёрток declarator'а: `*next` → `Base*`, `arr[10]` → `int[10]`."""
    prefix, suffix = "", ""
    node = decl
    for _ in range(12):
        if node is None or _same(node, name_node):
            break
        if node.type == "pointer_declarator":
            prefix += "*"
        elif node.type == "reference_declarator":
            prefix += "&&" if _has_anon(node, "&&") else "&"
        elif node.type == "array_declarator":
            size = node.child_by_field_name("size")
            suffix += f"[{_text(size, src) if size is not None else ''}]"
        elif node.type == "function_declarator":
            params = node.child_by_field_name("parameters")
            inner = node.child_by_field_name("declarator")
            stars = ""
            while inner is not None and not _same(inner, name_node):
                if inner.type == "pointer_declarator":
                    stars += "*"
                inner = inner.child_by_field_name("declarator") or next(
                    (c for c in inner.named_children if c.type in _CPP_DECL_WRAPPERS), None)
            return f"{base} ({prefix}{stars})" + _params_text(params, src)
        node = node.child_by_field_name("declarator") or next(
            (c for c in node.named_children if c.type in _CPP_DECL_WRAPPERS), None)
    return f"{base}{prefix}{suffix}"


def _cpp_method(node, func, base_type: str, access: str, src: bytes) -> MethodInfo | None:
    name_node = _cpp_find_name(func.child_by_field_name("declarator"), src)
    if name_node is None:
        return None
    name = _text(name_node, src)
    if name_node.type == "qualified_identifier":
        name = name.split("::")[-1]
    params = _params_text(func.child_by_field_name("parameters"), src)

    is_dtor = name_node.type == "destructor_name" or name.startswith("~")
    is_ctor = not is_dtor and base_type == ""
    # обёртки между типом и function_declarator (`Foo* get()`, `const T& ref()`)
    ret = base_type
    if not is_ctor and not is_dtor:
        wrap = ""
        n = node.child_by_field_name("declarator")
        while n is not None and not _same(n, func):
            if n.type == "pointer_declarator":
                wrap += "*"
            elif n.type == "reference_declarator":
                wrap += "&&" if _has_anon(n, "&&") else "&"
            n = n.child_by_field_name("declarator") or next(
                (c for c in n.named_children if c.type in _CPP_DECL_WRAPPERS), None)
        ret = base_type + wrap

    is_const = any(c.type == "type_qualifier" and _text(c, src) == "const"
                   for c in func.children)
    is_virtual = _has_anon(node, "virtual") or any(
        c.type == "virtual_specifier" for c in func.children)
    is_pure = any(c.type == "number_literal" and _text(c, src) == "0"
                  for c in node.children)
    is_static = any(c.type == "storage_class_specifier" and _text(c, src) == "static"
                    for c in node.children)
    return MethodInfo(
        name=name, return_type=ret, params=params, access=access,
        is_constructor=is_ctor, is_destructor=is_dtor,
        is_static=is_static, is_abstract=is_pure, is_virtual=is_virtual or is_pure,
        is_const=is_const,
    )


def _cpp_member(node, access: str, src: bytes, cls: ClassInfo, result: list):
    """Один член тела класса. node: field_declaration | declaration | function_definition."""
    type_node = node.child_by_field_name("type")

    # вложенный тип: `class Inner {...};`, `enum E {...};`
    if type_node is not None and type_node.type in (
            "class_specifier", "struct_specifier", "enum_specifier", "union_specifier"):
        _collect_cpp(type_node, src, result, outer=cls.name, scope=cls.uid)
        return

    base_type = _cpp_base_type(node, type_node, src) if type_node is not None else ""
    is_static = any(c.type == "storage_class_specifier" and _text(c, src) == "static"
                    for c in node.children)
    is_const = any(c.type == "type_qualifier" and _text(c, src) in ("const", "constexpr")
                   for c in node.children)

    decls = node.children_by_field_name("declarator")
    if not decls:
        return
    for decl in decls:
        func = _cpp_find_function(decl)
        if func is not None:
            inner = func.child_by_field_name("declarator")
            # указатель на функцию `void (*cb)(int)` — это поле
            if inner is not None and inner.type == "parenthesized_declarator":
                name_node = _cpp_find_name(inner, src)
                if name_node is not None:
                    cls.fields.append(FieldInfo(
                        name=_text(name_node, src),
                        type_str=_cpp_decl_type(base_type, decl, name_node, src),
                        access=access, is_static=is_static, is_readonly=is_const))
                continue
            m = _cpp_method(node, func, base_type, access, src)
            if m is not None:
                cls.methods.append(m)
            continue
        name_node = _cpp_find_name(decl, src)
        if name_node is None:
            continue
        cls.fields.append(FieldInfo(
            name=_text(name_node, src),
            type_str=_cpp_decl_type(base_type, decl, name_node, src),
            access=access, is_static=is_static, is_readonly=is_const))


def _cpp_parse_body(body, src: bytes, cls: ClassInfo, default_access: str, result: list):
    access = default_access
    for child in body.children:
        t = child.type
        if t == "access_specifier":
            access = _text(child, src).rstrip(":").strip()
            continue
        if t == "template_declaration":
            inner = next((c for c in child.named_children
                          if c.type in ("declaration", "function_definition",
                                        "field_declaration", "class_specifier",
                                        "struct_specifier")), None)
            if inner is None:
                continue
            if inner.type in ("class_specifier", "struct_specifier"):
                _collect_cpp(child, src, result, outer=cls.name, scope=cls.uid)
            else:
                _cpp_member(inner, access, src, cls, result)
            continue
        if t in ("field_declaration", "declaration", "function_definition"):
            _cpp_member(child, access, src, cls, result)
        elif t in ("class_specifier", "struct_specifier", "enum_specifier", "union_specifier"):
            _collect_cpp(child, src, result, outer=cls.name, scope=cls.uid)
        # friend_declaration, alias_declaration, using_declaration — пропускаем


def _cpp_parse_bases(clause, src: bytes) -> list[str]:
    out = []
    for c in clause.named_children:
        if c.type in ("type_identifier", "qualified_identifier", "template_type"):
            out.append(_norm_qual(_strip_generics(_text(c, src))))
        elif c.type == "base_specifier":
            for cc in c.named_children:
                if cc.type in ("type_identifier", "qualified_identifier", "template_type"):
                    out.append(_norm_qual(_strip_generics(_text(cc, src))))
                    break
    return out


def _collect_cpp(node, src: bytes, result: list, outer: str | None = None, scope: str = ""):
    if node.type == "namespace_definition":     # `namespace a::b {}`, безымянный — прозрачен
        name_node = node.child_by_field_name("name")
        body = node.child_by_field_name("body")
        if name_node is not None:
            scope = _join_scope(scope, _text(name_node, src))
        for child in (body.children if body is not None else []):
            _collect_cpp(child, src, result, outer, scope)
        return

    type_params: list[str] = []
    if node.type == "template_declaration":
        tpl = _child_of_type(node, "template_parameter_list")
        inner = next((c for c in node.named_children
                      if c.type in ("class_specifier", "struct_specifier")), None)
        if inner is None:
            for c in node.children:
                _collect_cpp(c, src, result, outer, scope)
            return
        if tpl is not None:
            type_params = _cpp_type_params(tpl, src)
        node = inner

    if node.type in ("class_specifier", "struct_specifier", "union_specifier", "enum_specifier"):
        kind = {"class_specifier": "class", "struct_specifier": "struct",
                "union_specifier": "union", "enum_specifier": "enum"}[node.type]
        body = _child_of_type(node, "field_declaration_list", "enumerator_list")
        if body is None:            # forward declaration
            return
        name_node = node.child_by_field_name("name") or _child_of_type(node, "type_identifier")
        if name_node is None:
            return
        cls = ClassInfo(name=_text(name_node, src), kind=kind,
                        type_params=type_params, outer=outer, scope=scope)
        if kind == "enum":
            cls.enum_values = [_text(e.child_by_field_name("name") or e, src)
                               for e in body.named_children if e.type == "enumerator"]
            result.append(cls)
            return
        base_clause = _child_of_type(node, "base_class_clause")
        if base_clause is not None:
            cls.parents = _cpp_parse_bases(base_clause, src)
        result.append(cls)          # до тела — чтобы внешний тип шёл раньше вложенных
        _cpp_parse_body(body, src, cls, "private" if kind == "class" else "public", result)
        cls.is_abstract = any(m.is_abstract for m in cls.methods)
        return

    for child in node.children:
        _collect_cpp(child, src, result, outer, scope)


def extract_cpp(source: str) -> list[ClassInfo]:
    from kyotsu.ts import get_parser
    src = source.encode("utf-8")
    tree = get_parser("cpp").parse(src)
    result: list[ClassInfo] = []
    _collect_cpp(tree.root_node, src, result)
    return result


# ── C# ─────────────────────────────────────────────────────────────────────────

_CS_TYPE_DECLS = {
    "class_declaration": "class", "interface_declaration": "interface",
    "struct_declaration": "struct", "enum_declaration": "enum",
    "record_declaration": "record", "record_struct_declaration": "record",
}


def _cs_modifiers(node, src: bytes) -> set[str]:
    return {_text(c, src).lower() for c in node.children if c.type == "modifier"}


def _cs_access(mods: set[str], default: str) -> str:
    if "public" in mods:
        return "public"
    if "protected" in mods and "internal" in mods:
        return "protected internal"
    if "protected" in mods and "private" in mods:
        return "private protected"
    if "protected" in mods:
        return "protected"
    if "internal" in mods:
        return "internal"
    if "private" in mods:
        return "private"
    return default


def _cs_type_of(node, src: bytes):
    """Узел типа члена: поле `type`, иначе первый типовой child."""
    t = node.child_by_field_name("type") or node.child_by_field_name("returns")
    if t is not None:
        return t
    return _child_of_type(node, "predefined_type", "identifier", "generic_name",
                          "nullable_type", "array_type", "qualified_name",
                          "tuple_type", "pointer_type", "function_pointer_type")


def _cs_accessors(prop, src: bytes) -> str:
    acc = _child_of_type(prop, "accessor_list")
    if acc is None:
        return "{ get; }" if _child_of_type(prop, "arrow_expression_clause") else ""
    parts = []
    for a in acc.named_children:
        if a.type != "accessor_declaration":
            continue
        mods = _cs_modifiers(a, src)
        kw = next((c.type for c in a.children
                   if (not c.is_named) and c.type in ("get", "set", "init")), None)
        if kw is None:
            continue
        mod = next((m for m in ("private", "protected", "internal") if m in mods), "")
        parts.append(f"{mod} {kw};".strip())
    return "{ " + " ".join(parts) + " }" if parts else ""


def _cs_member(child, src: bytes, cls: ClassInfo, result: list):
    t = child.type
    if t in _CS_TYPE_DECLS:
        _collect_cs(child, src, result, outer=cls.name, scope=cls.uid)
        return

    mods = _cs_modifiers(child, src)
    default = "public" if cls.kind == "interface" else "private"
    access = _cs_access(mods, default)
    is_static = "static" in mods or "const" in mods
    common = dict(access=access, is_static=is_static)

    if t in ("field_declaration", "event_field_declaration"):
        var_decl = _child_of_type(child, "variable_declaration")
        if var_decl is None:
            return
        type_node = _cs_type_of(var_decl, src)
        type_str = _text(type_node, src) if type_node else "?"
        if t == "event_field_declaration":
            type_str = "event " + type_str
        for vd in _children_of_type(var_decl, "variable_declarator"):
            name_node = vd.child_by_field_name("name") or _child_of_type(vd, "identifier")
            if name_node:
                cls.fields.append(FieldInfo(
                    name=_text(name_node, src), type_str=type_str,
                    is_readonly=bool(mods & {"readonly", "const"}), **common))

    elif t == "property_declaration":
        type_node = _cs_type_of(child, src)
        name_node = child.child_by_field_name("name") or _child_of_type(child, "identifier")
        if name_node is None:
            return
        type_str = _text(type_node, src) if type_node else "?"
        acc = _cs_accessors(child, src)
        cls.fields.append(FieldInfo(
            name=_text(name_node, src),
            type_str=f"{type_str} {acc}".strip(),
            is_readonly=(acc == "{ get; }"), **common))

    elif t == "event_declaration":
        type_node = _cs_type_of(child, src)
        name_node = child.child_by_field_name("name") or _child_of_type(child, "identifier")
        if name_node is not None:
            cls.fields.append(FieldInfo(
                name=_text(name_node, src),
                type_str="event " + (_text(type_node, src) if type_node else "?"), **common))

    elif t == "method_declaration":
        ret = _cs_type_of(child, src)
        name_node = child.child_by_field_name("name") or _child_of_type(child, "identifier")
        if name_node is None:
            return
        name = _text(name_node, src)
        tpl = _child_of_type(child, "type_parameter_list")
        if tpl is not None:
            name += _text(tpl, src)
        cls.methods.append(MethodInfo(
            name=name,
            return_type=_text(ret, src) if ret else "void",
            params=_params_text(child.child_by_field_name("parameters")
                                or _child_of_type(child, "parameter_list"), src),
            is_abstract="abstract" in mods or (
                cls.kind == "interface" and _child_of_type(child, "block") is None),
            is_virtual=bool(mods & {"virtual", "override", "abstract"}), **common))

    elif t == "constructor_declaration":
        name_node = child.child_by_field_name("name") or _child_of_type(child, "identifier")
        if name_node is not None:
            cls.methods.append(MethodInfo(
                name=_text(name_node, src), return_type="",
                params=_params_text(child.child_by_field_name("parameters")
                                    or _child_of_type(child, "parameter_list"), src),
                is_constructor=True, **common))

    elif t == "destructor_declaration":
        name_node = _child_of_type(child, "identifier")
        cls.methods.append(MethodInfo(
            name="~" + (_text(name_node, src) if name_node else cls.name),
            return_type="", params="()", is_destructor=True, **common))

    elif t == "indexer_declaration":
        ret = _cs_type_of(child, src)
        params = _child_of_type(child, "bracketed_parameter_list")
        cls.fields.append(FieldInfo(
            name="this" + (_params_text(params, src) if params else "[]"),
            type_str=(_text(ret, src) if ret else "?") + " " + _cs_accessors(child, src),
            **common))

    elif t in ("operator_declaration", "conversion_operator_declaration"):
        ret = _cs_type_of(child, src)
        op = next((c for c in child.children
                   if (not c.is_named) and c.type not in ("operator", "implicit", "explicit")
                   and c.start_byte > (ret.end_byte if ret else 0)
                   and c.type not in ("(", ")", ";")), None)
        op_txt = _text(op, src) if op is not None else ""
        cls.methods.append(MethodInfo(
            name=f"operator{op_txt}",
            return_type=_text(ret, src) if ret else "",
            params=_params_text(child.child_by_field_name("parameters")
                                or _child_of_type(child, "parameter_list"), src),
            **common))


def _collect_cs(node, src: bytes, result: list, outer: str | None = None, scope: str = ""):
    if node.type == "namespace_declaration":            # вложенные namespace складываются
        nm = node.child_by_field_name("name")
        body = node.child_by_field_name("body")
        if nm is not None:
            scope = _join_scope(scope, _text(nm, src))
        for c in (body.children if body is not None else []):
            _collect_cs(c, src, result, outer, scope)
        return

    kind = _CS_TYPE_DECLS.get(node.type)
    if kind is None:
        for child in node.children:
            if child.type == "file_scoped_namespace_declaration":
                nm = child.child_by_field_name("name")       # `namespace N;` — до конца файла
                if nm is not None:
                    scope = _join_scope(scope, _text(nm, src))
                continue
            _collect_cs(child, src, result, outer, scope)
        return

    name_node = node.child_by_field_name("name") or _child_of_type(node, "identifier")
    if name_node is None:
        return
    mods = _cs_modifiers(node, src)
    cls = ClassInfo(name=_text(name_node, src), kind=kind, outer=outer, scope=scope,
                    is_abstract="abstract" in mods)
    if kind == "record" and _has_anon(node, "struct"):
        cls.kind = "struct"

    tpl = _child_of_type(node, "type_parameter_list")
    if tpl is not None:
        cls.type_params = [_text(p.child_by_field_name("name") or p, src)
                           for p in tpl.named_children if p.type == "type_parameter"]

    base_list = node.child_by_field_name("bases") or _child_of_type(node, "base_list")
    if base_list is not None:
        for base in base_list.named_children:
            if base.type in ("identifier", "generic_name", "qualified_name"):
                cls.parents.append(_norm_qual(_strip_generics(_text(base, src))))
            elif base.type == "primary_constructor_base_type":
                inner = _child_of_type(base, "identifier", "generic_name", "qualified_name")
                if inner is not None:
                    cls.parents.append(_norm_qual(_strip_generics(_text(inner, src))))

    # `partial class X` в нескольких местах — один тип: члены дописываем в уже собранный
    if "partial" in mods:
        prev = next((c for c in result if c.name == cls.name and c.outer == outer
                     and c.scope == scope and c.kind == cls.kind), None)
        if prev is not None:
            for p in cls.parents:
                if p not in prev.parents:
                    prev.parents.append(p)
            prev.type_params = prev.type_params or cls.type_params
            prev.is_abstract = prev.is_abstract or cls.is_abstract
            cls = prev
        else:
            result.append(cls)
    else:
        result.append(cls)

    if kind == "enum":
        body = _child_of_type(node, "enum_member_declaration_list")
        if body is not None:
            cls.enum_values = [
                _text(m.child_by_field_name("name") or _child_of_type(m, "identifier"), src)
                for m in body.named_children if m.type == "enum_member_declaration"]
        return

    # record Point(int X, int Y) — позиционные параметры = публичные свойства.
    # У class/struct (C# 12) те же скобки — это первичный конструктор: параметры
    # захватываются в поля, свойств не создают, поэтому пишем только конструктор.
    plist = _child_of_type(node, "parameter_list")
    if plist is not None:
        if node.type not in ("record_declaration", "record_struct_declaration"):
            cls.methods.append(MethodInfo(
                name=cls.name, return_type="", params=_params_text(plist, src),
                access="public", is_constructor=True))
            plist = None
    for p in (plist.named_children if plist is not None else []):
        if p.type != "parameter":
            continue
        ptype = _cs_type_of(p, src)
        pname = p.child_by_field_name("name") or _children_of_type(p, "identifier")[-1:]
        pname = pname[0] if isinstance(pname, list) and pname else pname
        if pname is None or isinstance(pname, list):
            continue
        cls.fields.append(FieldInfo(
            name=_text(pname, src),
            type_str=(_text(ptype, src) if ptype else "?") + " { get; init; }",
            access="public", is_readonly=True))

    body = node.child_by_field_name("body") or _child_of_type(node, "declaration_list")
    if body is not None:
        for child in body.named_children:
            _cs_member(child, src, cls, result)
    if kind == "interface":
        cls.is_abstract = True
    elif not cls.is_abstract:
        cls.is_abstract = any(m.is_abstract for m in cls.methods)


def extract_cs(source: str) -> list[ClassInfo]:
    from kyotsu.ts import get_parser
    src = source.encode("utf-8")
    tree = get_parser("c_sharp").parse(src)
    result: list[ClassInfo] = []
    _collect_cs(tree.root_node, src, result)
    return result


# ── Python ─────────────────────────────────────────────────────────────────────

_PY_LITERAL_TYPES = {
    "integer": "int", "float": "float", "string": "str", "concatenated_string": "str",
    "true": "bool", "false": "bool", "list": "list", "list_comprehension": "list",
    "dictionary": "dict", "dictionary_comprehension": "dict", "set": "set",
    "tuple": "tuple",
}


def _py_access(name: str) -> str:
    if name.startswith("__") and name.endswith("__"):
        return "public"
    if name.startswith("__"):
        return "private"
    if name.startswith("_"):
        return "protected"
    return "public"


def _py_infer_type(node, src: bytes, params: dict[str, str]) -> str:
    """Тип значения: аннотация параметра, литерал, вызов класса, иначе ''."""
    if node is None:
        return ""
    t = node.type
    if t in _PY_LITERAL_TYPES:
        return _PY_LITERAL_TYPES[t]
    if t == "identifier":
        return params.get(_text(node, src), "")
    if t == "call":
        fn = node.child_by_field_name("function")
        if fn is not None and fn.type == "identifier":
            name = _text(fn, src)
            if name[:1].isupper():
                return name
    if t == "attribute":                       # Status.NEW → Status
        obj = node.child_by_field_name("object")
        if obj is not None and obj.type == "identifier" and _text(obj, src)[:1].isupper():
            return _text(obj, src)
    return ""


def _py_params(params_node, src: bytes) -> tuple[str, dict[str, str]]:
    """Строка параметров без self/cls и словарь имя → аннотация."""
    parts, ann = [], {}
    for i, p in enumerate(params_node.named_children):
        if p.type == "identifier" and i == 0 and _text(p, src) in ("self", "cls"):
            continue
        if p.type in ("typed_parameter", "typed_default_parameter"):
            name_node = p.child_by_field_name("name") or p.named_children[0]
            ann[_text(name_node, src)] = _text(p.child_by_field_name("type"), src)
        parts.append(_norm_ws(_text(p, src)))
    return "(" + ", ".join(parts) + ")", ann


def _py_add_field(cls: ClassInfo, name: str, type_str: str, is_static=False):
    for f in cls.fields:
        if f.name == name:
            if not f.type_str and type_str:
                f.type_str = type_str
            return
    cls.fields.append(FieldInfo(name=name, type_str=type_str, access=_py_access(name),
                                is_static=is_static, is_readonly=name.isupper()))


def _py_targets(node) -> list[tuple]:
    """
    Пары (левый узел, узел значения) одного присваивания.

    Цепочка `a = b = 0` даёт две пары с общим значением, распаковка
    `x, y = 1, 2` — по паре на элемент (значение None, если не сопоставилось).
    """
    lefts, right = [], node
    while right is not None and right.type == "assignment":
        lefts.append(right.child_by_field_name("left"))
        right = right.child_by_field_name("right")
    out: list[tuple] = []
    for lt in lefts:
        if lt is None:
            continue
        if lt.type in ("pattern_list", "tuple_pattern"):
            vals = list(right.named_children) if (
                right is not None and right.type in ("expression_list", "tuple")) else []
            for i, t in enumerate(lt.named_children):
                out.append((t, vals[i] if i < len(vals) else None))
        else:
            out.append((lt, right))
    return out


def _py_self_assignments(block, src: bytes, cls: ClassInfo, params: dict[str, str]):
    """self.x = … на любой глубине тела метода → поля."""
    stack = [block]
    while stack:
        n = stack.pop()
        if n.type == "assignment":
            type_node = n.child_by_field_name("type")
            for left, value in _py_targets(n):
                if left.type != "attribute" or \
                        _text(left.child_by_field_name("object"), src) != "self":
                    continue
                name = _text(left.child_by_field_name("attribute"), src)
                type_str = _text(type_node, src) if type_node is not None else \
                    _py_infer_type(value, src, params)
                _py_add_field(cls, name, type_str)
        elif n.type not in ("function_definition", "class_definition", "lambda"):
            stack.extend(reversed(n.named_children))


def _collect_py(node, src: bytes, result: list, outer: str | None = None, scope: str = ""):
    decorators: list[str] = []
    if node.type == "decorated_definition":
        decorators = [_text(d, src).lstrip("@").split("(")[0] for d in node.named_children
                      if d.type == "decorator"]
        inner = node.child_by_field_name("definition")
        if inner is None or inner.type != "class_definition":
            return
        node = inner

    if node.type != "class_definition":
        for c in node.named_children:
            _collect_py(c, src, result, outer, scope)
        return

    name = _text(node.child_by_field_name("name"), src)
    cls = ClassInfo(name=name, outer=outer, scope=scope)
    sup = node.child_by_field_name("superclasses")
    bases = [_text(a, src) for a in sup.named_children] if sup is not None else []
    for b in bases:
        base = b.split(".")[-1]
        if base in ("ABC", "object", "Generic", "Protocol"):
            if base == "ABC":
                cls.is_abstract = True
            if base == "Protocol":
                cls.kind = "interface"
            continue
        if b.startswith("Generic[") or b.startswith("Protocol["):
            cls.type_params = [p.strip() for p in b[b.index("[") + 1:-1].split(",")]
            if b.startswith("Protocol"):
                cls.kind = "interface"
            continue
        if base in ("Enum", "IntEnum", "StrEnum", "Flag"):
            cls.kind = "enum"
            continue
        cls.parents.append(base.split("[")[0])
    is_dataclass = "dataclass" in decorators
    result.append(cls)

    body = node.child_by_field_name("body")
    for st in (body.named_children if body is not None else []):
        fdecos: list[str] = []
        item = st
        if st.type == "decorated_definition":
            fdecos = [_text(d, src).lstrip("@").split("(")[0].split(".")[-1]
                      for d in st.named_children if d.type == "decorator"]
            item = st.child_by_field_name("definition")
            if item is None:
                continue
        if item.type == "class_definition":
            _collect_py(st, src, result, outer=name, scope=cls.uid)
            continue
        if item.type == "expression_statement" and item.named_children:
            e = item.named_children[0]
            if e.type == "assignment":
                left = e.child_by_field_name("left")
                if left is None or left.type != "identifier":
                    continue
                fname = _text(left, src)
                if cls.kind == "enum":
                    cls.enum_values.append(fname)
                    continue
                type_node = e.child_by_field_name("type")
                type_str = _text(type_node, src) if type_node is not None else \
                    _py_infer_type(e.child_by_field_name("right"), src, {})
                # аннотированное поле dataclass — поле экземпляра; иначе — атрибут класса (static)
                _py_add_field(cls, fname, type_str, is_static=not (is_dataclass and type_node is not None))
            continue
        if item.type != "function_definition":
            continue
        mname = _text(item.child_by_field_name("name"), src)
        params_str, ann = _py_params(item.child_by_field_name("parameters"), src)
        ret = item.child_by_field_name("return_type")
        ret_str = _text(ret, src) if ret is not None else ""
        if "property" in fdecos or "cached_property" in fdecos:
            _py_add_field(cls, mname, ret_str)
            continue
        if mname == "__init__" or "setter" in fdecos:
            _py_self_assignments(item.child_by_field_name("body"), src, cls, ann)
            if mname != "__init__":
                continue
        else:
            _py_self_assignments(item.child_by_field_name("body"), src, cls, ann)
        is_abstract = "abstractmethod" in fdecos
        cls.methods.append(MethodInfo(
            name=mname, return_type=ret_str, params=params_str, access=_py_access(mname),
            is_constructor=(mname == "__init__"),
            is_static=("staticmethod" in fdecos or "classmethod" in fdecos),
            is_abstract=is_abstract, is_virtual=is_abstract))
    if any(m.is_abstract for m in cls.methods):
        cls.is_abstract = True


def extract_py(source: str) -> list[ClassInfo]:
    from kyotsu.ts import get_parser
    src = source.encode("utf-8")
    tree = get_parser("python").parse(src)
    result: list[ClassInfo] = []
    _collect_py(tree.root_node, src, result)
    return result
