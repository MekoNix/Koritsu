"""Карточки и опись: коротко, дёшево и с идентификатором."""
from materials import estimate_tokens
from materials.cards import CARD_MAX_LINES, human_size


def test_card_starts_with_id_and_stays_short(store, tmp_path):
    p = tmp_path / "отчёт.md"
    p.write_text("# Отчёт о продажах\n\n" + "\n".join(f"строка {i}" for i in range(500)), encoding="utf-8")
    m = store.add(str(p))
    card = store.card(m.id)
    assert card.lines[0].startswith(f"[{m.id}] отчёт.md — текст, ")
    assert "500 строк" not in card.lines[0] and "502 строки" in card.lines[0]
    assert len(card.lines) <= CARD_MAX_LINES
    assert all(len(line) <= 120 for line in card.lines)


def test_every_card_is_short_on_a_mixed_project(store, png, pdf, tmp_path):
    """Проект из разных материалов: ни одна карточка не разрастается."""
    store.add(pdf, name="методичка.pdf")
    store.add(png(800, 600, "white"), name="прибор.png")
    store.add(bytes(range(256)) * 4, name="дамп.bin")
    for i in range(6):
        p = tmp_path / f"опыт{i}.csv"
        p.write_text("темп;выход\n" + "\n".join(f"{t};{t * 2}" for t in range(40)), encoding="utf-8")
        store.add(str(p))
    for m in store.list():
        assert 1 <= len(store.card(m.id).lines) <= CARD_MAX_LINES, m.name


def test_inventory_lists_every_material_with_its_id(store, pdf, png):
    store.add(pdf, name="методичка.pdf")
    store.add(png(300, 200, "white"), name="прибор.png")
    inv = store.inventory()
    assert inv.startswith("Материалы проекта (3 материала):")   # + картинка из PDF
    for m in store.list():
        assert f"[{m.id}]" in inv


def test_inventory_is_cheap(store, tmp_path):
    """
    Опись — это то, что уходит в промпт по умолчанию, значит она должна быть
    дешёвой: примерно десяток строк и полсотни токенов на материал, не абзац.
    """
    for i in range(20):
        p = tmp_path / f"материал{i}.md"
        p.write_text(f"# Раздел {i}\n\n" + "\n".join(f"пункт {j}" for j in range(100)), encoding="utf-8")
        store.add(str(p))
    inv = store.inventory()
    assert len(store.list()) == 20
    assert estimate_tokens(inv) < 20 * 60
    assert len(inv.splitlines()) <= 20 * (CARD_MAX_LINES + 1) + 1


def test_field_values_are_codes_but_the_card_is_russian(store, pdf, tmp_path):
    """Разрез, ради которого заведены KIND_WORDS/UNIT_WORDS.

    В полях — коды (их читает клиент службы, генератор клиента и модель), в
    карточке и якоре — русские слова: карточку читает человек, а якорь модель
    вставляет в отчёт, и «page 2» уехало бы туда как есть.
    """
    p = tmp_path / "конспект.md"
    p.write_text("строка раз\nстрока два\n", encoding="utf-8")
    store.add(str(p))
    m = store.add(pdf, name="методичка.pdf")

    assert (m.kind, m.unit) == ("pdf", "page")
    for материал in store.list():
        assert материал.kind.isascii() and материал.unit.isascii(), материал.name
        assert материал.lang.isascii(), материал.name

    карточка = store.card(m.id)
    assert карточка.lines[0].startswith(f"[{m.id}] методичка.pdf — pdf, ")
    assert "3 страницы" in карточка.lines[0]
    assert store.read(m.id, 2, 2).anchor == "«методичка.pdf», страница 2"
    assert store.read(m.id, 1, 3).anchor == "«методичка.pdf», страницы 1–3"


def test_pdf_card_tells_what_was_extracted(store, pdf):
    m = store.add(pdf, name="методичка.pdf")
    text = store.card(m.id).text
    assert "заголовок: Методичка по химии" in text
    assert "1 картинка отдельными материалами" in text and "1 таблица" in text


def test_image_card_names_the_source_page(store, pdf, no_tesseract):
    m = store.add(pdf, name="методичка.pdf")
    child = store.card(m.children[0])
    assert "источник: «методичка.pdf», страница 2" in child.text
    assert "пикселей" in child.lines[0]


def test_human_size():
    assert human_size(900) == "900 Б"
    assert human_size(2048) == "2 КБ"
    assert human_size(3 * 1024 * 1024) == "3,0 МБ"
