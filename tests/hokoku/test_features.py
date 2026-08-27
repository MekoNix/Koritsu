"""Возможности второй волны: поля, ссылки, подсветка, форматы, безопасность путей."""
import io
import shutil

import pytest
from docx import Document
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from hokoku import (Blocks, Code, Diagram, HokokuError, Image, Markdown, Table, Text,
                    extract_tags, render)
from .conftest import ptext, texts


def _fields(doc, kind):
    return [f.get(qn("w:instr")) for f in doc.element.body.iter(qn("w:fldSimple")) if kind in f.get(qn("w:instr"))]


def test_tag_inside_hyperlink_and_field(template, tmp_path):
    def build(d):
        p = d.add_paragraph("см. ")
        rid = d.part.relate_to("https://x.y", RT.HYPERLINK, is_external=True)
        h = OxmlElement("w:hyperlink"); h.set(qn("r:id"), rid)
        r = OxmlElement("w:r"); t = OxmlElement("w:t"); t.text = "{{ссылка}}"; r.append(t); h.append(r)
        p._p.append(h)
        p2 = d.add_paragraph("Дата: ")
        f = OxmlElement("w:fldSimple"); f.set(qn("w:instr"), " DATE ")
        r = OxmlElement("w:r"); t = OxmlElement("w:t"); t.text = "{{дата}}"; r.append(t); f.append(r)
        p2._p.append(f)
    path = template(build)
    assert [t.key for t in extract_tags(path)] == ["ссылка", "дата"]
    out = str(tmp_path / "o.docx")
    res = render(path, {"ссылка": "документация", "дата": "01.09"}, out)
    assert res.unfilled == [] and texts(out) == ["см. документация", "Дата: 01.09"]


def test_numbers_bool_and_nfc(template, tmp_path):
    import unicodedata
    out = str(tmp_path / "o.docx")
    render(template(lambda d: d.add_paragraph("n={{n}} f={{f}} b={{b}} й={{й}}")),
           {"n": 5, "f": 2.5, "b": True, unicodedata.normalize("NFD", "й"): "ok"}, out)
    assert texts(out) == ["n=5 f=2.5 b=да й=ok"]


def test_output_bytes_and_filelike(template, tmp_path):
    path = template(lambda d: d.add_paragraph("{{a}}"))
    res = render(path, {"a": "x"})
    assert res.output is None and res.data[:2] == b"PK"
    assert ptext(Document(io.BytesIO(res.data)).paragraphs[0]) == "x"
    buf = io.BytesIO()
    render(path, {"a": "y"}, buf)
    assert ptext(Document(io.BytesIO(buf.getvalue())).paragraphs[0]) == "y"


def test_document_input_not_mutated(template, tmp_path):
    d = Document(template(lambda d: d.add_paragraph("{{a}}")))
    render(d, {"a": "x"}, str(tmp_path / "o.docx"))
    assert d.paragraphs[0].text == "{{a}}"


def test_svg_image(template, tmp_path):
    pytest.importorskip("cairosvg")
    svg = b'<svg xmlns="http://www.w3.org/2000/svg" width="100" height="50"><rect width="100" height="50" fill="red"/></svg>'
    out = str(tmp_path / "o.docx")
    res = render(template(lambda d: d.add_paragraph("{{i}}")), {"i": Image(svg, caption="svg")}, out)
    assert res.figures == 1 and len(Document(out).inline_shapes) == 1


def test_captions_are_seq_fields_with_bookmarks_and_refs(template, tmp_path, png):
    def build(d):
        d.add_paragraph("Схема на {ref:схема}, таблица {ref:таб}, см. также {ref:нет}.")
        d.add_paragraph("{{схема}}")
        d.add_paragraph("{{таб}}")
        d.add_paragraph("{{текст}}")
    out = str(tmp_path / "o.docx")
    res = render(template(build), {
        "схема": Image(png, caption="Схема", split_pages=False),
        "таб": Table([["a"], ["1"]], caption="Т"),
        "текст": Markdown("см. рисунок {ref:схема} и таблицу {ref:таб}"),
    }, out)
    d = Document(out)
    assert res.refs == {"схема": 1, "таб": 1} and res.unresolved_refs == []
    seq = _fields(d, "SEQ")
    assert any("SEQ Рисунок" in f for f in seq) and any("SEQ Таблица" in f for f in seq)
    names = [b.get(qn("w:name")) for b in d.element.body.iter(qn("w:bookmarkStart"))]
    assert "_Ref_схема" in names and "_Ref_таб" in names
    assert "Рисунок 1 — Схема" in texts(out) and "Таблица 1 — Т" in texts(out)
    assert "см. рисунок 1 и таблицу 1" in texts(out)          # REF-поля с кэшем номеров
    refs = _fields(d, "REF")
    assert any("_Ref_схема" in f for f in refs)


