"""
hokoku (報告 — «отчёт») — отчёты из DOCX-шаблонов с тегами {{ключ}} / {{ключ:подсказка}}.

  extract_tags(template)                 → [Tag]  — теги отовсюду: тело, таблицы,
                                            колонтитулы, текстовые поля
  render(template, values, out)          → RenderResult — подстановка значений
  docx_to_pdf(docx, pdf)                 → PDF через LibreOffice (если установлен)
  validate_docx(source)                  → защита от zip-slip / zip-bomb / XXE / макросов VBA

Значения — типизированные (model.py): Text, Markdown, Code, Image, Diagram, Table, Formula, Toc, Blocks, PageBreak.
Оформление — styles.yaml (render(..., style={...}) перегружает).
Inline-значения подставляются внутрь runs, не трогая форматирование соседей;
блочные — новыми абзацами после абзаца с тегом.
"""
from .model import (Blocks, Code, Diagram, Formula, Image, Markdown, PageBreak, RenderResult, Table, Tag,
                    Text, Toc, HokokuError, Value)
from .tags import extract_tags
from .render import render
from .safety import validate_docx, DocxValidationError, safe_name
from .pdf import docx_to_pdf

__all__ = [
    "Text", "Markdown", "Code", "Image", "Diagram", "Table", "Formula", "Toc", "Blocks", "PageBreak", "Value",
    "Tag", "RenderResult", "HokokuError",
    "extract_tags", "render", "docx_to_pdf",
    "validate_docx", "DocxValidationError", "safe_name",
]
