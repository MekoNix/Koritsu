"""Статическая трассировка Main() в C# → ObjectGraph (без компиляции и запуска)."""
from uml_generator.objektis import extract_objects


def _g(src):
    g = extract_objects(src, "csharp")
    return {i.name: i for i in g.instances}, {(l.source, l.target, l.label): l.kind for l in g.links}, g.notes


def _slots(inst):
    return {s.name: s.value for s in inst.slots}


CLASSES = """
using System.Collections.Generic;
class Task {
    public string Title;
    public bool Done = false;
    public Task(string title, bool done = false) { Title = title; this.Done = done; }
}
class Manager {
    private List<Task> tasks = new List<Task>();
    public Task Current { get; set; }
    public string Name;
    public Manager(string name) { Name = name; }
    public void Add(Task t) { tasks.Add(t); Current = t; }
}
"""


def _main(body):
    return CLASSES + "class Program { static void Main(string[] args) {\n" + body + "\n} }"


def test_constructors_and_defaults():
    inst, _, _ = _g(_main('var m = new Manager("ops");\nTask t = new Task("a");\nTask u = new("b", done: true);'))
    assert _slots(inst["m"]) == {"tasks": "[]", "Current": "null", "Name": '"ops"'}
    assert _slots(inst["t"]) == {"Title": '"a"', "Done": "false"}
    assert _slots(inst["u"])["Done"] == "true" and inst["u"].type_name == "Task"


def test_method_call_and_property_assignment():
    inst, links, _ = _g(_main('var m = new Manager("x");\nvar a = new Task("a");\nvar b = new Task("b");\nm.Add(a);\nm.Add(b);\na.Title = "z";'))
    assert _slots(inst["m"])["tasks"] == "[→a, →b]" and _slots(inst["m"])["Current"] == "→ b"
    assert links[("m", "a", "tasks[0]")] == "containment"
    assert links[("m", "b", "Current")] == "association"
    assert _slots(inst["a"])["Title"] == '"z"'


def test_object_initializer_and_collections():
    inst, links, _ = _g(_main('var t = new Task("a") { Done = true };\nvar xs = new List<Task> { t, new Task("b") };\nTask[] arr = { new Task("c") };'))
    assert _slots(inst["t"])["Done"] == "true"
    assert {"task1", "task2"} <= set(inst)


def test_direct_collection_add_on_field():
    inst, links, _ = _g(_main('var m = new Manager("x");\nm.Current = new Task("q");'))
    assert _slots(inst["m"])["Current"] == "→ task1" and links[("m", "task1", "Current")] == "association"


def test_loops_noted_no_main_noted():
    inst, _, notes = _g(_main('for (int i = 0; i < 3; i++) { var t = new Task("a"); }'))
    assert inst == {} and any("циклы" in n for n in notes)
    g = extract_objects(CLASSES, "csharp")
    assert g.is_empty() and any("Main" in n for n in g.notes)


def test_base_constructor_and_static_skipped():
    inst, _, _ = _g("""
class Shape { public static int Count; protected string Fill = "red"; public string Name;
              public Shape(string name) { Name = name; Count++; } }
class Circle : Shape { public double R; public Circle(string name, double r) : base(name) { R = r; } }
class P { static void Main() { var c = new Circle("c1", 2); } }
""")
    assert _slots(inst["c"]) == {"Fill": '"red"', "Name": '"c1"', "R": "2"}


def test_compound_assignment_shown_as_expression():
    inst, _, notes = _g(_main('var t = new Task("a");\nt.Title += "!";'))
    assert _slots(inst["t"])["Title"] == '"a" + "!"' and any("+=" in n for n in notes)
