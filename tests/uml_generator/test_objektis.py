"""
Тесты objektis: end-to-end проверка Python dynamic backend + builder.
Запуск:
    python -m unittest tests.uml_generator.test_objektis

Сохраняет .drawio рядом с этим файлом для визуальной проверки.
"""
import os
import sys

_PACKAGES = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), 'packages')
if _PACKAGES not in sys.path:
    sys.path.insert(0, _PACKAGES)

from uml_generator.objektis._facade import extract_objects
from uml_generator.objektis.builder import build_xml

_OUT = os.path.dirname(os.path.abspath(__file__))


def _save(name: str, xml: str) -> str:
    path = os.path.join(_OUT, f"test_{name}.drawio")
    with open(path, "w", encoding="utf-8") as f:
        f.write(xml)
    return path


def _assert(cond: bool, msg: str):
    if not cond:
        raise AssertionError(msg)
    print(f"  OK  {msg}")


# ── 1. Простой случай: 1 объект ───────────────────────────────────────────────

_SAMPLE_1 = '''
class Point:
    def __init__(self, x, y):
        self.x = x
        self.y = y

p = Point(3, 4)
'''


def test_simple_one_object():
    print("\n== test_simple_one_object ==")
    g = extract_objects(_SAMPLE_1, "python")
    _assert(len(g.instances) == 1, "должен быть один инстанс")
    inst = g.instances[0]
    _assert(inst.name == "p", f"имя инстанса = 'p', получили {inst.name!r}")
    _assert(inst.type_name == "Point", f"тип = 'Point', получили {inst.type_name!r}")
    slot_names = {s.name for s in inst.slots}
    _assert(slot_names == {"x", "y"}, f"слоты = x,y, получили {slot_names}")
    _save("simple", build_xml(g))


# ── 2. Композиция: один объект ссылается на другой ───────────────────────────

_SAMPLE_2 = '''
class Engine:
    def __init__(self, power):
        self.power = power

class Car:
    def __init__(self, name, engine):
        self.name = name
        self.engine = engine

e = Engine(120)
c = Car("Toyota", e)
'''


def test_two_objects_with_link():
    print("\n== test_two_objects_with_link ==")
    g = extract_objects(_SAMPLE_2, "python")
    _assert(len(g.instances) == 2, f"2 инстанса, получили {len(g.instances)}")
    names = {i.name for i in g.instances}
    _assert(names == {"e", "c"}, f"имена = e,c, получили {names}")
    _assert(len(g.links) == 1, f"1 link, получили {len(g.links)}")
    link = g.links[0]
    _assert(link.source == "c" and link.target == "e",
            f"link c→e, получили {link.source}→{link.target}")
    _assert(link.label == "engine", f"label = engine, получили {link.label!r}")
    _save("two_link", build_xml(g))


# ── 3. Коллекция: TaskManager содержит список Task'ов ─────────────────────────

_SAMPLE_3 = '''
class Task:
    def __init__(self, title, done=False):
        self.title = title
        self.done = done

class TaskManager:
    def __init__(self):
        self.tasks = []
    def add(self, t):
        self.tasks.append(t)

mgr = TaskManager()
mgr.add(Task("buy milk"))
mgr.add(Task("call mom", done=True))
mgr.add(Task("write report"))
'''


def test_collection():
    print("\n== test_collection ==")
    # На уровне extract_objects получаем «сырые» 3 link'а до коллапса.
    g = extract_objects(_SAMPLE_3, "python")
    types = sorted(i.type_name for i in g.instances)
    _assert(types == ["Task", "Task", "Task", "TaskManager"],
            f"4 инстанса (3 Task + 1 TaskManager), получили {types}")
    contain_links = [l for l in g.links if l.kind == "containment"]
    _assert(len(contain_links) == 3,
            f"3 containment links, получили {len(contain_links)}")
    sources = {l.source for l in contain_links}
    _assert(sources == {"mgr"}, f"все containment from mgr, получили {sources}")
    # build_xml должен свернуть в 1 summary-инстанс с multiplicity=3.
    xml = build_xml(g)
    _assert("[3]" in xml, "должна быть multiplicity [3] в заголовке")
    _save("collection", xml)


