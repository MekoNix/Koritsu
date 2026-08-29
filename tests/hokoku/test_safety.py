import io
import zipfile

import pytest

from hokoku import DocxValidationError, validate_docx, safe_name
from hokoku.safety import safe_join


def _zip(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for n, b in members.items():
            z.writestr(n, b)
    return buf.getvalue()


GOOD = {"[Content_Types].xml": b"<Types/>", "word/document.xml": b"<w:document/>"}


def test_ok():
    validate_docx(_zip(GOOD))


def test_zip_slip():
    with pytest.raises(DocxValidationError):
        validate_docx(_zip({**GOOD, "../evil.txt": b"x"}))
    with pytest.raises(DocxValidationError):
        validate_docx(_zip({**GOOD, "/abs.xml": b"x"}))


def test_xxe():
    with pytest.raises(DocxValidationError):
        validate_docx(_zip({**GOOD, "word/styles.xml": b'<!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]><x/>'}))


def test_zip_bomb_ratio():
    with pytest.raises(DocxValidationError):
        validate_docx(_zip({**GOOD, "word/media/big.bin": b"\0" * (5 * 1024 * 1024)}))


def test_zip_bomb_many_small_members():
    """Каждый член «чистый» (50 КБ, сжатие не проверяется), а вместе — 10 МБ из 30 КБ."""
    members = {**GOOD}
    for i in range(200):
        members[f"word/media/f{i}.bin"] = b"\0" * (50 * 1024)
    data = _zip(members)
    assert len(data) < 200 * 1024                      # на диске мелочь
    with pytest.raises(DocxValidationError, match="zip-bomb"):
        validate_docx(data)


def test_zip_bomb_xml_share():
    """Один член в пределах лимитов, но XML пакета в разы больше, чем читает lxml."""
    from hokoku import safety
    import os
    big = b"<w:p>" + os.urandom(1024 * 1024).hex().encode() + b"</w:p>"   # плохо сжимается
    data = _zip({**GOOD, "word/document2.xml": big})
    old = safety.MAX_XML_UNCOMPRESSED
    safety.MAX_XML_UNCOMPRESSED = 1024 * 1024
    try:
        with pytest.raises(DocxValidationError, match="XML пакета"):
            validate_docx(data)
    finally:
        safety.MAX_XML_UNCOMPRESSED = old


def test_zip_bomb_lying_header():
    """Размер в заголовке занижен: верить ему нельзя, считаем распаковкой."""
    real = 4 * 1024 * 1024
    data = bytearray(_zip({**GOOD, "word/media/f.bin": b"\0" * real}))
    true_size = real.to_bytes(4, "little")
    assert data.count(true_size) >= 2                   # локальный заголовок + оглавление
    data = bytearray(data.replace(true_size, (100).to_bytes(4, "little")))
    with pytest.raises(DocxValidationError):
        validate_docx(bytes(data))


def test_not_zip_and_no_document():
    with pytest.raises(DocxValidationError):
        validate_docx(b"not a zip")
    with pytest.raises(DocxValidationError):
        validate_docx(_zip({"a.xml": b"<a/>"}))


CT_MAIN = b"application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"


def test_macro_docm():
    """Настоящий .docm: главная часть macroEnabled — шаблон отклоняем целиком."""
    types = b'<Types><Override PartName="/word/document.xml" ContentType=' \
            b'"application/vnd.ms-word.document.macroEnabled.main+xml"/></Types>'
    with pytest.raises(DocxValidationError, match="макрос"):
        validate_docx(_zip({"[Content_Types].xml": types, "word/document.xml": b"<w:document/>",
                            "word/vbaProject.bin": b"MACRO"}))


def test_vba_in_plain_docx():
    """Гибрид: обычный .docx с подложенным vbaProject.bin — по имени части,
    по content type и по связи (файл может называться как угодно)."""
    with pytest.raises(DocxValidationError, match="макрос"):
        validate_docx(_zip({**GOOD, "word/vbaProject.bin": b"MACRO"}))
    types = b'<Types><Default Extension="bin" ContentType=' \
            b'"application/vnd.ms-office.vbaProject"/></Types>'
    with pytest.raises(DocxValidationError, match="макрос"):
        validate_docx(_zip({**GOOD, "[Content_Types].xml": types, "word/x.bin": b"MACRO"}))
    rels = b'<Relationships><Relationship Id="r9" Type="http://schemas.microsoft.com/office/' \
           b'2006/relationships/vbaProject" Target="x.bin"/></Relationships>'
    with pytest.raises(DocxValidationError, match="макрос"):
        validate_docx(_zip({**GOOD, "word/_rels/document.xml.rels": rels, "word/x.bin": b"MACRO"}))


def test_vba_override_after_64k():
    """Override с vbaProject в конце длинного [Content_Types].xml — тоже видим."""
    types = b"<Types>" + b"<!-- " + b"x" * 200000 + b" -->" \
            + b'<Override PartName="/word/x.bin" ContentType="application/vnd.ms-office.vbaProject"/>' \
            + b"</Types>"
    with pytest.raises(DocxValidationError, match="макрос"):
        validate_docx(_zip({**GOOD, "[Content_Types].xml": types}))


def test_not_a_word_file_is_our_error(template, tmp_path):
    """Не .docx (например .dotx): наружу — DocxValidationError, а не голый ValueError."""
    import hokoku
    src = template(lambda d: d.add_paragraph("{{ключ}}"))
    dst = str(tmp_path / "tpl.dotx.docx")
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dst, "w") as zout:
        for it in zin.infolist():
            data = zin.read(it.filename)
            if it.filename == "[Content_Types].xml":
                data = data.replace(CT_MAIN, CT_MAIN.replace(b"document.main", b"template.main"))
            zout.writestr(it, data)
    with pytest.raises(DocxValidationError):
        hokoku.render(dst, {"ключ": "x"}, str(tmp_path / "out.docx"))


