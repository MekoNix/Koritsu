"""Учёт потока и разбор потока по закрытым объектам.

Две беды, от которых здесь стоит забор:

1. **Поток мимо лимита и журнала.** «Весь отчёт одним вызовом» обязан быть
   потоковым, значит самый дорогой вызов в системе — потоковый. Если он не
   проверяет лимит и не пишет расход, пользователь уходит за бюджет незаметно,
   а объяснить потом нечем. Отдельно проверяется обрыв: расход тогда не
   известен, и ноль в журнале был бы дырой, через которую бюджет расходуется
   мимо учёта.
2. **Потеря готового при обрыве.** У отчёта на десятки тегов половина значений
   к моменту обрыва уже написана. Разбор по закрытым объектам обязан их
   сохранить — и обязан не ломаться на скобке внутри строки и на разрыве куска
   в самом неудобном месте.
"""
from __future__ import annotations

import json

import pytest

import llm
from llm import Journal, Limit, Stop
from llm.model import Prices
from llm.stream_parse import ObjectStream, iter_objects

from .conftest import (anthropic_stream, json_response, openai_stream,
                       stream_response)

SCHEMA = {"type": "object", "properties": {"n": {"type": "integer"}},
          "required": ["n"], "additionalProperties": False}


def _usage(n_in=120, n_out=30):
    return {"prompt_tokens": n_in, "completion_tokens": n_out}


# ── учёт потока ─────────────────────────────────────────────────────────────
def test_поток_пишет_расход_в_журнал(make_endpoint):
    spec, rec = make_endpoint([stream_response(openai_stream("ответ", usage=_usage()))])
    spec.prices = Prices(input_per_mtok=1.0, output_per_mtok=5.0)
    журнал = Journal()
    list(llm.stream_object(spec.id, None, "скажи", journal=журнал,
                           meta={"run": "r_1", "tag": "цель_работы"}))
    assert len(журнал.entries) == 1
    запись = журнал.entries[0]
    assert запись["input"] == 120 and запись["output"] == 30
    assert запись["measured"] is True
    # Без units запись не участвует в лимите, и весь учёт потока — видимость.
    assert запись["units"] > 0 and запись["cost"] > 0
    assert запись["tag"] == "цель_работы"


def test_расход_потока_виден_лимиту(make_endpoint):
    """Смысл записи — не отчёт ради отчёта: следующий вызов должен подорожать."""
    spec, rec = make_endpoint([stream_response(openai_stream("ок", usage=_usage()))])
    лимит = Limit(cap_units=1_000_000)
    было = лимит.remaining()
    list(llm.stream_object(spec.id, None, "скажи", limit=лимит))
    assert лимит.spent() > 0 and лимит.remaining() < было


def test_отказ_по_лимиту_приходит_до_вызова(make_endpoint):
    """Отказ посреди потока — это уже потраченные деньги, значит только до."""
    spec, rec = make_endpoint([stream_response(openai_stream("ок", usage=_usage()))])
    лимит = Limit(cap_units=1.0)
    куски = list(llm.stream_object(spec.id, SCHEMA, "дай", limit=лимит))
    assert rec.requests == []                       # по проводу не пошли вовсе
    assert куски[0].kind == "error"
    assert куски[0].error.kind == llm.ErrorKind.LIMIT_EXCEEDED
    assert куски[-1].kind == "stop" and куски[-1].stop == Stop.ERROR
    # Вызова не было — писать в журнал нечего.
    assert лимит.journal.entries == []


def test_обрыв_на_середине_всё_равно_попадает_в_журнал(make_endpoint):
    """Вызывающий бросил поток: деньги потрачены, запись обязана быть."""
    spec, rec = make_endpoint([stream_response(openai_stream("двенадцать",
                                                            usage=_usage()))])
    журнал = Journal()
    поток = llm.stream_object(spec.id, None, "скажи", journal=журнал)
    видено = []
    for кусок in поток:
        if кусок.kind == "text":
            видено.append(кусок.text)
        if len(видено) == 3:
            break
    поток.close()
    запись = журнал.entries[0]
    assert запись["stop"] == Stop.CANCELLED
    # Счётчиков не было — но ноль был бы дырой: лимит его не заметит.
    assert запись["measured"] is False
    assert запись["input"] > 0 and запись["output"] > 0 and запись["units"] > 0


def test_отмена_потока_учитывается_как_расход(make_endpoint):
    spec, rec = make_endpoint([stream_response(openai_stream("длинный ответ"))])
    журнал = Journal()
    list(llm.stream_object(spec.id, None, "скажи", journal=журнал,
                           cancel=lambda: True))
    assert len(журнал.entries) == 1
    assert журнал.entries[0]["stop"] == Stop.CANCELLED
    assert журнал.entries[0]["measured"] is False


