"""
tools — инструменты агента (уровень 3) поверх той механики, что уже есть.

Уровень 3 отличается от первых двух одним: значения ставит не разбор ответа, а
сама модель по ходу работы — и потому ровно здесь легче всего завести второй
путь записи. Не заведён: **`set_tag` — это `fill._accept`**, тот самый общий
хвост уровней 1 и 2, а он кончается `Project.set_value`. Второй путь означал бы
второй набор правил про версии, `source` и защиту правки человека, и разошлись
бы они молча — заметно это стало бы на отчёте, где пропал абзац, написанный
студентом.

Из этого же выведен и весь набор, а не придуман:

* **Путей нет ни у одного аргумента.** Материал адресуется идентификатором
  (первые 16 знаков sha256 от содержимого), схема — идентификатором артефакта.
  Имя файла подделывается содержимым, идентификатор — нет. Форма
  идентификатора проверяется до обращения к хранилищу: `Store` складывает из
  него путь, и `../` обязан умереть на входе, а не внутри.
* **Мутирует только `set_tag`.** Остальные читают и производят артефакты.
* **Пользовательский код не выполняется.** `make_flowchart` и диаграммы — это
  `fragmos.generate_xml` и `uml_generator`, они разбирают исходник tree-sitter'ом.
  Ни `exec`, ни подпроцесса, ни поиска в сети здесь нет и не будет.
* **Список инструментов постоянен на весь прогон.** Недоступность приходит
  ответом `is_error`, а не исчезнувшим инструментом: объявления стоят в
  кэшируемом префиксе, и меняющийся набор означал бы промах мимо кэша на каждом
  ходу плюс поведение, которого модель не может предсказать.
* **Модель не видит ни OOXML, ни готовых файлов.** `preview` отдаёт цифры.

Решения, названные здесь, чтобы их не пришлось выяснять по коду:

**Беда инструмента возвращается модели, а не наружу.** Ответ — `is_error=True` и
объект JSON `{"error": код, "message": …}`, где сказано, что именно поправить
(неизвестный ключ — со списком известных и подсказкой «похоже на»). Прогон при
этом продолжается: модель, получившая внятный отказ, чинится следующим ходом, а
упавший прогон стоит всех уже потраченных денег и не даёт ничего.

**`read_material` отдаёт кусок, а не материал целиком** (`READ_CHARS`). Методичка
бывает на сотни килобайт, окно — нет, и «отдали всё» кончается обрывом на
середине работы. В ответе всегда есть `total` и `truncated`: модель видит, что
осталось, и просит следующий кусок номерами строк или страниц.

**`preview` не отдаёт байты.** Документ модели не нужен, а отдать его значит
отдать OOXML — то, чего она не видит по несущему решению версии. Числа страниц
в ответе тоже нет: чтобы его узнать, надо собрать DOCX и прогнать LibreOffice
подпроцессом, а это дорого на каждом ходу и не отвечает ни на один вопрос
модели.

**Потолок ходов** — `MAX_STEPS`. На нём петля останавливается штатным исходом
(`Stop.MAX_TOKENS`, пометка `step_limit` в `degraded`), а не ошибкой: всё, что
модель успела поставить, уже сохранено — `set_tag` пишет версию в момент
вызова, а не в конце прогона. История петли не сохраняется (`llm/loop.py:87`),
поэтому «сохранено в момент производства» здесь не удобство, а единственный
способ не заплатить второй раз за то же самое.

**Расход в журнале.** Инструменты сами денег не стоят: цена — это вызовы
модели, а их в прогоне столько, сколько ходов. Один ход — одна запись журнала
(`llm.loop._record`, приметы `run`, `level`, `step`), лимит проверяется перед
каждым ходом. Сами вызовы инструментов ложатся в `runs/<id>.json` (`Run.steps`)
и пишутся на диск сразу: прогон, оборванный на пятом ходу, обязан оставить
след того, что успел сделать.
"""
from __future__ import annotations

import json

import hokoku
import llm
import materials
import fragmos
import uml_generator
from uml_generator import objektis

from . import build as build_mod, fill as fill_mod, schema as schema_mod
from .errors import OrchestratorError, hint

