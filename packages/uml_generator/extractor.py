"""
Extractor — парсит C++ и C# исходники через tree-sitter
и возвращает список ClassInfo с полями и методами.
"""
from dataclasses import dataclass, field as dc_field


# ── Data structures ────────────────────────────────────────────────────────────

@dataclass
class FieldInfo:
    name:    str
    type_str: str
    access:  str  # "public" | "private" | "protected" | "internal"


@dataclass
class MethodInfo:
    name:          str
    return_type:   str
    params:        str
    access:        str
    is_constructor: bool = False


@dataclass
class ClassInfo:
    name:         str
    parents:      list[str]       = dc_field(default_factory=list)
    fields:       list[FieldInfo]  = dc_field(default_factory=list)
    methods:      list[MethodInfo] = dc_field(default_factory=list)
    is_interface: bool = False
    is_struct:    bool = False


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


def _access_sym(raw: str) -> str:
    raw = raw.lower().strip().rstrip(":")
    if raw in ("public", "private", "protected", "internal"):
        return raw
    return "private"


# ── C++ Extraction ─────────────────────────────────────────────────────────────

def _cpp_unwrap_declarator(node, src: bytes):
    """Recursively unwrap pointer/reference declarators to find function_declarator or identifier."""
    if node is None:
        return node
    if node.type in ("function_declarator",):
        return node
    if node.type in ("field_identifier", "identifier", "destructor_name", "operator_name"):
        return node
    # Dive into pointer/reference/abstract wrappers
    for child in node.children:
        if child.type in (
            "function_declarator", "field_identifier", "identifier",
            "pointer_declarator", "reference_declarator",
            "destructor_name", "operator_name",
        ):
            result = _cpp_unwrap_declarator(child, src)
            if result is not None:
                return result
    return node


def _cpp_parse_bases(base_clause_node, src: bytes) -> list[str]:
    result = []
    for child in base_clause_node.named_children:
        if child.type in ("type_identifier", "qualified_identifier", "template_type"):
            name = _text(child, src)
            if "<" in name:
                name = name[:name.index("<")].strip()
            result.append(name)
        elif child.type == "base_specifier":
            # Older tree-sitter-cpp versions wrap in base_specifier
            for c in child.named_children:
                if c.type in ("type_identifier", "qualified_identifier", "template_type"):
                    name = _text(c, src)
                    if "<" in name:
                        name = name[:name.index("<")].strip()
                    result.append(name)
                    break
    return result


def _cpp_field_name(declarator_node, src: bytes) -> str:
    """Extract bare name from a declarator node (unwrap pointers/refs/arrays)."""
    node = declarator_node
    for _ in range(10):  # prevent infinite loop
        if node.type in ("field_identifier", "identifier"):
            return _text(node, src)
        # Go deeper
        inner = None
        for child in node.children:
            if child.type not in ("*", "&", "&&", "[", "]", ")", "(", "const", "volatile"):
                inner = child
                break
        if inner is None or inner is node:
            break
        node = inner
    return _text(declarator_node, src)


