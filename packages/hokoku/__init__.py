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
  validate(template, values, manifest)   → [Problem] до сборки: типы, лимиты, {ref:} в никуда
  blank_document()                       → Document с нуля: стили, поля, номера страниц (шаблона нет)
  check_template(template)               → [Problem] шаблона: нет стилей, полей шире листа
  style_from_sample(sample)              → StyleProfile — оформление чужого готового отчёта (не шаблона!)
  apply_style(doc, profile)              → наложить это оформление на наш документ
  outline_from_sample(sample)            → [{level, text, number}] — строение примера, не оформление

Живой режим (live.py) — работа без шаблона: упорядоченный список именованных блоков.
  Work / Block                           → список и его кусок; операции чистые, прежний список цел
  live.insert / replace / remove / move / rename → новый список, прежний цел (нужна отмена)
  assemble(work)                         → байты DOCX: тот же render, второго рисовальщика нет
  validate_work(work)                    → [Problem] до сборки: дубли ключей, лимиты, {ref:} в никуда
  live_tools() / call_tool(work, имя, …) → инструменты агента над списком (модель зовёт оркестратор)
  text_slots / texts_schema / fill_texts → связный текст одним проходом по готовому списку
Общие слова (insert, replace, remove, move, block, heading, outline, draft) наверх не
подняты намеренно: `hokoku.insert` не говорит, куда и что, а `hokoku.live.insert` говорит.

Значения — типизированные (model.py): Text, Markdown, Code, Image, Diagram, Table, Formula, Toc, Blocks, PageBreak.
Замечания — `Problem` (`kyotsu.Notice` плюс тег): одна форма на `validate`, `check_manifest`,
`check_template` и предупреждения `build_report`; в JSON уезжает `to_dict()`.
Оформление — styles.yaml (render(..., style={...}) перегружает).
Inline-значения подставляются внутрь runs, не трогая форматирование соседей;
блочные — новыми абзацами после абзаца с тегом.
"""
from .model import (Blocks, Code, Diagram, Formula, Image, Markdown, PageBreak, Problem, RenderResult,
                    Table, Tag, Text, Toc, HokokuError, Value)
from .tags import extract_tags
from .render import render
from .safety import validate_docx, DocxValidationError, safe_name
from .pdf import docx_bytes_to_pdf, docx_to_pdf
from .images import count_pages
from .wire import (VALUE_TYPES, WIRE_VERSION, WireError, value_from_json, value_schema,
                   value_to_json, values_from_json, values_to_json)
from .manifest import (LIMIT_KEYS, MANIFEST_TYPES, Manifest, ManifestError, TagSpec,
                       check_manifest, default_spec, manifest_from_json,
                       manifest_from_template, manifest_prompt, manifest_schema,
                       manifest_to_json, suggest_type)
from .report import build_report
from .validate import validate
from .template import (A4_GOST, BodyText, PageSetup, STYLE_SPECS, blank_document,
                       check_template, document_bytes, ensure_style, ensure_styles)
from . import live
from .live import (Block, KINDS, LiveError, LiveTool, TEXT_KINDS, Work, any_block_value_schema,
                   assemble, call_tool, list_blocks, live_tools, render_work, text_slots,
                   texts_schema, fill_texts, unresolved_refs, validate_work, work_template,
                   work_values)
from .sample import (HeadingLook, SampleError, StyleProfile, apply_heading_numbering,
                     apply_style, document_from_sample, outline_from_sample,
                     style_from_sample)

__all__ = [
    "Text", "Markdown", "Code", "Image", "Diagram", "Table", "Formula", "Toc", "Blocks", "PageBreak", "Value",
    "Tag", "RenderResult", "HokokuError", "Problem",
    "extract_tags", "render", "docx_to_pdf", "docx_bytes_to_pdf",
    "validate_docx", "DocxValidationError", "safe_name",
    "WIRE_VERSION", "VALUE_TYPES", "count_pages", "WireError", "value_from_json", "value_to_json",
    "values_from_json", "values_to_json", "value_schema", "build_report",
    "Manifest", "TagSpec", "ManifestError", "MANIFEST_TYPES", "LIMIT_KEYS",
    "manifest_from_template", "manifest_from_json", "manifest_to_json", "check_manifest",
    "manifest_prompt", "manifest_schema", "suggest_type", "default_spec", "validate",
    "blank_document", "check_template", "ensure_style", "ensure_styles", "document_bytes",
    "PageSetup", "BodyText", "A4_GOST", "STYLE_SPECS",
    "style_from_sample", "apply_style", "apply_heading_numbering", "document_from_sample",
    "outline_from_sample", "StyleProfile", "HeadingLook", "SampleError",
    "live", "Work", "Block", "LiveTool", "LiveError", "KINDS", "TEXT_KINDS",
    "work_values", "work_template", "render_work", "assemble",
    "validate_work", "unresolved_refs",
    "live_tools", "call_tool", "list_blocks", "any_block_value_schema",
    "text_slots", "texts_schema", "fill_texts",
]
