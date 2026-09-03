"""
backends.anthropic — протокол Messages API.

Второй бэкенд существует не потому, что Anthropic нужен прямо сейчас (первым
доводится DeepSeek), а потому что именно он проверяет, честно ли слой
провайдеро-независим: у него другие имена счётчиков, другой вид потока, другой
способ просить схему и **есть** управляемый кэш, которого у первого нет. Всё,
что выше бэкендов, от этих различий не должно поменяться ни строчкой.

`protocol: anthropic` не означает api.anthropic.com: Anthropic-совместимый
прокси подключается тем же кодом с другим base_url, и возможности у него свои —
поэтому и здесь ничего не берётся из адреса, всё из Caps.

Что тут есть сверх первого бэкенда:
  * `cache_control` на границах стабильных кусков (раскладка Б.5, до 4 штук);
  * `stop_reason: "refusal"` — отдельный исход, приводится к Stop.REFUSED;
  * четыре счётчика вместо двух, кэш уже снаружи входа (вычитать не надо);
  * подсчёт токенов до отправки — единственный точный во всём слое.
"""
from __future__ import annotations

import json

from ..errors import ErrorKind, LlmError, Stop
from ..model import Chunk, OperatorChannel, PrefixCache, Structured, ToolCall, Usage
from .. import jsonschema, layout
from .base import Backend, Request

API_VERSION = "2023-06-01"
MAX_BREAKPOINTS = 4          # ограничение протокола


