"""
Тесты builder'а по сценариям слияния стрелок наследования (junction):
несколько потомков одного родителя → один «ствол» к родителю и ветки от потомков.
Запуск: python -m pytest tests/uml_generator
Выходные XML пишутся рядом (в .gitignore) — открыть в draw.io для визуальной проверки.
"""
import os

from uml_generator.extractor import extract_cs, extract_cpp
from uml_generator.builder import build_xml

_OUT = os.path.dirname(os.path.abspath(__file__))


def _save(name: str, xml: str) -> str:
    path = os.path.join(_OUT, f"test_{name}.xml")
    with open(path, "w", encoding="utf-8") as f:
        f.write(xml)
    return path


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
    classes = extract_cs(CS_MERGE)
    assert len(classes) == 4, f"4 класса (Shape + 3 потомка), got {len(classes)}"

    xml = build_xml(classes)
    _save("merge_3children", xml)

    junctions = xml.count('ellipse;whiteSpace')
    trunks    = xml.count('id="jt')
    branches  = xml.count('endArrow=none;startArrow=none')

    assert junctions == 1, f"1 junction, got {junctions}"
    assert trunks    == 1, f"1 trunk,    got {trunks}"
    assert branches  == 3, f"3 branches, got {branches}"


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
    classes = extract_cs(CS_TWO_PARENTS)
    assert len(classes) == 6, f"6 классов, got {len(classes)}"

    xml = build_xml(classes)
    _save("merge_2interfaces", xml)

    junctions = xml.count('ellipse;whiteSpace')
    trunks    = xml.count('id="jt')
    branches  = xml.count('endArrow=none;startArrow=none')

    assert junctions == 2, f"2 junctions, got {junctions}"
    assert trunks    == 2, f"2 trunks,    got {trunks}"
    assert branches  == 4, f"4 branches,  got {branches}"


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
    classes = extract_cs(CS_SINGLE)
    xml = build_xml(classes)
    _save("no_merge_single", xml)

    junctions = xml.count('ellipse;whiteSpace')
    normal    = xml.count('endArrow=block')

    assert junctions == 0, f"0 junctions, got {junctions}"
    assert normal    == 1, f"1 обычная стрелка, got {normal}"


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
    classes = extract_cs(CS_MIXED)
    assert len(classes) == 6, f"6 классов, got {len(classes)}"

    xml = build_xml(classes)
    _save("mixed", xml)

    junctions = xml.count('ellipse;whiteSpace')
    assert junctions >= 1, f"минимум 1 junction, got {junctions}"


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
    classes = extract_cpp(CPP_MERGE)
    assert len(classes) == 4, f"4 класса, got {len(classes)}"

    xml = build_xml(classes)
    _save("cpp_merge", xml)

    junctions = xml.count('ellipse;whiteSpace')
    branches  = xml.count('endArrow=none;startArrow=none')

    assert junctions == 1, f"1 junction, got {junctions}"
    assert branches  == 3, f"3 branches, got {branches}"


# ── 6. Граничные случаи ───────────────────────────────────────────────────────

def test_empty():
    xml = build_xml([])
    assert '<mxCell id="0"' in xml, "пустой XML содержит базовые ячейки"

    classes = extract_cs("public class Alone { private int x; }")
    xml = build_xml(classes)
    assert xml.count('ellipse;whiteSpace') == 0, "одиночный класс — без junction"


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
            failed += 1
    if failed:
        sys.exit(1)
