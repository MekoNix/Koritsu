"""
Word: текст по абзацам, картинки отдельными материалами, таблицы, формулы —
и ни одного пути, на котором файл «принят», а содержимое потеряно молча.
"""
import io
import zipfile

import pytest
from materials import KIND_DOCX, KIND_IMAGE
from materials import _docx_safe

from .conftest import build_docx, fraction_omml, repack


def test_paragraphs_are_the_unit(store, docx_file):
    """Единица — блок документа: абзац или таблица, на своём месте по порядку."""
    m = store.add(docx_file, name="методичка.docx")
    assert m.kind == KIND_DOCX and m.unit == "paragraph"
    assert m.extra["title"] == "Методичка по химии"
    assert "Vvedenie" in store.read(m.id, 1, 1).text
    assert store.read(m.id, 1, 1).anchor == "«методичка.docx», абзац 1"
    assert store.read(m.id, 1, 3).anchor == "«методичка.docx», абзацы 1–3"
    # Весь текст документа доезжает до модели — ради этого всё и делалось.
    assert "Vyvody po rabote" in store.read(m.id).text


def test_empty_paragraphs_keep_the_numbering_honest(store):
    """Пустой абзац остаётся единицей: иначе номер в якоре зависел бы от того,
    что мы посчитали пустым, а не от самого файла."""
    m = store.add(build_docx(["pervyj", "", "tretij"]), name="пропуски.docx")
    assert m.count == 3
    assert store.read(m.id, 3, 3).text == "tretij"


def test_embedded_image_becomes_its_own_material(store, docx_file):
    """Рисунок из методички вставляют в отчёт — значит он отдельный материал."""
    m = store.add(docx_file, name="методичка.docx")
    assert len(m.children) == 1
    child = store.get(m.children[0])
    assert child.kind == KIND_IMAGE
    assert child.origin["parent"] == m.id
    assert child.origin["parent_name"] == "методичка.docx"
    assert child.origin["paragraph"] > 0        # место в документе запомнено
    assert child.extra["width"] > 0
    assert store.blob(child.id)[:4] == b"\x89PNG"   # байты те же, вставлять есть что
    assert m.extra["images"] == 1
    assert "абзац" in store.card(child.id).text


def test_same_image_twice_is_one_material(store, png):
    """Одна картинка в двух местах документа — один материал, а не два."""
    data = png(200, 120, "green")
    m = store.add(build_docx(["pervyj", "vtoroj"], images=[(1, data), (2, data)]),
                  name="дубли.docx")
    assert len(m.children) == 1


def test_tiny_images_are_skipped(store, png):
    """Линейки и маркеры материалами не становятся — только шум в описи."""
    m = store.add(build_docx(["tekst"], images=[(1, png(8, 8, "black"))]), name="мелочь.docx")
    assert m.children == []


def test_table_is_not_lost(store, docx_file):
    """Таблица есть и списком, и в тексте: python-docx её из абзацев не отдаёт,
    без своего обхода она исчезла бы из того, что видит модель."""
    m = store.add(docx_file, name="методичка.docx")
    tables = store.tables(m.id)
    assert tables and tables[0]["rows"][0] == ["God", "Summa"]
    assert tables[0]["paragraph"] == m.count            # таблица — последняя единица
    assert "2025" in store.read(m.id, m.count, m.count).text
    assert "1 таблица" in store.card(m.id).text


def test_formula_is_read_as_text(store):
    """Формула OMML: python-docx её не видит вовсе, и без разбора абзац
    «Формула: (a+b)/2» доехал бы до модели как «Формула:»."""
    data = build_docx(["Formula: "], formula=(1, fraction_omml("a+b", "2")))
    m = store.add(data, name="формулы.docx")
    assert store.read(m.id, 1, 1).text == "Formula: (a+b)/2"


def test_broken_zip_is_not_an_empty_document(store):
    """Порченый файл обязан отличаться от пустого документа: иначе человек
    решит, что методичка загружена, а модель не получит ничего."""
    m = store.add("PK\x03\x04 дальше мусор".encode(), name="битый.docx")
    assert m.kind == KIND_DOCX and m.count == 0
    assert any("битый zip" in n or "не открывается" in n for n in m.notes)
    assert m.notes[0] in store.card(m.id).text


def test_zip_without_document_xml_is_refused(store, docx_file):
    m = store.add(repack(docx_file, drop=("word/document.xml",)), name="подделка.docx")
    assert m.count == 0 and any("не документ Word" in n for n in m.notes)


def test_old_doc_says_what_to_do(store):
    """Старый .doc (OLE2, не zip) не читается — и говорит об этом человеку."""
    m = store.add(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 64, name="условие.doc")
    assert m.kind == KIND_DOCX and m.count == 0
    assert any("сохраните как .docx" in n for n in m.notes)


def test_docx_that_is_really_an_old_doc(store):
    """Расширение врёт: .docx с сигнатурой OLE2 — это .doc, и сказать надо про .doc."""
    m = store.add(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 64, name="условие.docx")
    assert any("старый формат Word" in n and "под паролем" in n for n in m.notes)


def test_doc_that_is_really_a_zip_is_parsed(store):
    """И наоборот: zip под именем .doc разбирается как docx, содержимое не теряется."""
    m = store.add(build_docx(["soderzhimoe est"]), name="условие.doc")
    assert m.count == 1 and "soderzhimoe" in store.read(m.id, 1, 1).text


