"""
routes — `/api/projects`: создание, список, карточка, корзина и значения тегов.

Коды отказа этого модуля:

    unauthorized     401  вошедшего нет
    invalid_id       400  идентификатор не uuid4
    not_found        404  нет такого проекта, или спрашивающий не в пространстве
    forbidden        403  участник есть, роли мало (`viewer` шлёт `PUT`)
    in_trash         409  пространство в корзине / проект уже в корзине
    not_in_trash     409  восстанавливать нечего
    bad_template     400  принесённый DOCX не читается
    invalid_value    400  значение тега не объект JSON
    project_exists   409  каталог по этим uuid уже занят

**Проверка доступа идёт через пространство, а не через проект.** Проект своей
роли не имеет: он принадлежит пространству (§1), и вторая таблица прав на
проекте разошлась бы с первой на первом же переносе проекта между
пространствами. Отсюда порядок в каждом обработчике: найти строку проекта →
`require_role` на его `workspace_id` → работать.

**Пути наружу не уезжают.** Карточка отдаёт `bytes_used`, а не путь; беда от
оркестратора (в её тексте бывает путь на томе) наружу идёт как `bad_template`
без подробностей, а настоящая — в журнал (§3, `log.py`).

Значения тегов — тонкая обёртка над `orchestrator.Project`: `GET` отдаёт
`project.values()`, `PUT` зовёт `set_value(..., source="manual")`. Своей модели
у службы для них нет и не будет — решение владельца §7 третьего круга: значения
остаются файлами, база держит индекс. История версий, откат и `source` живут в
оркестраторе; ночь 2 добавит сюда маршруты поверх них, но не второе описание.
"""
from __future__ import annotations

import os
import shutil

from fastapi import APIRouter, File, Form, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select

import orchestrator

from ..db import SessionDep
from ..errors import ApiError
from ..ids import check_id
from ..log import беды
from ..settings import Settings
from ..workspaces.deps import CurrentUser
from ..workspaces.service import EDITOR, VIEWER, iso, require_role
from .models import NAME_MAX, Project
from .service import dir_for, dir_size, get_row, restore
from .service import trash as в_корзину   # имя занято параметром запроса `trash`

router = APIRouter(prefix="/projects", tags=["projects"])

BAD_TEMPLATE = "bad_template"
INVALID_VALUE = "invalid_value"
PROJECT_EXISTS = "project_exists"
IN_TRASH = "in_trash"


class ProjectNameIn(BaseModel):
    """Тело переименования. Имя по-английски, как у соседей: оно уезжает в
    OpenAPI и становится именем типа в клиенте сайта (§5)."""

    name: str = Field(min_length=1, max_length=NAME_MAX)


def настройки(request: Request) -> Settings:
    return request.app.state.settings


def карточка(p: Project, settings: Settings, *, теги: bool = False) -> dict:
    """Проект наружу. Пути в ответе нет — только идентификаторы и число байт.

    Теги (`project.keys()`) читаются с диска, поэтому в списке их нет: список из
    сотни проектов означал бы сотню обходов каталогов ради колонки, которую в
    списке не показывают.
    """
    каталог = dir_for(settings, p.owner_id, p.id)
    тело = {"id": p.id, "workspace_id": p.workspace_id, "owner_id": p.owner_id,
            "name": p.name, "created_at": iso(p.created_at),
            "updated_at": iso(p.updated_at), "deleted_at": iso(p.deleted_at),
            "purge_after": iso(p.purge_after), "bytes_used": dir_size(каталог)}
    if теги:
        тело["keys"] = orchestrator.Project(каталог).keys()
    return тело


def открыть(p: Project, settings: Settings) -> orchestrator.Project:
    """Каталог проекта как `orchestrator.Project`.

    Отдельной функцией, потому что зовут её пять обработчиков, а беда у всех
    одна: каталога нет. Наружу она уходит как 404 — для клиента «проекта нет»
    и «каталог пропал» одно и то же событие, а разбираться в разнице по журналу
    нам, а не ему.
    """
    каталог = dir_for(settings, p.owner_id, p.id)
    try:
        return orchestrator.Project(каталог)
    except Exception:                                   # noqa: BLE001
        беды.exception("проект %s: каталога нет на томе", p.id)
        raise ApiError("not_found", "Project not found", 404,
                       where="path.project_id") from None


@router.post("", status_code=201, operation_id="create_project",
             summary="Create a project in a workspace",
             description=(
                 "Creates a project and its directory on the volume. Multipart: "
                 "the name and an optional DOCX template; without a template "
                 "the report is built from scratch. Editor role in the "
                 "workspace. 400 bad_template, 403 forbidden, 404 not_found, "
                 "409 project_exists."))
