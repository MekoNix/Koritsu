"""Петля инструментов (Г.3) и пробный вызов (Б.4).

Петля одна на всех поставщиков намеренно: два цикла — два набора багов, две
модели поведения при ошибке инструмента, два места, где чинить потолок ходов.
Поэтому она проверяется на обоих протоколах и обязана вести себя одинаково.
"""
from __future__ import annotations

import pytest

import llm
from llm import ErrorKind, LlmError, Stop, Structured, Tool
from llm.loop import Limits

from .conftest import anthropic_stream, json_response, openai_stream, stream_response

ЭХО = Tool(name="echo", description="Повторяет текст.",
           schema={"type": "object", "properties": {"text": {"type": "string"}},
                   "required": ["text"], "additionalProperties": False})


def _зов(call_id="c1", name="echo", args='{"text": "привет"}'):
    return [{"index": 0, "id": call_id, "function": {"name": name, "arguments": args}}]


def _usage(n_in=100, n_out=10):
    return {"prompt_tokens": n_in, "completion_tokens": n_out}


ЧТЕНИЕ = Tool(name="read", description="Читает файл.",
              schema={"type": "object",
                      "properties": {"путь": {"type": "string"},
                                     "кодировка": {"type": "string"}},
                      "required": ["путь"], "additionalProperties": False})


# ── петля ───────────────────────────────────────────────────────────────────
def test_петля_зовёт_инструмент_и_возвращает_ответ(make_endpoint):
    spec, rec = make_endpoint([
        stream_response(openai_stream("", usage=_usage(), finish="tool_calls",
                                      tool_calls=_зов())),
        stream_response(openai_stream("сделано", usage=_usage())),
    ])
    позвано: list = []
    result = llm.run_tools(spec.id, [ЭХО], "используй echo",
                           on_call=lambda c: позвано.append(c) or c.arguments["text"])
    assert result.ok and result.text == "сделано"
    assert len(позвано) == 1 and позвано[0].name == "echo"
    assert result.attempts == 2                     # два хода модели
    assert result.usage.input == 200                # расход обоих ходов


def test_ответ_инструмента_едет_обратно_в_истории(make_endpoint):
    spec, rec = make_endpoint([
        stream_response(openai_stream("", usage=_usage(), finish="tool_calls",
                                      tool_calls=_зов())),
        stream_response(openai_stream("готово", usage=_usage())),
    ])
    llm.run_tools(spec.id, [ЭХО], "зови", on_call=lambda c: "ответ инструмента")
    второй = rec.requests[1]["messages"]
    роли = [m["role"] for m in второй]
    assert "assistant" in роли and "tool" in роли
    ответ = [m for m in второй if m["role"] == "tool"][0]
    assert ответ["content"] == "ответ инструмента" and ответ["tool_call_id"] == "c1"


def test_исключение_инструмента_возвращается_модели_а_не_наружу(make_endpoint):
    """Недоступность приходит ответом is_error, а не исчезновением инструмента:
    иначе поведение модели непредсказуемо (Д.3)."""
    spec, rec = make_endpoint([
        stream_response(openai_stream("", usage=_usage(), finish="tool_calls",
                                      tool_calls=_зов())),
        stream_response(openai_stream("понял", usage=_usage())),
    ])

    def падает(call):
        raise RuntimeError("файл не читается")

    result = llm.run_tools(spec.id, [ЭХО], "зови", on_call=падает)
    assert result.ok
    ответ = [m for m in rec.requests[1]["messages"] if m["role"] == "tool"][0]
    assert "файл не читается" in ответ["content"]


def test_битые_аргументы_возвращаются_модели(make_endpoint):
    spec, rec = make_endpoint([
        stream_response(openai_stream("", usage=_usage(), finish="tool_calls",
                                      tool_calls=_зов(args="{это не json"))),
        stream_response(openai_stream("исправился", usage=_usage())),
    ])
    вызвано: list = []
    result = llm.run_tools(spec.id, [ЭХО], "зови", on_call=lambda c: вызвано.append(c))
    assert вызвано == []                       # до инструмента дело не дошло
    ответ = [m for m in rec.requests[1]["messages"] if m["role"] == "tool"][0]
    assert "не разобрались" in ответ["content"]


