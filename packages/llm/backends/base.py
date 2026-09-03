"""
backends.base — интерфейс бэкенда и общая часть всех протоколов.

Здесь проходит единственная граница, где вообще существует различие между
поставщиками. Всё, что выше (api, structured, loop, journal), про протокол не
знает и спрашивает возможности через Caps. Ветвление по имени поставщика вне
этого каталога — ошибка, которую придётся выкорчёвывать (записка, раздел 0).

Бэкенд обязан:
  * собрать тело запроса из раскладки (layout) и настроек ступени лестницы;
  * пройти поток и отдать наши Chunk'и, а не сырые события протокола;
  * привести причину остановки к Stop.* и счётчики к нашей конвенции usage;
  * сохранить сырой usage дословно в raw_usage.

Непотокового пути наружу нет: `complete()` собирает ответ из своего же потока
(А.4 — один внутренний путь, две наружные формы).
"""
from __future__ import annotations

import time

from ..errors import ErrorKind, LlmError, Stop
from ..model import Chunk, EndpointSpec, Result, Structured, Usage
from ..transport import Cancelled, Transport
from .. import layout, usage as usage_mod


class Request:
    """Что слой просит у бэкенда. Нарочно бедный объект: всё, что здесь есть,
    обязано существовать у любого протокола хотя бы в виде «нечего делать».

    `structured_step` — уже выбранная ступень лестницы (А.3), бэкенд её не
    выбирает, а исполняет: выбор — общее решение, оно в structured.py.
    Картинок здесь нет намеренно: решение владельца от 2026-08-29 —
    «картинки модели не отдаём вовсе, OCR справляется». Если endpoint объявит
    зрение, слой всё равно им не пользуется.
    """

    def __init__(self, parts, max_tokens: int = 1024, schema: dict | None = None,
                 structured_step: str = Structured.TEXT, tools=None,
                 tool_choice: str | None = None, history=None,
                 temperature: float | None = None, effort: str | None = None,
                 stop_sequences=None, frame_mark: str | None = None):
        self.parts = list(parts)
        self.max_tokens = max_tokens
        self.schema = schema
        self.structured_step = structured_step
        self.tools = list(tools or [])
        self.tool_choice = tool_choice
        # history — уже состоявшийся обмен (для петли инструментов): список
        # словарей в нашем нейтральном виде, бэкенд переводит их в свой формат.
        self.history = list(history or [])
        self.temperature = temperature
        self.effort = effort
        self.stop_sequences = list(stop_sequences or [])
        # frame_mark — метка рамки недоверенного текста. Она принадлежит
        # запросу, а не процессу: модульная переменная на два одновременных
        # прогона означала бы, что метку из первого прогона видит второй, а
        # начало второго обнуляет её посреди первого. `None` — «метки не дали»,
        # бэкенд выпустит свою и запишет сюда (см. Backend.request_mark).
        self.frame_mark = frame_mark


