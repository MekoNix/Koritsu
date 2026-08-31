"""
Контракт wire: круговой прогон, схема против model.py, отказы, версии.

Ни один тест здесь не ходит в сеть и не зовёт модель: контракт обязан проверяться сам
по себе. Образцы значений лежат файлами (tests/hokoku/values/*.json), а не строками
в коде, — тогда правка схемы видна в дифе образцов.
"""
import json
import pathlib
from dataclasses import dataclass, fields

import pytest

from hokoku import (Blocks, Code, Diagram, Formula, Image, Markdown, PageBreak, Table, Text, Toc)
from hokoku import wire
from hokoku.wire import (VALUE_TYPES, WIRE_VERSION, WireError, value_from_json, value_schema,
                         value_to_json, values_from_json, values_to_json)
from llm import jsonschema

VALUES_DIR = pathlib.Path(__file__).parent / "values"
XML = ('<mxfile><diagram name="лист 1"><mxGraphModel><root/></mxGraphModel></diagram>'
       '<diagram name="лист 2"><mxGraphModel><root/></mxGraphModel></diagram></mxfile>')

TYPE_OF = {Text: "text", Markdown: "markdown", Code: "code", Image: "image", Diagram: "diagram",
           Table: "table", Formula: "formula", Toc: "toc", PageBreak: "page_break",
           Blocks: "blocks"}
# Поля датакласса, которых в JSON нет: их ставит служба, а не отправитель значения.
SERVICE_ONLY = {"Image": {"source"}, "Markdown": {"images_dir"}, "Diagram": {"xml"}}


@pytest.fixture
def store(png):
    """Поддельное хранилище артефактов: словарь «идентификатор → байты»."""
    return {"af_png": png, "af_xml": XML.encode("utf-8"), "af_broken": b"not an image at all"}


@pytest.fixture
def resolve(store):
    def _resolve(art_id):
        return store[art_id]
    return _resolve


@pytest.fixture
def artifact_of(store):
    back = {bytes(data): art_id for art_id, data in store.items()}
    return lambda data: back[bytes(data)]


# ── 1. круговой прогон ────────────────────────────────────────────────────────

@pytest.mark.parametrize("path", sorted(VALUES_DIR.glob("*.json")), ids=lambda p: p.stem)
def test_образец_переживает_круговой_прогон(path, resolve, artifact_of):
    d = json.loads(path.read_text(encoding="utf-8"))
    value = value_from_json(d, resolve_artifact=resolve)
    assert value_to_json(value, artifact_of=artifact_of) == d


def test_образцы_есть_на_каждый_тип():
    """Тип без образца — тип, круговой прогон которого никто не проверяет."""
    have = {json.loads(p.read_text(encoding="utf-8"))["type"] for p in VALUES_DIR.glob("*.json")}
    assert have == set(TYPE_OF.values())


def test_значение_переживает_круговой_прогон(png, resolve, artifact_of):
    """Обратная сторона: значение с умолчаниями → JSON → то же самое значение."""
    for value in (Text("а"), Markdown("**б**"), Code("x = 1"), Image(png),
                  Table([["1"]]), Formula("a=b"), Toc(), PageBreak(),
                  Blocks([Text("а"), PageBreak()])):
        d = value_to_json(value, artifact_of=artifact_of)
        assert value_from_json(d, resolve_artifact=resolve) == value


def test_diagram_через_артефакт(resolve):
    d = {"v": 1, "type": "diagram", "artifact": "af_xml", "caption": "Алгоритм"}
    assert value_from_json(d, resolve_artifact=resolve) == Diagram(XML, caption="Алгоритм")


def test_скаляры_переводятся_в_текст():
    """Голых скаляров в JSON нет: true стало бы словом «да» уже у получателя."""
    assert values_to_json({"n": 42, "готово": True, "провал": False, "s": "текст"}) == {
        "n": {"v": 1, "type": "text", "text": "42"},
        "готово": {"v": 1, "type": "text", "text": "да"},
        "провал": {"v": 1, "type": "text", "text": "нет"},
        "s": {"v": 1, "type": "text", "text": "текст"}}


# ── 2. схема не отстала от model.py ───────────────────────────────────────────

def test_каждое_поле_датакласса_выражено():
    """Самый важный тест контракта: поле, добавленное в model.py и забытое в wire.py,
    иначе молча теряет настройку значения."""
    for cls, name in TYPE_OF.items():
        expected = {f.name for f in fields(cls)} - SERVICE_ONLY.get(cls.__name__, set())
        assert expected <= set(value_schema(name)["properties"]), cls.__name__


