"""Лестница структурированного вывода (А.3) и повторы.

Главное, что здесь проверяется: значение, добытое любой из четырёх ступеней,
проходит один и тот же валидатор и приходит вызывающему в одном и том же виде.
Вызывающий код не должен знать, какой ступенью оно добыто.
"""
from __future__ import annotations

import llm
from llm import Stop, Structured
from llm import structured

from .conftest import openai_stream, stream_response

SCHEMA = {
    "type": "object",
    "properties": {"цель": {"type": "string"}, "часов": {"type": "integer"}},
    "required": ["цель", "часов"],
    "additionalProperties": False,
}
ГОДНОЕ = '{"цель": "сделать отчёт", "часов": 40}'


def _usage(n_in=100, n_out=20):
    return {"prompt_tokens": n_in, "completion_tokens": n_out}


# ── извлечение JSON из текста ───────────────────────────────────────────────
def test_чистый_json_разбирается():
    assert structured.extract_json(ГОДНОЕ)["часов"] == 40


def test_json_в_заборе_разбирается():
    text = 'Вот ответ:\n```json\n{"a": 1}\n```\nГотово.'
    assert structured.extract_json(text) == {"a": 1}


def test_фигурная_скобка_в_значении_не_сбивает_поиск():
    """Наивный поиск по первой и последней скобке здесь ломается, а значения
    тегов — сплошь человеческий текст, в котором бывает всё."""
    text = 'Пояснение. {"текст": "формула {x} внутри", "n": 1} Конец.'
    assert structured.extract_json(text) == {"текст": "формула {x} внутри", "n": 1}


def test_пустой_ответ_даёт_ошибку():
    import pytest
    with pytest.raises(ValueError):
        structured.extract_json("   ")


# ── ступени ─────────────────────────────────────────────────────────────────
def test_ступень_1_схема_в_запросе(make_endpoint):
    spec, rec = make_endpoint([stream_response(openai_stream(ГОДНОЕ, usage=_usage()))])
    spec.declared.structured_output = Structured.JSON_SCHEMA
    result = llm.generate_object(spec.id, SCHEMA, "дай значения")
    assert result.ok and result.value["часов"] == 40
    assert result.structured_step == Structured.JSON_SCHEMA
    assert result.attempts == 1
    assert rec.last["response_format"]["type"] == "json_schema"


def test_ступень_2_строгий_инструмент(make_endpoint):
    """Ступень 2 выше ступени 3 намеренно: инструмент со схемой не даёт модели
    выдумать ключ, а режим JSON гарантирует только валидный JSON."""
    calls = [{"index": 0, "id": "c1",
              "function": {"name": "set_values", "arguments": ГОДНОЕ}}]
    spec, rec = make_endpoint([stream_response(
        openai_stream("", usage=_usage(), finish="tool_calls", tool_calls=calls))])
    spec.declared.structured_output = Structured.TOOL_STRICT
    result = llm.generate_object(spec.id, SCHEMA, "дай значения")
    assert result.ok and result.value["цель"] == "сделать отчёт"
    assert result.structured_step == Structured.TOOL_STRICT
    assert rec.last["tool_choice"]["function"]["name"] == "set_values"


def test_ступень_3_режим_json_со_схемой_словами(make_endpoint):
    spec, rec = make_endpoint([stream_response(openai_stream(ГОДНОЕ, usage=_usage()))])
    spec.declared.structured_output = Structured.JSON_OBJECT
    result = llm.generate_object(spec.id, SCHEMA, "дай значения")
    assert result.ok and result.structured_step == Structured.JSON_OBJECT
    assert rec.last["response_format"] == {"type": "json_object"}
    # Схему в запрос не положишь — значит она проговорена словами в промпте.
    промпт = " ".join(m["content"] for m in rec.last["messages"])
    assert "часов" in промпт and "обязательно" in промпт