# Сколько знаков содержимого отдаётся за один `read_material`. Потолок нужен не ради
# денег, а ради работоспособности: материал на сотни килобайт, отданный целиком,
# либо не влезет в окно, либо вытеснит из него всё остальное — и то и другое
# кончается прогоном, который ничего не поставил.
READ_CHARS = 6000

# Потолок исходника, который принимают строители схем. Разбор миллиона знаков
# tree-sitter'ом упирается не в правильность, а во время хода: модель ждёт, а
# потолок ходов идёт. Отказ при этом внятный — модель знает, что делать.
MAX_SOURCE_CHARS = 200_000

# Сколько исходников берут диаграммы классов и объектов за один вызов. Больше —
# это не диаграмма, а обои: читать её человек не станет.
MAX_SOURCES = 8

# Потолок ходов прогона уровня 3 — умолчание слоя (`llm.Limits`), а не своё
# число: два числа про одно и то же рано или поздно разойдутся, и объяснять,
# какое из них главное, будет нечем. На потолке петля останавливается штатно
# (`Stop.MAX_TOKENS`, пометка `step_limit`), а поставленное уже сохранено.
MAX_STEPS = llm.Limits().max_steps

_LANGS = ("python", "csharp", "cpp")
_FLOWCHART_MODES = ("default", "loopLimit", "plain")
_THEMES = ("dark", "light")

# ── операторский канал: то самое одно место ──────────────────────────────────
# Вопрос владельца (`status.md`, «Решить владельцу»): пускать ли уровень 3 на
# endpoint, у которого нет операторского канала, — то есть где наши указания для
# модели не весомее текста из файла студента. Решение владельца 2026-08-31:
# заглушка, идём дальше. Заглушка стоит здесь одна на весь уровень, а не
# ветвлением по коду: разбросанное поведение нельзя ни переключить одним
# движением, ни назвать в отчёте.
#
#   "allow" — пускать молча (не рекомендуется: разницы с проверенным
#             endpoint'ом не остаётся вовсе);
#   "flag"  — пускать, но каждое значение из `set_tag` получает пометку
#             «проверить», а в итоге прогона стоит замечание уровня info.
#             Это и есть заглушка по умолчанию: предложение из `status.md`
#             («структурированный вывод не ниже строгого инструмента и пометка
#             „проверить“ на каждом значении») выполнено наполовину — пометка
#             ставится, ступень не требуется;
#   "deny"  — отказ до вызова, ни одного потраченного токена.
#
# Заглушка осталась «flag» и после того, как канал начали мерить (2026-09-03,
# `llm.probing._step_operator`): у deepseek и openrouter указание оператора устояло
# 2 из 2, владелец поднял заявку до `messages_system`, и на этих двух ворота теперь
# пропускают без пометки — но именно потому, что канал у них **объявлен и
# исполняется** (`openai_compat._operator_reminder` повторяет указание после
# недоверенного текста), а не потому, что заглушка ослабла. На endpoint'е, где
# канала нет, всё по-прежнему: пускаем и помечаем.
#
# Правило, которое здесь важно помнить: проба умеет заявку **понизить** и не умеет
# **повысить** (`llm.model.merged_caps`). Значит эти ворота нельзя открыть
# измерением — только решением владельца, и отозвать его тоже можно одной строкой
# в `presets.py`.
WITHOUT_OPERATOR_CHANNEL = "flag"

# Пометка, которая ложится в `Version.flags` при "flag". Текст один на все
# значения: по нему человек в интерфейсе отбирает то, что надо перечитать.
UNVERIFIED_FLAG = ("проверить: у endpoint'а нет операторского канала, "
                   "указания службы для модели не весомее текста из файлов проекта")


