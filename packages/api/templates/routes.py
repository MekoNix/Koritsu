"""
routes — шаблоны отчётов: свои (`/api/templates`) и приложенные к работе.

    POST   /api/templates             201  загрузить DOCX (multipart: file, name)
                                      200  тот же файл уже был — прежний шаблон
    GET    /api/templates             200  свои шаблоны: имя, размер, тегов, дата
    DELETE /api/templates/{id}        204  убрать
    GET    /api/templates/{id}/blob   200  скачать оригинал байт в байт

    GET    /api/projects/{id}/templates        200  шаблоны работы (viewer)
    POST   /api/projects/{id}/templates        201  приложить (editor)
                                               200  уже приложен
    POST   /api/projects/{id}/templates/{tid}/use  200  собирать работу по нему
    DELETE /api/projects/{id}/templates/{tid}  204  убрать из работы (editor)

**Шаблонов у работы много, и добавляют их у работы.** Бланк выбирают там, где
им пользуются, — на странице отчётов работы, а не в профиле; личная полка
(`/api/templates`) при этом остаётся **источником**: приложить можно и уже
загруженный шаблон, назвав его `template_id`. Тем же полем шаблон выбирается
при создании проекта, и это не совпадение, а одно и то же знание.

**Приложенный шаблон не подменяет шаблон работы сам собой.** Работа собирается
по манифесту, построенному при её создании; список приложенных — это то, из
чего человек выбирает. Выбор — отдельное действие (`…/use`), и в нём весь
смысл разделения: приложить бланк к работе можно про запас, а собираться она
будет по тому, который выбран. Какой это, видно в списке полем `active`.

**Смена бланка бережёт решения человека.** `…/use` идёт через
`orchestrator.Project.update_template`, а тот строит новый манифест **поверх
старого**: тег добавили — завели запись; тег убрали — пометили «нет в шаблоне»,
но не стёрли; задания, типы и ограничения остались. Значения тегов при этом
никуда не деваются, и работа, у которой сменили бланк, собирается сразу.

**Зачем это отдельно от проекта.** До сегодня шаблон существовал только внутри
работы: `POST /api/projects` принимал DOCX, клал его артефактом, и человек,
заводящий пятую работу по тому же ГОСТу, искал тот же файл у себя на диске в
пятый раз. Разделы настроек делаются вместе с API: шаблон принадлежит
человеку, лежит рядом с его проектами и выбирается при
создании работы по идентификатору (`template_id` у `POST /api/projects`).

**Байты копируются, а не связываются.** Проект, заведённый по шаблону, получает
его артефактом — своей копией. Поэтому удаление шаблона из списка не трогает ни
одной работы, и поэтому же правка шаблона (то есть загрузка нового) не меняет
задним числом уже заведённые: смена шаблона у работы — отдельное намерение
(`Project.update_template`), и делать её незаметно нельзя.

**Сюда нельзя ключом** — только сессией сайта (`auth.ТОЛЬКО_СЕССИЯ`), как
и в ключи моделей: это личные файлы аккаунта, а не работа над проектом.
Внешнему клиенту шаблон не нужен и без него: он приносит DOCX телом создания
проекта, как и раньше.

Скачивание отдаёт `Content-Disposition: attachment` с именем шаблона и
`X-Content-Type-Options: nosniff` — те же две вещи, что у артефактов, и по той
же причине: браузеру запрещено угадывать тип за нас.
"""
from __future__ import annotations

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field

from ..db import SessionDep
from ..errors import ApiError
from ..materials import upload
from ..materials.deps import РедакторПроекта, ЧитательПроекта
from ..projects.routes import ОТЧЁТ, отчёт
from ..workspaces.deps import CurrentUser
from . import service

router = APIRouter(prefix="/templates", tags=["templates"])

# Второй роутер: те же шаблоны, но со стороны работы. Отдельным объектом, а не
# вложенным включением: вложенных включений служба не признаёт
# (`routes.зеркало`), а префикс у этих маршрутов другой.
project_router = APIRouter(prefix="/projects/{project_id}/templates",
                           tags=["templates"])

# Поле формы, в котором приходит имя шаблона. Рядом с `upload.ПОЛЕ` («file»),
# потому что оба — имена частей одной формы.
ПОЛЕ_ИМЕНИ = "name"

