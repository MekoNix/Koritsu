"""
api — функции, которые видит остальной код (Б.1).

Их девять. Больше — значит, в слой протекла бизнес-логика: слой не знает ни про
hokoku, ни про манифест, ни про теги. Он знает про схемы JSON, инструменты и
токены. Про теги знает вызывающая служба.

Наружу слой отдаёт две формы — готовое значение и поток кусков, — но внутри
путь один: и то и другое идёт через стриминг (А.4). Причины: отмена в обоих
протоколах есть только закрытие потока; непотоковый запрос с большим max_tokens
упирается в таймаут соединения; два внутренних пути — два набора багов.
"""
from __future__ import annotations

import json
import time

from .errors import LlmError, Stop
from .model import Chunk, Estimate, Part, Result, Structured, Usage
from . import jsonschema, layout, registry, structured, usage as usage_mod
from .backends.base import Request

# Умолчания разные у «весь объект» и «одно значение» именно потому, что иначе
# они уедут в вызывающий код: у этих двух вызовов разные места в интерфейсе и
# разная ожидаемая длина ответа (Б.1).
DEFAULT_OBJECT_TOKENS = 8192
DEFAULT_VALUE_TOKENS = 2048


def _as_parts(prompt) -> list:
    """Промпт: строка или готовый список кусков раскладки Б.5."""
    if isinstance(prompt, str):
        return layout.simple(prompt)
    return list(prompt)


def _request_factory(parts, max_tokens: int, effort, temperature, frame_mark=None):
    """Фабрика запросов для лестницы: ступень и добавки к промпту приходят снаружи.

    Схема-подсказка (schema_hint) добавляется только на тех ступенях, где схему
    в запрос не положишь: на ступенях 1–2 повтор схемы словами вредит — модель
    копирует её как пример вместо того, чтобы заполнять поля.
    """
    def make(step, schema, extra_parts):
        pieces = list(parts)
        hint = structured.schema_hint(schema, step)
        if hint:
            pieces.append(Part(role="request", text=hint, stable=False))
        pieces.extend(extra_parts)
        return Request(parts=pieces, max_tokens=max_tokens, schema=schema,
                       structured_step=step, effort=effort, temperature=temperature,
                       frame_mark=frame_mark)
    return make


def _generate(endpoint_id: str, schema: dict, prompt, max_tokens: int,
              effort=None, temperature=None, cancel=None, limit=None,
              journal=None, meta=None, frame_mark=None) -> Result:
    """Общая машинерия generate_object / generate_value.

    Порядок здесь содержательный: сначала проверка лимита по оценке (отказ **до**
    вызова, а не посреди — В.5), потом лестница, потом запись в журнал. Запись
    делается и на неудаче тоже: неудачный вызов стоил денег, и в отчётности он
    обязан быть.

    Наружу функция **не бросает**: любая беда приходит как Result с ok=False и
    заполненным `error`. Один тип возврата на все исходы — иначе вызывающий
    обязан и проверять флаг, и ловить исключение, и рано или поздно забудет
    одно из двух.
    """
    spec = registry.spec_of(endpoint_id)
    backend = registry.backend_of(endpoint_id)
    caps = registry.capabilities(endpoint_id)
    parts = _as_parts(prompt)

    if limit is not None:
        # Отказ по лимиту — единственный случай, который в журнал НЕ пишется:
        # вызова не было, денег не потрачено, писать нечего.
        guess = estimate(endpoint_id, parts, schema, max_tokens=max_tokens,
                         frame_mark=frame_mark)
        try:
            limit.check(guess.units)
        except LlmError as exc:
            return Result(ok=False, stop=Stop.ERROR, endpoint=endpoint_id,
                          model=spec.model, error=exc)

    factory = _request_factory(parts, max_tokens, effort, temperature, frame_mark)
    try:
        result = structured.run_ladder(backend, factory, schema, caps=caps, cancel=cancel)
    except LlmError as exc:
        # Ошибка по проводу: расхода нет (или он неизвестен), но событие в
        # журнал попасть должно — иначе «почему ничего не сгенерировалось»
        # не расследуется.
        # Ступень берём фактическую, а не TEXT: `degraded` объясняет цифры
        # записи, и обход, приписанный не той ступени, объясняет не тот вызов.
        result = Result(ok=False, stop=Stop.ERROR, endpoint=endpoint_id,
                        model=spec.model, error=exc,
                        request_id=getattr(exc, "request_id", None),
                        structured_step=backend.supported_step(Structured.JSON_SCHEMA),
                        degraded=structured.degraded_for(
                            backend.supported_step(Structured.JSON_SCHEMA), caps))
    _record(journal, limit, result, spec, with_retries(meta, backend))
    return result