def operator_channel_gate(endpoint_id: str) -> tuple[tuple[str, ...], list[hokoku.Problem]]:
    """Ворота уровня 3 на endpoint'е без операторского канала. Одна на прогон.

    Возвращает `(пометки для каждого значения, замечания прогона)`; при
    `WITHOUT_OPERATOR_CHANNEL == "deny"` бросает `OrchestratorError` **до**
    первого вызова: отказ после пятого хода стоил бы денег за пять ходов и
    ничего бы не изменил.

    Зачем вообще: без операторского канала строка «ты выполняешь задание
    службы» едет тем же каналом, что и текст файла студента, — а в файле бывает
    написано «забудь предыдущие указания». Рамка `llm.layout` это сдерживает, но
    сдерживание не равно каналу, и утверждать обратное на основании заявки
    владельца нельзя.
    """
    # Переключатель проверяется первым и всегда, даже когда канал есть: опечатка
    # («flg») иначе не совпала бы ни с одной веткой и сработала бы как молчаливое
    # «пускать» — то самое разбросанное поведение, ради которого заглушка и
    # собрана в одном месте.
    if WITHOUT_OPERATOR_CHANNEL not in ("allow", "flag", "deny"):
        raise OrchestratorError(
            f"WITHOUT_OPERATOR_CHANNEL — allow, flag или deny, "
            f"а не {WITHOUT_OPERATOR_CHANNEL!r}")
    caps = llm.capabilities(endpoint_id)
    if caps.operator_channel == llm.OperatorChannel.MESSAGES_SYSTEM:
        return (), []
    if WITHOUT_OPERATOR_CHANNEL == "deny":
        raise OrchestratorError(
            f"endpoint {endpoint_id!r} не объявляет операторского канала "
            f"({caps.operator_channel!r}): уровень 3 на нём запрещён "
            "(orchestrator.tools.WITHOUT_OPERATOR_CHANNEL)")
    if WITHOUT_OPERATOR_CHANNEL == "allow":
        # Молча — значит молча: ни пометки на значении, ни замечания в итоге.
        # Три режима обязаны различаться делом, иначе переключатель ничего не
        # переключает, а объясняет.
        return (), []
    problem = fill_mod._problem(
        "no_operator_channel", None,
        f"у endpoint'а {endpoint_id!r} нет операторского канала "
        f"({caps.operator_channel!r}); прогон уровня 3 разрешён "
        f"решением владельца 2026-08-31, режим "
        f"{WITHOUT_OPERATOR_CHANNEL!r}: каждое значение помечено «проверить»",
        "info")
    return (UNVERIFIED_FLAG,), [problem]


# ── объявления инструментов ──────────────────────────────────────────────────

def _obj(props: dict, required=()) -> dict:
    return {"type": "object", "properties": props, "required": list(required),
            "additionalProperties": False}


_ID = {"type": "string", "description": "идентификатор материала из list_materials"}
_ARTIFACT = {"type": "string"}


