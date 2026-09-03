"""Журнал расхода и поведение на границе лимита (В.4, В.5).

Проверяется главное свойство записи: из неё считается всё — месячный расход в
единицах, деньги по любому прайсу, разбивка по endpoint'ам, доля попаданий в
кэш. Из одного числа «токены» не считается ничего.
"""
from __future__ import annotations

import httpx
import pytest

import llm
from llm import ErrorKind, Journal, Limit, LlmError
from llm.model import Prices, Result, Usage
from llm.transport import Retry

from .conftest import Recorder, openai_stream, stream_response


def _usage(n_in=100, n_out=20):
    return {"prompt_tokens": n_in, "completion_tokens": n_out}


SCHEMA = {"type": "object", "properties": {"n": {"type": "integer"}},
          "required": ["n"], "additionalProperties": False}


def test_запись_содержит_всё_нужное_для_отчётности(make_endpoint):
    spec, rec = make_endpoint([stream_response(openai_stream('{"n":1}', usage=_usage()))])
    spec.prices = Prices(input_per_mtok=1.0, output_per_mtok=5.0)
    journal = Journal()
    llm.generate_object(spec.id, SCHEMA, "дай", journal=journal,
                        meta={"run": "r_11", "tag": "цель_работы", "user": "u_7"})
    запись = journal.entries[0]
    for поле in ("input", "output", "cache_read", "cache_write", "measured", "units",
                 "cost", "price_snapshot", "degraded", "attempts", "stop",
                 "latency_ms", "own_key", "endpoint", "protocol", "model", "raw_usage"):
        assert поле in запись, поле
    # meta вызывающей службы кладётся как есть: слой её не толкует.
    assert запись["run"] == "r_11" and запись["tag"] == "цель_работы"


def test_снимок_цены_защищает_прошлые_месяцы(make_endpoint):
    """Цена в настройках меняется; без снимка прошлое пересчитается по новой."""
    spec, rec = make_endpoint([stream_response(openai_stream('{"n":1}', usage=_usage()))])
    spec.prices = Prices(input_per_mtok=1.0, output_per_mtok=5.0)
    journal = Journal()
    llm.generate_object(spec.id, SCHEMA, "дай", journal=journal)
    spec.prices = Prices(input_per_mtok=99.0, output_per_mtok=999.0)
    assert journal.entries[0]["price_snapshot"]["input_per_mtok"] == 1.0


def test_без_цены_снимок_none_а_не_нули():
    """«Не знаем» и «бесплатно» в отчёте о расходах различны."""
    spec = llm.presets.deepseek()
    result = Result(usage=Usage(input=10), endpoint=spec.id, model=spec.model)
    from llm.journal import record
    запись = record(result, spec)
    assert запись["price_snapshot"] is None and запись["cost"] is None


def test_свой_ключ_считается_но_против_тарифа_не_идёт(make_endpoint):
    spec, rec = make_endpoint([stream_response(openai_stream('{"n":1}', usage=_usage()))])
    spec.own_key = True
    journal = Journal()
    llm.generate_object(spec.id, SCHEMA, "дай", journal=journal)
    assert journal.total_units() == 0.0                 # против тарифа — ноль
    assert journal.total_units(own_key=True) > 0        # но расход посчитан


def test_доля_оценённого_видна_отдельно(make_endpoint):
    """Оценки в сумму входят, но пользователю показывается их доля — иначе
    через месяц никто не объяснит, откуда цифра."""
    spec, rec = make_endpoint([
        stream_response(openai_stream('{"n":1}', usage=_usage(100, 0))),
        stream_response(openai_stream('{"n":1}', usage=None)),
    ])
    journal = Journal()
    llm.generate_object(spec.id, SCHEMA, "дай", journal=journal)
    llm.generate_object(spec.id, SCHEMA, "дай", journal=journal)
    assert 0.0 < journal.estimated_share() < 1.0
    assert journal.entries[0]["measured"] is True
    assert journal.entries[1]["measured"] is False


def test_доля_оценённого_отбирает_записи_так_же_как_сумма(make_endpoint):
    """Доля считается ОТ той суммы, которую она объясняет.

    `total_units` по умолчанию не берёт расход по ключу пользователя (в лимит
    он не идёт), а доля оценок бралась по всем записям подряд — и отвечала про
    другие деньги, чем те, о которых спрашивают.
    """
    spec, rec = make_endpoint([
        stream_response(openai_stream('{"n":1}', usage=_usage(100, 0))),
        stream_response(openai_stream('{"n":1}', usage=None)),
    ])
    journal = Journal()
    llm.generate_object(spec.id, SCHEMA, "дай", journal=journal)   # измерено, тариф
    spec.own_key = True
    llm.generate_object(spec.id, SCHEMA, "дай", journal=journal)   # оценка, свой ключ
    assert journal.estimated_share() == 0.0            # тарифное всё измерено
    assert journal.estimated_share(own_key=True) > 0.0


