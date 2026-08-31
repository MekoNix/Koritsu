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
только в коде, — а раскладка промпта выродилась в два куска из пяти.

    Project(path)                        каталог работы: материалы, значения,
                                         версии, манифест, прогоны, журнал
    fill_tag(project, key, endpoint=…)    уровень 1: один тег
    fill_report(project, endpoint=…)      уровень 2: весь отчёт потоком
    build(project)                        значения → validate → build_report
    build_parts(project, keys=…)          раскладка промпта в пять ролей

Состав пакета:

    errors.py    свой тип ошибки и подсказка «похоже на»
    project.py   состояние на диске; единственное место, знающее про пути
    prompt.py    манифест + опись материалов + соседи → [llm.Part]
    schema.py    какие теги просить и по какой схеме
    stream.py    поток уровня 2 → пары (ключ, значение) по мере закрытия
    fill.py      уровни 1 и 2, проверка и запись версий
    build.py     значения → hokoku.build_report

Чего здесь нет намеренно: HTTP, сервера и CLI сайта (их в этой версии нет
вовсе), уровня 3 (агент с инструментами — упирается в нерешённый вопрос
владельца) и любого выполнения пользовательского кода.
"""
from .errors import OrchestratorError
from .project import Project, Run, SOURCES, Version, artifact_id
from .prompt import RULES, build_parts, prompt_hash, render, seal_mark
from .schema import fillable, report_schema, tag_schema
from .stream import TagStream
from .fill import RunResult, TagFill, fill_report, fill_tag
from .build import check, job_of
from .build import build

__all__ = [
    "Project", "Version", "Run", "SOURCES", "artifact_id",
    "fill_tag", "fill_report", "TagFill", "RunResult",
    "build", "check", "job_of",
    "build_parts", "seal_mark", "render", "prompt_hash", "RULES",
    "tag_schema", "report_schema", "fillable", "TagStream",
    "OrchestratorError",
    "prompt", "schema", "stream", "fill",
]