def tools() -> list[llm.Tool]:
    """Объявления всех семи инструментов, в постоянном порядке.

    Порядок и состав постоянны намеренно: список едет в каждом запросе прогона и
    стоит в кэшируемом префиксе. Собирать его «по обстановке» (нет материалов —
    убрать `read_material`) значило бы платить за префикс заново на каждом ходу и
    менять правила игры посреди прогона.

    Известная беда, не наша: инструмент без аргументов сегодня до нас не
    доходит. `llm.loop._call_tool` (`loop.py:252`) считает вызов с
    `raw_arguments="{}"` и пустым разбором битым JSON и отвечает модели ошибкой
    сам — а `"{}"` присылает всякий поставщик, у которого поле аргументов
    обязательно. Значит `list_materials` и `preview` работают только там,
    где поле аргументов не присылается вовсе. Чинится это в `llm` одним
    условием; заводить здесь фиктивный аргумент ради обхода нельзя — модель
    всё равно вправе прислать `{}`, а лишний параметр останется навсегда.

    Имена первых двух — `list_materials` и `read_material`, как просила записка
    `koritsu-kadai-2026-08-31.md` (Г.2), а не прежние `list_project_files` /
    `read_file`. Смысл не менялся ни на день — **пути не принимаются ни в одном
    аргументе**, — но слова видит модель, и `read_file` звало её к файловой
    системе, которой у неё нет: файлов у нас не существует, есть материалы с
    идентификатором-хешем. Имя файла подделывается содержимым, идентификатор —
    нет, и назвать это разными словами в разных местах значило бы объяснять
    модели устройство хранилища дважды и по-разному.
    """
    value = schema_mod.any_value_schema()
    return [
        llm.Tool(name="list_materials", schema=_obj({}), description=(
            "Опись материалов проекта: идентификатор, имя, вид, чем нумеруется "
            "содержимое и сколько его. Содержимого не отдаёт — его отдаёт "
            "read_material по идентификатору. Без аргументов; пустой список "
            "означает, что материалов нет.")),
        llm.Tool(name="read_material", description=(
            "Кусок содержимого материала по его идентификатору из list_materials. "
            "Границы включительно, "
            f"нумерация с 1, за один вызов не больше {READ_CHARS} знаков. "
            "В ответе total (сколько всего единиц) и truncated (кусок обрезан) — "
            "по ним запрашивай следующий кусок. Другого способа адресовать "
            "материал нет: имён и путей инструмент не принимает."),
            schema=_obj({
                "id": _ID,
                "start": {"type": ["integer", "null"], "minimum": 1,
                          "description": "первая строка или страница"},
                "end": {"type": ["integer", "null"], "minimum": 1,
                        "description": "последняя строка или страница"}},
                required=["id"])),
        llm.Tool(name="make_flowchart", description=(
            "Блок-схема алгоритма из исходника-материала (draw.io). Код НЕ "
            "выполняется — только разбирается. Возвращает идентификатор "
            "артефакта: его и ставь в значение тега типа diagram."),
            schema=_obj({
                "id": _ID,
                "language": {"enum": list(_LANGS)},
                "mode": {"enum": [*_FLOWCHART_MODES, None],
                         "description": "режим отрисовки; по умолчанию default"}},
                required=["id", "language"])),
        llm.Tool(name="make_class_diagram", description=(
            "Диаграмма классов UML по исходникам-материалам (draw.io). Код НЕ "
            "выполняется. Возвращает идентификатор артефакта и список классов."),
            schema=_obj({
                "ids": {"type": "array", "items": _ID, "minItems": 1,
                        "maxItems": MAX_SOURCES},
                "language": {"enum": list(_LANGS)},
                "theme": {"enum": [*_THEMES, None]}},
                required=["ids", "language"])),
        llm.Tool(name="make_object_diagram", description=(
            "Диаграмма объектов UML: какие экземпляры создаёт код и как они "
            "связаны. Трассировка статическая, код НЕ выполняется. В notes "
            "написано, чего разбор не понял, — читай их, прежде чем ставить "
            "схему в отчёт."),
            schema=_obj({
                "ids": {"type": "array", "items": _ID, "minItems": 1,
                        "maxItems": MAX_SOURCES},
                "language": {"enum": list(_LANGS)},
                "theme": {"enum": [*_THEMES, None]}},
                required=["ids", "language"])),
        llm.Tool(name="set_tag", description=(
            "Поставить значение тега отчёта. Значение проверяется тем же "
            "валидатором, что и правка человека: тип обязан совпасть с "
            "манифестом, артефакт — существовать. Отказ приходит с перечнем "
            "замечаний — поправь значение и повтори. Ставь значение сразу, как "
            "оно готово: поставленное сохранено и обрывом не отменяется."),
            schema=_obj({"key": {"type": "string"}, "value": value},
                        required=["key", "value"])),
        llm.Tool(name="preview", schema=_obj({}), description=(
            "Состояние отчёта: сколько тегов заполнено, какие пусты, какие "
            "замечания даёт проверка. Файла не отдаёт — документ собирается "
            "после прогона. Без аргументов.")),
    ]


TOOL_NAMES = ("list_materials", "read_material", "make_flowchart",
              "make_class_diagram", "make_object_diagram", "set_tag", "preview")


class ToolError(Exception):
    """Беда, которую модель может починить сама: код, текст и что известно.

    Отдельный тип, а не `OrchestratorError`: тот означает «службу позвали
    неправильно» и обязан долетать до человека, а этот — ответ модели внутри
    петли. Слить их значило бы либо ронять прогон на опечатке модели, либо
    прятать от человека настоящую поломку.
    """

    def __init__(self, code: str, message: str, **extra):
        super().__init__(message)
        self.payload = {"error": code, "message": message, **extra}


