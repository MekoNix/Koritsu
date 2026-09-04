"""
live — живой режим со стороны службы: хранение списка блоков, петля и текст.

Второй способ работы (решение 2026-09-03): шаблона нет вовсе, работа — это
упорядоченный список именованных блоков, документ — его сборка. Сам список и всё,
что с ним делают, живёт в `hokoku.live` (`Work`, `Block`, `insert`/`replace`/
`remove`/`move`, объявления инструментов и `call_tool`, `texts_schema`,
`fill_texts`, `assemble`). Здесь — то, чего у чистого движка отчётов нет и быть
не должно: диск, версии, `source`, вызов модели, журнал расхода и лимит.

Разрез проходит ровно по этой черте, и стоит назвать его прямо:

* **Список правит `hokoku.live`.** Ни одной своей вставки, перестановки и своего
  набора инструментов здесь нет. Вторая реализация тех же операций разошлась бы
  с первой молча — а разойтись ей есть в чём: ключи, ссылки `{ref:}`, порядок.
* **Помнит список проект.** `Project.set_blocks` — единственная точка записи, как
  `set_value` для тегов; версия пишется на каждую правку, и «вернуть как было»
  работает без единой копии на стороне вызывающего.
* **Кто написал — вопрос хранилища.** У `hokoku.live.Block` пометки `source` нет
  и не нужно: движку отчётов всё равно, чья рука. Проходу текста — не всё равно
  (написанное человеком не переписывается), поэтому пометка живёт в записи блока
  на диске и приклеивается обратно по ключу.
* **Всё ценное сохраняется в момент производства.** Петля историю не сохраняет
  (`llm/loop.py`), значит каждая правка списка пишет новую версию сразу. Обрыв на
  пятом ходу стоит одного хода, а не прогона; плата — версия на вызов
  инструмента, и она честно мала: версия списка меряется килобайтами.
* **Мутируют два инструмента, а не один.** Кроме правки списка, живой режим
  умеет `put_source` — модель кладёт сочинённый ею исходник в материалы работы.
  Заведён он не для удобства: `make_flowchart` и обе диаграммы адресуют материал
  идентификатором, а код, написанный моделью, лежал блоком, — построить схему по
  своему же коду ей было нечем. Дверь для файла при этом одна и та же
  (`Project.add_material`), второго пути приёма не заводится.

Связный текст петлёй **не пишется** (решение владельца 2026-09-04): скелет и
нетекстовое собирает `solve`, весь текст пишется одним проходом `write_texts` по
готовому списку, видя соседей. Абзацы, написанные по одному, разойдутся между
собой, и увидит это тот, кто прочтёт работу целиком.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import hokoku
import llm
from llm.model import Part

from . import agent as agent_mod, fill as fill_mod, prompt as prompt_mod, \
    tools as tools_mod
from .errors import OrchestratorError
from .tools import ToolError

# Сколько ходов живого режима позволено одному прогону (решение владельца
# 2026-09-04). Своё умолчание, а не унаследованное от `llm.Limits` (12): там оно
# про один вопрос с инструментами, а здесь агент собирает работу целиком —
# заголовки, код, таблицы, схемы, — и дюжины ходов на это не хватает. Потолок
# нужен всё равно: петля, которая вставляет и вставляет, иначе платит вечно.
MAX_STEPS = 50

# Инструмент, которого нет у шаблонного пути: модель кладёт **свой** исходник в
# материалы работы. Заведён он ровно ради связки «пишет код и рисует по нему
# схему»: `make_flowchart` адресует материал идентификатором, а сочинённый
# моделью код лежал блоком работы — построить схему по своему же коду ей было
# нечем, и схемы получались только по тому, что принёс человек.
PUT_SOURCE = "put_source"

# Расширение имени по языку. Не таблица языков (её знает `check_code`), а
# ровно то, по чему `materials` узнаёт текстовый материал, а человек — файл в
# распакованной папке. Незнакомый язык — `.txt`, а не догадка.
SOURCE_EXT = {"python": ".py", "py": ".py", "cpp": ".cpp", "c++": ".cpp",
              "c": ".c", "csharp": ".cs", "c#": ".cs", "cs": ".cs",
              "java": ".java", "javascript": ".js", "sql": ".sql", "bash": ".sh"}

# Потолок имени материала: имя приходит от модели и показывается человеку.
MAX_NAME = 120

# Имена инструментов живого режима: чтение материалов и схемы (общие с уровнем 3
# шаблонного пути), свой `put_source` и правка списка (объявляет `hokoku.live`).
# Своего списка имён для чужих объявлений здесь не заводится — он бы разошёлся с
# ними на первой правке.
LIVE_TOOL_NAMES = tools_mod.MATERIAL_TOOLS + (PUT_SOURCE,) + hokoku.live.TOOL_NAMES


# ── перевод: записи на диске ↔ список блоков `hokoku` ────────────────────────

def work_of(project, blocks=None) -> hokoku.Work:
    """Записи блоков проекта → `hokoku.live.Work` с типизированными значениями.

    Значение разбирается тем же `wire.value_from_json`, что и значение тега, и с
    тем же `resolve_artifact`: артефакт, которого нет, обязан умереть здесь, а не
    в собранном документе.

    Битая запись не выбрасывается молча и не роняет всё: она уже лежит в проекте,
    чинить её — работа человека, а вот делать вид, что блока не было, нельзя —
    список сдвинется, и ссылки уедут. Поэтому отказ с именем блока.
    """
    items = project.blocks() if blocks is None else list(blocks)
    out = []
    for record in items:
        try:
            value = hokoku.value_from_json(record["value"],
                                           resolve_artifact=project.resolve_artifact)
        except hokoku.WireError as exc:
            raise OrchestratorError(
                f"блок {record.get('key')!r} не читается: {exc.detail}") from None
        out.append(hokoku.live.block(record["key"], value,
                                     label=record.get("label") or ""))
    return hokoku.Work(tuple(out))


def records_of(work, *, source: str, before=()) -> list:
    """`Work` → записи для `Project.set_blocks`, с пометкой источника.

    Пометка прежних блоков сохраняется по ключу: правка одного блока не делает
    моделью весь список, а без этого проход текста затирал бы написанное
    человеком — ровно та беда, ради которой `source` и заводился у тегов.
    """
    прежние = {r["key"]: r.get("source") for r in before}
    return [{"key": b.key, "kind": b.kind, "label": b.label,
             "value": hokoku.value_to_json(b.value),
             "source": прежние.get(b.key) or source}
            for b in work.blocks]


def as_tools(declarations) -> list[llm.Tool]:
    """Объявления `hokoku.live.LiveTool` → `llm.Tool`. Мост, и ничего больше.

    Мост нужен потому, что `hokoku` про слой моделей не знает и знать не должен:
    он отдаёт имя, описание и схему, а `strict`, объявление поставщику и вся
    механика вызова — дело слоя. Переписывать объявления здесь нельзя: тогда
    модель получила бы одно описание инструмента, а работал бы другой.
    """
    return [llm.Tool(name=t.name, description=t.description, schema=t.schema)
            for t in declarations]


def source_tool() -> llm.Tool:
    """Объявление `put_source`: модель кладёт сочинённый ею исходник материалом.

    Описание написано по образцу остальных (`tools.material_tools`) и говорит
    модели три вещи, без которых инструмент зовут неправильно: **путей он не
    принимает** (имя нужно человеку, адресом служит возвращённый
    идентификатор), **код не выполняется** и **листинг в работу ставится
    отдельно** блоком `code`. Последнее не придирка: положив исходник и решив,
    что он уже в работе, модель отдала бы отчёт без листинга.
    """
    return llm.Tool(name=PUT_SOURCE, description=(
        "Положить сочинённый тобой исходник в материалы работы. Возвращает "
        "идентификатор материала — по нему строятся схемы (make_flowchart, "
        "make_class_diagram, make_object_diagram) и его же читает read_material. "
        "Код НЕ выполняется: его только разбирают. Путей инструмент не "
        "принимает: имя нужно человеку, чтобы узнать файл, а адресом служит "
        f"идентификатор. Больше {tools_mod.MAX_SOURCE_CHARS} знаков за раз не "
        "берёт. Сам листинг в работу этот инструмент НЕ ставит — вставь его "
        "блоком code отдельно."),
        schema=_obj({
            "name": {"type": "string",
                     "description": "имя файла, например «сортировка.py»; "
                                    "путей и разделителей не принимает"},
            "lang": {"type": "string",
                     "description": "язык исходника: python, cpp, csharp"},
            "text": {"type": "string", "description": "сам исходник"}},
            required=["name", "lang", "text"]))


def live_tools() -> list[llm.Tool]:
    """Весь набор живого режима: материалы, свой исходник и правка списка блоков.

    Порядок постоянен и совпадает с `LIVE_TOOL_NAMES`: список едет в каждом
    запросе прогона и стоит в кэшируемом префиксе, а меняющийся набор означал бы
    промах мимо кэша на каждом ходу.
    """
    return [*tools_mod.material_tools(), source_tool(), *as_tools(hokoku.live_tools())]


def _obj(props: dict, required=()) -> dict:
    return {"type": "object", "properties": props, "required": list(required),
            "additionalProperties": False}


# ── диспетчер живого режима ──────────────────────────────────────────────────

class LiveBox(tools_mod.ToolBox):
    """Инструменты живого режима поверх той же механики, что у уровня 3.

    Наследование, а не копия: чтение материалов и построение схем — это ровно те
    же `_list_materials`, `_read_material`, `_make_flowchart` и диаграммы, с той
    же проверкой идентификаторов, тем же переводом чужих исключений в ответ
    модели и той же записью хода прогона на диск. Отличается только то, куда
    ложится произведённое: там значение тега, здесь блок списка.

    Правку списка целиком делает `hokoku.live.call_tool`: он чистый — берёт
    список и отдаёт новый, — а записывает новый список и заводит версию этот
    класс. Тегов у живого режима нет вовсе, поэтому `set_tag` и `preview` сюда
    не попадают: манифеста нет, шаблона нет, и «поставить значение тега»
    отвечать нечем.
    """

    def __init__(self, project, run, *, parts, work=None, note: str = "",
                 source: str = "agent"):
        super().__init__(project, run, parts=parts)
        self.records = project.blocks()
        self.work = work_of(project, self.records) if work is None else work
        self.source = source
        self.note = note
        self.version = None                 # шапка последней записанной версии
        self.changed: list = []             # что менялось, по порядку
        self._handlers = {
            **{name: self._handlers[name] for name in tools_mod.MATERIAL_TOOLS},
            PUT_SOURCE: self._put_source,
            **{name: self._block_tool for name in hokoku.live.TOOL_NAMES},
        }

    def _put_source(self, args: dict) -> dict:
        """Сочинённый моделью исходник → материал проекта. → идентификатор и объём.

        Дверь для файла у проекта одна (`Project.add_material`), и этот
        инструмент идёт в неё же: второй путь приёма означал бы второй набор
        правил про проверку недоверенного содержимого и про то, что материал
        адресуется содержимым, а не именем.

        Материал, а не блок работы, потому что схемы строятся по материалам:
        `make_flowchart` и обе диаграммы принимают идентификатор. Положив код
        блоком, модель не смогла бы построить по нему схему — ровно та дырка,
        ради которой инструмент и заведён.

        Тот же исходник, положенный дважды, — тот же материал: идентификатор
        считается по содержимому, и повторный ход не плодит мусора и не стоит
        разбора.
        """
        text = args.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ToolError("empty_source",
                            "text — сам исходник строкой, и пустым он не бывает: "
                            "пустой материал схемы не даст")
        if len(text) > tools_mod.MAX_SOURCE_CHARS:
            raise ToolError("too_big",
                            f"в исходнике {len(text)} знаков, потолок "
                            f"{tools_mod.MAX_SOURCE_CHARS}: разбей его на файлы")
        name = _source_name(args.get("name"), args.get("lang"))
        material = self.project.add_material(text.encode("utf-8"), name, do_ocr=False)
        return {"material": material.id, "name": material.name, "chars": len(text),
                "note": "схему по нему строят make_flowchart и диаграммы; сам "
                        "листинг поставь в работу блоком code"}

    def _block_tool(self, args: dict) -> dict:
        """Любой инструмент списка — через `hokoku.live.call_tool`.

        Один обработчик на все пять, потому что различать их здесь нечем и
        незачем: имя решает чужой диспетчер, а наше дело — записать то, что он
        вернул. Имя берётся из вызова, а не из аргументов: `ToolBox.__call__`
        уже выбрал обработчик по нему.
        """
        name = self._current
        try:
            work, answer = hokoku.call_tool(self.work, name, args,
                                            resolve_artifact=self.project.resolve_artifact)
        except hokoku.live.LiveError as exc:
            # Беда движка — такая же чинимая беда для модели, как наша: код и
            # текст у неё уже готовы (`LiveError.payload`), и переписывать их
            # значило бы объяснять модели одно и то же двумя разными словами.
            raise ToolError(exc.payload.get("error", "rejected"),
                            exc.payload.get("message", str(exc)),
                            **{k: v for k, v in exc.payload.items()
                               if k not in ("error", "message")}) from None
        потолок = hokoku.report.HARD_LIMITS["max_values"]
        if len(work) > потолок:
            # Потолок блоков один на службу и на движок отчётов (решение
            # владельца 2026-09-04): свой, вдвое меньший, означал бы, что список
            # из 700 блоков петлёй не собрать, а руками — можно, и объяснить эту
            # разницу человеку было бы нечем.
            raise ToolError("too_many",
                            f"в работе было бы {len(work)} блоков, потолок {потолок}")
        if list(work.keys()) != list(self.work.keys()) or work.blocks != self.work.blocks:
            self._write(work, _note_of(name, answer))
            answer = {**answer, "version": self.version.n}
        return answer

    def __call__(self, call):
        """Тот же диспетчер, но с памятью об имени: его спрашивает `_block_tool`."""
        self._current = call.name
        return super().__call__(call)

    def _write(self, work, note: str) -> None:
        """Новый список — на диск сразу. Прогон обрывается, сделанное остаётся."""
        records = records_of(work, source=self.source, before=self.records)
        self.version = self.project.set_blocks(
            records, source=self.source, run=self.run.id,
            note=f"{self.note}: {note}" if self.note else note)
        self.work, self.records = work, records
        self.changed.append(note)


def _source_name(raw, lang) -> str:
    """Имя файла для сочинённого исходника или отказ. Разделителей не пропускает.

    Проверка, а не тихая подчистка: имя пишет модель, и подчищенное имя — это
    другое имя, о котором ей не сказали. Путь при этом до хранилища всё равно не
    доехал бы (`Store` кладёт материал в папку по идентификатору), но обещание
    «путей ни в одном аргументе» проверяется на входе, а не внутри чужого пакета.

    Расширение дописывается по языку, если его нет: по нему `materials` узнаёт
    текстовый материал, а человек — файл в распакованной папке.
    """
    name = str(raw or "").strip()
    if not name:
        raise ToolError("bad_name",
                        "name — имя файла, по которому человек узнает исходник")
    плохо = [c for c in name if c in "/\\:" or ord(c) < 32 or ord(c) == 127]
    if плохо or ".." in name:
        raise ToolError("bad_name",
                        f"{name!r} — не имя файла: путей инструмент не принимает, "
                        "имя одним звеном, без «/», «\\», «:» и «..»")
    if len(name) > MAX_NAME:
        raise ToolError("bad_name", f"имя длиннее {MAX_NAME} знаков")
    if "." not in name:
        name += SOURCE_EXT.get(str(lang or "").strip().lower(), ".txt")
    return name


def _note_of(tool: str, answer: dict) -> str:
    """Зачем была эта версия — словами, из ответа инструмента.

    Без такой строки история списка — столбик номеров, по которому нельзя
    выбрать, куда возвращаться; а выбор возврата — единственное, ради чего
    живой режим держит список, а не правит документ на месте.
    """
    key = answer.get("key") or answer.get("removed") or answer.get("moved") or ""
    слова = {"insert_block": "вставлен блок", "replace_block": "переписан блок",
             "remove_block": "убран блок", "move_block": "переставлен блок"}
    return f"{слова.get(tool, tool)} {key}".strip()


# ── уровень 3 живого режима ──────────────────────────────────────────────────

@dataclass
class LiveResult:
    """Итог прогона живого режима. `ok` — прогон дошёл до конца.

    Как и у уровней 1–3 шаблонного пути, «дошёл до конца» и «работа готова» —
    разные утверждения: прогон, упёршийся в потолок ходов, оставил список на
    диске, и вставленное вставлено, — но закончить его модель не успела.
    """

    run: object
    blocks: list = field(default_factory=list)
    version: object = None
    changed: list = field(default_factory=list)
    problems: list = field(default_factory=list)
    usage: dict = field(default_factory=dict)
    steps: int = 0
    calls: int = 0
    text: str = ""
    stop: str = ""
    outcome: str = ""
    ok: bool = False


def solve(project, task: str, *, endpoint: str, tools=None, chunks=(), data=(),
          max_steps=None, max_units=None, max_tokens=None, effort=None,
          cancel=None, note: str = "") -> LiveResult:
    """Уровень 3 живого режима: агент собирает работу блоками.

    Порядок тот же, что у `fill_agent`, и переставляться не должен: ворота
    операторского канала → прогон → раскладка → метка рамки → петля. Ворота
    стоят до первого вызова, потому что отказ после пятого хода стоил бы денег
    за пять ходов и ничего бы не изменил.

    `task` — что нужно сделать, словами службы. Условие задачи и пожелания
    человека едут не сюда, а `data=` — недоверенными кусками в рамке: их писали
    не мы, и указанием для модели они быть не могут.

    Связный текст здесь не пишется (решение владельца 2026-09-04) — это отдельный
    проход `write_texts` по готовому списку. Здесь собирается скелет и то, чего
    текстом не написать: заголовки, схемы, код, таблицы.

    `max_steps=None` — потолок ходов живого режима `MAX_STEPS` (50, решение
    владельца 2026-09-04), а не умолчание среднего слоя: собрать работу целиком
    за дюжину ходов нельзя, и прогон обрывался бы на середине штатно.
    """
    extra_flags, gate_problems = tools_mod.operator_channel_gate(endpoint)

    run = project.start_run(level=3, endpoint=endpoint)
    parts = [prompt_mod.live_rules_part()]
    parts.extend(prompt_mod.file_parts(project.store(), chunks=chunks))
    parts.extend(prompt_mod.data_parts(data))
    outline = prompt_mod.blocks_part(project)
    if outline is not None:
        parts.append(outline)
    parts.append(Part(role="request", stable=False, text=_solve_request(task)))
    fill_mod._seal(project, run, parts)

    box = LiveBox(project, run, parts=parts,
                  note=note or ("проверить: нет операторского канала"
                                if extra_flags else ""))
    limits = llm.Limits(
        max_steps=int(max_steps or MAX_STEPS), max_units=max_units,
        **({} if max_tokens is None else {"max_tokens_per_call": max_tokens}))
    result = llm.run_tools(endpoint, list(tools if tools is not None else live_tools()),
                           parts, box, limits=limits, cancel=cancel,
                           journal=project.journal(), meta={"run": run.id, "level": 3},
                           effort=effort, limit=project.limit(), frame_mark=run.mark)

    # Проверка списка целиком — та же, что стоит перед сборкой документа
    # (`hokoku.live.validate_work`), и здесь она нужна именно после прогона:
    # ссылка `{ref:}` на убранный блок и пустое значение видны только на всём
    # списке сразу, а модель правит его по одному блоку.
    out = LiveResult(run=run, blocks=project.blocks(), version=box.version,
                     changed=list(box.changed),
                     problems=[*gate_problems, *box.problems,
                               *hokoku.live.validate_work(box.work)],
                     usage=llm.usage_of(result), steps=result.attempts,
                     calls=box.calls, text=result.text or "", stop=result.stop)
    if result.error is not None:
        out.problems.append(fill_mod._problem("run_failed", None, str(result.error)))
    for code, message in agent_mod._degraded_words(limits.max_steps).items():
        if code in result.degraded:
            out.problems.append(fill_mod._problem(code, None, message, "info"))
    out.outcome = agent_mod._outcome(result, out.changed)
    out.ok = out.outcome == "done"
    project.finish_run(run, out.outcome)
    return out


def _solve_request(task: str) -> str:
    """Хвост запроса живого режима: что делать и чем. После брейкпойнта кэша."""
    return (f"{str(task).strip()}\n"
            "Работай инструментами. Материалы читаются по идентификатору "
            "(list_materials, read_material), свой сочинённый исходник кладётся "
            "в материалы put_source, схемы строятся из исходников "
            "(make_flowchart, make_class_diagram, make_object_diagram), блоки "
            "правятся insert_block, replace_block, remove_block, move_block, "
            "состав работы показывает list_blocks.\n"
            "Схема по своему же коду строится в два хода: сначала put_source, "
            "потом make_flowchart по возвращённому идентификатору. Сам листинг "
            "put_source в работу не ставит — вставь его блоком code.\n"
            "Каждый готовый блок вставляй сразу, не копи их до конца: "
            "вставленное сохранено и обрыв его не отменит.\n"
            "Ошибка инструмента — не конец работы: в ответе написано, что не так, "
            "поправь вызов и повтори.\n"
            "Ходов немного. Закончив, перестань звать инструменты и напиши "
            "короткий итог словами: что сделано и что осталось человеку.")


# ── текст одним проходом ─────────────────────────────────────────────────────

@dataclass
class TextsResult:
    """Итог прохода текста. `filled` — блоки, в которые текст лёг."""

    run: object
    filled: list = field(default_factory=list)
    version: object = None
    problems: list = field(default_factory=list)
    usage: dict = field(default_factory=dict)
    stop: str = ""
    ok: bool = False


def write_texts(project, *, endpoint: str, chunks=(), data=(), max_tokens=None,
                effort=None, cancel=None, overwrite: bool = False) -> TextsResult:
    """Весь связный текст работы — одним вызовом по готовому списку блоков.

    Решение владельца 2026-09-04, и довод посчитан заранее: блоки связаны так
    же, как теги (введение ссылается на цель, вывод — на замеры), и текст,
    написанный по одному блоку в петле, будет связным по отдельности и
    рассогласованным вместе. Плюс расход: петля с историей — самый дорогой
    способ написать абзац.

    Что просить и по какой схеме, решает `hokoku.live.texts_schema`: место под
    текст — пустой или черновой текстовый блок, и знать это правило дважды
    нельзя. Наше здесь другое: блок, чьё содержимое поставил человек (`source` =
    `manual` или `file`), из просимых **выбрасывается** — пропажу своего абзаца
    человек обнаружит в готовом отчёте, и это то же правило, что у тегов.
    """
    records = project.blocks()
    чужие = {r["key"] for r in records
             if r.get("source") in ("manual", "file")} if not overwrite else set()
    work = work_of(project, records)
    try:
        schema = hokoku.live.texts_schema(work)
    except hokoku.live.LiveError as exc:
        raise OrchestratorError(str(exc)) from None
    for key in чужие:
        schema["properties"].pop(key, None)
    schema["required"] = list(schema["properties"])
    if not schema["properties"]:
        raise OrchestratorError(
            "нечего писать: все пустые текстовые блоки написаны не моделью. "
            "Переписать — overwrite=True")

    run = project.start_run(level=2, endpoint=endpoint)
    parts = [prompt_mod.ask_rules_part()]
    parts.extend(prompt_mod.file_parts(project.store(), chunks=chunks))
    parts.extend(prompt_mod.data_parts(data))
    список = prompt_mod.blocks_part(project, texts=True, blocks=records)
    if список is not None:
        parts.append(список)
    parts.append(Part(role="request", stable=False, text=(
        "Напиши связный текст работы по этому списку блоков. Заполни блоки: "
        + ", ".join(f"[{k}]" for k in schema["properties"]) + ".\n"
        "Ответь ОДНИМ объектом JSON: ключ блока → текст в markdown. Ключи — "
        "ровно перечисленные, лишних не добавляй.\n"
        "Пиши, видя соседей: заголовки говорят, о чём раздел, а уже написанные "
        "блоки — что в работе уже сказано; не повторяй их и не противоречь им.\n"
        "Ссылка на рисунок, таблицу или формулу — только {ref:ключ}: номера "
        "ставит сборщик.")))
    fill_mod._seal(project, run, parts)

    result = llm.generate_object(
        endpoint, schema, parts,
        **({} if max_tokens is None else {"max_tokens": max_tokens}),
        effort=effort, cancel=cancel, limit=project.limit(),
        journal=project.journal(), frame_mark=run.mark,
        meta={"run": run.id, "level": 2, "texts": len(schema["properties"])})

    out = TextsResult(run=run, usage=llm.usage_of(result), stop=result.stop)
    if not result.ok or not isinstance(result.value, dict):
        out.problems.append(fill_mod._problem("model_failed", None, fill_mod._why(result)))
        project.finish_run(run, "error")
        return out

    тексты = {}
    for key in schema["properties"]:
        text = result.value.get(key)
        if not isinstance(text, str) or not text.strip():
            out.problems.append(fill_mod._problem(
                "not_returned", key, f"модель не написала текст блока {key!r}", "info"))
            continue
        тексты[key] = text
    if тексты:
        try:
            work = hokoku.live.fill_texts(work, тексты)
        except hokoku.live.LiveError as exc:
            out.problems.append(fill_mod._problem("bad_texts", None, str(exc)))
            project.finish_run(run, "error")
            return out
        out.filled = list(тексты)
        # Одна версия на весь проход, а не по версии на блок: проход и есть одна
        # правка — «текст написан», — и разрезать её на двадцать версий значило
        # бы сделать «вернуть как было» перебором двадцати номеров.
        out.version = project.set_blocks(
            records_of(work, source="agent", before=records), source="agent", run=run.id,
            note=f"текст одним проходом: {len(out.filled)} блоков")
    out.ok = bool(out.filled) and not [p for p in out.problems if p.level == "error"]
    project.finish_run(run, "done" if out.ok else "interrupted")
    return out


__all__ = ["LiveBox", "LiveResult", "TextsResult", "solve", "write_texts",
           "live_tools", "source_tool", "as_tools", "work_of", "records_of",
           "LIVE_TOOL_NAMES", "MAX_STEPS", "PUT_SOURCE", "SOURCE_EXT"]