def test_оценка_потока_помечена_и_видна_долей(make_endpoint):
    """Поток без счётчиков считается эвристикой — и это должно быть видно."""
    spec, rec = make_endpoint([stream_response(openai_stream("ответ"))])
    журнал = Journal()
    list(llm.stream_object(spec.id, None, "скажи", journal=журнал))
    assert журнал.entries[0]["measured"] is False
    assert журнал.estimated_share() == 1.0


def test_журнал_берётся_из_лимита_когда_отдельного_нет(make_endpoint):
    spec, rec = make_endpoint([stream_response(openai_stream("ок", usage=_usage()))])
    лимит = Limit(cap_units=1_000_000)
    list(llm.stream_object(spec.id, None, "скажи", limit=лимит))
    assert len(лимит.journal.entries) == 1


def test_обрыв_по_проводу_тоже_попадает_в_журнал(make_endpoint):
    """Упавший вызов стоил денег — в отчётности он обязан быть (В.4)."""
    # 401, а не 5xx: ключ не примут и на второй попытке, значит проверяется
    # именно запись расхода, а не политика повторов.
    spec, rec = make_endpoint([json_response({"error": "ключ"}, status=401)])
    журнал = Journal()
    with pytest.raises(llm.LlmError):
        list(llm.stream_object(spec.id, None, "скажи", journal=журнал))
    assert len(журнал.entries) == 1
    запись = журнал.entries[0]
    assert запись["ok"] is False and запись["stop"] == Stop.ERROR
    assert "error_kind" in запись


def test_ошибка_внутри_потока_кончается_stop_error(make_endpoint):
    """Конец потока читается по последнему куску `stop` — так обещает докстрока
    `stream_object`. Значит ошибка внутри 200-потока обязана кончиться
    `stop=error`, а не `end_turn`.

    Цена ошибки ровно та, ради которой поток и разбирают по последнему куску:
    вызывающий, увидев `end_turn`, запишет оборванный на середине ответ как
    законченный ход — и половина отчёта уедет получателю как готовая. В журнале
    при этом всё верно, врёт именно то, что видит вызывающий.
    """
    события = [(None, {"choices": [{"index": 0, "delta": {"content": "нача"}}]}),
               (None, {"error": {"code": 502, "message": "Provider returned invalid response"}})]
    spec, rec = make_endpoint([stream_response(события)])
    журнал = Journal()
    куски = list(llm.stream_object(spec.id, None, "скажи", journal=журнал))
    assert [c.kind for c in куски[-3:]] == ["error", "usage", "stop"]
    assert куски[-1].stop == Stop.ERROR
    # Порядок кусков тот же, что у любого другого конца потока: usage, потом
    # stop. Второй разбор конца потока — приглашение забыть один из них.
    assert журнал.entries[0]["ok"] is False


def test_ошибка_внутри_потока_второго_протокола_такой_же_кусок(make_endpoint):
    """Два разных конца потока у одного слоя — приглашение забыть второй разбор.

    У anthropic ошибка в потоке уходила исключением, у openai — куском
    `kind="error"`. Форма обязана быть одна: кусок ошибки, затем usage, затем
    stop=error.
    """
    spec = llm.presets.anthropic(api_key_env="TEST_KEY_UNUSED")
    события = [("message_start", {"type": "message_start",
                                  "message": {"usage": {"input_tokens": 7000}}}),
               ("content_block_start", {"type": "content_block_start", "index": 0,
                                        "content_block": {"type": "text", "text": ""}}),
               ("content_block_delta", {"type": "content_block_delta", "index": 0,
                                        "delta": {"type": "text_delta", "text": "нача"}}),
               ("error", {"type": "error",
                          "error": {"type": "overloaded_error", "message": "перегрузка"}})]
    spec, rec = make_endpoint([stream_response(события)], spec=spec)
    куски = list(llm.stream_object(spec.id, None, "скажи"))
    assert [c.kind for c in куски[-3:]] == ["error", "usage", "stop"]
    assert куски[-1].stop == Stop.ERROR
    # Счётчики, которые успели приехать, не выброшены: вход модель уже
    # прочитала и деньги за него взяты.
    assert куски[-2].usage.input == 7000 and куски[-2].usage.measured is True


