"""Валидатор схем: он один на все четыре ступени лестницы, значит его строгость
и есть строгость слоя на нижних ступенях."""
from __future__ import annotations

import copy

import pytest

from llm import jsonschema

SCHEMA = {
    "type": "object",
    "properties": {
        "цель": {"type": "string", "minLength": 3},
        "часов": {"type": "integer", "minimum": 1, "maximum": 100},
        "готово": {"type": "boolean"},
        "теги": {"type": "array", "items": {"type": "string"}, "maxItems": 3},
        "уровень": {"type": "string", "enum": ["низкий", "высокий"]},
    },
    "required": ["цель", "часов"],
    "additionalProperties": False,
}


def test_годное_значение_проходит():
    assert jsonschema.validate({"цель": "сделать", "часов": 5}, SCHEMA) == []


def test_неизвестный_ключ_ловится():
    """Главная защита от «модель выдумала тег»: additionalProperties: false."""
    errors = jsonschema.validate({"цель": "сделать", "часов": 5, "лишний": 1}, SCHEMA)
    assert any("лишний" in e for e in errors)


def test_нет_обязательного_ключа():
    errors = jsonschema.validate({"цель": "сделать"}, SCHEMA)
    assert any("часов" in e for e in errors)


def test_булево_не_проходит_за_целое():
    """bool — подкласс int в Python; для схемы это разные типы, и True вместо 1
    означает, что модель ошиблась."""
    errors = jsonschema.validate({"цель": "сделать", "часов": True}, SCHEMA)
    assert errors


def test_границы_чисел_и_строк():
    errors = jsonschema.validate({"цель": "ок", "часов": 500}, SCHEMA)
    assert len(errors) == 2      # и длина строки, и потолок числа


def test_enum_и_список():
    errors = jsonschema.validate(
        {"цель": "сделать", "часов": 5, "уровень": "средний",
         "теги": ["a", "b", "c", "d"]}, SCHEMA)
    assert any("средний" in e for e in errors)
    assert any("не больше 3" in e for e in errors)


def test_вложенный_объект_даёт_путь_к_ошибке():
    schema = {"type": "object",
              "properties": {"итог": {"type": "object",
                                      "properties": {"n": {"type": "integer"}},
                                      "required": ["n"]}}}
    errors = jsonschema.validate({"итог": {"n": "пять"}}, schema)
    assert errors and "итог.n" in errors[0]


def test_все_ошибки_сразу_а_не_первая():
    """Список, а не исключение: на ступенях 3–4 ошибки едут модели в промпт
    повтора, и нужны они все, а не первая."""
    errors = jsonschema.validate({"часов": "много", "лишний": 1}, SCHEMA)
    assert len(errors) >= 3


# ── проверка самой схемы ────────────────────────────────────────────────────
def test_ref_и_oneof_отвергаются_у_нас_а_не_поставщиком():
    with pytest.raises(jsonschema.SchemaError):
        jsonschema.check_schema({"type": "object", "properties": {"a": {"$ref": "#/x"}}})
    with pytest.raises(jsonschema.SchemaError):
        jsonschema.check_schema({"oneOf": [{"type": "string"}]})


def test_additional_properties_true_не_поддерживается():
    with pytest.raises(jsonschema.SchemaError):
        jsonschema.check_schema({"type": "object", "additionalProperties": True})


def test_годная_схема_проходит():
    jsonschema.check_schema(SCHEMA)


# ── приведение к строгому режиму ────────────────────────────────────────────
def test_strictify_добавляет_required_и_закрывает_объект():
    """Строгий режим у обоих поставщиков требует все ключи в required."""
    out = jsonschema.strictify(SCHEMA)
    assert set(out["required"]) == set(SCHEMA["properties"])
    assert out["additionalProperties"] is False


def test_strictify_идёт_вглубь():
    schema = {"type": "object",
              "properties": {"вложение": {"type": "object",
                                          "properties": {"a": {"type": "string"}}}}}
    out = jsonschema.strictify(schema)
    assert out["properties"]["вложение"]["additionalProperties"] is False
    assert out["properties"]["вложение"]["required"] == ["a"]


def test_strictify_не_портит_исходную_схему():
    before = copy.deepcopy(SCHEMA)
    jsonschema.strictify(SCHEMA)
    assert SCHEMA == before      # глубоко: расширение трогает вложенные dict и enum


# ── необязательность, пережившая строгий режим ──────────────────────────────
# Схема с необязательными полями трёх видов: обычное, перечисление и такое,
# которое null принимает и само (у hokoku это caption — там null значит своё).
OPTIONAL = {
    "type": "object",
    "properties": {
        "type": {"const": "code"},
        "text": {"type": "string"},
        "lang": {"type": "string"},
        "выравнивание": {"enum": ["left", "center", "right"]},
        "подпись": {"anyOf": [{"type": "string"}, {"type": "null"}]},
    },
    "required": ["type", "text"],
    "additionalProperties": False,
}


