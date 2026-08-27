"""Разбор членов C++ (статический, через tree-sitter)."""
from uml_generator.extractor import extract_cpp


def _by_name(classes):
    return {c.name: c for c in classes}


def _field(cls, name):
    return next(f for f in cls.fields if f.name == name)


def _method(cls, name):
    return next(m for m in cls.methods if m.name == name)


SRC = """
namespace geo {
enum class Color { Red, Blue };
template<typename T>
class Base {
public:
    Base();
    virtual ~Base();
    virtual void run() = 0;
    static int count;
    std::vector<T> items;
    std::shared_ptr<Base<T>> next;
    const std::string& name() const;
    friend class Friend;
    class Inner { int z; };
    using Ptr = std::shared_ptr<Base>;
    int arr[10];
    void (*cb)(int);
    bool operator==(const Base& o) const;
    template<class U> void tmpl(U u);
protected:
    int prot_;
private:
    mutable int mut_;
    int a_, b_;
    Base* self_;
};
class Derived final : public Base<int>, private Mixin {
public:
    explicit Derived(int x) : Base<int>() {}
    void run() override;
    inline static constexpr int K = 3;
    Derived(const Derived&) = delete;
};
struct Pod { int x; int y; Pod* next; };
union U { int i; float f; };
}
class Fwd;
"""


def test_kinds_and_names():
    c = _by_name(extract_cpp(SRC))
    assert set(c) == {"Color", "Base", "Inner", "Derived", "Pod", "U"}
    assert c["Color"].kind == "enum" and c["Color"].enum_values == ["Red", "Blue"]
    assert c["U"].kind == "union" and c["Pod"].is_struct
    assert c["Base"].is_abstract and not c["Derived"].is_abstract


def test_template_and_nested():
    c = _by_name(extract_cpp(SRC))
    assert c["Base"].type_params == ["T"] and c["Base"].display_name == "Base<T>"
    assert c["Inner"].outer == "Base"
    assert c["Derived"].parents == ["Base", "Mixin"]


def test_access_sections():
    b = _by_name(extract_cpp(SRC))["Base"]
    assert _field(b, "count").access == "public"
    assert _field(b, "prot_").access == "protected"
    assert _field(b, "mut_").access == "private" and _field(b, "mut_").type_str == "int"
    p = _by_name(extract_cpp(SRC))["Pod"]
    assert _field(p, "x").access == "public"           # struct — public по умолчанию
    assert _field(_by_name(extract_cpp(SRC))["Inner"], "z").access == "private"


def test_multiple_declarators():
    b = _by_name(extract_cpp(SRC))["Base"]
    assert [f.name for f in b.fields if f.name.endswith("_") and f.name[0] in "ab"] == ["a_", "b_"]


def test_field_types():
    b = _by_name(extract_cpp(SRC))["Base"]
    assert _field(b, "arr").type_str == "int[10]"
    assert _field(b, "cb").type_str == "void (*)(int)"
    assert _field(b, "next").type_str == "std::shared_ptr<Base<T>>"
    assert _field(b, "self_").type_str == "Base*"
    assert _field(b, "count").is_static
    assert _field(_by_name(extract_cpp(SRC))["Pod"], "next").type_str == "Pod*"


def test_methods():
    b = _by_name(extract_cpp(SRC))["Base"]
    names = [m.name for m in b.methods]
    assert names == ["Base", "~Base", "run", "name", "operator==", "tmpl"]
    assert _method(b, "Base").is_constructor
    assert _method(b, "~Base").is_destructor and _method(b, "~Base").is_virtual
    assert _method(b, "run").is_abstract and _method(b, "run").is_virtual
    assert _method(b, "name").return_type == "const std::string&" and _method(b, "name").is_const
    assert _method(b, "operator==").return_type == "bool"
    assert _method(b, "tmpl").params == "(U u)"


def test_derived_modifiers():
    d = _by_name(extract_cpp(SRC))["Derived"]
    assert _method(d, "run").is_virtual
    assert _field(d, "K").is_static and _field(d, "K").is_readonly and _field(d, "K").type_str == "int"
    ctors = [m for m in d.methods if m.is_constructor]
    assert [m.params for m in ctors] == ["(int x)", "(const Derived&)"]


def test_forward_declaration_skipped():
    assert "Fwd" not in _by_name(extract_cpp(SRC))
    assert extract_cpp("") == []