def test_новое_поле_модели_роняет_схему(monkeypatch):
    @dataclass
    class Осмотр:
        text: str
        rotate: int = 0

    monkeypatch.setitem(wire._TYPES, "осмотр", wire._spec("осмотр", Осмотр, {"text": wire._TEXT}))
    with pytest.raises(RuntimeError, match="rotate"):
        wire._check_model_coverage()


def test_схема_для_модели_уже():
    """Модель не рисует draw.io XML и не решает, что картинка не нумеруется."""
    full, model = value_schema("diagram"), value_schema("diagram", for_model=True)
    assert "xml" in full["properties"] and "xml" not in model["properties"]
    assert "artifact" in model["required"]
    assert {"const": False} in value_schema("image")["properties"]["caption"]["anyOf"]
    assert value_schema("image", for_model=True)["properties"]["caption"] == \
        {"type": ["string", "null"]}


def test_схема_целиком_перечисляет_типы():
    schema = value_schema()
    assert {s["properties"]["type"]["const"] for s in schema["anyOf"]} == set(TYPE_OF.values())
    items = value_schema("blocks")["properties"]["items"]["items"]["anyOf"]
    assert "blocks" not in {s["properties"]["type"]["const"] for s in items}
    assert all("v" not in s["properties"] for s in items)


def test_схема_проходит_проверщик_слоя_llm():
    """Сквозная проверка: схема, которую мы отдаём модели, обязана проходить тот самый
    проверщик, через который её пропускает structured.run_ladder. Без этого теста
    «заполнить тег» падало на SchemaError ещё до обращения к сети — на каждом типе."""
    for name in VALUE_TYPES:
        model = value_schema(name, for_model=True)
        jsonschema.check_schema(model)
        # run_ladder на ступенях 1–2 отдаёт поставщику именно strictify(схему)
        jsonschema.check_schema(jsonschema.strictify(model))
        jsonschema.check_schema(value_schema(name))     # и схема валидатора тоже


def test_версия_не_обязательна_модели():
    """«v» ставит служба: требовать его от модели — лишние токены на каждом значении."""
    assert "v" not in value_schema("text", for_model=True)["required"]
    assert "v" in value_schema("text", for_model=True)["properties"]
    assert "v" in value_schema("text")["required"]
    assert jsonschema.validate({"type": "text", "text": "а"},
                               value_schema("text", for_model=True)) == []


def test_значение_проверяется_схемой_для_модели():
    """Схема — не украшение: дискриминатор, обязательные поля и вариант блока
    ловятся тем же валидатором, что работает на ступенях 3–4."""
    blocks = value_schema("blocks", for_model=True)
    assert jsonschema.validate(
        {"type": "blocks", "items": [{"type": "text", "text": "а"},
                                     {"type": "image", "artifact": "af_png"}]}, blocks) == []
    # ошибку берём у варианта, выбранного по метке, а не сваливаем все девять
    errors = jsonschema.validate({"type": "blocks", "items": [{"type": "image"}]}, blocks)
    assert errors == ["items[0]: нет обязательного ключа 'artifact'"]
    assert jsonschema.validate({"type": "table", "rows": [["а"]]},
                               value_schema("text", for_model=True))    # чужая метка


def test_неизвестный_тип_в_схеме():
    with pytest.raises(WireError, match="похоже на"):
        value_schema("imagе")                                # «е» кириллическая


# ── 3. отказы ─────────────────────────────────────────────────────────────────

