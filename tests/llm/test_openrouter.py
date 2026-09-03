"""Пресет OpenRouter: шлюз как обычный OpenAI-совместимый endpoint.

Смысл файла тот же, что у test_backends: доказать, что особенности шлюза
кончаются в ДАННЫХ пресета и в общих механизмах бэкенда, а ветвления «если это
OpenRouter» нигде не появилось. Поэтому здесь почти нет проверок поведения —
почти всё проверяет, что заполненная форма Б.3 даёт правильное тело запроса и
правильные заголовки.

Всё на записанных ответах: фикстура из conftest ломает транспорт httpx
структурно, в сеть отсюда не сходить.

Числа и имена полей взяты из первоисточников 2026-08-30 — из документации
OpenRouter и живого ответа `/api/v1/models`; ссылки в докстроке пресета.
"""
from __future__ import annotations

import pytest

import llm
from llm import ErrorKind, LlmError, PrefixCache, Stop, Structured
from llm import layout
from llm.backends.base import Request
from llm.backends.openai_compat import OpenAICompatBackend

from .conftest import openai_stream, stream_response


@pytest.fixture
def шлюз(make_endpoint):
    """endpoint OpenRouter на поддельном транспорте."""
    def build(responses, **overrides):
        spec = llm.presets.openrouter(api_key_env="TEST_KEY_UNUSED")
        return make_endpoint(responses, spec=spec, **overrides)
    return build


# ── форма Б.3: адрес, модель, цены ──────────────────────────────────────────
def test_адрес_складывается_в_пути_протокола():
    """base_url кончается на /api, а пути протокола начинаются с /v1 — вместе
    они дают документированные адреса шлюза. Ошибка здесь стоила бы 404 на
    первом же вызове, а видна только сложением двух строк из разных файлов."""
    spec = llm.presets.openrouter()
    backend = OpenAICompatBackend(spec)
    assert spec.base_url + backend.stream_path == \
        "https://openrouter.ai/api/v1/chat/completions"
    assert spec.base_url + backend.models_path == "https://openrouter.ai/api/v1/models"


def test_цены_не_переживают_смену_модели():
    """Цена — свойство модели, а не шлюза. Пресет с ценами Gemini и
    подменённой моделью врал бы про деньги молча, а `None` честно означает
    «по этому endpoint'у деньги не считаем» (В.5)."""
    известная = llm.presets.openrouter()
    assert известная.model == "google/gemini-2.5-flash-lite"
    assert известная.prices.filled()
    assert известная.context_tokens == 1048576

    чужая = llm.presets.openrouter(model="какой-то/новый-релиз")
    assert not чужая.prices.filled()
    assert чужая.context_tokens is None


def test_цены_дают_веса_приведённых_единиц():
    """Веса единиц (В.2) берутся из цен endpoint'а, а не из умолчаний. У
    Gemini 2.5 Flash Lite чтение кэша — 0.1× входа (совпало с умолчанием),
    а выход — 4×, а не 5×, и лимит обязан считать по 4."""
    spec = llm.presets.openrouter()
    веса = llm.usage.weights(spec.prices)
    assert веса["read"] == pytest.approx(0.1)
    assert веса["out"] == pytest.approx(4.0)


def test_у_дешёвой_модели_с_миллионом_контекста_цены_тоже_есть():
    """Второй разумный выбор: то же миллионное окно вчетверо дешевле. Её
    раздают 17 провайдеров, четверо без структурированного вывода, — и это
    ровно тот случай, ради которого стоит require_parameters."""
    spec = llm.presets.openrouter(model="deepseek/deepseek-v4-flash")
    assert spec.prices.input_per_mtok == pytest.approx(0.0801)
    assert spec.context_tokens == 1048576


def test_пресет_виден_в_реестре_пресетов():
    """Через PRESETS его находит и `python -m llm probe --preset openrouter`."""
    assert "openrouter" in llm.presets.PRESETS
    assert llm.presets.make("openrouter").label == "OpenRouter"