def test_ступень_4_разбор_из_текста(make_endpoint):
    ответ = f"Конечно, вот значения:\n```json\n{ГОДНОЕ}\n```"
    spec, rec = make_endpoint([stream_response(openai_stream(ответ, usage=_usage()))])
    spec.declared.structured_output = Structured.TEXT
    result = llm.generate_object(spec.id, SCHEMA, "дай значения")
    assert result.ok and result.value["часов"] == 40
    assert result.structured_step == Structured.TEXT
    assert "response_format" not in rec.last


# ── необязательное поле на строгой ступени ──────────────────────────────────
С_НЕОБЯЗАТЕЛЬНЫМ = {
    "type": "object",
    "properties": {"цель": {"type": "string"}, "язык": {"type": "string"}},
    "required": ["цель"],
    "additionalProperties": False,
}


def test_необязательное_поле_гасится_null_а_не_выдумывается(make_endpoint):
    """Дефект, спавший на json_object: строгий режим требует все ключи в required,
    и без замены модель обязана выдумать «язык» — а выдумка молча перекрыла бы
    умолчание. Схема к поставщику уезжает с null'ом, ответ с null'ом проходит, и
    до вызывающего значение доходит вовсе без ключа — как со ступеней 3–4."""
    ответ = '{"цель": "сделать отчёт", "язык": null}'
    spec, rec = make_endpoint([stream_response(openai_stream(ответ, usage=_usage()))])
    spec.declared.structured_output = Structured.JSON_SCHEMA
    result = llm.generate_object(spec.id, С_НЕОБЯЗАТЕЛЬНЫМ, "дай значения")
    assert result.ok and result.value == {"цель": "сделать отчёт"}
    отдано = rec.last["response_format"]["json_schema"]["schema"]
    assert set(отдано["required"]) == {"цель", "язык"}
    assert отдано["properties"]["язык"]["type"] == ["string", "null"]


def test_гашение_одинаково_на_всех_ступенях(make_endpoint):
    """Обещание модуля: вызывающий не должен знать, какой ступенью добыто значение.
    На ступени 3 схема к поставщику не ездит, но null «я не задаю» модель шлёт всё
    равно, и повтор из-за него был бы деньгами за ту же самую мысль."""
    ответ = '{"цель": "сделать отчёт", "язык": null}'
    spec, rec = make_endpoint([stream_response(openai_stream(ответ, usage=_usage()))])
    spec.declared.structured_output = Structured.JSON_OBJECT
    result = llm.generate_object(spec.id, С_НЕОБЯЗАТЕЛЬНЫМ, "дай значения")
    assert result.ok and result.attempts == 1
    assert result.value == {"цель": "сделать отчёт"}


def test_null_в_обязательном_поле_остаётся_ошибкой(make_endpoint):
    """Гасить можно только необязательное: «цель: null» — не «я не задаю», а
    невыполненное требование, и молча стереть его значило бы вернуть пустой отчёт."""
    spec, rec = make_endpoint([stream_response(openai_stream('{"цель": null}', usage=_usage()))])
    spec.declared.structured_output = Structured.JSON_SCHEMA
    result = llm.generate_object(spec.id, С_НЕОБЯЗАТЕЛЬНЫМ, "дай значения")
    assert not result.ok and "цель" in result.error.message


def test_ступень_не_поднимается_выше_объявленной(make_endpoint):
    """Заявка endpoint'а — потолок: просить json_schema там, где её нет,
    значит получить 400 на первом же боевом вызове."""
    spec, rec = make_endpoint([stream_response(openai_stream(ГОДНОЕ, usage=_usage()))])
    spec.declared.structured_output = Structured.JSON_OBJECT
    result = llm.generate_object(spec.id, SCHEMA, "дай")
    assert result.structured_step == Structured.JSON_OBJECT


