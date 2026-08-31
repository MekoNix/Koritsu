"""
jsonschema — маленький валидатор подмножества JSON Schema.

Зачем свой, а не библиотека: на ступенях 3–4 лестницы (А.3) проверять пришедшее
обязаны мы сами, и проверка должна быть **той же самой**, что на ступенях 1–2.
Одна проверка на все четыре ступени — важное свойство: разница между ступенями
только в вероятности, что валидатор ругнётся, а не в строгости правил.
Зависимость ради двух сотен строк тащить не хотелось.

Поддерживаемое подмножество (сознательно узкое — что умеют строгие режимы
обоих поставщиков):

  type: object | array | string | number | integer | boolean | null
        (и список типов: ["string", "null"])
  properties, required, additionalProperties (только False — «неизвестный ключ»)
  items (одна схема), minItems, maxItems
  enum, const
  minLength, maxLength, pattern
  minimum, maximum, exclusiveMinimum, exclusiveMaximum
  anyOf — только как помеченное объединение (у каждого варианта дискриминатор
        `type` с `const`); строгий режим OpenAI принимает именно anyOf
  description, title — игнорируются, они для модели

Чего нет намеренно: $ref, oneOf/allOf, зависимости, форматы. Строгие режимы
поставщиков их либо не принимают, либо принимают по-разному, а «схема, которая
у нас проходит, а у поставщика 400» — худший из миров. oneOf запрещён и после
того, как anyOf разрешён: на непересекающихся вариантах они значат одно и то
же, а принимают поставщики только второй — значит и писать надо только второй.
"""
from __future__ import annotations

import re


class SchemaError(Exception):
    """Схема составлена неправильно (наша ошибка, не модели)."""


_TYPES = {
    "object": dict,
    "array": list,
    "string": str,
    "boolean": bool,
    "null": type(None),
}


def _type_ok(value, name: str) -> bool:
    """Проверка одного имени типа. `integer` и `number` — особые случаи.

    bool в Python — подкласс int, поэтому True прошло бы как integer. Для схемы
    это ошибка: модель, вернувшая true вместо 1, ошиблась, и мы обязаны это
    заметить.
    """
    if name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if name == "boolean":
        return isinstance(value, bool)
    expected = _TYPES.get(name)
    if expected is None:
        raise SchemaError(f"неизвестный тип в схеме: {name!r}")
    if expected is str:
        return isinstance(value, str)
    return isinstance(value, expected) and not isinstance(value, bool)


def _same(value, expected) -> bool:
    """Равенство по правилам JSON, а не Python: True == 1, но `const: false`
    обязан отвергнуть 0 — иначе проверка дискриминатора стала бы украшением.
    """
    if isinstance(value, bool) or isinstance(expected, bool):
        return isinstance(value, bool) and isinstance(expected, bool) and value == expected
    return value == expected


def _path(prefix: str, key) -> str:
    if isinstance(key, int):
        return f"{prefix}[{key}]"
    return f"{prefix}.{key}" if prefix else str(key)


def validate(value, schema: dict, where: str = "") -> list:
    """Проверяет значение по схеме. Возвращает список ошибок (пустой — годно).

    Возвращает список, а не бросает: на ступенях 3–4 ошибки нужно показать
    модели в промпте повтора («ты вернул вот это, вот что не так»), а для
    этого их нужно все сразу, а не первую.
    """
    errors: list = []
    _walk(value, schema or {}, where, errors)
    return errors


def _walk(value, schema: dict, where: str, errors: list) -> None:
    if not isinstance(schema, dict):
        raise SchemaError(f"схема в {where or 'корне'} не объект")

    # тип: строка или список строк
    declared = schema.get("type")
    if declared is not None:
        names = declared if isinstance(declared, list) else [declared]
        if not any(_type_ok(value, n) for n in names):
            errors.append(f"{where or 'значение'}: ожидался тип {'/'.join(names)}, "
                          f"пришёл {type(value).__name__}")
            return   # дальше проверять бессмысленно: правила зависят от типа

    if "enum" in schema:
        allowed = schema["enum"]
        if not any(_same(value, x) for x in allowed):
            errors.append(f"{where or 'значение'}: {value!r} не из списка {allowed!r}")

    if "const" in schema and not _same(value, schema["const"]):
        errors.append(f"{where or 'значение'}: {value!r} вместо {schema['const']!r}")

    if "anyOf" in schema:
        _walk_any_of(value, schema["anyOf"], where, errors)

    if isinstance(value, dict):
        _walk_object(value, schema, where, errors)
    elif isinstance(value, list):
        _walk_array(value, schema, where, errors)
    elif isinstance(value, str):
        _walk_string(value, schema, where, errors)
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        _walk_number(value, schema, where, errors)


