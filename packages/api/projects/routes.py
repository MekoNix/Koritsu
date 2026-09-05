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
    unknown_module   400  названного модуля служба не отдаёт
    invalid_value    400  значение тега не объект JSON или не по форме своего типа
    unknown_tag      404  тега с таким ключом в бланке работы нет
    project_exists   409  каталог по этим uuid уже занят

**Проверка доступа идёт через пространство, а не через проект.** Проект своей
роли не имеет: он принадлежит пространству, и вторая таблица прав на
проекте разошлась бы с первой на первом же переносе проекта между
пространствами. Отсюда порядок в каждом обработчике: найти строку проекта →
`require_role` на его `workspace_id` → работать.

**Пути наружу не уезжают.** Карточка отдаёт `bytes_used`, а не путь; беда от
оркестратора (в её тексте бывает путь на томе) наружу идёт как `bad_template`
без подробностей, а настоящая — в журнал (`log.py`).

**Форму значения проверяет оркестратор, а не этот файл.** До сих пор
`PUT` спрашивал одно — объект ли это, — и таблица без `rows`, картинка без
`artifact` и формула без `latex` ложились на том как есть; обнаруживалось это
сборкой отчёта, то есть через задание, деньги и пять минут. Теперь значение
разбирает `Project.check_value` — дверь к тому же разбору, которым значение
прочтёт сборщик, — и отказ приходит сразу, с `where` на поле, которое не так.
Второго описания «годного значения» при этом не заводится ни строки, и движок
отчётов в службу не тянется: правило разреза запрещает ей знать про него вовсе.

**Объявленный тип тега здесь не сверяется** — намеренно. Тип в манифесте часто
угадан по метке (его предлагает движок отчётов по слову в метке), и отказать
человеку, поставившему картинку в тег, который служба сочла схемой, значило бы
защищать догадку от правды. Расхождение видно там, где оно чем-то грозит: перед
сборкой (проверка значений против манифеста), и там же его показывают.

Значения тегов — тонкая обёртка над `orchestrator.Project`: `GET` отдаёт
`project.values()`, `PUT` зовёт `set_value(..., source="manual")`. Своей модели
у службы для них нет и не будет: значения остаются файлами, база держит индекс.
История версий, откат и `source` живут в оркестраторе; маршруты службы ложатся
поверх них, но второго описания не заводят.
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
from .models import MODULE_LEN, NAME_MAX, Project
from .service import dir_for, dir_size, get_row, restore
from .service import trash as в_корзину   # имя занято параметром запроса `trash`

router = APIRouter(prefix="/projects", tags=["projects"])

BAD_TEMPLATE = "bad_template"
INVALID_VALUE = "invalid_value"
PROJECT_EXISTS = "project_exists"
IN_TRASH = "in_trash"
UNKNOWN_MODULE = "unknown_module"
UNKNOWN_TAG = "unknown_tag"

# Потолок задания на тег. Задание пишет человек, читает модель, и живёт оно в
# манифесте на томе: без потолка одно поле формы могло бы раздуть манифест до
# мегабайтов, которые потом уезжают в каждый запрос к модели.
PROMPT_MAX = 4000


class TagPromptIn(BaseModel):
    """Тело правки задания на тег. Пустая строка — «задания нет»."""

    prompt: str = Field(
        max_length=PROMPT_MAX,
        description=("What the model is told to write into this tag. Stored in "
                     "the manifest of the work, so it outlives a single run."))


class ProjectPatchIn(BaseModel):
    """Тело правки работы: имя и модуль, оба необязательные.

    Имя по-английски, как у соседей: оно уезжает в OpenAPI и становится именем
    типа в клиенте сайта.

    Оба поля необязательны, и это не «сойдёт и так»: правок у работы две и
    делаются они из разных мест — имя правит диалог переименования, модуль
    выбирается на карточке. Требовать оба сразу значило бы, что смена модуля
    перепишет имя тем, что было в форме на момент открытия.

    Пустое тело — не отказ, а «ничего не менять»: отвечать `422` на просьбу
    ничего не делать незачем, а состояние работы от неё то же самое.
    """

    name: str | None = Field(default=None, min_length=1, max_length=NAME_MAX)
    module: str | None = Field(
        default=None, max_length=MODULE_LEN,
        description=("Module this work is done with, from GET /api/modules. "
                     "An empty string clears it."))