def test_проба_перекрывает_заявку(make_endpoint):
    """Заявили json_schema, проба добилась только json_object — работаем по
    json_object (Б.4)."""
    spec, rec = make_endpoint([stream_response(openai_stream(ГОДНОЕ, usage=_usage()))])
    spec.declared.structured_output = Structured.JSON_SCHEMA
    # Через реестр, а не присваиванием: у результата пробы одна дверь
    # (`registry.update_probe`), и тест, который ходит мимо неё, перестаёт
    # проверять тот путь, которым проба попадает в описание на самом деле.
    llm.update_probe(spec.id, llm.Probe(at="2026-08-29T12:00:00Z", ok=True,
                                        structured_output=Structured.JSON_OBJECT))
    caps = llm.capabilities(spec.id)
    assert caps.structured_output == Structured.JSON_OBJECT
    assert caps.is_confirmed("structured_output")
    result = llm.generate_object(spec.id, SCHEMA, "дай")
    assert result.structured_step == Structured.JSON_OBJECT


# ── повторы ─────────────────────────────────────────────────────────────────
def test_битый_json_повторяется_и_чинится(make_endpoint):
    spec, rec = make_endpoint([
        stream_response(openai_stream("это не json вовсе", usage=_usage(100, 10))),
        stream_response(openai_stream(ГОДНОЕ, usage=_usage(200, 20))),
    ])
    spec.declared.structured_output = Structured.JSON_OBJECT
    result = llm.generate_object(spec.id, SCHEMA, "дай")
    assert result.ok and result.attempts == 2
    # Повторы — настоящие вызовы за настоящие деньги: расход суммируется.
    assert result.usage.input == 300 and result.usage.output == 30


def test_в_промпт_повтора_едет_разбор_ошибок(make_endpoint):
    """Без показа модели её собственного ответа повтор — та же лотерея."""
    spec, rec = make_endpoint([
        stream_response(openai_stream('{"цель": "ок"}', usage=_usage())),
        stream_response(openai_stream(ГОДНОЕ, usage=_usage())),
    ])
    spec.declared.structured_output = Structured.JSON_OBJECT
    llm.generate_object(spec.id, SCHEMA, "дай")
    повтор = " ".join(m["content"] for m in rec.requests[1]["messages"])
    assert "Предыдущий ответ не подошёл" in повтор
    assert "часов" in повтор


def test_повторы_кончаются_и_отказ_внятный(make_endpoint):
    """Три попытки (первая плюс два повтора), потом отказ с расходом."""
    spec, rec = make_endpoint([stream_response(openai_stream("мусор", usage=_usage(50, 5)))
                               for _ in range(3)])
    spec.declared.structured_output = Structured.JSON_OBJECT
    result = llm.generate_object(spec.id, SCHEMA, "дай")
    assert not result.ok and result.attempts == 3
    assert result.error.kind == llm.ErrorKind.BAD_RESPONSE
    assert result.usage.input == 150      # расход всех трёх попыток
    assert result.units > 0


def test_на_ступенях_1_и_2_повторов_нет(make_endpoint):
    """Если уж схема в запросе не помогла, повтор не поможет: сломано другое."""
    spec, rec = make_endpoint([stream_response(openai_stream("мусор", usage=_usage()))])
    spec.declared.structured_output = Structured.JSON_SCHEMA
    result = llm.generate_object(spec.id, SCHEMA, "дай")
    assert not result.ok and result.attempts == 1
    assert len(rec.requests) == 1


def test_отказ_модели_не_повторяется(make_endpoint):
    """Отказ — законный исход; второй заход даст тот же отказ за вторые деньги."""
    spec, rec = make_endpoint([stream_response(
        openai_stream("не могу", usage=_usage(), finish="content_filter"))])
    spec.declared.structured_output = Structured.JSON_OBJECT
    result = llm.generate_object(spec.id, SCHEMA, "дай")
    assert result.stop == Stop.REFUSED and not result.ok
    assert result.attempts == 1 and len(rec.requests) == 1
    assert result.usage.input == 100      # расход на отказе есть и он записан


