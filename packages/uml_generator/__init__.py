"""
UML Generator (бывш. klassis) — генерация UML-диаграмм классов и объектов
в формате draw.io из исходного кода.

  extract_cs / extract_cpp — извлечение классов из C# / C++ (tree-sitter)
  build_xml                — диаграмма классов → draw.io XML
  objektis                 — диаграммы объектов (динамический дамп Python / C#)

Самостоятельный модуль: не зависит от fragmos.
"""

from .extractor import extract_cpp, extract_cs
from .builder import build_xml

__all__ = ["extract_cpp", "extract_cs", "build_xml"]
