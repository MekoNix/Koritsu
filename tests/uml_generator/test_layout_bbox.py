"""
Раскладка по рамкам: блоки, подписи и линии не должны налезать друг на друга.

Проверка идёт по готовому draw.io XML (`_bbox.boxes_from_xml`), а не по
внутренним структурам раскладки: наезжают на картинке именно нарисованные
прямоугольники, и мерить надо их.
"""
from uml_generator import build_xml, extract_cpp, extract_cs, extract_py
from uml_generator import objektis
from uml_generator._bbox import boxes_from_xml, find_crossings, find_overlaps, overlap
from uml_generator.styles import get_layout

# ── Образцы ───────────────────────────────────────────────────────────────────

PY_MANY_METHODS = "class Huge:\n" + "".join(
    f"    def method_number_{i:02d}(self, argument_one: dict[str, list[int]], "
    f"argument_two: OtherService = None) -> ResultEnvelope:\n        pass\n"
    for i in range(30)) + (
    "class OtherService:\n    def ping(self) -> bool: pass\n"
    "class ResultEnvelope:\n    def ok(self) -> bool: pass\n")

CS_FIFTEEN = """
namespace App {
  public interface IRepository { void Save(Entity e); }
  public abstract class Entity { public int Id; public string Name; }
  public class Person : Entity { public Address HomeAddress; public List<Order> Orders; }
  public class Address { public string City; public string Street; public int House; }
  public class Order : Entity { public List<OrderLine> Lines; public Person Customer; public Money Total; }
  public class OrderLine { public Product Item; public int Quantity; public Money Price; }
  public class Product : Entity { public Money Price; public Category Kind; }
  public class Category : Entity { public Category Parent; }
  public class Money { public decimal Amount; public string Currency; }
  public class PersonRepository : IRepository { public void Save(Entity e) {} public Person Find(int id) { return null; } }
  public class OrderRepository : IRepository { public void Save(Entity e) {} public Order Find(int id) { return null; } }
  public class ProductRepository : IRepository { public void Save(Entity e) {} public Product Find(int id) { return null; } }
  public class OrderService { public OrderRepository Orders; public ProductRepository Products;
                              public Order Create(Person p, List<Product> items) { return null; } }
  public class ReportService { public OrderService Orders;
                               public string BuildMonthlyReport(Person customer, Money limit) { return null; } }
  public class Application { public OrderService Service; public ReportService Reports; public PersonRepository People; }
}
"""

CPP_SHAPES = """
class RenderContext { public: void set_color(const std::string& name); private: std::string color_; };
class Shape { public: virtual double area() const = 0; virtual ~Shape(); };
class Circle : public Shape { public: double area() const override; private: double radius_; };
class Square : public Shape { public: double area() const override; private: double side_; };
class Triangle : public Shape { public: double area() const override; private: double a_; double b_; double c_; };
class Group : public Shape { public: double area() const override; private: std::vector<std::shared_ptr<Shape>> kids_; };
class Canvas { public: void draw(const Shape& s, const RenderContext& ctx);
               private: std::vector<std::unique_ptr<Shape>> shapes_; RenderContext* ctx_; };
"""

# много интерфейсов с общими потомками: в одном коридоре несколько точек слияния
CS_MANY_JUNCTIONS = "\n".join(
    [f"public interface I{i} {{ void M{i}(); }}" for i in range(6)]
    + [f"public class C{i}{k} : I{i} {{ public void M{i}() {{}} public int Field{k}; }}"
       for i in range(6) for k in range(3)])

# те же интерфейсы, но потомки идут вперемешку: размахи стволов перекрываются, и
# точки слияния встают этажами — зазор под рядом должен вырасти под все этажи
CS_INTERLEAVED_JUNCTIONS = "\n".join(
    [f"public interface J{i} {{ void N{i}(); }}" for i in range(9)]
    + [f"public class K{j:02d} : J{j % 9} {{ public void N{j % 9}() {{}} public int G{j}; }}"
       for j in range(27)])

# длинная цепочка наследования: рядов много, и родитель каждого — на ряд выше
PY_DEEP_CHAIN = "class L0:\n    pass\n" + "".join(
    f"class L{i}(L{i - 1}):\n"
    f"    def __init__(self):\n"
    f"        self.back: L0 = None\n"
    f"        self.peer: L{max(0, i - 2)} = None\n"
    for i in range(1, 11))