# Поле формы, в котором приходит идентификатор уже сохранённого шаблона. То же
# имя, что у поля создания проекта (`projects.routes`), и это не совпадение:
# «взять шаблон с полки» — одно и то же действие в обоих местах, и звать его
# двумя словами значило бы, что клиент помнит, какое где.
ПОЛЕ_ШАБЛОНА = "template_id"

# Тип DOCX. Полностью, а не `application/octet-stream`: Word открывает файл по
# типу, и «двоичный поток» он предлагает сохранить, а не открыть.
DOCX = ("application/vnd.openxmlformats-officedocument."
        "wordprocessingml.document")

# Описание тела для OpenAPI. Пишется руками по той же причине, что у загрузки
# материала: обработчик берёт `Request`, а не `UploadFile` (размер режется на
# потоке), и вывести форму из подписи FastAPI не может.
ТЕЛО_ЗАГРУЗКИ = {
    "requestBody": {
        "required": True,
        "content": {"multipart/form-data": {"schema": {
            "type": "object",
            "properties": {
                upload.ПОЛЕ: {"type": "string", "format": "binary"},
                ПОЛЕ_ИМЕНИ: {"type": "string"},
            },
            "required": [upload.ПОЛЕ]}}},
    }
}


# То же для формы приложения к работе. Файл здесь **не** обязателен: вместо него
# приходит `template_id`, и требовать оба поля значило бы соврать в документе.
ТЕЛО_ПРИЛОЖЕНИЯ = {
    "requestBody": {
        "required": True,
        "content": {"multipart/form-data": {"schema": {
            "type": "object",
            "properties": {
                upload.ПОЛЕ: {"type": "string", "format": "binary"},
                ПОЛЕ_ИМЕНИ: {"type": "string"},
                ПОЛЕ_ШАБЛОНА: {"type": "string"},
            }}}},
    }
}


class TemplateOut(BaseModel):
    """Карточка шаблона. Пути на томе в ней нет и быть не может."""

    id: str = Field(description="Template id, used when creating a project")
    name: str = Field(description="Human-readable name")
    bytes: int = Field(description="Size of the DOCX on the volume")
    tags: int = Field(description="How many tags the template has")
    sha256: str = Field(description="First characters of the content hash")
    user_id: str | None = Field(
        default=None,
        description=("Whose template this is. A project may carry a template "
                     "uploaded by another member of the workspace."))
    created_at: str | None = Field(default=None, description="When it was uploaded")
    active: bool | None = Field(
        default=None,
        description=("Whether this is the template the work is built from. "
                     "Only listed for templates attached to a project: on the "
                     "personal shelf the question has no meaning."))


@router.post("", status_code=201, operation_id="upload_template",
             response_model=TemplateOut,
             summary="Upload a report template",
             description=(
                 "Stores a DOCX template of your own (multipart field `file`, "
                 "optional `name`) and answers with its card: size and how "
                 "many tags it has. The file is parsed the same way a project "
                 "template is, so a file rejected here would be rejected there "
                 "too. One DOCX is one template: uploading the very same bytes "
                 "again answers 200 with the template you already have, under "
                 "the name you gave it then. 400 bad_template, "
                 "400 invalid_name, 400 no_file, 413 file_too_large, "
                 "413 quota_exceeded."),
             responses={200: {"model": TemplateOut,
                              "description": "The same file was already there"}},
             openapi_extra=ТЕЛО_ЗАГРУЗКИ)
async def загрузить(request: Request, response: Response, s: SessionDep,
                    user: CurrentUser) -> dict:
    """Принять DOCX: размер на потоке, разбор, тот же файл, квота, том.

    Асинхронный обработчик — по той же необходимости, что у загрузки материала:
    тело читается с обрывом по размеру, а обрыв возможен только на потоке.

    Повторная загрузка тех же байтов отвечает `200` и прежней карточкой.
    `409` было бы честнее по букве и хуже по делу: человек, второй раз выбравший
    тот же файл, добивается ровно того, что уже есть, и отказ заставил бы его
    искать в списке строку, которую служба и так держит в руках.
    """
    settings = request.app.state.settings
    имя_файла, данные, поля = await upload.принять_файл_и_поля(
        request, settings.file_max_bytes, (ПОЛЕ_ИМЕНИ,))
    шаблон, новый = service.добавить(s, settings, user.id,
                                     имя=поля.get(ПОЛЕ_ИМЕНИ, ""),
                                     имя_файла=имя_файла, данные=данные)
    if not новый:
        response.status_code = 200
    return service.карточка(шаблон)


