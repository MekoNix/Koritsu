"""
orchestrator — единственный, кто знает про все пакеты сразу.

Пять пакетов (`hokoku` — отчёты из DOCX-шаблонов, `llm` — слой моделей,
`materials` — материалы студента, `fragmos` и `uml_generator` — схемы) не связаны
между собой ни одним импортом, и это правило держится намеренно: каждый из них
самостоятелен и тестируется отдельно. Не хватало того единственного, кто знает
про всех сразу, — им и работает этот пакет. Импортировать соседей можно только
ему; из него не импортирует никто.

**Почему отдельный пакет, а не модуль внутри hokoku** (решение владельца
2026-08-31). Служба обязана знать про хранилище (материалы, версии значений,
артефакты) и про модель. `hokoku` объявил про себя обратное в двух местах:
манифест — «хранение за службой», `build_report` — «готовые файлы наружу
байтами не отдаём». Положить склейку туда значит завести в движке отчётов
импорт `llm` и `materials`, то есть притащить сетевой код всюду, где нужны
просто отчёты, и отменить оба решения, ради которых писался `wire.py`.

Разрыв, ради которого пакет и заведён: **никто не собирал `[llm.Part]`**. В
`packages/` `Part` создавался только с ролями `rules` и `request`; роли `files`,
`manifest`, `neighbors` не создавал никто, кроме тестов. Из-за этого рамка
вокруг недоверенного текста (`llm.layout.frame_untrusted`) не вызывалась ни разу
на рабочем пути — защита от инъекции через материалы студента существовала
только в коде, — а раскладка промпта выродилась в два куска из пяти. Рамку
получает не роль, а кусок с признаком `Part.untrusted`: здесь его ставят
`files`, `manifest` (метки тегов из чужого DOCX-шаблона) и `neighbors`
(значения могли быть списаны из файла студента).

    Project(path)                        каталог работы: материалы, значения,
                                         версии, манифест, прогоны, журнал
    fill_tag(project, key, endpoint=…)    уровень 1: один тег
    fill_report(project, endpoint=…)      уровень 2: весь отчёт потоком
    fill_agent(project, endpoint=…)       уровень 3: агент с инструментами
    build(project)                        значения → validate → build_report
    build_parts(project, keys=…)          раскладка промпта в пять ролей
    ask(project, вопрос, endpoint=…)      один вопрос модели вне тегов
    make_template(project, …)             строение работы → заготовки блоков
    solve(project, задание, endpoint=…)   живой режим: агент собирает блоки
    write_texts(project, endpoint=…)      весь связный текст одним проходом
    check_code(text, lang)                разбирается ли сочинённый исходник
    kadai_services(project, endpoint=…)   двери для сценария kadai

Состав пакета:

    errors.py    свой тип ошибки и подсказка «похоже на»
    project.py   состояние на диске; единственное место, знающее про пути
    prompt.py    манифест + опись материалов + соседи → [llm.Part]
    schema.py    какие теги просить и по какой схеме
    stream.py    поток уровня 2 → пары (ключ, значение) по мере закрытия
    fill.py      уровни 1 и 2, проверка и запись версий
    tools.py     семь инструментов уровня 3 поверх той же механики
    agent.py     уровень 3: петля llm.run_tools, отбор, ворота, исход
    build.py     значения → hokoku.build_report
    live.py      живой режим: работа списком блоков, свои инструменты, текст
    doors.py     двери наружу: ask, make_template, check_code, Services для kadai
    kadai.py     python -m orchestrator.kadai: сценарий с уже собранными дверями

Три уровня — не три службы: у всех один отбор тегов, одна раскладка промпта,
один валидатор и одна точка записи версии. Инструмент уровня 3 — тонкая
обёртка над тем, что уже есть: `set_tag` это `fill._accept`, `preview` это
`check`. Второй путь записи значения был бы вторым набором правил про версии,
`source` и защиту правки человека, и разошлись бы они молча.

Чего здесь нет намеренно: HTTP, сервера и CLI сайта (их в этой версии нет
вовсе) и любого выполнения пользовательского кода — схемы строятся разбором
tree-sitter'ом, ни `exec`, ни подпроцесса, ни поиска в сети.

Уровень 3 на endpoint'е без операторского канала — открытый вопрос владельца;
решение 2026-08-31 «заглушка, идём дальше» стоит одним переключателем
`tools.WITHOUT_OPERATOR_CHANNEL` (`allow` | `flag` | `deny`) и работает через
единственные ворота `tools.operator_channel_gate`.
"""
from .errors import OrchestratorError
from .project import BLOCK_FIELDS, BlockVersion, Project, Run, SOURCES, Version, \
    artifact_id
from .prompt import RULES, build_parts, prompt_hash, render, seal_mark
from .schema import any_value_schema, fillable, report_schema, tag_schema
from .stream import TagStream
from .fill import RunResult, TagFill, fill_report, fill_tag
from .tools import ToolBox, ToolError, operator_channel_gate
from .agent import AgentResult, fill_agent
from .build import check, job_of
from .build import build
from .live import LiveResult, TextsResult, live_tools, solve, write_texts
from .doors import Answer, ask, check_code, kadai_services, make_template

__all__ = [
    "Project", "Version", "BlockVersion", "Run", "SOURCES", "artifact_id",
    "BLOCK_FIELDS",
    "fill_tag", "fill_report", "TagFill", "RunResult",
    "fill_agent", "AgentResult", "ToolBox", "ToolError", "operator_channel_gate",
    "build", "check", "job_of",
    "ask", "Answer", "make_template", "check_code", "solve", "write_texts",
    "kadai_services",
    "LiveResult", "TextsResult", "live_tools",
    "build_parts", "seal_mark", "render", "prompt_hash", "RULES",
    "tag_schema", "any_value_schema", "report_schema", "fillable", "TagStream",
    "OrchestratorError",
    "prompt", "schema", "stream", "fill", "tools", "agent", "live", "doors",
]