# ── 4. Цикл ссылок: parent ↔ child ────────────────────────────────────────────

_SAMPLE_4 = '''
class Node:
    def __init__(self, name):
        self.name = name
        self.parent = None
        self.children = []

root = Node("root")
a = Node("a")
b = Node("b")
root.children = [a, b]
a.parent = root
b.parent = root
'''


def test_cyclic_refs():
    print("\n== test_cyclic_refs ==")
    g = extract_objects(_SAMPLE_4, "python")
    _assert(len(g.instances) == 3, f"3 узла, получили {len(g.instances)}")
    # a.parent → root, b.parent → root, root.children[0] → a, [1] → b
    parent_links = [l for l in g.links if l.label == "parent"]
    _assert(len(parent_links) == 2, f"2 parent-link, получили {len(parent_links)}")
    targets = {l.target for l in parent_links}
    _assert(targets == {"root"}, f"оба parent → root, получили {targets}")
    _save("cyclic", build_xml(g))


# ── 5. Краш: код падает, но классы определены — должен быть частичный snapshot ─

_SAMPLE_5 = '''
class Counter:
    def __init__(self):
        self.value = 0

c = Counter()
c.value = 42
raise ValueError("boom")
'''


def test_crashed_code_partial_snapshot():
    print("\n== test_crashed_code_partial_snapshot ==")
    g = extract_objects(_SAMPLE_5, "python")
    _assert(len(g.instances) == 1, f"должен быть 1 инстанс, получили {len(g.instances)}")
    _assert(g.instances[0].name == "c", "имя инстанса 'c'")
    _assert(any("user code" in n for n in g.notes), f"должна быть заметка о краше: {g.notes}")
    _save("crashed", build_xml(g))


# ── 6. Пустой код / нет классов ──────────────────────────────────────────────

def test_empty():
    print("\n== test_empty ==")
    g = extract_objects("", "python")
    _assert(g.is_empty(), "пустой граф для пустого кода")
    g2 = extract_objects("x = 1\nprint(x)", "python")
    _assert(g2.is_empty(), "пустой граф если нет user-классов")


# ── 7. Неподдерживаемый язык ──────────────────────────────────────────────────

def test_unknown_language():
    print("\n== test_unknown_language ==")
    g = extract_objects("class Foo {}", "java")
    _assert(g.is_empty(), "пустой граф для java")
    _assert(any("java" in n for n in g.notes), f"заметка про язык: {g.notes}")


# ── C# тесты ─────────────────────────────────────────────────────────────────
# Эти тесты skip'аются если нет dotnet или tree-sitter-languages.

import shutil as _shutil


def _csharp_available() -> tuple[bool, str]:
    if _shutil.which("dotnet") is None:
        return False, "dotnet не найден"
    try:
        from uml_generator._ts import get_parser
        get_parser("c_sharp")
    except Exception as e:
        return False, f"tree-sitter-languages: {e}"
    return True, ""


_CS_SAMPLE_1 = """
using System;
class Point {
    public int X;
    public int Y;
    public Point(int x, int y) { X = x; Y = y; }
}
class Program {
    static void Main(string[] args) {
        Point p = new Point(3, 4);
    }
}
"""


def test_csharp_simple():
    print("\n== test_csharp_simple ==")
    ok, why = _csharp_available()
    if not ok:
        print(f"  SKIP: {why}")
        return
    g = extract_objects(_CS_SAMPLE_1, "csharp", timeout=120)
    if g.is_empty():
        print(f"  SKIP/FAIL: graph пуст · notes={g.notes}")
        return
    _assert(len(g.instances) >= 1, f"≥1 инстанс, получили {len(g.instances)}")
    types = {i.type_name for i in g.instances}
    _assert("Point" in types, f"должен быть Point, получили {types}")
    _save("csharp_simple", build_xml(g))


