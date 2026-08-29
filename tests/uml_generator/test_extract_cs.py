"""Разбор членов C# (статический, через tree-sitter)."""
from uml_generator.extractor import extract_cs


def _by_name(classes):
    return {c.name: c for c in classes}


def _field(cls, name):
    return next(f for f in cls.fields if f.name == name)


def _method(cls, name):
    return next(m for m in cls.methods if m.name == name)


SRC = """
namespace App {
  public enum Status { Active, Done }
  public record Point(int X, int Y);
  public abstract class Base<T> where T : class {
    public static int Count;
    protected readonly List<T> items = new();
    public event EventHandler Changed;
    public abstract void Run();
    public virtual T Get(int i) => items[i];
    public string Name { get; private set; }
    public int Ro { get; }
    public int Ex => 1;
    public int this[int i] => 0;
    public static Base<T> operator +(Base<T> a, Base<T> b) => a;
    ~Base() {}
    public class Nested { public int Z; }
    private int _x, _y;
    public const int K = 1;
  }
  public class Impl : Base<string>, IDisposable, IRunner {
    public override void Run() {}
    internal protected void X() {}
    private protected void Y() {}
    public void Gen<T>(T a, params int[] rest) {}
  }
  public interface IRunner { void Run(); int Speed { get; } }
  public struct Vec { public double X, Y; }
}
"""


def test_kinds_and_names():
    c = _by_name(extract_cs(SRC))
    assert set(c) == {"Status", "Point", "Base", "Nested", "Impl", "IRunner", "Vec"}
    assert c["Status"].kind == "enum" and c["Status"].enum_values == ["Active", "Done"]
    assert c["Point"].kind == "record"
    assert c["IRunner"].is_interface and c["Vec"].is_struct
    assert c["Base"].is_abstract and c["IRunner"].is_abstract and not c["Impl"].is_abstract


def test_generics_and_nested():
    c = _by_name(extract_cs(SRC))
    assert c["Base"].type_params == ["T"] and c["Base"].display_name == "Base<T>"
    assert c["Nested"].outer == "Base"
    assert c["Impl"].parents == ["Base", "IDisposable", "IRunner"]


def test_record_positional_params_are_properties():
    p = _by_name(extract_cs(SRC))["Point"]
    assert [(f.name, f.type_str) for f in p.fields] == [
        ("X", "int { get; init; }"), ("Y", "int { get; init; }")]


def test_primary_constructor_of_class_is_not_properties():
    """C# 12: `class Prim(int seed)` — первичный конструктор, а не свойства."""
    c = _by_name(extract_cs("class Prim(int seed, string name) { public int Seed => seed; }"))["Prim"]
    assert [f.name for f in c.fields] == ["Seed"]
    assert [(m.name, m.params, m.is_constructor) for m in c.methods] == \
        [("Prim", "(int seed, string name)", True)]
    s = _by_name(extract_cs("struct Vec2(double x, double y) { }"))["Vec2"]
    assert s.fields == [] and [m.name for m in s.methods] == ["Vec2"]


def test_interface_members_are_public():
    i = _by_name(extract_cs(SRC))["IRunner"]
    assert _method(i, "Run").access == "public" and _method(i, "Run").is_abstract
    assert _field(i, "Speed").access == "public"


def test_property_accessors():
    b = _by_name(extract_cs(SRC))["Base"]
    assert _field(b, "Name").type_str == "string { get; private set; }"
    assert _field(b, "Ro").type_str == "int { get; }" and _field(b, "Ro").is_readonly
    assert _field(b, "Ex").type_str == "int { get; }"
    assert _field(b, "this[int i]").type_str == "int { get; }"


def test_modifiers():
    b = _by_name(extract_cs(SRC))["Base"]
    assert _field(b, "Count").is_static and _field(b, "K").is_static and _field(b, "K").is_readonly
    assert _field(b, "items").is_readonly and _field(b, "items").access == "protected"
    assert _method(b, "Run").is_abstract and _method(b, "Get").is_virtual
    assert _method(b, "operator+").is_static
    assert _method(b, "~Base").is_destructor


def test_multiple_declarators_and_events():
    b = _by_name(extract_cs(SRC))["Base"]
    assert [f.name for f in b.fields if f.name.startswith("_")] == ["_x", "_y"]
    assert _field(b, "Changed").type_str == "event EventHandler"
    v = _by_name(extract_cs(SRC))["Vec"]
    assert [f.name for f in v.fields] == ["X", "Y"]


def test_combined_access_and_generic_method():
    i = _by_name(extract_cs(SRC))["Impl"]
    assert _method(i, "X").access == "protected internal"
    assert _method(i, "Y").access == "private protected"
    assert _method(i, "Gen<T>").params == "(T a, params int[] rest)"
    assert _method(i, "Run").is_virtual


def test_constructor():
    c = _by_name(extract_cs("class A { public A(int x) {} private A() {} }"))["A"]
    assert [(m.access, m.is_constructor) for m in c.methods] == [("public", True), ("private", True)]


def test_forward_and_empty():
    assert extract_cs("") == []
    assert [c.name for c in extract_cs("class A {} class B : A {}")] == ["A", "B"]
