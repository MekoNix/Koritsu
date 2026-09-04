"""
doors — двери службы наружу: вопрос вне тегов, шаблон работы, проверка кода, `Services`.

Эти двери заведены ради одного правила разреза: **сценарий не разговаривает
с моделью и не знает путей.** `kadai` — сценарий; всё, что у него есть, приходит
аргументом, а не импортом (`kadai.seams.Services`). Значит кто-то обязан собрать
эти двери из готовой механики, и это здесь.

**`ask` — безтеговая дверь к модели** (записка о kadai, И.16). Обе прежние точки
входа привязаны к тегам: `fill_tag` отказывает на ключе вне манифеста,
`fill_report` строит схему из манифеста. Стадиям «разбор задания» и «структура»
отвечать было нечем, и без этой двери `kadai` пришлось бы импортировать `llm` —
то есть завести второй средний слой. Внутри всё то же самое, что у уровня 1:
раскладка кусков, рамка вокруг недоверенного текста, метка рамки на прогон,
журнал расхода, лимит пользователя и проверка ответа схемой. Не заводится ровно
одно — версия тега: у ответа нет тега.

**`make_template` — структура работы, а не документ** (И.18). Модель сочиняет
**строение**: какие разделы, что в них обязательно, чем они заполняются.
Заготовки блоков по этому строению собираются детерминированно, без модели.
Вид работы здесь не назван ни разу и назван быть не может — и с 2026-09-04 его
не называет и сценарий: работой может оказаться что угодно, от отчёта о
продажах до записки, и служба обязана собирать любую одинаково. Отсюда пара
полей у раздела: `kind` — как раздел называется в этой работе (свободное слово
от модели), `type` — чем он заполняется (перечень движка отчётов). Умолчания,
если вызывающему есть что предложить, приходят аргументом (`default=`), то есть
данными.

**`check_code` — статическая проверка сочинённого кода** (решение владельца
2026-08-31, К0). Код в архиве агент пишет сам, исполнять его мы не будем
никогда, и единственное, что можно честно обещать, — что он разбирается. Это
tree-sitter из `kyotsu`, тот же, которым `fragmos` строит схемы; отдельной
двери не было ни у кого, потому что тем нужен AST, а здесь нужен один ответ:
целый ли исходник. Знание о языках при этом остаётся в службе — сценарию оно
не принадлежит (решение 2026-09-04).

**`kadai_services` — сборка всех дверей.** Импортировать соседей позволено
только оркестратору (решение 2026-08-31), и направление здесь именно такое:
`orchestrator` знает про `kadai`, `kadai` про `orchestrator` — нет. Импорт стоит
внутри функции намеренно: сценарий — надстройка, и `import orchestrator` не
должен падать оттого, что в надстройке опечатка.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import hokoku
import kyotsu
import llm

from . import fill as fill_mod, live as live_mod, prompt as prompt_mod
from .errors import OrchestratorError

# Схема сочинённого строения работы. Полей ровно столько, сколько нужно, чтобы
# из ответа собрались заготовки блоков: заголовок раздела, как он называется
# (`kind` — свободное слово модели), чем заполняется (`type` — перечень движка) и
# обязателен ли. Пара `kind`/`type` — та же, что у `kadai.profile`: два ответа на
# «чем заполнен раздел» разошлись бы молча, и раздел, объявленный схемой, стал бы
# обычным текстом. Перечень типов берётся у движка (`hokoku.live.KINDS` без
# служебных), а не переписывается здесь: своя копия отстала бы от него молча.
# Ни одного слова про вид работы: его не знает ни служба, ни сценарий.
STRUCTURE_SCHEMA = {
    "type": "object",
    "properties": {
        "sections": {
            "type": "array", "minItems": 1,
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string",
                              "description": "заголовок раздела так, как он встанет в работу"},
                    "level": {"type": "integer", "minimum": 1, "maximum": 3,
                              "description": "1 — раздел, 2 — подраздел"},
                    "kind": {"type": "string",
                             "description": "вид раздела своими словами: чем он "
                                            "является в этой работе"},
                    "type": {"type": "string",
                             "enum": [k for k in hokoku.live.KINDS
                                      if k not in ("heading", "page_break", "text")],
                             "description": "чем раздел заполняется: текстом, "
                                            "листингом, таблицей, схемой"},
                    "required": {"type": "boolean",
                                 "description": "обязателен ли раздел в этой работе"},
                    "prompt": {"type": "string",
                               "description": "что именно писать в разделе, одной фразой"},
                },
                "required": ["title", "kind", "type"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["sections"],
    "additionalProperties": False,
}


@dataclass
class Answer:
    """Ответ на один вопрос вне тегов.

    Отдельный тип, а не голый словарь: у вопроса бывает исход «модель отказала»
    и «оборвалось по проводу», и словарь на них отвечал бы `None`, по которому
    не понять, спрашивать ли второй раз. `ok` означает «ответ есть и он по
    схеме»; всё остальное — в `problems`, в общей форме замечаний проекта.
    """

    run: object
    ok: bool = False
    value: dict | None = None
    text: str = ""
    problems: list = field(default_factory=list)
    usage: dict = field(default_factory=dict)
    stop: str = ""


def ask(project, question: str, *, endpoint: str, schema: dict | None = None,
        parts=(), chunks=(), data=(), run=None, max_tokens=None, effort=None,
        cancel=None) -> Answer:
    """Один вопрос модели вне тегов: схема ответа своя, версии тега не заводится.

    `question` — наш вопрос, нашими словами. Всё чужое — условие задачи,
    пожелания человека, куски материалов — едет `data=` и `chunks=`, то есть
    недоверенными кусками в рамке со случайной меткой прогона. Разница не
    косметическая: текст, приехавший вопросом, для модели указание, а текст в
    рамке — данные, и в чужом файле бывает написано «забудь предыдущие
    указания».

    `schema=None` — ответ словами, без схемы: он приходит в `text`. Так спрашивают
    то, что человек будет читать глазами, а не служба разбирать полями.

    `parts` — готовые куски вызывающего, если он собрал их сам; встают перед
    вопросом. `run` — прогон, если вопрос не первый: тогда несколько вопросов
    делят одну метку рамки и один кэшируемый префикс. Не передашь — заводится
    свой, и это дороже ровно на кэш.
    """
    own_run = run is None
    if own_run:
        run = project.start_run(level=1, endpoint=endpoint)
    built = prompt_mod.ask_parts(project, question, chunks=chunks, data=data,
                                 extra=list(parts))
    fill_mod._seal(project, run, built)

    limit = project.limit()
    meta = {"run": run.id, "level": 1, "ask": True}
    if schema is None:
        out = _ask_text(project, run, built, endpoint=endpoint, limit=limit, meta=meta,
                        max_tokens=max_tokens, effort=effort, cancel=cancel)
    else:
        result = llm.generate_object(
            endpoint, schema, built,
            **({} if max_tokens is None else {"max_tokens": max_tokens}),
            effort=effort, cancel=cancel, limit=limit, journal=project.journal(),
            frame_mark=run.mark, meta=meta)
        out = Answer(run=run, stop=result.stop, usage=llm.usage_of(result),
                     text=result.text or "")
        if result.ok and isinstance(result.value, dict):
            out.ok, out.value = True, result.value
        else:
            out.problems.append(fill_mod._problem("model_failed", None, fill_mod._why(result)))
    run.steps.append({"ask": question[:80], "ok": out.ok, "stop": out.stop})
    if own_run:
        project.finish_run(run, "done" if out.ok else "error")
    else:
        project.save_run(run)
    return out


def _ask_text(project, run, parts, *, endpoint, limit, meta, max_tokens, effort,
              cancel) -> Answer:
    """Вопрос без схемы: поток без схемы, текст копится, расход считает слой.

    Потоком, а не `generate_object` с выдуманной схемой-обёрткой: обёртка
    (`{"answer": …}`) заставила бы модель отвечать полем там, где спросили
    словами, и половину ответов пришлось бы вынимать из кавычек.
    """
    out = Answer(run=run)
    pieces: list[str] = []
    error = None
    stream = llm.stream_object(
        endpoint, None, parts,
        **({} if max_tokens is None else {"max_tokens": max_tokens}),
        effort=effort, cancel=cancel, limit=limit, journal=project.journal(),
        frame_mark=run.mark, meta=meta)
    try:
        for chunk in stream:
            if chunk.kind == "text":
                pieces.append(chunk.text or "")
            elif chunk.kind == "usage" and chunk.usage is not None:
                out.usage = {**chunk.usage.as_dict(), "raw": dict(chunk.raw or {})}
            elif chunk.kind == "stop":
                out.stop = chunk.stop or out.stop
            elif chunk.kind == "error" and chunk.error is not None:
                error = chunk.error
    except llm.LlmError as exc:
        error = exc
    out.text = "".join(pieces)
    if error is not None:
        out.problems.append(fill_mod._problem("stream_failed", None, str(error)))
    out.ok = bool(out.text.strip()) and error is None
    if not out.ok and error is None:
        out.problems.append(fill_mod._problem("model_failed", None,
                                              "модель не ответила ни словом"))
    return out


def make_template(project, structure=None, *, endpoint: str, task: str = "",
                  default=(), chunks=(), data=(), source: str = "agent",
                  before=(), run=None) -> list:
    """Строение работы → список блоков-заготовок в проекте.

    Вид работы не фиксирован (решение владельца 2026-09-04): строение сочиняется
    по условию и пожеланиям, а `default=` — список разделов-предложений, если
    вызывающему есть что предложить; модель видит их предложением, а не законом.
    Служба о видах работ не знает ни слова и знать не должна — и с 2026-09-04 их
    не знает никто: работой бывает что угодно, и палитра разделов, записанная
    где-либо в коде, была бы утверждением о том, чего мы не знаем.

    `structure=None` — строение сочиняет модель (`ask` по `STRUCTURE_SCHEMA`).
    Готовое строение (уже просеянное ситами сценария) передаётся аргументом, и
    тогда модель не зовётся вовсе: это же и есть путь «человек поправил
    структуру и велел продолжать».

    Из каждого раздела получаются два блока: заголовок и **заготовка** —
    место под содержимое со значением `None`. Пустым значением заготовку не
    выразить: пустое значение в отчёте — ошибка (решение 2026-08-29), и заведи
    мы его здесь, вся работа сразу оказалась бы полной битых блоков.

    `before` — список блоков, каким он был до пересборки (обычно
    `project.blocks()`; дверь сценария подставляет его сама). Он нужен ради
    одного: **правка человека переживает пересборку строения.** Без него
    повторный вызов переписывал список целиком, и написанное человеком исчезало
    молча — беда того же рода, что затёртое значение тега, только заметная не
    сразу, а на готовом отчёте.

    Как сопоставляются старое и новое, сказано в `_carry_over`: по заголовку
    раздела, потому что другого общего имени у разделов нет — ключи блоков
    выдаются заново. Переименованный человеком заголовок мы поэтому не узнаём, и
    его блоки уезжают в конец списка; об этом написано в пометке версии, а не
    умолчано.

    Возвращается записанный список блоков. Пишется он одной версией: строение —
    одна правка, и разрезать её на двадцать версий значило бы сделать «вернуть
    прежнее строение» перебором номеров.
    """
    if structure is None:
        answer = ask(project, _structure_request(task, default), endpoint=endpoint,
                     schema=STRUCTURE_SCHEMA, chunks=chunks, data=data, run=run)
        if not answer.ok:
            raise OrchestratorError(
                "строение работы не сочинилось: "
                + "; ".join(p.message for p in answer.problems))
        sections = answer.value.get("sections") or []
    else:
        sections = list(structure)
    before = list(before or ())
    свои = [r for r in before if r.get("source") in HUMAN_SOURCES
            and str(r.get("kind")) != "heading"]
    work = blocks_of(sections, taken=[r["key"] for r in свои])
    if not len(work):
        raise OrchestratorError("строение пусто: ни одного раздела — собирать нечего")
    work, перенесено, осиротели = _carry_over(project, work, before, свои)
    # `before` отдаётся и `records_of`: пометка `source` перенесённых блоков
    # приклеивается обратно по ключу — тому же, что был. Второго словаря
    # источников здесь не заводится, иначе их станет два и они разойдутся.
    project.set_blocks(live_mod.records_of(work, source=source, before=before),
                       source=source, note=_template_note(перенесено, осиротели))
    return project.blocks()


def _template_note(перенесено, осиротели) -> str:
    """Зачем была эта версия — словами. Потеря правки человека называется вслух."""
    note = "строение работы"
    if перенесено:
        note += f"; перенесено правок человека: {len(перенесено)}"
    if осиротели:
        note += ("; без своего раздела и потому в конце: "
                 + ", ".join(осиротели))
    return note


def blocks_of(sections, *, taken=()) -> hokoku.Work:
    """Разделы строения → список блоков: заголовок и место под содержимое.

    Принимаются и словари, и объекты с теми же полями (`kadai.profile.Section`):
    служба обязана быть полезна обеим сторонам, а различать их по типу значит
    завести здесь знание о чужом классе.

    Заголовок и заготовку делает `hokoku.live` (`heading`, `draft`), а не мы:
    заголовок — это markdown «## Название», по которому `render` ставит стиль
    Heading N и который находит поле оглавления, а место под текст — черновик с
    пометкой, потому что пустое значение движок отчётов считает ошибкой. Оба
    правила принадлежат движку, и знать их здесь вторично значило бы разойтись
    с ним молча.

    Ключи блоков придумывает служба (`hokoku.live.new_key`), а не сценарий и не
    модель: ключ — адрес, и два блока с одним адресом означают потерянный блок.

    `taken` — ключи, которые заняты и в этом списке ещё не стоят: так пересборка
    строения оставляет перенесённым правкам человека **их прежние ключи**.
    Прежний ключ здесь не украшение: по нему приклеивается обратно пометка
    `source`, и по нему же стоят ссылки `{ref:}` из соседних блоков человека.
    """
    work = hokoku.Work()
    taken = {hokoku.wire.norm_key(str(k)) for k in (taken or ())}
    for section in sections:
        # `kind` (как раздел называется в этой работе) здесь только принимается:
        # блоки строятся по `type`, а имя вида — дело сита вызывающего. Читать его
        # тут значило бы завести в службе второе мнение о том, чем раздел заполнен.
        raw = section if isinstance(section, dict) else {
            name: getattr(section, name, None)
            for name in ("key", "title", "kind", "type", "required", "prompt", "level")}
        title = str(raw.get("title") or "").strip()
        if not title:
            raise OrchestratorError("раздел без заголовка: назвать его нечем")
        kind = str(raw.get("type") or "markdown")
        if kind not in hokoku.live.KINDS or kind == "heading":
            raise OrchestratorError(
                f"раздел {title!r}: {kind!r} — не вид содержимого "
                f"({', '.join(k for k in hokoku.live.KINDS if k != 'heading')})")
        level = raw.get("level")
        level = int(level) if isinstance(level, int) and 1 <= level <= 6 else 1
        задание = str(raw.get("prompt") or "").strip()
        work = hokoku.live.insert(
            work, hokoku.live.block(_free_key(work, taken),
                                    hokoku.live.heading(level, title), label=title))
        # Задание раздела едет в черновик, а не только в метку: текстовый проход
        # читает его подсказкой (`text_slots` → `hint`), и без него модель, пишущая
        # весь текст разом, знает про блок только имя соседей.
        work = hokoku.live.insert(
            work, hokoku.live.block(_free_key(work, taken),
                                    _slot(kind, задание or title),
                                    label=задание or title))
    return work


# Кто написал блок так, что переписывать его нельзя. Тот же список, что у прохода
# текста (`live.write_texts`) и у сценария: разойдись он, пересборка строения
# сохраняла бы одно, а проход текста берёг другое.
HUMAN_SOURCES = ("manual", "file")


def _free_key(work: hokoku.Work, taken) -> str:
    """Свободный ключ блока с учётом того, что займут перенесённые правки.

    Своего счётчика ключей здесь не заводится: их придумывает
    `hokoku.live.new_key`, а он смотрит только на список, который строится.
    Перенесённые блоки в него ещё не встали, но их ключи заняты — два блока с
    одним адресом означают потерянный блок, — поэтому занятый ключ вставляется в
    список-пробник, и следующий спрашивается у того же `new_key`.
    """
    key = hokoku.live.new_key(work)
    пробник = work
    while key in taken:
        пробник = hokoku.live.insert(
            пробник, hokoku.live.block(key, hokoku.Text("занято")))
        key = hokoku.live.new_key(пробник)
    return key


def _carry_over(project, work: hokoku.Work, before, свои):
    """Перенести правки человека в пересобранное строение. → (список, перенесённые, осиротевшие).

    Сопоставляются **разделы**, а не блоки, и по заголовку: ключи блоков
    выдаются заново при каждой пересборке, и другого имени, общего у старого и
    нового строения, у раздела нет. Отсюда прямо следует, чего этот перенос не
    умеет: **переименованный заголовок мы не узнаём** — для нас это «раздел
    убрали и добавили другой», и молча посадить текст человека в раздел с другим
    названием было бы хуже потери: он бы его не искал.

    Заголовки не переносятся вовсе, даже поправленные человеком: заголовок — имя
    раздела, и он собирается из нового строения. Перенесённый заголовок стоял бы
    вторым рядом со своим.

    Место переносимого блока — конец его раздела. Если человек написал в разделе
    **текст**, заготовка под текст из этого раздела убирается: иначе проход
    текста написал бы в неё второй абзац про то же самое, и в отчёте оказалось
    бы два вступления подряд.

    Раздела не нашлось — блок встаёт в конец работы и называется в пометке
    версии. Выбросить его нельзя (это написанное человеком), а поставить
    наугад — тем более.
    """
    if not свои:
        return work, [], []
    старый = live_mod.work_of(project, before)
    перенесено, осиротели = [], []
    for заголовок, ключи in _human_sections(старый, {r["key"] for r in свои}).items():
        хвост = _section_tail(work, заголовок)
        if хвост is None:
            for key in ключи:
                work = hokoku.live.insert(work, старый.get(key))
                осиротели.append(key)
            continue
        if any(старый.get(k).kind in hokoku.live.TEXT_KINDS for k in ключи):
            work, хвост = _drop_slot(work, заголовок, хвост)
        for key in ключи:
            work = hokoku.live.insert(work, старый.get(key), after=хвост)
            хвост = key
            перенесено.append(key)
    return work, перенесено, осиротели


def _title(block) -> str:
    """Заголовок раздела так, как его сравнивают: без решётки, регистра и лишних пробелов."""
    return " ".join(block.text.lstrip("#").split()).casefold()


def _human_sections(work: hokoku.Work, ключи: set) -> dict:
    """Блоки человека по разделам: `{заголовок: [ключи по порядку]}`.

    Блоки до первого заголовка складываются под пустым именем — раздела у них
    нет, и найтись в новом строении им не по чему.
    """
    out: dict = {}
    заголовок = ""
    for b in work.blocks:
        if b.kind == "heading":
            заголовок = _title(b)
            continue
        if b.key in ключи:
            out.setdefault(заголовок, []).append(b.key)
    return out


def _section_tail(work: hokoku.Work, заголовок: str):
    """Ключ последнего блока раздела с таким заголовком. `None` — раздела нет."""
    хвост = None
    внутри = False
    for b in work.blocks:
        if b.kind == "heading":
            if внутри:
                break
            внутри = _title(b) == заголовок
            if внутри:
                хвост = b.key
            continue
        if внутри:
            хвост = b.key
    return хвост


def _drop_slot(work: hokoku.Work, заголовок: str, хвост: str):
    """Убрать из раздела заготовку под текст. → (список, новый хвост раздела).

    Заготовка узнаётся так же, как её узнаёт проход текста (`text_slots`):
    текстовый блок с пометкой черновика. Знать это правило вторым способом
    нельзя — разойдясь, мы убирали бы написанное.
    """
    места = {s["key"] for s in hokoku.live.text_slots(work)}
    внутри = False
    for b in work.blocks:
        if b.kind == "heading":
            if внутри:
                break
            внутри = _title(b) == заголовок
            continue
        if внутри and b.key in места:
            work = hokoku.live.remove(work, b.key)
            return work, _section_tail(work, заголовок)
    return work, хвост


def _slot(kind: str, hint: str):
    """Место под содержимое раздела: черновик для текста, пусто-значение для прочих.

    Для текста это `hokoku.live.draft` — блок, который проход текста узнаёт по
    пометке. Для таблицы, кода и схемы места под содержимое не бывает вовсе:
    пустая таблица — битое значение, и завести её значило бы сделать работу
    полной ошибок ещё до первого хода. Поэтому там встаёт черновик текстом: его
    заменит петля, вставив на это место настоящую таблицу или схему.
    """
    return hokoku.live.draft(hint if kind in hokoku.live.TEXT_KINDS
                             else f"{hint} (здесь будет {kind})")


def _structure_request(task: str, default) -> str:
    """Вопрос про строение работы. Умолчания сценария — предложением, не законом."""
    lines = [str(task).strip() or
             "Сочини строение работы по условию задачи и пожеланиям человека."]
    предложено = [str(s.get("title") if isinstance(s, dict) else getattr(s, "title", ""))
                  for s in (default or ())]
    предложено = [t for t in предложено if t.strip()]
    if предложено:
        lines.append("Обычное строение такой работы: " + "; ".join(предложено) + ". "
                     "Это предложение, а не закон: разделы, которых условие не "
                     "требует, не бери, недостающие добавь.")
    lines.append("Ответь одним объектом JSON: sections — список разделов по "
                 "порядку. У каждого раздела заголовок, вид раздела своими "
                 "словами (kind), чем он заполняется (type), обязателен ли он и "
                 "одна фраза о том, что в нём писать. "
                 "Текста разделов сейчас не пиши — его напишут потом.")
    return "\n".join(lines)


# ── статическая проверка сочинённого кода ────────────────────────────────────

# Языки, которые в проекте вообще разбираются, и их грамматики. Таблица одна:
# те же три языка знают `fragmos` и `uml_generator`, и заводить здесь четвёртый
# список значило бы обещать проверку языка, по которому потом не строится ни
# схема, ни диаграмма. Псевдонимы — потому что имя языка приходит из значения
# блока `code`, а его пишет модель: «py», «c#» и «c++» она напишет наверняка.
CODE_GRAMMARS = {
    "python": "python", "py": "python", "python3": "python",
    "cpp": "cpp", "c++": "cpp", "cxx": "cpp", "cc": "cpp", "hpp": "cpp",
    "csharp": "c_sharp", "c#": "c_sharp", "cs": "c_sharp", "c_sharp": "c_sharp",
}

# Сколько мест разбора показываем. Обрывок исходника даёт ошибку почти в каждой
# строке, и весь этот список человеку не нужен: чинить он будет первую.
MAX_CODE_NOTICES = 20

# Сколько знаков исходника цитируем в замечании. Без цитаты «строка 12» ищется
# глазами по листингу, с целой строкой — уезжает в отчёт чужой длины.
CODE_SNIPPET = 60


def check_code(text, lang: str = "", *, name: str = "") -> list:
    """Разбирается ли этот исходник. → список `kyotsu.Notice`; пусто — разбирается.

    Решение владельца 2026-08-31 (К0): **код проверяется статически и никогда не
    исполняется**. Здесь это ровно tree-sitter: грамматика разбирает текст, не
    запуская его, и находит то, что от разбора и ждут, — обрывки и
    синтаксический мусор. На вопрос «верно ли работает решение» она не отвечает,
    и в архиве это написано дословно (`kadai.archive.NOT_RUN`).

    Отдельной двери у этой проверки не было ни у кого, хотя tree-sitter стоит в
    `kyotsu` и зовётся из `fragmos`: тем нужен AST, а здесь нужен один ответ —
    целый ли исходник. Заводить это знание в `kadai` нельзя (решение
    2026-09-04: знание о языках сценарию не принадлежит), поэтому дверь тут.

    Три исхода, и все три — замечание, а не исключение: их показывают человеку и
    кладут в архив рядом с кодом, а для этого нужны все сразу.

    * **пусто** — `error`: пустой листинг в отчёте это дырка, которую видно
      только глазами, и никакая грамматика её не назовёт;
    * **язык не наш** — `warning`: код уедет в архив непроверенным, и молчать об
      этом нельзя — архив обещает статически проверенный код;
    * **не разбирается** — `error` на каждое место (`ERROR` и пропущенный узел),
      с номером строки: без номера «где-то не так» ищется перечитыванием.
    """
    text = "" if text is None else str(text)
    where = str(name) or None
    if not text.strip():
        return [kyotsu.Notice(
            module="orchestrator", level="error", code="empty_code", file=where,
            message="листинг пуст: в отчёт уехал бы блок кода без кода")]
    grammar = CODE_GRAMMARS.get(str(lang or "").strip().lower())
    if grammar is None:
        назван = f"{lang!r}" if str(lang or "").strip() else "не назван"
        return [kyotsu.Notice(
            module="orchestrator", level="warning", code="unknown_language", file=where,
            message=f"язык листинга {назван}: разбираются только "
                    f"{', '.join(sorted(set(CODE_GRAMMARS.values())))}, "
                    "и этот код уедет в архив непроверенным")]
    root = kyotsu.get_parser(grammar).parse(text.encode("utf-8")).root_node
    if not root.has_error:
        return []
    out: list = []
    _bad_nodes(root, out)
    return [_code_notice(n, grammar, where) for n in out[:MAX_CODE_NOTICES]]


def _bad_nodes(node, out: list) -> None:
    """Узлы `ERROR` и пропущенные узлы, сверху вниз и слева направо.

    Внутрь найденного не спускаемся: дети ошибочного узла — та же одна ошибка,
    разложенная на слова, и показывать её человеку двадцатью строками значит
    спрятать вторую настоящую ошибку под первой.
    """
    if node.type == "ERROR" or node.is_missing:
        out.append(node)
        return
    if not node.has_error:
        return
    for child in node.children:
        if len(out) > MAX_CODE_NOTICES:
            return
        _bad_nodes(child, out)


def _code_notice(node, grammar: str, where: str | None) -> "kyotsu.Notice":
    line = int(node.start_point[0]) + 1
    if node.is_missing:
        message = (f"не хватает {node.type!r}: исходник обрывается или "
                   f"в нём не закрыта скобка")
    else:
        кусок = " ".join(node.text.decode("utf-8", "replace").split())
        if len(кусок) > CODE_SNIPPET:
            кусок = кусок[:CODE_SNIPPET - 1] + "…"
        message = f"не разбирается как {grammar}: «{кусок}»" if кусок else \
                  f"не разбирается как {grammar}"
    return kyotsu.Notice(module="orchestrator", level="error", code="syntax_error",
                         message=f"строка {line}: {message}", file=where, line=line)


# ── сборка дверей для сценария ───────────────────────────────────────────────

def kadai_services(project, *, endpoint: str, **defaults):
    """Все двери сценария одним объектом: `kadai.seams.Services`.

    Двери приходят функциями от одного проекта и одного endpoint'а — сценарию
    не из чего собрать второй набор и нечем узнать, откуда взялся первый. Это и
    есть весь разрез: `kadai` держит порядок стадий, служба — состояние, модель
    и файлы.

    `defaults` — умолчания, которые сценарий не называет сам (например
    `max_steps`): они дописываются в вызов дверей, и менять их сценарию не
    надо, а иногда и нельзя.

    Импорт `kadai` стоит внутри функции намеренно: `orchestrator` полон и без
    сценария, а `import orchestrator` не должен падать оттого, что в надстройке
    над ним опечатка. Направление импорта при этом единственно возможное —
    соседей импортирует только оркестратор (решение 2026-08-31).
    """
    from kadai.seams import Services

    def ask_door(*args, **kwargs):
        return ask(project, *args, endpoint=kwargs.pop("endpoint", endpoint), **kwargs)

    def template_door(*args, **kwargs):
        # `before` подставляется дверью, а не сценарием: список блоков —
        # состояние проекта, а сценарий про проект знает только имена методов.
        # Умолчание здесь безопасно по построению: на первой сборке блоков ещё
        # нет, и переносить нечего.
        kwargs.setdefault("before", project.blocks())
        return make_template(project, *args, endpoint=kwargs.pop("endpoint", endpoint),
                             **kwargs)

    def solve_door(*args, **kwargs):
        for name, value in defaults.items():
            kwargs.setdefault(name, value)
        return live_mod.solve(project, *args, endpoint=kwargs.pop("endpoint", endpoint),
                              **kwargs)

    def texts_door(**kwargs):
        return live_mod.write_texts(project, endpoint=kwargs.pop("endpoint", endpoint),
                                    **kwargs)

    # `check_code` приходит функцией как есть: ни проекта, ни endpoint'а ей не
    # нужно — она разбирает текст tree-sitter'ом и ничего не пишет. Обёртка ради
    # единообразия была бы обёрткой, которая ничего не делает.
    return Services(project=project, ask=ask_door, make_template=template_door,
                    solve=solve_door,
                    extra={"write_texts": texts_door, "check_code": check_code})


__all__ = ["Answer", "STRUCTURE_SCHEMA", "ask", "make_template", "blocks_of",
           "check_code", "CODE_GRAMMARS", "HUMAN_SOURCES", "kadai_services"]