def with_retries(meta, backend) -> dict:
    """meta вызывающего плюс записки о повторах транспорта на ЭТОМ вызове.

    Забирает их тот, кто сделал вызов, и никто другой. Записка, оставленная в
    транспорте, дождётся следующего забирающего и припишется чужому вызову:
    повтор, случившийся при генерации значения, всплывал в записи хода петли,
    прошедшего с первой попытки. Тогда «почему этот ход шёл вчетверо дольше»
    получает ложный ответ, а настоящая задержка так и остаётся необъяснимой.

    Забираем и когда журнала нет: записка принадлежит этому вызову, и оставить
    её значит подложить её следующему.
    """
    take = getattr(backend.transport(), "take_retries", None)
    notes = take() if callable(take) else []
    if not notes:
        return meta
    return {**(meta or {}), "retries": notes}


def _record(journal, limit, result: Result, spec, meta) -> None:
    """Запись вызова в журнал вызывающего и в журнал лимита — в оба.

    «Или туда, или туда» тут не годится: подавший и журнал, и лимит получал
    расход только в свой журнал, `limit.spent()` не рос вовсе, и лимит не
    срабатывал никогда — то есть проверка перед следующим вызовом сравнивала
    оценку с одним и тем же вчерашним остатком. Ошибка молчаливая: отчётность
    при этом выглядит правильной, потому что журнал вызывающего полон.

    Сверка на тождество — чтобы один и тот же журнал, поданный обоими путями,
    не посчитал вызов дважды и не отказал вдвое раньше срока.
    """
    if journal is not None:
        journal.add(result, spec, meta)
    if limit is not None and limit.journal is not journal:
        limit.journal.add(result, spec, meta)


def generate_object(endpoint_id: str, schema: dict, prompt, max_tokens: int = DEFAULT_OBJECT_TOKENS,
                    effort=None, temperature=None, cancel=None, limit=None,
                    journal=None, meta=None, frame_mark=None) -> Result:
    """Объект по схеме: значения сразу многих тегов. Ступень лестницы — сама.

    `frame_mark` — метка рамки недоверенного текста, общая на прогон (см.
    `layout.new_mark` и `Backend.request_mark`). Не дали — слой выпустит свою на
    этот запрос: защита цела, но у соседних вызовов прогона куски `files`
    разойдутся метками и кэш префикса обнулится на каждом вызове.
    """
    return _generate(endpoint_id, schema, prompt, max_tokens, effort, temperature,
                     cancel, limit, journal, meta, frame_mark)


def generate_value(endpoint_id: str, schema: dict, prompt, max_tokens: int = DEFAULT_VALUE_TOKENS,
                   effort=None, temperature=None, cancel=None, limit=None,
                   journal=None, meta=None, frame_mark=None) -> Result:
    """Одно значение по схеме одного значения. Отличается умолчаниями, не кодом."""
    return _generate(endpoint_id, schema, prompt, max_tokens, effort, temperature,
                     cancel, limit, journal, meta, frame_mark)