def настройки(request: Request) -> Settings:
    return request.app.state.settings


def манифест(проект: orchestrator.Project):
    """Манифест работы или `None`, если файла на томе нет.

    `None`, а не отказ: карточку работы нельзя ронять из-за недостающего файла
    — беда уходит в журнал, а человек видит работу без тегов, что и есть правда
    о ней.
    """
    try:
        return проект.manifest()
    except orchestrator.OrchestratorError:
        беды.warning("проект %s: манифеста нет — теги не показываю", проект.path)
        return None


def теги_шаблона(проект: orchestrator.Project) -> list[tuple]:
    """Теги шаблона парами `(ключ, запись манифеста)`, в порядке документа.

    **Манифест, а не `project.keys()`.** Второй перечисляет ключи, у которых уже
    есть версия значения, то есть на новом проекте отдаёт пустоту — а вопрос
    «какие теги в этой работе» задаётся ровно до первого прогона: без ответа на
    него слева нечего показать и нечего заполнять. Теги манифеста этот вопрос
    и есть.

    Тег, которого в шаблоне больше нет (`missing`), не показывается: его запись
    держится ради промпта, а заполнять его некуда — в документе для него места
    не осталось.

    Манифеста нет — пустой список, а не отказ: карточку проекта нельзя ронять
    из-за того, что на томе недостаёт файла; беда уходит в журнал, а человек
    видит проект без тегов, что и есть правда о нём.
    """
    m = манифест(проект)
    if m is None:
        return []
    return [(ключ, спец) for ключ, спец in m.tags.items() if not спец.missing]


def карточка(p: Project, settings: Settings, *, теги: bool = False) -> dict:
    """Проект наружу. Пути в ответе нет — только идентификаторы и число байт.

    Теги читаются с диска, поэтому в списке их нет: список из сотни проектов
    означал бы сотню обходов каталогов ради колонки, которую в списке не
    показывают.
    """
    каталог = dir_for(settings, p.owner_id, p.id)
    тело = {"id": p.id, "workspace_id": p.workspace_id, "owner_id": p.owner_id,
            "name": p.name, "module": p.module, "created_at": iso(p.created_at),
            "updated_at": iso(p.updated_at), "deleted_at": iso(p.deleted_at),
            "purge_after": iso(p.purge_after), "bytes_used": dir_size(каталог)}
    if теги:
        тело["keys"] = [ключ for ключ, _ in теги_шаблона(orchestrator.Project(каталог))]
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
                 "the name and, optionally, either a DOCX template or the id of "
                 "one of your saved templates (`template_id`); without either "
                 "the report is built from scratch. `module` says which module "
                 "the work is done with (from GET /api/modules) and may be left "
                 "out. Editor role in the workspace. 400 bad_template, "
                 "400 unknown_module, 403 forbidden, 404 not_found, "
                 "409 project_exists."))
