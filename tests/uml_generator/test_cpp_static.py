"""Статическая трассировка main() в C++ → ObjectGraph (без компиляции и запуска)."""
from uml_generator.objektis import extract_objects


def _g(src):
    g = extract_objects(src, "cpp")
    return {i.name: i for i in g.instances}, {(l.source, l.target, l.label): l.kind for l in g.links}, g.notes


def _slots(inst):
    return {s.name: s.value for s in inst.slots}


CLASSES = """
#include <vector>
#include <string>
struct Task {
    std::string title;
    bool done = false;
    Task(std::string t, bool d = false) : title(t) { done = d; }
};
class Manager {
    std::vector<Task*> tasks;
    Task* current = nullptr;
public:
    int id;
    Manager(int i) { this->id = i; }
    void add(Task* t);
};
void Manager::add(Task* t) { tasks.push_back(t); current = t; }
struct Pod { int x; int y; };
"""


def _main(body):
    return CLASSES + "int main() {\n" + body + "\nreturn 0;\n}"


def test_declaration_forms():
    inst, _, _ = _g(_main('Task a("a");\nTask b{"b", true};\nauto c = Task("c");\nTask* d = new Task("d");\nManager m(7);'))
    assert _slots(inst["a"]) == {"title": '"a"', "done": "false"}
    assert _slots(inst["b"])["done"] == "true"
    assert inst["c"].type_name == "Task" and inst["d"].type_name == "Task"
    assert _slots(inst["m"]) == {"tasks": "[]", "current": "nullptr", "id": "7"}


def test_out_of_line_method_and_pointers():
    inst, links, _ = _g(_main('Manager m(1);\nTask a("a");\nTask* p = new Task("p");\nm.add(&a);\nm.add(p);\np->done = true;'))
    assert _slots(inst["m"])["tasks"] == "[→a, →p]" and _slots(inst["m"])["current"] == "→ p"
    assert links[("m", "a", "tasks[0]")] == "containment" and links[("m", "p", "current")] == "association"
    assert _slots(inst["p"])["done"] == "true"


def test_aggregate_init_and_field_assignment():
    inst, _, _ = _g(_main('Pod q{1, 2};\nq.x = 5;'))
    assert _slots(inst["q"]) == {"x": "5", "y": "2"}


def test_loops_and_missing_main():
    inst, _, notes = _g(_main('for (int i = 0; i < 2; i++) { Task t("a"); }'))
    assert inst == {} and any("циклы" in n for n in notes)
    g = extract_objects(CLASSES, "cpp")
    assert g.is_empty() and any("main" in n for n in g.notes)


def test_base_init_list_nested_struct_and_static():
    inst, links, _ = _g("""
struct Position { int x = 0; int y = 0; };
class Animal {
public:
    Animal(std::string name, int age = 1) : name_(name), age_(age) {}
    static int count;
    void move(int dx) { pos_.x += dx; }
protected:
    std::string name_; int age_; Position pos_;
};
class Dog : public Animal { public: Dog(std::string n) : Animal(n) {} };
int main() { Dog rex("Rex"); rex.move(3); return 0; }
""")
    assert _slots(inst["rex"]) == {"name_": '"Rex"', "age_": "1", "pos_": "→ rex.pos_"}
    assert _slots(inst["rex.pos_"]) == {"x": "0 + 3", "y": "0"}
    assert links[("rex", "rex.pos_", "pos_")] == "association"


def test_mutual_object_fields_do_not_recurse():
    """
    Двусторонняя связь Order ↔ Customer: `new_obj` → `attr_types` → `new_obj`
    уходил в рекурсию — 993 фантомных объекта (`o.buyer.lastOrder.buyer…`)
    и заметка «трассировка прервана (RecursionError)».
    """
    inst, links, notes = _g("""
#include <string>
class Customer;
class Order    { public: Customer& buyer; int total; };
class Customer { public: std::string name; Order& lastOrder; };
int main() { Order o; return 0; }
""")
    assert list(inst) == ["o", "o.buyer"]
    assert links[("o", "o.buyer", "buyer")] == "association"
    assert any("взаимная ссылка" in n for n in notes)
    assert not any("RecursionError" in n for n in notes)


def test_nested_object_fields_still_expand():
    """Цепочка без цикла разворачивается целиком — обрыв только на повторе класса."""
    inst, links, notes = _g("""
class Engine  { public: int power; };
class Gearbox { public: Engine motor; int gears; };
class Car     { public: Gearbox box; };
int main() { Car c; return 0; }
""")
    assert list(inst) == ["c", "c.box", "c.box.motor"]
    assert links[("c", "c.box", "box")] == "association"
    assert notes == []