def stream_object(endpoint_id: str, schema: dict | None, prompt,
                  max_tokens: int = DEFAULT_OBJECT_TOKENS, effort=None,
                  temperature=None, cancel=None, limit=None, journal=None,
                  meta=None, frame_mark=None):
    """То же потоком — для прогресса и печати значения по мере генерации.

    Лестницы с повторами здесь нет намеренно: повтор посреди потока означал бы,
    что напечатанное надо стереть. Поток отдаёт куски как есть, а разбор и
    проверку схемы вызывающий делает по накопленному тексту (см. stream_parse —
    он отдаёт закрытые объекты по мере готовности, чтобы обрыв стоил одного
    значения) или зовёт generate_object, если поток нужен только ради прогресса.

    Лимит и журнал здесь те же, что у обычного вызова, и по той же причине:
    «весь отчёт одним вызовом» — самый дорогой вызов в системе, и он обязан быть
    потоковым. Поток мимо учёта означал бы, что пользователь уходит за лимит
    незаметно, а объяснить потом расход нечем.

    Тонкость, которой у generate_* нет: расход потока известен только в конце, а
    при обрыве — не известен вовсе. Решение принято в пользу учёта:

      * лимит проверяется по оценке **до** первого куска (В.5), как и у
        generate_*, — отказ посреди потока это уже потраченные деньги;
      * запись в журнал делается **всегда**, когда вызов состоялся, — в том
        числе если вызывающий бросил поток на середине или соединение
        оборвалось;
      * если счётчики не пришли, в запись идёт оценка (вход по длине промпта,
        выход по числу уже полученных символов) с `measured=False`. Ноль был бы
        дырой в учёте: вызов был, деньги потрачены, а лимит их не увидел бы.
        Долю таких записей видно через `Journal.estimated_share`.

    Отказ по лимиту приходит не исключением, а концом потока: кусок kind="error"
    с LlmError и следом kind="stop" со stop=error — форма та же, что у ошибки по
    проводу, чтобы у вызывающего был один разбор конца потока. В журнал такой
    отказ не пишется: вызова не было, писать нечего.

    **Про null «этого поля я не задаю».** На строгих ступенях схема уезжает к
    поставщику расширенной (`jsonschema.strictify`): строгий режим требует все
    ключи в `required`, и без разрешённого null модель обязана была бы выдумать
    `code.lang`, `image.align` и прочее — её догадка молча перекрыла бы умолчание
    шаблона, и отчёт вышел бы с чужим оформлением без единой ошибки. Обратно
    null снимает `jsonschema.drop_unset`, и у потока для него два разных места:

      * **вызов инструмента** (ступень 2) приходит уже разобранным объектом —
        его слой гасит сам, в `_stream_chunks`. Другого места нет: дальше по
        течению разбирать уже нечего;
      * **текст** (ступени 1, 3, 4) слой не трогает вовсе. Погасить null в буквах
        значит собрать весь объект и переписать его — а тогда «печать значения по
        мере генерации», ради которой поток и существует, перестаёт работать.
        Поэтому обязанность честно передана вызывающему: разобрав объект из
        текста (stream_parse), прогони его через
        `jsonschema.drop_unset(value, schema)` с **исходной** схемой — той же,
        что подана сюда, а не расширенной. Не сделать этого — получить null'ы
        «не задаю» как настоящие значения; сделать по расширенной схеме — не
        погасить ничего.

    Кому вся эта тонкость не нужна, тому нужен `generate_object`: там гашение
    делает `run_ladder` и вызывающий об этом не думает.
    """
    spec = registry.spec_of(endpoint_id)
    backend = registry.backend_of(endpoint_id)
    parts = _as_parts(prompt)
    step = backend.supported_step(Structured.JSON_SCHEMA) if schema else Structured.TEXT
    prepared = None
    if schema:
        jsonschema.check_schema(schema)
        prepared = jsonschema.strictify(schema) if step in (
            Structured.JSON_SCHEMA, Structured.TOOL_STRICT) else schema

    if limit is not None:
        # Оценка считается по промпту без схемы-подсказки, а схема передаётся
        # отдельно: подсказка ниже добавится в parts, и посчитать её дважды
        # значило бы отказать раньше, чем нужно.
        guess = estimate(endpoint_id, parts, prepared, max_tokens=max_tokens,
                         frame_mark=frame_mark)
        try:
            limit.check(guess.units)
        except LlmError as exc:
            return _refused(exc)

    if prepared is not None:
        hint = structured.schema_hint(prepared, step)
        if hint:
            parts = parts + [Part(role="request", text=hint)]
    request = Request(parts=parts, max_tokens=max_tokens, schema=prepared,
                      structured_step=step, effort=effort, temperature=temperature,
                      frame_mark=frame_mark)
    # `degraded` объясняет цифры записи (В.4): без него «этот прогон стоил
    # вчетверо» необъяснимо. У потока без схемы обходить нечего — там пусто.
    degraded = structured.degraded_for(
        step, registry.capabilities(endpoint_id)) if prepared is not None else []
    return _stream_chunks(backend, spec, request, cancel, journal, limit, meta,
                          degraded, schema)