def _walk_any_of(value, branches, where: str, errors: list) -> None:
    """Помеченное объединение: годен, если подошёл хоть один вариант.

    Если не подошёл ни один, ошибки берём у варианта, выбранного по дискриминатору
    (`type`), а не сваливаем все сразу: модели в промпте повтора нужно «в блоке
    image нет artifact», а не девять списков претензий от чужих вариантов.
    """
    for branch in branches:
        attempt: list = []
        _walk(value, branch, where, attempt)
        if not attempt:
            return
    picked = _by_tag(value, branches)
    if picked is None:
        names = [tag for tag in (_tag_of(b) for b in branches) if tag is not None]
        hint = f" (ожидался один из: {', '.join(map(repr, names))})" if names else ""
        errors.append(f"{where or 'значение'}: не подходит ни под один вариант{hint}")
        return
    _walk(value, picked, where, errors)


def _tag_of(branch) -> object:
    """Значение дискриминатора варианта — `properties.type.const`, если он есть."""
    if not isinstance(branch, dict):
        return None
    return ((branch.get("properties") or {}).get("type") or {}).get("const")


def _by_tag(value, branches):
    if not isinstance(value, dict):
        return None
    for branch in branches:
        tag = _tag_of(branch)
        if tag is not None and _same(value.get("type"), tag):
            return branch
    return None


def _walk_object(value: dict, schema: dict, where: str, errors: list) -> None:
    props = schema.get("properties") or {}
    for name in schema.get("required") or []:
        if name not in value:
            errors.append(f"{where or 'объект'}: нет обязательного ключа {name!r}")
    # Неизвестный ключ — отдельная ошибка, а не мелочь: именно она ловит
    # «модель выдумала тег», ради чего в схемах и стоит additionalProperties: false.
    if schema.get("additionalProperties") is False:
        for name in value:
            if name not in props:
                errors.append(f"{where or 'объект'}: неизвестный ключ {name!r}")
    for name, sub in props.items():
        if name in value:
            _walk(value[name], sub, _path(where, name), errors)


def _walk_array(value: list, schema: dict, where: str, errors: list) -> None:
    if "minItems" in schema and len(value) < schema["minItems"]:
        errors.append(f"{where or 'список'}: элементов {len(value)}, "
                      f"нужно не меньше {schema['minItems']}")
    if "maxItems" in schema and len(value) > schema["maxItems"]:
        errors.append(f"{where or 'список'}: элементов {len(value)}, "
                      f"нужно не больше {schema['maxItems']}")
    item_schema = schema.get("items")
    if isinstance(item_schema, dict):
        for i, item in enumerate(value):
            _walk(item, item_schema, _path(where, i), errors)


def _walk_string(value: str, schema: dict, where: str, errors: list) -> None:
    if "minLength" in schema and len(value) < schema["minLength"]:
        errors.append(f"{where or 'строка'}: длина {len(value)}, "
                      f"нужно не меньше {schema['minLength']}")
    if "maxLength" in schema and len(value) > schema["maxLength"]:
        errors.append(f"{where or 'строка'}: длина {len(value)}, "
                      f"нужно не больше {schema['maxLength']}")
    pattern = schema.get("pattern")
    if pattern:
        try:
            if re.search(pattern, value) is None:
                errors.append(f"{where or 'строка'}: не подходит под шаблон {pattern!r}")
        except re.error as exc:
            raise SchemaError(f"кривой pattern в {where or 'корне'}: {exc}")


def _walk_number(value, schema: dict, where: str, errors: list) -> None:
    if "minimum" in schema and value < schema["minimum"]:
        errors.append(f"{where or 'число'}: {value} меньше {schema['minimum']}")
    if "maximum" in schema and value > schema["maximum"]:
        errors.append(f"{where or 'число'}: {value} больше {schema['maximum']}")
    # По 2020-12 это числа, а не булевы флаги при minimum/maximum (так было в draft-04).
    if "exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"]:
        errors.append(f"{where or 'число'}: {value} не больше {schema['exclusiveMinimum']}")
    if "exclusiveMaximum" in schema and value >= schema["exclusiveMaximum"]:
        errors.append(f"{where or 'число'}: {value} не меньше {schema['exclusiveMaximum']}")


def check_schema(schema: dict) -> None:
    """Проверяет, что схема из поддерживаемого подмножества. Бросает SchemaError.

    Вызывается один раз при сборке запроса, а не в горячем пути. Смысл — поймать
    $ref и oneOf у себя, а не получить 400 от поставщика с невнятным текстом.
    """
    _check(schema, "")


_UNSUPPORTED = ("$ref", "oneOf", "allOf", "not", "if", "then", "else",
                "patternProperties", "dependentSchemas", "$defs", "definitions")