def test_split_sheets_share_number(template, tmp_path, tall_png):
    out = str(tmp_path / "o.docx")
    render(template(lambda d: d.add_paragraph("{{a}}")), {"a": Image(tall_png, caption="С", split_pages=True)}, out)
    d = Document(out)
    seq = _fields(d, "SEQ Рисунок")
    assert len(seq) >= 2 and "\\c" not in seq[0] and all("\\c" in f for f in seq[1:])
    caps = [t for t in texts(out) if t.startswith("Рисунок")]
    assert caps[0].startswith("Рисунок 1 — С (лист 1 из")


def test_captions_without_fields_style_override(template, tmp_path, png):
    out = str(tmp_path / "o.docx")
    render(template(lambda d: d.add_paragraph("{{a}}")), {"a": Image(png, caption="X")}, out,
           style={"captions": {"fields": False, "figure": "Рис. {n} – {caption}"}})
    d = Document(out)
    assert _fields(d, "SEQ") == [] and "Рис. 1 – X" in texts(out)
    with pytest.raises(ValueError):
        render(template(lambda d: d.add_paragraph("{{a}}")), {"a": "x"}, out, style={"nope": {}})


def test_intro_paragraph_keeps_with_picture(template, tmp_path, png):
    def build(d):
        d.add_paragraph("Блок-схема алгоритма:")
        d.add_paragraph("{{схема}}")
        d.add_paragraph("Просто текст")
        d.add_paragraph("{{ещё}}")
    out = str(tmp_path / "o.docx")
    render(template(build), {"схема": Image(png), "ещё": Image(png)}, out)
    ps = Document(out).paragraphs
    assert ptext(ps[0]) == "Блок-схема алгоритма:" and ps[0]._p.find(".//" + qn("w:keepNext")) is not None
    after = next(p for p in ps if ptext(p) == "Просто текст")
    assert after._p.find(".//" + qn("w:keepNext")) is None
    pic = next(p for p in ps if p._p.find(".//" + qn("w:drawing")) is not None)
    assert pic._p.find(".//" + qn("w:keepNext")) is not None             # картинка прилипает к подписи


def test_code_highlight_and_line_numbers(template, tmp_path):
    pytest.importorskip("pygments")
    out = str(tmp_path / "o.docx")
    render(template(lambda d: d.add_paragraph("{{c}}")),
           {"c": Code("def f(x):\n    return x  # c\n", "python", line_numbers=True)}, out)
    ps = Document(out).paragraphs
    assert [ptext(p) for p in ps] == ["1  def f(x):", "2      return x  # c"]
    colors = {r.font.color.rgb for p in ps for r in p.runs if r.font.color and r.font.color.rgb}
    assert len(colors) >= 2                                           # серые номера + подсветка
    render(template(lambda d: d.add_paragraph("{{c}}")), {"c": Code("x", "python", highlight=False)}, out)
    assert all(r.font.color.rgb is None for p in Document(out).paragraphs for r in p.runs)


def test_markdown_tasks_nested_quote_image_attrs(template, tmp_path, png):
    (tmp_path / "i.png").write_bytes(png)
    out = str(tmp_path / "o.docx")
    render(template(lambda d: d.add_paragraph("{{m}}")),
           {"m": Markdown("- [ ] сделать\n- [x] готово\n\n> > глубоко\n\n![Подпись](i.png){width=3cm align=left}")},
           out, images_dir=str(tmp_path))
    d = Document(out)
    t = texts(out)
    assert "☐ сделать" in t and "☑ готово" in t and "глубоко" in t and "> глубоко" not in t
    shp = d.inline_shapes[0]
    assert abs(shp.width.cm - 3.0) < 0.05
    pic = next(p for p in d.paragraphs if p._p.find(".//" + qn("w:drawing")) is not None)
    assert pic._p.find(".//" + qn("w:jc")).get(qn("w:val")) == "left"


def test_value_with_braces_is_not_expanded(template, tmp_path):
    out = str(tmp_path / "o.docx")
    res = render(template(lambda d: d.add_paragraph("{{a}} {{b}}")), {"a": "x{{b}}y", "b": "B"}, out)
    assert texts(out) == ["x{{b}}y B"] and res.unfilled == []


