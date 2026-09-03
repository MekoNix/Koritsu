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
    и журнал должен это фиксировать.

    Канал выставляется здесь явно, а не берётся из пресета: заявка в пресете —
    решение владельца и меняется (deepseek подняли до `messages_system`
    2026-09-03). Тест про поведение петли, а не про то, что владелец решил
    сегодня, иначе он падает при каждом пересмотре решения.
    """
    spec, rec = make_endpoint([stream_response(openai_stream("готово", usage=_usage()))])
    spec.declared.operator_channel = llm.OperatorChannel.SYSTEM_FIRST
    result = llm.run_tools(spec.id, [ЭХО], "зови", on_call=lambda c: "x")
    assert "no_operator_channel" in result.degraded


def test_с_операторским_каналом_пометки_нет(make_endpoint):
    """Обратная половина: объявленный канал пометку снимает.

    Без этой половины предыдущий тест проходил бы и на коде, который ставит
    пометку всегда, — а пометка, которая стоит всегда, ничего не значит.
    """
    spec, rec = make_endpoint([stream_response(openai_stream("готово", usage=_usage()))])
    spec.declared.operator_channel = llm.OperatorChannel.MESSAGES_SYSTEM
    result = llm.run_tools(spec.id, [ЭХО], "зови", on_call=lambda c: "x")
    assert "no_operator_channel" not in result.degraded


# ── проба ───────────────────────────────────────────────────────────────────
def _ответы_пробы(*, структура=Structured.JSON_SCHEMA, usage_с_флагом=True,
                  usage_без_флага=False, инструменты=True, оператор=True):
    """Записанная последовательность ответов на шаги Б.4.

    `оператор` — послушалась ли модель указания оператора против подложенного
    текста. Ответов на этот шаг столько, сколько пар в `_OPERATOR_TRIALS`:
    шаг делает по вызову на пару и на первом же проигрыше не останавливается.
    """
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
    # шаг 6: операторский канал, по вызову на каждую пару слов.
    # Ответы потоковые: `complete()` внутри идёт тем же потоком (А.4), и
    # непотоковый ответ здесь дал бы пустой текст — то есть «не устояло» по
    # недоразумению, а не по существу.
    from llm.probing import _OPERATOR_TRIALS
    for оператор_слово, подложенное in _OPERATOR_TRIALS:
        ответы.append(stream_response(openai_stream(
            оператор_слово if оператор else подложенное)))
    return ответы


def _ответы_кэша(первый=None, второй=None):
    """Два ответа шага 7 (кэш). Счётчики — как их отдаёт совместимый сервер.

    `None` вместо словаря значит «usage в потоке не пришёл вовсе»: тогда
    сработает запасной подсчёт, и сырых счётчиков не будет ни одного — тот
    самый случай, в котором мерить кэш нечем.
    """
    return [stream_response(openai_stream("да", usage=первый)),
            stream_response(openai_stream("да", usage=второй))]


def _счётчики_кэша(кэш=None, вход=2100):
    """Счётчики шага кэша. `кэш=None` — полей про кэш в ответе нет вовсе."""
    usage = {"prompt_tokens": вход, "completion_tokens": 2}
    if кэш is not None:
        usage["prompt_tokens_details"] = {"cached_tokens": кэш}
    return usage


def _проба(ответы, spec=None, кэш=False):
    from .conftest import Recorder
    recorder = Recorder(ответы)
    spec = spec or llm.presets.deepseek(api_key_env="TEST_KEY_UNUSED")
    transport = llm.Transport(spec.base_url, headers={}, client=recorder.client())
    return llm.probe(spec, transport=transport, do_cache_step=кэш), recorder


def test_проба_проходит_шаги_и_записывает_ступень():
    result, rec = _проба(_ответы_пробы(структура=Structured.JSON_OBJECT))
    assert result.ok
    assert result.structured_output == Structured.JSON_OBJECT
    assert result.streaming is True
    assert result.tools is True
    имена = [шаг["step"] for шаг in result.steps]
    assert имена == ["models", "plain", "stream", "structured", "tools",
                     "operator", "cache"]


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


def test_операторский_канал_проба_видит_что_указание_устояло():
    """Модель ответила словом оператора, а не подложенным — канал держится."""
    result, rec = _проба(_ответы_пробы(оператор=True))
    assert result.operator_channel == llm.OperatorChannel.MESSAGES_SYSTEM
    шаг = [ш for ш in result.steps if ш["step"] == "operator"][0]
    assert шаг["ok"] is True
    # Указание оператора обязано ехать системным сообщением ПОСЛЕ
    # пользовательского текста: проверяем именно середину разговора, а не
    # первое системное, которое есть у всех.
    последний = rec.requests[-1]["messages"]
    роли = [m["role"] for m in последний]
    assert роли.index("system", 1) > роли.index("user")


def test_операторский_канал_понижается_когда_указание_не_устояло():
    """Модель повторила подложенное слово — заявка владельца опровергнута.

    Это единственное направление, в котором проба вправе менять канал: вверх
    она не ходит, потому что одна удачная попытка не доказывает стойкость
    против настоящей инъекции.
    """
    spec = llm.presets.deepseek(api_key_env="TEST_KEY_UNUSED")
    spec.declared.operator_channel = llm.OperatorChannel.MESSAGES_SYSTEM
    result, rec = _проба(_ответы_пробы(оператор=False), spec=spec)
    assert result.operator_channel == llm.OperatorChannel.SYSTEM_FIRST
    llm.register_endpoint(spec)
    llm.update_probe(spec.id, result)
    caps = llm.capabilities(spec.id)
    assert caps.operator_channel == llm.OperatorChannel.SYSTEM_FIRST
    assert caps.is_confirmed("operator_channel")


def test_операторский_канал_проба_не_повышает_заявку():
    """Проба увидела, что указание устояло, а владелец заявил слабый канал.

    Заявка сильнее: ошибка в сторону разрешения — это уровень 3 на endpoint'е,
    который канал не держит, и цена у неё несопоставима с ценой осторожности.
    """
    spec = llm.presets.deepseek(api_key_env="TEST_KEY_UNUSED")
    spec.declared.operator_channel = llm.OperatorChannel.SYSTEM_FIRST
    result, rec = _проба(_ответы_пробы(оператор=True), spec=spec)
    assert result.operator_channel == llm.OperatorChannel.MESSAGES_SYSTEM
    llm.register_endpoint(spec)
    llm.update_probe(spec.id, result)
    caps = llm.capabilities(spec.id)
    assert caps.operator_channel == llm.OperatorChannel.SYSTEM_FIRST
    assert not caps.is_confirmed("operator_channel")


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


def test_вызов_без_аргументов_доходит_до_инструмента(make_endpoint):
    """`{}` — законный вызов инструмента без аргументов, а не битый JSON.

    Его шлёт всякий openai-совместимый поставщик. Пока петля считала непустой
    `raw_arguments` при пустом разборе признаком поломки, инструмент без
    аргументов получал отказ, не доходя до вызова, — и молча: модели уходил
    внятный текст «повтори с корректным JSON», она «чинилась», а инструмент так
    и не звался ни разу. У оркестратора таких два из семи: `list_materials`
    и `preview`.
    """
    без_аргументов = Tool(name="список", description="Перечисляет материалы.",
                          schema={"type": "object", "properties": {},
                                  "additionalProperties": False})
    spec, rec = make_endpoint([
        stream_response(openai_stream("", usage=_usage(), finish="tool_calls",
                                      tool_calls=_зов(name="список", args="{}"))),
        stream_response(openai_stream("готово", usage=_usage())),
    ])
    позвано: list = []
    llm.run_tools(spec.id, [без_аргументов], "зови",
                  on_call=lambda c: позвано.append(c) or "два материала")
    assert [c.name for c in позвано] == ["список"]
    assert позвано[0].arguments == {}


# ── шаг 1: имя модели против списка API ─────────────────────────────────────
def test_имя_модели_не_из_списка_даёт_предупреждение():
    """Имя модели зашито в пресете, а поставщик переименовывает модели молча.

    Живая проба deepseek 2026-09-03: `deepseek-chat` в списке `/v1/models`
    отсутствует, а вызовы проходят. Пробу это не отменяет — но без
    предупреждения переименование мы узнаем отказом на боевом вызове, то есть
    в момент, когда пользователь ждёт отчёт.
    """
    ответы = _ответы_пробы()
    ответы[0] = json_response({"data": [{"id": "deepseek-chat-v3.2"},
                                        {"id": "deepseek-reasoner"}]})
    result, rec = _проба(ответы)
    assert result.ok                                  # проба всё равно прошла
    assert result.model_listed is False
    предупреждение = " ".join(result.warnings)
    assert "deepseek-chat" in предупреждение
    # Предупреждение без «а как надо» отправляет человека за списком руками:
    # похожее имя подсказывается прямо здесь.
    assert "deepseek-chat-v3.2" in предупреждение
    шаг = [ш for ш in result.steps if ш["step"] == "models"][0]
    assert шаг["ok"] is False


def test_имя_модели_из_списка_предупреждений_не_даёт():
    """Обратная половина: предупреждение, которое стоит всегда, ничего не значит."""
    result, rec = _проба(_ответы_пробы())
    assert result.model_listed is True
    assert result.warnings == []


def test_список_моделей_недоступен_это_не_расхождение():
    """Отсутствие списка ничего не говорит о том, работает ли endpoint.

    Записать сюда «имени нет в списке» значило бы выдумать расхождение из
    молчания сервера — и погнать владельца править верное имя в пресете.
    """
    import httpx
    ответы = _ответы_пробы()
    ответы[0] = httpx.Response(404, json={"error": {"message": "no such path"}})
    result, rec = _проба(ответы)
    assert result.model_listed is None
    assert result.warnings == []
    шаг = [ш for ш in result.steps if ш["step"] == "models"][0]
    assert шаг["ok"] is True


# ── шаг 7: кэш префикса ─────────────────────────────────────────────────────
def test_шаг_кэша_меряет_попадание_по_счётчикам():
    """Единственное, что здесь вообще измеримо: ненулевое чтение из кэша во
    ВТОРОМ ответе. Оно же — единственное, чем заявку можно подтвердить."""
    ответы = _ответы_пробы() + _ответы_кэша(_счётчики_кэша(кэш=0),
                                            _счётчики_кэша(кэш=2048))
    spec = llm.presets.deepseek(api_key_env="TEST_KEY_UNUSED")
    result, rec = _проба(ответы, spec=spec, кэш=True)
    assert result.prefix_cache_works is True
    assert result.prefix_cache_reported is True
    шаг = [ш for ш in result.steps if ш["step"] == "cache"][0]
    assert шаг["ok"] is True and "2048" in шаг["note"]
    llm.register_endpoint(spec)
    llm.update_probe(spec.id, result)
    assert llm.capabilities(spec.id).is_confirmed("prefix_cache")


def test_шаг_кэша_без_счётчиков_кэша_не_измерим():
    """Endpoint о кэше не отчитывается — это результат «не измеримо», а не
    «кэша нет».

    Снаружи оба случая выглядят одинаково нулём в `cache_read`, но значат
    разное: промах опровергал бы заявку, молчание не говорит ничего. Записать
    молчание как опровержение значило бы выдумать измерение, которого не было.
    """
    голый = _счётчики_кэша(кэш=None)
    spec = llm.presets.deepseek(api_key_env="TEST_KEY_UNUSED")
    result, rec = _проба(_ответы_пробы() + _ответы_кэша(голый, голый),
                         spec=spec, кэш=True)
    assert result.prefix_cache_works is None
    assert result.prefix_cache_reported is False
    шаг = [ш for ш in result.steps if ш["step"] == "cache"][0]
    assert шаг["ok"] is None                      # не «прошёл» и не «провалился»
    assert "не отчитывается" in шаг["note"]
    llm.register_endpoint(spec)
    llm.update_probe(spec.id, result)
    caps = llm.capabilities(spec.id)
    assert caps.prefix_cache == llm.PrefixCache.AUTOMATIC   # заявка цела
    assert not caps.is_confirmed("prefix_cache")            # и не подтверждена


def test_шаг_кэша_на_автокэше_промах_неубедителен():
    """Счётчики есть, попадания нет: на автокэше это ничего не доказывает —
    попадание зависит от того, что было на сервере между двумя запросами."""
    нулевой = _счётчики_кэша(кэш=0)
    spec = llm.presets.deepseek(api_key_env="TEST_KEY_UNUSED")
    result, rec = _проба(_ответы_пробы() + _ответы_кэша(нулевой, нулевой),
                         spec=spec, кэш=True)
    assert result.prefix_cache_reported is True    # счётчики есть
    assert result.prefix_cache_works is None       # а вывода нет
    шаг = [ш for ш in result.steps if ш["step"] == "cache"][0]
    assert шаг["ok"] is None and "неубедителен" in шаг["note"]
    llm.register_endpoint(spec)
    llm.update_probe(spec.id, result)
    assert not llm.capabilities(spec.id).is_confirmed("prefix_cache")


def test_на_управляемом_кэше_промах_опровергает_заявку():
    """Брейкпойнты расставили мы сами — значит вправе ждать попадания, и его
    отсутствие содержательно. Это единственный случай, когда шаг говорит «нет».
    """
    нулевой = _счётчики_кэша(кэш=0)
    spec = llm.presets.deepseek(api_key_env="TEST_KEY_UNUSED")
    spec.declared.prefix_cache = llm.PrefixCache.BREAKPOINTS
    result, rec = _проба(_ответы_пробы() + _ответы_кэша(нулевой, нулевой),
                         spec=spec, кэш=True)
    assert result.prefix_cache_works is False
    шаг = [ш for ш in result.steps if ш["step"] == "cache"][0]
    assert шаг["ok"] is False
    llm.register_endpoint(spec)
    llm.update_probe(spec.id, result)
    caps = llm.capabilities(spec.id)
    assert caps.prefix_cache == llm.PrefixCache.NONE
    assert caps.is_confirmed("prefix_cache")


def test_незапущенный_шаг_кэша_виден_как_непроверенный():
    """Шаг платный и по умолчанию не идёт — но молчать об этом нельзя.

    Отчёт без строки про кэш показывает «automatic» как знание, а это
    непроверенная заявка владельца. Отсюда третье состояние шага: `ok=None`.
    """
    result, rec = _проба(_ответы_пробы())
    шаг = [ш for ш in result.steps if ш["step"] == "cache"][0]
    assert шаг["ok"] is None
    assert "--cache-step" in шаг["note"]
    assert result.prefix_cache_reported is None     # шага не было вовсе
    assert result.prefix_cache_works is None


def test_шаг_кэша_не_нужен_там_где_кэш_не_объявлен():
    """Заявлено «кэша нет» — проверять нечего, и лишних запросов не будет."""
    spec = llm.presets.deepseek(api_key_env="TEST_KEY_UNUSED")
    spec.declared.prefix_cache = llm.PrefixCache.NONE
    result, rec = _проба(_ответы_пробы(), spec=spec, кэш=True)
    шаг = [ш for ш in result.steps if ш["step"] == "cache"][0]
    assert шаг["ok"] is True and "не объявлен" in шаг["note"]
    assert rec.responses == []          # заготовок на кэш не тратилось


def test_префикс_шага_кэша_перекрывает_минимум_кэширования():
    """Префикс короче минимального даёт промах, неотличимый от «кэша нет».

    Минимум у поставщиков разный (у Anthropic на Opus 5 — 512 токенов), и
    сэкономленная на пробе тысяча токенов стоила бы выдуманного знания.
    """
    from llm.probing import CACHE_MIN_TOKENS
    нулевой = _счётчики_кэша(кэш=0)
    spec = llm.presets.deepseek(api_key_env="TEST_KEY_UNUSED")
    result, rec = _проба(_ответы_пробы() + _ответы_кэша(нулевой, нулевой),
                         spec=spec, кэш=True)
    первый, второй = rec.requests[-2], rec.requests[-1]
    префикс = первый["messages"][0]["content"]
    assert len(префикс) >= CACHE_MIN_TOKENS * spec.chars_per_token
    # И оба запроса обязаны быть одинаковыми знак в знак: разойдись префикс,
    # мерили бы не кэш, а собственную сборку тела.
    assert первый["messages"] == второй["messages"]


# ── посредник: измерено на прогоне, а не свойство навсегда ──────────────────
def test_посредник_помечает_пробу_как_измеренную_на_прогоне():
    """За одним именем модели у шлюза стоит разный поставщик, и умеют они
    разное. Ступень лестницы, снятая на умеющем, — про тот прогон."""
    spec = llm.presets.openrouter(api_key_env="TEST_KEY_UNUSED")
    ответы = _ответы_пробы()
    ответы[0] = json_response({"data": [{"id": spec.model}]})
    result, rec = _проба(ответы, spec=spec)
    assert result.provider_routed is True
    assert any("посредник" in текст for текст in result.warnings)
    llm.register_endpoint(spec)
    llm.update_probe(spec.id, result)
    caps = llm.capabilities(spec.id)
    assert caps.provider_routed is True
    assert caps.is_confirmed("provider_routed")


def test_прямой_endpoint_посредником_не_объявляется():
    """Обратная половина: пометка, которая стоит на всех, не значит ничего."""
    result, rec = _проба(_ответы_пробы())
    assert result.provider_routed is False
    assert result.providers_seen == []


def test_фактический_поставщик_из_ответа_записывается():
    """Поле `provider` в справочнике ответа не описано (документированный путь
    — отдельный запрос `/api/v1/generation`), но живые ответы шлюза его
    отдают. Читаем терпимо: есть — записываем, нет — «ответ не назвал».
    """
    ответы = _ответы_пробы()
    ответы[1] = json_response({"provider": "DeepInfra",
                               "choices": [{"message": {"content": "готов"},
                                            "finish_reason": "stop"}],
                               "usage": {"prompt_tokens": 10,
                                         "completion_tokens": 2}})
    result, rec = _проба(ответы)
    assert result.providers_seen == ["DeepInfra"]
    # Названный исполнитель доказывает маршрутизацию даже там, где её не
    # объявляли: заявке пресета такое известно быть не обязано.
    assert result.provider_routed is True
    assert any("DeepInfra" in текст for текст in result.warnings)


def test_поле_provider_не_строкой_поставщиком_не_считается():
    """`provider` — ещё и имя поля, которое шлём МЫ (ограничение
    маршрутизации). Сервер, отразивший наш объект обратно, не должен
    превратиться в «поставщика по имени {'require_parameters': True}»."""
    ответы = _ответы_пробы()
    ответы[1] = json_response({"provider": {"require_parameters": True},
                               "choices": [{"message": {"content": "готов"},
                                            "finish_reason": "stop"}],
                               "usage": {"prompt_tokens": 10,
                                         "completion_tokens": 2}})
    result, rec = _проба(ответы)
    assert result.providers_seen == []
    assert result.provider_routed is False


def test_проба_считает_символы_с_меткой_рамки(monkeypatch):
    """Тот же приём, что убран из `base._estimate_usage`: считать надо ровно то
    тело, которое уехало, а рамка едет по проводу и стоит токенов.

    Сегодня разницы в числах нет — недоверенных кусков в промптах пробы не
    бывает. Она появится молча в тот день, когда шаг пробы получит чужой текст,
    и калибровка коэффициента оценки начнёт занижать вход.
    """
    from llm import probing
    метки: list = []
    исходный = probing.layout.total_chars

    def записать(parts, mark=None):
        метки.append(mark)
        return исходный(parts, mark)

    monkeypatch.setattr(probing.layout, "total_chars", записать)
    нулевой = _счётчики_кэша(кэш=0)
    _проба(_ответы_пробы() + _ответы_кэша(нулевой, нулевой), кэш=True)
    assert метки, "проба не посчитала символы ни разу"
    assert all(mark for mark in метки), "total_chars позвали без метки рамки"