def test_приёмник_получает_записи():
    """Куда писать журнал — дело вызывающей службы, а не пакета."""
    сложенное: list = []
    journal = Journal(sink=сложенное.append)
    spec = llm.presets.deepseek()
    journal.add(Result(usage=Usage(input=10), endpoint=spec.id), spec)
    assert len(сложенное) == 1


# ── лимит ───────────────────────────────────────────────────────────────────
def test_отказ_до_вызова_а_не_посреди(make_endpoint):
    """Посреди — это потраченные деньги без результата (В.5)."""
    spec, rec = make_endpoint([])                # ответов нет: вызова не будет
    limit = Limit(cap_units=10)
    result = llm.generate_object(spec.id, SCHEMA, "x" * 5000, limit=limit)
    assert not result.ok
    assert result.error.kind == ErrorKind.LIMIT_EXCEEDED
    assert rec.requests == []                    # до сети дело не дошло


def test_отказ_приходит_с_цифрой_а_не_попробуйте_позже():
    limit = Limit(cap_units=1000)
    with pytest.raises(LlmError) as поймали:
        limit.check(estimate_units=5000)
    текст = поймали.value.message
    assert "5000" in текст and "1000" in текст


def test_пороги_предупреждения(make_endpoint):
    journal = Journal()
    spec = llm.presets.deepseek()
    limit = Limit(cap_units=1000, journal=journal)
    assert limit.warning() is None
    journal.add(Result(usage=Usage(input=750), units=750, endpoint=spec.id), spec)
    assert limit.warning() == 0.70
    journal.add(Result(usage=Usage(input=210), units=210, endpoint=spec.id), spec)
    assert limit.warning() == 0.95


def test_остаток_не_уходит_в_минус():
    journal = Journal()
    spec = llm.presets.deepseek()
    limit = Limit(cap_units=100, journal=journal)
    journal.add(Result(usage=Usage(input=500), units=500, endpoint=spec.id), spec)
    assert limit.remaining() == 0.0


def test_израсходованное_списывается_даже_на_неудаче(make_endpoint):
    """Остановленный прогон списывает израсходованное и говорит сколько."""
    spec, rec = make_endpoint([stream_response(openai_stream("мусор", usage=_usage()))
                               for _ in range(3)])
    spec.declared.structured_output = llm.Structured.JSON_OBJECT
    limit = Limit(cap_units=10_000_000)
    result = llm.generate_object(spec.id, SCHEMA, "дай", limit=limit)
    assert not result.ok
    assert limit.spent() > 0
    assert limit.journal.entries[0]["units"] == result.units


# ── петля инструментов на границе лимита и на обрыве ─────────────────────────
ЭХО = llm.Tool(name="echo", description="Повторяет текст.",
               schema={"type": "object", "properties": {"text": {"type": "string"}},
                       "required": ["text"], "additionalProperties": False})


def _зов(call_id="c1"):
    return [{"index": 0, "id": call_id, "function": {"name": "echo",
                                                     "arguments": '{"text": "привет"}'}}]


def _ход_с_инструментом(n_in=100, n_out=20, call_id="c1"):
    return stream_response(openai_stream("", usage=_usage(n_in, n_out),
                                         finish="tool_calls", tool_calls=_зов(call_id)))


def test_обрыв_посреди_прогона_даёт_итог_с_расходом_а_не_исключение(make_endpoint):
    """Записи по ходам в журнале уже есть; исключение вместо итога оставило бы
    израсходованное неучтённым — деньги потрачены, а суммы нет."""
    spec, rec = make_endpoint([_ход_с_инструментом(),
                               httpx.Response(401, text="ключ протух")])
    journal = Journal()
    result = llm.run_tools(spec.id, [ЭХО], "зови", on_call=lambda c: "ок",
                           journal=journal)
    assert not result.ok and result.stop == llm.Stop.ERROR
    assert result.error.kind == ErrorKind.AUTH
    assert result.usage.input == 100 and result.units > 0   # расход первого хода цел
    assert "transport_error" in result.degraded
    assert [e["step"] for e in journal.entries] == [1, 2]
    assert journal.entries[1]["error_kind"] == ErrorKind.AUTH


