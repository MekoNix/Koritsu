"""
structured — лестница структурированного вывода (А.3).

Единственная возможность из матрицы, которую можно честно эмулировать. Слой
спускается по ступеням, пока endpoint не согласится:

  1. json_schema — схема прямо в запросе. Модель физически не может выдумать
     ключ. Это и есть тот забор, на котором держится защита от инъекции: что бы
     ни было написано в файле студента, вернуть можно только объявленные ключи.
  2. tool_strict — один инструмент `set_values` с той же схемой и tool_choice,
     вынуждающим его вызвать. Гарантии почти те же, дороже на объявление.
  3. json_object — гарантируется только валидный JSON; ключи и типы проверяет
     наш валидатор.
  4. text — свободный текст, JSON выковыриваем сами. Работает всегда, ошибается
     чаще всего.

Порядок именно такой (а не «схема → режим JSON → инструмент»): строгий
инструмент даёт гарантию невыдуманного ключа, а json_object — нет.

Три правила, которые легко потерять при реализации:
  * На всех четырёх ступенях значение проходит **один и тот же** валидатор.
    Разница между ступенями — только вероятность, что он ругнётся.
  * Ступени 3 и 4 требуют повтора при неудачном разборе — до двух раз, потом
    отказ. Повторы считаются в расход: они настоящие вызовы за настоящие деньги.
  * На ступенях 1–2 необязательное поле выражается null'ом, а не отсутствием:
    строгий режим требует все ключи в `required` (jsonschema.strictify). Такой
    null значит «я этого поля не задаю», и до вызывающего он не доходит —
    `jsonschema.drop_unset` снимает его перед проверкой. Потеряете гашение —
    модель начнёт выдумывать оформление, и подмена умолчания получателя пройдёт
    без единой ошибки.
"""
from __future__ import annotations

import json
import re

from .errors import ErrorKind, LlmError, Stop
from .model import Part, Result, Structured, Usage
from . import jsonschema, usage as usage_mod

MAX_RETRIES = 2      # ступени 3–4: два повтора, потом честный отказ


def degraded_for(step: str, caps) -> list:
    """Чего не было и что пришлось обойти — для поля `degraded` (Б.2).

    Это не предупреждение пользователю, а объяснение цифр в журнале: почему у
    этой генерации cache_read ноль и почему она стоила вчетверо.
    """
    marks: list = []
    if Structured.rank(step) > Structured.rank(Structured.JSON_SCHEMA):
        marks.append("no_json_schema")
    if step in (Structured.JSON_OBJECT, Structured.TEXT):
        marks.append("schema_checked_locally")
    if caps is not None:
        from .model import OperatorChannel, PrefixCache
        if caps.prefix_cache == PrefixCache.NONE:
            marks.append("no_prefix_cache")
        if not caps.effort:
            marks.append("no_effort")
        if caps.operator_channel != OperatorChannel.MESSAGES_SYSTEM:
            marks.append("no_operator_channel")
        if caps.usage_contaminated:
            # Не обход, а предупреждение о самих цифрах записи: счётчики этого
            # endpoint'а включают расход посредника, а не только наш вызов.
            # Место то же и по той же причине: `degraded` и заведён затем, чтобы
            # цифру в журнале было чем объяснить, когда её спросят.
            marks.append("usage_with_agent_overhead")
    return marks


def schema_hint(schema: dict, step: str) -> str:
    """Добавка к промпту для ступеней, где схему в запрос не положишь.

    На ступенях 1–2 схема едет по проводу и повторять её словами вредно: модель
    склонна копировать пример из промпта вместо того, чтобы заполнять поля.
    На ступенях 3–4 это единственный способ сообщить требования.
    """
    if step in (Structured.JSON_SCHEMA, Structured.TOOL_STRICT):
        return ""
    described = jsonschema.describe(schema)
    tail = ("Ответь ОДНИМ объектом JSON и ничем больше: без пояснений, "
            "без markdown-заборов, без текста до и после.")
    if step == Structured.TEXT:
        tail = ("Ответь ОДНИМ объектом JSON. Если без пояснений никак, "
                "положи объект в блок ```json ... ```.")
    return f"Требуемая структура ответа:\n{described}\n\n{tail}" if described else tail