# блоки шире ряда: раскладка обязана перенести ряд, а не сжать блоки
CS_WIDE_ROWS = "\n".join(
    f"public class VeryLongDomainEntityName{i} {{ "
    f"public Dictionary<string, List<VeryLongDomainEntityName{(i + 1) % 12}>> IndexOfRelated{i}; "
    f"public string ComputeSomethingVeryImportantAndLong{i}"
    f"(Dictionary<string,int> a, List<string> b) {{ return null; }} }}"
    for i in range(12))

# двенадцать коллекций одного класса: столько же подписей «0..*» у одного блока
CS_LABEL_CROWD = "public class Hub { public int Id; }\n" + "\n".join(
    f"public class Spoke{i} {{ public List<Hub> Items; public int N{i}; }}" for i in range(12))

PY_OBJECTS_LONG_VALUES = '''
class Configuration:
    def __init__(self, path, options):
        self.path = path
        self.options = options

class Server:
    def __init__(self, cfg, name):
        self.cfg = cfg
        self.name = name

cfg = Configuration("/very/long/path/to/the/configuration/file/on/disk.yaml",
                    {"retries": 5, "timeout": 30, "verbose": True})
first = Server(cfg, "primary-application-server-node-01.internal.example.org")
second = Server(cfg, "secondary-application-server-node-02.internal.example.org")
third = Server(cfg, "tertiary-application-server-node-03.internal.example.org")
'''

CS_OBJECTS = """
class Engine { public int Power; public Engine(int p) { Power = p; } }
class Car { public string Name; public Engine Motor;
            public Car(string n, Engine e) { Name = n; Motor = e; } }
class Program {
  static void Main() {
    var motor = new Engine(150);
    var car = new Car("very-long-model-name-for-the-test", motor);
    var spare = new Car("another-long-model-name-here", motor);
  }
}
"""

CPP_OBJECTS = """
struct Engine { int power; };
struct Car { std::string name; Engine* motor; };
int main() {
    Engine e{150};
    Car a{"very-long-model-name-for-the-test", &e};
    Car b{"another-long-model-name-here", &e};
}
"""


def _class_diagrams() -> dict[str, str]:
    return {
        "python: класс с 30 методами и длинными сигнатурами":
            build_xml(extract_py(PY_MANY_METHODS)),
        "csharp: 15 классов, наследование и композиция":
            build_xml(extract_cs(CS_FIFTEEN)),
        "cpp: иерархия фигур и владение":
            build_xml(extract_cpp(CPP_SHAPES)),
        "csharp: шесть интерфейсов с потомками":
            build_xml(extract_cs(CS_MANY_JUNCTIONS)),
        "python: цепочка наследования на десять уровней":
            build_xml(extract_py(PY_DEEP_CHAIN)),
        "csharp: блоки шире ряда, ряд переносится":
            build_xml(extract_cs(CS_WIDE_ROWS)),
        "csharp: двенадцать кратностей у одного блока":
            build_xml(extract_cs(CS_LABEL_CROWD)),
        "csharp: девять интерфейсов, потомки вперемешку":
            build_xml(extract_cs(CS_INTERLEAVED_JUNCTIONS)),
    }


def _object_diagrams() -> dict[str, str]:
    return {
        "python: объекты с длинными значениями слотов":
            objektis.build_xml(objektis.extract_objects(PY_OBJECTS_LONG_VALUES, "python")),
        "csharp: объекты из Main()":
            objektis.build_xml(objektis.extract_objects(CS_OBJECTS, "csharp")),
        "cpp: объекты из main()":
            objektis.build_xml(objektis.extract_objects(CPP_OBJECTS, "cpp")),
    }


def _diagrams() -> dict[str, str]:
    return {**_class_diagrams(), **_object_diagrams()}


# ── Рамки не пересекаются ─────────────────────────────────────────────────────

def test_nodes_do_not_overlap():
    """Ни один блок не наезжает на другой — ни на диаграмме классов, ни объектов."""
    for name, xml in _diagrams().items():
        nodes, _ = boxes_from_xml(xml)
        assert len(nodes) >= 2, name
        assert find_overlaps(nodes) == [], name


