"""Хранилище: идентификаторы, отсутствие дублей, чтение кусков и байтов."""
import pytest

from materials import KIND_TEXT, KIND_UNKNOWN, MaterialsError, Store, material_id


def write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return str(p)


def test_add_text_and_read_chunk(store, tmp_path):
    path = write(tmp_path, "конспект.md", "\n".join(f"строка {i}" for i in range(1, 21)))
    m = store.add(path)
    assert m.kind == KIND_TEXT and m.unit == "строка" and m.count == 20
    assert m.lang == "кириллица"
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