def test_macros_are_read_but_flagged(store, docx_file):
    """.docm: текст читаем (иначе потеряли бы условие задачи), но пометка видна —
    сам файл в отчёт отдавать нельзя."""
    data = repack(docx_file, add={"word/vbaProject.bin": b"\x00" * 32})
    m = store.add(data, name="методичка.docm")
    assert m.extra.get("macros") is True
    assert "Vvedenie" in store.read(m.id, 1, 1).text
    assert any("макросами" in n for n in m.notes)
    assert any("макросами" in ln for ln in store.card(m.id).lines)


def test_xxe_declaration_is_refused(store, docx_file):
    """XML с DOCTYPE/ENTITY редакторы не пишут: это billion-laughs или чтение
    чужих файлов через парсер. До парсера такой документ не доходит."""
    evil = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><x/>'
    m = store.add(repack(docx_file, add={"word/evil.xml": evil}), name="бомба.docx")
    assert m.count == 0 and any("XXE" in n for n in m.notes)


def test_zip_bomb_is_measured_by_unpacking(store, docx_file, monkeypatch):
    """Потолок меряется распаковкой, а не заголовками архива: заголовок пишет
    тот же, кто прислал файл. Потолок здесь занижен, чтобы тест был быстрым."""
    monkeypatch.setattr(_docx_safe, "MAX_TOTAL_BYTES", 4096)
    data = repack(docx_file, add={"word/media/бомба.bin": b"\x00" * (2 * 1024 * 1024)})
    m = store.add(data, name="бомба.docx")
    assert m.count == 0 and any("zip-бомба" in n for n in m.notes)


def test_suspicious_member_name_is_refused(store, docx_file):
    """Имя вида `../..` Word не пишет никогда — это признак собранного вручную
    архива, и разбирать его мы не станем, хотя сами никуда не распаковываем."""
    data = repack(docx_file, add={"../../побег.xml": b"<x/>"})
    m = store.add(data, name="побег.docx")
    assert m.count == 0 and any("подозрительное имя" in n for n in m.notes)


def test_same_bytes_under_another_name_are_not_reparsed(store, docx_file, monkeypatch):
    """Разбор Word дорогой (zip, XML, картинки). Тот же файл под другим именем —
    тот же материал, и второй раз он не разбирается."""
    first = store.add(docx_file, name="методичка.docx")

    def upset(*a, **kw):
        raise AssertionError("разбор запустился второй раз на тех же байтах")

    monkeypatch.setattr("materials.store.parse", upset)
    again = store.add(docx_file, name="она_же_под_другим_именем.docx")
    assert again.id == first.id and again.name == "методичка.docx"
    assert again.children == first.children


def test_document_without_text_says_so(store, png):
    """Документ из одних картинок: текста нет — и это написано, а не подразумевается."""
    m = store.add(build_docx([""], images=[(1, png())]), name="только_картинки.docx")
    assert any("нет текста" in n for n in m.notes)
    assert len(m.children) == 1


def _with_body(data, body_xml):
    """Тот же документ, но с дописанным в тело куском XML: так собирается то,
    чего python-docx не умеет — надписи и правки."""
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        xml = z.read("word/document.xml").decode()
    xml = xml.replace("</w:body>", body_xml + "</w:body>")
    return repack(data, add={"word/document.xml": xml.encode()})


def test_deleted_text_does_not_reach_the_model(store):
    """Вычеркнутое при правках в документе уже нет: если отдать это модели,
    в отчёт попадёт то, что автор методички убрал."""
    body = ('<w:p><w:del><w:r><w:t>vycherknuto</w:t></w:r></w:del>'
            '<w:r><w:t>ostalos</w:t></w:r></w:p>')
    m = store.add(_with_body(build_docx(["obychnyj abzac"]), body), name="правки.docx")
    text = store.read(m.id).text
    assert "ostalos" in text and "vycherknuto" not in text


def test_text_box_is_read_once(store):
    """Надпись Word пишет дважды — современным способом и запасным (VML), — и
    без разбора AlternateContent её текст попал бы в абзац двумя копиями."""
    inner = ('<w:txbxContent><w:p><w:r><w:t>nadpis</w:t></w:r></w:p></w:txbxContent>')
    body = ('<w:p><mc:AlternateContent '
            'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006">'
            f'<mc:Choice Requires="wps"><w:drawing>{inner}</w:drawing></mc:Choice>'
            f'<mc:Fallback><w:pict>{inner}</w:pict></mc:Fallback>'
            '</mc:AlternateContent></w:p>')
    m = store.add(_with_body(build_docx(["obychnyj abzac"]), body), name="надпись.docx")
    assert store.read(m.id).text.count("nadpis") == 1


def test_content_control_is_not_lost(store):
    """Поле шаблона (`w:sdt`) — то, чем на кафедре делают строки «ФИО» и «Тема».
    python-docx такие блоки не отдаёт вовсе, и шапка задания терялась бы."""
    body = ('<w:sdt><w:sdtPr/><w:sdtContent>'
            '<w:p><w:r><w:t>Tema: teplota rastvoreniya</w:t></w:r></w:p>'
            '</w:sdtContent></w:sdt>')
    m = store.add(_with_body(build_docx(["shapka"]), body), name="задание.docx")
    assert "Tema: teplota rastvoreniya" in store.read(m.id).text


@pytest.mark.parametrize("name", ["шаблон.dotx", "шаблон.dotm"])
def test_templates_are_parsed_too(store, name):
    """Кафедральный шаблон приносят тоже — и содержимое из него нужно."""
    m = store.add(build_docx(["tekst shablona"]), name=name)
    assert m.kind == KIND_DOCX and "tekst shablona" in store.read(m.id).text