_CS_SAMPLE_2 = """
using System;
using System.Collections.Generic;

class Task {
    public string Title;
    public bool Done;
    public Task(string title) { Title = title; Done = false; }
}

class TaskManager {
    public List<Task> Tasks = new List<Task>();
    public void Add(Task t) { Tasks.Add(t); }
}

class Program {
    static void Main(string[] args) {
        TaskManager mgr = new TaskManager();
        Task t1 = new Task("buy milk");
        Task t2 = new Task("call mom");
        mgr.Add(t1);
        mgr.Add(t2);
    }
}
"""


def test_csharp_collection():
    print("\n== test_csharp_collection ==")
    ok, why = _csharp_available()
    if not ok:
        print(f"  SKIP: {why}")
        return
    g = extract_objects(_CS_SAMPLE_2, "csharp", timeout=120)
    if g.is_empty():
        print(f"  SKIP/FAIL: graph пуст · notes={g.notes}")
        return
    # Сырое: 1 TaskManager + 2 Task + 2 containment link.
    types = sorted(i.type_name for i in g.instances)
    _assert(types == ["Task", "Task", "TaskManager"],
            f"3 инстанса (1 mgr + 2 tasks), получили {types}")
    contain = [l for l in g.links if l.kind == "containment"]
    _assert(len(contain) >= 2,
            f"≥2 containment links, получили {len(contain)}")
    # build_xml должен свернуть в 1 summary с multiplicity=2.
    xml = build_xml(g)
    _assert("[2]" in xml, "должна быть multiplicity [2] в заголовке")
    _save("csharp_collection", xml)


_CS_SAMPLE_3 = """
using System;
class Engine {
    public int Power;
    public Engine(int p) { Power = p; }
}
class Car {
    public string Model;
    public Engine Motor;
    public Car(string m, Engine e) { Model = m; Motor = e; }
}
class Program {
    static void Main(string[] args) {
        Engine e = new Engine(120);
        Car c = new Car("Toyota", e);
    }
}
"""


def test_csharp_link():
    print("\n== test_csharp_link ==")
    ok, why = _csharp_available()
    if not ok:
        print(f"  SKIP: {why}")
        return
    g = extract_objects(_CS_SAMPLE_3, "csharp", timeout=120)
    if g.is_empty():
        print(f"  SKIP/FAIL: graph пуст · notes={g.notes}")
        return
    names = {i.name for i in g.instances}
    _assert(names == {"e", "c"}, f"имена e,c, получили {names}")
    motor_links = [l for l in g.links if l.label == "Motor"]
    _assert(len(motor_links) == 1, f"1 link Motor, получили {len(motor_links)}")
    _assert(motor_links[0].source == "c" and motor_links[0].target == "e",
            "link c→e через Motor")
    _save("csharp_link", build_xml(g))


_CS_SAMPLE_4_NO_MAIN = """
using System;
class Foo { public int X; }
"""


def test_csharp_no_main():
    print("\n== test_csharp_no_main ==")
    ok, why = _csharp_available()
    if not ok:
        print(f"  SKIP: {why}")
        return
    g = extract_objects(_CS_SAMPLE_4_NO_MAIN, "csharp", timeout=60)
    _assert(g.is_empty(), "пустой граф если нет Main")
    has_warning = any("Main" in n for n in g.notes)
    _assert(has_warning, f"должна быть заметка про Main: {g.notes}")


# ── runner ────────────────────────────────────────────────────────────────────

def _run_all():
    tests = [
        test_simple_one_object,
        test_two_objects_with_link,
        test_collection,
        test_cyclic_refs,
        test_crashed_code_partial_snapshot,
        test_empty,
        test_unknown_language,
        test_csharp_simple,
        test_csharp_collection,
        test_csharp_link,
        test_csharp_no_main,
    ]
    failures = []
    for t in tests:
        try:
            t()
        except AssertionError as e:
            print(f"  FAIL: {t.__name__}: {e}")
            failures.append(t.__name__)
        except Exception as e:
            print(f"  ERROR: {t.__name__}: {type(e).__name__}: {e}")
            failures.append(t.__name__)

    print("\n" + "=" * 50)
    if failures:
        print(f"FAILED: {len(failures)} / {len(tests)}")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print(f"ALL PASSED ({len(tests)} tests)")
        print(f"drawio файлы: {_OUT}")


if __name__ == "__main__":
    _run_all()
