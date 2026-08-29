"""Отрисовка диаграммы классов: подписи членов, одноимённые классы, порты рёбер."""
import re

from uml_generator.extractor import extract_cpp, extract_cs
from uml_generator.builder import build_xml, _method_text


def _class_cells(xml):
    return re.findall(r'<mxCell id="(c\d+)" value="([^"]*)"', xml)


def _edges(xml):
    """[(id, source, target, exitX, exitY)] для всех рёбер XML."""
    out = []
    for eid, style, src, tgt in re.findall(
            r'<mxCell id="(\w+)" value="" style="([^"]*)"[^>]*edge="1" '
            r'source="(\w+)" target="(\w+)"', xml):
        m = re.search(r'exitX=([\d.]+);exitY=([\d.]+)', style)
        out.append((eid, src, tgt, m.group(1), m.group(2)) if m else (eid, src, tgt, "", ""))
    return out


def test_cpp_const_method_not_glued_to_return_type():
    """Было `+ name(): const std::string& const` — const читался как часть типа."""
    b = extract_cpp("class Box { public: const std::string& name() const; };")[0]
    assert _method_text(b.methods[0]) == "+ name() const: const std::string&"


def test_same_name_classes_get_own_cells():
    """`namespace N1 { class Prim }` и `N2.Prim` — две ячейки, а не одна поверх другой."""
    xml = build_xml(extract_cs(
        "namespace N1 { class Prim { public int A; } }\n"
        "namespace N2 { class Prim { public string B; } }\n"))
    cells = _class_cells(xml)
    assert len(cells) == 2
    assert len({cid for cid, _ in cells}) == 2, "id ячеек должны различаться"
    geoms = re.findall(r'<mxGeometry x="(\d+)" y="(\d+)"', xml)
    assert len(set(geoms)) == 2, "блоки не должны лежать друг на друге"


def test_partial_class_is_merged():
    classes = extract_cs(
        "partial class Doc { public int A; public void Open() {} }\n"
        "partial class Doc : IFile { public string B; public void Save() {} }\n")
    assert len(classes) == 1
    doc = classes[0]
    assert [f.name for f in doc.fields] == ["A", "B"]
    assert [m.name for m in doc.methods] == ["Open", "Save"]
    assert doc.parents == ["IFile"]


def test_multiple_inheritance_branch_and_edge_do_not_share_port():
    """C : A, B, у A ещё потомок D — ветка к junction и ребро к B выходят из разных точек."""
    xml = build_xml(extract_cpp("""
        class A { public: void a(); };
        class B { public: void b(); };
        class C : public A, protected B { public: void c(); };
        class D : public A { public: void d(); };
    """))
    ids = dict(_class_cells(xml))
    c_id = next(cid for cid, val in ids.items() if val == "C")
    exits = [(eid, ex, ey) for eid, src, _t, ex, ey in _edges(xml) if src == c_id]
    assert len(exits) == 2, f"у C два исходящих ребра, got {exits}"
    assert len({(ex, ey) for _e, ex, ey in exits}) == 2, f"порты совпали: {exits}"
