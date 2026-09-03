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


def test_alias_resolves_to_object():
    """`y = m` — тот же объект; слот должен ссылаться на него, а не на текст «y»."""
    inst, links, _ = _g(CLASSES + 'm = Manager()\ny = m\nt = Task("a")\nt.owner = y\n')
    assert _slots(inst["t"])["owner"] == "→ m"
    assert links[("t", "m", "owner")] == "association"
    assert "y" not in inst


def test_recursive_method_keeps_built_objects():
    """Рекурсия обрывается по глубине; уже собранные объекты остаются."""
    inst, _, notes = _g("""
class A:
    def __init__(self):
        self.x = 1
    def f(self):
        self.f()
a = A()
a.f()
""")
    assert _slots(inst["a"]) == {"x": "1"}
    assert any("рекурсия" in n for n in notes)


def test_chained_and_tuple_assignment():
    """`self.a = self.b = 0` даёт оба слота, `self.x, self.y = 1, 2` — тоже."""
    inst, _, _ = _g("""
class P:
    def __init__(self):
        self.a = self.b = 0
        self.x, self.y = 1, 2
p = P()
""")
    assert _slots(inst["p"]) == {"a": "0", "b": "0", "x": "1", "y": "2"}


def test_chained_assignment_builds_one_object():
    """`t.a = t.b = M()` — один экземпляр на два слота, а не два."""
    inst, links, _ = _g("""
class M:
    def __init__(self):
        self.v = 1
class T:
    def __init__(self):
        self.a = None
        self.b = None
t = T()
t.a = t.b = M()
""")
    assert [i.type_name for i in inst.values()].count("M") == 1
    m = next(n for n, i in inst.items() if i.type_name == "M")
    assert links[("t", m, "a")] == "association" and links[("t", m, "b")] == "association"


def test_unattachable_assignment_in_method_makes_no_phantom_object():
    """`self.xs[0] = M()` / `unknown.a = M()` не должны рождать объект без связей."""
    inst, _, _ = _g("""
class M:
    def __init__(self):
        self.v = 1
class Box:
    def __init__(self):
        self.xs = []
    def fill(self):
        self.xs[0] = M()
        unknown.attr = M()
b = Box()
b.fill()
""")
    assert [i.type_name for i in inst.values()] == ["Box"]


# ── соседние файлы ───────────────────────────────────────────────────────────
# Материалов у задания бывает несколько, и класс редко лежит в том же файле,
# что и точка входа. До 2.0.0a4.2 `files` игнорировался вовсе: соседний файл
# молча пропадал, а схема выходила пустой — и почему, узнать было нельзя.

ДВИГАТЕЛЬ = """
class Двигатель:
    def __init__(self, мощность):
        self.мощность = мощность
"""


def _многофайл(source, *files):
    g = extract_objects(source, "python",
                        files=[{"filename": f"сосед{i}.py", "code": c}
                               for i, c in enumerate(files)])
    return {i.name: i for i in g.instances}, g.notes


def test_класс_из_соседнего_файла_виден_точке_входа():
    """Экземпляр создаётся в первом материале, класс объявлен во втором."""
    inst, _ = _многофайл("д = Двигатель(120)\n", ДВИГАТЕЛЬ)
    assert list(inst) == ["д"]
    assert inst["д"].type_name == "Двигатель"
    assert _slots(inst["д"]) == {"мощность": "120"}


def test_соседей_может_быть_несколько_и_наследование_через_них_видно():
    """Базовый класс в одном соседе, наследник в другом — слоты собираются оба."""
    база = "class Узел:\n    def __init__(self):\n        self.имя = None\n"
    потомок = ("class Мотор(Узел):\n    def __init__(self):\n"
               "        self.имя = 'м'\n        self.об = 0\n")
    inst, _ = _многофайл("m = Мотор()\n", база, потомок)
    assert _slots(inst["m"]) == {"имя": "'м'", "об": "0"}


def test_код_уровня_модуля_у_соседа_не_исполняется():
    """Иначе на схеме появился бы экземпляр, которого при импорте не возникает.

    Разница с C#/C++, где склейка безопасна: там трассируется только `Main()`,
    а у Python исполняется весь модуль. Молчать об этом нельзя — заметка.
    """
    inst, notes = _многофайл("д = Двигатель(120)\n",
                             ДВИГАТЕЛЬ + "лишний = Двигатель(1)\n")
    assert list(inst) == ["д"]
    assert any("только объявления" in n for n in notes), notes


def test_объявления_у_соседа_заметки_не_родят():
    """Импорты, докстрока и определения — не пропущенный код, жаловаться не на что.

    Докстрока модуля разбирается как обычное выражение, и без отдельной
    проверки заметка выскакивала бы на любом файле с шапкой, то есть почти
    на всех: заметка, которая всегда есть, ничего не сообщает.
    """
    сосед = '"""Двигатель."""\nimport os\n' + ДВИГАТЕЛЬ
    _, notes = _многофайл("д = Двигатель(120)\n", сосед)
    assert not any("только объявления" in n for n in notes), notes


def test_пустой_сосед_ничего_не_ломает():
    inst, _ = _многофайл("д = Двигатель(120)\n", "", ДВИГАТЕЛЬ, None)
    assert list(inst) == ["д"]