# ── заголовки ───────────────────────────────────────────────────────────────
def test_визитка_едет_в_заголовках_рядом_с_ключом(monkeypatch):
    """`X-OpenRouter-Title` необязателен для вызова — он нужен только для
    рейтингов openrouter.ai. Едет через общий extra_headers, отдельного кода
    под шлюз для этого не понадобилось."""
    monkeypatch.setenv("OPENROUTER_KEY_ДЛЯ_ТЕСТА", "sk-or-test")
    spec = llm.presets.openrouter(api_key_env="OPENROUTER_KEY_ДЛЯ_ТЕСТА",
                                  api_key_file=None)
    головы = OpenAICompatBackend(spec).headers()
    assert головы["Authorization"] == "Bearer sk-or-test"
    assert головы["X-OpenRouter-Title"] == "Koritsu"


def test_выдуманного_адреса_проекта_наружу_не_уходит(шлюз):
    """`HTTP-Referer` не шлём, пока адреса у проекта нет.

    Заголовок необязательный: без него шлюз работает так же, а с заглушкой
    `https://github.com/koritsu` мы сообщали бы о себе заведомо неверные
    сведения — и не один раз, а в каждом живом запросе. Проверяется на
    настоящем исходящем запросе, а не на описании: важно, что именно уехало.
    """
    spec, rec = шлюз([stream_response(openai_stream())])
    assert "HTTP-Referer" not in spec.extra_headers
    llm.backend_of(spec.id).complete(Request(parts=layout.simple("привет")))
    ушедшие = {k.lower() for k in rec.headers[-1]}
    assert "http-referer" not in ушедшие and "referer" not in ушедшие


def test_адрес_добавляется_данными_когда_появится(monkeypatch):
    """Появится адрес — правится форма Б.3, а не код: заголовок кладут
    в extra_headers пресета или через overrides."""
    monkeypatch.setenv("OPENROUTER_KEY_ДЛЯ_ТЕСТА", "sk-or-test")
    spec = llm.presets.openrouter(api_key_env="OPENROUTER_KEY_ДЛЯ_ТЕСТА",
                                  api_key_file=None,
                                  extra_headers={"HTTP-Referer": "https://koritsu.ru",
                                                 "X-OpenRouter-Title": "Koritsu"})
    assert OpenAICompatBackend(spec).headers()["HTTP-Referer"] == "https://koritsu.ru"


def test_ключ_в_описании_не_хранится():
    """Тот же инвариант, что и у остальных пресетов: в spec лежит ИМЯ
    переменной, а не значение, и в repr ключ попасть не может."""
    spec = llm.presets.openrouter()
    assert spec.api_key_env == "OPENROUTER_API_KEY"
    assert "OPENROUTER_API_KEY" in repr(spec)
    with pytest.raises(LlmError) as поймали:
        spec.resolve_key()
    assert поймали.value.kind == ErrorKind.AUTH


# ── тело запроса ────────────────────────────────────────────────────────────
def test_маршрутизация_ограничена_умеющими_провайдерами(шлюз):
    """Главное поле пресета. По умолчанию шлюз молча игнорирует параметр,
    которого провайдер не понимает: проба зафиксировала бы json_schema, попав
    на умеющего, а боевой запрос вернул бы свободный текст без всякой ошибки.
    require_parameters превращает молчание в честный 503."""
    spec, rec = шлюз([stream_response(openai_stream())])
    llm.backend_of(spec.id).complete(Request(parts=layout.simple("привет")))
    assert rec.last["provider"] == {"require_parameters": True}


def test_флаг_include_usage_не_шлётся(шлюз):
    """У шлюза usage приходит всегда, а `stream_options.include_usage`
    объявлен устаревшим и не действует. Лишнее поле в теле — риск на ровном
    месте, и слать его незачем."""
    spec, rec = шлюз([stream_response(openai_stream())])
    llm.backend_of(spec.id).complete(Request(parts=layout.simple("привет")))
    assert "stream_options" not in rec.last
    assert "usage" not in rec.last


def test_лестница_собирается_как_у_всех(шлюз):
    """Ступени — общий механизм; у шлюза они обязаны выглядеть ровно так же,
    как у любого совместимого сервера, плюс подмешанный `provider`."""
    schema = {"type": "object", "properties": {"n": {"type": "integer"}},
              "required": ["n"], "additionalProperties": False}
    spec, rec = шлюз([stream_response(openai_stream('{"n":1}')),
                      stream_response(openai_stream("", tool_calls=[
                          {"index": 0, "id": "c1",
                           "function": {"name": "set_values",
                                        "arguments": '{"n":1}'}}]))])
    backend = llm.backend_of(spec.id)
    backend.complete(Request(parts=layout.simple("дай"), schema=schema,
                             structured_step=Structured.JSON_SCHEMA))
    assert rec.last["response_format"]["json_schema"]["strict"] is True
    assert rec.last["provider"] == {"require_parameters": True}

    backend.complete(Request(parts=layout.simple("дай"), schema=schema,
                             structured_step=Structured.TOOL_STRICT))
    assert rec.last["tool_choice"]["function"]["name"] == "set_values"