def test_потолок_ходов_обрывает_зацикливание(make_endpoint):
    ответы = [stream_response(openai_stream("", usage=_usage(), finish="tool_calls",
                                            tool_calls=_зов(call_id=f"c{i}")))
              for i in range(3)]
    spec, rec = make_endpoint(ответы)
    result = llm.run_tools(spec.id, [ЭХО], "зови", on_call=lambda c: "ещё",
                           limits=Limits(max_steps=3))
    assert result.stop == Stop.MAX_TOKENS
    assert "step_limit" in result.degraded
    assert result.attempts == 3


def test_потолок_в_единицах_обрывает_по_цене(make_endpoint):
    """Потолок в приведённых единицах, а не в токенах: тысяча токенов выхода и
    тысяча из кэша стоят в пятьдесят раз по-разному."""
    ответы = [stream_response(openai_stream("", usage=_usage(5000, 500),
                                            finish="tool_calls",
                                            tool_calls=_зов(call_id=f"c{i}")))
              for i in range(5)]
    spec, rec = make_endpoint(ответы)
    result = llm.run_tools(spec.id, [ЭХО], "зови", on_call=lambda c: "ещё",
                           limits=Limits(max_steps=5, max_units=10000))
    assert result.stop == Stop.MAX_TOKENS and "budget_cut" in result.degraded
    assert result.attempts < 5


def test_отмена_прерывает_петлю(make_endpoint):
    spec, rec = make_endpoint([])
    result = llm.run_tools(spec.id, [ЭХО], "зови", on_call=lambda c: "x",
                           cancel=lambda: True)
    assert result.stop == Stop.CANCELLED
    assert rec.requests == []


def test_каждый_ход_отдельная_запись_журнала(make_endpoint):
    """Прогон агента — десятки вызовов; без разбивки не понять, что съело бюджет."""
    spec, rec = make_endpoint([
        stream_response(openai_stream("", usage=_usage(), finish="tool_calls",
                                      tool_calls=_зов())),
        stream_response(openai_stream("конец", usage=_usage())),
    ])
    journal = llm.Journal()
    llm.run_tools(spec.id, [ЭХО], "зови", on_call=lambda c: "ок", journal=journal,
                  meta={"run": "r_1"})
    assert len(journal.entries) == 2
    assert [e["step"] for e in journal.entries] == [1, 2]
    assert all(e["run"] == "r_1" for e in journal.entries)


def test_петля_одинакова_на_втором_протоколе(make_endpoint):
    """Формат обмена другой, поведение петли — то же."""
    spec = llm.presets.anthropic(api_key_env="TEST_KEY_UNUSED")
    spec, rec = make_endpoint([
        stream_response(anthropic_stream("", usage_in={"input_tokens": 100},
                                         usage_out={"output_tokens": 10},
                                         stop_reason="tool_use",
                                         tool_use={"id": "tu_1", "name": "echo",
                                                   "args": '{"text": "привет"}'})),
        stream_response(anthropic_stream("сделано", usage_in={"input_tokens": 100},
                                         usage_out={"output_tokens": 10})),
    ], spec=spec)
    позвано: list = []
    result = llm.run_tools(spec.id, [ЭХО], "зови",
                           on_call=lambda c: позвано.append(c.name) or "ок")
    assert result.ok and result.text == "сделано" and позвано == ["echo"]
    блоки = rec.requests[1]["messages"][-1]["content"]
    assert блоки[0]["type"] == "tool_result" and блоки[0]["tool_use_id"] == "tu_1"


def test_строгий_инструмент_вызывающего_уезжает_строгой_схемой(make_endpoint):
    """`strict: true` без строгой схемы — четырёхсотка на ровном месте.

    Строгий режим требует все ключи `properties` в `required`; необязательное
    поле выражается тогда разрешённым null, а не отсутствием в `required`.
    Внутренний `set_values` приходит уже расширенным из лестницы, а инструмент
    вызывающего уезжал как есть — и его первый же необязательный параметр
    ломал вызов целиком. Проба этого не ловит: у ЭХО `required` случайно
    совпадает со всеми ключами.
    """
    spec, rec = make_endpoint([stream_response(openai_stream("готово", usage=_usage()))])
    llm.run_tools(spec.id, [ЧТЕНИЕ], "зови", on_call=lambda c: "ок")
    параметры = rec.last["tools"][0]["function"]["parameters"]
    assert rec.last["tools"][0]["function"]["strict"] is True
    assert set(параметры["required"]) == {"путь", "кодировка"}
    assert параметры["additionalProperties"] is False
    # Взамен обязательности необязательному полю разрешён null «не задаю».
    assert "null" in str(параметры["properties"]["кодировка"])
    assert "null" not in str(параметры["properties"]["путь"])