class ToolBox:
    """Диспетчер инструментов одного прогона: `on_call` для `llm.run_tools`.

    Состояние прогона держится здесь, а не в петле: петля историю не сохраняет
    (`llm/loop.py:87`), и всё, что произведено, обязано лежать в проекте в момент
    производства. Отсюда же `filled` и `steps` — они пишутся на диск сразу.

    `allowed` — теги, которые прогону разрешено ставить: отбор `schema.fillable`
    минус те, чью текущую версию написал человек. Проверка стоит в инструменте,
    а не только в отборе, потому что тег модель называет сама: без неё «поставь
    цель» прошло бы мимо всех отборов и затёрло бы правку студента.
    """

    def __init__(self, project, run, *, manifest, parts, template, allowed,
                 extra_flags=()):
        self.project = project
        self.run = run
        self.manifest = manifest
        self.parts = parts
        self.template = template
        self.allowed = set(allowed)
        self.extra_flags = tuple(extra_flags)
        self.filled: list = []
        self.problems: list = []
        self.calls: int = 0
        self._typed = fill_mod._typed_values(project, skip=None)
        self._handlers = {
            "list_materials": self._list_materials,
            "read_material": self._read_material,
            "make_flowchart": self._make_flowchart,
            "make_class_diagram": self._make_class_diagram,
            "make_object_diagram": self._make_object_diagram,
            "set_tag": self._set_tag,
            "preview": self._preview,
        }

    # ── диспетчер ───────────────────────────────────────────────────────────
    def __call__(self, call) -> llm.ToolResult:
        """Вызов инструмента → ответ модели. Наружу не бросает ничего чинимого.

        Петля и сама превращает исключение в `is_error` (`loop._call_tool`), но
        текстом «инструмент не отработал: …». Здесь ответ разбираемый — объект
        JSON с кодом беды, — потому что модель на него отвечает следующим ходом,
        и «что именно поправить» она должна прочитать, а не угадать.
        """
        self.calls += 1
        handler = self._handlers.get(call.name)
        if handler is None:
            return self._answer(call, {"error": "unknown_tool",
                                       "message": f"инструмента {call.name!r} нет"
                                                  f"{hint(call.name, self._handlers)}",
                                       "known": list(TOOL_NAMES)}, is_error=True)
        try:
            answer = handler(dict(call.arguments or {}))
        except ToolError as exc:
            return self._answer(call, exc.payload, is_error=True)
        except OrchestratorError:
            # Служба позвана неправильно — это наша беда, а не модели: чинить её
            # моделью бессмысленно, и прятать её в ответ инструмента значит
            # прятать поломку службы от человека.
            raise
        except Exception as exc:                    # noqa: BLE001 — чужие пакеты
            # `fragmos`, `uml_generator` и `materials` бросают своё; для модели
            # это такая же чинимая беда («не тот язык», «не тот материал»).
            return self._answer(call, {"error": "tool_failed",
                                       "message": f"{type(exc).__name__}: {exc}"},
                                is_error=True)
        return self._answer(call, answer)

    def _answer(self, call, payload: dict, *, is_error: bool = False) -> llm.ToolResult:
        self._step({"tool": call.name, "ok": not is_error,
                    "error": payload.get("error", "") if is_error else ""})
        return llm.ToolResult(call_id=call.id, is_error=is_error,
                              content=json.dumps(payload, ensure_ascii=False))

    def _step(self, step: dict) -> None:
        """Ход в записи прогона — сразу на диск, а не в конце.

        Прогон, оборванный связью на пятом ходу, обязан оставить след первых
        четырёх: иначе «за что заплачено» в журнале есть, а «что при этом
        делалось» — нет.
        """
        self.run.steps.append(step)
        self.project.save_run(self.run)

    # ── чтение материалов ───────────────────────────────────────────────────
    def _list_materials(self, args: dict) -> dict:
        """Опись материалов. Не отказывает никогда: пустой проект — пустой список."""
        store = self.project.store()
        return {"materials": [{"id": m.id, "name": m.name, "kind": m.kind,
                           "unit": m.unit, "count": m.count, "lang": m.lang,
                           "notes": list(m.notes)} for m in store.list()]}

    def _read_material(self, args: dict) -> dict:
        """Кусок материала по идентификатору, не длиннее `READ_CHARS`.

        Обрезка молчаливой не бывает: `truncated` и `total` в ответе — это то,
        чем модель просит продолжение. Молча отданный обрубок кончился бы
        отчётом, написанным по первой трети методички, и никто бы не узнал.
        """
        material = self._material(args.get("id"))
        chunk = self.project.store().read(material.id, args.get("start"), args.get("end"))
        text, cut = _cut(chunk.text, READ_CHARS)
        return {"id": material.id, "name": material.name, "unit": chunk.unit,
                "from": chunk.start, "to": chunk.end, "total": material.count,
                "truncated": cut, "anchor": chunk.anchor, "text": text}

    # ── схемы ───────────────────────────────────────────────────────────────
    def _make_flowchart(self, args: dict) -> dict:
        """Блок-схема алгоритма: `fragmos.generate_xml` → артефакт.

        Аргумента `only` («одна схема одного алгоритма») здесь нет, и это не
        забывчивость: `fragmos` отдаёт схемы всех функций сразу, по странице на
        функцию, а резать mxfile на нашей стороне значило бы вернуть разрезание
        схем в код, откуда его убирали. В ответе есть `pages` — модель ставит
        нужный лист полем `page` значения diagram.

        Что в схему не вошло, `fragmos` с 2.0.0a4.2 говорит вслух (`warnings=`,
        `kyotsu.Notice`), и мы это проводим в три места сразу: в ответ модели —
        ей решать, ставить ли такую схему в отчёт; в `problems` прогона — их
        видит человек; и рядом с артефактом на диск (`put_artifact(notices=)`) —
        оттуда их берёт полная проверка перед сборкой (`build.check`), потому
        что смотреть отчёт человек будет позже и другим глазом. `hokoku` при
        этом про `fragmos` по-прежнему ничего не знает: замечание доезжает до
        отчёта через службу, а не через пакет.
        """
        source = self._source(args.get("id"))
        language = _one_of(args.get("language"), _LANGS, "language")
        mode = _one_of(args.get("mode") or "default", _FLOWCHART_MODES, "mode")
        notices: list = []
        try:
            xml = fragmos.generate_xml(source.text, language, mode_id=mode,
                                       warnings=notices)
        except SyntaxError as exc:
            raise ToolError("parse_error",
                            f"исходник {source.name!r} не разобрался как {language}: {exc}. "
                            "Проверь язык и материал") from None
        except Exception as exc:                    # noqa: BLE001 — fragmos бросает своё
            raise ToolError("parse_error",
                            f"схема по {source.name!r} не построилась: "
                            f"{type(exc).__name__}: {exc}") from None
        self.problems.extend(notices)
        return {"artifact": self.project.put_artifact(xml.encode("utf-8"), name="схема",
                                                      notices=notices),
                "pages": hokoku.wire.count_pages(xml), "language": language,
                "warnings": [n.to_dict() for n in notices],
                "note": "страница на функцию; нужный лист ставится полем page"}

    def _make_class_diagram(self, args: dict) -> dict:
        """Диаграмма классов: `extract_py/cs/cpp` → `build_xml` → артефакт."""
        sources = self._sources(args.get("ids"))
        language = _one_of(args.get("language"), _LANGS, "language")
        theme = _one_of(args.get("theme") or "dark", _THEMES, "theme")
        extract = {"python": uml_generator.extract_py,
                   "csharp": uml_generator.extract_cs,
                   "cpp": uml_generator.extract_cpp}[language]
        classes: list = []
        for source in sources:
            try:
                classes.extend(extract(source.text))
            except Exception as exc:                # noqa: BLE001 — чужой разбор
                raise ToolError("parse_error",
                                f"{source.name!r} не разобрался как {language}: "
                                f"{type(exc).__name__}: {exc}") from None
        if not classes:
            # Пустая диаграмма — это лист «нет классов», вставленный в отчёт как
            # схема. Отказ здесь полезнее: модель либо возьмёт другой материал,
            # либо не будет ставить схему вовсе.
            raise ToolError("no_classes",
                            "в этих материалах не нашлось ни одного класса: "
                            "диаграмму классов строить не из чего")
        xml = uml_generator.build_xml(classes, theme)
        return {"artifact": self.project.put_artifact(xml.encode("utf-8"), name="классы"),
                "classes": [c.name for c in classes], "language": language}

    def _make_object_diagram(self, args: dict) -> dict:
        """Диаграмма объектов: `objektis.extract_objects` → `build_xml` → артефакт.

        `notes` отдаются модели дословно: там честно написано, чего статическая
        трассировка не поняла. Пересказать их короче значило бы решить за
        модель, какая недосказанность неважна, — а именно она и попадает потом в
        отчёт как утверждение.

        Первый материал — точка входа (модуль, `Main()`, `main()`), остальные
        едут соседними файлами. Первый в `files` **не повторяется**: `cs_static`
        и `cpp_static` склеивают точку входа со всеми соседями в один текст
        (`cs_static.py:390`), и вход, поданный дважды, разбирался бы дважды. На
        C# с операторами верхнего уровня это видно глазом: `new Двигатель(120)`
        в исходнике один, а на схеме появлялся второй, `двигатель2`, которого в
        коде студента нет. Придуманный экземпляр в отчёте хуже отсутствующей
        схемы: его не с чем сверить.
        """
        sources = self._sources(args.get("ids"))
        language = _one_of(args.get("language"), _LANGS, "language")
        theme = _one_of(args.get("theme") or "dark", _THEMES, "theme")
        files = [{"filename": s.name, "code": s.text} for s in sources[1:]]
        graph = objektis.extract_objects(sources[0].text, language, files=files)
        if graph.is_empty():
            raise ToolError("no_objects",
                            "трассировка не нашла ни одного экземпляра "
                            "пользовательских классов",
                            notes=list(graph.notes))
        xml = objektis.build_xml(graph, theme)
        return {"artifact": self.project.put_artifact(xml.encode("utf-8"), name="объекты"),
                "objects": [i.name for i in graph.instances],
                "notes": list(graph.notes)}

    # ── значения ────────────────────────────────────────────────────────────
    def _set_tag(self, args: dict) -> dict:
        """Значение тега — через `fill._accept`, то есть через `Project.set_value`.

        Той же функцией, а не похожей. Всё, ради чего она написана, действует и
        здесь: `wire.value_from_json` (значение выражается, артефакт существует),
        `hokoku.validate` (годно против шаблона и манифеста), жёсткая беда версии
        не заводит, мягкое замечание едет в `flags` вместе со значением, версия
        самоописана. Отдельного доверенного пути для модели нет — он и был бы той
        дырой, через которую в отчёт попадает то, чего человеку положить не дали.

        Правку человека прогон не трогает: тег, чью текущую версию поставил
        человек, в `allowed` не попал, и ответ здесь — отказ, а не молчаливая
        замена. Аргумента `overwrite` у инструмента нет намеренно: переписать
        чужое — решение человека, и класть его в руки модели значит отдать ей
        право, которого у неё нет.
        """
        key = str(args.get("key") or "")
        value = args.get("value")
        if not isinstance(value, dict):
            raise ToolError("bad_value",
                            f"value — объект значения с полем type, "
                            f"а не {type(value).__name__}")
        key = hokoku.wire.norm_key(key)
        if key not in self.allowed:
            raise ToolError("unknown_key",
                            f"тега {key!r} прогону ставить нельзя: его нет в задании, "
                            f"его заполняет не модель или его уже написал человек"
                            f"{hint(key, self.allowed)}",
                            known=sorted(self.allowed))
        fill = fill_mod._accept(self.project, self.manifest, key, value,
                                run=self.run, result=None, parts=self.parts,
                                others={k: v for k, v in self._typed.items() if k != key},
                                template=self.template, extra_flags=self.extra_flags)
        if not fill.ok:
            self.problems.extend(fill.problems)
            raise ToolError("rejected",
                            f"значение тега {key!r} не принято",
                            key=key,
                            problems=[p.message for p in fill.problems])
        self.filled.append(key)
        self.problems.extend(fill.problems)
        parsed = fill_mod._parse(self.project, value)
        if parsed is not None:
            # Поставленное значение становится соседом для следующих проверок:
            # `depends_on` смотрит на то, что уже есть.
            self._typed[key] = parsed
        return {"ok": True, "key": key, "version": fill.version.n,
                "flags": list(fill.flags),
                "problems": [p.message for p in fill.problems]}

    def _preview(self, args: dict) -> dict:
        """Состояние отчёта цифрами: заполнено, не заполнено, замечания.

        Это `orchestrator.check` — та же полная проверка, что стоит перед
        сборкой, и второго ответа на вопрос «годен ли отчёт» здесь не заводится.
        Байтов нет: документ модели не нужен, а отдать его значит отдать OOXML.
        """
        problems = build_mod.check(self.project)
        values = self.project.values()
        wanted = schema_mod.fillable(self.manifest)
        return {"filled": [k for k in wanted if k in values],
                "unfilled": [k for k in wanted if k not in values],
                "problems": [{"key": p.key, "level": p.level, "message": p.message}
                             for p in problems[:40]],
                "problems_total": len(problems)}

    # ── общее ───────────────────────────────────────────────────────────────
    def _material(self, mid) -> materials.Material:
        """Материал по идентификатору. Путь вместо идентификатора — отказ.

        Форма проверяется до обращения к хранилищу, тем же выражением, что у
        `Project.resolve_artifact`: `Store` складывает из идентификатора путь, и
        `../../etc/passwd`, дойдя до него, стал бы чтением мимо проекта. Проверка
        внутри чужого пакета нас не спасёт — она не наша.
        """
        mid = str(mid or "")
        if not hokoku.wire.ARTIFACT_RE.match(mid) or ".." in mid:
            raise ToolError("bad_id",
                            f"{mid!r} — не идентификатор материала. Пути не "
                            "принимаются: идентификаторы даёт list_materials")
        store = self.project.store()
        try:
            return store.get(mid)
        except materials.MaterialsError:
            known = [m.id for m in store.list()]
            raise ToolError("unknown_id",
                            f"материала {mid!r} в проекте нет{hint(mid, known)}",
                            known=known) from None

    def _source(self, mid):
        """Материал как исходник: текстовый, не пустой, не длиннее потолка."""
        material = self._material(mid)
        if material.kind != materials.KIND_TEXT:
            raise ToolError("not_source",
                            f"материал {material.name!r} — {material.kind}, "
                            "а схема строится по исходнику (текстовый материал)")
        text = self.project.store().read(material.id).text
        if not text.strip():
            raise ToolError("empty_source", f"материал {material.name!r} пуст")
        if len(text) > MAX_SOURCE_CHARS:
            raise ToolError("too_big",
                            f"в материале {material.name!r} {len(text)} знаков, "
                            f"потолок разбора — {MAX_SOURCE_CHARS}")
        return _Source(id=material.id, name=material.name, text=text)

    def _sources(self, ids) -> list:
        if not isinstance(ids, list) or not ids:
            raise ToolError("bad_ids", "ids — непустой список идентификаторов материалов")
        if len(ids) > MAX_SOURCES:
            raise ToolError("too_many",
                            f"за раз берётся не больше {MAX_SOURCES} исходников, "
                            f"дано {len(ids)}")
        return [self._source(mid) for mid in ids]