def test_отмена_второго_протокола_не_теряет_измеренный_вход(make_endpoint):
    """Дыра, которую докстрока `Backend.stream` объявляет закрытой.

    Счётчики входа приезжают первым же событием (`message_start`), и при отмене
    они уже известны. Копить их в локальной переменной и переносить в state
    только после цикла значит на отмене выбросить измеренное и подменить его
    оценкой — на живом промпте это занижение в десятки раз, то есть отмена
    снова становится способом тратить бюджет мимо лимита.
    """
    spec = llm.presets.anthropic(api_key_env="TEST_KEY_UNUSED")
    spec, rec = make_endpoint([stream_response(anthropic_stream(
        "двенадцать", usage_in={"input_tokens": 7000, "cache_read_input_tokens": 0},
        usage_out={"output_tokens": 5}))], spec=spec)
    видено: list = []
    журнал = Journal()

    def прервать():
        return len(видено) >= 3

    for кусок in llm.stream_object(spec.id, None, "скажи", cancel=прервать,
                                   journal=журнал):
        if кусок.kind == "text":
            видено.append(кусок.text)
        последний = кусок
    assert последний.stop == Stop.CANCELLED
    запись = журнал.entries[0]
    assert запись["measured"] is True
    assert запись["input"] == 7000        # а не оценка по длине промпта


def test_поток_со_схемой_записывает_ступень_и_обходы(make_endpoint):
    """Запись обязана объяснять свои цифры: ступень и чего не было (В.4)."""
    spec, rec = make_endpoint([stream_response(openai_stream('{"n":1}',
                                                             usage=_usage()))])
    журнал = Journal()
    list(llm.stream_object(spec.id, SCHEMA, "дай", journal=журнал))
    запись = журнал.entries[0]
    assert запись["structured_step"] is not None
    assert запись["units"] > 0


def test_без_журнала_и_лимита_поток_прежний(make_endpoint):
    """Учёт добавлен, а форма потока не изменилась: куски те же."""
    spec, rec = make_endpoint([stream_response(openai_stream("привет"))])
    куски = list(llm.stream_object(spec.id, None, "скажи"))
    assert "".join(c.text for c in куски if c.kind == "text") == "привет"
    assert куски[-1].kind == "stop" and куски[-1].stop == Stop.END_TURN


# ── разбор потока по закрытым объектам ──────────────────────────────────────
def _по_кускам(текст: str, n: int):
    """Текст, нарезанный на куски по n символов — как приходит из потока."""
    return [текст[i:i + n] for i in range(0, len(текст), n)]


def test_объекты_отдаются_по_мере_закрытия():
    поток = ObjectStream()
    assert поток.feed('[{"тег": "a"}, {"тег"') == [{"тег": "a"}]
    assert поток.feed(': "b"}]') == [{"тег": "b"}]
    assert поток.objects == [{"тег": "a"}, {"тег": "b"}]


def test_скобка_и_кавычка_внутри_строки_не_считаются():
    """Значения тегов — человеческий текст, в нём бывает всё."""
    текст = r'{"v": "фигурная { и вторая } и кавычка \" и косая \\"}{"v": 2}'
    assert list(iter_objects(_по_кускам(текст, 3))) == [
        {"v": 'фигурная { и вторая } и кавычка " и косая \\'}, {"v": 2}]


def test_разрыв_посреди_экранированной_кавычки():
    """Кусок кончился на `\\`, а `"` приедет следующим: строка не закрылась."""
    поток = ObjectStream()
    assert поток.feed('{"v": "конец строки \\') == []
    assert поток.feed('" и }) ещё не конец"}') == [
        {"v": 'конец строки " и }) ещё не конец'}]


def test_разрыв_посреди_двойной_косой():
    """`\\\\` — это косая, а не экран следующей кавычки, даже если разорвать."""
    поток = ObjectStream()
    assert поток.feed('{"v": "путь \\') == []
    assert поток.feed('\\"}') == [{"v": "путь \\"}]


def test_разрыв_посреди_ключа_и_между_скобкой_и_запятой():
    куски = ['[{"дли', 'нный_ключ": 1}', ',', ' {"b": 2}]']
    поток = ObjectStream()
    готово = [поток.feed(к) for к in куски]
    assert готово == [[], [{"длинный_ключ": 1}], [], [{"b": 2}]]


def test_разрыв_посреди_многобайтового_символа():
    """Кусок может кончиться половиной «ё»: байты держит декодер."""
    байты = '{"v": "ёж"}'.encode()
    поток = ObjectStream()
    середина = байты.index("ё".encode()) + 1      # ровно посреди двух байт «ё»
    assert поток.feed(байты[:середина]) == []
    assert поток.feed(байты[середина:]) == [{"v": "ёж"}]


def test_разрыв_по_одному_байту_переживается():
    байты = json.dumps({"тег": "значение с ё и {"}, ensure_ascii=False).encode()
    поток = ObjectStream()
    готово = [v for b in байты for v in поток.feed(bytes([b]))]
    assert готово == [{"тег": "значение с ё и {"}]


