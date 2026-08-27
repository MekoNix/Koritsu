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