def test_неизвестный_ключ_считается_ошибкой_и_вызывает_повтор(make_endpoint):
    """Это и есть защита «модель выдумала тег» на нижних ступенях."""
    spec, rec = make_endpoint([
        stream_response(openai_stream('{"цель":"а","часов":1,"выдумка":9}', usage=_usage())),
        stream_response(openai_stream(ГОДНОЕ, usage=_usage())),
    ])
    spec.declared.structured_output = Structured.JSON_OBJECT
    result = llm.generate_object(spec.id, SCHEMA, "дай")
    assert result.ok and result.attempts == 2
    assert "выдумка" in " ".join(m["content"] for m in rec.requests[1]["messages"])


# ── пометки деградации ──────────────────────────────────────────────────────
def test_degraded_объясняет_цифры_а_не_пугает_пользователя(make_endpoint):
    """`degraded` — объяснение, почему вызов стоил столько, для журнала."""
    spec, rec = make_endpoint([stream_response(openai_stream(ГОДНОЕ, usage=_usage()))])
    spec.declared.structured_output = Structured.JSON_OBJECT
    result = llm.generate_object(spec.id, SCHEMA, "дай")
    assert "no_json_schema" in result.degraded
    assert "schema_checked_locally" in result.degraded
    assert "no_effort" in result.degraded


def test_на_полном_endpointе_деградаций_меньше(make_endpoint):
    spec = llm.presets.anthropic(api_key_env="TEST_KEY_UNUSED")
    from .conftest import anthropic_stream
    spec, rec = make_endpoint([stream_response(anthropic_stream(
        ГОДНОЕ, usage_in={"input_tokens": 100}, usage_out={"output_tokens": 20}))],
        spec=spec)
    result = llm.generate_object(spec.id, SCHEMA, "дай")
    assert result.ok and result.degraded == []


# ── обрыв по потолку и флаг счётчиков ───────────────────────────────────────
def test_обрыв_по_потолку_не_повторяется_и_виден_причиной(make_endpoint):
    """Обрезанный ответ не разбирается, но повтор с тем же потолком обрежет его
    в том же месте. Вызывающему нужна причина `max_tokens`, а не `bad_response`:
    лечится это большим потолком, а не другим промптом."""
    spec, rec = make_endpoint([stream_response(
        openai_stream('{"цель": "сделать отч', usage=_usage(), finish="length"))])
    spec.declared.structured_output = Structured.JSON_OBJECT
    result = llm.generate_object(spec.id, SCHEMA, "дай")
    assert result.stop == Stop.MAX_TOKENS
    assert not result.ok and result.attempts == 1
    assert len(rec.requests) == 1                  # повтора не было
    assert result.usage.input == 100               # расход обрезанного вызова учтён


def test_проба_отменяет_лишний_флаг_include_usage(make_endpoint):
    """Проба перекрывает заявку не только по ступени лестницы: если usage
    приходит и без флага, флаг лишний, а лишнее поле — риск 400."""
    spec, rec = make_endpoint([stream_response(openai_stream(ГОДНОЕ, usage=_usage()))])
    spec.declared.usage_stream_flag = True
    llm.update_probe(spec.id, llm.Probe(at="2026-08-29T12:00:00Z", ok=True,
                                        usage_stream_flag_needed=False))
    llm.generate_object(spec.id, SCHEMA, "дай")
    assert "stream_options" not in rec.last


def test_проба_включает_нужный_флаг_вопреки_заявке(make_endpoint):
    spec, rec = make_endpoint([stream_response(openai_stream(ГОДНОЕ, usage=_usage()))])
    spec.declared.usage_stream_flag = False
    llm.update_probe(spec.id, llm.Probe(at="2026-08-29T12:00:00Z", ok=True,
                                        usage_stream_flag_needed=True))
    llm.generate_object(spec.id, SCHEMA, "дай")
    assert rec.last["stream_options"] == {"include_usage": True}