def создать(request: Request, s: SessionDep, user: CurrentUser,
            workspace_id: str = Form(...), name: str = Form(""),
            module: str = Form(""),
            template: UploadFile | None = File(None),
            template_id: str | None = Form(None)) -> dict:
    """Новый проект: строка в базе и каталог на томе.

    Форма `multipart`, а не JSON, потому что вместе с именем приходит файл
    шаблона (загрузка телом запроса). Шаблон **необязателен**: без него
    оркестратор строит документ с нуля (`Project.create(template=None)`), и
    человек, у которого образца под рукой нет, всё равно заводит проект.

    Шаблон приходит одним из двух способов: файлом (как раньше) или
    идентификатором своего сохранённого шаблона (`template_id`, подпакет
    `api.templates`). Второй способ **копирует** байты в проект, а не ссылается
    на строку: работа не должна ломаться оттого, что человек убрал шаблон из
    своего списка через месяц.

    Оба сразу — отказ, а не «файл главнее»: молча выбранный за человека шаблон
    — это чужой ГОСТ в готовой работе, и заметят его на кафедре. Отказ идёт
    кодом `bad_template`, а не своим новым: с точки зрения клиента беда одна —
    «шаблон не принят», и разбирать её по двум кодам ему незачем.

    `module` — каким модулем эта работа делается. Поле, а не догадка по тому,
    есть ли у работы теги шаблона: работа, где сделан и отчёт, и задание, ломала
    любую догадку, а главная модуля обязана показывать свои работы, а не все
    подряд. Пусто — законно: работу заводят раньше, чем решают, чем её делать.

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
    if (template_id or "").strip():
        if байты is not None:
            raise ApiError(BAD_TEMPLATE,
                           "Send either a template file or template_id, not both",
                           400, where="body.template_id")
        # Импорт внутри обработчика: подпакет шаблонов тянет оркестратор и
        # приёмник материалов, а этот модуль читает `api.models` при сборке
        # приложения — на уровне модуля вышел бы круг импортов.
        from ..templates import service as шаблоны              # noqa: PLC0415

        байты = шаблоны.байты(
            settings, шаблоны.найти(s, user.id, template_id.strip(),
                                    where="body.template_id"))
    p = Project(workspace_id=ws.id, owner_id=user.id,
                name=name.strip() or "Project",
                module=проверить_модуль(module, where="body.module"))
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
        # а клиенту про раскладку тома знать нечего.
        беды.exception("проект %s: шаблон не принят", p.id)
        shutil.rmtree(каталог, ignore_errors=True)
        raise ApiError(BAD_TEMPLATE, "Template is not a readable DOCX file", 400,
                       where="body.template") from None
    return карточка(p, settings, теги=True)


@router.get("", operation_id="list_projects",
            summary="List projects of a workspace",
            description=(
                "Lists the projects of one workspace; `trash=true` lists the "
                "ones in the trash instead, `module` narrows the list down to "
                "the works done with one module. 400 invalid_id, "
                "400 unknown_module, 404 not_found."))
def список(request: Request, workspace_id: str, s: SessionDep, user: CurrentUser,
           trash: bool = False, module: str = "") -> dict:
    """Проекты пространства. `trash=true` — те, что лежат в корзине.

    `module` — отбор для главной страницы модуля: она показывает свои работы, а
    не все подряд. Отбором, а не своим маршрутом у каждого модуля: список
    проектов один, и четыре его копии разошлись бы на первом же новом столбце.
    """
    settings = настройки(request)
    ws = require_role(s, user.id, check_id(workspace_id, where="query.workspace_id"),
                      VIEWER, where="query.workspace_id", allow_deleted=trash)
    запрос = select(Project).where(Project.workspace_id == ws.id)
    if module.strip():
        запрос = запрос.where(
            Project.module == проверить_модуль(module, where="query.module",
                                               пусто_можно=False))
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
              summary="Rename a project or say which module it is done with",
              description=(
                  "Changes the name of a project, in the database and in its "
                  "settings on the volume, and the module it is done with. "
                  "Both fields are optional; an empty body changes nothing. "
                  "Editor role. 400 unknown_module, 403 forbidden, "
                  "404 not_found, 409 in_trash, 422 validation_failed."))
def переименовать(project_id: str, тело: ProjectPatchIn, request: Request,
                  s: SessionDep, user: CurrentUser) -> dict:
    """Имя и модуль работы. Имя правится в двух местах сразу — база и том.

    Имя `rename_project` осталось прежним намеренно: это тот же самый маршрут,
    и переименование его сменило бы имя метода в сгенерированном клиенте ради
    второго поля.
    """
    settings = настройки(request)
    p = доступный(s, user, project_id, EDITOR)
    if тело.module is not None:
        p.module = проверить_модуль(тело.module, where="body.module")
    if тело.name is None:
        s.flush()
        return карточка(p, settings)
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
    """В корзину. Каталог остаётся на томе до `purge_after` (десять дней)."""
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


# ── теги и их значения (тонко, поверх orchestrator) ──────────────────────────

@router.get("/{project_id}/tags", operation_id="list_project_tags",
            summary="Tags of the project template",
            description=(
                "Every tag of the template, in the order they appear in the "
                "document: key, label, type, whether it is required, the "
                "prompt the model is given for it, and whether it is filled, "
                "with the source and the number of the current version when it "
                "is. Tags no longer present in the template are left out. "
                "`constructs` lists the Jinja constructions of the template "
                "the builder does not understand (`{% for %}` and the like): "
                "they stay in the document as text and do not break the build. "
                "400 invalid_id, 404 not_found, 409 in_trash."))
def теги_проекта(project_id: str, request: Request, s: SessionDep,
                 user: CurrentUser) -> dict:
    """Теги шаблона со состоянием заполнения — то, из чего сделана колонка тегов.

    **Зачем отдельный маршрут, а не поля в карточке проекта.** Карточка
    отвечает на вопрос «что это за проект» и уезжает в списках; здесь на каждый
    тег читается шапка текущей версии (`head_version` — файл на тег), и класть
    это в карточку значило бы платить обходом каталога значений за каждую
    строку списка проектов.

    **Метка и тип — оттуда же, откуда ключи.** Без них экран показывает все
    теги одинаково: таблица, картинка и абзац текста заполняются по-разному, и
    решать это по имени ключа сайт не должен.

    Заполненность — это `head_version`, а не «в `values()` есть ключ»: рядом с
    признаком нужны `source` (своё или от модели — пометка спецификации) и
    номер версии, за которым идёт история, и второй обход тома ради тех же
    файлов был бы платой ни за что.
    """
    settings = настройки(request)
    p = доступный(s, user, project_id, VIEWER)
    проект = открыть(p, settings)
    m = манифест(проект)
    теги = []
    for ключ, спец in теги_шаблона(проект):
        шапка = проект.head_version(ключ)
        теги.append({"key": ключ, "label": спец.label, "type": спец.type,
                     "required": bool(спец.required), "prompt": спец.prompt,
                     "filled": шапка is not None,
                     "source": None if шапка is None else шапка.source,
                     "version": None if шапка is None else шапка.n,
                     "at": None if шапка is None else шапка.at})
    return {"tags": теги,
            "constructs": [] if m is None else list(m.constructs)}


@router.patch("/{project_id}/tags/{key}", operation_id="set_tag_prompt",
              summary="Set what the model is told to write into one tag",
              description=(
                  "Writes the prompt of one tag into the manifest of the work. "
                  "It is the same text a template comment fills in when the "
                  "template carries one, and it outlives a single run, unlike "
                  "the run-wide prompt sent with fill_report. An empty string "
                  "clears it. Editor role. 400 invalid_id, 403 forbidden, "
                  "404 not_found, 404 unknown_tag, 409 in_trash."))
def задание_тега(project_id: str, key: str, тело: TagPromptIn, request: Request,
                 s: SessionDep, user: CurrentUser) -> dict:
    """Задание модели на один тег — поле рядом с заполнением.

    Правкой манифеста, а не отдельной таблицей: задание принадлежит бланку
    работы, живёт столько же, сколько он, и уезжает моделью из того же
    манифеста, из которого едут тип и метка. Вторая копия в базе разошлась бы с
    ним при первой же смене бланка.

    Идёт через `Project.set_tag_prompt`, а не правит манифест здесь: движка
    отчётов службе не видно (правило разреза), и счётчик правок манифеста
    ставится в одном месте — при записи.
    """
    settings = настройки(request)
    p = доступный(s, user, project_id, EDITOR)
    проект = открыть(p, settings)
    try:
        текст = проект.set_tag_prompt(key, тело.prompt)
    except orchestrator.OrchestratorError:
        raise ApiError(UNKNOWN_TAG, "This work has no tag with that key", 404,
                       where="path.key") from None
    return {"key": key, "prompt": текст}


@router.get("/{project_id}/values", operation_id="get_project_values",
            summary="Current tag values of a project",
            description=(
                "The current value of every tag of the project, in the shape "
                "the report builder reads. 400 invalid_id, 404 not_found, "
                "409 in_trash."))
def значения(project_id: str, request: Request, s: SessionDep,
             user: CurrentUser) -> dict:
    """Текущие значения всех тегов. Форма — та же, что читает сборщик отчёта."""
    settings = настройки(request)
    p = доступный(s, user, project_id, VIEWER)
    return {"values": открыть(p, settings).values()}


@router.put("/{project_id}/values/{key}", operation_id="set_project_value",
            summary="Set one tag value by hand",
            description=(
                "Writes one tag value as a new version marked source=manual; "
                "previous versions are kept. The body is the value itself, a "
                "JSON object shaped by its own type field: text and markdown "
                "carry text, a table carries rows, an image or a diagram "
                "carries the id of an artifact, a formula carries latex. A "
                "value that does not fit its type is refused with "
                "invalid_value and where pointing at the field. Editor role. "
                "400 invalid_value, 403 forbidden, 404 not_found, "
                "409 in_trash."))
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
    (та же причина, по которой формы запроса называются `ProjectPatchIn`).
    """
    settings = настройки(request)
    p = доступный(s, user, project_id, EDITOR)
    проект = открыть(p, settings)
    проверить_форму(проект, value)
    try:
        версия = проект.set_value(key, value, source="manual")
    except orchestrator.OrchestratorError:
        raise ApiError(INVALID_VALUE, "Tag value must be a JSON object", 400,
                       where="body") from None
    return {"key": версия.key, "version": версия.n, "source": версия.source,
            "at": версия.at}