def test_строгий_инструмент_и_во_втором_протоколе(make_endpoint):
    """Требование строгого режима одно на оба протокола, и обход обязан быть
    один: иначе он найдётся в одном бэкенде и не найдётся в другом."""
    spec = llm.presets.anthropic(api_key_env="TEST_KEY_UNUSED")
    spec, rec = make_endpoint([stream_response(anthropic_stream(
        "готово", usage_in={"input_tokens": 10}, usage_out={"output_tokens": 1}))],
        spec=spec)
    llm.run_tools(spec.id, [ЧТЕНИЕ], "зови", on_call=lambda c: "ок")
    схема = rec.last["tools"][0]["input_schema"]
    assert set(схема["required"]) == {"путь", "кодировка"}


def test_нестрогий_инструмент_не_переписывается(make_endpoint):
    """Строгости не просили — схему трогать нельзя: расширять `required` там,
    где поставщик этого не требует, значит менять смысл объявления."""
    мягкий = Tool(name="read", description="Читает файл.", strict=False,
                  schema=ЧТЕНИЕ.schema)
    spec, rec = make_endpoint([stream_response(openai_stream("готово", usage=_usage()))])
    llm.run_tools(spec.id, [мягкий], "зови", on_call=lambda c: "ок")
    параметры = rec.last["tools"][0]["function"]["parameters"]
    assert параметры["required"] == ["путь"]
    assert "strict" not in rec.last["tools"][0]["function"]


def test_null_не_задаю_не_доезжает_до_инструмента(make_endpoint):
    """Обратная половина той же пары: расширили схему — обязаны погасить null.

    Иначе инструмент вызывающего получит `кодировка: None` как настоящее
    значение и откроет файл в кодировке None вместо своего умолчания — ошибки
    при этом не будет ни одной.
    """
    аргументы = '{"путь": "a.py", "кодировка": null}'
    spec, rec = make_endpoint([
        stream_response(openai_stream("", usage=_usage(), finish="tool_calls",
                                      tool_calls=_зов(name="read", args=аргументы))),
        stream_response(openai_stream("готово", usage=_usage())),
    ])
    позвано: list = []
    llm.run_tools(spec.id, [ЧТЕНИЕ], "зови", on_call=lambda c: позвано.append(c) or "ок")
    assert позвано[0].arguments == {"путь": "a.py"}
    # Дословное остаётся дословным: пересчитать задним числом должно быть чем.
    assert "кодировка" in позвано[0].raw_arguments


def test_петля_отказывает_на_endpointе_без_инструментов(make_endpoint):
    spec, rec = make_endpoint([])
    spec.declared.tools = False
    with pytest.raises(LlmError) as поймали:
        llm.run_tools(spec.id, [ЭХО], "зови", on_call=lambda c: "x")
    assert поймали.value.kind == ErrorKind.UNSUPPORTED


def test_без_операторского_канала_ставится_пометка(make_endpoint):
    """Г.2: на таком endpoint'е указание оператора не весомее текста из файлов,
    и журнал должен это фиксировать."""
    spec, rec = make_endpoint([stream_response(openai_stream("готово", usage=_usage()))])
    result = llm.run_tools(spec.id, [ЭХО], "зови", on_call=lambda c: "x")
    assert "no_operator_channel" in result.degraded


# ── проба ───────────────────────────────────────────────────────────────────
def _ответы_пробы(*, структура=Structured.JSON_SCHEMA, usage_с_флагом=True,
                  usage_без_флага=False, инструменты=True):
    """Записанная последовательность ответов на шесть шагов Б.4."""
    ответы: list = [
        json_response({"data": [{"id": "deepseek-chat"}]}),          # шаг 1
        json_response({"choices": [{"message": {"content": "готов"},
                                    "finish_reason": "stop"}],
                       "usage": {"prompt_tokens": 10, "completion_tokens": 2}}),  # шаг 2
        stream_response(openai_stream("раз", usage=({"prompt_tokens": 10,
                                                     "completion_tokens": 3}
                                                    if usage_с_флагом else None))),
        stream_response(openai_stream("раз", usage=({"prompt_tokens": 10,
                                                     "completion_tokens": 3}
                                                    if usage_без_флага else None))),
    ]
    # шаг 4: неудачные ступени выше искомой, потом удачная
    for ступень in Structured.LADDER:
        if ступень == структура:
            ответы.append(stream_response(openai_stream('{"ok": true, "n": 7}')))
            break
        ответы.append(stream_response(openai_stream("ерунда")))
    # шаг 5
    if инструменты:
        ответы.append(stream_response(openai_stream(
            "", finish="tool_calls",
            tool_calls=[{"index": 0, "id": "c1",
                         "function": {"name": "echo", "arguments": '{"text":"привет"}'}}])))
    else:
        ответы.append(stream_response(openai_stream("не буду")))
    return ответы


