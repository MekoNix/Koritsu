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


def _textboxes_in(p_elem, part):
    for tx in p_elem.iter(qn("w:txbxContent")):
        for child in list(tx.iterchildren()):
            if child.tag == qn("w:p"):
                yield ParaLoc(Paragraph(child, part), "textbox", False)
            elif child.tag == qn("w:tbl"):
                yield from _paras_in_table(child, part)


def iter_paragraphs(doc):
    """Снимок списка — рендер вставляет абзацы по ходу, итерировать живое дерево нельзя."""
    out = list(_paras_in_element(doc.element.body, doc.part, "body", False))
    for section in doc.sections:
        for kind in ("header", "first_page_header", "even_page_header",
                     "footer", "first_page_footer", "even_page_footer"):
            hf = getattr(section, kind)
            if hf.is_linked_to_previous:
                continue
            where = "header" if "header" in kind else "footer"
            out.extend(_paras_in_element(hf._element, hf.part, where, False))
    return out
