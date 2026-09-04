"""PDF: текст с номерами страниц, картинки отдельными материалами, таблицы."""
from materials import KIND_IMAGE, KIND_PDF

from .conftest import build_pdf


def test_pages_are_numbered(store, pdf):
    m = store.add(pdf, name="методичка.pdf")
    assert m.kind == KIND_PDF and m.unit == "page" and m.count == 3
    assert m.extra["title"] == "Методичка по химии"
    assert "Hod raboty" in store.read(m.id, 2, 2).text
    assert store.read(m.id, 2, 2).anchor == "«методичка.pdf», страница 2"
    assert store.read(m.id, 1, 3).anchor == "«методичка.pdf», страницы 1–3"


def test_embedded_image_becomes_its_own_material(store, pdf):
    """Картинку со страницы потом вставляют в отчёт — значит она отдельный материал."""
    m = store.add(pdf, name="методичка.pdf")
    assert len(m.children) == 1
    child = store.get(m.children[0])
    assert child.kind == KIND_IMAGE
    assert child.origin["parent"] == m.id
    assert child.origin["page"] == 2                 # страница-источник запомнена
    assert child.origin["parent_name"] == "методичка.pdf"
    assert child.extra["width"] > 0 and store.blob(child.id)[:4] == b"\x89PNG"
    assert m.extra["images"] == 1


def test_same_image_on_many_pages_is_one_material(store, png):
    data = png(200, 120, "green")
    m = store.add(build_pdf(["stranica odin", "stranica dva"], images=[(1, data), (2, data)]),
                  name="дубли.pdf")
    assert len(m.children) == 1


def test_tiny_images_are_skipped(store, png):
    """Линейки и маркеры материалами не становятся — только шум в описи."""
    m = store.add(build_pdf(["tekst stranicy"], images=[(1, png(8, 8, "black"))]), name="мелочь.pdf")
    assert m.children == []


def test_tables_are_extracted(store, pdf):
    m = store.add(pdf, name="методичка.pdf")
    tables = store.tables(m.id)
    assert tables and tables[0]["page"] == 3
    assert tables[0]["rows"][0] == ["God", "Summa"]


def test_scanned_pdf_without_tesseract_does_not_crash(store, scanned_pdf, no_tesseract):
    """Скан без OCR: материал есть, страницы пустые, в карточке честная пометка."""
    m = store.add(scanned_pdf, name="скан.pdf")
    assert m.kind == KIND_PDF and m.count == 1
    assert m.extra.get("scanned") is True
    assert any("текстового слоя" in n and "tesseract не установлен" in n for n in m.notes)
    assert store.read(m.id, 1, 1).text == ""
    # Страницу-картинку вынули отдельным материалом, и она тоже честна о причине.
    child = store.get(m.children[0])
    assert any("tesseract не установлен" in n for n in child.notes)


def test_scanned_pdf_uses_ocr_when_available(store, scanned_pdf, fake_tesseract):
    """Появился tesseract — страницы скана читаются через него."""
    m = store.add(scanned_pdf, name="скан.pdf")
    assert fake_tesseract.splitlines()[0] in store.read(m.id, 1, 1).text
    assert any("получен через OCR" in n for n in m.notes)
    # Ту же страницу второй раз через tesseract не гоняем — она уже прочитана.
    assert store.get(m.children[0]).notes == ["текст не распознавался"]


def test_broken_pdf_is_not_fatal(store):
    m = store.add("%PDF-1.4 сломанный файл".encode(), name="битый.pdf")
    assert m.kind == KIND_PDF and m.count == 0 and m.notes