def проверить_форму(проект: orchestrator.Project, value: dict) -> None:
    """Значение по форме своего типа — или `400 invalid_value` с местом.

    Проверяет `Project.check_value` — дверь оркестратора к тому самому разбору,
    которым значение прочтёт сборщик отчёта.
    Своей проверки («у таблицы есть `rows`, у формулы `latex`») служба заводить
    не имеет права: она разошлась бы с настоящей на первом же новом поле, и
    разошлась бы молча — в сторону «приняли то, что потом не соберётся».

    **Зовётся дверь, а не движок отчётов.** Импортировать его службе запрещено
    ни одной строкой (`tests/api/test_e2e.py`), и запрет этот не формальный:
    служба, потянувшая движок, перестанет собираться без python-docx. Поэтому
    знание о форме значения живёт там, где ему положено, а сюда приезжает
    запись «что не так»: `stage`, `path`, `field`.
    """
    беда = проект.check_value(value)
    if беда is None:
        return
    if беда["field"] == "type" and not беда["path"]:
        raise ApiError(INVALID_VALUE,
                       "Tag value must name a known type: "
                       + ", ".join(orchestrator.VALUE_TYPES), 400,
                       where="body.type")
    куски = ["body", *(x for x in (беда["path"], беда["field"]) if x)]
    if беда["stage"] == "artifact":
        текст = "Artifact referenced by the tag value is not available"
    elif беда["field"]:
        текст = f'Tag value does not fit its type: field "{беда["field"]}"'
    else:
        текст = "Tag value does not fit its type"
    raise ApiError(INVALID_VALUE, текст, 400, where=".".join(куски))


