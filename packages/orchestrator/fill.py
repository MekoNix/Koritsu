"""
fill — два уровня вызова модели: один тег и весь отчёт потоком.

Уровень 1 (`fill_tag`) — схема одного значения, `llm.generate_value`. Годится,
когда человек правит один тег и хочет переписать именно его.

Уровень 2 (`fill_report`) — схема всего отчёта, `llm.stream_object`. Он не
роскошь и не оптимизация: **теги связаны**. Введение ссылается на цель, вывод —
на замеры, заключение повторяет задачи введения. N независимых вызовов дадут N
связных по отдельности и рассогласованных вместе кусков, и заметно это станет
только при чтении отчёта целиком — то есть на кафедре.

Потоковым уровень 2 обязан быть по другой причине: он длинный, а длинное
рвётся. Значения сохраняются по мере закрытия своих объектов, поэтому обрыв на
девятом теге из двенадцати оставляет девять сохранённых, а не ноль. Человек
видит «заполнено 9 из 12, прогон оборвался», а не «ошибка» — и не платит второй
раз за уже полученное.

Что здесь общего у обоих уровней и почему это важно:

* **Один валидатор.** Всё, что вернула модель, проходит `wire.value_from_json`
  и `hokoku.validate` — ровно то же, что проходит значение, пришедшее из
  интерфейса. Отдельного «доверенного» пути для модели нет: он и был бы той
  дырой, через которую в отчёт попадает то, чего человеку положить не дали.
* **Одна точка записи.** Версию заводит только `Project.set_value`.
* **Лимит и журнал — в оба.** Оба параметра слой принимает аргументами, и оба
  сюда проведены: отказ по лимиту приходит ДО вызова (посреди — это уже
  потраченные деньги), а запись в журнал делается и на неудаче тоже.
* **Жёсткая беда версии не заводит.** Значение, которое не выражается или не
  проходит проверку, уезжает в `problems`; мягкое замечание («проверить») —
  в `Version.flags` вместе с сохранённым значением. Иначе история значения
  засоряется битым, и «Вернуть» предлагает вернуться к нему.
* **Чужого не трогаем.** Тег, чья текущая версия поставлена человеком
  (`source` = `manual` или `file`), прогон обходит: у уровня 2 — молча для
  модели и с пометкой для человека, у уровня 1 — отказом. Ради этого различия
  `source` и заведён; переписать можно, но только сказав `overwrite=True`.
  Отбор `schema.fillable` (нет в шаблоне, заполняет не модель) применяют оба
  уровня — раньше уровень 1 не применял его вовсе.
* **Null «этого поля я не задаю» гасим сами.** Слой объявил это обязанностью
  вызывающего, и на строгой ступени цена пропуска — не подменённое умолчание,
  а потерянное значение целиком (`_accept`).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import hokoku
import llm

from . import prompt as prompt_mod, schema as schema_mod
from .errors import OrchestratorError, hint
from .stream import TagStream


@dataclass
class TagFill:
    """Исход заполнения одного тега.

    `ok` означает «значение сохранено новой версией». Сохранённое значение с
    мягкими замечаниями — это `ok=True` и непустые `flags`: файл полезен с
    пометками, а отказ отдал бы человеку ничего за те же деньги.
    """

    key: str
    ok: bool = False
    value: dict | None = None
    version: object = None
    problems: list = field(default_factory=list)
    flags: list = field(default_factory=list)
    stop: str = ""
    usage: dict = field(default_factory=dict)


@dataclass
class RunResult:
    """Итог прогона уровня 2. `ok` — прогон дошёл до конца, а не «всё заполнено».

    Разделять обязательно: прогон, в котором модель отказалась заполнить один
    необязательный тег, кончился штатно, а прогон, оборванный связью на первом
    теге, — нет, хотя в обоих часть тегов пуста.
    """

    run: object
    filled: list = field(default_factory=list)
    problems: list = field(default_factory=list)
    usage: dict = field(default_factory=dict)
    stop: str = ""
    outcome: str = ""
    ok: bool = False


# ── уровень 1 ────────────────────────────────────────────────────────────────

def fill_tag(project, key: str, *, endpoint: str, run=None, chunks=(),
             effort=None, cancel=None, max_tokens=None,
             overwrite: bool = False) -> TagFill:
    """Один тег: схема его типа → `llm.generate_value` → проверка → версия.

    `run` можно передать снаружи (тогда несколько тегов делятся одной меткой
    рамки и одним кэшируемым префиксом) или не передавать — тогда прогон
    заводится свой. Второе дороже: у каждого прогона своя метка, а метка стоит
    в каждом недоверенном куске — `files`, `manifest`, `neighbors`, — то есть
    между прогонами кэшируется только `rules`. Внутри прогона кэш цел, и это
    ровно тот размен И.1, на который владелец пошёл сознательно.

    Отбор тот же, что у уровня 2, и это не формальность: без него вызов платит
    настоящими деньгами за тег, которого нет в шаблоне, а подпись руководителя
    сочиняет модель. `overwrite=True` — единственный способ переписать значение,
    которое написал человек; молчаливое согласие здесь означало бы, что он
    узнаёт о пропаже своего текста из готового отчёта.
    """
    manifest = project.manifest()
    key = hokoku.wire.norm_key(str(key))
    spec = schema_mod.spec_of(manifest, key)
    if not schema_mod.fillable(manifest, keys=[key]):
        # Причина одна из двух, и назвать её надо: «нельзя» без «почему»
        # выглядит поломкой службы, а это решение манифеста.
        raise OrchestratorError(
            f"тег {key!r} помечен «нет в шаблоне»: заполнять нечего"
            if spec.missing else
            f"тег {key!r} по манифесту заполняет не модель, а {spec.source_hint!r}")
    if not overwrite:
        held = _held_by(project, key)
        if held is not None:
            raise OrchestratorError(
                f"значение тега {key!r} поставлено не моделью ({held!r}): "
                "прогон его не трогает. Переписать — overwrite=True")
    own_run = run is None
    if own_run:
        run = project.start_run(level=1, endpoint=endpoint)

    parts = prompt_mod.build_parts(project, keys=[key], level=1, manifest=manifest,
                                   chunks=chunks)
    _seal(project, run, parts)

    limit = project.limit()
    result = llm.generate_value(
        endpoint, schema_mod.tag_schema(spec), parts,
        **({} if max_tokens is None else {"max_tokens": max_tokens}),
        effort=effort, cancel=cancel, limit=limit, journal=project.journal(),
        frame_mark=run.mark, meta={"run": run.id, "tag": key, "level": 1})

    if not result.ok or not isinstance(result.value, dict):
        fill = TagFill(key=key, ok=False, stop=result.stop,
                       usage=llm.usage_of(result),
                       problems=[_problem("model_failed", key, _why(result))])
    else:
        fill = _accept(project, manifest, key, result.value, run=run, result=result,
                       parts=parts, others=_typed_values(project, skip=key),
                       template=project.template())
    run.steps.append({"key": key, "ok": fill.ok, "stop": fill.stop})
    if own_run:
        project.finish_run(run, "done" if fill.ok else "error")
    else:
        project.save_run(run)
    return fill


# ── уровень 2 ────────────────────────────────────────────────────────────────

def fill_report(project, *, endpoint: str, keys=None, chunks=(), effort=None,
                cancel=None, max_tokens=None, on_tag=None, on_text=None,
                overwrite: bool = False) -> RunResult:
    """Весь отчёт одним потоковым вызовом; готовые теги сохраняются по ходу.

    `on_text(кусок)` зовётся на каждый кусок текста потока, до разбора. Тот
    самый кадр, ради которого уровень 2 сделан потоковым: служба отдаёт его
    человеку по мере генерации, а склейку в ~100 мс делает она же — здесь
    куски идут как пришли, и решать за читателя, сколько их копить, слой
    прогона не должен. Обрыв внутри `on_text` не ловится намеренно: если
    приёмник кадров сломан, прогон надо останавливать, а не платить дальше в
    пустоту.

    `on_tag(TagFill)` зовётся сразу после сохранения каждого тега. Он нужен с
    самого начала, хотя сегодня печатает строку в stderr: это будущий кадр SSE.
    Без него уровень 2 написался бы как «дождались, разобрали, сохранили всё», и
    частичное сохранение пришлось бы вставлять заново — а вставлять его в
    готовый цикл поздно, потому что к тому моменту сохранение уже привязано к
    концу потока.

    Написанное человеком прогон не трогает (`overwrite=False`): такой тег
    выбрасывается из отбора ДО сборки схемы, то есть модель о нём даже не
    спрашивают. Из промпта он при этом не исчезает — соседом он поехать обязан,
    иначе остальные теги окажутся с ним рассогласованы.
    """
    manifest = project.manifest()
    wanted = schema_mod.fillable(manifest, keys=keys)
    kept: list = []
    if not overwrite:
        held = [(key, _held_by(project, key)) for key in wanted]
        wanted = [key for key, who in held if who is None]
        kept = [_problem("kept", key,
                         f"значение тега {key!r} поставлено не моделью ({who!r}): "
                         "прогон его не трогает", "info")
                for key, who in held if who is not None]
        if not wanted and kept:
            # Отдельный текст, потому что общий («ни одного заполняемого тега»)
            # соврал бы: теги заполняемые, просто все уже написаны человеком.
            raise OrchestratorError(
                "все запрошенные теги написаны не моделью: "
                + ", ".join(repr(p["key"]) for p in kept)
                + ". Переписать — overwrite=True")
    schema = schema_mod.report_schema(manifest, keys=wanted)
    run = project.start_run(level=2, endpoint=endpoint)
    parts = prompt_mod.build_parts(project, keys=wanted, level=2, manifest=manifest,
                                   chunks=chunks)
    _seal(project, run, parts)

    out = RunResult(run=run, problems=list(kept))
    # Шаблон читается один раз на прогон: `validate` разбирает DOCX, и делать это
    # заново на каждом из двенадцати тегов — двенадцать разборов одного файла.
    template = project.template()
    typed = _typed_values(project, skip=None)
    tags = TagStream()
    seen: set = set()
    allowed = set(wanted)
    error = None
    stream = llm.stream_object(
        endpoint, schema, parts,
        **({} if max_tokens is None else {"max_tokens": max_tokens}),
        effort=effort, cancel=cancel, limit=project.limit(),
        journal=project.journal(), frame_mark=run.mark,
        meta={"run": run.id, "level": 2})
    try:
        for chunk in stream:
            if chunk.kind == "text":
                if on_text is not None:
                    on_text(chunk.text)
                for key, value_json in tags.feed(chunk.text):
                    fill = _tag_of_stream(project, manifest, key, value_json, run,
                                          typed=typed, seen=seen, allowed=allowed,
                                          parts=parts, out=out, template=template)
                    if fill is not None and on_tag is not None:
                        on_tag(fill)
            elif chunk.kind == "usage" and chunk.usage is not None:
                out.usage = {**chunk.usage.as_dict(), "raw": dict(chunk.raw or {})}
            elif chunk.kind == "stop":
                out.stop = chunk.stop or out.stop
            elif chunk.kind == "error" and chunk.error is not None:
                error = chunk.error
    except llm.LlmError as exc:
        # Обрыв по проводу приходит исключением, отказ модели — куском потока.
        # Исходы разные, а поведение одно: сохранённое остаётся сохранённым.
        error = exc
    if error is not None:
        out.problems.append(_problem("stream_failed", None, str(error)))

    tail = tags.close()
    for key, raw in tail["broken"]:
        out.problems.append(_problem("broken_value", key,
                                     f"значение тега {key!r} не разобралось как JSON: "
                                     f"{raw[:200]}"))
    for key, raw in tail["skipped"]:
        if raw.strip() == "null" and key in allowed and not _required(manifest, key):
            # Это не ошибка модели, а наше же разрешение: `strictify` кладёт в
            # `required` все теги корня и взамен делает необязательный тег
            # nullable. Ответить на разрешённое `null` бедой уровня `error` (да
            # ещё и «тег не вернулся» вдогонку) значит ругать модель за то, что
            # мы сами ей велели. Тег считается пройденным: его не «потеряли».
            seen.add(key)
            out.problems.append(_problem(
                "left_unset", key,
                f"модель не стала заполнять необязательный тег {key!r}", "info"))
            continue
        out.problems.append(_problem("not_an_object", key,
                                     f"значение тега {key!r} — не объект, а {raw[:80]!r}"))
    for key in wanted:
        if key not in seen:
            # «Заполнено 9 из 12» человек должен увидеть сразу, а не узнать при
            # сборке: прогон кончился штатно, а тег так и не пришёл.
            out.problems.append(_problem("not_returned", key,
                                         f"модель не вернула тег {key!r}", "info"))
    out.outcome = _outcome(out, error, tags)
    if tags.truncated and tail["key"]:
        out.problems.append(_problem("truncated", tail["key"],
                                     f"поток оборвался на теге {tail['key']!r}: "
                                     "значение не дописано и не сохранено"))
    out.ok = out.outcome == "done"
    project.finish_run(run, out.outcome)
    return out


def _tag_of_stream(project, manifest, key, value_json, run, *, typed, seen,
                   allowed, parts, out, template) -> TagFill | None:
    """Один закрывшийся тег потока: проверить, сохранить, записать в итог."""
    key = hokoku.wire.norm_key(str(key))
    if key not in allowed:
        # `additionalProperties: false` в схеме поток не стережёт: мы разбираем
        # его сами. Опечатка в имени тега иначе потеряла бы значение молча.
        out.problems.append(_problem("unknown_key", key,
                                     f"модель вернула тег {key!r}, которого не просили"
                                     f"{hint(key, allowed)}"))
        return None
    if key in seen:
        out.problems.append(_problem("duplicate_key", key,
                                     f"тег {key!r} пришёл в потоке дважды: "
                                     "второе значение отброшено"))
        return None
    seen.add(key)
    fill = _accept(project, manifest, key, value_json, run=run, result=None,
                   parts=parts, others=typed, template=template)
    if fill.ok:
        out.filled.append(key)
        parsed = _parse(project, value_json)
        if parsed is not None:
            # Сохранённый тег становится соседом для следующих: `depends_on`
            # проверяется по тому, что уже есть, а не по тому, что будет.
            typed[key] = parsed
    out.problems.extend(fill.problems)
    run.steps.append({"key": key, "ok": fill.ok, "flags": list(fill.flags)})
    return fill


# ── общее: проверка и запись ─────────────────────────────────────────────────

def _accept(project, manifest, key: str, value_json: dict, *, run, result, parts,
            others: dict, template, stop: str = "", extra_flags=()) -> TagFill:
    """Значение модели → проверки → версия. Общий хвост **всех трёх** уровней.

    Порядок проверок содержательный и меняться не должен: сначала `wire`
    (значение вообще выражается, тип известен, артефакт достался — это
    единственный способ узнать, что артефакт существует), потом `hokoku.validate`
    (годность против шаблона и манифеста). Обратный порядок означал бы проверку
    лимитов у значения, которое ещё неизвестно чем является.

    `extra_flags` — пометки, которые ставит не проверка значения, а условия
    прогона: сегодня это «проверить» уровня 3 на endpoint'е без операторского
    канала (`tools.operator_channel_gate`). Параметр, а не второй путь записи:
    инструмент `set_tag` обязан быть этой самой функцией, иначе защита правки
    человека, версии и `source` разойдутся на первой же правке.
    """
    stop = stop or (result.stop if result is not None else "")
    usage = llm.usage_of(result) if result is not None else {}
    # Гашение null'ов «этого поля я не задаю» — обязанность вызывающего, и слой
    # объявил её прямо (`llm/api.py`, stream_object). Схема берётся ИСХОДНАЯ, по
    # одному тегу: к поставщику уехала расширенная (`strictify`), по ней гасить
    # нечего — она сама эти null'ы и разрешила. Цена пропуска не «умолчание
    # подменилось», а потеря: `strictify` делает nullable служебное поле `v`,
    # которое есть у каждого типа значения, поэтому не погашенный ответ не
    # выражается вовсе — теряется даже простой текст. На уровне 1 то же самое уже
    # сделал `run_ladder`; повтор безвреден (гасить второй раз нечего) и держит
    # обещание независимо от того, каким путём слой сходил к модели.
    value_json = llm.jsonschema.drop_unset(
        value_json, schema_mod.tag_schema(schema_mod.spec_of(manifest, key)))
    try:
        typed = hokoku.value_from_json(value_json,
                                       resolve_artifact=project.resolve_artifact)
    except hokoku.WireError as exc:
        return TagFill(key=key, ok=False, value=value_json, stop=stop, usage=usage,
                       problems=[_problem("wire", key, exc.detail)])

    problems = _check(template, manifest, key, typed, others)
    hard = [p for p in problems if p.level == "error"]
    if hard:
        # Жёсткая беда версии не заводит: история значения не должна собирать
        # то, к чему «Вернуть» возвращаться не имеет права.
        return TagFill(key=key, ok=False, value=value_json, stop=stop, usage=usage,
                       problems=problems)

    flags = [*extra_flags] + [f"{p.code}: {p.message}" for p in problems]
    version = project.set_value(
        key, value_json, source="agent", run=run.id, flags=flags,
        meta={"endpoint": run.endpoint,
              "model": (result.model if result is not None else ""),
              "prompt_hash": prompt_mod.prompt_hash(parts),
              "manifest_version": manifest.manifest_version,
              "stop": stop, "usage": usage})
    return TagFill(key=key, ok=True, value=value_json, version=version, flags=flags,
                   problems=problems, stop=stop, usage=usage)


def _check(template, manifest, key: str, typed, others: dict) -> list:
    """`hokoku.validate` по одному тегу — тот же валидатор, что и у интерфейса.

    Замечания фильтруются по ключу, и это не сокрытие проблем. `validate` смотрит
    на весь отчёт сразу и честно говорит «обязательный тег без значения» про все
    ещё не заполненные теги; посреди прогона уровня 2 это не беда, а «ещё не
    дошли». Полная, нефильтрованная проверка делается один раз перед сборкой
    (`build`), и именно она решает, годен ли отчёт.
    """
    values = dict(others)
    values[key] = typed
    try:
        problems = hokoku.validate(template, values, manifest)
    except Exception as exc:                       # noqa: BLE001 — шаблон чужой
        return [_problem("validate_failed", key,
                         f"проверка значения не удалась: {type(exc).__name__}: {exc}")]
    return [p for p in problems if p.key == key]


def _held_by(project, key: str) -> str | None:
    """`source` текущей версии, если её поставила не модель, иначе None.

    Смотрим на версию, а не на `source_hint` манифеста: подсказка манифеста
    говорит, кто заполняет тег вообще, а вопрос здесь другой — кто написал ТО,
    что лежит сейчас. Ради этого различия `source` и заведён: без него правка
    человека неотличима от сгенерированного, и прогон затирает её молча.

    `template` (умолчание шаблона) чужим не считается: его никто не писал руками,
    и заменить его — ровно то, зачем прогон и зовут.
    """
    head = project.head_version(key)
    if head is None:
        return None
    return head.source if head.source in ("manual", "file") else None


def _required(manifest, key: str) -> bool:
    """Обязателен ли тег по манифесту — тот же признак, что кладёт `required`
    схемы (`hokoku.manifest_schema`). Второго списка обязательных не заводим:
    разойдись он со схемой — модель разрешено не заполнять одно, а спрашиваем
    мы другое."""
    spec = manifest.tags.get(key)
    return bool(spec is None or spec.required)


def _typed_values(project, *, skip) -> dict:
    """Уже сохранённые значения в типизированном виде — соседи для проверки.

    Битые значения молча выбрасываются: они уже лежат в проекте, чинить их —
    работа человека, а ронять из-за них заполнение соседнего тега незачем.
    """
    stored = project.values()
    if skip is not None:
        stored.pop(skip, None)
    typed, _errors = hokoku.values_from_json(
        stored, resolve_artifact=project.resolve_artifact)
    return typed


def _parse(project, value_json: dict):
    try:
        return hokoku.value_from_json(value_json,
                                      resolve_artifact=project.resolve_artifact)
    except hokoku.WireError:
        return None


def _seal(project, run, parts) -> None:
    """Выпустить метку рамки прогона и записать её в прогон.

    Метка выпускается один раз по всем недоверенным текстам сразу — до того, как
    хоть один кусок отрендерен. Тогда перевыпуск на рендере невозможен, и метка
    в `runs/<id>.json` — та же самая, что уехала по проводу. Иначе «какой меткой
    были обёрнуты файлы» стало бы вопросом без ответа.

    Записанным дело не кончается: метка **передаётся явно** — `frame_mark=` у
    `generate_value` и `stream_object`. Совпадение записанного с проводом
    держится на этом, а не на удаче: метка принадлежит запросу, и не передай мы
    свою, слой выпустит на каждый запрос собственную. Тогда в `runs/<id>.json`
    лежала бы метка, которой модель не видела, а кэш префикса рушился бы на
    каждом вызове прогона — недоверенные куски каждый раз новые.
    """
    run.mark = prompt_mod.seal_mark(parts, run.mark or None)
    project.save_run(run)


def _outcome(out: RunResult, error, tags: TagStream) -> str:
    """Итог прогона одним словом. Разделение стоит того, чтобы его не сливать.

    `interrupted` — заплатили и часть получили; `error` — не получили ничего по
    нашей или чужой вине; `refused` — законный отказ модели, повторять его
    бессмысленно и денег он стоил столько же.
    """
    if error is not None:
        return "interrupted" if out.filled else "error"
    if out.stop == llm.Stop.REFUSED:
        return "refused"
    if out.stop in (llm.Stop.CANCELLED, llm.Stop.MAX_TOKENS) or tags.truncated:
        return "interrupted"
    if out.stop == llm.Stop.ERROR:
        return "interrupted" if out.filled else "error"
    return "done"


def _why(result) -> str:
    if getattr(result, "error", None) is not None:
        return str(result.error)
    if not isinstance(result.value, dict):
        return f"модель вернула {type(result.value).__name__}, а нужен объект значения"
    return f"вызов не удался (stop={result.stop})"


def _problem(code: str, key, message: str, level: str = "error") -> hokoku.Problem:
    """Замечание службы. Запись та же, что у `hokoku.validate` и `check_manifest`.

    Один канал замечаний на все пакеты (`kyotsu.Notice`, а с тегом —
    `hokoku.Problem`): интерфейс разбирает `module`, `level`, `code`, `key`,
    `message` и не должен знать, кто именно ругнулся. `module` здесь
    `orchestrator` — по нему и видно, что беда не в значении, а в прогоне.

    Своего такого же класса служба не заводит: два одинаковых dataclass'а — это
    два места, где чинить одно и то же поле, и ровно так каналы и разъезжались.
    """
    return hokoku.Problem(module="orchestrator", level=level, code=code, key=key,
                          message=message)


__all__ = ["TagFill", "RunResult", "fill_tag", "fill_report"]