def test_петля_не_обходит_лимит_пользователя(make_endpoint):
    """Без проверки уровень «агент с инструментами» тратил бы мимо лимита,
    который api.generate_object проверяет до вызова (В.5)."""
    spec, rec = make_endpoint([])                       # ответов нет: вызова не будет
    limit = Limit(cap_units=1)
    result = llm.run_tools(spec.id, [ЭХО], "x" * 5000, on_call=lambda c: "ок",
                           limit=limit)
    assert not result.ok and result.error.kind == ErrorKind.LIMIT_EXCEEDED
    assert "limit_stop" in result.degraded
    assert rec.requests == [] and result.attempts == 0


def test_лимит_проверяется_перед_каждым_ходом_а_не_только_первым(make_endpoint):
    """Ход — отдельный вызов, и «отказ до вызова» относится к каждому: прогон
    агента это десятки обращений, одной проверки на входе мало."""
    spec, rec = make_endpoint([_ход_с_инструментом(call_id=f"c{i}") for i in range(3)])
    порог = llm.estimate(spec.id, "зови", max_tokens=4096).units
    # Первый ход съедает больше, чем весь остаток: второй обязан не начаться.
    rec.responses = [stream_response(openai_stream(
        "", usage=_usage(int(порог * 3), 0), finish="tool_calls",
        tool_calls=_зов(f"c{i}"))) for i in range(3)]
    limit = Limit(cap_units=порог * 2)
    result = llm.run_tools(spec.id, [ЭХО], "зови", on_call=lambda c: "ок",
                           limit=limit)
    assert len(rec.requests) == 1 and result.attempts == 1
    assert not result.ok and result.error.kind == ErrorKind.LIMIT_EXCEEDED
    assert result.usage.input == int(порог * 3)        # израсходованное сохранено
    assert limit.spent() > 0                           # ход попал в журнал лимита


def test_повторы_транспорта_видны_в_записи_хода(make_endpoint):
    """Ход, простоявший три паузы, иначе ничем не отличим от быстрого соседа."""
    spec = llm.presets.deepseek(api_key_env="TEST_KEY_UNUSED")
    rec = Recorder([httpx.Response(429, text="slow down", headers={"retry-after": "2"}),
                    stream_response(openai_stream("готово", usage=_usage()))])
    llm.register_endpoint(spec, transport=llm.Transport(
        spec.base_url, client=rec.client(),
        retry=Retry(sleep=lambda s: None, monotonic=lambda: 0.0)))
    journal = Journal()
    result = llm.run_tools(spec.id, [ЭХО], "зови", on_call=lambda c: "ок",
                           journal=journal)
    assert result.ok
    повторы = journal.entries[0]["retries"]
    assert [п["kind"] for п in повторы] == [ErrorKind.RATE_LIMIT]
    assert повторы[0]["delay_s"] == 2.0


def test_повторы_видны_и_в_записи_обычного_вызова(make_endpoint):
    """Повтор обязан лечь в запись того вызова, который его и вызвал.

    Забирал записки только `run_tools`; `generate_object` и поток о них не
    знали, и записка ждала в транспорте следующего забирающего. Дальше повтор,
    случившийся при генерации значения, всплывал в записи хода петли, прошедшего
    с первой попытки, — то есть «почему этот ход шёл вчетверо дольше» получало
    ложный ответ, а настоящая задержка оставалась необъяснимой.
    """
    spec = llm.presets.deepseek(api_key_env="TEST_KEY_UNUSED")
    rec = Recorder([httpx.Response(429, text="slow down", headers={"retry-after": "2"}),
                    stream_response(openai_stream("{}", usage=_usage()))])
    llm.register_endpoint(spec, transport=llm.Transport(
        spec.base_url, client=rec.client(),
        retry=Retry(sleep=lambda s: None, monotonic=lambda: 0.0)))
    journal = Journal()
    llm.generate_object(spec.id, {"type": "object", "properties": {},
                                  "additionalProperties": False},
                        "дай", journal=journal)
    повторы = journal.entries[0]["retries"]
    assert [п["kind"] for п in повторы] == [ErrorKind.RATE_LIMIT]


