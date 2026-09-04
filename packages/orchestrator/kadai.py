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


def main(argv=None) -> int:
    """Точка входа. Разбор аргументов и коды возврата — сценария, не наши."""
    from kadai.__main__ import main as scenario

    return scenario(argv, services_factory=services, prog="python -m orchestrator.kadai")


if __name__ == "__main__":                      # pragma: no cover
    raise SystemExit(main())


__all__ = ["blank_template", "services", "main"]