def _cpp_parse_members(body_node, src: bytes, default_access: str):
    current = default_access
    fields:  list[FieldInfo]  = []
    methods: list[MethodInfo] = []

    for child in body_node.children:
        t = child.type

        if t == "access_specifier":
            current = _access_sym(_text(child, src))
            continue

        if t in ("field_declaration", "declaration"):
            type_node  = child.child_by_field_name("type")
            decl_node  = child.child_by_field_name("declarator")

            # Constructor / destructor have no type node but have a declarator
            if type_node is None and decl_node is not None:
                inner = _cpp_unwrap_declarator(decl_node, src)
                if inner and inner.type == "function_declarator":
                    name_node  = inner.child_by_field_name("declarator")
                    params_node = inner.child_by_field_name("parameters")
                    name = _text(name_node, src) if name_node else ""
                    params = _text(params_node, src) if params_node else "()"
                    if name:
                        methods.append(MethodInfo(
                            name=name, return_type="",
                            params=params, access=current,
                            is_constructor=True,
                        ))
                continue

            if type_node is None or decl_node is None:
                continue

            type_str = _text(type_node, src)
            inner = _cpp_unwrap_declarator(decl_node, src)

            if inner and inner.type == "function_declarator":
                name_node   = inner.child_by_field_name("declarator")
                params_node = inner.child_by_field_name("parameters")
                name   = _text(name_node, src) if name_node else ""
                params = _text(params_node, src) if params_node else "()"
                if name:
                    methods.append(MethodInfo(
                        name=name, return_type=type_str,
                        params=params, access=current,
                    ))
            else:
                name = _cpp_field_name(decl_node, src)
                if name:
                    fields.append(FieldInfo(name=name, type_str=type_str, access=current))

        elif t == "function_definition":
            type_node = child.child_by_field_name("type")
            decl_node = child.child_by_field_name("declarator")
            if decl_node is None:
                continue
            inner = _cpp_unwrap_declarator(decl_node, src)
            if inner and inner.type == "function_declarator":
                name_node   = inner.child_by_field_name("declarator")
                params_node = inner.child_by_field_name("parameters")
                name   = _text(name_node, src) if name_node else ""
                params = _text(params_node, src) if params_node else "()"
                ret    = _text(type_node, src) if type_node else ""
                if name:
                    methods.append(MethodInfo(
                        name=name, return_type=ret,
                        params=params, access=current,
                        is_constructor=(type_node is None),
                    ))

    return fields, methods


def _collect_cpp(node, src: bytes, result: list[ClassInfo]):
    # template_declaration wraps class_specifier — unwrap it
    if node.type == "template_declaration":
        for child in node.children:
            if child.type in ("class_specifier", "struct_specifier"):
                _collect_cpp(child, src, result)
                return
        # Recurse normally if no class found directly
        for child in node.children:
            _collect_cpp(child, src, result)
        return

    if node.type in ("class_specifier", "struct_specifier"):
        is_struct = node.type == "struct_specifier"
        default_access = "public" if is_struct else "private"

        has_body = any(c.type == "field_declaration_list" for c in node.children)
        if has_body:
            name = ""
            parents: list[str] = []
            fields:  list[FieldInfo]  = []
            methods: list[MethodInfo] = []

            for child in node.children:
                if child.type == "type_identifier" and not name:
                    name = _text(child, src)
                elif child.type == "base_class_clause":
                    try:
                        parents = _cpp_parse_bases(child, src)
                    except Exception:
                        pass
                elif child.type == "field_declaration_list":
                    try:
                        fields, methods = _cpp_parse_members(child, src, default_access)
                    except Exception:
                        pass

            if name:
                result.append(ClassInfo(
                    name=name, parents=parents,
                    fields=fields, methods=methods,
                    is_struct=is_struct,
                ))
        # Don't recurse into class body (avoids nested class duplication)
        return

    for child in node.children:
        _collect_cpp(child, src, result)


def extract_cpp(source: str) -> list[ClassInfo]:
    try:
        from ._ts import get_parser as _get_ts_parser
    except ImportError as e:
        raise ImportError(f"tree-sitter не установлен: {e}")

    parser = _get_ts_parser("cpp")
    src    = source.encode("utf-8")
    tree   = parser.parse(src)

    result: list[ClassInfo] = []
    _collect_cpp(tree.root_node, src, result)
    return result


# ── C# Extraction ──────────────────────────────────────────────────────────────

def _cs_modifiers(node, src: bytes) -> str:
    """Extract the effective access modifier from a C# member node."""
    mods = []
    for child in node.children:
        if child.type == "modifier":
            mods.append(_text(child, src).lower())
    if "public" in mods:
        return "public"
    if "protected" in mods:
        return "protected"
    if "internal" in mods:
        return "internal"
    return "private"