def test_чужой_повтор_не_приписывается_следующему_ходу(make_endpoint):
    """Записка уносится тем, кто сделал вызов, — иначе она приписывается чужому.

    Сценарий доказанный: повтор из `generate_object` всплывал в записи хода
    `run_tools`, прошедшего с первой попытки.
    """
    spec = llm.presets.deepseek(api_key_env="TEST_KEY_UNUSED")
    rec = Recorder([httpx.Response(429, text="slow down", headers={"retry-after": "2"}),
                    stream_response(openai_stream("{}", usage=_usage())),
                    stream_response(openai_stream("готово", usage=_usage()))])
    llm.register_endpoint(spec, transport=llm.Transport(
        spec.base_url, client=rec.client(),
        retry=Retry(sleep=lambda s: None, monotonic=lambda: 0.0)))
    journal = Journal()
    llm.generate_object(spec.id, {"type": "object", "properties": {},
                                  "additionalProperties": False},
                        "дай", journal=journal)
    llm.run_tools(spec.id, [ЭХО], "зови", on_call=lambda c: "ок", journal=journal)
    assert "retries" in journal.entries[0]
    assert "retries" not in journal.entries[1]


def test_повтор_потока_ложится_в_запись_потока(make_endpoint):
    """У потока запись делается в finally, и записка обязана дойти и туда."""
    spec = llm.presets.deepseek(api_key_env="TEST_KEY_UNUSED")
    rec = Recorder([httpx.Response(503, text="перегрузка"),
                    stream_response(openai_stream("ок", usage=_usage()))])
    llm.register_endpoint(spec, transport=llm.Transport(
        spec.base_url, client=rec.client(),
        retry=Retry(sleep=lambda s: None, monotonic=lambda: 0.0)))
    journal = Journal()
    list(llm.stream_object(spec.id, None, "скажи", journal=journal))
    assert [п["kind"] for п in journal.entries[0]["retries"]] == [ErrorKind.TRANSPORT]


def test_лимит_видит_расход_даже_когда_журнал_дали_отдельный(make_endpoint):
    """Иначе `spent()` за прогон не растёт и проверка перед ходом бесполезна."""
    spec, rec = make_endpoint([_ход_с_инструментом(),
                               _ход_с_инструментом(call_id="c2")])
    journal = Journal()
    limit = Limit(cap_units=10_000_000)
    llm.run_tools(spec.id, [ЭХО], "зови", on_call=lambda c: "ок",
                  journal=journal, limit=limit, limits=llm.Limits(max_steps=2))
    assert len(journal.entries) == 2
    assert limit.spent() == journal.total_units()      # тот же расход, не вдвое


def test_один_журнал_обоими_путями_не_считается_дважды(make_endpoint):
    spec, rec = make_endpoint([_ход_с_инструментом(),
                               _ход_с_инструментом(call_id="c2")])
    journal = Journal()
    limit = Limit(cap_units=10_000_000, journal=journal)
    llm.run_tools(spec.id, [ЭХО], "зови", on_call=lambda c: "ок",
                  journal=journal, limit=limit, limits=llm.Limits(max_steps=2))
    assert len(journal.entries) == 2


# ── журнал вызывающего и журнал лимита: нужны оба ────────────────────────────
def test_лимит_видит_расход_обычного_вызова_при_отдельном_журнале(make_endpoint):
    """`elif` здесь стоил бы всей проверки: журнал лимита не растёт, `spent()`
    остаётся вчерашним, и лимит не срабатывает никогда — сколько бы вызовов с
    журналом вызывающего ни сделали."""
    spec, rec = make_endpoint([stream_response(openai_stream('{"n":1}', usage=_usage()))])
    журнал = Journal()
    лимит = Limit(cap_units=10_000_000)
    result = llm.generate_object(spec.id, SCHEMA, "дай", journal=журнал, limit=лимит)
    assert result.ok
    assert len(журнал.entries) == 1
    assert лимит.spent() > 0
    assert лимит.spent() == журнал.total_units()       # тот же расход, не вдвое


def test_один_журнал_обоими_путями_обычному_вызову_не_считается_дважды(make_endpoint):
    spec, rec = make_endpoint([stream_response(openai_stream('{"n":1}', usage=_usage()))])
    журнал = Journal()
    лимит = Limit(cap_units=10_000_000, journal=журнал)
    llm.generate_object(spec.id, SCHEMA, "дай", journal=журнал, limit=лимит)
    assert len(журнал.entries) == 1


def test_лимит_срабатывает_после_вызова_с_отдельным_журналом(make_endpoint):
    """Смысл записи — не отчётность ради отчётности: следующий вызов обязан
    упереться в лимит, а не начаться заново с полным остатком."""
    spec, rec = make_endpoint([stream_response(openai_stream('{"n":1}',
                                                             usage=_usage(100000, 0)))])
    журнал = Journal()
    лимит = Limit(cap_units=100100)
    llm.generate_object(spec.id, SCHEMA, "дай", journal=журнал, limit=лимит)
    второй = llm.generate_object(spec.id, SCHEMA, "дай ещё", journal=журнал, limit=лимит)
    assert not второй.ok and второй.error.kind == ErrorKind.LIMIT_EXCEEDED
    assert len(rec.requests) == 1                      # второго вызова не было


