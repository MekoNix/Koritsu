"""
Тесты UML Generator (бывш. klassis): extractor + builder.
Запуск: python -m pytest tests/uml_generator
Выходные XML открываются в draw.io для визуальной проверки.
"""
import os, sys

_PACKAGES = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), 'packages')
if _PACKAGES not in sys.path:
    sys.path.insert(0, _PACKAGES)

from uml_generator.extractor import extract_cs, extract_cpp
from uml_generator.builder import build_xml

try:
    from uml_generator._ts import get_parser as _
    _HAS_TSL = True
except ImportError:
    _HAS_TSL = False

def _skip_if_no_tsl():
    if not _HAS_TSL:
        raise RuntimeError("SKIP: tree-sitter-languages не установлен")

_OUT = os.path.dirname(os.path.abspath(__file__))

def _save(name: str, xml: str) -> str:
    path = os.path.join(_OUT, f"test_{name}.xml")
    with open(path, "w", encoding="utf-8") as f:
        f.write(xml)
    return path


def _assert(cond: bool, msg: str):
    if not cond:
        raise AssertionError(msg)
    print(f"  OK  {msg}")


# ── 1. Merge: 3 потомка одного родителя ───────────────────────────────────────

CS_MERGE = """
using System;

public abstract class Shape {
    protected string Color;
    public abstract double Area();
    public abstract double Perimeter();
}

public class Circle : Shape {
    private double Radius;
    public Circle(double radius) {}
    public override double Area() { return 0; }
    public override double Perimeter() { return 0; }
}

public class Rectangle : Shape {
    private double Width;
    private double Height;
    public Rectangle(double w, double h) {}
    public override double Area() { return 0; }
    public override double Perimeter() { return 0; }
}

public class Triangle : Shape {
    private double A;
    private double B;
    private double C;
    public Triangle(double a, double b, double c) {}
    public override double Area() { return 0; }
    public override double Perimeter() { return 0; }
}
"""

def test_merge_three_children():
    _skip_if_no_tsl()
    print("\n[1] Merge: 3 потомка Shape")
    classes = extract_cs(CS_MERGE)
    _assert(len(classes) == 4, f"4 класса (Shape + 3 потомка), got {len(classes)}")

    xml = build_xml(classes)
    path = _save("merge_3children", xml)

    junctions = xml.count('ellipse;whiteSpace')
    trunks    = xml.count('id="jt')
    branches  = xml.count('endArrow=none;startArrow=none')

    _assert(junctions == 1, f"1 junction, got {junctions}")
    _assert(trunks    == 1, f"1 trunk,    got {trunks}")
    _assert(branches  == 3, f"3 branches, got {branches}")
    print(f"  XML → {path}")


# ── 2. Merge: два родителя, у каждого по 2 потомка ───────────────────────────

CS_TWO_PARENTS = """
public interface IDrawable {
    void Draw();
}

public interface IResizable {
    void Resize(double factor);
}

public class VectorShape : IDrawable {
    public void Draw() {}
}

public class RasterShape : IDrawable {
    public void Draw() {}
}

public class ScalableVector : IResizable {
    public void Resize(double factor) {}
}

public class ScalableRaster : IResizable {
    public void Resize(double factor) {}
}
"""

def test_merge_two_interfaces():
    print("\n[2] Merge: 2 интерфейса × 2 потомка каждый")
    classes = extract_cs(CS_TWO_PARENTS)
    _assert(len(classes) == 6, f"6 классов, got {len(classes)}")

    xml = build_xml(classes)
    path = _save("merge_2interfaces", xml)

    junctions = xml.count('ellipse;whiteSpace')
    trunks    = xml.count('id="jt')
    branches  = xml.count('endArrow=none;startArrow=none')

    _assert(junctions == 2, f"2 junctions, got {junctions}")
    _assert(trunks    == 2, f"2 trunks,    got {trunks}")
    _assert(branches  == 4, f"4 branches,  got {branches}")
    print(f"  XML → {path}")