def _cs_parse_members(body_node, src: bytes):
    fields:  list[FieldInfo]  = []
    methods: list[MethodInfo] = []

    for child in body_node.named_children:
        t = child.type
        access = _cs_modifiers(child, src)

        try:
            if t == "field_declaration":
                var_decl = _child_of_type(child, "variable_declaration")
                if var_decl:
                    type_node = var_decl.child_by_field_name("type")
                    if type_node is None:
                        type_node = _child_of_type(var_decl,
                            "predefined_type", "identifier", "generic_name",
                            "nullable_type", "array_type", "qualified_name")
                    type_str = _text(type_node, src) if type_node else "?"
                    for vd in _children_of_type(var_decl, "variable_declarator"):
                        name_node = vd.child_by_field_name("name") or _child_of_type(vd, "identifier")
                        if name_node:
                            fields.append(FieldInfo(
                                name=_text(name_node, src),
                                type_str=type_str, access=access,
                            ))

            elif t == "property_declaration":
                type_node = child.child_by_field_name("type")
                name_node = child.child_by_field_name("name")
                if name_node:
                    fields.append(FieldInfo(
                        name=_text(name_node, src),
                        type_str=(_text(type_node, src) if type_node else "?") + " { get; set; }",
                        access=access,
                    ))

            elif t == "method_declaration":
                ret_node    = child.child_by_field_name("returns") or child.child_by_field_name("type")
                name_node   = child.child_by_field_name("name")
                params_node = child.child_by_field_name("parameters")
                if name_node:
                    methods.append(MethodInfo(
                        name=_text(name_node, src),
                        return_type=_text(ret_node, src) if ret_node else "void",
                        params=_text(params_node, src) if params_node else "()",
                        access=access,
                    ))

            elif t == "constructor_declaration":
                name_node   = child.child_by_field_name("name")
                params_node = child.child_by_field_name("parameters")
                if name_node:
                    methods.append(MethodInfo(
                        name=_text(name_node, src),
                        return_type="",
                        params=_text(params_node, src) if params_node else "()",
                        access=access,
                        is_constructor=True,
                    ))

        except Exception:
            pass

    return fields, methods


def _collect_cs(node, src: bytes, result: list[ClassInfo]):
    if node.type in ("class_declaration", "interface_declaration", "struct_declaration"):
        is_interface = node.type == "interface_declaration"
        is_struct    = node.type == "struct_declaration"

        name_node = node.child_by_field_name("name")
        if name_node is None:
            name_node = _child_of_type(node, "identifier")
        name = _text(name_node, src) if name_node else ""

        parents: list[str] = []
        base_list = node.child_by_field_name("bases") or _child_of_type(node, "base_list")
        if base_list:
            for base in base_list.named_children:
                if base.type in ("identifier", "generic_name", "qualified_name"):
                    base_name = _text(base, src)
                    if "<" in base_name:
                        base_name = base_name[:base_name.index("<")].strip()
                    parents.append(base_name)

        body = node.child_by_field_name("body") or _child_of_type(node, "declaration_list")
        fields, methods = [], []
        if body:
            try:
                fields, methods = _cs_parse_members(body, src)
            except Exception:
                pass

        if name:
            result.append(ClassInfo(
                name=name, parents=parents,
                fields=fields, methods=methods,
                is_interface=is_interface, is_struct=is_struct,
            ))
        return  # don't recurse into body (skip nested types)

    for child in node.children:
        _collect_cs(child, src, result)


def extract_cs(source: str) -> list[ClassInfo]:
    try:
        from ._ts import get_parser as _get_ts_parser
    except ImportError as e:
        raise ImportError(f"tree-sitter не установлен: {e}")

    parser = _get_ts_parser("c_sharp")
    src    = source.encode("utf-8")
    tree   = parser.parse(src)

    result: list[ClassInfo] = []
    _collect_cs(tree.root_node, src, result)
    return result