class _Source:
    """Исходник материала: идентификатор, имя и текст. Пути в нём нет."""

    def __init__(self, id: str, name: str, text: str):   # noqa: A002
        self.id, self.name, self.text = id, name, text


def _cut(text: str, limit: int) -> tuple[str, bool]:
    """Обрезка с честным признаком. Многоточие не ставим: оно уехало бы в отчёт."""
    return (text, False) if len(text) <= limit else (text[:limit], True)


def _one_of(value, allowed, name: str) -> str:
    """Значение из перечня — с внятным отказом вместо KeyError.

    Перечень стоит и в схеме инструмента, но полагаться на неё нельзя: строгий
    режим есть не у всякого endpoint'а, а на слабой ступени схема к поставщику
    не едет вовсе — модель присылает что хочет.
    """
    text = str(value or "")
    if text not in allowed:
        raise ToolError("bad_argument",
                        f"{name}: {text!r} — не из списка {', '.join(allowed)}"
                        f"{hint(text, allowed)}")
    return text


__all__ = ["tools", "ToolBox", "ToolError", "TOOL_NAMES", "operator_channel_gate",
           "WITHOUT_OPERATOR_CHANNEL", "UNVERIFIED_FLAG", "READ_CHARS", "MAX_STEPS",
           "MAX_SOURCES", "MAX_SOURCE_CHARS"]
