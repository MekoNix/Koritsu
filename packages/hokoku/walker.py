"""
walker — все абзацы документа, где могут стоять теги.

Тело, таблицы (любой вложенности), колонтитулы всех секций, текстовые поля
(w:txbxContent — и в w:pict, и в mc:AlternateContent), content controls. Сноски — нет.
"""
from __future__ import annotations

import io
from dataclasses import dataclass

from docx import Document
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph
from docx.text.run import Run

from .safety import validate_docx


def open_document(source):
    """Путь / bytes / file-like / готовый Document → Document (с валидацией)."""
    if hasattr(source, "paragraphs") and hasattr(source, "part"):
        return source
    validate_docx(source)
    if isinstance(source, (bytes, bytearray)):
        return Document(io.BytesIO(bytes(source)))
    return Document(source)


@dataclass
class ParaLoc:
    paragraph: Paragraph
    where: str                    # body | table | header | footer | textbox
    in_table: bool = False

    def runs(self) -> list[Run]:
        """Все runs абзаца, включая внутри гиперссылок и полей; без удалённых (w:del)
        и без вложенных текстовых полей (они — отдельные ParaLoc)."""
        p = self.paragraph._p
        return [Run(r, self.paragraph) for r in
                p.xpath("./w:r | ./*[not(self::w:del) and not(self::w:pict) and not(self::w:drawing)]//w:r"
                        "[not(ancestor::w:txbxContent) and not(ancestor::w:del)]")]

    def text(self) -> str:
        return "".join(r.text for r in self.runs())


def _paras_in_element(elem, part, where: str, in_table: bool):
    """Абзацы непосредственно в elem, затем вложенные таблицы и текстовые поля."""
    for child in list(elem.iterchildren()):
        tag = child.tag
        if tag == qn("w:p"):
            yield ParaLoc(Paragraph(child, part), where, in_table)
            yield from _textboxes_in(child, part)
        elif tag == qn("w:tbl"):
            yield from _paras_in_table(child, part)
        elif tag == qn("w:sdt"):
            content = child.find(qn("w:sdtContent"))
            if content is not None:
                yield from _paras_in_element(content, part, where, in_table)


def _paras_in_table(tbl, part):
    for row in tbl.iterchildren(qn("w:tr")):
        for tc in row.iterchildren(qn("w:tc")):
            yield from _paras_in_element(tc, part, "table", True)


MC = "{http://schemas.openxmlformats.org/markup-compatibility/2006}"


def _dead_fallback(el) -> bool:
    """Текстовое поле из mc:Fallback, у которого есть mc:Choice: в Choice лежит та же
    копия содержимого, и без этой проверки тег обрабатывается дважды — один
    нумерованный тег давал два рисунка и сбитую нумерацию."""
    node = el.getparent()
    while node is not None:
        if node.tag == MC + "Fallback":
            alt = node.getparent()
            if alt is not None and alt.find(MC + "Choice") is not None:
                return True
        node = node.getparent()
    return False


def _textboxes_in(p_elem, part):
    for tx in p_elem.iter(qn("w:txbxContent")):
        if _dead_fallback(tx):
            continue
        for child in list(tx.iterchildren()):
            if child.tag == qn("w:p"):
                yield ParaLoc(Paragraph(child, part), "textbox", False)
            elif child.tag == qn("w:tbl"):
                yield from _paras_in_table(child, part)


HF_KINDS = ("header", "first_page_header", "even_page_header",
            "footer", "first_page_footer", "even_page_footer")


def _headers_footers(doc):
    """Колонтитулы всех секций, кроме унаследованных от предыдущей."""
    for section in doc.sections:
        for kind in HF_KINDS:
            hf = getattr(section, kind)
            if not hf.is_linked_to_previous:
                yield hf, ("header" if "header" in kind else "footer")


def iter_paragraphs(doc):
    """Снимок списка — рендер вставляет абзацы по ходу, итерировать живое дерево нельзя."""
    out = list(_paras_in_element(doc.element.body, doc.part, "body", False))
    for hf, where in _headers_footers(doc):
        out.extend(_paras_in_element(hf._element, hf.part, where, False))
    return out


MARKERS = ("{{", "{ref:")


def marked_paragraphs(doc, markers=MARKERS) -> set:
    """Абзацы, в тексте которых есть маркер, — одним XPath на каждую часть документа.
    Разбирать runs у каждого абзаца только ради вопроса «есть ли тут тег» дорого:
    на шаблоне в 2000 абзацев это 120 мс против 2 мс. Множество держит сами элементы,
    поэтому сравнение по вхождению (`p in hot`) законно.
    Отбор нестрогий (сюда попадает и текст в w:del, и вложенное текстовое поле) —
    точную проверку делает тот, кто абзац обрабатывает."""
    cond = " or ".join(f"contains(string(.), '{m}')" for m in markers)
    out = set(doc.element.body.xpath(f".//w:p[{cond}]"))
    for hf, _ in _headers_footers(doc):
        out.update(hf._element.xpath(f".//w:p[{cond}]"))
    return out