def создать(request: Request, s: SessionDep, user: CurrentUser,
            workspace_id: str = Form(...), name: str = Form(""),
            template: UploadFile | None = File(None)) -> dict:
    """Новый проект: строка в базе и каталог на томе.

    Форма `multipart`, а не JSON, потому что вместе с именем приходит файл
    шаблона (§2: загрузка телом запроса). Шаблон **необязателен**: без него
    оркестратор строит документ с нуля (`Project.create(template=None)`), и
    человек, у которого образца под рукой нет, всё равно заводит проект.

    Порядок — сначала база, потом диск, и это не случайность: `id` каталога
    берётся из строки, а строка при беде на диске откатится сама
    (сессия на запрос, `db.session`). Обратный порядок оставил бы на томе
    каталог, о котором база не знает.
    """
    settings = настройки(request)
    ws = require_role(s, user.id, check_id(workspace_id, where="body.workspace_id"),
                      EDITOR, where="body.workspace_id")
    байты = None
    if template is not None and template.filename:
        байты = template.file.read()
    p = Project(workspace_id=ws.id, owner_id=user.id, name=name.strip() or "Project")
    s.add(p)
    s.flush()

    каталог = dir_for(settings, p.owner_id, p.id)
    if os.path.isdir(каталог) and os.listdir(каталог):
        # Совпадение двух uuid4 невероятно; каталог тут означает мусор от
        # прежнего прогона, и молча писать в него — терять чужие файлы.
        raise ApiError(PROJECT_EXISTS, "Project directory is not empty", 409)
    os.makedirs(каталог, exist_ok=True)
    try:
        orchestrator.Project.create(каталог, template=байты, name=p.name)
    except Exception:                                   # noqa: BLE001
        # Подробности — в журнал: в тексте беды оркестратора стоит путь на томе,
        # а клиенту про раскладку тома знать нечего (§3).
        беды.exception("проект %s: шаблон не принят", p.id)
        shutil.rmtree(каталог, ignore_errors=True)
        raise ApiError(BAD_TEMPLATE, "Template is not a readable DOCX file", 400,
                       where="body.template") from None
    return карточка(p, settings, теги=True)


@router.get("", operation_id="list_projects",
            summary="List projects of a workspace",
            description=(
                "Lists the projects of one workspace; `trash=true` lists the "
                "ones in the trash instead. 400 invalid_id, 404 not_found."))
def список(request: Request, workspace_id: str, s: SessionDep, user: CurrentUser,
           trash: bool = False) -> dict:
    """Проекты пространства. `trash=true` — те, что лежат в корзине."""
    settings = настройки(request)
    ws = require_role(s, user.id, check_id(workspace_id, where="query.workspace_id"),
                      VIEWER, where="query.workspace_id", allow_deleted=trash)
    запрос = select(Project).where(Project.workspace_id == ws.id)
    запрос = запрос.where(Project.deleted_at.is_not(None) if trash
                          else Project.deleted_at.is_(None))
    строки = s.scalars(запрос.order_by(Project.created_at)).all()
    return {"projects": [карточка(p, settings) for p in строки]}


@router.get("/{project_id}", operation_id="get_project",
            summary="One project",
            description=(
                "One project: name, workspace, the tag keys of its manifest and "
                "the size of its directory. Paths are never returned. "
                "400 invalid_id, 404 not_found, 409 in_trash."))
def карточка_одного(project_id: str, request: Request, s: SessionDep,
                    user: CurrentUser) -> dict:
    """Карточка: имя, пространство, теги из манифеста, размер каталога."""
    settings = настройки(request)
    p = доступный(s, user, project_id, VIEWER)
    return карточка(p, settings, теги=True)


@router.patch("/{project_id}", operation_id="rename_project",
              summary="Rename a project",
              description=(
                  "Renames a project, in the database and in its settings on "
                  "the volume. Editor role. 403 forbidden, 404 not_found, "
                  "409 in_trash, 422 validation_failed."))
def переименовать(project_id: str, тело: ProjectNameIn, request: Request,
                  s: SessionDep, user: CurrentUser) -> dict:
    settings = настройки(request)
    p = доступный(s, user, project_id, EDITOR)
    p.name = тело.name.strip()
    s.flush()
    # Имя лежит и в `project.json`: его читает `build_report`, а не мы. Один
    # источник тут завести нельзя — база нужна для списка без обхода тома, —
    # поэтому обновляем оба сразу, в одном обработчике.
    проект = открыть(p, settings)
    настройки_проекта = проект.settings()
    настройки_проекта["name"] = p.name
    проект.save_settings(настройки_проекта)
    return карточка(p, settings)