def test_strictify_даёт_необязательному_полю_способ_промолчать():
    """Строгий режим требует все ключи в required — значит отсутствием поля
    необязательность больше не выразить. Без замены модель обязана выдумать язык
    подсветки и выравнивание, и догадка молча перекроет умолчание шаблона."""
    out = jsonschema.strictify(OPTIONAL)
    assert out["properties"]["lang"]["type"] == ["string", "null"]
    assert None in out["properties"]["выравнивание"]["enum"]
    assert jsonschema.validate({"type": "code", "text": "x = 1", "lang": None,
                                "выравнивание": None, "подпись": None}, out) == []
    jsonschema.check_schema(out)


def test_strictify_не_гасит_обязательное_и_дискриминатор():
    """`type` — метка варианта: по ней валидатор выбирает ветку anyOf, и nullable
    дискриминатор увёл бы разбор в чужой вариант. Обязательное поле null'ом тоже
    не гасится: «не задаю» и «задать обязан» — разные вещи."""
    out = jsonschema.strictify(OPTIONAL)
    assert out["properties"]["type"] == {"const": "code"}
    assert out["properties"]["text"] == {"type": "string"}


def test_strictify_идёт_вглубь_и_расширяет_там_же():
    schema = {"type": "object", "properties": {"блок": {
        "type": "object", "properties": {"a": {"type": "string"}, "b": {"type": "string"}},
        "required": ["a"]}}}
    внутри = jsonschema.strictify(schema)["properties"]["блок"]
    assert внутри["properties"]["b"]["type"] == ["string", "null"]
    assert внутри["properties"]["a"] == {"type": "string"}


def test_strictify_идемпотентен():
    """Второй проход не должен давать ["string", "null", "null"]: strictify зовут
    по своему разу и run_ladder, и api.stream_object."""
    once = jsonschema.strictify(OPTIONAL)
    assert jsonschema.strictify(once) == once


def test_allows_null_перечисление_главнее_типа():
    """У {"type": ["string","null"], "enum": ["a"]} null не проходит перечисление.
    Ошибись здесь — и strictify сочтёт поле уже гасимым, а модель останется без
    законного способа промолчать."""
    assert jsonschema.allows_null({"type": ["string", "null"]})
    assert not jsonschema.allows_null({"type": ["string", "null"], "enum": ["a"]})
    assert jsonschema.allows_null({"enum": ["a", None]})
    assert not jsonschema.allows_null({"const": "code"})
    assert jsonschema.allows_null({})         # без ограничений годится и null


def test_drop_unset_убирает_ровно_то_что_разрешил_strictify():
    """Пара обязана сходиться: что strictify разрешил погасить, drop_unset убирает,
    а чужой null (подпись) остаётся — иначе пропадёт разница между «подписи нет»
    и «подпись без текста»."""
    ответ = {"type": "code", "text": "x = 1", "lang": None,
             "выравнивание": None, "подпись": None}
    assert jsonschema.validate(ответ, jsonschema.strictify(OPTIONAL)) == []
    assert jsonschema.drop_unset(ответ, OPTIONAL) == {
        "type": "code", "text": "x = 1", "подпись": None}
    assert jsonschema.validate(jsonschema.drop_unset(ответ, OPTIONAL), OPTIONAL) == []


def test_drop_unset_не_чинит_ответ_за_модель():
    """Убрать null у обязательного поля или у выдуманного ключа значило бы стереть
    жалобы валидатора: пропали бы и «нет обязательного», и защита от выдуманного
    ключа — ровно то, ради чего стоит additionalProperties: false."""
    ответ = {"type": "code", "text": None, "выдумка": None}
    assert jsonschema.drop_unset(ответ, OPTIONAL) == ответ
    assert len(jsonschema.validate(jsonschema.drop_unset(ответ, OPTIONAL), OPTIONAL)) == 2


def test_drop_unset_идёт_внутрь_вариантов_и_списков():
    """Блоки внутри blocks приходят списком помеченных объектов; не спуститься туда
    значит починить только верхний уровень, а оформление вложенного блока оставить
    выдуманным."""
    schema = {"type": "object", "additionalProperties": False, "required": ["items"],
              "properties": {"items": {"type": "array", "items": {"anyOf": [
                  OPTIONAL,
                  {"type": "object", "additionalProperties": False,
                   "required": ["type", "artifact"],
                   "properties": {"type": {"const": "image"},
                                  "artifact": {"type": "string"},
                                  "align": {"enum": ["left", "center"]}}}]}}}}
    ответ = {"items": [{"type": "code", "text": "x", "lang": None, "выравнивание": None,
                        "подпись": None},
                       {"type": "image", "artifact": "af", "align": None}]}
    assert jsonschema.validate(ответ, jsonschema.strictify(schema)) == []
    assert jsonschema.drop_unset(ответ, schema) == {
        "items": [{"type": "code", "text": "x", "подпись": None},
                  {"type": "image", "artifact": "af"}]}