def test_nodes_keep_gap():
    """Между блоками остаётся зазор: соприкасающиеся рамки читаются как один блок."""
    gap = min(get_layout()["h_gap"], get_layout()["v_gap"]) // 4
    for name, xml in _diagrams().items():
        nodes, _ = boxes_from_xml(xml)
        # точки слияния живут в коридоре между рядами и меряются отдельно
        blocks = {k: v for k, v in nodes.items() if v[2] > 20}
        assert find_overlaps(blocks, gap) == [], name


def test_edge_labels_are_not_on_blocks():
    """Кратности и имена полей стоят рядом с линией, но не поверх блоков."""
    for name, xml in _diagrams().items():
        nodes, labels = boxes_from_xml(xml)
        hits = [(lid, nid) for lid, lb in labels.items()
                for nid, nb in nodes.items() if overlap(lb, nb)]
        assert hits == [], f"{name}: {hits}"


def test_edge_labels_do_not_stack():
    """Две подписи не ложатся одна на другую — иначе не прочитать ни ту, ни другую."""
    for name, xml in _diagrams().items():
        _, labels = boxes_from_xml(xml)
        assert find_overlaps(labels) == [], name


def test_edges_do_not_cross_blocks():
    """Линия связи обходит чужие блоки, а не проходит сквозь них."""
    for name, xml in _diagrams().items():
        assert find_crossings(xml) == [], f"{name}: {find_crossings(xml)}"


def test_object_diagram_has_labels_to_place():
    """Проверка подписей не холостая: на диаграмме объектов они есть."""
    for name, xml in _object_diagrams().items():
        _, labels = boxes_from_xml(xml)
        assert labels, name


# ── Читаемость: диаграмма растёт, шрифт не мельчает ───────────────────────────

def test_font_size_does_not_shrink_with_diagram():
    """
    Сторож «слишком мелко»: от роста диаграммы шрифт не уменьшается.

    Место под содержимое даёт холст, а не масштаб текста, — иначе большая
    диаграмма превращается в нечитаемую сетку из серых полосок.
    """
    cfg = get_layout()
    small = build_xml(extract_cs("public class A { public int X; }"))
    big = build_xml(extract_cs(CS_MANY_JUNCTIONS))
    for xml in (small, big):
        assert f'fontSize={cfg["header_font"]};' in xml
        assert f'fontSize={cfg["member_font"]};' in xml
    small_nodes, _ = boxes_from_xml(small)
    big_nodes, _ = boxes_from_xml(big)
    def area(nodes):
        xs = [b[0] + b[2] for b in nodes.values()]
        ys = [b[1] + b[3] for b in nodes.values()]
        return max(xs) * max(ys)
    assert area(big_nodes) > area(small_nodes)


def test_block_is_wide_enough_for_its_longest_row():
    """Ширина блока считается по самой длинной строке, а не по шагу сетки."""
    from uml_generator._text import text_width
    cfg = get_layout()
    classes = extract_py(PY_MANY_METHODS)
    from uml_generator.builder import _class_width, _member_rows
    for cls in classes:
        fields, methods = _member_rows(cls)
        longest = max([text_width(t, cfg["member_font"]) for t, _, _ in fields + methods]
                      + [text_width(cls.display_name, cfg["header_font"], bold=True)])
        assert _class_width(cls, cfg) >= longest + 10


def test_interface_header_holds_two_lines():
    """
    У «interface» заголовок в две строки: стереотип и имя.

    С прежней постоянной высотой имя выезжало из шапки на первую строку членов.
    """
    from uml_generator.builder import _header_h
    cfg = get_layout()
    iface = extract_cs("public interface IThing { void Do(); }")[0]
    plain = extract_cs("public class Thing { public void Do() {} }")[0]
    assert _header_h(iface, cfg) >= 2 * cfg["header_font"]
    assert _header_h(iface, cfg) > _header_h(plain, cfg)
    xml = build_xml([iface])
    assert f'startSize={_header_h(iface, cfg)};' in xml
    # первая строка членов начинается ниже шапки
    assert f'<mxGeometry y="{_header_h(iface, cfg)}"' in xml


# ── Измеритель не холостой ────────────────────────────────────────────────────

