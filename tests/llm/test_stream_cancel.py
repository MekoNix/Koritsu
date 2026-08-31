"""Стриминг и отмена.

Стриминг внутри слоя безусловен (А.4): отмена в обоих протоколах — это закрытие
потока, другого способа нет. Отсюда и проверки: отменённый прогон обязан вернуть
Stop.CANCELLED с уже накопленным расходом, а не исключение — деньги за
отменённый вызов всё равно потрачены и в журнал попасть должны.
"""
from __future__ import annotations

import llm
from llm import Stop
from llm import layout
from llm.backends.base import Request
from llm.transport import _iter_sse

from .conftest import anthropic_stream, openai_stream, stream_response


def test_куски_приходят_по_одному(make_endpoint):
    spec, rec = make_endpoint([stream_response(openai_stream("привет"))])
    куски = [c for c in llm.stream_object(spec.id, None, "скажи") if c.kind == "text"]
    assert "".join(c.text for c in куски) == "привет"
    assert len(куски) == 6


def test_поток_завершается_счётчиками_и_причиной(make_endpoint):
    spec, rec = make_endpoint([stream_response(openai_stream(
        "ок", usage={"prompt_tokens": 7, "completion_tokens": 2}))])
    хвост = list(llm.stream_object(spec.id, None, "скажи"))[-2:]
    assert хвост[0].kind == "usage" and хвост[0].usage.input == 7
    assert хвост[1].kind == "stop" and хвост[1].stop == Stop.END_TURN


def test_отмена_посреди_потока_даёт_cancelled(make_endpoint):
    """Отменяем после третьего куска: соединение закрывается на месте."""
    spec, rec = make_endpoint([stream_response(openai_stream("двенадцать"))])
    видено: list = []

    def прервать():
        return len(видено) >= 3

    for кусок in llm.stream_object(spec.id, None, "скажи", cancel=прервать):
        if кусок.kind == "text":
            видено.append(кусок.text)
        последний = кусок
    assert последний.stop == Stop.CANCELLED
    assert len(видено) <= 4          # после отмены новых кусков не приходит


def test_отмена_в_generate_не_исключение_а_исход(make_endpoint):
    """Вызывающий получает нормальный Result: расход уже потрачен и он в нём."""
    spec, rec = make_endpoint([stream_response(openai_stream("длинный ответ"))])
    result = llm.generate_object(
        spec.id, {"type": "object", "properties": {}, "additionalProperties": False},
        "дай", cancel=lambda: True)
    assert result.stop == Stop.CANCELLED and not result.ok


def test_отмена_до_первого_куска(make_endpoint):
    spec, rec = make_endpoint([stream_response(openai_stream("что-то"))])
    куски = list(llm.stream_object(spec.id, None, "скажи", cancel=lambda: True))
    assert куски[-1].stop == Stop.CANCELLED
    assert not any(c.kind == "text" for c in куски)


def test_поток_второго_протокола_отменяется_так_же(make_endpoint):
    spec = llm.presets.anthropic(api_key_env="TEST_KEY_UNUSED")
    spec, rec = make_endpoint([stream_response(anthropic_stream("двенадцать"))],
                              spec=spec)
    куски = list(llm.stream_object(spec.id, None, "скажи", cancel=lambda: True))
    assert куски[-1].stop == Stop.CANCELLED


# ── разбор SSE ──────────────────────────────────────────────────────────────
def test_многострочный_data_склеивается():
    """Спецификация SSE: несколько data-строк подряд склеиваются через \\n."""
    строки = ["event: x", "data: пер", "data: вая", "", "data: вторая", ""]
    события = list(_iter_sse(строки))
    assert события == [("x", "пер\nвая"), (None, "вторая")]


def test_комментарии_и_keepalive_пропускаются():
    строки = [": keep-alive", "data: тело", ""]
    assert list(_iter_sse(строки)) == [(None, "тело")]


def test_битая_строка_в_потоке_не_роняет_прогон(make_endpoint):
    """У совместимых серверов встречается мусор, а ответ при этом целый."""
    события = [(None, "не json"),
               (None, {"choices": [{"delta": {"content": "ок"}}]}),
               (None, {"choices": [{"delta": {}, "finish_reason": "stop"}]})]
    spec, rec = make_endpoint([stream_response(события)])
    result = llm.backend_of(spec.id).complete(Request(parts=layout.simple("х")))
    assert result.text == "ок" and result.stop == Stop.END_TURN


def test_непотоковой_формы_наружу_нет_а_внутри_один_путь(make_endpoint):
    """generate_* и stream_* идут одним потоковым путём: в теле запроса stream."""
    spec, rec = make_endpoint([stream_response(openai_stream('{}'))])
    llm.generate_object(spec.id, {"type": "object", "properties": {},
                                  "additionalProperties": False}, "дай")
    assert rec.last["stream"] is True