def retry_hint(errors, raw_text: str) -> str:
    """Промпт повтора: что именно пришло и что с ним не так.

    Показываем модели её собственный ответ и список претензий валидатора.
    Без этого повтор — та же лотерея; с этим модель обычно чинит ответ с
    первого раза. Текст обрезан: длинный неудачный ответ стоит денег на входе.
    """
    listed = "\n".join(f"- {e}" for e in errors[:10])
    shown = raw_text[:1500]
    return ("Предыдущий ответ не подошёл.\n\n"
            f"Ты ответил:\n{shown}\n\n"
            f"Что не так:\n{listed}\n\n"
            "Ответь заново — только объект JSON, исправив перечисленное.")


# ── извлечение JSON из ответа ───────────────────────────────────────────────
_FENCE_RE = re.compile(r"```(?:json)?\s*(.+?)```", re.DOTALL | re.IGNORECASE)


def extract_json(text: str):
    """JSON из ответа модели. Возвращает объект или бросает ValueError.

    Четыре попытки, от строгой к отчаянной. Порядок важен: сначала пробуем
    весь текст целиком (так приходит ответ на ступенях 1–3), и только потом
    ищем в тексте — иначе на ответе `{"a": 1}` мы бы полезли искать скобки.
    """
    if not text or not text.strip():
        raise ValueError("пустой ответ")
    stripped = text.strip()
    try:
        return json.loads(stripped)
    except (ValueError, json.JSONDecodeError):
        pass
    # Забор ```json ... ``` — самый частый способ модели «пояснить» ответ.
    for match in _FENCE_RE.finditer(stripped):
        try:
            return json.loads(match.group(1).strip())
        except (ValueError, json.JSONDecodeError):
            continue
    # Сбалансированный объект или список где-то внутри текста.
    found = _find_balanced(stripped)
    if found is not None:
        return found
    raise ValueError("в ответе нет разбираемого JSON")


def _find_balanced(text: str):
    """Первый сбалансированный { } или [ ] в тексте, с учётом строк и экранов.

    Наивный поиск по первой и последней скобке ломается на любом ответе, где
    фигурная скобка встречается в тексте значения, — а у нас значения тегов
    сплошь человеческий текст, в котором бывает всё.
    """
    for opener, closer in (("{", "}"), ("[", "]")):
        start = text.find(opener)
        while start != -1:
            depth = 0
            in_string = False
            escaped = False
            for i in range(start, len(text)):
                ch = text[i]
                if in_string:
                    if escaped:
                        escaped = False
                    elif ch == "\\":
                        escaped = True
                    elif ch == '"':
                        in_string = False
                    continue
                if ch == '"':
                    in_string = True
                elif ch == opener:
                    depth += 1
                elif ch == closer:
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(text[start:i + 1])
                        except (ValueError, json.JSONDecodeError):
                            break
            start = text.find(opener, start + 1)
    return None


def value_from_result(result: Result, schema: dict, step: str):
    """Значение из ответа: из вызова инструмента или из текста.

    На ступени 2 объект приходит аргументами `set_values`, на остальных — в
    тексте. Дальше и там и там один и тот же валидатор — в этом весь смысл
    лестницы: вызывающий код не должен знать, какой ступенью значение добыто.
    """
    if step == Structured.TOOL_STRICT:
        for call in result.tool_calls:
            if call.name == "set_values":
                if call.arguments or not call.raw_arguments.strip():
                    return call.arguments
                # Инструмент позвали, но аргументы не разобрались — это тот же
                # битый JSON, только приехавший другим полем.
                return extract_json(call.raw_arguments)
        raise ValueError("модель не позвала set_values")
    return extract_json(result.text)


