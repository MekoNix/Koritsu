"""
UML Generator (бывш. klassis) — генерация UML-диаграмм классов и объектов
в формате draw.io из исходного кода.

  extract_py / extract_cs / extract_cpp — извлечение классов (tree-sitter, без выполнения)
  build_xml                — диаграмма классов → draw.io XML
  objektis                 — диаграммы объектов (статическая трассировка; код не выполняется)

Самостоятельный модуль: не зависит от fragmos.
"""

from .extractor import extract_cpp, extract_cs, extract_py
from .builder import build_xml

__all__ = ["extract_py", "extract_cpp", "extract_cs", "build_xml"]
