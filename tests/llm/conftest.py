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
import os

import httpx
import pytest

import llm
from llm.backends.cli import CliRunner


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


# ── поддельный подпроцесс для протокола cli ─────────────────────────────────
class FakeCli(CliRunner):
    """Поддельный запускатель команды: подделка того же места, что MockTransport.

    Настоящую команду `claude` тесты звать не должны — это деньги и секунды, — а
    запрет на сеть её не ловит: она ходит из другого процесса. Поэтому
    подменяется ровно один метод, `run_once`; всё остальное — записки о
    повторах, идентификатор ответа, политика повторов — берётся у настоящего
    `CliRunner`, иначе тесты проверяли бы не тот код, который работает.

    Заготовка — либо кортеж `(код возврата, stdout, stderr)`, либо вызываемый
    объект `(argv, промпт, cancel) -> кортеж`, который волен и бросить.
    """

    def __init__(self, responses, retry=None, command="claude"):
        super().__init__(command=command, retry=retry or llm.Retry(attempts=1))
        self.responses = list(responses)
        self.runs: list = []          # что именно запускали, по разу на попытку

    def executable(self):
        return "/поддельный/путь/claude"

    def run_once(self, argv, stdin_text, cwd, env, timeout_s, cancel=None,
                 endpoint_id=""):
        argv = list(argv)
        system = ""
        if "--system-prompt-file" in argv:
            path = argv[argv.index("--system-prompt-file") + 1]
            with open(path, "r", encoding="utf-8") as fh:
                system = fh.read()
        self.runs.append({"argv": argv, "prompt": stdin_text, "system": system,
                          "cwd": cwd, "env": dict(env), "timeout_s": timeout_s,
                          # что лежало в рабочем каталоге на момент запуска:
                          # проверить это после вызова уже нельзя, каталог убран
                          "в_каталоге": sorted(os.listdir(cwd))})
        if not self.responses:
            raise AssertionError("запусков больше, чем заготовлено ответов")
        item = self.responses.pop(0)
        return item(argv, stdin_text, cancel) if callable(item) else item

    @property
    def last(self) -> dict:
        return self.runs[-1] if self.runs else {}


def cli_json(result: str = "готово", *, model_usage=None, turn_usage=None,
             is_error: bool = False, stop_reason: str = "end_turn",
             denials=None, session_id: str = "sess_тест",
             total_cost_usd: float = 0.0016, **extra) -> str:
    """Записанный ответ `claude -p --output-format json`.

    Поля и их значения сняты с живого вызова 2026-08-31; здесь их ровно столько,
    сколько читает бэкенд, плюс те, что он кладёт в raw_usage.
    """
    payload = {
        "type": "result", "subtype": "success", "is_error": is_error,
        "stop_reason": stop_reason, "num_turns": 1, "duration_ms": 1435,
        "session_id": session_id, "total_cost_usd": total_cost_usd,
        "permission_denials": list(denials or []),
        "result": result,
        "usage": turn_usage if turn_usage is not None else {
            "input_tokens": 252, "output_tokens": 74,
            "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
            "output_tokens_details": {"thinking_tokens": 64},
        },
    }
    if model_usage is not None:
        payload["modelUsage"] = model_usage
    elif turn_usage is None:
        payload["modelUsage"] = {"claude-haiku-4-5-20251001": {
            "inputTokens": 1151, "outputTokens": 82,
            "cacheReadInputTokens": 0, "cacheCreationInputTokens": 0,
            "costUSD": total_cost_usd, "contextWindow": 200000,
            "maxOutputTokens": 32000, "canonicalModel": "claude-haiku-4-5"}}
    payload.update(extra)
    return json.dumps(payload, ensure_ascii=False)


def cli_endpoint(responses, spec=None, retry=None, **overrides):
    """Регистрирует endpoint протокола cli на поддельном запускателе."""
    spec = spec or llm.presets.claude_cli_proba()
    for name, value in overrides.items():
        setattr(spec, name, value)
    runner = FakeCli(responses, retry=retry)
    llm.register_endpoint(spec, transport=runner)
    return spec, runner


@pytest.fixture
def make_cli():
    """Фабрика: (список заготовок) → (spec, поддельный запускатель)."""
    return cli_endpoint


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
