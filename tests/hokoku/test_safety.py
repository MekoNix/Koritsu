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