def test_лимит_видит_расход_потока_при_отдельном_журнале(make_endpoint):
    """У потока та же развилка и та же цена: «весь отчёт одним вызовом» —
    самый дорогой вызов в системе, и мимо лимита он проходить не должен."""
    spec, rec = make_endpoint([stream_response(openai_stream("ок", usage=_usage()))])
    журнал = Journal()
    лимит = Limit(cap_units=10_000_000)
    list(llm.stream_object(spec.id, None, "скажи", journal=журнал, limit=лимит))
    assert len(журнал.entries) == 1
    assert лимит.spent() > 0 and лимит.spent() == журнал.total_units()


def test_один_журнал_обоими_путями_потоку_не_считается_дважды(make_endpoint):
    spec, rec = make_endpoint([stream_response(openai_stream("ок", usage=_usage()))])
    журнал = Journal()
    лимит = Limit(cap_units=10_000_000, journal=журнал)
    list(llm.stream_object(spec.id, None, "скажи", journal=журнал, limit=лимит))
    assert len(журнал.entries) == 1


def test_отменённый_вызов_записан_с_расходом_а_не_нулём(make_endpoint):
    """Отмена не бесплатна: промпт модель прочитала, часть ответа написала.

    Ноль в записи выглядит как бесплатный вызов, лимит его не замечает —
    и отмена становится способом тратить бюджет мимо учёта.
    """
    spec, rec = make_endpoint([stream_response(openai_stream("длинный ответ"))])
    журнал = Journal()
    result = llm.generate_object(spec.id, SCHEMA, "дай " + "x" * 900,
                                 cancel=lambda: True, journal=журнал)
    assert result.stop == llm.Stop.CANCELLED and not result.ok
    запись = журнал.entries[0]
    assert запись["measured"] is False                 # оценка, и это видно
    assert запись["input"] > 0 and запись["units"] > 0


def test_отменённый_вызов_виден_лимиту(make_endpoint):
    """То же самое с другой стороны: отменить дважды и не подорожать нельзя."""
    spec, rec = make_endpoint([stream_response(openai_stream("длинный ответ"))])
    лимит = Limit(cap_units=10_000_000)
    llm.generate_object(spec.id, SCHEMA, "дай " + "x" * 900,
                        cancel=lambda: True, limit=лимит)
    assert лимит.spent() > 0


# ── где живёт сборка meta записи ────────────────────────────────────────────
def test_забор_записок_о_повторах_одним_местом():
    """`with_retries` и `step_meta` живут в journal, а не в api и loop.

    Правда о том, чего вызов стоил, собирается в одном месте: раньше `loop`
    ходил за забором записок в `api`, то есть знал про журнальную сторону
    соседа, и второе место забора рано или поздно завелось бы отдельно. Тогда
    записка, забытая в транспорте, досталась бы чужому вызову.

    Прежние имена оставлены переэкспортом — на них ссылались снаружи пакета.
    """
    from llm import api, journal as journal_mod, loop
    assert api.with_retries is journal_mod.with_retries
    assert loop._step_meta is journal_mod.step_meta


def test_номер_хода_и_повторы_едут_в_запись_вместе(make_endpoint):
    """`step_meta` обязан класть в запись и номер хода, и записки о повторах:
    ход, вчетверо дольше соседнего из-за пауз, иначе ничем от него не отличим.
    """
    from llm import journal as journal_mod

    class Транспорт:
        """Транспорт, который отдаёт одну записку о повторе и очищает её."""

        def __init__(self):
            self.записки = [{"attempt": 2, "kind": "rate_limit"}]

        def take_retries(self):
            записки, self.записки = self.записки, []
            return записки

    class Бэкенд:
        def __init__(self):
            self._транспорт = Транспорт()

        def transport(self):
            return self._транспорт

    бэкенд = Бэкенд()
    meta = journal_mod.step_meta({"run": "r_1"}, 3, бэкенд)
    assert meta == {"run": "r_1", "step": 3,
                    "retries": [{"attempt": 2, "kind": "rate_limit"}]}
    # Записка принадлежит вызову: второй забор её уже не увидит, иначе она
    # припишется следующему ходу.
    assert journal_mod.step_meta({"run": "r_1"}, 4, бэкенд) == {"run": "r_1", "step": 4}
