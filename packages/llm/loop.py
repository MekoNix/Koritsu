"""
loop — своя петля инструментов, одна на всех поставщиков (Г.3).

Соблазн, которому нельзя поддаваться: «у Anthropic есть штатный tool_runner,
там зовём его, а на остальных пишем свою». Два цикла — два набора багов, две
модели поведения при ошибке инструмента, два места, где чинить потолок ходов.
Поэтому петля одна и штатным runner'ом мы не пользуемся нигде.

Что мы при этом теряем на Anthropic-endpoint'е: удобство и `task_budget` (модель
видит обратный отсчёт и заканчивает аккуратно, а наш потолок обрывает). Что
приобретаем: единственное место, где живут потолок ходов, кооперативная отмена,
лимит пользователя и журнал вызовов — у нас это всё равно должно было быть.
Повтор временных ошибок петля не делает сама: он лежит ниже, в транспорте, и
достаётся ей вместе с каждым вызовом (см. transport.Retry).

Про безопасность (Г.2, Ж.3): на endpoint'е без операторского канала указание
«ты оператор» не весомее текста из файла студента. Поэтому петля не полагается
на послушание модели, а ограничивает её механически: список инструментов
фиксирован, недоступность приходит ответом `is_error`, а не исчезновением
инструмента, и есть потолок ходов и токенов.
"""
from __future__ import annotations

import time

from .errors import ErrorKind, LlmError, Stop
from .model import Part, Result, ToolResult, Usage
from . import api, jsonschema, layout, registry, usage as usage_mod
from .backends.base import Request

MAX_STEPS_DEFAULT = 12


class Limits:
    """Потолки прогона. Оба обязательны: ходы ловят зацикливание, единицы — цену.

    Потолок в приведённых единицах, а не в токенах: тысяча токенов выхода и
    тысяча токенов чтения из кэша стоят в пятьдесят раз по-разному, и потолок
    «в токенах» на разных прогонах означал бы разные деньги.
    """

    def __init__(self, max_steps: int = MAX_STEPS_DEFAULT, max_units: float | None = None,
                 max_tokens_per_call: int = 4096):
        self.max_steps = max_steps
        self.max_units = max_units
        self.max_tokens_per_call = max_tokens_per_call


