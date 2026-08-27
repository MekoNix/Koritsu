"""
objektis — UML Object Diagram (диаграмма объектов) из исходного кода.

Дополняет диаграмму классов: там структура типов, здесь снимок конкретных
экземпляров с заполненными слотами и связями между ними.

Правило: пользовательский код не выполняется. Бэкенды — только статические:
  python → py_static  (модуль / `__main__` / вызванная main())
  csharp → cs_static  (тело Main())
  cpp    → cpp_static (тело main())
Общее состояние трассировки — _trace.py.
IR (model.py) и builder.py принимают любой ObjectGraph.
"""
from .model import ObjectGraph, ObjectInstance, ObjectLink, Slot
from .builder import build_xml
from ._facade import extract_objects


__all__ = [
    "ObjectGraph", "ObjectInstance", "ObjectLink", "Slot",
    "extract_objects", "build_xml",
]