@router.delete("/{project_id}", operation_id="trash_project",
               summary="Move a project to the trash",
               description=(
                   "Moves a project to the trash; its directory stays on the "
                   "volume until purge_after. Editor role. 403 forbidden, "
                   "404 not_found, 409 in_trash."))
def удалить(project_id: str, request: Request, s: SessionDep,
            user: CurrentUser) -> dict:
    """В корзину. Каталог остаётся на томе до `purge_after` (§2: десять дней)."""
    settings = настройки(request)
    p = доступный(s, user, project_id, EDITOR)
    в_корзину(s, p, settings)
    return карточка(p, settings)


@router.post("/{project_id}/restore", operation_id="restore_project",
             summary="Restore a project from the trash",
             description=(
                 "Restores a project from the trash. Editor role. "
                 "403 forbidden, 404 not_found."))
def восстановить(project_id: str, request: Request, s: SessionDep,
                 user: CurrentUser) -> dict:
    settings = настройки(request)
    p = доступный(s, user, project_id, EDITOR, allow_deleted=True)
    restore(s, p)
    return карточка(p, settings)


# ── значения тегов (тонко, поверх orchestrator) ──────────────────────────────

@router.get("/{project_id}/values", operation_id="get_project_values",
            summary="Current tag values of a project",
            description=(
                "The current value of every tag of the project, in the shape "
                "the report builder reads. 400 invalid_id, 404 not_found, "
                "409 in_trash."))
def значения(project_id: str, request: Request, s: SessionDep,
             user: CurrentUser) -> dict:
    """Текущие значения всех тегов. Форма — та же, что у `hokoku.wire`."""
    settings = настройки(request)
    p = доступный(s, user, project_id, VIEWER)
    return {"values": открыть(p, settings).values()}


@router.put("/{project_id}/values/{key}", operation_id="set_project_value",
            summary="Set one tag value by hand",
            description=(
                "Writes one tag value as a new version marked source=manual; "
                "previous versions are kept. The body is the value itself, a "
                "JSON object. Editor role. 400 invalid_value, 403 forbidden, "
                "404 not_found, 409 in_trash."))
def поставить(project_id: str, key: str, value: dict, request: Request,
              s: SessionDep, user: CurrentUser) -> dict:
    """Значение тега рукой человека: `source="manual"`.

    `source` ставим здесь, а не берём из тела: значение, пришедшее по этому
    маршруту, написал человек — и разрешить клиенту назвать себя `agent` значило
    бы отдать наружу пометку, ради которой `source` и заведён (прогон уровня 2
    не трогает чужое).

    Аргумент тела назван по-английски, в отличие от прочих имён обработчиков:
    имя аргумента-тела уезжает в OpenAPI заголовком схемы (было `Значение`), а
    оттуда — в клиент сайта, где кириллицу ни набрать, ни отличить от соседней
    (та же причина, по которой формы запроса называются `ProjectNameIn`).
    """
    settings = настройки(request)
    p = доступный(s, user, project_id, EDITOR)
    try:
        версия = открыть(p, settings).set_value(key, value, source="manual")
    except orchestrator.OrchestratorError:
        raise ApiError(INVALID_VALUE, "Tag value must be a JSON object", 400,
                       where="body") from None
    return {"key": версия.key, "version": версия.n, "source": версия.source,
            "at": версия.at}


# ── общее ────────────────────────────────────────────────────────────────────

def доступный(s, user, project_id: str, min_role: str, *,
              allow_deleted: bool = False) -> Project:
    """Строка проекта, если спрашивающему до неё есть дело.

    Порядок проверок важен и такой: сначала строка (её нет — 404), потом роль в
    её пространстве (не участник — тоже 404, роли мало — 403), и только потом
    корзина. Обратный порядок отвечал бы «в корзине» на чужой проект, то есть
    рассказывал бы о существовании чужого (§3).
    """
    p = get_row(s, project_id)
    require_role(s, user.id, p.workspace_id, min_role, where="path.project_id",
                 allow_deleted=allow_deleted)
    if p.deleted_at is not None and not allow_deleted:
        raise ApiError(IN_TRASH, "Project is in the trash", 409,
                       where="path.project_id")
    return p


__all__ = ["router"]
