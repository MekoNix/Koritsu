"""Хранилище: идентификаторы, отсутствие дублей, чтение кусков и байтов."""
import pytest

from materials import KIND_TEXT, KIND_UNKNOWN, MaterialsError, Store, material_id

from .conftest import build_pdf


def write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return str(p)


def test_add_text_and_read_chunk(store, tmp_path):
    path = write(tmp_path, "конспект.md", "\n".join(f"строка {i}" for i in range(1, 21)))
    m = store.add(path)
    # Значения полей — коды по-английски, подписи для человека остаются в
    # карточке и якоре: их проверяют строки ниже.
    assert m.kind == KIND_TEXT and m.unit == "line" and m.count == 20
    assert m.lang == "cyrillic"
    chunk = store.read(m.id, 3, 5)
    assert chunk.text == "строка 3\nстрока 4\nстрока 5"
    assert chunk.anchor == "«конспект.md», строки 3–5"


def test_same_file_added_twice_is_one_material(store, tmp_path, monkeypatch):
    """Повторное добавление не дублирует материал и не считает разбор заново."""
    path = write(tmp_path, "данные.csv", "a;b\n1;2\n")
    calls = []
    import materials.store as store_mod
    real = store_mod.parse
    monkeypatch.setattr(store_mod, "parse", lambda *a, **k: (calls.append(1), real(*a, **k))[1])

    first = store.add(path)
    second = store.add(path)
    assert first.id == second.id
    assert len(store.list()) == 1
    assert len(calls) == 1                      # второй раз разбора не было


def test_same_bytes_under_other_name_is_same_material(store):
    """Идентификатор — от содержимого, поэтому имя на дедупликацию не влияет."""
    data = "одно и то же".encode()
    a = store.add(data, name="первый.txt")
    b = store.add(data, name="второй.txt")
    assert a.id == b.id == material_id(data)
    assert store.get(b.id).name == "первый.txt"   # имя остаётся от первого добавления


def test_bytes_need_a_name(store):
    with pytest.raises(MaterialsError):
        store.add(b"abc")


def test_missing_file(store):
    with pytest.raises(MaterialsError):
        store.add("/нет/такого/файла.txt")


def test_blob_and_path_return_original_bytes(store, png):
    data = png(64, 64, "red")
    m = store.add(data, name="прибор.png")
    assert store.blob(m.id) == data
    assert store.path(m.id).endswith(".png")


def test_unknown_type_is_kept_but_not_parsed(store):
    """Неизвестный тип не ломает разбор: файл сохранён, в карточке сказано почему."""
    m = store.add(bytes(range(256)) * 8, name="прибор.dat")
    assert m.kind == KIND_UNKNOWN and m.count == 0
    assert m.notes and "не поддерживается" in m.notes[0]
    assert store.blob(m.id)[:4] == bytes(range(4))
    assert store.read(m.id).text == ""


def test_unknown_extension_but_text_inside(store):
    """Расширения не перечислить все: текст внутри опознаётся по содержимому."""
    m = store.add("program Test;\nbegin\nend.\n".encode(), name="lab.pas7")
    assert m.kind == KIND_TEXT and m.count == 3
    assert any("по содержимому" in n for n in m.notes)


def test_read_out_of_range_is_clamped(store, tmp_path):
    """Модель ошибается в номерах — сборку контекста это ронять не должно."""
    m = store.add(write(tmp_path, "a.txt", "one\ntwo\nthree\n"))
    chunk = store.read(m.id, 2, 999)
    assert chunk.start == 2 and chunk.end == 3 and chunk.text == "two\nthree"
    assert store.read(m.id, 0, 1).start == 1
    assert store.read(m.id, 50, 60).text == "three"     # прижали к последней строке


def test_store_survives_reopen(store, tmp_path):
    m = store.add(write(tmp_path, "a.txt", "раз\nдва\n"))
    again = Store(store.root)
    assert [x.id for x in again.list()] == [m.id]
    assert again.read(m.id, 1, 1).text == "раз"


def test_list_keeps_order_of_adding(store, tmp_path):
    ids = [store.add(write(tmp_path, f"f{i}.txt", f"файл {i}\n")).id for i in range(5)]
    assert [m.id for m in store.list()] == ids


def test_remove_убирает_и_исходник_и_разбор(store, tmp_path):
    """Удаление: байты уходят с диска, а не только из описи.

    Нужно службе (`api`): человек удалил файл, и квота обязана перестать
    его считать. Полуудаление — «из списка пропал, место занимает» — это ровно
    та беда, которую человек обнаруживает через месяц.
    """
    import os

    m = store.add(write(tmp_path, "лишнее.txt", "раз\nдва\n"))
    папка = os.path.join(store.root, m.id)
    assert os.path.isdir(папка)

    store.remove(m.id)

    assert not os.path.exists(папка)
    assert store.list() == []
    with pytest.raises(MaterialsError):
        store.get(m.id)


def test_remove_несуществующего(store):
    """Удаление того, чего нет, — опечатка вызывающего, а не «уже удалено»."""
    with pytest.raises(MaterialsError):
        store.remove("0123456789abcdef")


def test_remove_уносит_детей(store, pdf):
    """Картинки, вынутые со страниц PDF, уходят вместе с родителем.

    Оставленные дети — «сироты», которых человек в описи не видит, а квота
    считает.
    """
    родитель = store.add(pdf, name="методичка.pdf", do_ocr=False)
    assert родитель.children, "у этого PDF должна быть картинка на странице"

    убрано = store.remove(родитель.id)

    assert set(убрано) == {родитель.id, *родитель.children}
    assert store.list() == []


def test_remove_бережёт_названных_детей(store, pdf):
    """`keep` — ссылки, про которые знает вызывающий, а не хранилище.

    Про значения тегов проекта знает служба (`api`), и она же называет тех, кого
    трогать нельзя: завести это знание здесь значило бы связать хранилище файлов
    с оркестратором.
    """
    родитель = store.add(pdf, name="методичка.pdf", do_ocr=False)
    ребёнок = родитель.children[0]

    убрано = store.remove(родитель.id, keep=[ребёнок])

    assert убрано == [родитель.id]
    assert [m.id for m in store.list()] == [ребёнок]
    assert store.blob(ребёнок)[:4] == b"\x89PNG"      # байты на месте


def test_remove_не_трогает_ребёнка_чужого_родителя(store, png):
    """Одна и та же картинка в двух методичках — ОДИН материал (идентификатор
    считается по содержимому). Удаление первой методички не смеет вынимать
    картинку из второй."""
    картинка = png()
    первая = store.add(build_pdf(["Pervaya"], images=[(1, картинка)]),
                       name="первая.pdf", do_ocr=False)
    вторая = store.add(build_pdf(["Vtoraya"], images=[(1, картинка)]),
                       name="вторая.pdf", do_ocr=False)
    общий = первая.children[0]
    assert вторая.children == [общий], "картинка одна и та же — материал один"

    убрано = store.remove(первая.id)

    assert убрано == [первая.id]
    assert {m.id for m in store.list()} == {вторая.id, общий}


def test_remove_с_children_false_оставляет_детей(store, pdf):
    """Уборка производных выключается: вызывающему бывает нужно убрать ровно то,
    что он назвал, — и решать это ему, а не умолчанию."""
    родитель = store.add(pdf, name="методичка.pdf", do_ocr=False)

    убрано = store.remove(родитель.id, children=False)

    assert убрано == [родитель.id]
    assert {m.id for m in store.list()} == set(родитель.children)