@router.get("", operation_id="list_templates",
            response_model=list[TemplateOut],
            summary="List your report templates",
            description=(
                "Your templates, newest first: name, size, number of tags and "
                "the date they were uploaded. 401 unauthenticated."))
def список(s: SessionDep, user: CurrentUser) -> list[dict]:
    """Свои шаблоны, новые сверху."""
    return [service.карточка(ш) for ш in service.мои(s, user.id)]


@router.delete("/{template_id}", status_code=204,
               operation_id="delete_template",
               summary="Delete a report template",
               description=(
                   "Removes one of your templates from the list and from the "
                   "volume. Projects created from it keep their own copy and "
                   "are not touched. A template that belongs to someone else "
                   "and one that never existed answer alike. "
                   "400 invalid_id, 404 not_found."))
def удалить(template_id: str, request: Request, s: SessionDep,
            user: CurrentUser) -> Response:
    """Убрать свой шаблон. Чужой и несуществующий — одинаково `404`."""
    service.удалить(s, request.app.state.settings, user.id, template_id)
    return Response(status_code=204)


@router.get("/{template_id}/blob", operation_id="download_template",
            summary="Download a report template",
            description=(
                "The DOCX of one of your templates, byte for byte, as an "
                "attachment. 400 invalid_id, 404 not_found."),
            response_class=Response)
def скачать(template_id: str, request: Request, s: SessionDep,
            user: CurrentUser) -> Response:
    """Оригинал байт в байт, с именем шаблона в заголовке скачивания.

    Имя приводится тем же `upload.заголовок_имени`, что у материалов: оно
    пришло от человека, и в заголовок ответа оно попадает разобранным на две
    формы RFC 6266, а не как есть.
    """
    settings = request.app.state.settings
    шаблон = service.найти(s, user.id, template_id)
    данные = service.байты(settings, шаблон)
    имя = шаблон.name
    if not имя.lower().endswith(service.РАСШИРЕНИЕ):
        имя += service.РАСШИРЕНИЕ
    return Response(content=данные, media_type=DOCX,
                    headers={
                        "Content-Disposition": upload.заголовок_имени(имя),
                        "X-Content-Type-Options": "nosniff",
                    })


# ── шаблоны работы ───────────────────────────────────────────────────────────

@project_router.get("", operation_id="list_project_templates",
                    response_model=list[TemplateOut],
                    summary="Templates attached to this project",
                    description=(
                        "The report templates attached to this project, in the "
                        "order they were attached. A project may carry several: "
                        "a title page, an appendix, a standard. `active` says "
                        "which one the report named by `report` is currently "
                        "built from; without `report` it is the single "
                        "document of the work. Viewer role. 400 invalid_id, "
                        "404 not_found."))
def шаблоны_работы(проект: ЧитательПроекта, s: SessionDep,
                   request: Request, report: str = ОТЧЁТ) -> list[dict]:
    """Шаблоны работы. Пустой список — законное состояние новой работы.

    `active` — про открытый документ, а не про работу: отчётов в ней несколько,
    и каждый собирается своим бланком, поэтому «выбран» без указания отчёта
    отвечало бы на вопрос, которого никто не задавал.
    """
    свой = service.текущий_шаблон(проект, report=отчёт(report))
    return [service.карточка(ш, активный=bool(свой) and ш.sha256 == свой)
            for ш in service.шаблоны_проекта(s, проект.id)]


@project_router.post("", status_code=201,
                     operation_id="attach_project_template",
                     response_model=TemplateOut,
                     summary="Attach a report template to this project",
                     description=(
                         "Attaches a template to the project: either a DOCX "
                         "sent here (multipart field `file`, optional `name`), "
                         "which lands on your own shelf as well, or one you "
                         "have already saved, named by `template_id`. Sending "
                         "both is refused. Attaching the same template twice is "
                         "the same state and answers 200. Editor role. "
                         "400 bad_template, 400 invalid_id, 400 invalid_name, "
                         "400 no_file, 403 forbidden, 404 not_found, "
                         "413 file_too_large, 413 quota_exceeded."),
                     responses={200: {"model": TemplateOut,
                                      "description": "It was attached already"}},
                     openapi_extra=ТЕЛО_ПРИЛОЖЕНИЯ)