_KNOWN = ("type", "properties", "required", "additionalProperties", "items",
          "enum", "const", "anyOf", "minItems", "maxItems", "minLength", "maxLength",
          "pattern", "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum",
          "description", "title", "default", "examples")


def _check(schema, where: str) -> None:
    if not isinstance(schema, dict):
        raise SchemaError(f"схема в {where or 'корне'} не объект")
    for key in _UNSUPPORTED:
        if key in schema:
            raise SchemaError(f"{where or 'корень'}: {key} не поддерживается "
                              f"(строгие режимы поставщиков его тоже понимают по-разному)")
    for key in schema:
        if key not in _KNOWN and not key.startswith("x-"):
            raise SchemaError(f"{where or 'корень'}: неизвестное ключевое слово {key!r}")
    declared = schema.get("type")
    if declared is not None:
        for name in (declared if isinstance(declared, list) else [declared]):
            if name not in ("object", "array", "string", "number", "integer",
                            "boolean", "null"):
                raise SchemaError(f"{where or 'корень'}: неизвестный тип {name!r}")
    if schema.get("additionalProperties") not in (None, False):
        raise SchemaError(f"{where or 'корень'}: additionalProperties поддерживается "
                          f"только как false")
    if "const" in schema and not isinstance(schema["const"], (str, int, float, bool, type(None))):
        raise SchemaError(f"{where or 'корень'}: const только для простого значения, "
                          f"не для объекта или списка")
    for key in ("exclusiveMinimum", "exclusiveMaximum"):
        bound = schema.get(key)
        if key in schema and (isinstance(bound, bool) or not isinstance(bound, (int, float))):
            raise SchemaError(f"{where or 'корень'}: {key} — число (2020-12), "
                              f"а не флаг при minimum/maximum")
    if "anyOf" in schema:
        branches = schema["anyOf"]
        if not isinstance(branches, list) or not branches:
            raise SchemaError(f"{where or 'корень'}: anyOf — непустой список схем")
        for i, branch in enumerate(branches):
            _check(branch, _path(where, f"anyOf[{i}]"))
    for name, sub in (schema.get("properties") or {}).items():
        _check(sub, _path(where, name))
    if isinstance(schema.get("items"), dict):
        _check(schema["items"], _path(where, "items"))


def allows_null(schema) -> bool:
    """Принимает ли схема null сама по себе. От этого зависит, что null значит.

    Порядок проверок неслучаен: перечисление главнее типа. У
    `{"type": ["string", "null"], "enum": ["a"]}` null не проходит enum, и счесть
    такое поле «уже гасимым» значило бы отдать поставщику схему, по которой
    модель не может ответить, — а узнали бы мы об этом по 400 в проде.
    """
    if not isinstance(schema, dict):
        return True
    if "const" in schema:
        return schema["const"] is None
    if "enum" in schema:
        return any(x is None for x in schema["enum"])
    if "anyOf" in schema:
        return any(allows_null(x) for x in schema["anyOf"])
    declared = schema.get("type")
    if declared is None:
        return True                  # без ограничений годится что угодно, в том числе null
    return "null" in (declared if isinstance(declared, list) else [declared])


def _nullable(schema: dict) -> dict:
    """Та же схема плюс null — тем способом, который принимают строгие режимы.

    `const` не расширяем: законное значение у него ровно одно, выдумывать модели
    там нечего, а nullable-дискриминатор увёл бы разбор варианта не в ту ветку.
    """
    if "const" in schema:
        return schema
    out = dict(schema)
    if "anyOf" in out:
        return {**out, "anyOf": list(out["anyOf"]) + [{"type": "null"}]}
    if "enum" in out:
        out["enum"] = list(out["enum"]) + [None]
    declared = out.get("type")
    if declared is not None:
        names = list(declared) if isinstance(declared, list) else [declared]
        out["type"] = names + ["null"]
    return out


def strictify(schema: dict) -> dict:
    """Готовит схему к строгому режиму поставщика: у объектов — все ключи в
    `required`, `additionalProperties: false`, а необязательным полям добавлен null.

    Зачем: строгий режим и у Anthropic, и у OpenAI требует, чтобы каждый ключ из
    `properties` был перечислен в `required`, иначе запрос отвергается. Значит
    отсутствием поля необязательность больше не выразить — и если ничего не дать
    взамен, модель **обязана выдумать** язык подсветки, выравнивание и глубину
    оглавления, а её догадка молча перекроет умолчание стиля и шаблона. Ошибки при
    этом не будет ни одной: отчёт просто выйдет с чужим оформлением.

    Взамен даётся null — «этого поля я не задаю». Обратно его убирает `drop_unset`
    по тому же признаку `allows_null`; пара обязана меняться только вместе.
    """
    if not isinstance(schema, dict):
        return schema
    out = dict(schema)
    props = out.get("properties")
    if isinstance(props, dict):
        was_required = set(out.get("required") or ())    # запоминаем до того, как перепишем
        prepared = {}
        for name, sub in props.items():
            sub = strictify(sub)
            if name not in was_required and not allows_null(sub):
                sub = _nullable(sub)
            prepared[name] = sub
        out["properties"] = prepared
        out["required"] = list(prepared)
        out["additionalProperties"] = False
    if isinstance(out.get("items"), dict):
        out["items"] = strictify(out["items"])
    if isinstance(out.get("anyOf"), list):
        # Варианты объединения — такие же объекты, и строгий режим требует того же
        # от них: без этого блоки внутри blocks уехали бы к поставщику нестрогими.
        out["anyOf"] = [strictify(x) for x in out["anyOf"]]
    return out


