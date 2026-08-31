"""Повтор временных ошибок в транспорте.

Зачем это вообще есть: отчёт целиком — десятки запросов подряд, и без повтора
прогон падает на первом же 429 «слишком часто» или на первой пятисотке, хотя и
то и другое лечится паузой. Повтор лежит в транспорте, значит достаётся всем
одинаково — обычному вызову, потоку и петле инструментов.

Проверяется и обратное, что важнее: 401 и 402 не повторяются **ни разу**.
Повторять «ключ не принят» и «денег нет» — жечь время на заведомо тот же ответ.

Ни один тест здесь не спит по-настоящему: `Retry` принимает `sleep` и
`monotonic` снаружи, и часы двигает сам поддельный сон.
"""
from __future__ import annotations

import datetime
from email.utils import format_datetime

import httpx
import pytest

import llm
from llm import ErrorKind, LlmError
from llm import layout
from llm.backends.base import Request
from llm.transport import Retry

from .conftest import Recorder, openai_stream, sse, stream_response


class Часы:
    """Поддельные сон и часы: время двигается только сном, прогон не ждёт."""

    def __init__(self):
        self.сейчас = 0.0
        self.сны: list = []

    def sleep(self, seconds: float) -> None:
        self.сны.append(seconds)
        self.сейчас += seconds

    def monotonic(self) -> float:
        return self.сейчас


def _endpoint(ответы, **политика):
    """Endpoint на записанных ответах с подменённым сном. Возвращает (spec, rec, часы)."""
    часы = Часы()
    spec = llm.presets.deepseek(api_key_env="TEST_KEY_UNUSED")
    rec = Recorder(ответы)
    transport = llm.Transport(spec.base_url, client=rec.client(),
                              retry=Retry(sleep=часы.sleep, monotonic=часы.monotonic,
                                          **политика))
    llm.register_endpoint(spec, transport=transport)
    return spec, rec, часы


def _вызов(spec):
    return llm.backend_of(spec.id).complete(Request(parts=layout.simple("х")))


def _429(retry_after: str | None = None):
    headers = {"retry-after": retry_after} if retry_after else {}
    return httpx.Response(429, text="slow down", headers=headers)


def _обрыв_после(события):
    """Ответ, который отдал часть потока и оборвался — беда посреди начатого."""
    def тело():
        yield sse(события).encode("utf-8")
        raise httpx.ReadError("связь оборвалась")
    return httpx.Response(200, content=тело(),
                          headers={"content-type": "text/event-stream"})


# ── что повторяется ─────────────────────────────────────────────────────────
def test_лимит_поставщика_повторяется_и_прогон_доходит():
    spec, rec, часы = _endpoint([_429(), stream_response(openai_stream("готов"))])
    result = _вызов(spec)
    assert result.text == "готов"
    assert len(rec.requests) == 2                    # ровно одна вторая попытка
    assert len(часы.сны) == 1


def test_пятисотка_повторяется():
    spec, rec, часы = _endpoint([httpx.Response(503, text="upstream down"),
                                 stream_response(openai_stream("готов"))])
    assert _вызов(spec).text == "готов"
    assert len(rec.requests) == 2


def test_таймаут_повторяется():
    def таймаутит(request):
        raise httpx.ReadTimeout("не дождались", request=request)
    spec, rec, часы = _endpoint([таймаутит, stream_response(openai_stream("готов"))])
    assert _вызов(spec).text == "готов"
    assert len(rec.requests) == 2


def test_отступ_растёт_и_идёт_с_разбросом():
    """Растёт — чтобы не долбить сервер; с разбросом — чтобы параллельные
    вызовы после общей пятисотки не вернулись к нему в такт."""
    spec, rec, часы = _endpoint([_429(), _429(), _429(),
                                 stream_response(openai_stream("готов"))],
                                attempts=4, base_delay_s=1.0)
    assert _вызов(spec).text == "готов"
    assert len(часы.сны) == 3
    for номер, пауза in enumerate(часы.сны):
        предел = 2 ** номер
        assert предел / 2 <= пауза <= предел, часы.сны
    assert часы.сны[0] < часы.сны[1] < часы.сны[2]


def test_разброс_разный_от_вызова_к_вызову():
    паузы: list = []
    for _ in range(12):
        llm.clear()
        spec, rec, часы = _endpoint([_429(), stream_response(openai_stream("готов"))])
        _вызов(spec)
        паузы.append(часы.сны[0])
    assert len(set(паузы)) > 1, "отступ без разброса — параллельные вызовы в такт"


# ── что не повторяется ──────────────────────────────────────────────────────
def test_ключ_не_принят_не_повторяется():
    spec, rec, часы = _endpoint([httpx.Response(401, text="bad key")])
    with pytest.raises(LlmError) as поймали:
        _вызов(spec)
    assert поймали.value.kind == ErrorKind.AUTH
    assert len(rec.requests) == 1 and часы.сны == []


def test_нет_денег_на_ключе_не_повторяется():
    """402 повторять — просто жечь время: пополнить счёт может только человек."""
    spec, rec, часы = _endpoint([httpx.Response(402, text="insufficient credits")])
    with pytest.raises(LlmError) as поймали:
        _вызов(spec)
    assert поймали.value.kind == ErrorKind.AUTH
    assert len(rec.requests) == 1 and часы.сны == []


