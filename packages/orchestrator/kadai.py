"""
`python -m orchestrator.kadai` — тот же сценарий, но с уже собранными дверями.

Команды и их разбор живут в `kadai.__main__` и здесь не повторяются: у
сценария один разбор аргументов, и второй разошёлся бы с ним на первом же новом
ключе. Здесь ровно то, чего сценарий сделать не может, — **собрать двери**:
открыть каталог проектом, связать его с endpoint'ом и отдать
`kadai.__main__.main` фабрикой.

Почему обёртка отдельным модулем, а не переменной окружения. Переменная
(`KADAI_SERVICES=orchestrator.doors:kadai_services`) остаётся и работает — она
единственный способ позвать `python -m kadai` руками, ничего не зная про
соседей. Но владельцу, который гоняет всю систему целиком, ставить переменную
себе же незачем: он и так знает, кто собирает двери. Отсюда две точки входа с
одним разбором аргументов и одной фабрикой, а не два CLI.

Направление импорта здесь единственно возможное и то же, что у `doors`:
**`orchestrator` знает про `kadai`, `kadai` про `orchestrator` — нет** (решение
2026-08-31). Импорт сценария стоит внутри `main`: `import orchestrator` не
должен падать оттого, что в надстройке над ним опечатка.

Путей этот файл не строит и не разбирает: каталог приходит строкой от человека
и уезжает в `Project` как есть. Всё, что про раскладку каталога, знает
`project.py`, и второго знающего в службе не заводится.
"""
from __future__ import annotations

import hokoku

from . import doors as doors_mod
from .project import Project

# Заготовка DOCX для нового проекта: пустой документ без единого тега.
#
# Она нужна потому, что `Project.create` строит манифест по шаблону, а у живого
# режима шаблона нет вовсе — работа это список блоков, и документ собирается из
# него (`hokoku.live.work_template`). Пустой шаблон и есть честная запись этого
# положения: тегов ноль, манифест пуст, и ни один шаблонный путь на такой проект
# не позовётся молча — ему нечего заполнять.
def blank_template() -> bytes:
    """Пустой DOCX для проекта живого режима. Своего DOCX здесь не рисуется."""
    return hokoku.live.work_template(hokoku.Work())


def services(path: str, *, endpoint: str = "", create: bool = False):
    """Фабрика дверей той подписи, которую ждёт `kadai.__main__.main`.

        factory(path, *, endpoint="", create=False) -> kadai.Services

    `create=True` бывает только у команды `new`, и решает, что значит «создать
    поверх существующего», не она, а `Project.create` — он на это отказывает.
    Разрешить создание здесь значило бы завести второе мнение о том, когда
    проект стирается.

    Endpoint, не названный в командной строке, берётся из настроек проекта: он
    записан туда при создании, и переспрашивать его человеку на каждой команде
    незачем.
    """
    project = Project.create(path, template=blank_template(), endpoint=endpoint) \
        if create else Project(path)
    return doors_mod.kadai_services(
        project, endpoint=endpoint or str(project.settings().get("endpoint") or ""))


# ── тот же сценарий, но из кода, а не из командной строки ────────────────────
#
# Три функции ниже нужны службе (`api/runs/handlers/kadai_*.py`) и ровно затем,
# чтобы служба **не импортировала `kadai`**. Направление импорта закреплено
# решением 2026-08-31: соседей знает только оркестратор. Не будь этих трёх
# обёрток, очередь заданий импортировала бы сценарий напрямую, и стрелка
# зависимостей развернулась бы на первом же обработчике.
#
# Разбора аргументов здесь нет и не будет: он один и живёт в `kadai.__main__`.
# Здесь только то, чего у командной строки нет вовсе, — покадровый доклад о
# стадиях (`on_stage`), без которого служба не смогла бы показать ход работы в
# потоке событий.

def stage_names() -> tuple:
    """Имена стадий по порядку. Служба рисует по ним полоску и считает шаги."""
    from kadai.stages import STAGE_NAMES

    return tuple(STAGE_NAMES)


def work(project, *, endpoint: str, wishes: dict | None = None,
         until: str | None = None, on_stage=None, stop=None) -> dict:
    """Завести или продолжить работу `kadai` и пройти стадии. → снимок.

    Работа заводится один раз на проект: есть запись о задании — продолжаем
    (`run.load`), нет — заводим (`run.new`). Решать это по флагу от вызывающего
    нельзя: «завести поверх заведённой» стёрло бы ход уже сделанных стадий, а
    узнал бы об этом человек по счёту за повторное решение задачи.

    Стадии проходятся **по одной**, а не одним `run(session)`, и это не
    дробление ради дробления: `run` внутри не докладывает никому, а показать
    ход работы человеку надо в тот момент, когда стадия кончилась, а не когда
    кончились все. Форма шага та же, что у CLI (`run(session, until=имя)`), и
    второго механизма остановки здесь не заводится — `until` из пожеланий
    по-прежнему решает `plan.pause_after`.

    `on_stage(имя, снимок)` зовётся после каждой стадии; `stop()` — «пора
    остановиться» (отмена задания): спрашивается между стадиями, где остановка
    ничего не стоит — сделанное сохранено, следующее не начато.
    """
    from kadai import run as run_mod, status as status_mod
    from kadai.plan import Wishes

    services = doors_mod.kadai_services(project, endpoint=endpoint)
    сессия = (run_mod.load(services) if status_mod.task(project)
              else run_mod.new(services, wishes=Wishes(**dict(wishes or {}))))

    имена = stage_names()
    предел = имена.index(until) if until in имена else len(имена) - 1
    for имя in имена[:предел + 1]:
        if stop is not None and stop():
            break
        run_mod.run(сессия, until=имя)
        if on_stage is not None:
            on_stage(имя, run_mod.snapshot(сессия))
        if сессия.work.state != "running":
            break
    return run_mod.snapshot(сессия)


def rework(project, *, endpoint: str, note: str, block: str | None = None,
           kind: str | None = None) -> dict:
    """Замечание человека → минимальный пересчёт → снимок.

    Что именно переигрывается, решает `kadai.rework.apply` (маршруты замечаний
    и их честная цена записаны там). Здесь — только сборка дверей и снимок
    после: служба должна отдать человеку то же, что показала бы командная
    строка, и вторым описанием «что случилось» этого не добиться.
    """
    from kadai import rework as rework_mod, run as run_mod

    services = doors_mod.kadai_services(project, endpoint=endpoint)
    сессия = run_mod.load(services)
    итог = rework_mod.apply(сессия, note=note, block=block, kind=kind)
    return {"rework": итог, "snapshot": run_mod.snapshot(сессия)}


def main(argv=None) -> int:
    """Точка входа. Разбор аргументов и коды возврата — сценария, не наши."""
    from kadai.__main__ import main as scenario

    return scenario(argv, services_factory=services, prog="python -m orchestrator.kadai")


if __name__ == "__main__":                      # pragma: no cover
    raise SystemExit(main())


__all__ = ["blank_template", "services", "stage_names", "work", "rework", "main"]
