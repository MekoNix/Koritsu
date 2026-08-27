"""
objektis — UML Object Diagram (диаграмма объектов) из исходного кода.

Дополняет klassis: где klassis показывает структуру типов, objektis показывает
снимок конкретных инстансов с заполненными слотами и links между ними.

Бэкенды:
  - python  → py_dynamic   (запуск кода + gc walk)
  - csharp  → cs_dynamic   (source-rewrite + run + reflection dump)  [TODO]
  - cpp     → cpp_static   (tree-sitter tracer of main())            [TODO]
"""
from .model import ObjectGraph, ObjectInstance, ObjectLink, Slot
from .builder import build_xml
from ._facade import extract_objects


__all__ = [
    "ObjectGraph", "ObjectInstance", "ObjectLink", "Slot",
    "extract_objects", "build_xml",
]