class Backend:
    """База всех бэкендов. Наследник переопределяет build_body и iter_stream."""

    protocol = ""
    stream_path = ""

    def __init__(self, spec: EndpointSpec, transport: Transport | None = None):
        self.spec = spec
        self._transport = transport

    # ── что обязан дать наследник ───────────────────────────────────────────
    def headers(self) -> dict:
        raise NotImplementedError

    def build_body(self, request: Request, stream: bool = True) -> dict:
        raise NotImplementedError

    def iter_stream(self, events, state: dict):
        """События протокола → наши Chunk'и. `state` копит usage и stop."""
        raise NotImplementedError

    def parse_response(self, payload: dict) -> Result:
        """Непотоковый ответ → Result. Нужен только пробе (Б.4, шаг 2)."""
        raise NotImplementedError

    def supported_step(self, wanted: str) -> str:
        """Самая сильная ступень лестницы, которую бэкенд умеет собрать."""
        raise NotImplementedError

    def open_events(self, body: dict, cancel=None):
        """Источник событий протокола: (имя события | None, разобранное тело).

        Отдельным методом, потому что «поток по проводу» — не единственный
        возможный провод. У обоих HTTP-протоколов это SSE через транспорт; у
        протокола, который зовёт модель командой (backends/cli.py), провод —
        труба подпроцесса, и никакого HTTP в нём нет вовсе.

        Всё, что вокруг, — порядок кусков (usage, потом stop), запасной подсчёт,
        превращение отмены в конец потока — живёт в `stream()` одним экземпляром
        на все протоколы. Переопределять `stream()` ради нового провода значило
        бы завести второй такой порядок, и первый же починенный в одном из них
        инвариант разошёлся бы с другим.
        """
        return self.transport().stream_sse(self.stream_path, body,
                                           endpoint_id=self.spec.id, cancel=cancel)

    # ── общее ───────────────────────────────────────────────────────────────
    def request_mark(self, request: Request) -> str:
        """Одна метка рамки на весь запрос — и текстам, и именам файлов.

        Метка выпускается разом по всему недоверенному входу запроса, поэтому
        `frame_untrusted` перевыпускать её уже не придётся. Брать метку
        покусочно (render_text без метки) нельзя: перевыпуск из-за одного файла
        не догонит уже отрендеренных соседей, и у части рамок останется метка,
        которую автор файла угадал. А знать метку — значит уметь закрыть рамку
        и продолжить запрос от нашего имени (А.3, Г.2).

        Имена файлов идут в тот же счёт: имя приходит от студента наравне с
        содержимым, и рамку оно ломает точно так же.

        Откуда метка берётся. Дал вызывающий (`request.frame_mark`) — берём
        его: одна метка на прогон это ещё и кэш префикса, который иначе
        обнуляется каждым запросом. Не дал — выпускаем свою и **запоминаем в
        запросе**: `build_body` и `_estimate_usage` зовут этот метод порознь, и
        две разные метки на один запрос означали бы, что оценку считали не по
        тому телу, которое отправили.

        Метка вызывающего, встретившаяся в недоверенном тексте, перевыпускается
        на весь запрос целиком, а не на один кусок: метку, которую автор файла
        уже знает, нельзя оставлять ни в одной рамке этого запроса.
        """
        untrusted: list = []
        for part in request.parts:
            if part.role != "files":
                continue
            untrusted.append(part.text)
            untrusted.append(part.name or "")
        mark = request.frame_mark
        if mark is None or any(mark in text for text in untrusted):
            mark = layout.new_mark(*untrusted)
            request.frame_mark = mark
        return mark

    def transport(self) -> Transport:
        if self._transport is None:
            self._transport = Transport(self.spec.base_url, headers=self.headers(),
                                        timeout_s=self.spec.timeout_s)
        return self._transport

    def stream(self, request: Request, cancel=None):
        """Главный путь: поток Chunk'ов. Всё остальное строится поверх.

        Отмена приходит сюда как Cancelled из транспорта и превращается в
        последний Chunk со stop=cancelled — вызывающий получает не исключение,
        а нормальный конец потока с уже накопленным usage. Деньги за
        отменённый вызов всё равно потрачены, и в журнал они попасть должны.

        Поэтому **любой** конец потока — обычный, отменённый, ошибочный — это
        кусок usage и следом кусок stop, в этом порядке. Пропустить usage у
        отмены значит записать отменённый вызов бесплатным: лимит нулевой
        записи не заметит, и отмена станет способом тратить бюджет мимо учёта.

        И причина остановки у ошибочного конца — `error`, а не `end_turn`.
        Вызывающий разбирает конец потока по последнему куску `stop` (так велит
        докстрока `api.stream_object`), и `end_turn` после куска ошибки значит,
        что оборванный на середине ответ он запишет как законченный ход.
        """
        body = self.build_body(request, stream=True)
        state = {"usage": Usage(), "raw_usage": {}, "stop": None, "text_chars": 0}
        try:
            events = self.open_events(body, cancel=cancel)
            for chunk in self.iter_stream(events, state):
                if chunk.kind == "error":
                    # Ошибку внутри 200-потока бэкенды отдают куском, а не
                    # исключением, — и причину остановки за них выставляем
                    # здесь, одним местом на все протоколы. Иначе ниже
                    # доклеится end_turn, и наружу уедет «ход закончился
                    # нормально» поверх уже случившейся беды.
                    state["stop"] = Stop.ERROR
                yield chunk
        except Cancelled:
            # Отмена не бесплатна: промпт модель уже прочитала и часть ответа
            # написала. Без usage-куска complete() соберёт Result с нулевым
            # расходом, журнал запишет отменённый вызов как бесплатный, и
            # отмена станет способом тратить бюджет мимо лимита. Ноль здесь
            # дороже неточности — поэтому счётчиков нет, идёт оценка (В.3),
            # то же решение, что и в api._stream_result.
            if not state["raw_usage"]:
                state["usage"] = self._estimate_usage(request, state)
            yield Chunk(kind="usage", usage=state["usage"], raw=state["raw_usage"])
            state["stop"] = Stop.CANCELLED
            # Порядок кусков тот же, что у обычного конца потока: usage, потом
            # stop. Иначе у вызывающего два разбора конца, и второй забудут.
            yield Chunk(kind="stop", stop=Stop.CANCELLED)
            return
        # Счётчики в потоке приходят не всегда: у OpenAI-совместимых без
        # stream_options.include_usage их нет вовсе, а флаг совместимые серверы
        # часто игнорируют. Тогда считаем сами и честно помечаем оценкой (В.3).
        if not state["raw_usage"]:
            state["usage"] = self._estimate_usage(request, state)
        yield Chunk(kind="usage", usage=state["usage"], raw=state["raw_usage"])
        if state["stop"] is None:
            state["stop"] = Stop.END_TURN
        yield Chunk(kind="stop", stop=state["stop"])

    def complete(self, request: Request, cancel=None) -> Result:
        """Готовый Result. Внутри — тот же поток (А.4): один путь, две формы."""
        started = time.monotonic()
        text_parts: list = []
        tool_calls: list = []
        usage = Usage()
        raw_usage: dict = {}
        stop = Stop.END_TURN
        for chunk in self.stream(request, cancel=cancel):
            if chunk.kind == "text":
                text_parts.append(chunk.text)
            elif chunk.kind == "tool_call" and chunk.tool_call is not None:
                tool_calls.append(chunk.tool_call)
            elif chunk.kind == "usage" and chunk.usage is not None:
                usage = chunk.usage
                raw_usage = chunk.raw or {}
            elif chunk.kind == "stop":
                stop = chunk.stop or stop
            elif chunk.kind == "error" and chunk.error is not None:
                raise chunk.error
        result = Result(
            ok=stop not in (Stop.ERROR,),
            text="".join(text_parts),
            usage=usage,
            stop=stop,
            endpoint=self.spec.id,
            model=self.spec.model,
            raw_usage=raw_usage,
            tool_calls=tool_calls,
            latency_ms=int((time.monotonic() - started) * 1000),
            # Идентификатор ответа поставщика: без него запись успешного вызова
            # нечем предъявить при разборе «списали деньги, а ответа нет».
            # Забираем, а не подсматриваем, — иначе он приписался бы и
            # следующему вызову (см. Transport.take_request_id).
            request_id=self.transport().take_request_id(),
        )
        result.units = usage_mod.units(usage, self.spec.prices)
        result.cost = usage_mod.cost(usage, self.spec.prices)
        return result

    def _estimate_usage(self, request: Request, state: dict) -> Usage:
        """Запасной подсчёт, когда usage не пришёл (В.3, самый частый случай).

        Вход считаем по собранному телу запроса, выход — по полученному тексту,
        обе оценки одной и той же эвристикой. Кэш при оценке всегда ноль:
        угадывать попадание в кэш нельзя, а придуманный cache_read занизил бы
        приведённые единицы и лимит перестал бы работать.
        """
        cpt = self.spec.chars_per_token
        # Метка та же, что уехала в теле запроса: рамки едут по проводу и
        # стоят токенов, а посчитать их другой меткой значит померить не тот
        # запрос, который отправили.
        input_chars = layout.total_chars(request.parts, self.request_mark(request))
        for message in request.history:
            input_chars += len(str(message.get("content", "")))
        return Usage(
            input=usage_mod.estimate_tokens("x" * input_chars, cpt),
            output=usage_mod.estimate_tokens("x" * state.get("text_chars", 0), cpt),
            measured=False,
        )

    def finish_usage(self, input_tokens: int, output_tokens: int,
                     cache_read: int = 0, cache_write: int = 0,
                     reasoning=None) -> Usage:
        """Сырые счётчики поставщика → наша конвенция.

        Единственное содержательное действие — вычесть кэш из входа там, где
        endpoint считает его внутри (declared.cache_inside_input). Без этого
        кэшированные токены посчитаются дважды.
        """
        clean_in, read, write = usage_mod.normalize_cache(
            input_tokens, cache_read, cache_write,
            self.spec.declared.cache_inside_input)
        return Usage(input=clean_in, output=output_tokens, cache_read=read,
                     cache_write=write, reasoning=reasoning, measured=True)


def make(spec: EndpointSpec, transport: Transport | None = None) -> Backend:
    """Единственная развилка по протоколу во всём пакете.

    Она именно про «как разговаривать по проводу», а не про «что endpoint
    умеет»: возможности спрашиваются через capabilities() и здесь не участвуют.
    """
    from .anthropic import AnthropicBackend
    from .cli import CliBackend
    from .openai_compat import OpenAICompatBackend

    if spec.protocol == "anthropic":
        return AnthropicBackend(spec, transport)
    if spec.protocol == "openai":
        return OpenAICompatBackend(spec, transport)
    if spec.protocol == "cli":
        # Провод здесь — не сеть, а подпроцесс. Развилка всё та же и про то же:
        # «как разговаривать», а не «что endpoint умеет».
        return CliBackend(spec, transport)
    raise LlmError(ErrorKind.UNSUPPORTED, f"неизвестный протокол {spec.protocol!r} "
                   f"(бывают: anthropic, openai, cli)", endpoint=spec.id)


__all__ = ["Backend", "Request", "make"]
