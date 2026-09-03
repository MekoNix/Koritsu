"""
kadai (課題, «задание») — сценарий «условие задачи → готовый архив».

На входе условие файлом и пожелания словами, на выходе ZIP с кодом, шаблоном,
решением и отчётом в Word. Единица, которой владеет пакет, — одно задание: у
него есть условие, пожелания, срок жизни и один архив на выходе. Проект в
`orchestrator` — единица хранения; второго слова для единицы смысла в проекте
нет, отсюда и имя. Имя переживает вопрос «а если завтра лабораторная»: курсовая,
реферат, расчётно-графическая — всё это 課題.

**Граница, и она узкая.** `orchestrator` уже хранит работу на диске,
версионирует значения с пометкой источника, собирает промпт, зовёт модель на
трёх уровнях, гоняет ответ через тот же валидатор, что и запрос из интерфейса, и
собирает отчёт. `kadai` не повторяет из этого ничего. Ему остаётся сценарий:

    вид работы данными            какие разделы бывают и что обязательно
    стадии и статус               где стоим, что готово, сколько потрачено
    два режима прохода            одно множество «где остановиться», не две ветки
    опись архива                  что кладём и под каким именем
    маршрутизация замечаний       что минимально пересчитать

**Ни одного импорта соседа.** Двери приходят аргументом (`seams.Services`,
`Project` объектом), а не импортом. Причина — не вкус: правило импорта,
принятое 2026-08-31, слоя над оркестратором не предусматривает вовсе («из него
не импортирует никто»), а поправка на порядок слоёв — открытая развилка
владельца. Пока она не закрыта, `import orchestrator` был бы нарушением
действующего решения, а `import hokoku` — вторым средним слоем, то есть ровно
тем, чего просили избежать. Проверяется это грепом и тестом
(`tests/kadai/test_border.py`): в `packages/kadai/` нет ни `import llm`, ни
`import hokoku`, ни `import materials`, ни `import docx`, ни `os.path.join`.

Состав пакета:

    errors.py    KadaiError, NotReady («сосед ещё не готов»), «похоже на»
    seams.py     швы: кого ждём, по какому адресу, с какой подписью
    profile.py   вид работы данными + четыре сита для сочинённой структуры
    profiles/    сами данные: kursovaya.yaml (в первой версии профиль один)
    plan.py      профиль + пожелания → стадии и множество остановок
    stages.py    семь стадий, их состояния, единственный механизм остановки
    status.py    снимок для API (ключ в ключ по записке Е.4) и хранение хода
    archive.py   опись ZIP, безопасные имена, обязательный «как-это-собрано.txt»
    rework.py    таблица зависимостей замечаний и то, что по ней вычисляется

Чего здесь нет намеренно и что ждёт соседей — перечислено в `seams.SEAMS`
поимённо: разбор условия (Word и OCR в `materials`), сочинение шаблона
(построение DOCX без шаблона в `hokoku`), безтеговая дверь к модели, журнал
производных, хранение хода стадий и сборка ZIP в `Project`. Каждый из них
отказывает `NotReady` с адресом и подписью, а не возвращает правдоподобную
пустоту: пустота доехала бы до человека под видом результата.

Чего здесь нет и не будет: исполнения кода (решение 2026-08-27 цело, песочницы
не будет — код разбирается статически и помечается в архиве как незапускавшийся),
своего хранилища, своей очереди, HTTP и второго канала предупреждений.
"""
from .errors import KadaiError, NotReady, hint, problem
from .seams import SEAMS, Seam, Services, door, method, not_ready, seam
from .profile import (Kind, Profile, Section, available, base_template,
                      check_structure, load, norm_key, parse, sections_of)
from .plan import Plan, Wishes, pauses_of, plan_of
from .stages import (DONE, RUNNING, SKIPPED, STAGE_NAMES, STAGES, STUMBLED, WAITING,
                     Hold, StageKind, StageState, Work, as_dict, begin, cancel,
                     events_since, finish, new_work, resume, stage_now, step, stumble)
from .status import empty_spent, snapshot, spent_of
from .archive import (DIR_DIAGRAMS, DIR_SOURCES, Entry, NOTICE, NOT_RUN, check_names,
                      in_dir, notice_text, pack, plan_archive, safe_leaf, solution_md)
from .rework import (ROUTES, Route, changed_entries, inputs_of, plan_rework, route,
                     tags_using_artifact, text_tags)

__all__ = [
    "KadaiError", "NotReady", "hint", "problem",
    "Seam", "SEAMS", "Services", "seam", "not_ready", "door", "method",
    "Profile", "Kind", "Section", "available", "load", "parse", "base_template",
    "check_structure",
    "sections_of", "norm_key",
    "Plan", "Wishes", "plan_of", "pauses_of",
    "STAGES", "STAGE_NAMES", "StageKind", "StageState", "Hold", "Work",
    "WAITING", "RUNNING", "DONE", "STUMBLED", "SKIPPED",
    "new_work", "begin", "step", "finish", "resume", "stumble", "cancel",
    "stage_now", "events_since", "as_dict",
    "snapshot", "spent_of", "empty_spent",
    "Entry", "NOT_RUN", "NOTICE", "DIR_SOURCES", "DIR_DIAGRAMS",
    "safe_leaf", "in_dir", "check_names", "plan_archive", "notice_text", "solution_md", "pack",
    "Route", "ROUTES", "route", "tags_using_artifact", "changed_entries", "text_tags",
    "inputs_of", "plan_rework",
    "profile", "plan", "stages", "status", "archive", "rework", "seams", "errors",
]