def test_заявка_занижена_а_лестница_умеет_выше(шлюз):
    """`declared.structured_output` намеренно скромный: занизить безопаснее,
    чем завысить. Бэкенд не даст собрать ступень сильнее заявленной, пока
    проба не подтвердит обратное, — и подтверждённое перекрывает заявку."""
    spec, rec = шлюз([])
    backend = llm.backend_of(spec.id)
    assert spec.declared.structured_output == Structured.JSON_OBJECT
    assert backend.supported_step(Structured.JSON_SCHEMA) == Structured.JSON_OBJECT

    # Через реестр, а не присваиванием в spec.probe: присваивание мимо реестра
    # работает ровно до первой вещи, которую проба меняет ПОМИМО поля probe.
    llm.update_probe(spec.id, llm.Probe(at="2026-08-30", ok=True,
                                        structured_output=Structured.JSON_SCHEMA))
    assert backend.supported_step(Structured.JSON_SCHEMA) == Structured.JSON_SCHEMA


# ── счётчики ────────────────────────────────────────────────────────────────
def test_кэш_вычитается_из_входа(шлюз):
    """Форма usage документирована: кэш посчитан ВНУТРИ prompt_tokens (в
    примере документации prompt_tokens 10339 при cached_tokens 10318, а
    total_tokens равен сумме входа и выхода). Без вычитания кэшированные
    токены посчитались бы дважды и приведённые единицы соврали бы вдвое."""
    usage = {"prompt_tokens": 10339, "completion_tokens": 60,
             "total_tokens": 10399,
             "prompt_tokens_details": {"cached_tokens": 10318,
                                       "cache_write_tokens": 0},
             "completion_tokens_details": {"reasoning_tokens": 0},
             "cost": 0.00014}
    spec, rec = шлюз([stream_response(openai_stream("ок", usage=usage))])
    result = llm.backend_of(spec.id).complete(Request(parts=layout.simple("привет")))
    assert result.usage.input == 21          # 10339 − 10318
    assert result.usage.cache_read == 10318
    assert result.usage.output == 60
    assert result.usage.measured is True
    # Сырое хранится дословно: если нормализация окажется неверной,
    # пересчитать можно будет задним числом (В.2).
    assert result.raw_usage["cost"] == 0.00014


def test_запись_кэша_читается_из_деталей_входа(шлюз):
    """`prompt_tokens_details.cache_write_tokens` — имя, которого до шлюза не
    встречалось; оно тоже посчитано внутри входа и тоже вычитается."""
    usage = {"prompt_tokens": 194, "completion_tokens": 2,
             "prompt_tokens_details": {"cached_tokens": 0,
                                       "cache_write_tokens": 100}}
    spec, rec = шлюз([stream_response(openai_stream("ок", usage=usage))])
    result = llm.backend_of(spec.id).complete(Request(parts=layout.simple("привет")))
    assert result.usage.cache_write == 100
    assert result.usage.input == 94


def test_размышления_считаются_отдельно(шлюз):
    spec, rec = шлюз([stream_response(openai_stream("ок", usage={
        "prompt_tokens": 10, "completion_tokens": 300,
        "completion_tokens_details": {"reasoning_tokens": 250}}))])
    result = llm.backend_of(spec.id).complete(Request(parts=layout.simple("думай")))
    assert result.usage.reasoning == 250
    assert result.usage.output == 300


# ── ошибки ──────────────────────────────────────────────────────────────────
def test_нет_подходящего_провайдера_это_ошибка_а_не_текст(шлюз):
    """Цена require_parameters: вместо тихой деградации приходит 503. Громкий
    отказ лучше молчаливой лжи, но вызывающий обязан увидеть именно kind."""
    import httpx
    spec, rec = шлюз([httpx.Response(503, json={
        "error": {"code": 503,
                  "message": "No endpoints found that support all parameters"}})])
    with pytest.raises(LlmError) as поймали:
        llm.backend_of(spec.id).complete(Request(parts=layout.simple("привет")))
    assert поймали.value.kind == ErrorKind.TRANSPORT
    assert поймали.value.status == 503