async def приложить_шаблон(request: Request, response: Response,
                           проект: РедакторПроекта, s: SessionDep,
                           user: CurrentUser) -> dict:
    """Приложить шаблон к работе: файлом или идентификатором своего.

    Оба сразу — отказ, а не «файл главнее»: молча выбранный за человека шаблон
    — это чужой ГОСТ в готовой работе (тот же довод, что у создания проекта).

    Приложить можно **только своё**: `найти` спрашивает владельца. Иначе, назвав
    чужой идентификатор, можно было бы узнать, что такой шаблон существует.
    """
    settings = request.app.state.settings
    имя_файла, данные, поля = await upload.принять_файл_и_поля(
        request, settings.file_max_bytes, (ПОЛЕ_ИМЕНИ, ПОЛЕ_ШАБЛОНА),
        файл_обязателен=False)
    названный = (поля.get(ПОЛЕ_ШАБЛОНА) or "").strip()
    if названный and данные:
        raise ApiError(service.BAD_TEMPLATE,
                       "Send either a template file or template_id, not both",
                       400, where="body." + ПОЛЕ_ШАБЛОНА)
    if названный:
        шаблон = service.найти(s, user.id, названный,
                               where="body." + ПОЛЕ_ШАБЛОНА)
    elif данные:
        шаблон, _ = service.добавить(s, settings, user.id,
                                     имя=поля.get(ПОЛЕ_ИМЕНИ, ""),
                                     имя_файла=имя_файла, данные=данные)
    else:
        raise ApiError(upload.NO_FILE,
                       "Send a DOCX file or the id of a saved template", 400,
                       where="body." + upload.ПОЛЕ)
    _, новая = service.приложить(s, проект.id, шаблон)
    if not новая:
        response.status_code = 200
    return service.карточка(шаблон)


@project_router.post("/{template_id}/use", operation_id="use_project_template",
                     response_model=TemplateOut,
                     summary="Build this project from this template",
                     description=(
                         "Makes one of the attached templates the one the work "
                         "is built from. Decisions already made about the tags "
                         "(prompts, types, limits) move to the new manifest: a "
                         "tag that is gone is marked as such rather than "
                         "dropped, and tag values are left alone. `report` "
                         "says which report of the project changes its "
                         "template; without it the single document of the "
                         "work does. Editor role. 400 bad_template, "
                         "400 invalid_id, 403 forbidden, 404 not_found."))
def выбрать_шаблон(template_id: str, проект: РедакторПроекта, s: SessionDep,
                   request: Request, report: str = ОТЧЁТ) -> dict:
    """Собирать работу по этому бланку.

    Отдельным действием, а не побочным следствием «приложить»: у работы
    приложенных бланков несколько, и молча выбранный за человека — это чужой
    ГОСТ в готовой работе. Тот же довод, что у создания проекта, где файл и
    `template_id` вместе не принимаются.

    Шаблон обязан быть **приложен** к этой работе: список приложенных и есть
    то, из чего выбирают. Иначе, назвав любой идентификатор, можно было бы
    собрать работу по бланку, которого в ней никто не видел.
    """
    settings = request.app.state.settings
    шаблон = service.выбрать(s, settings, проект, template_id,
                             report=отчёт(report))
    return service.карточка(шаблон, активный=True)


@project_router.delete("/{template_id}", status_code=204,
                       operation_id="detach_project_template",
                       summary="Remove a template from this project",
                       description=(
                           "Takes a template off the project. The file itself "
                           "stays on the shelf of whoever uploaded it: the same "
                           "DOCX may be attached to several works. Editor role. "
                           "400 invalid_id, 403 forbidden, 404 not_found."),
                       response_class=Response)
def отвязать_шаблон(template_id: str, проект: РедакторПроекта,
                    s: SessionDep) -> Response:
    """Убрать шаблон из работы. Файл остаётся у своего человека."""
    service.отвязать(s, проект.id, template_id)
    return Response(status_code=204)


__all__ = ["router", "project_router", "TemplateOut", "ПОЛЕ_ИМЕНИ",
           "ПОЛЕ_ШАБЛОНА", "DOCX"]