def test_переполнение_контекста_не_повторяется():
    """Повтор того же запроса даст ровно тот же ответ: короче он не станет."""
    spec, rec, часы = _endpoint([httpx.Response(
        400, json={"error": {"message": "maximum context length exceeded"}})])
    with pytest.raises(LlmError) as поймали:
        _вызов(spec)
    assert поймали.value.kind == ErrorKind.CONTEXT_OVERFLOW
    assert len(rec.requests) == 1 and часы.сны == []


# ── Retry-After ─────────────────────────────────────────────────────────────
def test_сервер_назвал_срок_и_он_уважается():
    """У 429 Retry-After обычно есть; приходить раньше — получить тот же отказ."""
    spec, rec, часы = _endpoint([_429("7"), stream_response(openai_stream("готов"))])
    assert _вызов(spec).text == "готов"
    assert часы.сны == [7.0]                         # без разброса: срок назван


def test_срок_может_прийти_датой():
    когда = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=30)
    spec, rec, часы = _endpoint([_429(format_datetime(когда, usegmt=True)),
                                 stream_response(openai_stream("готов"))])
    assert _вызов(spec).text == "готов"
    assert 25.0 <= часы.сны[0] <= 31.0


def test_срок_длиннее_бюджета_отказ_сразу_а_не_через_минуту():
    spec, rec, часы = _endpoint([_429("300")], total_s=30.0)
    with pytest.raises(LlmError) as поймали:
        _вызов(spec)
    assert поймали.value.kind == ErrorKind.RATE_LIMIT
    assert часы.сны == [] and len(rec.requests) == 1


# ── потолки ─────────────────────────────────────────────────────────────────
def test_потолок_попыток():
    spec, rec, часы = _endpoint([_429(), _429()], attempts=2)
    with pytest.raises(LlmError) as поймали:
        _вызов(spec)
    assert поймали.value.kind == ErrorKind.RATE_LIMIT
    assert len(rec.requests) == 2 and len(часы.сны) == 1


def test_потолок_общего_времени_не_даёт_вызову_растянуться():
    """Худший случай вызывающего — бюджет, а не «попытки × таймаут»."""
    spec, rec, часы = _endpoint([_429("2"), _429("2"), _429("2")],
                                attempts=9, total_s=5.0)
    with pytest.raises(LlmError):
        _вызов(spec)
    assert часы.сны == [2.0, 2.0]                    # третья пауза в бюджет не влезла
    assert len(rec.requests) == 3
    assert sum(часы.сны) <= 5.0


# ── поток ───────────────────────────────────────────────────────────────────
def test_обрыв_до_первого_события_повторяется():
    """429 и пятисотка приходят кодом ответа, то есть до потока — там повтор
    ничем не рискует: наружу ещё ничего не отдано."""
    spec, rec, часы = _endpoint([_429(), stream_response(openai_stream("готов"))])
    assert _вызов(spec).text == "готов"


def test_обрыв_посреди_отданного_потока_не_повторяется():
    """Повтор с нуля соврал бы про расход (поставщик уже посчитал отданное) и
    удвоил бы напечатанное вызывающему."""
    начало = openai_stream("привет")[:3]
    spec, rec, часы = _endpoint([_обрыв_после(начало),
                                 stream_response(openai_stream("готов"))])
    with pytest.raises(LlmError) as поймали:
        _вызов(spec)
    assert поймали.value.kind == ErrorKind.TRANSPORT
    assert len(rec.requests) == 1                    # второй запрос не ушёл
    assert часы.сны == []


# ── видимость ───────────────────────────────────────────────────────────────
def test_каждая_попытка_оставляет_записку():
    """Молчаливый повтор — необъяснимая задержка в отчёте и потерянная причина."""
    spec, rec, часы = _endpoint([_429("3"), stream_response(openai_stream("готов"))])
    _вызов(spec)
    записки = llm.backend_of(spec.id).transport().take_retries()
    assert len(записки) == 1
    assert записки[0]["kind"] == ErrorKind.RATE_LIMIT
    assert записки[0]["attempt"] == 1 and записки[0]["delay_s"] == 3.0
    assert "slow down" in записки[0]["reason"]
    # Забрали — значит унесли: второй раз та же записка не припишется другому ходу.
    assert llm.backend_of(spec.id).transport().take_retries() == []


def test_повтор_можно_вывести_наружу_сразу():
    """`on_retry` — тот же след, но для служб, которые смотрят за прогоном живьём."""
    видено: list = []
    часы = Часы()
    spec = llm.presets.deepseek(api_key_env="TEST_KEY_UNUSED")
    rec = Recorder([_429("1"), stream_response(openai_stream("готов"))])
    llm.register_endpoint(spec, transport=llm.Transport(
        spec.base_url, client=rec.client(), on_retry=видено.append,
        retry=Retry(sleep=часы.sleep, monotonic=часы.monotonic)))
    _вызов(spec)
    assert [з["kind"] for з in видено] == [ErrorKind.RATE_LIMIT]
