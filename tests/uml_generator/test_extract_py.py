"""Разбор классов Python (статический, через tree-sitter)."""
from uml_generator.extractor import extract_py
from uml_generator.builder import _detect_relations


def _by_name(classes):
    return {c.name: c for c in classes}


def _field(cls, name):
    return next(f for f in cls.fields if f.name == name)


def _method(cls, name):
    return next(m for m in cls.methods if m.name == name)


SRC = """
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum

class Status(Enum):
    NEW = 1
    DONE = 2

@dataclass
class Point:
    x: int
    y: int = 0

class Base(ABC):
    counter: int = 0
    def __init__(self, id: int, tags=None):
        self.id = id
        self._secret = "x"
        self.__hidden = []
        self.items: list[str] = []
        self.status = Status.NEW
        self.origin = Point(1, 2)
    @abstractmethod
    def area(self) -> float: ...
    @staticmethod
    def make(n): pass
    @property
    def size(self) -> int: return 1
    def _helper(self, a, *args, **kw): pass
    class Inner:
        pass

class Child(Base, Mixin):
    def area(self): return 0.0
    def grow(self):
        self.extra = 5
"""


def test_kinds():
    c = _by_name(extract_py(SRC))
    assert set(c) == {"Status", "Point", "Base", "Inner", "Child"}
    assert c["Status"].kind == "enum" and c["Status"].enum_values == ["NEW", "DONE"]
    assert c["Base"].is_abstract and not c["Child"].is_abstract
    assert c["Inner"].outer == "Base"
    assert c["Child"].parents == ["Base", "Mixin"]      # ABC не считается родителем


def test_dataclass_fields():
    p = _by_name(extract_py(SRC))["Point"]
    assert [(f.name, f.type_str, f.is_static) for f in p.fields] == [("x", "int", False), ("y", "int", False)]


def test_init_fields_and_access():
    b = _by_name(extract_py(SRC))["Base"]
    assert [f.name for f in b.fields] == ["counter", "id", "_secret", "__hidden", "items", "status", "origin", "size"]
    assert _field(b, "counter").is_static and _field(b, "counter").type_str == "int"
    assert _field(b, "id").type_str == "int"                  # из аннотации параметра
    assert _field(b, "_secret").access == "protected" and _field(b, "_secret").type_str == "str"
    assert _field(b, "__hidden").access == "private" and _field(b, "__hidden").type_str == "list"
    assert _field(b, "items").type_str == "list[str]"
    assert _field(b, "status").type_str == "Status" and _field(b, "origin").type_str == "Point"
    assert _field(b, "size").type_str == "int"                # @property → поле


def test_methods():
    b = _by_name(extract_py(SRC))["Base"]
    assert _method(b, "__init__").is_constructor and _method(b, "__init__").access == "public"
    assert _method(b, "__init__").params == "(id: int, tags=None)"
    assert _method(b, "area").is_abstract and _method(b, "area").return_type == "float"
    assert _method(b, "make").is_static and _method(b, "make").params == "(n)"
    assert _method(b, "_helper").access == "protected" and _method(b, "_helper").params == "(a, *args, **kw)"
    assert "size" not in [m.name for m in b.methods]
    c = _by_name(extract_py(SRC))["Child"]
    assert _field(c, "extra").type_str == "int"               # self.x в любом методе


def test_relations():
    rels = {(r.src, r.tgt): (r.kind, r.label) for r in _detect_relations(extract_py(SRC))}
    assert rels[("Child", "Base")] == ("inheritance", "")
    assert rels[("Base", "Status")] == ("composition", "")
    assert rels[("Base", "Point")] == ("composition", "")
    assert rels[("Inner", "Base")] == ("nesting", "")
