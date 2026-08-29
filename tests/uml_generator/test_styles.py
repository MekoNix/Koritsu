"""
Тема `css`: цвета пишутся ролями `var(--роль, светлый-hex)`.

Одна схема годится и в интерфейс, и в отчёт: в SVG роль выносится наружу
дословно (страница красит её своей темой), в PNG CSS-контекста нет и рисуется
запасной цвет — то есть светлая палитра. Проверено экспортом через drawio CLI:
PNG темы `css` побайтно совпадает с PNG темы `light`.
"""
import re
import xml.etree.ElementTree as ET

import pytest

from uml_generator.builder import build_xml
from uml_generator.extractor import extract_cs
from uml_generator.objektis import ObjectGraph, ObjectInstance, ObjectLink, Slot
from uml_generator.objektis import build_xml as build_obj_xml
from uml_generator.styles import _load, get_theme

CLASSES = extract_cs(
    "interface ILog { void Log(string s); }\n"
    "enum Kind { A, B }\n"
    "class Task { public Kind K; }\n"
    "class Manager : ILog { public List<Task> Tasks; public void Log(string s) {} }\n")


def _roles(xml):
    return set(re.findall(r'var\((--[a-z-]+),', xml))


def test_every_palette_key_has_a_role():
    """Роль нужна каждому ключу палитры, иначе тема `css` уронит builder на KeyError."""
    data = _load()
    for name, palette in data["themes"].items():
        assert set(palette) == set(data["roles"]), f"тема {name} разошлась с roles"


def test_css_fallback_is_exactly_the_light_palette():
    light, css, roles = get_theme("light"), get_theme("css"), _load()["roles"]
    for key, role in roles.items():
        if isinstance(role, dict):
            for sub, var in role.items():
                assert css[key][sub] == f"var(--{var},{light[key][sub]})"
        else:
            assert css[key] == f"var(--{role},{light[key]})"


def test_unknown_theme_lists_css():
    with pytest.raises(ValueError, match="css"):
        get_theme("phosphor")


def test_class_diagram_in_roles():
    css, light = build_xml(CLASSES, theme="css"), build_xml(CLASSES, theme="light")
    assert build_xml(CLASSES) == build_xml(CLASSES, theme="dark"), "умолчание не менялось"
    assert "var(" not in light, "светлая и тёмная темы остались на hex"
    assert "fillColor=var(--node-fill,#ffffff);" in css
    assert "strokeColor=var(--node-accent-line,#4f46e5);" in css   # интерфейс
    assert "fillColor=var(--node-alt-fill,#f0f9ff);" in css        # enum
    assert _roles(css) >= {"--node-fill", "--node-line", "--node-text",
                           "--node-text-muted", "--edge", "--edge-label"}
    ET.fromstring(css)                        # роль с запятой не ломает XML и style


def test_object_diagram_in_roles():
    graph = ObjectGraph(
        instances=[ObjectInstance("car", "Car", [Slot("engine", "→ engine1")]),
                   ObjectInstance("engine1", "Engine", [Slot("power", "150")])],
        links=[ObjectLink("car", "engine1", "engine", "containment")])
    css = build_obj_xml(graph, theme="css")
    assert _roles(css) >= {"--node-fill", "--node-line", "--node-text",
                           "--node-text-muted", "--edge-alt"}
    ET.fromstring(css)