class AnthropicBackend(Backend):
    protocol = "anthropic"
    stream_path = "/v1/messages"
    complete_path = "/v1/messages"
    count_path = "/v1/messages/count_tokens"
    # Те же имена, что читает `_usage_from`: чтение, запись и разбивка записи
    # по TTL. По их присутствию шаг пробы про кэш отличает промах от «endpoint
    # о кэше не отчитывается» — молчание проб не опровергает заявку.
    CACHE_USAGE_KEYS = ("cache_read_input_tokens", "cache_creation_input_tokens",
                        "cache_creation")

    def headers(self) -> dict:
        head = {"x-api-key": self.spec.resolve_key(),
                "anthropic-version": API_VERSION,
                "Content-Type": "application/json"}
        head.update(self.spec.extra_headers)
        return head

    def supported_step(self, wanted: str) -> str:
        declared = self.spec.probe.structured_output or self.spec.declared.structured_output
        floor = Structured.rank(declared if declared != Structured.NONE else Structured.TEXT)
        return Structured.LADDER[max(Structured.rank(wanted), floor)]

    # ── сборка запроса ──────────────────────────────────────────────────────
    def build_body(self, request: Request, stream: bool = True) -> dict:
        system_blocks, messages = self._layout(request)
        body: dict = {
            "model": self.spec.model,
            "max_tokens": request.max_tokens,
            "messages": messages,
        }
        if stream:
            body["stream"] = True
        if system_blocks:
            body["system"] = system_blocks
        if request.temperature is not None:
            body["temperature"] = request.temperature
        if request.stop_sequences:
            body["stop_sequences"] = request.stop_sequences
        if request.effort and self.spec.declared.effort:
            body["output_config"] = {"effort": request.effort}

        step = request.structured_step
        if step == Structured.JSON_SCHEMA and request.schema:
            config = body.setdefault("output_config", {})
            config["format"] = {"type": "json_schema", "schema": request.schema}

        tools = list(request.tools)
        if step == Structured.TOOL_STRICT and request.schema:
            tools = tools + [_set_values_tool(request.schema)]
        if tools:
            body["tools"] = [_tool_json(t) for t in tools]
            if step == Structured.TOOL_STRICT:
                body["tool_choice"] = {"type": "tool", "name": "set_values"}
            elif request.tool_choice:
                body["tool_choice"] = request.tool_choice
        return body

    def _layout(self, request: Request) -> tuple:
        """Раскладка Б.5 → system-блоки и messages, с брейкпойнтами кэша.

        Брейкпойнты ставит бэкенд, вызывающий код их не видит. Правило —
        «волатильное после последнего брейкпойнта»: иначе первое же изменение
        соседних значений обнулит кэш файлов проекта, и обещанная дешёвая
        перегенерация тега не состоится.

        Если кэша нет (прокси без cache_control), метка просто не ставится —
        порядок кусков остаётся тем же, и это не напрасно: у автокэша совпадение
        тоже считается по префиксу.
        """
        cacheable = self.spec.declared.prefix_cache == PrefixCache.BREAKPOINTS
        system_parts, user_parts = layout.split(request.parts)
        marks = set(layout.breakpoints(request.parts, MAX_BREAKPOINTS)) if cacheable else set()
        ordered = layout.order_parts(request.parts)
        mark_ids = {id(ordered[i]) for i in marks}
        # Метка рамки выпускается один раз на весь запрос: блоки здесь
        # собираются по одному, и метка, взятая покусочно, разъедется между
        # ними при первом же перевыпуске (см. Backend.request_mark).
        frame_mark = self.request_mark(request)

        system_blocks: list = []
        for part in system_parts:
            block = {"type": "text", "text": layout.render_text(part, frame_mark)}
            if id(part) in mark_ids:
                block["cache_control"] = {"type": "ephemeral"}
            system_blocks.append(block)

        content: list = []
        for part in user_parts:
            block = {"type": "text", "text": layout.render_text(part, frame_mark)}
            if id(part) in mark_ids:
                block["cache_control"] = {"type": "ephemeral"}
            content.append(block)

        messages: list = []
        if content:
            messages.append({"role": "user", "content": content})
        messages.extend(_history_json(request.history))
        if not messages:
            messages.append({"role": "user", "content": [{"type": "text", "text": "."}]})
        return system_blocks, messages

    # ── разбор потока ───────────────────────────────────────────────────────
    def iter_stream(self, events, state: dict):
        """События Messages API → Chunk'и.

        Поток здесь именованный (`event: content_block_delta`), в отличие от
        безымянного у первого бэкенда, и usage приходит двумя порциями: вход в
        `message_start`, выход в `message_delta`. Поэтому счётчики копятся, а не
        перезаписываются одним событием.

        Копятся они **сразу в `state`**, а не в локальной переменной с переносом
        после цикла: из цикла есть два выхода мимо конца — отмена (Cancelled из
        транспорта) и ошибка внутри потока, — и на обоих локальная переменная
        пропала бы вместе с уже измеренным входом. Дальше `Backend.stream`
        увидел бы пустой raw_usage и подменил настоящие счётчики оценкой по
        длине промпта: на отмене это занижение в десятки раз, то есть ровно та
        дыра в учёте, которую докстрока `Backend.stream` объявляет закрытой.
        """
        blocks: dict = {}
        raw_usage: dict = state.setdefault("raw_usage", {})
        for name, payload in events:
            kind = name or payload.get("type")
            if kind == "message_start":
                message = payload.get("message") or {}
                raw_usage.update(message.get("usage") or {})
                self._store_usage(state, raw_usage)
            elif kind == "content_block_start":
                block = payload.get("content_block") or {}
                if block.get("type") == "tool_use":
                    blocks[payload.get("index", 0)] = {
                        "id": block.get("id") or "", "name": block.get("name") or "",
                        "args": []}
            elif kind == "content_block_delta":
                delta = payload.get("delta") or {}
                if delta.get("type") == "text_delta" and delta.get("text"):
                    state["text_chars"] = state.get("text_chars", 0) + len(delta["text"])
                    yield Chunk(kind="text", text=delta["text"])
                elif delta.get("type") == "input_json_delta":
                    slot = blocks.get(payload.get("index", 0))
                    if slot is not None:
                        slot["args"].append(delta.get("partial_json") or "")
            elif kind == "message_delta":
                raw_usage.update(payload.get("usage") or {})
                self._store_usage(state, raw_usage)
                stop_reason = (payload.get("delta") or {}).get("stop_reason")
                if stop_reason:
                    state["stop"] = _stop_from(stop_reason)
            elif kind == "error":
                # Куском, а не исключением: у второго бэкенда ошибка в потоке
                # едет ровно так же, и два разных конца потока у одного слоя —
                # приглашение забыть второй разбор. Причину остановки выставит
                # Backend.stream, счётчики уже в state и не потеряются.
                error = payload.get("error") or {}
                yield Chunk(kind="error", raw=error, error=LlmError(
                    ErrorKind.TRANSPORT, error.get("message") or "ошибка в потоке",
                    endpoint=self.spec.id, raw=error))
                return
        for index in sorted(blocks):
            slot = blocks[index]
            yield Chunk(kind="tool_call",
                        tool_call=_make_call(slot["id"] or f"call_{index}",
                                             slot["name"], "".join(slot["args"])))

    def _store_usage(self, state: dict, raw_usage: dict) -> None:
        """Счётчики в state сразу, как только приехали.

        Отдельным методом, чтобы забыть один из двух вызовов было труднее: вход
        и выход приезжают разными событиями, и «перенесу после цикла» — это
        именно та строчка, которая теряет расход на отмене.
        """
        if raw_usage:
            state["raw_usage"] = raw_usage
            state["usage"] = self._usage_from(raw_usage)

    def parse_response(self, payload: dict) -> tuple:
        text_parts: list = []
        calls: list = []
        for block in payload.get("content") or []:
            if block.get("type") == "text":
                text_parts.append(block.get("text") or "")
            elif block.get("type") == "tool_use":
                calls.append(ToolCall(id=block.get("id") or "",
                                      name=block.get("name") or "",
                                      arguments=block.get("input") or {},
                                      raw_arguments=json.dumps(block.get("input") or {},
                                                               ensure_ascii=False)))
        raw_usage = payload.get("usage") or {}
        usage = self._usage_from(raw_usage) if raw_usage else Usage(measured=False)
        return ("".join(text_parts), calls, usage, raw_usage,
                _stop_from(payload.get("stop_reason")))

    def _usage_from(self, raw: dict) -> Usage:
        """Четыре счётчика. Кэш здесь уже снаружи входа — вычитать не надо.

        Проверка всё равно идёт через finish_usage: если это Anthropic-совместимый
        прокси, который считает иначе, поле declared.cache_inside_input спасает
        и здесь. Одно место нормализации на все протоколы.
        """
        cache_write = raw.get("cache_creation_input_tokens") or 0
        if not cache_write:
            # Разбивка записи по TTL, когда она приходит вместо общего числа.
            detail = raw.get("cache_creation") or {}
            cache_write = sum(v for v in detail.values() if isinstance(v, int))
        return self.finish_usage(
            raw.get("input_tokens") or 0,
            raw.get("output_tokens") or 0,
            raw.get("cache_read_input_tokens") or 0,
            cache_write,
        )

    def count_tokens(self, request: Request) -> int:
        """Точный подсчёт до отправки — единственный во всём слое (В.3).

        Именно поэтому Estimate различает `counted` и `estimated`: на границе
        лимита отказ по точному счёту и отказ по догадке — утверждения разной
        силы, и смешивать их в отчётности нельзя.
        """
        body = self.build_body(request, stream=False)
        body.pop("max_tokens", None)
        body.pop("stream", None)
        payload, _ = self.transport().post_json(self.count_path, body,
                                                endpoint_id=self.spec.id)
        return int(payload.get("input_tokens") or 0)