def run_ladder(backend, request_factory, schema: dict, caps=None, cancel=None,
               max_retries: int = MAX_RETRIES) -> Result:
    """Полный проход лестницы с повторами. Возвращает Result со значением.

    `request_factory(step, extra_parts) -> Request` — собирает запрос под
    выбранную ступень. Фабрика, а не готовый запрос: на повторе к промпту
    добавляется разбор ошибок, а на ступени 2 меняется весь способ спросить.

    Что здесь важно и неочевидно:
      * повторы **суммируются в расход**: каждый — настоящий вызов, и если
        считать только последний, журнал будет врать в пользу дешевизны;
      * ступени 1 и 2 повторов не требуют — если уж там пришло не то, повтор
        не поможет, сломано что-то другое;
      * отказ модели (Stop.REFUSED) повторять нельзя: это законный исход, и
        второй заход даст ровно тот же отказ за вторые деньги.
    """
    # Ступень решается один раз, до первого вызова: она зафиксирована пробой, и
    # пересматривать её в горячем пути значит платить за неудачные попытки.
    step = backend.supported_step(Structured.JSON_SCHEMA)
    jsonschema.check_schema(schema)
    # strictify кладёт в required все ключи — иначе строгий режим схему не примет —
    # и взамен разрешает необязательным полям null. Обратно его снимает drop_unset.
    prepared = jsonschema.strictify(schema) if step in (Structured.JSON_SCHEMA,
                                                        Structured.TOOL_STRICT) else schema

    total_usage = Usage()
    attempts = 0
    extra_parts: list = []
    last_errors: list = []
    last_result: Result | None = None
    allowed = 1 if step in (Structured.JSON_SCHEMA, Structured.TOOL_STRICT) else max_retries + 1

    while attempts < allowed:
        attempts += 1
        request = request_factory(step, prepared, extra_parts)
        result = backend.complete(request, cancel=cancel)
        total_usage = total_usage + result.usage
        last_result = result

        if result.stop == Stop.CANCELLED:
            return _finish(result, backend, total_usage, attempts, step, caps,
                           value=None, ok=False)
        if result.stop == Stop.REFUSED:
            # Отказ — исход, а не ошибка: usage есть, в журнал он идёт,
            # повторять бессмысленно.
            return _finish(result, backend, total_usage, attempts, step, caps,
                           value=None, ok=False)

        try:
            value = value_from_result(result, prepared, step)
        except ValueError as exc:
            if result.stop == Stop.MAX_TOKENS:
                # Ответ обрезан потолком вывода, а не испорчен моделью. Повтор
                # с тем же потолком обрежет его в том же месте — это чистая
                # трата денег. И главное: причина остановки обязана дойти до
                # вызывающего как `max_tokens`, иначе он не поймёт, что лечится
                # это увеличением потолка, а не другим промптом.
                finished = _finish(result, backend, total_usage, attempts, step,
                                   caps, value=None, ok=False)
                finished.stop = Stop.MAX_TOKENS
                finished.error = LlmError(
                    ErrorKind.BAD_RESPONSE,
                    "ответ обрезан потолком вывода и потому не разобрался; "
                    "нужен больший max_tokens, а не повтор",
                    endpoint=backend.spec.id)
                return finished
            last_errors = [str(exc)]
            extra_parts = [Part(role="request", text=retry_hint(last_errors, result.text))]
            continue

        # null «этого поля я не задаю» до вызывающего доходить не должен: оставить
        # его значило бы перекрыть умолчание получателя значением, которого модель
        # не выбирала. Гасим на всех четырёх ступенях, а не только на строгих:
        # одинаковое значение с любой ступени — обещание этого модуля, а модель
        # шлёт такой null и там, где схема к поставщику не ездила.
        value = jsonschema.drop_unset(value, schema)
        errors = jsonschema.validate(value, schema)
        if not errors:
            return _finish(result, backend, total_usage, attempts, step, caps,
                           value=value, ok=True)
        last_errors = errors
        extra_parts = [Part(role="request",
                            text=retry_hint(errors, json.dumps(value, ensure_ascii=False)))]

    # Все попытки исчерпаны. Расход уже потрачен и обязан попасть в результат.
    result = last_result or Result(endpoint=backend.spec.id, model=backend.spec.model)
    finished = _finish(result, backend, total_usage, attempts, step, caps,
                       value=None, ok=False)
    finished.stop = Stop.ERROR
    finished.error = LlmError(
        ErrorKind.BAD_RESPONSE,
        f"ответ не разобрался за {attempts} попыт(ку/ки): "
        + "; ".join(last_errors[:5]),
        endpoint=backend.spec.id)
    return finished


def _finish(result: Result, backend, total_usage: Usage, attempts: int, step: str,
            caps, value, ok: bool) -> Result:
    """Досборка Result: суммарный расход, единицы, деньги, пометки деградации."""
    result.value = value
    result.ok = ok
    result.usage = total_usage
    result.attempts = attempts
    result.structured_step = step
    result.units = usage_mod.units(total_usage, backend.spec.prices)
    result.cost = usage_mod.cost(total_usage, backend.spec.prices)
    result.degraded = degraded_for(step, caps)
    return result


__all__ = ["run_ladder", "extract_json", "schema_hint", "retry_hint",
           "degraded_for", "value_from_result", "MAX_RETRIES"]
