"""Статическая трассировка Python → ObjectGraph (код не выполняется)."""
from uml_generator.objektis import extract_objects


def _g(src):
    g = extract_objects(src, "python")
    return {i.name: i for i in g.instances}, {(l.source, l.target, l.label): l.kind for l in g.links}, g.notes


def _slots(inst):
    return {s.name: s.value for s in inst.slots}


CLASSES = """
class Task:
    count = 0
    def __init__(self, title, done=False):
        self.title = title
        self.done = done
        self.owner = None
    def assign(self, p):
        self.owner = p

class Manager:
    def __init__(self, name="ops"):
        self.name = name
        self.tasks = []
    def add(self, t):
        self.tasks.append(t)
"""


def test_constructor_args_and_defaults():
    inst, _, _ = _g(CLASSES + 't1 = Task("a")\nt2 = Task(title="b", done=True)\n')
    assert _slots(inst["t1"]) == {"count": "0", "title": '"a"', "done": "False", "owner": "None"}
    assert _slots(inst["t2"])["done"] == "True" and _slots(inst["t2"])["title"] == '"b"'
    assert inst["t1"].type_name == "Task"


def test_attribute_assignment_makes_link():
    inst, links, _ = _g(CLASSES + 'm = Manager()\nt = Task("a")\nt.owner = m\n')
    assert _slots(inst["t"])["owner"] == "→ m"
    assert links[("t", "m", "owner")] == "association"


def test_method_call_append_and_assign():
    inst, links, _ = _g(CLASSES + 'm = Manager()\nt1 = Task("a")\nt2 = Task("b")\nm.add(t1)\nm.add(t2)\nt2.assign(t1)\n')
    assert _slots(inst["m"])["tasks"] == "[→t1, →t2]"
    assert links[("m", "t1", "tasks[0]")] == "containment"
    assert links[("m", "t2", "tasks[1]")] == "containment"
    assert links[("t2", "t1", "owner")] == "association"


def test_direct_append_and_nested_constructor():
    inst, links, _ = _g(CLASSES + 'm = Manager()\nm.tasks.append(Task("z"))\n')
    assert "task1" in inst and links[("m", "task1", "tasks[0]")] == "containment"


def test_list_literal_and_main_block():
    inst, _, _ = _g(CLASSES + 'xs = [Task("c"), Task("d")]\nif __name__ == "__main__":\n    t3 = Task("e")\n')
    assert {"xs[0]", "xs[1]", "t3"} <= set(inst)


def test_main_function_called():
    inst, _, _ = _g(CLASSES + 'def main():\n    m = Manager("x")\n    m.add(Task("q"))\nmain()\n')
    assert "m" in inst and _slots(inst["m"])["tasks"] == "[→task1]"


def test_inheritance_init():
    inst, _, _ = _g("""
class Base:
    def __init__(self, x):
        self.x = x
class Child(Base):
    pass
c = Child(5)
""")
    assert _slots(inst["c"]) == {"x": "5"} and inst["c"].type_name == "Child"


def test_loops_and_conditions_noted_not_executed():
    inst, _, notes = _g(CLASSES + 'for i in range(3):\n    t = Task(i)\nif True:\n    u = Task(1)\n')
    assert inst == {}
    assert any("циклы" in n for n in notes) and any("условия" in n for n in notes)


def test_no_classes():
    inst, _, notes = _g("x = 1\nprint(x)\n")
    assert inst == {} and notes


def test_never_executes(tmp_path):
    marker = tmp_path / "executed"
    src = CLASSES + f"import os\nopen({str(marker)!r}, 'w').close()\nt = Task(1)\n"
    inst, _, _ = _g(src)
    assert "t" in inst and not marker.exists()


def test_method_assigns_attribute_of_parameter():
    inst, links, _ = _g("""
class Customer:
    def __init__(self):
        self.orders = []
    def place(self, order):
        self.orders.append(order)
        order.customer = self
class Order:
    def __init__(self):
        self.customer = None
ann = Customer()
o = Order()
ann.place(o)
""")
    assert _slots(inst["o"])["customer"] == "→ ann" and links[("o", "ann", "customer")] == "association"
