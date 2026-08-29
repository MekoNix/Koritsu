"""
Матрица «место тега × тип значения»: каждый тип значения должен корректно
рендериться в каждом месте шаблона, где тег вообще может стоять.
"""
import pytest
from docx import Document
from docx.oxml.ns import qn

from hokoku import Blocks, Code, Image, Markdown, PageBreak, Table, Text, render
from .conftest import ptext
from .test_tags import _textbox_xml

PLACES = ["body", "body_with_text", "cell", "nested_cell", "header", "footer", "textbox", "list_item"]


def build_template(d, key="x"):
    d.add_paragraph("до")
    d.add_paragraph(f"{{{{{key}}}}}")                                   # body
    d.add_paragraph(f"Слева {{{{{key}}}}} справа.")                     # body_with_text
    t = d.add_table(rows=1, cols=2)
    t.cell(0, 0).text = "Заголовок"
    t.cell(0, 1).text = f"{{{{{key}}}}}"                                # cell
    inner = t.cell(0, 0).add_table(rows=1, cols=1)
    inner.cell(0, 0).text = f"вл {{{{{key}}}}}"                        # nested_cell
    d.sections[0].header.paragraphs[0].text = f"Шапка {{{{{key}}}}}"    # header
    d.sections[0].footer.paragraphs[0].text = f"{{{{{key}}}}} подвал"   # footer
    d.add_paragraph().add_run()._r.append(_textbox_xml(f"поле {{{{{key}}}}}"))   # textbox
    d.add_paragraph(f"пункт {{{{{key}}}}}", style="List Bullet")         # list_item
    d.add_paragraph("после")


def values(png):
    return {
        "text": "простой текст",
        "Text_nl": Text("строка 1\nстрока 2"),
        "Markdown": Markdown("**жирный** и *курсив*\n\n- пункт\n- ещё\n\n| a | b |\n|---|---|\n| 1 | 2 |"),
        "Code": Code("int x = 1;\nreturn x;"),
        "Image": Image(png, caption="Картинка"),
        "Table": Table([["h1", "h2"], ["1", "2"]], caption="Таблица"),
        "Blocks": Blocks([Text("абзац"), Image(png), Table([["a"], ["b"]]), PageBreak(), Code("x")]),
    }


def _all_text(doc):
    parts = [t.text or "" for t in doc.element.body.iter(qn("w:t"))]
    for s in doc.sections:
        for hf in (s.header, s.footer):
            parts.extend(t.text or "" for t in hf._element.iter(qn("w:t")))
    return "".join(parts)


def _blips(doc):
    n = len(list(doc.element.body.iter(qn("a:blip"))))
    return n + sum(len(list(hf._element.iter(qn("a:blip")))) for s in doc.sections for hf in (s.header, s.footer))


@pytest.mark.parametrize("vname", list(values(b"").keys()))
def test_value_type_in_every_place(template, tmp_path, png, vname):
    path = template(build_template)
    out = str(tmp_path / f"{vname}.docx")
    res = render(path, {"x": values(png)[vname]}, out)
    d = Document(out)
    full = _all_text(d)
    assert "{{" not in full and res.unfilled == []
    for marker in ("до", "Слева ", " справа.", "Заголовок", "вл ", "Шапка ", " подвал", "поле ", "пункт ", "после"):
        assert marker in full, marker                       # текст вокруг тегов цел везде
    if vname == "text":
        assert full.count("простой текст") == len(PLACES)
    if vname == "Text_nl":
        assert full.count("строка 1") == len(PLACES) and full.count("строка 2") == len(PLACES)
    if vname == "Image":
        # картинка вставляется везде, но в колонтитулах не нумеруется (логотип — не «Рисунок N»)
        assert _blips(d) == len(PLACES) and res.figures == len(PLACES) - 2
    if vname in ("Table", "Markdown"):
        assert len(list(d.element.body.iter(qn("w:tbl")))) >= 2 + 4     # исходные 2 + в body/text/cell/list
        assert full.count("1") >= len(PLACES)
    if vname == "Blocks":
        assert full.count("абзац") == len(PLACES) and _blips(d) == len(PLACES)
        assert any(br.get(qn("w:type")) == "page" for br in d.element.body.iter(qn("w:br")))
    if vname == "Code":
        assert full.count("return x;") == len(PLACES)


def test_many_different_tags_in_one_template(template, tmp_path, png):
    def build(d):
        d.sections[0].header.paragraphs[0].text = "{{шапка}}"
        t = d.add_table(rows=2, cols=2)
        t.cell(0, 0).text = "Студент"
        t.cell(0, 1).text = "{{фио}}"
        t.cell(1, 0).text = "Схема"
        t.cell(1, 1).text = "{{схема}}"
        d.add_paragraph("Цель: {{цель}}")
        d.add_paragraph("{{ход}}")
        d.add_paragraph("{{листинг}}")
        d.add_paragraph("{{таблица}}")
        d.add_paragraph("Вывод: {{вывод}} — конец.")
    out = str(tmp_path / "out.docx")
    res = render(template(build), {
        "шапка": "Отчёт", "фио": "Иванов", "схема": Image(png, caption="Схема"),
        "цель": Text("изучить"), "ход": Markdown("# Ход\n1. раз\n2. два"),
        "листинг": Code("print(1)"), "таблица": Table([["a", "b"], ["1", "2"]], caption="Т",
                                                     col_widths_cm=[3, 5], align=["left", "right"]),
        "вывод": Markdown("**всё** хорошо"),
    }, out)
    d = Document(out)
    full = _all_text(d)
    assert res.unfilled == [] and "{{" not in full
    assert d.sections[0].header.paragraphs[0].text == "Отчёт"
    assert d.tables[0].cell(0, 1).text == "Иванов"
    assert "Рисунок 1 — Схема" in [ptext(p) for p in d.tables[0].cell(1, 1).paragraphs]
    assert "Цель: изучить" in full and "Вывод: " in full and "всё" in full and " — конец." in full
    assert [ptext(p) for p in d.paragraphs if p.style.name == "Heading 1"] == ["Ход"]
    assert "Таблица 1 — Т" in full and res.tables == 1 and res.figures == 1
    # markdown внутри абзаца с текстом: «Вывод: » остался, блок вставлен рядом
    tbl = d.tables[1]
    assert tbl.cell(0, 1).paragraphs[0].alignment is not None or tbl.cell(0, 1).paragraphs[0]._p.find(".//" + qn("w:jc")) is not None
