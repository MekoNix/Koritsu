"""Единое перечисление ошибок на все endpoint'ы.

Смысл этих тестов — гарантировать, что вызывающий код **никогда** не разбирает
текст сообщения поставщика: он сравнивает `kind` с константой. Два разных
протокола, отдающих одну и ту же беду по-разному, обязаны дать один kind.
"""
from __future__ import annotations

import httpx
import pytest

import llm
from llm import ErrorKind, LlmError
from llm import layout
from llm.backends.base import Request
from llm.errors import kind_from_status
from llm.transport import Retry

from .conftest import Recorder, stream_response


def _вызов(spec):
    return llm.backend_of(spec.id).complete(Request(parts=layout.simple("х")))


def _без_повторов(ответы, spec=None):
    """Endpoint с выключенными повторами: (spec, recorder).

    Эти тесты про приведение беды к одному виду, а не про политику повторов
    (она в test_retry.py). С повтором по умолчанию транспорт сходил бы за одним
    и тем же 429 четырежды, а заготовленный ответ здесь один.
    """
    spec = spec or llm.presets.deepseek(api_key_env="TEST_KEY_UNUSED")
    rec = Recorder(ответы)
    llm.register_endpoint(spec, transport=llm.Transport(
        spec.base_url, client=rec.client(), retry=Retry(attempts=1)))
    return spec, rec


def test_ключ_не_принят(make_endpoint):
    spec, rec = make_endpoint([httpx.Response(401, json={"error": {"message": "bad key"}})])
    with pytest.raises(LlmError) as поймали:
        _вызов(spec)
    assert поймали.value.kind == ErrorKind.AUTH
    assert not поймали.value.retryable


def test_нет_такой_модели(make_endpoint):
    spec, rec = make_endpoint([httpx.Response(404, json={"error": "no model"})])
    with pytest.raises(LlmError) as поймали:
        _вызов(spec)
    assert поймали.value.kind == ErrorKind.NOT_FOUND


def test_лимит_поставщика_ретраится():
    spec, rec = _без_повторов([httpx.Response(429, text="slow down")])
    with pytest.raises(LlmError) as поймали:
        _вызов(spec)
    assert поймали.value.kind == ErrorKind.RATE_LIMIT
    assert поймали.value.retryable


def test_переполнение_контекста_отличается_от_плохого_запроса(make_endpoint):
    """Оба приходят как 400 с текстом — отдельного кода нет ни у кого."""
    spec, rec = make_endpoint([
        httpx.Response(400, json={"error": {"message": "maximum context length exceeded"}}),
        httpx.Response(400, json={"error": {"message": "unknown field foo"}}),
    ])
    with pytest.raises(LlmError) as первое:
        _вызов(spec)
    assert первое.value.kind == ErrorKind.CONTEXT_OVERFLOW
    with pytest.raises(LlmError) as второе:
        _вызов(spec)
    assert второе.value.kind == ErrorKind.TRANSPORT


def test_серверная_ошибка_ретраится():
    spec, rec = _без_повторов([httpx.Response(503, text="upstream down")])
    with pytest.raises(LlmError) as поймали:
        _вызов(spec)
    assert поймали.value.kind == ErrorKind.TRANSPORT and поймали.value.retryable


def test_таймаут():
    def таймаутит(request):
        raise httpx.ReadTimeout("не дождались", request=request)
    spec, rec = _без_повторов([таймаутит])
    with pytest.raises(LlmError) as поймали:
        _вызов(spec)
    assert поймали.value.kind == ErrorKind.TIMEOUT and поймали.value.retryable


def test_сетевая_ошибка():
    def рвётся(request):
        raise httpx.ConnectError("нет связи", request=request)
    spec, rec = _без_повторов([рвётся])
    with pytest.raises(LlmError) as поймали:
        _вызов(spec)
    assert поймали.value.kind == ErrorKind.TRANSPORT


def test_ошибка_в_потоке_второго_протокола(make_endpoint):
    """Messages API умеет прислать ошибку событием посреди потока."""
    spec = llm.presets.anthropic(api_key_env="TEST_KEY_UNUSED")
    события = [("message_start", {"type": "message_start", "message": {"usage": {}}}),
               ("error", {"type": "error",
                          "error": {"type": "overloaded_error", "message": "перегружен"}})]
    spec, rec = make_endpoint([stream_response(события)], spec=spec)
    with pytest.raises(LlmError) as поймали:
        _вызов(spec)
    assert поймали.value.kind == ErrorKind.TRANSPORT


def test_ошибка_по_проводу_становится_result_а_не_исключением(make_endpoint):
    """Наружу api не бросает: один тип возврата на все исходы."""
    spec, rec = make_endpoint([httpx.Response(401, text="nope")])
    result = llm.generate_object(spec.id, {"type": "object", "properties": {},
                                           "additionalProperties": False}, "дай")
    assert not result.ok and result.error.kind == ErrorKind.AUTH
    assert result.stop == llm.Stop.ERROR


