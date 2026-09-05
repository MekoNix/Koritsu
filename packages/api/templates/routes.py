"""
routes — шаблоны отчётов в настройках аккаунта: `/api/templates`.

    POST   /api/templates             201  загрузить DOCX (multipart: file, name)
    GET    /api/templates             200  свои шаблоны: имя, размер, тегов, дата
    DELETE /api/templates/{id}        204  убрать
    GET    /api/templates/{id}/blob   200  скачать оригинал байт в байт

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
from ..materials import upload
from ..workspaces.deps import CurrentUser
from . import service

router = APIRouter(prefix="/templates", tags=["templates"])

# Поле формы, в котором приходит имя шаблона. Рядом с `upload.ПОЛЕ` («file»),
# потому что оба — имена частей одной формы.
ПОЛЕ_ИМЕНИ = "name"

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


class TemplateOut(BaseModel):
    """Карточка шаблона. Пути на томе в ней нет и быть не может."""

    id: str = Field(description="Template id, used when creating a project")
    name: str = Field(description="Human-readable name")
    bytes: int = Field(description="Size of the DOCX on the volume")
    tags: int = Field(description="How many tags the template has")
    sha256: str = Field(description="First characters of the content hash")
    created_at: str | None = Field(default=None, description="When it was uploaded")


@router.post("", status_code=201, operation_id="upload_template",
             response_model=TemplateOut,
             summary="Upload a report template",
             description=(
                 "Stores a DOCX template of your own (multipart field `file`, "
                 "optional `name`) and answers with its card: size and how "
                 "many tags it has. The file is parsed the same way a project "
                 "template is, so a file rejected here would be rejected there "
                 "too. 400 bad_template, 400 invalid_name, 400 no_file, "
                 "413 file_too_large, 413 quota_exceeded."),
             openapi_extra=ТЕЛО_ЗАГРУЗКИ)
async def загрузить(request: Request, s: SessionDep,
                    user: CurrentUser) -> dict:
    """Принять DOCX: размер на потоке, разбор, квота, байты на том.

    Асинхронный обработчик — по той же необходимости, что у загрузки материала:
    тело читается с обрывом по размеру, а обрыв возможен только на потоке.
    """
    settings = request.app.state.settings
    имя_файла, данные, поля = await upload.принять_файл_и_поля(
        request, settings.file_max_bytes, (ПОЛЕ_ИМЕНИ,))
    шаблон = service.добавить(s, settings, user.id,
                              имя=поля.get(ПОЛЕ_ИМЕНИ, ""),
                              имя_файла=имя_файла, данные=данные)
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


__all__ = ["router", "TemplateOut", "ПОЛЕ_ИМЕНИ", "DOCX"]