# ── 3. Одиночное наследование — merge НЕ должен срабатывать ──────────────────

CS_SINGLE = """
public class Vehicle {
    protected int Speed;
    public void Move() {}
}

public class Car : Vehicle {
    private int Doors;
    public void Honk() {}
}
"""

def test_no_merge_single():
    print("\n[3] Одиночное наследование — без merge")
    classes = extract_cs(CS_SINGLE)
    xml = build_xml(classes)
    path = _save("no_merge_single", xml)

    junctions = xml.count('ellipse;whiteSpace')
    normal    = xml.count('endArrow=block')

    _assert(junctions == 0, f"0 junctions, got {junctions}")
    _assert(normal    == 1, f"1 обычная стрелка, got {normal}")
    print(f"  XML → {path}")


# ── 4. Смешанный граф: merge + composition + dependency ───────────────────────

CS_MIXED = """
public interface ILogger {
    void Log(string msg);
}

public abstract class Service {
    protected ILogger Logger;
    public abstract void Execute();
}

public class OrderService : Service {
    private PaymentService Payment;
    public override void Execute() {}
}

public class PaymentService : Service {
    public override void Execute() {}
    public void Charge(OrderService order) {}
}

public class FileLogger : ILogger {
    public void Log(string msg) {}
}

public class ConsoleLogger : ILogger {
    public void Log(string msg) {}
}
"""

def test_mixed_graph():
    print("\n[4] Смешанный граф")
    classes = extract_cs(CS_MIXED)
    _assert(len(classes) == 6, f"6 классов, got {len(classes)}")

    xml = build_xml(classes)
    path = _save("mixed", xml)

    junctions = xml.count('ellipse;whiteSpace')
    _assert(junctions >= 1, f"минимум 1 junction, got {junctions}")
    print(f"  XML → {path}")


# ── 5. C++: merge наследования ────────────────────────────────────────────────

CPP_MERGE = """
class Animal {
public:
    std::string name;
    virtual void speak() = 0;
    virtual void move() = 0;
};

class Dog : public Animal {
private:
    int age;
public:
    Dog(int a);
    void speak() override;
    void move() override;
    void fetch();
};

class Cat : public Animal {
private:
    bool indoor;
public:
    Cat(bool i);
    void speak() override;
    void move() override;
    void purr();
};

class Bird : public Animal {
private:
    double wingspan;
public:
    Bird(double w);
    void speak() override;
    void move() override;
    void fly();
};
"""

def test_cpp_merge():
    print("\n[5] C++: 3 потомка Animal")
    classes = extract_cpp(CPP_MERGE)
    _assert(len(classes) == 4, f"4 класса, got {len(classes)}")

    xml = build_xml(classes)
    path = _save("cpp_merge", xml)

    junctions = xml.count('ellipse;whiteSpace')
    branches  = xml.count('endArrow=none;startArrow=none')

    _assert(junctions == 1, f"1 junction, got {junctions}")
    _assert(branches  == 3, f"3 branches, got {branches}")
    print(f"  XML → {path}")


# ── 6. Граничные случаи ───────────────────────────────────────────────────────

def test_empty():
    print("\n[6] Граничные случаи")
    xml = build_xml([])
    _assert('<mxCell id="0"' in xml, "пустой XML содержит базовые ячейки")
    print("  OK  empty classes")

    classes = extract_cs("public class Alone { private int x; }")
    xml = build_xml(classes)
    _assert(xml.count('ellipse;whiteSpace') == 0, "одиночный класс — без junction")
    print("  OK  single class no junction")


# ── Runner ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    tests = [
        test_merge_three_children,
        test_merge_two_interfaces,
        test_no_merge_single,
        test_mixed_graph,
        test_cpp_merge,
        test_empty,
    ]
    passed = failed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except Exception as e:
            print(f"  FAIL  {e}")
            failed += 1

    print(f"\n{'='*40}")
    print(f"Passed: {passed}/{passed+failed}")
    if failed:
        sys.exit(1)