def run_tools(endpoint_id: str, tools, prompt, on_call, limits: Limits | None = None,
              cancel=None, journal=None, meta=None, effort=None, limit=None,
              frame_mark=None) -> Result:
    """Петля: модель зовёт инструменты, `on_call(ToolCall) -> str | ToolResult`.

    Возвращает Result с суммарным расходом по всем ходам. Один вызов модели —
    одна запись в журнале (В.4): прогон агента это десятки вызовов, и без
    разбивки нельзя понять, что съело бюджет.

    Наружу функция **не бросает** транспортную беду, как и api._generate: обрыв
    на пятом ходу приходит как Result с ok=False, заполненным `error` и уже
    израсходованным. Исключением он уйти не может — расход по четырём успешным
    ходам настоящий, и потерять его итог значит потерять деньги в отчётности.

    `limits` и `limit` — разные вещи, и обе нужны. `Limits` — наши потолки
    одного прогона (ходы, единицы, токены на вызов), защита от зацикливания.
    `limit` — денежный лимит пользователя (В.5), тот же объект, что принимает
    api.generate_object. Он проверяется **перед каждым ходом**: ход — это
    отдельный вызов, и «отказ до вызова, а не посреди» относится именно к нему.
    Правило В.5 «начавшийся прогон дорабатывает» запрещает рвать вызов на
    середине, а не выдавать по лимиту ещё десять вызовов подряд: прогон агента
    это десятки обращений, и без проверки на каждом уровень «агент с
    инструментами» обходил бы лимит целиком.

    Исключение из `on_call` не роняет прогон: оно превращается в ответ
    инструмента с `is_error=True`, и модель получает шанс поправиться. Ронять
    можно только то, что модель починить не может — например, отмену.
    """
    limits = limits or Limits()
    spec = registry.spec_of(endpoint_id)
    backend = registry.backend_of(endpoint_id)
    caps = registry.capabilities(endpoint_id)
    if not caps.supports_tools():
        raise LlmError(ErrorKind.UNSUPPORTED,
                       f"endpoint {endpoint_id} не объявляет инструменты; "
                       f"петля инструментов на нём недоступна", endpoint=endpoint_id)

    parts = layout.simple(prompt) if isinstance(prompt, str) else list(prompt)
    history: list = []
    total = Usage()
    started = time.monotonic()
    steps = 0
    stop = Stop.END_TURN
    last_text = ""
    error = None
    degraded: list = []
    if caps.operator_channel != "messages_system":
        # Объяснение цифр и рисков в журнале: без операторского канала указания
        # оператора не весомее текста из файлов проекта (Г.2).
        degraded.append("no_operator_channel")
    if not caps.effort:
        degraded.append("no_effort")

    while steps < limits.max_steps:
        if cancel is not None and cancel():
            stop = Stop.CANCELLED
            break
        if limit is not None:
            # Отказ по лимиту в журнал не пишется: вызова не было, денег не
            # потрачено, писать нечего (как в api._generate). Израсходованное
            # предыдущими ходами при этом остаётся в итоге — оно настоящее.
            try:
                limit.check(_estimate_units(endpoint_id, parts, history,
                                            limits.max_tokens_per_call, frame_mark))
            except LlmError as exc:
                error = exc
                stop = Stop.ERROR
                degraded.append("limit_stop")
                break
        steps += 1
        # Метка рамки одна на все ходы прогона: разойдись она между ходами,
        # модель на пятом ходу увидела бы рамку с меткой, которую сама уже
        # прочитала на первом. Не дали — выпустится своя, но общая на прогон её
        # тогда сделать неоткуда, и кэш префикса рушится на каждом ходу.
        request = Request(parts=parts, max_tokens=limits.max_tokens_per_call,
                          tools=list(tools), history=list(history), effort=effort,
                          frame_mark=frame_mark)
        try:
            result = backend.complete(request, cancel=cancel)
        except LlmError as exc:
            # Беда по проводу на середине прогона. Исключением наружу её пускать
            # нельзя: записи по прошлым ходам в журнале уже есть, а итога с их
            # суммой не будет, и расход повиснет неучтённым.
            error = exc
            stop = Stop.ERROR
            degraded.append("transport_error")
            failed = Result(ok=False, stop=Stop.ERROR, endpoint=endpoint_id,
                            model=spec.model, error=exc, attempts=steps,
                            request_id=getattr(exc, "request_id", None))
            _record(journal, limit, failed, spec, _step_meta(meta, steps, backend))
            break
        total = total + result.usage
        last_text = result.text or last_text
        _record(journal, limit, result, spec, _step_meta(meta, steps, backend))

        if result.stop in (Stop.CANCELLED, Stop.REFUSED):
            stop = result.stop
            break
        if limits.max_units is not None and usage_mod.units(total, spec.prices) > limits.max_units:
            # Обрыв по потолку — отдельный исход, а не ошибка: расход настоящий
            # и в журнале он уже есть. Эквивалента task_budget («модель видит
            # обратный отсчёт и заканчивает аккуратно») у нас нет: мы обрываем.
            stop = Stop.MAX_TOKENS
            degraded.append("budget_cut")
            break
        if not result.tool_calls:
            stop = result.stop or Stop.END_TURN
            break

        history.append({"role": "assistant_tool_calls", "text": result.text,
                        "calls": result.tool_calls})
        for call in result.tool_calls:
            _clean_arguments(call, tools)
            answer = _call_tool(on_call, call)
            history.append({"role": "tool_result", "call_id": call.id,
                            "content": answer.content, "is_error": answer.is_error})
        stop = Stop.TOOL_USE
    else:
        # Потолок ходов исчерпан, модель не закончила. Это исход, а не ошибка.
        stop = Stop.MAX_TOKENS
        degraded.append("step_limit")

    final = Result(ok=stop in (Stop.END_TURN, Stop.TOOL_USE), text=last_text,
                   usage=total, stop=stop, endpoint=endpoint_id, model=spec.model,
                   attempts=steps, degraded=degraded, error=error,
                   latency_ms=int((time.monotonic() - started) * 1000))
    final.units = usage_mod.units(total, spec.prices)
    final.cost = usage_mod.cost(total, spec.prices)
    return final


