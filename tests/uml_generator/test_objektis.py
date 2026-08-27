"""Тесты objektis: builder по готовому ObjectGraph и фасад (код не выполняется)."""
import pytest

from uml_generator.objektis import (
    ObjectGraph, ObjectInstance, ObjectLink, Slot, build_xml, extract_objects,
)
from uml_generator.objektis.builder import _collapse_collections


def _graph_two_linked():
    return ObjectGraph(
        instances=[
            ObjectInstance("car", "Car", [Slot("name", "'Audi'"), Slot("engine", "→ engine1")]),
            ObjectInstance("engine1", "Engine", [Slot("power", "150")]),
        ],
        links=[ObjectLink("car", "engine1", "engine")],
    )


def test_empty_graph_xml():
    xml = build_xml(ObjectGraph())
    assert '<mxCell id="0"' in xml and "<u>" not in xml


def test_two_objects_with_link():
    xml = build_xml(_graph_two_linked())
    assert xml.count('edge="1"') == 1
    assert "car : Car" in xml and "engine1 : Engine" in xml
    assert "name = &#x27;Audi&#x27;" in xml


def test_collapse_collections():
    g = ObjectGraph(
        instances=[ObjectInstance("m", "Manager")]
                  + [ObjectInstance(f"task{i}", "Task", [Slot("done", "False")]) for i in range(4)],
        links=[ObjectLink("m", f"task{i}", f"tasks[{i}]", "containment") for i in range(4)],
    )
    c = _collapse_collections(g)
    assert len(c.instances) == 2
    assert c.instances[1].is_summary and c.instances[1].multiplicity == "4"
    assert len(c.links) == 1 and c.links[0].label == "tasks"


def test_small_or_differing_collections_not_collapsed():
    g = ObjectGraph(
        instances=[ObjectInstance("m", "Manager")]
                  + [ObjectInstance(f"t{i}", "Task", [Slot("n", str(i))]) for i in range(4)],
        links=[ObjectLink("m", f"t{i}", f"tasks[{i}]", "containment") for i in range(4)],
    )
    assert len(_collapse_collections(g).instances) == 5      # слоты различаются
    assert len(_collapse_collections(g, 2).instances) == 5
    g2 = ObjectGraph(
        instances=[ObjectInstance("m", "Manager")]
                  + [ObjectInstance(f"t{i}", "Task", [Slot("n", "1")]) for i in range(2)],
        links=[ObjectLink("m", f"t{i}", f"tasks[{i}]", "containment") for i in range(2)],
    )
    assert len(_collapse_collections(g2).instances) == 3     # меньше порога


def test_cyclic_refs_not_collapsed():
    g = ObjectGraph(
        instances=[ObjectInstance("root", "Node"), ObjectInstance("a", "Node"), ObjectInstance("b", "Node")],
        links=[ObjectLink("root", "a", "children[0]", "containment"),
               ObjectLink("root", "b", "children[1]", "containment"),
               ObjectLink("a", "root", "parent"), ObjectLink("b", "root", "parent")],
    )
    assert len(_collapse_collections(g).instances) == 3


@pytest.mark.parametrize("lang", ["java", "go"])
def test_facade_unsupported_language_returns_note(lang):
    g = extract_objects("class Foo {}", lang)
    assert g.is_empty() and g.notes


@pytest.mark.parametrize("lang, src", [
    ("python", "import os\nclass A:\n    pass\nopen({m!r}, 'w').close()\na = A()\n"),
    ("csharp", "class A {{}} class P {{ static void Main() {{ System.IO.File.Create({m!r}); var a = new A(); }} }}"),
    ("cpp", "#include <fstream>\nstruct A {{}};\nint main() {{ std::ofstream f({m!r}); A a; return 0; }}"),
])
def test_static_backends_never_execute(lang, src, tmp_path):
    marker = str(tmp_path / "executed")
    g = extract_objects(src.format(m=marker), lang)
    assert [i.name for i in g.instances] == ["a"]
    assert not (tmp_path / "executed").exists()