def test_strict_paths(template, tmp_path, png):
    (tmp_path / "ok.png").write_bytes(png)
    out = str(tmp_path / "o.docx")
    render(template(lambda d: d.add_paragraph("{{i}}")), {"i": Image("ok.png")}, out,
           images_dir=str(tmp_path), strict_paths=True)
    with pytest.raises(HokokuError):
        render(template(lambda d: d.add_paragraph("{{i}}")), {"i": Image("../../etc/passwd")}, out,
               images_dir=str(tmp_path), strict_paths=True)
    with pytest.raises(HokokuError):
        render(template(lambda d: d.add_paragraph("{{i}}")), {"i": Image("ok.png")}, out, strict_paths=True)


def test_extract_tags_places_and_count(template):
    def build(d):
        d.sections[0].header.paragraphs[0].text = "{{фио}}"
        d.add_paragraph("{{фио:ФИО}} и {{фио}}")
    tags = extract_tags(template(build))
    assert len(tags) == 1 and tags[0].count == 3 and tags[0].label == "ФИО"
    assert set(tags[0].places) == {"body", "header"}


def test_numbering_reuses_abstract_num(template, tmp_path):
    out = str(tmp_path / "o.docx")
    render(template(lambda d: d.add_paragraph("{{m}}")),
           {"m": Markdown("\n\n".join(f"- a{i}\n- b{i}\n\nтекст {i}" for i in range(20)) + "\n\n1. x\n2. y")}, out)
    base = len(Document().part.numbering_part.element.findall(qn("w:abstractNum")))
    numbering = Document(out).part.numbering_part.element
    assert len(numbering.findall(qn("w:abstractNum"))) - base == 2   # один на вид списка (ul, ol)
    assert len(numbering.findall(qn("w:num"))) >= 21                  # но свой w:num на каждый список


@pytest.mark.skipif(shutil.which("drawio") is None, reason="нет drawio CLI")
def test_diagram_from_drawio_xml(template, tmp_path):
    xml = ('<mxGraphModel><root><mxCell id="0"/><mxCell id="1" parent="0"/>'
           '<mxCell id="2" value="A" style="rounded=1" vertex="1" parent="1">'
           '<mxGeometry x="20" y="20" width="80" height="40" as="geometry"/></mxCell></root></mxGraphModel>')
    out = str(tmp_path / "o.docx")
    res = render(template(lambda d: d.add_paragraph("{{d}}")), {"d": Diagram(xml, caption="Схема")}, out)
    assert res.figures == 1 and "Рисунок 1 — Схема" in texts(out)


def test_diagram_without_cli_raises(template, tmp_path, monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: None)
    with pytest.raises(HokokuError):
        render(template(lambda d: d.add_paragraph("{{d}}")), {"d": Diagram("<x/>")}, str(tmp_path / "o.docx"))


def test_formula_value_and_markdown_math(template, tmp_path):
    M = "{http://schemas.openxmlformats.org/officeDocument/2006/math}"
    from hokoku import Formula
    out = str(tmp_path / "o.docx")
    res = render(template(lambda d: (d.add_paragraph("{{f}}"), d.add_paragraph("{{m}}"))), {
        "f": Formula(r"E = m c^2", ref="энергия"),
        "m": Markdown("Энергия $E$ по формуле {ref:энергия}; и ещё:\n\n$$ \\frac{a}{b} = \\sqrt{x} $$\n\nконец"),
    }, out)
    d = Document(out)
    body = d.element.body
    assert len(list(body.iter(M + "oMath"))) == 3                    # формула, $E$, $$…$$
    assert res.formulas == 2 and res.refs["энергия"] == 1
    assert any("SEQ Формула" in f for f in _fields(d, "SEQ"))
    t = texts(out)
    assert any(x.strip().startswith("(") and x.strip().endswith(")") for x in t)   # «(1)» у формулы
    assert "Энергия  по формуле 1; и ещё:" in t
    assert d.settings.element.find(qn("w:updateFields")) is not None
    render(template(lambda d: d.add_paragraph("{{f}}")), {"f": Formula("\\frac{a")}, out)   # обрывок не роняет


def test_toc(template, tmp_path):
    from hokoku import Toc
    out = str(tmp_path / "o.docx")
    render(template(lambda d: (d.add_paragraph("{{toc}}"), d.add_heading("Раздел", 1))),
           {"toc": Toc(levels=2, title="Содержание")}, out)
    d = Document(out)
    instr = "".join(t.text for t in d.element.body.iter(qn("w:instrText")))
    assert 'TOC \\o "1-2"' in instr
    assert "Содержание" in texts(out)
    assert d.settings.element.find(qn("w:updateFields")).get(qn("w:val")) == "true"