def test_ошибка_попадает_в_журнал_с_видом():
    spec, rec = _без_повторов([httpx.Response(429, text="slow")])
    journal = llm.Journal()
    llm.generate_object(spec.id, {"type": "object", "properties": {},
                                  "additionalProperties": False}, "дай", journal=journal)
    assert journal.entries[0]["error_kind"] == ErrorKind.RATE_LIMIT


def test_соответствие_кодов_видам():
    assert kind_from_status(403) == ErrorKind.AUTH
    assert kind_from_status(408) == ErrorKind.TIMEOUT
    assert kind_from_status(504) == ErrorKind.TIMEOUT
    assert kind_from_status(418) == ErrorKind.TRANSPORT


def test_ретраить_осмысленно_только_три_вида():
    assert set(ErrorKind.RETRYABLE) == {ErrorKind.RATE_LIMIT, ErrorKind.TIMEOUT,
                                        ErrorKind.TRANSPORT}


def test_плохой_запрос_не_ретраится_хотя_вид_у_него_транспортный():
    """«Прочие 4xx» приведены к `transport`, но повтор того же тела даст тот же
    ответ. Ретраится 5xx и обрыв — не ошибка в запросе."""
    плохой = LlmError(kind_from_status(400), "unknown field foo", status=400)
    assert плохой.kind == ErrorKind.TRANSPORT and not плохой.retryable
    assert LlmError(ErrorKind.TRANSPORT, "обрыв").retryable          # без кода — сеть
    assert LlmError(kind_from_status(503), status=503).retryable
    assert LlmError(kind_from_status(429), status=429).retryable
    assert LlmError(kind_from_status(408), status=408).retryable


def test_идентификатор_запроса_доходит_до_ошибки():
    """Единственная зацепка при разборе «списали деньги, а ответа нет».

    Имя теста называет ровно то, что он проверяет: путь ошибки. Успешный вызов
    проверяется отдельно — раньше эти два пути прикрывались одним тестом с
    именем пошире проверки, и `Result.request_id` не заполнялся вовсе.
    """
    spec, rec = _без_повторов([httpx.Response(500, text="oops",
                                              headers={"x-request-id": "req_42"})])
    with pytest.raises(LlmError) as поймали:
        _вызов(spec)
    assert поймали.value.request_id == "req_42"


def test_идентификатор_запроса_доходит_до_результата(make_endpoint):
    """Тот же идентификатор, но у **успешного** вызова — и в журнале.

    Разбирают-то как раз успешные: «списали деньги, а ответа нет» это вызов,
    который вернулся с 200 и пустотой. Без идентификатора в записи журнала
    предъявить поставщику нечего, а поле у всех успешных вызовов было null.
    """
    from .conftest import openai_stream
    spec, rec = make_endpoint([stream_response(openai_stream("{}"),
                                               request_id="req_777")])
    журнал = llm.Journal()
    result = llm.generate_object(
        spec.id, {"type": "object", "properties": {}, "additionalProperties": False},
        "дай", journal=журнал)
    assert result.request_id == "req_777"
    assert журнал.entries[0]["request_id"] == "req_777"


def test_идентификатор_запроса_доходит_до_записи_потока(make_endpoint):
    """У потока запись делается в finally, и идентификатор обязан дойти и туда."""
    from .conftest import openai_stream
    spec, rec = make_endpoint([stream_response(openai_stream("ок"),
                                               request_id="req_stream")])
    журнал = llm.Journal()
    list(llm.stream_object(spec.id, None, "скажи", journal=журнал))
    assert журнал.entries[0]["request_id"] == "req_stream"


def test_идентификатор_не_переезжает_на_следующий_вызов(make_endpoint):
    """Забирают, а не подсматривают: чужой идентификатор в записи хуже пустого.

    Вызов, упавший до заголовков (сеть не ответила), обязан остаться без
    идентификатора, а не унаследовать его от удачного предыдущего — иначе
    поставщику предъявят чужой запрос.
    """
    from .conftest import openai_stream
    spec, rec = make_endpoint([stream_response(openai_stream("ок"),
                                               request_id="req_first"),
                               httpx.Response(500, text="oops")])
    backend = llm.backend_of(spec.id)
    assert _вызов_на(backend).request_id == "req_first"
    журнал = llm.Journal()
    llm.generate_object(spec.id, {"type": "object", "properties": {},
                                  "additionalProperties": False}, "дай",
                        journal=журнал)
    assert журнал.entries[0]["request_id"] is None