_OVERLAPPING_XML = """<?xml version="1.0" encoding="UTF-8"?>
<mxGraphModel><root>
<mxCell id="0"/><mxCell id="1" parent="0"/>
<mxCell id="a" value="A" style="swimlane;" vertex="1" parent="1">
  <mxGeometry x="0" y="0" width="200" height="100" as="geometry"/></mxCell>
<mxCell id="b" value="B" style="swimlane;" vertex="1" parent="1">
  <mxGeometry x="100" y="50" width="200" height="100" as="geometry"/></mxCell>
<mxCell id="e" value="" style="edgeStyle=orthogonalEdgeStyle;exitX=0.5;exitY=1.0;entryX=0.5;entryY=0.0;"
  edge="1" source="a" target="b" parent="1"><mxGeometry relative="1" as="geometry"/></mxCell>
<mxCell id="e_l" value="0..*" style="edgeLabel;fontSize=10;" vertex="1" connectable="0" parent="e">
  <mxGeometry x="1" relative="1" as="geometry"><mxPoint x="0" y="0" as="offset"/></mxGeometry></mxCell>
</root></mxGraphModel>"""


def test_checker_sees_a_real_overlap():
    """
    Проверки выше стоят ровно столько, сколько стоит измеритель: на заведомо
    наложенной диаграмме он обязан найти и наложение блоков, и подпись на блоке.

    Без этого набор тестов проходил бы и на пустом разборе XML.
    """
    nodes, labels = boxes_from_xml(_OVERLAPPING_XML)
    assert set(nodes) == {"a", "b"}
    assert find_overlaps(nodes)
    assert labels, "подпись ребра не разобрана"
    assert any(overlap(lb, nb) for lb in labels.values() for nb in nodes.values())


def test_every_class_becomes_a_measured_box():
    """Все блоки диаграммы попали в измерение: пропущенный не проверить на наезд."""
    for src, extract in ((CS_FIFTEEN, extract_cs), (CPP_SHAPES, extract_cpp)):
        classes = extract(src)
        nodes, _ = boxes_from_xml(build_xml(classes))
        # кроме блоков в разборе есть точки слияния — их ширина мала
        blocks = [b for b in nodes.values() if b[2] > 20]
        assert len(blocks) == len(classes)


# ── Читаемость: содержимое умещается в рамке ──────────────────────────────────

def test_block_holds_all_its_rows():
    """
    Высота блока вмещает заголовок и все строки: место даёт рамка, а не сжатие
    строк. Иначе последние методы вылезали бы за низ блока — на соседа.
    """
    from uml_generator.builder import _class_height, _header_h, _member_rows
    cfg = get_layout()
    for src, extract in ((PY_MANY_METHODS, extract_py), (CS_FIFTEEN, extract_cs)):
        for cls in extract(src):
            fields, methods = _member_rows(cls)
            need = _header_h(cls, cfg) + (len(fields) + len(methods)) * cfg["row_h"]
            if fields and methods:
                need += cfg["sep_h"]
            assert _class_height(cls, cfg) >= need, cls.display_name


def test_row_height_fits_the_font():
    """Строка члена выше своего шрифта: иначе соседние строки слипаются."""
    cfg = get_layout()
    assert cfg["row_h"] >= cfg["member_font"] * 1.4
    assert cfg["header_h"] >= cfg["header_font"] * 1.4


def test_junctions_stay_in_the_corridor():
    """
    Точка слияния наследования лежит в зазоре между рядами, а не в полосе блоков.

    Точек в одном коридоре бывает несколько (у каждого родителя своя), и вторая
    и следующие встают этажами ниже. Пока зазор под рядом был постоянным, нижние
    этажи опускались в полосу следующего ряда: точка либо садилась на блок, либо
    вставала вплотную к нему — какой из двух случаев, зависело от того, совпали
    ли они по x. Зазор считается по числу этажей, поэтому не должно быть ни того,
    ни другого.
    """
    seen = 0
    for name, xml in _class_diagrams().items():
        nodes, _ = boxes_from_xml(xml)
        blocks = [b for b in nodes.values() if b[2] > 20]
        dots = [b for b in nodes.values() if b[2] <= 20]
        seen += len(dots)
        bands = {(b[1], b[1] + b[3]) for b in blocks}
        for d in dots:
            for top, bottom in bands:
                assert d[1] + d[3] <= top or d[1] >= bottom, f"{name}: {d} в полосе {top}..{bottom}"
    assert seen, "образцов с точками слияния нет — проверка холостая"