REFUSALS = [
    ({"v": 1, "type": "имидж"}, "неизвестный тип"),
    ({"v": 1, "type": "image", "artifact": "af_png", "captionn": "Схема"}, 'похоже на "caption"'),
    ({"v": 1, "type": "text"}, 'нет обязательного поля "text"'),
    ({"v": "1", "type": "text", "text": "а"}, 'поле "v"'),
    ({"v": 0, "type": "text", "text": "а"}, 'поле "v"'),
    ({"v": 2, "type": "text", "text": "а"}, "версии 2, читатель знает до 1"),
    ({"v": 1, "type": "image", "artifact": "../секрет.png"}, "не идентификатор артефакта"),
    ({"v": 1, "type": "image", "artifact": "/etc/passwd"}, "не идентификатор артефакта"),
    ({"v": 1, "type": "image", "artifact": "iVBORw0KGgoAAAANSUhEUgAAAMgAAAB4CAIAAAD" * 2},
     "не идентификатор артефакта"),
    ({"v": 1, "type": "image", "artifact": "af_broken"}, "не картинка"),
    ({"v": 1, "type": "table", "rows": [["A", "B"], ["1"], ["1", "2", "3"]]}, "в строке 2 ячеек 1"),
    ({"v": 1, "type": "table", "rows": [["a", "b"]], "align": ["left"]}, "1 значений на 2 колонок"),
    ({"v": 1, "type": "table", "rows": [["a", "b"]], "col_widths_cm": [1]}, "1 значений на 2"),
    ({"v": 1, "type": "table", "rows": [[1, 2]]}, "ячейка [1][1]"),
    ({"v": 1, "type": "diagram", "xml": "<mxfile/>", "page": 0}, "номер листа, считая с 1"),
    ({"v": 1, "type": "diagram", "xml": XML, "page": 3}, "лист 3, а в схеме листов 2"),
    ({"v": 1, "type": "diagram", "xml": "<mxfile/>", "artifact": "af_xml"}, "заданы оба"),
    ({"v": 1, "type": "diagram"}, "не задано ни одного"),
    ({"v": 1, "type": "toc", "levels": 12}, "от 1 до 9"),
    ({"v": 1, "type": "toc", "levels": True}, "от 1 до 9"),
    ({"v": 1, "type": "image", "artifact": "af_png", "caption": True}, "true бессмысленно"),
    ({"v": 1, "type": "image", "artifact": "af_png", "align": "middle"}, "left, center, right"),
    ({"v": 1, "type": "image", "artifact": "af_png", "width_cm": True}, "ожидалось число"),
    ({"v": 1, "type": "code", "text": "x", "lang": 3}, "ожидалась строка"),
    ({"v": 1, "type": "blocks", "items": [{"type": "blocks", "items": []}]}, "нельзя вкладывать"),
    ({"v": 1, "type": "blocks", "items": [{"v": 1, "type": "text", "text": "а"}]},
     'поле "v" стоит только на значении верхнего уровня'),
    ({"v": 1, "type": "blocks", "items": ["строка"]}, "должно быть объектом JSON"),
    ("не объект", "должно быть объектом JSON"),
]


def test_версию_можно_не_писать(resolve):
    """Версия на значении необязательна: отсутствие = текущая, как и `wire_version` у задания.
    Иначе каждый производитель значений (интерфейс, скрипт, модель) обязан штамповать «v»."""
    from hokoku import Text
    v = value_from_json({"type": "text", "text": "а"}, resolve_artifact=resolve)
    assert isinstance(v, Text) and v.text == "а"


@pytest.mark.parametrize("bad,expect", REFUSALS, ids=range(len(REFUSALS)))
def test_отказ(bad, expect, resolve):
    with pytest.raises(WireError) as e:
        value_from_json(bad, resolve_artifact=resolve)
    assert expect in str(e.value)


def test_ошибка_называет_место_внутри_blocks(resolve):
    bad = {"v": 1, "type": "blocks", "items": [{"type": "text", "text": "а"},
                                               {"type": "image", "artifact": "af_png",
                                                "captionn": "Схема"}]}
    with pytest.raises(WireError, match=r"items\[1\].*captionn"):
        value_from_json(bad, resolve_artifact=resolve)


def test_артефакт_без_колбэка():
    with pytest.raises(WireError, match="resolve_artifact"):
        value_from_json({"v": 1, "type": "image", "artifact": "af_png"})


def test_путь_наружу_не_выражается(png, artifact_of):
    """Обратное преобразование само по себе не может протащить путь в JSON."""
    with pytest.raises(WireError, match="путей там нет"):
        value_to_json(Image("/etc/hostname"), artifact_of=artifact_of)
    with pytest.raises(WireError, match="artifact_of"):
        value_to_json(Image(png))
    with pytest.raises(WireError, match="не выражается"):
        value_to_json(object())


# ── 4. набор значений ─────────────────────────────────────────────────────────

def test_набор_собирает_что_может(resolve):
    values, errors = values_from_json({
        "цель": {"v": 1, "type": "markdown", "text": "Изучить"},
        "схема": {"v": 1, "type": "image", "artifact": "af_missing"},
        "чужое": {"v": 1, "type": "нечто"}}, resolve_artifact=resolve)
    assert values == {"цель": Markdown("Изучить")}
    assert [(e["key"], e["stage"]) for e in errors] == [("схема", "artifact"), ("чужое", "wire")]
    assert "af_missing" in errors[0]["message"]


def test_ключи_нормализуются_в_nfc(resolve):
    """Word и macOS пишут «й» разложенной (NFD); нормализуем обе стороны, не полагаясь
    на то, что это сделал клиент."""
    nfc, nfd = "\u0439\u043e\u043b", "\u0438\u0306\u043e\u043b"
    values, errors = values_from_json({nfc: {"v": 1, "type": "text", "text": "а"},
                                       nfd: {"v": 1, "type": "text", "text": "б"}},
                                      resolve_artifact=resolve)
    assert list(values) == [nfc]
    assert "повторяется" in errors[0]["message"]


def test_набор_не_объект():
    with pytest.raises(WireError, match="объектом JSON"):
        values_from_json([{"v": 1, "type": "text", "text": "а"}])