def test_external_refs_stripped(template, tmp_path):
    """attachedTemplate и внешний OLE-объект шаблона в отчёт не переезжают."""
    import hokoku
    att, ole = "file:///tmp/evil.dotm", "file:///tmp/payload.xlsx"
    src = template(lambda d: d.add_paragraph("Цель: {{цель}}"))
    dst = str(tmp_path / "ext.docx")
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dst, "w") as zout:
        for it in zin.infolist():
            data = zin.read(it.filename)
            if it.filename == "word/settings.xml":
                data = data.replace(b"</w:settings>", b'<w:attachedTemplate r:id="rIdAtt"/></w:settings>')
            elif it.filename == "word/_rels/document.xml.rels":
                data = data.replace(b"</Relationships>",
                                    b'<Relationship Id="rIdOle" Type="http://schemas.openxmlformats.org'
                                    b'/officeDocument/2006/relationships/oleObject" Target="'
                                    + ole.encode() + b'" TargetMode="External"/></Relationships>')
            zout.writestr(it, data)
        zout.writestr("word/_rels/settings.xml.rels",
                      '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/'
                      'relationships"><Relationship Id="rIdAtt" Type="http://schemas.openxmlformats.org'
                      f'/officeDocument/2006/relationships/attachedTemplate" Target="{att}"'
                      ' TargetMode="External"/></Relationships>')
    out = str(tmp_path / "out.docx")
    hokoku.render(dst, {"цель": "Изучить"}, out)
    with zipfile.ZipFile(out) as z:
        blob = b"".join(z.read(n) for n in z.namelist() if n.endswith((".xml", ".rels")))
    assert att.encode() not in blob and ole.encode() not in blob
    assert b"attachedTemplate" not in blob


def test_safe_name_and_join(tmp_path):
    assert safe_name("../../etc/passwd") == "passwd.docx"
    assert safe_name("Отчёт №1 (v2).docx") == "Отчёт 1 (v2).docx"
    assert safe_name("") == "file.docx" and safe_name(".docx") == "file.docx"
    assert safe_join(str(tmp_path), "a", "b.png").startswith(str(tmp_path))
    with pytest.raises(DocxValidationError):
        safe_join(str(tmp_path), "..", "x")
    with pytest.raises(DocxValidationError):
        safe_join(str(tmp_path), "/etc/passwd")


def test_repetitive_xml_is_not_a_bomb():
    """Честная методичка: 5000 одинаковых абзацев сжимаются в 200+ раз — это не бомба.
    XML держим абсолютным размером, степень сжатия проверяем у вложений."""
    body = "<w:p><w:r><w:t>Одинаковый абзац методички.</w:t></w:r></w:p>".encode() * 5000
    data = _zip({**GOOD, "word/document.xml": b"<w:document>" + body + b"</w:document>"})
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        info = z.getinfo("word/document.xml")
        assert info.file_size / info.compress_size > 200            # именно тот случай
    validate_docx(data)                                             # не должно бросать


def test_unsupported_compression_method():
    """Метод сжатия, которого нет в zipfile: раньше NotImplementedError летел мимо нас."""
    data = bytearray(_zip({**GOOD, "word/media/x.bin": b"abc" * 500}))
    data = bytearray(data.replace(b"\x08\x00", b"\x63\x00"))        # deflate → 99
    with pytest.raises(DocxValidationError, match="метод сжатия"):
        validate_docx(bytes(data))
