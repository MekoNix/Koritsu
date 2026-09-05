"""
kadai (課題, «задание») — сценарий «условие задачи → готовый архив».

На входе условие файлом и пожелания словами, на выходе ZIP с кодом, шаблоном,
решением и отчётом в Word. Единица, которой владеет пакет, — одно задание: у
него есть условие, пожелания, срок жизни и один архив на выходе. Проект в
`orchestrator` — единица хранения; второго слова для единицы смысла в проекте
нет, отсюда и имя. Имя переживает вопрос «а если завтра документ другого вида»:
вид работы пакетом не назван нигде и назван быть не может — всё это 課題.

**Граница, и она узкая.** `orchestrator` уже хранит работу на диске,
версионирует значения с пометкой источника, собирает промпт, зовёт модель на
трёх уровнях, гоняет ответ через тот же валидатор, что и запрос из интерфейса, и
собирает отчёт. `kadai` не повторяет из этого ничего. Ему остаётся сценарий:

    строение работы данными       какие разделы бывают и что обязательно
    стадии и статус               где стоим, что готово, сколько потрачено
    два режима прохода            одно множество «где остановиться», не две ветки
    опись архива                  что кладём и под каким именем
    маршрутизация замечаний       что минимально пересчитать

**Двери приходят аргументом, а не импортом.** `orchestrator`, `llm` и
`materials` не импортируются вовсе: правило импорта слоя над оркестратором не
предусматривает («из него не импортирует никто»), а поправка на порядок слоёв —
открытая развилка. Всё, что делает служба — модель, диск, версии, архив, —
приходит объектом `seams.Services`.

`hokoku` — единственное исключение, и оно узкое: правило разреза 2.0.0a4.3
разрешает звать его **как чистый инструмент** (байты и значения, без диска и
проекта). Живёт это исключение в одном файле, `blocks.py`, чтобы проверялось
чтением одного модуля. Проверяется грепом и тестом
(`tests/kadai/test_border.py`): в `packages/kadai/` нет ни `import llm`, ни
`import materials`, ни `import orchestrator`, ни `import docx`, ни
`os.path.join`, ни `open(`, ни дисковых функций `hokoku`.

Состав пакета:

    errors.py    KadaiError, NotReady («сосед ещё не готов»), «похоже на»
    seams.py     швы: кого ждём, по какому адресу, с какой подписью
    blocks.py    единственное место, где зовётся hokoku — чистыми функциями
    profile.py   строение из ответа модели + четыре сита для него
    plan.py      строение + пожелания → стадии и множество остановок
    stages.py    семь стадий, их состояния, единственный механизм остановки
    run.py       те же семь стадий, выполненные дверями: от условия до архива
    status.py    снимок для API (форма ключ в ключ) и хранение хода
    archive.py   опись ZIP, безопасные имена, обязательный «как-это-собрано.txt»
    rework.py    маршруты замечаний и минимальный пересчёт по ним
    __main__.py  python -m kadai: new, run, status, rework, archive

Чего здесь нет намеренно и что ждёт соседей — перечислено в `seams.SEAMS`
поимённо. Недоведённых швов осталось два, и оба не двери, а точность:
отделимость распознанного OCR по кускам (человеку показывается весь текст
условия с пометкой) и отпечаток входа (устарелость блока считается по ключам и
журналу производных, а не по входу). Остальные сведены и зовутся
по-настоящему. Дверь, которой не дали, по-прежнему отказывает `NotReady` с
адресом и подписью, а не возвращает правдоподобную пустоту: пустота доехала бы
до человека под видом результата.

Чего здесь нет и не будет: исполнения кода (песочницы не будет — код
разбирается статически и помечается в архиве как незапускавшийся),
своего хранилища, своей очереди, HTTP и второго канала предупреждений.
"""
from . import blocks, run
from .errors import KadaiError, NotReady, hint, problem
from .seams import SEAMS, Seam, Services, door, method, not_ready, seam
from .profile import (EXPECTS, FORBIDDEN, Kind, MAX_SECTIONS, Profile, SECTION_TYPES,
                      Section, check_structure, compose, norm_key, parse, sections_of,
                      structure_request, structure_schema)
from .plan import Plan, Wishes, pauses_of, plan_of
from .stages import (DONE, RUNNING, SKIPPED, STAGE_NAMES, STAGES, STUMBLED, WAITING,
                     Hold, StageKind, StageState, Work, as_dict, begin, cancel,
                     events_since, finish, new_work, reopen, resume, stage_now, step,
                     stumble)
from .status import empty_spent, save_task, snapshot, spent_of, task
from .archive import (DIR_DIAGRAMS, DIR_SOURCES, Entry, NOTICE, NOT_RUN, check_names,
                      in_dir, notice_text, pack, plan_archive, safe_leaf, solution_md)
from .rework import (BLOCK_ROUTE, REPLAY, ROUTES, Route, changed_entries, inputs_of,
                     plan_rework, route, route_of_block, tags_using_artifact, text_tags)
from .run import Session

__all__ = [
    "KadaiError", "NotReady", "hint", "problem",
    "Seam", "SEAMS", "Services", "seam", "not_ready", "door", "method",
    "Profile", "Kind", "Section", "parse",
    "check_structure", "compose", "structure_schema", "structure_request",
    "EXPECTS", "FORBIDDEN", "MAX_SECTIONS", "SECTION_TYPES", "sections_of", "norm_key",
    "Plan", "Wishes", "plan_of", "pauses_of",
    "STAGES", "STAGE_NAMES", "StageKind", "StageState", "Hold", "Work",
    "WAITING", "RUNNING", "DONE", "STUMBLED", "SKIPPED",
    "new_work", "begin", "step", "finish", "resume", "reopen", "stumble", "cancel",
    "stage_now", "events_since", "as_dict",
    "snapshot", "spent_of", "empty_spent", "save_task", "task",
    "Entry", "NOT_RUN", "NOTICE", "DIR_SOURCES", "DIR_DIAGRAMS",
    "safe_leaf", "in_dir", "check_names", "plan_archive", "notice_text", "solution_md", "pack",
    "Route", "ROUTES", "BLOCK_ROUTE", "REPLAY", "route", "route_of_block",
    "tags_using_artifact", "changed_entries", "text_tags", "inputs_of", "plan_rework",
    "Session",
    "profile", "plan", "stages", "status", "archive", "rework", "seams", "errors",
    "blocks", "run",
]