def test_идентификатор_не_переезжает_с_упавшего_вызова(make_endpoint):
    """Вызов, не дошедший до заголовков, обязан остаться вовсе без него.

    Тонкий путь: предыдущий вызов получил заголовки (и идентификатор), но
    кончился ошибкой внутри 200-потока — и `complete()` поднял её, не дойдя до
    места, где идентификатор забирают. Оставленный в транспорте, он достался бы
    следующему вызову, который до заголовков даже не добрался, — и поставщику
    предъявили бы чужой запрос.
    """
    from .conftest import openai_stream

    def оборвать(request):
        raise httpx.ConnectError("сеть не отвечает")

    события = [(None, {"choices": [{"index": 0, "delta": {"content": "нача"}}]}),
               (None, {"error": {"code": 502, "message": "beда у поставщика"}})]
    spec, rec = make_endpoint([stream_response(события, request_id="req_alien"),
                               оборвать])
    with pytest.raises(LlmError):
        _вызов_на(llm.backend_of(spec.id))
    журнал = llm.Journal()
    with pytest.raises(LlmError):
        list(llm.stream_object(spec.id, None, "скажи", journal=журнал))
    assert журнал.entries[0]["request_id"] is None


def _вызов_на(backend):
    return backend.complete(Request(parts=layout.simple("х")))


# ── ключ ────────────────────────────────────────────────────────────────────
def test_ключ_не_хранится_в_описании_endpointа(monkeypatch):
    """В описании — имя переменной, а не значение: описание попадает в логи."""
    spec = llm.presets.deepseek()
    assert "sk-test-secret" not in repr(spec)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-secret")
    assert spec.resolve_key() == "sk-test-secret"
    assert "sk-test-secret" not in repr(spec)


def test_ключ_читается_из_файла_когда_переменной_нет(monkeypatch, tmp_path):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    файл = tmp_path / "deepseek.key"
    файл.write_text("sk-from-file\n", encoding="utf-8")
    spec = llm.presets.deepseek(api_key_file=str(файл))
    assert spec.resolve_key() == "sk-from-file"


def test_нет_ключа_ни_там_ни_там(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    spec = llm.presets.deepseek(api_key_file="/такого/пути/нет")
    assert spec.has_key() is False
    with pytest.raises(LlmError) as поймали:
        spec.resolve_key()
    assert поймали.value.kind == ErrorKind.AUTH


def test_незарегистрированный_endpoint():
    with pytest.raises(LlmError) as поймали:
        llm.capabilities("ep_которого_нет")
    assert поймали.value.kind == ErrorKind.NOT_FOUND


def test_неизвестный_протокол():
    spec = llm.EndpointSpec(id="ep_x", protocol="грпц", base_url="http://x", model="m")
    with pytest.raises(LlmError) as поймали:
        llm.register_endpoint(spec)
    assert поймали.value.kind == ErrorKind.UNSUPPORTED


def test_нет_денег_на_ключе_не_ретраится():
    """402 отдают и DeepSeek («Insufficient Balance»), и шлюзы. Ретраить его
    бессмысленно, поэтому он обязан быть не `transport`, а `auth`."""
    assert kind_from_status(402) == ErrorKind.AUTH
    assert not LlmError(kind_from_status(402)).retryable


def test_ошибка_внутри_успешного_потока(make_endpoint):
    """Шлюз уже отдал 200 и заголовки, а беда случилась позже — сообщить о ней
    HTTP-кодом уже нечем, и она приезжает полем `error` внутри события."""
    events = [(None, {"choices": [{"index": 0, "delta": {"content": "на"}}]}),
              (None, {"error": {"code": 429, "message": "provider is overloaded"}})]
    spec, rec = make_endpoint([stream_response(events)])
    with pytest.raises(LlmError) as поймали:
        _вызов(spec)
    assert поймали.value.kind == ErrorKind.RATE_LIMIT
    assert поймали.value.retryable
    assert "overloaded" in поймали.value.message


def test_ошибка_в_потоке_приводится_той_же_таблицей(make_endpoint):
    """Код внутри объекта ошибки означает ровно то же, что означал бы
    HTTP-код: одна таблица на оба случая, а не вторая правда рядом."""
    events = [(None, {"error": {"code": 402, "message": "недостаточно средств"}})]
    spec, rec = make_endpoint([stream_response(events)])
    with pytest.raises(LlmError) as поймали:
        _вызов(spec)
    assert поймали.value.kind == ErrorKind.AUTH
    assert поймали.value.status == 402


def test_переполнение_контекста_видно_и_внутри_потока(make_endpoint):
    events = [(None, {"error": {"code": 400,
                                "message": "maximum context length exceeded"}})]
    spec, rec = make_endpoint([stream_response(events)])
    with pytest.raises(LlmError) as поймали:
        _вызов(spec)
    assert поймали.value.kind == ErrorKind.CONTEXT_OVERFLOW
