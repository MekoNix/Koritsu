from docx import Document

from hokoku import extract_tags
from hokoku.tags import parse_tag, TAG_RE
from .conftest import texts


def test_parse_forms():
    assert parse_tag("{{фио}}") == ("фио", "фио")
    assert parse_tag("{{ global_фио : ФИО студента }}") == ("global_фио", "ФИО студента")
    assert parse_tag("{{a.b-c_1}}") == ("a.b-c_1", "a.b-c_1")
    assert parse_tag("{{с пробелом}}") is None
    assert parse_tag("{{#if x}}") is None and parse_tag("{{x|def}}") is None   # зарезервировано


def test_extract_everywhere(template):
    def build(d):
        d.sections[0].header.paragraphs[0].text = "{{шапка}}"
        d.sections[0].footer.paragraphs[0].text = "стр. {{подвал:Подвал}}"
        p = d.add_paragraph()
        p.add_run("Студент {{").bold = True
        p.add_run("фио")
        p.add_run("}} группа {{группа}}")
        t = d.add_table(rows=1, cols=1)
        t.cell(0, 0).add_paragraph("{{ячейка}}")
        inner = t.cell(0, 0).add_table(rows=1, cols=1)
        inner.cell(0, 0).text = "{{вложенная}}"
        d.add_paragraph("{{фио}} ещё раз")
    path = template(build)
    tags = extract_tags(path)
    assert [(t.key, t.where) for t in tags] == [
        ("фио", "body"), ("группа", "body"), ("ячейка", "table"), ("вложенная", "table"),
        ("шапка", "header"), ("подвал", "footer")]
    assert next(t for t in tags if t.key == "подвал").label == "Подвал"


def test_extract_textbox(template):
    def build(d):
        p = d.add_paragraph()
        r = p.add_run()
        r._r.append(_textbox_xml("Тема: {{тема}}"))
    path = template(build)
    assert [(t.key, t.where) for t in extract_tags(path)] == [("тема", "textbox")]


def _textbox_xml(text):
    from docx.oxml import parse_xml
    return parse_xml(
        '<w:pict xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
        'xmlns:v="urn:schemas-microsoft-com:vml"><v:shape><v:textbox><w:txbxContent>'
        f'<w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:txbxContent></v:textbox></v:shape></w:pict>')