def _record(journal, limit, result: Result, spec, meta: dict) -> None:
    """Запись хода в журнал вызывающего и в журнал лимита.

    В api._generate вызов один, и хватает «или туда, или туда». Здесь ходов
    десятки, и лимит проверяется перед каждым: если израсходованное не попадёт
    в его журнал, `limit.spent()` не вырастет за прогон и проверка будет
    сравнивать оценку с одним и тем же вчерашним остатком, то есть не проверять
    ничего. Сверка на тождество — чтобы один и тот же журнал, поданный обоими
    путями, не посчитал ход дважды.
    """
    if journal is not None:
        journal.add(result, spec, meta)
    if limit is not None and limit.journal is not journal:
        limit.journal.add(result, spec, meta)


def _step_meta(meta, steps: int, backend) -> dict:
    """meta вызывающей службы + номер хода + повторы транспорта на этом ходу.

    Повторы кладутся в запись, потому что иначе они невидимы: ход, который
    из-за трёх пауз занял вчетверо дольше соседнего, в журнале ничем от него не
    отличается, и «почему прогон шёл двадцать минут» не расследуется.

    Забор записок — общий с api (`api.with_retries`), и это не украшение: два
    места забора означали бы, что одно из них рано или поздно забудут, а
    забытая записка достанется чужому вызову.
    """
    return api.with_retries({**(meta or {}), "step": steps}, backend)


def _estimate_units(endpoint_id: str, parts, history, max_tokens: int,
                    frame_mark=None) -> float:
    """Оценка следующего хода в приведённых единицах — тем же счётом, что api.

    История входит в оценку намеренно: на десятом ходу она и есть основной вес
    запроса, и лимит, считающий один исходный промпт, промахнётся тем сильнее,
    чем длиннее прогон. Счёт по истории грубый (текст ответов и вызовов как
    есть) — точнее посчитать нечем, а недооценить лимит хуже, чем переоценить.
    """
    pieces = list(parts)
    if history:
        текст = "\n".join(f"{item.get('text') or ''}{item.get('content') or ''}"
                          f"{item.get('calls') or ''}" for item in history)
        pieces.append(Part(role="neighbors", text=текст, stable=False))
    return api.estimate(endpoint_id, pieces, max_tokens=max_tokens,
                        frame_mark=frame_mark).units


def _clean_arguments(call, tools) -> None:
    """Гасит null «этого поля я не задаю» в аргументах вызова инструмента.

    Обратная половина `strictify` в `_tool_json`: строгий режим заставил нас
    перечислить в `required` все ключи и разрешить необязательным null, и без
    гашения инструмент вызывающего получил бы `кодировка: None` как настоящее
    значение — то есть открыл бы файл в кодировке None вместо своего
    умолчания. Ошибки при этом не будет ни одной.

    Гасим по **исходной** схеме инструмента: по расширенной гасить нечего, она
    сама эти null и разрешила. `raw_arguments` остаётся дословным — пересчитать
    задним числом должно быть чем.
    """
    schema = next((t.schema for t in tools if t.name == call.name), None)
    if schema:
        call.arguments = jsonschema.drop_unset(call.arguments, schema)


def _call_tool(on_call, call) -> ToolResult:
    """Вызов инструмента. Любая беда возвращается модели, а не наружу.

    Битые аргументы (`arguments` пустые при непустом `raw_arguments`) — тот же
    случай: модель ошиблась, и сказать ей об этом надо ответом инструмента.
    """
    # `{}` — законный вызов инструмента без аргументов, а не битый JSON: его шлёт
    # всякий openai-совместимый поставщик. Без этой оговорки инструменты без
    # аргументов (`list_project_files`, `preview`) отвергались бы всегда, не доходя
    # до вызова, — и молча, потому что модель получала бы внятный отказ и «чинилась».
    if call.raw_arguments.strip() not in ("", "{}") and not call.arguments:
        return ToolResult(call_id=call.id, is_error=True,
                          content="аргументы не разобрались как JSON; "
                                  "повтори вызов с корректным JSON")
    try:
        answer = on_call(call)
    except Exception as exc:                      # noqa: BLE001 — сознательно широко
        return ToolResult(call_id=call.id, is_error=True,
                          content=f"инструмент {call.name} не отработал: {exc}")
    if isinstance(answer, ToolResult):
        return answer
    return ToolResult(call_id=call.id, content=str(answer))


__all__ = ["run_tools", "Limits", "MAX_STEPS_DEFAULT"]