# ── 5. версии и миграции ──────────────────────────────────────────────────────

def test_цепочка_миграций_пуста_но_рабочая(monkeypatch):
    """Миграция — чистая функция словарь → словарь; на каждую пишется тест с
    зафиксированным старым JSON, который задним числом не правится."""
    assert wire._MIGRATIONS == {}
    monkeypatch.setattr(wire, "WIRE_VERSION", 2)
    monkeypatch.setitem(wire._MIGRATIONS, 1, lambda d: {**d, "lang": "python"})
    assert wire._upgrade({"v": 1, "type": "code", "text": "x = 1"}) == {
        "type": "code", "text": "x = 1", "lang": "python"}


# ── 6. строгий режим поставщика против необязательных полей ───────────────────

# Что модель решает сама: без этих полей значения не бывает. Всё остальное — оформление,
# и его умолчание принадлежит стилю и шаблону, а не догадке модели.
ОБЯЗАТЕЛЬНОЕ = {
    "text": {"text": "абзац"},
    "markdown": {"text": "**б**"},
    "code": {"text": "x = 1"},
    "image": {"artifact": "af_png"},
    "diagram": {"artifact": "af_xml"},
    "table": {"rows": [["а", "б"]]},
    "formula": {"latex": "a=b"},
    "toc": {},
    "page_break": {},
    "blocks": {"items": [{"type": "code", "text": "y = 2"}]},
}


def _строгий_ответ(значение, schema: dict):
    """Ответ, которого потребует строгий режим: каждый обязательный ключ схемы на месте,
    а то, чего модель не задавала, погашено null'ом. Ровно так придёт ответ со ступени 1,
    где ключ пропустить физически нельзя."""
    if isinstance(значение, dict):
        if "anyOf" in schema:                       # помеченное объединение: ветка по метке
            schema = next(b for b in schema["anyOf"]
                          if b["properties"]["type"]["const"] == значение["type"])
        props = schema.get("properties") or {}
        out = {k: _строгий_ответ(v, props.get(k, {})) for k, v in значение.items()}
        return {**{k: None for k in schema.get("required", ())}, **out}
    if isinstance(значение, list) and isinstance(schema.get("items"), dict):
        return [_строгий_ответ(x, schema["items"]) for x in значение]
    return значение


def _через_модель(имя: str, resolve):
    """Полный путь: схема → строгий режим → ответ модели → значение hokoku."""
    model = value_schema(имя, for_model=True)
    ответ = _строгий_ответ({"type": имя, **ОБЯЗАТЕЛЬНОЕ[имя]}, jsonschema.strictify(model))
    assert jsonschema.validate(ответ, jsonschema.strictify(model)) == [], имя
    погашено = jsonschema.drop_unset(ответ, model)
    assert jsonschema.validate(погашено, model) == [], имя
    return value_from_json(погашено, resolve_artifact=resolve)


@pytest.mark.parametrize("имя", VALUE_TYPES)
def test_строгий_режим_не_меняет_значение(имя, resolve):
    """Главный тест стыка с llm: значение, у которого модель погасила всё оформление,
    обязано быть тем же объектом, что и значение вовсе без этих полей. Иначе отчёт
    выходит с чужим оформлением и без единой ошибки — заметить нечем."""
    без_полей = value_from_json({"type": имя, **ОБЯЗАТЕЛЬНОЕ[имя]}, resolve_artifact=resolve)
    assert _через_модель(имя, resolve) == без_полей


def test_умолчания_оформления_переживают_строгий_режим(resolve, png):
    """То же самое поимённо — чтобы в диффе было видно, что именно молча подменялось:
    язык подсветки, шапка таблицы, номер формулы, глубина оглавления, выравнивание."""
    assert _через_модель("code", resolve) == Code("x = 1")          # lang "", а не «python»
    assert _через_модель("table", resolve).header is True
    assert _через_модель("formula", resolve).numbered is True
    assert _через_модель("toc", resolve).levels == 3
    картинка = _через_модель("image", resolve)
    assert картинка.align == "center" and картинка.caption is None and картинка.source == png
    assert _через_модель("blocks", resolve).items == [Code("y = 2")]  # и внутри blocks тоже


def test_подпись_у_картинки_остаётся_трёхзначной():
    """caption null у hokoku значит своё («Рисунок N» без текста) — гасить его нельзя,
    иначе пропадёт разница с false (без подписи и без номера)."""
    полная = jsonschema.strictify(value_schema("image"))
    assert {"const": False} in полная["properties"]["caption"]["anyOf"]
    модели = value_schema("image", for_model=True)
    ответ = {"type": "image", "artifact": "af_png", "caption": None,
             "width_cm": None, "align": None, "ref": None, "v": None}
    assert jsonschema.drop_unset(ответ, модели)["caption"] is None
