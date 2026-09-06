"""
routes — история значений и возврат к прошлой версии.

    GET  …/values/{key}/versions        200  все версии тега, старые сверху
    GET  …/values/{key}/versions/{n}    200  шапка версии и само значение
    POST …/values/{key}/rollback        200  вернуть версию {n} (роль editor)
    GET  …/blocks?run=                  200  текущий список блоков решения
    GET  …/blocks/versions              200  все версии списка
    GET  …/blocks/versions/{n}          200  шапка версии и сами блоки
    POST …/blocks/rollback              200  вернуть версию {n} (роль editor)

Шесть маршрутов поверх шести методов `orchestrator.Project`, и своей логики
здесь нет ни строки — это намеренно. История версий живёт на томе (файл версии
создаётся и никогда не заменяется), и всякая попытка службы «помочь» ей —
кэшировать список, хранить номер текущей в базе — завела бы второй ответ на
вопрос «какая версия сейчас», который разошёлся бы с диском на первом же
одновременном прогоне.

**Возврат — это новая версия, а не откат номера** (`Project.rollback`). Отсюда
и `POST`, а не `DELETE`: возврат ничего не удаляет, он дописывает. Клиенту это
видно по ответу — номер в нём **больше** того, к которому вернулись.

**История принадлежит документу, а не работе.** В работе несколько отчётов, у
каждого свои значения и своя история, и какой из них открыт, говорит `?report=`
(идентификатор записи журнала об отчёте). Без него читается единственный
документ работы.

**Чтение — `viewer`, возврат — `editor`.** Разрез тот же, что у значений
(`projects/routes.py`): смотреть историю может всякий, кто видит проект, а
менять то, что покажется в отчёте, — только тот, кому доверили писать.

Коды отказа: `404 not_found` — нет проекта, нет тега или нет такой версии
(одинаково: «версии 7 у тега нет» — тоже «не найдено», и различать это статусом
нечем); `403 forbidden` — роли мало; `409 in_trash` — проект в корзине.
"""
from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

import orchestrator

from ..db import SessionDep
from ..errors import ApiError, NOT_FOUND
from ..projects.routes import ОТЧЁТ, РЕШЕНИЕ, доступный, настройки, открыть
from ..workspaces.deps import CurrentUser
from ..workspaces.service import EDITOR, VIEWER

router = APIRouter(prefix="/projects/{project_id}", tags=["versions"])


class RollbackIn(BaseModel):
    """Тело возврата: номер версии, к которой возвращаемся.

    Тело, а не путь, потому что возврат — действие над тегом, а не обращение к
    версии: `POST …/values/{key}/versions/{n}` читалось бы как «создать версию
    номер n», чего служба не умеет и не должна.
    """

    n: int = Field(ge=1, description="Version number to bring back")


# ── версии значения тега ─────────────────────────────────────────────────────

@router.get("/values/{key}/versions", operation_id="list_value_versions",
            summary="History of one tag value",
            description=(
                "Every version of one tag, oldest first: who wrote it, in "
                "which run, by which model and with which flags. The values "
                "themselves are not here; ask for one version. 400 invalid_id, "
                "404 not_found, 409 in_trash."))
def версии(project_id: str, key: str, request: Request, s: SessionDep,
           user: CurrentUser, report: str = ОТЧЁТ) -> dict:
    """Все версии тега. Без значений: список истории читают, чтобы выбрать."""
    проект = _проект(s, user, project_id, request, VIEWER, report)
    список = проект.versions(key)
    if not список:
        raise ApiError(NOT_FOUND, "Tag has no versions", 404, where="path.key")
    return {"key": список[0].key, "versions": [_шапка(v) for v in список]}


@router.get("/values/{key}/versions/{n}", operation_id="get_value_version",
            summary="One version of a tag value",
            description=(
                "The header of one version and the value itself, in the shape "
                "the report builder reads. 400 invalid_id, 404 not_found, "
                "409 in_trash."))
def версия(project_id: str, key: str, n: int, request: Request, s: SessionDep,
           user: CurrentUser, report: str = ОТЧЁТ) -> dict:
    """Шапка версии и само значение — то, что показывают рядом с «Вернуть»."""
    проект = _проект(s, user, project_id, request, VIEWER, report)
    try:
        шапка, значение = проект.version(key, n)
    except orchestrator.OrchestratorError as беда:
        raise ApiError(NOT_FOUND, str(беда), 404, where="path.n") from None
    return {"key": шапка.key, "version": _шапка(шапка), "value": значение}


@router.post("/values/{key}/rollback", operation_id="rollback_value",
             summary="Bring back an earlier version of a tag",
             description=(
                 "Writes the chosen version again as a new one; nothing is "
                 "deleted, so the answer carries a higher number than asked "
                 "for. Editor role. 400 invalid_id, 403 forbidden, "
                 "404 not_found, 409 in_trash."))
def вернуть(project_id: str, key: str, тело: RollbackIn, request: Request,
            s: SessionDep, user: CurrentUser, report: str = ОТЧЁТ) -> dict:
    """Вернуть значение версии `n` — новой версией (см. докстроку модуля)."""
    проект = _проект(s, user, project_id, request, EDITOR, report)
    try:
        шапка = проект.rollback(key, тело.n)
    except orchestrator.OrchestratorError as беда:
        raise ApiError(NOT_FOUND, str(беда), 404, where="body.n") from None
    return {"key": шапка.key, "version": _шапка(шапка), "restored_from": тело.n}