def _refused(exc: LlmError):
    """Отказ до вызова в форме потока — тоже генератор, а не готовый список:
    вызывающий закрывает поток одинаково, чем бы тот ни кончился."""
    yield Chunk(kind="error", error=exc)
    yield Chunk(kind="stop", stop=Stop.ERROR)


def _stream_chunks(backend, spec, request, cancel, journal, limit, meta, degraded,
                   schema):
    """Проход потока с записью расхода в конце — включая конец не по плану.

    Запись стоит в finally, и это единственный способ не потерять расход, когда
    вызывающий бросил поток на середине: брошенный генератор получает
    GeneratorExit ровно в точке yield, и без finally запись не сделается
    никогда — а вызов при этом состоялся и деньги потрачены.

    `schema` — **исходная** схема вызывающего, а не `request.schema`: в запрос
    уехала расширенная (strictify), и гасить null'ы по ней нельзя — по ней
    гасить нечего, она сама их и разрешила.
    """
    started = time.monotonic()
    usage = Usage()
    raw_usage: dict = {}
    seen_usage = False
    stop = None
    error = None
    chars = 0
    try:
        for chunk in backend.stream(request, cancel=cancel):
            if chunk.kind == "text":
                # Текст целиком не копим: журналу он не нужен, а отчёт на
                # десятки тегов держать в памяти вторым экземпляром незачем.
                chars += len(chunk.text)
            elif chunk.kind == "usage" and chunk.usage is not None:
                usage, raw_usage, seen_usage = chunk.usage, chunk.raw or {}, True
            elif chunk.kind == "stop":
                # Уже случившуюся ошибку куском stop не перебиваем: у части
                # серверов после куска ошибки приезжает ещё и обычная причина
                # остановки, и «последнее слово» отдало бы наружу end_turn
                # поверх беды.
                if stop != Stop.ERROR:
                    stop = chunk.stop or stop
            elif chunk.kind == "error" and chunk.error is not None:
                error, stop = chunk.error, Stop.ERROR
            elif (chunk.kind == "tool_call" and chunk.tool_call is not None
                    and schema is not None):
                # Ступень 2 отдаёт готовое значение вызовом инструмента — и это
                # единственное место потока, где слой держит в руках разобранный
                # объект, а не буквы. Значит и гасить null'ы «не задаю» надо
                # ровно здесь: дальше их снимать будет некому. `raw_arguments`
                # остаётся дословным — пересчитать задним числом должно быть чем.
                chunk.tool_call.arguments = jsonschema.drop_unset(
                    chunk.tool_call.arguments, schema)
            yield chunk
    except GeneratorExit:
        # Поток бросили, не досмотрев. Это не ошибка вызова, а отмена: исход
        # такой же, как у закрытого соединения.
        stop = stop or Stop.CANCELLED
        raise
    except LlmError as exc:
        error, stop = exc, Stop.ERROR
        raise
    finally:
        # Забрать записки и идентификатор надо в любом случае, даже когда писать
        # некуда: они принадлежат этому вызову, и оставленные в транспорте
        # припишутся следующему.
        meta = with_retries(meta, backend)
        request_id = (backend.transport().take_request_id()
                      or getattr(error, "request_id", None))
        if journal is not None or limit is not None:
            _record(journal, limit,
                    _stream_result(spec, request, usage, raw_usage, seen_usage,
                                   stop, error, chars, started, degraded,
                                   request_id),
                    spec, meta)


def _stream_result(spec, request, usage, raw_usage, seen_usage, stop, error,
                   chars, started, degraded, request_id=None) -> Result:
    """Итог потока для журнала. Без счётчиков — оценка, а не ноль.

    Ноль здесь дороже неточности: запись с нулём выглядит как бесплатный вызов,
    лимит её не заметит, и обрывы станут способом расходовать бюджет мимо учёта.
    Оценка считается той же эвристикой, что и у бэкенда (В.3), и помечается
    measured=False — цифра, про которую забыли, что она догадка, хуже догадки.
    """
    if not seen_usage:
        cpt = spec.chars_per_token
        usage = Usage(
            input=usage_mod.estimate_tokens(
                "x" * layout.total_chars(request.parts, request.frame_mark), cpt),
            output=usage_mod.estimate_tokens("x" * chars, cpt),
            measured=False)
    result = Result(ok=(error is None and stop != Stop.ERROR),
                    usage=usage, stop=stop or Stop.END_TURN, endpoint=spec.id,
                    model=spec.model, raw_usage=raw_usage, error=error,
                    request_id=request_id,
                    degraded=list(degraded),
                    structured_step=request.structured_step,
                    latency_ms=int((time.monotonic() - started) * 1000))
    result.units = usage_mod.units(usage, spec.prices)
    result.cost = usage_mod.cost(usage, spec.prices)
    return result


