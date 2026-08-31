"""
Общая оснастка тестов слоя llm.

Два правила, которые здесь обеспечиваются структурно, а не договорённостью:

1. **Ни один тест не ходит в сеть.** Настоящий транспорт httpx подменён так,
   что любая попытка обратиться к сети роняет тест с внятным текстом. Забыть
   подставить MockTransport физически нельзя.
2. **Ответы записанные.** Потоки собираются из записанных последовательностей
   событий SSE — в том числе таких, которых на живом endpoint'е добиться
   трудно: поток без usage, поток с отказом, обрыв на середине.
"""
from __future__ import annotations

import json

import httpx
import pytest

import llm


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Запрет на сеть. Autouse: действует на каждый тест пакета."""

    def deny(self, request):        # noqa: ANN001
        raise AssertionError(
            f"тест попытался пойти в сеть: {request.method} {request.url}. "
            f"Тесты слоя работают только на записанных ответах.")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", deny)


@pytest.fixture(autouse=True)
def _clean_registry():
    """Реестр endpoint'ов общий на процесс — чистим до и после каждого теста."""
    llm.clear()
    yield
    llm.clear()


# ── сборка записанных ответов ───────────────────────────────────────────────
def sse(events) -> str:
    """Список (имя | None, тело) → текст SSE.

    Именованные события шлёт один протокол, безымянные — другой; функция умеет
    оба, чтобы фикстуры выглядели одинаково.
    """
    out: list = []
    for name, payload in events:
        if name:
            out.append(f"event: {name}")
        body = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
        out.append(f"data: {body}")
        out.append("")
    return "\n".join(out) + "\n"


class Recorder:
    """Поддельный транспорт: отдаёт заготовленные ответы по очереди и помнит,
    какие тела запросов через него прошли.

    Тела запросов проверяются в тестах не ради формы ради формы: именно там
    видно, поставил ли бэкенд брейкпойнт кэша, послал ли флаг include_usage и
    какую ступень лестницы собрал.
    """

    def __init__(self, responses):
        self.responses = list(responses)
        self.requests: list = []
        self.headers: list = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        try:
            self.requests.append(json.loads(request.content or b"{}"))
        except ValueError:
            self.requests.append({})
        self.headers.append(dict(request.headers))
        if not self.responses:
            raise AssertionError("запросов больше, чем заготовлено ответов")
        item = self.responses.pop(0)
        return item(request) if callable(item) else item

    @property
    def last(self) -> dict:
        return self.requests[-1] if self.requests else {}

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self))


def stream_response(events, status: int = 200, request_id: str = "req_test") -> httpx.Response:
    return httpx.Response(status, text=sse(events),
                          headers={"content-type": "text/event-stream",
                                   "x-request-id": request_id})


def json_response(payload, status: int = 200, request_id: str = "req_test") -> httpx.Response:
    return httpx.Response(status, json=payload,
                          headers={"x-request-id": request_id})


def endpoint(recorder: Recorder, spec=None, **overrides):
    """Регистрирует endpoint на поддельном транспорте и возвращает его spec."""
    spec = spec or llm.presets.deepseek(api_key_env="TEST_KEY_UNUSED")
    for name, value in overrides.items():
        setattr(spec, name, value)
    # Повторов в тестах на записанных ответах быть не должно: заготовлен один ответ,
    # а Transport по умолчанию повторил бы 429/5xx четырежды — и съел бы заготовку,
    # да ещё и поспал бы по-настоящему. Тесты про сами повторы задают Retry явно.
    transport = llm.Transport(spec.base_url, headers={"x-test": "1"},
                              client=recorder.client(), retry=llm.Retry(attempts=1))
    llm.register_endpoint(spec, transport=transport)
    return spec


@pytest.fixture
def make_endpoint():
    """Фабрика: (список ответов, spec) → (spec, recorder)."""
    def build(responses, spec=None, **overrides):
        recorder = Recorder(responses)
        registered = endpoint(recorder, spec, **overrides)
        return registered, recorder
    return build


# ── типовые записанные потоки ───────────────────────────────────────────────
def openai_stream(text: str = "готов", usage: dict | None = None,
                  finish: str = "stop", tool_calls=None):
    """Поток формата chat/completions. `usage=None` — счётчиков в потоке нет."""
    events: list = []
    for piece in text:
        events.append((None, {"choices": [{"index": 0, "delta": {"content": piece}}]}))
    for call in tool_calls or []:
        events.append((None, {"choices": [{"index": 0, "delta": {"tool_calls": [call]}}]}))
    events.append((None, {"choices": [{"index": 0, "delta": {}, "finish_reason": finish}]}))
    if usage is not None:
        events.append((None, {"choices": [], "usage": usage}))
    events.append((None, "[DONE]"))
    return events


def anthropic_stream(text: str = "готов", usage_in: dict | None = None,
                     usage_out: dict | None = None, stop_reason: str = "end_turn",
                     tool_use=None):
    """Поток Messages API: usage приходит двумя порциями — вход и выход."""
    events: list = [("message_start",
                     {"type": "message_start",
                      "message": {"usage": usage_in or {"input_tokens": 0}}})]
    events.append(("content_block_start",
                   {"type": "content_block_start", "index": 0,
                    "content_block": {"type": "text", "text": ""}}))
    for piece in text:
        events.append(("content_block_delta",
                       {"type": "content_block_delta", "index": 0,
                        "delta": {"type": "text_delta", "text": piece}}))
    if tool_use:
        events.append(("content_block_start",
                       {"type": "content_block_start", "index": 1,
                        "content_block": {"type": "tool_use", "id": tool_use["id"],
                                          "name": tool_use["name"]}}))
        events.append(("content_block_delta",
                       {"type": "content_block_delta", "index": 1,
                        "delta": {"type": "input_json_delta",
                                  "partial_json": tool_use["args"]}}))
    events.append(("message_delta",
                   {"type": "message_delta", "delta": {"stop_reason": stop_reason},
                    "usage": usage_out or {"output_tokens": 0}}))
    events.append(("message_stop", {"type": "message_stop"}))
    return events