def test_обрыв_после_трёх_из_десяти_сохраняет_три():
    """Главный случай: половина отчёта написана, связь упала."""
    объекты = [{"тег": f"t{i}", "значение": "текст } со скобкой"} for i in range(10)]
    полный = "[" + ", ".join(json.dumps(o, ensure_ascii=False) for o in объекты) + "]"
    оборванный = полный[:полный.index("t3") + 1]   # третий дописан, четвёртый нет
    поток = ObjectStream()
    спасено = [v for кусок in _по_кускам(оборванный, 7) for v in поток.feed(кусок)]
    assert спасено == объекты[:3]
    assert поток.truncated and поток.pending.startswith('{"тег": "t')
    assert поток.broken == []


def test_вложенные_объекты_не_считаются_верхним_уровнем():
    текст = '{"a": {"b": {"c": 1}}, "d": [{"e": 2}]}'
    поток = ObjectStream()
    assert поток.feed(текст) == [json.loads(текст)]


def test_пояснения_и_забор_вокруг_json_пропускаются():
    """Модель любит пояснить ответ; JSON от этого не перестаёт быть JSON."""
    текст = 'Вот значения:\n```json\n{"n": 1}\n```\nи всё.'
    assert list(iter_objects([текст])) == [{"n": 1}]


def test_неразобранный_кусок_не_теряется_молча():
    """Пропавший тег обязан быть видим: иначе отчёт молча неполный."""
    поток = ObjectStream()
    assert поток.feed('{"n": 1,}{"n": 2}') == [{"n": 2}]
    assert len(поток.broken) == 1 and поток.broken[0] == '{"n": 1,}'


# ── null «не задаю» не должен доехать до вызывающего ────────────────────────
С_НЕОБЯЗАТЕЛЬНЫМ = {
    "type": "object",
    "properties": {"n": {"type": "integer"}, "lang": {"type": "string"}},
    "required": ["n"], "additionalProperties": False}


def _строгий_endpoint(make_endpoint, ответы):
    """Endpoint на ступени 2: значение приезжает вызовом инструмента."""
    spec = llm.presets.deepseek(api_key_env="TEST_KEY_UNUSED")
    spec.declared.structured_output = llm.Structured.TOOL_STRICT
    return make_endpoint(ответы, spec=spec)


def _зов_set_values(аргументы: str):
    return [{"index": 0, "id": "c1",
             "function": {"name": "set_values", "arguments": аргументы}}]


def test_поток_снимает_null_не_задаю_с_готового_значения(make_endpoint):
    """Строгий режим требует все ключи, поэтому необязательным полям выдан null
    «этого поля я не задаю» (strictify). Не снять его обратно — значит отдать
    вызывающему null как настоящее значение: у hokoku он молча перекроет
    умолчание шаблона (`code.lang`), и отчёт выйдет с чужим оформлением без
    единой ошибки. run_ladder снимает, поток обязан снимать так же.
    """
    spec, rec = _строгий_endpoint(make_endpoint, [stream_response(openai_stream(
        "", finish="tool_calls", tool_calls=_зов_set_values('{"n": 1, "lang": null}')))])
    зовы = [c.tool_call for c in llm.stream_object(spec.id, С_НЕОБЯЗАТЕЛЬНЫМ, "дай")
            if c.kind == "tool_call"]
    assert зовы[0].arguments == {"n": 1}
    # Сырое остаётся дословным: пересчитать задним числом должно быть чем.
    assert "lang" in зовы[0].raw_arguments


def test_поток_не_чинит_значение_за_модель(make_endpoint):
    """Гасится ровно то, что расширил strictify. Обязательное поле с null —
    не «промолчала», а неверный ответ, и вызывающий обязан его увидеть."""
    spec, rec = _строгий_endpoint(make_endpoint, [stream_response(openai_stream(
        "", finish="tool_calls", tool_calls=_зов_set_values('{"n": null}')))])
    зовы = [c.tool_call for c in llm.stream_object(spec.id, С_НЕОБЯЗАТЕЛЬНЫМ, "дай")
            if c.kind == "tool_call"]
    assert зовы[0].arguments == {"n": None}


def test_поток_без_схемы_вызовы_инструмента_не_трогает(make_endpoint):
    """Без схемы гасить нечем и незачем: чужой null — чужой смысл."""
    spec, rec = _строгий_endpoint(make_endpoint, [stream_response(openai_stream(
        "", finish="tool_calls", tool_calls=_зов_set_values('{"n": 1, "lang": null}')))])
    зовы = [c.tool_call for c in llm.stream_object(spec.id, None, "дай")
            if c.kind == "tool_call"]
    assert зовы[0].arguments == {"n": 1, "lang": None}