# ── схема словами ───────────────────────────────────────────────────────────
def test_describe_перечисляет_ключи_по_русски():
    text = jsonschema.describe(SCHEMA)
    assert "цель" in text and "обязательно" in text
    assert "готово" in text and "необязательно" in text
    assert "других ключей быть не должно" in text


# ── const, границы-исключающие, помеченное объединение ──────────────────────
UNION = {"anyOf": [
    {"type": "object",
     "properties": {"type": {"const": "text"}, "text": {"type": "string"}},
     "required": ["type", "text"], "additionalProperties": False},
    {"type": "object",
     "properties": {"type": {"const": "image"}, "artifact": {"type": "string"},
                    "width_cm": {"type": ["number", "null"], "exclusiveMinimum": 0}},
     "required": ["type", "artifact"], "additionalProperties": False},
]}


def test_const_проверяется_а_не_украшает():
    """Дискриминатор помеченного объединения — единственный способ выразить
    «этот объект именно markdown», и не проверять его нельзя."""
    schema = {"type": "object", "properties": {"type": {"const": "markdown"}}}
    assert jsonschema.validate({"type": "markdown"}, schema) == []
    errors = jsonschema.validate({"type": "code"}, schema)
    assert errors and "markdown" in errors[0]


def test_const_различает_ложь_и_ноль():
    """0 == False в Python, но не в JSON: caption: false — не то же, что caption: 0."""
    assert jsonschema.validate(False, {"const": False}) == []
    assert jsonschema.validate(0, {"const": False}) != []
    assert jsonschema.validate(True, {"const": 1}) != []
    assert jsonschema.validate("markdown", {"enum": [1]}) != []


def test_исключающие_границы():
    """По 2020-12 exclusiveMinimum — число: ширина 0 см не бывает."""
    schema = {"type": "number", "exclusiveMinimum": 0, "exclusiveMaximum": 100}
    assert jsonschema.validate(0.1, schema) == []
    assert jsonschema.validate(0, schema) != []
    assert jsonschema.validate(100, schema) != []


def test_исключающая_граница_флагом_отвергается():
    """draft-04 писал их булевыми при minimum; молча принять — значит не проверять."""
    with pytest.raises(jsonschema.SchemaError, match="exclusiveMinimum"):
        jsonschema.check_schema({"type": "number", "minimum": 0, "exclusiveMinimum": True})


def test_anyof_годен_если_подошёл_вариант():
    jsonschema.check_schema(UNION)
    assert jsonschema.validate({"type": "text", "text": "а"}, UNION) == []
    assert jsonschema.validate({"type": "image", "artifact": "af", "width_cm": 5}, UNION) == []


def test_anyof_берёт_ошибки_у_варианта_по_метке():
    """Иначе в промпт повтора уехали бы претензии всех вариантов сразу, и модель
    чинила бы не то: «нет text» в объекте, который вовсе не text."""
    errors = jsonschema.validate({"type": "image"}, UNION)
    assert errors == ["объект: нет обязательного ключа 'artifact'"]
    errors = jsonschema.validate({"type": "image", "artifact": "af", "width_cm": 0}, UNION)
    assert errors and "width_cm" in errors[0]


def test_anyof_без_метки_одна_понятная_ошибка():
    errors = jsonschema.validate({"type": "видео"}, UNION)
    assert len(errors) == 1 and "ни под один вариант" in errors[0]
    assert "'text'" in errors[0] and "'image'" in errors[0]


def test_oneof_по_прежнему_запрещён():
    """anyOf строгий режим OpenAI принимает, oneOf — нет. На непересекающихся
    вариантах они значат одно и то же, значит писать надо тот, который примут."""
    with pytest.raises(jsonschema.SchemaError):
        jsonschema.check_schema({"oneOf": [{"type": "string"}]})
    with pytest.raises(jsonschema.SchemaError, match="anyOf"):
        jsonschema.check_schema({"anyOf": []})
    with pytest.raises(jsonschema.SchemaError):
        jsonschema.check_schema({"anyOf": [{"$ref": "#/x"}]})


def test_strictify_идёт_внутрь_вариантов():
    """Без этого блоки внутри blocks уехали бы к поставщику нестрогими — а узнали
    бы мы об этом по 400 в проде, а не тестом."""
    out = jsonschema.strictify(UNION)
    assert out["anyOf"][0]["required"] == ["type", "text"]
    assert out["anyOf"][1]["additionalProperties"] is False
    assert UNION["anyOf"][1]["required"] == ["type", "artifact"]      # исходник цел


def test_describe_рассказывает_про_варианты():
    """На ступенях 3–4 схема едет словами, и «любое значение» вместо списка
    вариантов означало бы, что модель про blocks ничего не узнала."""
    text = jsonschema.describe({"type": "object", "properties": {"items": {
        "type": "array", "items": UNION}}})
    assert "вариант" in text and "'text'" in text and "artifact" in text