def _проба(ответы, spec=None):
    from .conftest import Recorder
    recorder = Recorder(ответы)
    spec = spec or llm.presets.deepseek(api_key_env="TEST_KEY_UNUSED")
    transport = llm.Transport(spec.base_url, headers={}, client=recorder.client())
    return llm.probe(spec, transport=transport), recorder


def test_проба_проходит_шаги_и_записывает_ступень():
    result, rec = _проба(_ответы_пробы(структура=Structured.JSON_OBJECT))
    assert result.ok
    assert result.structured_output == Structured.JSON_OBJECT
    assert result.streaming is True
    assert result.tools is True
    имена = [шаг["step"] for шаг in result.steps]
    assert имена == ["models", "plain", "stream", "structured", "tools"]


def test_проба_проверяет_поток_с_флагом_и_без():
    """Главный практический риск учёта: флаг то нужен, то игнорируется."""
    result, rec = _проба(_ответы_пробы(usage_с_флагом=True, usage_без_флага=False))
    assert result.usage_in_stream is True
    assert result.usage_stream_flag_needed is True
    # Первый потоковый запрос — с флагом, второй — без.
    потоковые = [r for r in rec.requests if r.get("stream")]
    assert "stream_options" in потоковые[0]
    assert "stream_options" not in потоковые[1]


def test_флаг_признан_лишним_если_usage_приходит_и_без_него():
    """Лишнее поле — риск 400 на совместимом сервере; слать его не надо."""
    result, rec = _проба(_ответы_пробы(usage_с_флагом=True, usage_без_флага=True))
    assert result.usage_in_stream is True
    assert result.usage_stream_flag_needed is False


def test_проба_спускается_по_лестнице_до_рабочей_ступени():
    result, rec = _проба(_ответы_пробы(структура=Structured.TEXT))
    assert result.structured_output == Structured.TEXT
    шаг = [s for s in result.steps if s["step"] == "structured"][0]
    assert "json_schema" in шаг["note"]      # видно, что верхние ступени пробовались


def test_проба_обрывается_если_ключ_не_принят():
    """Шаг 2 не прошёл — дальше проверять нечего и незачем тратить деньги."""
    import httpx
    result, rec = _проба([json_response({"data": []}),
                          httpx.Response(401, json={"error": {"message": "bad key"}})])
    assert result.ok is False
    assert result.error and "auth" in result.error
    assert len(result.steps) == 2


def test_результат_пробы_перекрывает_заявку():
    spec = llm.presets.deepseek(api_key_env="TEST_KEY_UNUSED")
    spec.declared.structured_output = Structured.JSON_SCHEMA
    result, rec = _проба(_ответы_пробы(структура=Structured.JSON_OBJECT), spec=spec)
    llm.register_endpoint(spec)
    llm.update_probe(spec.id, result)      # единственная дверь для пробы
    caps = llm.capabilities(spec.id)
    assert caps.structured_output == Structured.JSON_OBJECT
    assert caps.is_confirmed("structured_output")


def test_непроверенное_остаётся_заявкой():
    """Интерфейс не должен показывать зелёную галочку там, где мы ничего не
    проверяли (Ж.6)."""
    spec = llm.presets.deepseek(api_key_env="TEST_KEY_UNUSED")
    result, rec = _проба(_ответы_пробы(), spec=spec)
    llm.register_endpoint(spec)
    llm.update_probe(spec.id, result)      # единственная дверь для пробы
    caps = llm.capabilities(spec.id)
    assert caps.is_confirmed("structured_output")      # проверено
    assert not caps.is_confirmed("prefix_cache")       # шаг 6 не запускался
    assert caps.prefix_cache == llm.PrefixCache.AUTOMATIC   # осталась заявка


def test_возможности_без_пробы_это_чистая_заявка():
    spec = llm.presets.deepseek(api_key_env="TEST_KEY_UNUSED")
    llm.register_endpoint(spec)
    caps = llm.capabilities(spec.id)
    assert caps.probed is False and caps.confirmed == set()