def test_кончились_деньги_не_ретраится(шлюз):
    """402 у шлюза значит «на ключе нет средств». Ретраить бессмысленно."""
    import httpx
    spec, rec = шлюз([httpx.Response(402, json={
        "error": {"code": 402, "message": "Insufficient credits"}})])
    with pytest.raises(LlmError) as поймали:
        llm.backend_of(spec.id).complete(Request(parts=layout.simple("привет")))
    assert поймали.value.kind == ErrorKind.AUTH
    assert not поймали.value.retryable


def test_обрыв_на_середине_потока(шлюз):
    """Документированное поведение: «any error occurred while the LLM is
    producing the output will be emitted in the response body or as an SSE
    data event» — то есть при уже отданном HTTP 200."""
    events = [(None, {"choices": [{"index": 0, "delta": {"content": "нача"}}]}),
              (None, {"error": {"code": 502,
                                "message": "Provider returned invalid response"}})]
    spec, rec = шлюз([stream_response(events)])
    with pytest.raises(LlmError) as поймали:
        llm.backend_of(spec.id).complete(Request(parts=layout.simple("привет")))
    assert поймали.value.kind == ErrorKind.TRANSPORT
    assert поймали.value.retryable


def test_finish_reason_error_это_остановка_ошибкой(шлюз):
    """Шлюз приводит finish_reason к пяти значениям, и `error` — одно из них.
    Без своей строки в таблице оно молча читалось бы как «модель закончила»."""
    spec, rec = шлюз([stream_response(openai_stream("часть", finish="error"))])
    result = llm.backend_of(spec.id).complete(Request(parts=layout.simple("привет")))
    assert result.stop == Stop.ERROR
    assert result.ok is False


# ── возможности ─────────────────────────────────────────────────────────────
def test_возможности_показывают_заявку_а_не_галочку(шлюз):
    """Ключа в сборке нет, пробы не было — значит НИЧЕГО не подтверждено, и
    интерфейс не должен рисовать зелёную галочку (Ж.6)."""
    spec, rec = шлюз([])
    caps = llm.capabilities(spec.id)
    assert caps.probed is False
    assert caps.confirmed == set()
    assert caps.structured_output == Structured.JSON_OBJECT
    assert caps.prefix_cache == PrefixCache.AUTOMATIC
    assert caps.usage_in_stream is True
    assert caps.effort is False          # «без thinking, просто api»
    assert caps.supports_tools() is True


def test_проба_перекрывает_заявку(шлюз):
    """Правило Б.4 — общее, но проверить его на новом пресете стоит: заявка
    здесь занижена намеренно, и весь расчёт на то, что проба её поднимет."""
    spec, rec = шлюз([])
    # Через реестр: `update_probe` — единственная дверь для результата пробы,
    # и присваивание мимо неё проверяло бы не тот путь.
    llm.update_probe(spec.id, llm.Probe(at="2026-08-30T00:00:00Z", ok=True,
                                        structured_output=Structured.JSON_SCHEMA,
                                        tools=True))
    caps = llm.capabilities(spec.id)
    assert caps.structured_output == Structured.JSON_SCHEMA
    assert caps.is_confirmed("structured_output")
    # Чего проба не проверяла, остаётся заявленным и НЕ подтверждённым.
    assert not caps.is_confirmed("prefix_cache")


def test_ключ_с_кириллицей_даёт_нашу_ошибку(monkeypatch):
    """Ключ уезжает в заголовок HTTP: не-ASCII валил сырым UnicodeEncodeError из httpx.

    Беда живая: русская «с» вместо латинской при копировании ключа из переписки.
    """
    from llm import errors, presets

    spec = presets.openrouter()
    monkeypatch.setenv(spec.api_key_env, "sk-or-v1-обычная-опечатка")
    with pytest.raises(errors.LlmError) as e:
        spec.resolve_key()
    assert e.value.kind == errors.ErrorKind.AUTH
    assert "вне латиницы" in str(e.value)


def test_обычный_ключ_проходит(monkeypatch):
    from llm import presets

    spec = presets.openrouter()
    monkeypatch.setenv(spec.api_key_env, "  sk-or-v1-0123456789  ")
    assert spec.resolve_key() == "sk-or-v1-0123456789"