# ── версии списка блоков (живой режим) ───────────────────────────────────────

@router.get("/blocks", operation_id="get_project_blocks",
            summary="Current block list of a project without a template",
            description=(
                "The ordered list of named blocks a template-less project is "
                "made of. Empty when the project has never had one. "
                "400 invalid_id, 404 not_found, 409 in_trash."))
def блоки(project_id: str, request: Request, s: SessionDep,
          user: CurrentUser, run: str = РЕШЕНИЕ) -> dict:
    """Текущий список блоков решения. Пусто — списка ещё не заводили."""
    проект = _проект(s, user, project_id, request, VIEWER, solution=run)
    return {"blocks": проект.blocks()}


@router.get("/blocks/versions", operation_id="list_block_versions",
            summary="History of the block list",
            description=(
                "Every version of the block list, oldest first. The list is "
                "versioned whole: half the edits move blocks around, and a "
                "per-block version answers nothing about that. 400 invalid_id, "
                "404 not_found, 409 in_trash."))
def версии_блоков(project_id: str, request: Request, s: SessionDep,
                  user: CurrentUser, run: str = РЕШЕНИЕ) -> dict:
    """Все версии списка блоков. Без самих блоков — по той же причине, что у тегов."""
    проект = _проект(s, user, project_id, request, VIEWER, solution=run)
    return {"versions": [_шапка_блоков(v) for v in проект.block_versions()]}


@router.get("/blocks/versions/{n}", operation_id="get_block_version",
            summary="One version of the block list",
            description=(
                "The header of one version and the blocks it held. "
                "400 invalid_id, 404 not_found, 409 in_trash."))
def версия_блоков(project_id: str, n: int, request: Request, s: SessionDep,
                  user: CurrentUser, run: str = РЕШЕНИЕ) -> dict:
    проект = _проект(s, user, project_id, request, VIEWER, solution=run)
    try:
        шапка, блоки_версии = проект.block_version(n)
    except orchestrator.OrchestratorError as беда:
        raise ApiError(NOT_FOUND, str(беда), 404, where="path.n") from None
    return {"version": _шапка_блоков(шапка), "blocks": блоки_версии}


@router.post("/blocks/rollback", operation_id="rollback_blocks",
             summary="Bring back an earlier block list",
             description=(
                 "Writes the chosen version of the whole list again as a new "
                 "one. Editor role. 400 invalid_id, 403 forbidden, "
                 "404 not_found, 409 in_trash."))
def вернуть_блоки(project_id: str, тело: RollbackIn, request: Request,
                  s: SessionDep, user: CurrentUser, run: str = РЕШЕНИЕ) -> dict:
    проект = _проект(s, user, project_id, request, EDITOR, solution=run)
    try:
        шапка = проект.rollback_blocks(тело.n)
    except orchestrator.OrchestratorError as беда:
        raise ApiError(NOT_FOUND, str(беда), 404, where="body.n") from None
    return {"version": _шапка_блоков(шапка), "restored_from": тело.n}


# ── общее ────────────────────────────────────────────────────────────────────

def _проект(s, user, project_id: str, request: Request, роль: str,
            report: str = "", solution: str = ""):
    """Каталог проекта как `orchestrator.Project`, если роли хватает.

    Обе двери — чужие и взяты как есть: `доступный` (строка, роль, корзина) и
    `открыть` (каталог на томе) живут в `projects/routes.py`, и повторять их
    здесь значило бы завести второе мнение о том, кому проект виден.

    `report` — какой документ работы открыт: история значения принадлежит
    отчёту, а не работе, и один список версий на все отчёты сразу показывал бы
    правки соседнего документа. `solution` — то же для решения: список блоков
    принадлежит ему, и в работе с двумя задачами он у каждой свой.
    """
    p = доступный(s, user, project_id, роль)
    return открыть(p, настройки(request), report, solution)


def _шапка(v) -> dict:
    """Версия значения наружу. Самоописанная запись — как она лежит на диске.

    Ни одного поля не выбрасываем: `endpoint`, `model`, `prompt_hash` и
    `manifest_version` — это и есть ответ на вопрос «чем объяснить это
    значение», ради которого они пишутся (`orchestrator.Version`).
    """
    return {"n": v.n, "key": v.key, "at": v.at, "source": v.source,
            "run": v.run, "flags": list(v.flags or ()), "endpoint": v.endpoint,
            "model": v.model, "prompt_hash": v.prompt_hash,
            "manifest_version": v.manifest_version, "stop": v.stop,
            "usage": dict(v.usage or {})}


def _шапка_блоков(v) -> dict:
    """Версия списка блоков наружу. `note` — зачем эта правка, `count` — сколько
    блоков в ней было: по ним и выбирают, куда возвращаться."""
    return {"n": v.n, "at": v.at, "source": v.source, "note": v.note,
            "run": v.run, "count": v.count}


__all__ = ["router", "RollbackIn"]