# ── вспомогательное ─────────────────────────────────────────────────────────
_STOP = {
    "end_turn": Stop.END_TURN,
    "stop_sequence": Stop.END_TURN,
    "max_tokens": Stop.MAX_TOKENS,
    "tool_use": Stop.TOOL_USE,
    "pause_turn": Stop.TOOL_USE,
    "refusal": Stop.REFUSED,        # отдельный исход, а не ошибка (Б.2)
    "model_context_window_exceeded": Stop.MAX_TOKENS,
}


def _stop_from(reason):
    if not reason:
        return None
    return _STOP.get(reason, Stop.END_TURN)


def _tool_json(tool) -> dict:
    """Объявление инструмента → JSON протокола.

    `strict` без строгой схемы — четырёхсотка на ровном месте: строгий режим
    требует, чтобы каждый ключ `properties` был перечислен в `required`, и
    объявление с одним необязательным параметром отвергается целиком. Поэтому
    строгость просим и схему готовим вместе, одним действием: попросить и не
    приготовить нельзя.

    `strictify` идемпотентен — внутренний `set_values` приезжает сюда уже
    расширенным из лестницы, и второй проход ничего не меняет. Обратную
    половину (гашение null «не задаю» перед вызовом инструмента) делает
    `loop._clean_arguments`; пара обязана меняться только вместе.
    """
    schema = tool.schema or {"type": "object", "properties": {}}
    if tool.strict:
        schema = jsonschema.strictify(schema)
    out: dict = {"name": tool.name, "description": tool.description,
                 "input_schema": schema}
    if tool.strict:
        out["strict"] = True
    return out


def _set_values_tool(schema: dict):
    from ..model import Tool
    return Tool(name="set_values",
                description="Верни значения строго по схеме. Другого способа ответить нет.",
                schema=schema, strict=True)


def _make_call(call_id: str, name: str, raw_args: str) -> ToolCall:
    try:
        args = json.loads(raw_args) if raw_args.strip() else {}
        if not isinstance(args, dict):
            args = {}
    except (ValueError, json.JSONDecodeError):
        args = {}
    return ToolCall(id=call_id, name=name, arguments=args, raw_arguments=raw_args)


def _history_json(history) -> list:
    """Наш нейтральный обмен → messages Messages API.

    Результат инструмента здесь — блок `tool_result` внутри пользовательского
    сообщения, а не отдельная роль. Разница с первым бэкендом чисто формальная,
    и она заканчивается тут: петля инструментов (loop.py) про неё не знает.
    """
    out: list = []
    for item in history:
        role = item.get("role")
        if role == "assistant_tool_calls":
            content: list = []
            if item.get("text"):
                content.append({"type": "text", "text": item["text"]})
            for call in item.get("calls", []):
                content.append({"type": "tool_use", "id": call.id, "name": call.name,
                                "input": call.arguments})
            out.append({"role": "assistant", "content": content})
        elif role == "tool_result":
            block = {"type": "tool_result", "tool_use_id": item.get("call_id"),
                     "content": item.get("content") or ""}
            if item.get("is_error"):
                block["is_error"] = True
            # Несколько результатов подряд склеиваются в одно сообщение
            # пользователя: протокол требует, чтобы tool_result шли вместе.
            if out and out[-1]["role"] == "user" and isinstance(out[-1]["content"], list) \
                    and out[-1]["content"] and out[-1]["content"][0].get("type") == "tool_result":
                out[-1]["content"].append(block)
            else:
                out.append({"role": "user", "content": [block]})
        else:
            out.append({"role": role or "user",
                        "content": [{"type": "text", "text": item.get("content") or ""}]})
    return out


__all__ = ["AnthropicBackend"]
