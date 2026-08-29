"""Определение связей между классами по типам полей и методов."""
from uml_generator.extractor import extract_cs, extract_cpp, extract_py
from uml_generator.builder import _detect_relations, _type_refs, _param_types


def _rels(classes):
    return {(r.src, r.tgt): (r.kind, r.label) for r in _detect_relations(classes)}


def test_type_refs_nested_generics():
    names = {"Base", "Task"}
    refs = _type_refs("std::shared_ptr<Base<T>>", names)
    assert [(r.name, r.ptr) for r in refs] == [("Base", True)]
    refs = _type_refs("Dictionary<string, List<Task>>", names)
    assert [(r.name, r.many) for r in refs] == [("Task", True)]
    assert [(r.name, r.many) for r in _type_refs("Task[]", names)] == [("Task", True)]
    assert [(r.name, r.ptr, r.many) for r in _type_refs("Task*", names)] == [("Task", True, False)]
    assert _type_refs("int { get; set; }", names) == []


def test_type_refs_square_brackets_are_not_always_arrays():
    """`Optional[T]` / `Callable[…]` — не коллекция; `list[T]`, `T[]`, `T[10]` — коллекция."""
    names = {"Product"}
    assert [(r.name, r.many) for r in _type_refs("Optional[Product]", names)] == [("Product", False)]
    assert [(r.name, r.many) for r in _type_refs("Callable[[int], Product]", names)] == \
        [("Product", False)]
    assert [(r.name, r.many) for r in _type_refs("Product | None", names)] == [("Product", False)]
    assert [(r.name, r.many) for r in _type_refs("list[Product]", names)] == [("Product", True)]
    assert [(r.name, r.many) for r in _type_refs("dict[str, Product]", names)] == [("Product", True)]
    assert [(r.name, r.many) for r in _type_refs("Optional[list[Product]]", names)] == \
        [("Product", True)]
    assert [(r.name, r.many) for r in _type_refs("Product[10]", names)] == [("Product", True)]
    # `int[]` внутри обобщения не делает Product массивом
    assert [(r.name, r.many) for r in _type_refs("Func<Product, int[]>", names)] == \
        [("Product", False)]


def test_py_optional_field_is_composition_not_aggregation():
    rels = _rels(extract_py(
        "class Product:\n"
        "    pass\n"
        "class Cart:\n"
        "    def __init__(self):\n"
        "        self.item: Optional[Product] = None\n"
        "class Shelf:\n"
        "    def __init__(self):\n"
        "        self.rows: list[Product] = []\n"
    ))
    assert rels[("Cart", "Product")] == ("composition", "")
    assert rels[("Shelf", "Product")] == ("aggregation", "0..*")


def test_param_types():
    assert _param_types("(CancellationToken ct = default, params int[] rest, ref Foo f)") == \
        ["CancellationToken", "int[]", "Foo"]
    assert _param_types("()") == []
    assert _param_types("(Dictionary<string, int> m, int x)") == ["Dictionary<string, int>", "int"]


def test_cs_relations():
    rels = _rels(extract_cs("""
        interface ILog { void Log(string s); }
        enum Kind { A, B }
        class Task { public Kind K; }
        class Manager : ILog {
            private List<Task> tasks;
            private Task current;
            public class Cfg { }
            public void Log(string s) {}
            public Task Make(Kind k) { return null; }
        }
    """))
    assert rels[("Manager", "ILog")] == ("realization", "")
    # List<Task> + Task current: вид — по приоритету (композиция), кратность коллекции остаётся
    assert rels[("Manager", "Task")] == ("composition", "0..*")
    assert rels[("Task", "Kind")] == ("composition", "")
    assert rels[("Cfg", "Manager")] == ("nesting", "")
    assert rels[("Manager", "Kind")] == ("dependency", "")


def test_cpp_relations():
    rels = _rels(extract_cpp("""
        class Engine {};
        class Wheel {};
        class Car {
            Engine engine;
            std::unique_ptr<Engine> owned;
            std::vector<Wheel> wheels;
            Wheel* spare;
            void repair(const Engine& e);
        };
        class Garage { std::shared_ptr<Car> car; };
    """))
    assert rels[("Car", "Engine")] == ("composition", "")
    assert rels[("Car", "Wheel")] == ("aggregation", "0..*")
    assert rels[("Garage", "Car")] == ("aggregation", "")


def test_inheritance_beats_dependency_and_self_ignored():
    rels = _rels(extract_cs("class A { public A next; } class B : A { public void f(A a) {} }"))
    assert ("A", "A") not in rels
    assert rels[("B", "A")] == ("inheritance", "")