def drop_unset(value, schema: dict):
    """Убирает null'ы, которыми модель сказала «этого поля я не задаю».

    Зеркало `strictify`: гасится ровно то, что оно расширило, — поле, которого
    исходная схема не требует и null'а сама не принимает. Цена ошибки в обе
    стороны. Не убрать — null уедет в значение как настоящий и перекроет
    умолчание шаблона (у hokoku это `code.lang`, `table.header`, `toc.levels`).
    Убрать лишнее — пропадёт и чужой смысл null'а (`image.caption`: null — подпись
    «Рисунок N» без текста, а не отсутствие подписи), и жалобы валидатора на
    выдуманный ключ и на пропущенное обязательное поле, то есть ответ окажется
    починен за модель.
    """
    if not isinstance(schema, dict):
        return value
    if isinstance(value, dict):
        props = schema.get("properties")
        if props is None and isinstance(schema.get("anyOf"), list):
            branch = _by_tag(value, schema["anyOf"])     # ветка объединения — по метке
            return drop_unset(value, branch) if branch is not None else value
        props = props or {}
        required = set(schema.get("required") or ())
        out = {}
        for name, item in value.items():
            sub = props.get(name)
            if sub is None:
                out[name] = item                         # выдуманный ключ ловит валидатор
            elif item is None and name not in required and not allows_null(sub):
                continue
            else:
                out[name] = drop_unset(item, sub)
        return out
    if isinstance(value, list) and isinstance(schema.get("items"), dict):
        return [drop_unset(x, schema["items"]) for x in value]
    return value


def describe(schema: dict, indent: int = 0) -> str:
    """Схема словами — для ступеней 3 и 4, где схему в запрос не положишь.

    Модель на этих ступенях видит только промпт, поэтому требования надо
    проговорить. Формат нарочно человеческий, а не JSON: JSON в промпте модель
    склонна копировать как пример ответа.
    """
    pad = "  " * indent
    lines: list = []
    kind = schema.get("type")
    if schema.get("anyOf"):
        for sub in schema["anyOf"]:
            lines.append(f"{pad}- вариант {_type_words(sub)}:")
            lines.append(describe(sub, indent + 1))
    elif kind == "object":
        props = schema.get("properties") or {}
        required = set(schema.get("required") or [])
        for name, sub in props.items():
            mark = "обязательно" if name in required else "необязательно"
            lines.append(f"{pad}- {name} ({_type_words(sub)}, {mark})"
                         + (f" — {sub['description']}" if sub.get("description") else ""))
            if sub.get("type") in ("object", "array"):
                lines.append(describe(sub, indent + 1))
        if schema.get("additionalProperties") is False:
            lines.append(f"{pad}  других ключей быть не должно")
    elif kind == "array":
        item = schema.get("items") or {}
        lines.append(f"{pad}  элементы списка: {_type_words(item)}")
        if item.get("type") in ("object", "array") or item.get("anyOf"):
            lines.append(describe(item, indent + 1))
    return "\n".join(x for x in lines if x.strip())


_TYPE_WORDS = {"string": "строка", "number": "число", "integer": "целое число",
               "boolean": "да/нет", "object": "объект", "array": "список",
               "null": "пусто"}


def _type_words(schema: dict) -> str:
    if "const" in schema:
        return f"ровно {schema['const']!r}"
    tag = _tag_of(schema)
    if tag is not None:              # вариант объединения зовём его меткой, а не «объект»
        return f"{_TYPE_WORDS['object']} {tag!r}"
    declared = schema.get("type")
    if declared is None:
        if schema.get("anyOf"):
            return "один из вариантов: " + ", ".join(_type_words(x) for x in schema["anyOf"])
        return "любое значение"
    names = declared if isinstance(declared, list) else [declared]
    words = " или ".join(_TYPE_WORDS.get(n, n) for n in names)
    if schema.get("enum"):
        words += " из: " + ", ".join(repr(x) for x in schema["enum"])
    return words


__all__ = ["validate", "check_schema", "strictify", "drop_unset", "allows_null",
           "describe", "SchemaError"]
