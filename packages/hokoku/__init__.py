"""
hokoku (報告 — «отчёт») — отчёты из DOCX-шаблонов с тегами {{ключ}} / {{ключ:подсказка}}.

  extract_tags(template)                 → [Tag]  — теги отовсюду: тело, таблицы,
                                            колонтитулы, текстовые поля
  render(template, values, out)          → RenderResult — подстановка значений
  docx_to_pdf(docx, pdf)                 → PDF через LibreOffice (если установлен)
  validate_docx(source)                  → защита от zip-slip / zip-bomb / XXE / макросов VBA
  build_report(job, …)                   → задание JSON → отчёт и результат JSON (wire.py)
  manifest_from_template(template)       → манифест шаблона: тип и промпт на каждый тег
  manifest_schema(manifest)              → JSON Schema всего ответа: {ключ тега: схема типа}
  validate(template, values, manifest)   → [проблема] до сборки: типы, лимиты, {ref:} в никуда

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
from .pdf import docx_bytes_to_pdf, docx_to_pdf
from .wire import (VALUE_TYPES, WIRE_VERSION, WireError, value_from_json, value_schema,
                   value_to_json, values_from_json, values_to_json)
from .manifest import (LIMIT_KEYS, MANIFEST_TYPES, Manifest, ManifestError, TagSpec,
                       check_manifest, default_spec, manifest_from_json,
                       manifest_from_template, manifest_prompt, manifest_schema,
                       manifest_to_json, suggest_type)
from .report import build_report
from .validate import validate

__all__ = [
    "Text", "Markdown", "Code", "Image", "Diagram", "Table", "Formula", "Toc", "Blocks", "PageBreak", "Value",
    "Tag", "RenderResult", "HokokuError",
    "extract_tags", "render", "docx_to_pdf", "docx_bytes_to_pdf",
    "validate_docx", "DocxValidationError", "safe_name",
    "WIRE_VERSION", "VALUE_TYPES", "WireError", "value_from_json", "value_to_json",
    "values_from_json", "values_to_json", "value_schema", "build_report",
    "Manifest", "TagSpec", "ManifestError", "MANIFEST_TYPES", "LIMIT_KEYS",
    "manifest_from_template", "manifest_from_json", "manifest_to_json", "check_manifest",
    "manifest_prompt", "manifest_schema", "suggest_type", "default_spec", "validate",
]
