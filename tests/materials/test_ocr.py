"""OCR: с tesseract и без него. Тяжёлых зависимостей в пакете нет — только подпроцесс."""
from materials import KIND_IMAGE, ocr


def test_no_tesseract_is_not_a_failure(store, png, no_tesseract):
    """Без tesseract материал сохраняется, разбор не падает, пометка честная."""
    assert ocr.available() is False
    assert ocr.recognize(png()) == ""
    m = store.add(png(300, 200, "white"), name="прибор.png")
    assert m.kind == KIND_IMAGE and m.count == 0
    assert m.extra == {"width": 300, "height": 200}
    assert ocr.NOT_INSTALLED in m.notes
    assert ocr.NOT_INSTALLED in store.card(m.id).text


def test_tesseract_is_used_when_present(store, png, fake_tesseract):
    """Появился tesseract — текст с картинки попадает в материал и в карточку."""
    assert ocr.available() is True and "rus" in ocr.languages()
    m = store.add(png(300, 200, "white"), name="прибор.png")
    assert m.count == 2 and m.lang == "кириллица"
    assert store.read(m.id, 1, 1).text == fake_tesseract.splitlines()[0]
    assert store.read(m.id, 1, 1).anchor == "«прибор.png», строка 1"
    assert ocr.NOT_INSTALLED not in m.notes
    assert "распознано:" in store.card(m.id).text


def test_missing_language_pack_does_not_break_call(monkeypatch, png, fake_tesseract):
    """Просить несуществующий языковой пакет нельзя — tesseract на этом падает."""
    monkeypatch.setattr(ocr, "languages", lambda *a, **k: ["eng"])
    assert ocr._lang_arg(("rus", "eng")) == ["-l", "eng"]
    monkeypatch.setattr(ocr, "languages", lambda *a, **k: ["deu"])
    assert ocr._lang_arg(("rus", "eng")) == []      # ничего подходящего — идём без -l


def test_image_material_keeps_the_file_itself(store, png, no_tesseract):
    """Модели картинку не отдаём, но файл остаётся — его вставят в отчёт по id."""
    data = png(120, 80, "blue")
    m = store.add(data, name="схема.png")
    assert store.blob(m.id) == data