def estimate(endpoint_id: str, prompt, schema: dict | None = None,
             max_tokens: int = DEFAULT_OBJECT_TOKENS, frame_mark=None) -> Estimate:
    """Оценка до отправки (В.3). `method` различает счёт и догадку.

    Точный подсчёт умеет только один протокол; там, где его нет, работает
    эвристика по символам. Интерфейс пишет «≈» в обоих случаях, но на границе
    лимита разница есть, и она не должна теряться.

    Выход оценить нечем: медиана по истории шаблона живёт в вызывающей службе,
    а слой берёт потолок max_tokens. Это заведомо пессимистично — и правильно:
    на границе лимита лучше отказать зря, чем начать и оборваться.

    **Считается ровно тот запрос, который уедет.** Схема — самая тяжёлая часть
    вызова «весь отчёт одним вызовом»; собери счётчику тело ступени TEXT, где её
    нет, и замер занизится на порядок, а `method="counted"` объявит его точным —
    утверждением наибольшей силы, по которому `Limit.check` сравнивает остаток.
    Поэтому ступень выбирается та же, что в боевом вызове, схема готовится тем
    же `strictify`, а на слабых ступенях вместо схемы едет та же подсказка
    словами (`schema_hint`) — и в счёт идёт она.
    """
    spec = registry.spec_of(endpoint_id)
    backend = registry.backend_of(endpoint_id)
    parts = _as_parts(prompt)
    step = backend.supported_step(Structured.JSON_SCHEMA) if schema else Structured.TEXT
    strict = step in (Structured.JSON_SCHEMA, Structured.TOOL_STRICT)
    # strictify идемпотентен, поэтому подать сюда уже расширенную схему
    # (так делает stream_object) безопасно.
    prepared = jsonschema.strictify(schema) if (schema and strict) else schema
    hint = structured.schema_hint(prepared, step) if prepared else ""
    counted_parts = list(parts)
    if hint:
        counted_parts.append(Part(role="request", text=hint, stable=False))

    chars = layout.total_chars(counted_parts, frame_mark)
    if prepared and strict:
        # На строгих ступенях подсказки нет, а схема уезжает в теле — и стоит
        # токенов ровно так же. Не посчитать её значит занизить самый дорогой
        # вызов в системе.
        chars += len(json.dumps(prepared, ensure_ascii=False))

    tokens = usage_mod.estimate_tokens("x" * chars, spec.chars_per_token)
    method = "estimated"
    counter = getattr(backend, "count_tokens", None)
    if callable(counter):
        try:
            request = Request(parts=counted_parts, max_tokens=max_tokens,
                              schema=prepared, structured_step=step,
                              frame_mark=frame_mark)
            tokens = counter(request)
            method = "counted"
        except LlmError:
            # Счётчик — удобство, а не условие работы: не ответил, значит
            # оцениваем эвристикой и честно помечаем.
            pass

    guess = Usage(input=tokens, output=max_tokens, measured=(method == "counted"))
    return Estimate(tokens=tokens, method=method, output_tokens=max_tokens,
                    units=usage_mod.units(guess, spec.prices))


def usage_of(result: Result) -> dict:
    """Нормализованные счётчики результата плюс приведённые единицы (В.2).

    Сырые счётчики отдаются рядом, а не вместо: `raw_usage` — единственный
    способ пересчитать задним числом, когда выяснится, что нормализация была
    неверной.
    """
    return {**result.usage.as_dict(), "units": result.units, "cost": result.cost,
            "raw": dict(result.raw_usage or {})}


__all__ = ["generate_object", "generate_value", "stream_object", "estimate",
           "usage_of", "DEFAULT_OBJECT_TOKENS", "DEFAULT_VALUE_TOKENS"]