# ── общее ────────────────────────────────────────────────────────────────────

def проверить_модуль(module: str | None, *, where: str,
                     пусто_можно: bool = True) -> str:
    """Модуль из реестра — или `400 unknown_module`. Пусто значит «не назначен».

    Спрашивается тот же реестр, из которого строится `GET /api/modules`, а не
    свой список слов: второй разошёлся бы с первым на первом же заведённом
    модуле, и в базе оказались бы имена, которых в службе нет.

    Пустая строка законна и означает «модуль не назначен» — кроме отбора в
    списке, где пустой отбор это отсутствие отбора, а не «работы без модуля»
    (`пусто_можно=False` там, где пустое значение уже отсеяно вызывающим).
    """
    # Импорт внутри функции: реестр модулей тянет их подпакеты, а те —
    # зависимости доступа, которые читают этот пакет обратно.
    from .. import modules                                    # noqa: PLC0415

    имя = (module or "").strip()
    if not имя:
        if пусто_можно:
            return ""
        raise ApiError(UNKNOWN_MODULE, "No such module", 400, where=where)
    if имя not in {info.id for info in modules.all_modules() if info.ready}:
        raise ApiError(UNKNOWN_MODULE, "No such module", 400, where=where)
    return имя



def доступный(s, user, project_id: str, min_role: str, *,
              allow_deleted: bool = False) -> Project:
    """Строка проекта, если спрашивающему до неё есть дело.

    Порядок проверок важен и такой: сначала строка (её нет — 404), потом роль в
    её пространстве (не участник — тоже 404, роли мало — 403), и только потом
    корзина. Обратный порядок отвечал бы «в корзине» на чужой проект, то есть
    рассказывал бы о существовании чужого.
    """
    p = get_row(s, project_id)
    require_role(s, user.id, p.workspace_id, min_role, where="path.project_id",
                 allow_deleted=allow_deleted)
    if p.deleted_at is not None and not allow_deleted:
        raise ApiError(IN_TRASH, "Project is in the trash", 409,
                       where="path.project_id")
    return p


__all__ = ["router"]
