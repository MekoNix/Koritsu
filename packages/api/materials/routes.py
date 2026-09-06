"""
routes — маршруты материалов проекта: `/api/projects/{id}/materials`.

Обработчики тонкие намеренно: каждый — «спросить доступ, позвать `service`,
отдать карточку». Всё, что толще одной мысли, живёт в соседних модулях, и это не
вкус, а то же правило, по которому `api` вообще отделён от `orchestrator`:
предметная работа, заведённая в обработчике, оказывается недоступной ни прогону,
ни консольной команде.

    POST   …/materials              202  принять файл, задание на разбор (editor)
    GET    …/materials              200  опись готовых (роль viewer)
    GET    …/materials/pending      200  принятые, ещё не разобранные
    GET    …/materials/{mid}        200  карточка одного
    GET    …/materials/{mid}/text   200  кусок содержимого с якорем
    GET    …/materials/{mid}/blob   200  оригинал байт в байт
    DELETE …/materials/{mid}        200  убрать с тома (роль editor)

**Загрузка отвечает `202`, а не `201`** (2.0.0a5.1): разбор чужого файла
уехал в очередь, и материала в момент ответа ещё нет. В теле — карточка
задания и `pending_id`, тот самый ключ, под которым материал появится в описи:
он известен сразу, потому что это sha256 содержимого, а не выданный кем-то
номер. Синхронного пути не осталось ни для каких файлов: путь один, через
очередь — так проще, и код один.

Отсюда и `GET …/materials/pending`: опись показывает разобранное, а человек
после загрузки обязан видеть и то, что ещё в работе, — иначе загруженный файл
исчезает на десяток секунд.

Идентификатор материала — не uuid службы, а 16 hex от sha256 содержимого
(`ids.py` объясняет, почему их формы разные), поэтому проверяется он своей
регуляркой и **до** похода на том: без проверки `..` из пути запроса уехал бы в
`os.path.join` внутри хранилища.

Ответ на скачивание несёт `Content-Disposition` с именем, приведённым в
`upload.заголовок_имени`. Само имя пришло от клиента при загрузке; путём оно не
было и здесь не становится — файл ищется по идентификатору.
"""
from __future__ import annotations

from fastapi import APIRouter, Query, Request, Response

import materials as _materials

from ..db import SessionDep
from ..errors import ApiError, INVALID_ID, NOT_FOUND
from ..ids import check_id
from ..jobs import service as задания
from ..jobs.registry import PARSE
from . import jobs as разбор
from . import service, upload
from .deps import CurrentUser, РедакторПроекта, ЧитательПроекта

router = APIRouter(prefix="/projects/{project_id}/materials", tags=["materials"])

# Форма идентификатора — одна на пакет: её же спрашивает `service`, когда ищет
# ссылки на материалы в значениях тегов (см. `service.ИД_RE`).
MATERIAL_ID_RE = service.ИД_RE

# Как в форме загрузки называют решение, которому файл принадлежит. Полем формы,
# а не отдельным маршрутом: файл и его место приезжают одним запросом, и
# «принят, но неизвестно куда» — состояние, которого лучше не заводить.
ПОЛЕ_РЕШЕНИЯ = "run_id"

# Как решение называют в запросе описи. Тот же параметр, что у остальных
# маршрутов решения (`projects/routes.РЕШЕНИЕ`), — здесь он про то, чьи файлы
# показывать.
РЕШЕНИЕ = Query(
    default="",
    description=("Show only the files of this solution, by its run id "
                 "(GET /api/projects/{id}/kadai/runs). Empty means every "
                 "material of the project."))

# Описание тела для OpenAPI. Пишется руками, потому что обработчик берёт
# `Request`, а не `UploadFile` (см. докстроку `upload`), и вывести форму из
# подписи FastAPI не может. Без него сгенерированный клиент сайта не знал бы,
# что у загрузки вообще есть тело.
ТЕЛО_ЗАГРУЗКИ = {
    "requestBody": {
        "required": True,
        "content": {"multipart/form-data": {"schema": {
            "type": "object",
            "properties": {
                upload.ПОЛЕ: {"type": "string", "format": "binary"},
                ПОЛЕ_РЕШЕНИЯ: {
                    "type": "string",
                    "description": ("Solution this file belongs to, by its run "
                                    "id. Empty means the project as a whole."),
                },
            },
            "required": [upload.ПОЛЕ]}}},
    }
}


def проверить_ид(material_id: str) -> str:
    """Форма идентификатора материала — до тома и до хранилища."""
    if not MATERIAL_ID_RE.match(material_id or ""):
        raise ApiError(INVALID_ID,
                       f"Material id must be {service.ДЛИНА_ИД} hex characters",
                       400, where="path.material_id")
    return material_id


def _нет_такого(material_id: str) -> ApiError:
    return ApiError(NOT_FOUND, "Material not found", 404,
                    where="path.material_id")


@router.post("", status_code=202, operation_id="upload_material",
             summary="Upload a material into the project",
             description=(
                 "Accepts a file (multipart field `file`), stores the bytes and "
                 "queues a `parse` job for them. Answers 202 with the job card "
                 "and `pending_id`, the identifier the material will have once "
                 "it is parsed. The same bytes uploaded twice are one material "
                 "and are parsed once. Editor role. 400 no_file, 402 limit_exhausted, "
                 "403 forbidden, "
                 "404 not_found, 413 file_too_large, 413 quota_exceeded, "
                 "415 unsupported_type."),
             openapi_extra=ТЕЛО_ЗАГРУЗКИ)
async def загрузить(request: Request, s: SessionDep, user: CurrentUser,
                    проект: РедакторПроекта) -> dict:
    """Принять файл: размер, тип, квота, байты на том, задание на разбор.

    Асинхронный обработчик — единственный такой здесь, и по необходимости: тело
    читается с обрывом по размеру, а обрыв возможен только на потоке, то есть в
    `await`. Всё остальное синхронно и уезжает в пул потоков, как и вся служба.

    `202` и на повторную загрузку того же файла, и на новый: с точки зрения
    клиента случилось одно и то же — файл принят, задание поставлено, — а
    разбирали его сейчас или месяц назад, наше внутреннее дело (кэш по хешу).
    Различать эти два случая кодом ответа значило бы рассказывать, какие
    файлы уже кто-то загружал.

    Настройки уезжают в постановку ради месячного лимита: разбор — такой
    же запуск нашего кода, как прогон, и своя цена у него есть. Отказ по лимиту
    приходит после того, как байты уже легли в `incoming/`, и это не течь:
    сессия откатывается, а сырые байты уносит часовая уборка воркера
    (`jobs.worker.уборка`), которой они и достались — принятыми, но без
    задания.
    """
    settings = request.app.state.settings
    имя, данные, поля = await upload.принять_файл_и_поля(
        request, settings.file_max_bytes, (ПОЛЕ_РЕШЕНИЯ,))
    ключ, _уже = service.принять(s, settings, проект, имя, данные)
    решение = str(поля.get(ПОЛЕ_РЕШЕНИЯ) or "").strip()
    if решение:
        # Форма проверяется здесь, а не в оркестраторе: из значения складывается
        # имя каталога на томе, и мусор в нём обязан умереть отказом клиенту, а
        # не пятисоткой из недр.
        check_id(решение, where="body.run_id")
        # Приписка ставится сразу, а не после разбора: файл уже принят, а
        # разбор идёт очередью и может не дойти — «принят неизвестно куда»
        # означало бы файл, которого не видно ни в одной папке контекста.
        service.приписать(проект, ключ, решение)
    задание = задания.enqueue(s, user, PARSE,
                              {разбор.КЛЮЧ: ключ, разбор.ИМЯ: имя},
                              project_id=проект.id, settings=settings)
    return {"job": задания.карточка(задание), "pending_id": ключ}


@router.get("", operation_id="list_materials",
            summary="List project materials",
            description=(
                "Cards of every parsed material of the project, in upload "
                "order. `run` narrows the list to the context folder of one "
                "solution. Files still being parsed are in "
                "`GET ./materials/pending`. 400 invalid_id, 404 not_found."))
def опись(проект: ЧитательПроекта, run: str = РЕШЕНИЕ) -> list[dict]:
    """Все разобранные материалы проекта в порядке добавления.

    Разобранные, а не все принятые: материал — это то, у чего есть содержимое и
    нумерация, и показывать в той же описи файл без них значило бы отдать
    клиенту карточку, половина полей которой врёт. Ждущие — соседним маршрутом.

    `run` оставляет в описи файлы одного решения — его папку контекста. Без
    него опись прежняя, все файлы работы: отчёты и схемы видят их как раньше.
    """
    на_томе = service.открыть(проект)
    свои = set(на_томе.solution_materials(run.strip())) if run.strip() else None
    return [service.карточка(m) for m in на_томе.store().list()
            if свои is None or m.id in свои]


@router.get("/pending", operation_id="list_pending_materials",
            summary="Materials accepted but not parsed yet",
            description=(
                "Files the project has accepted and whose `parse` job has not "
                "finished. Each entry carries the identifier the material will "
                "have (`pending_id`), the name it was uploaded under and the "
                "job card. An entry leaves this list when the job finishes: on "
                "success the material shows up in `GET ./materials`, on failure "
                "the job card in `GET /api/jobs` says why. 400 invalid_id, "
                "404 not_found."))
def ожидающие(s: SessionDep, проект: ЧитательПроекта) -> list[dict]:
    """Принятые, но ещё не разобранные файлы проекта.

    Заданиями проекта, а не заданиями пришедшего: файл, загруженный соседом по
    общему пространству, станет материалом того же проекта, и не показать его —
    значит показать человеку опись, в которой через секунду появляется файл,
    взявшийся ниоткуда. Наружу при этом уезжает то же, что уезжает в карточке
    задания, — `payload` придумали не мы, а тот, кто загружал, и ничего, кроме
    имени файла и ключа, в нём нет.

    Список ограничен ждущими и работающими. Упавшее задание сюда не попадает:
    оно кончилось, и место разговора о нём — карточка задания с её `error`, а
    не опись материалов, где ему пришлось бы жить вечно.
    """
    return [{"pending_id": str((з.payload or {}).get(разбор.КЛЮЧ) or ""),
             "name": str((з.payload or {}).get(разбор.ИМЯ) or ""),
             "job": задания.карточка(з)}
            for з in задания.в_работе(s, проект.id, kind=PARSE)]


@router.get("/{material_id}", operation_id="get_material",
            summary="Material card",
            description=(
                "The card of one material: kind, size, what its content is "
                "numbered by and how much of it, notes of the parser. "
                "400 invalid_id, 404 not_found."))
def карточка_материала(material_id: str, проект: ЧитательПроекта) -> dict:
    проверить_ид(material_id)
    try:
        return service.карточка(service.хранилище(проект).get(material_id))
    except _materials.MaterialsError:
        raise _нет_такого(material_id) from None


@router.get("/{material_id}/text", operation_id="get_material_text",
            summary="A chunk of the material text",
            description=(
                "A chunk of the material text with an anchor a reader can "
                "check. Bounds are inclusive and start at 1; bounds outside the "
                "material are clamped, and the anchor says what was returned. "
                "400 invalid_id, 404 not_found."))
def текст(material_id: str, проект: ЧитательПроекта,
          start: int | None = Query(None, ge=1),
          end: int | None = Query(None, ge=1)) -> dict:
    """Кусок содержимого с якорем. Границы включительные, нумерация с единицы.

    Выход за пределы обрезается молча — так решил `materials.Store.read`, и
    решать это второй раз здесь незачем: якорь в ответе показывает, что
    отдали на самом деле.
    """
    проверить_ид(material_id)
    try:
        кусок = service.хранилище(проект).read(material_id, start, end)
    except _materials.MaterialsError:
        raise _нет_такого(material_id) from None
    return {"id": кусок.id, "name": кусок.name, "unit": кусок.unit,
            "start": кусок.start, "end": кусок.end, "text": кусок.text,
            "anchor": кусок.anchor}


@router.get("/{material_id}/blob", operation_id="download_material",
            summary="Download the original file",
            description=(
                "The original file, byte for byte, always as "
                "application/octet-stream. 400 invalid_id, 404 not_found."))
def оригинал(material_id: str, проект: ЧитательПроекта) -> Response:
    """Исходный файл байт в байт — то, что человек загрузил.

    `application/octet-stream` для всего, а не угаданный тип: `Content-Type`,
    взятый из имени файла, — это `text/html` на загруженном `.html` и хранимая
    XSS на нашем домене. Тип нужен человеку в момент открытия скачанного файла,
    а не браузеру в момент получения.
    """
    проверить_ид(material_id)
    склад = service.хранилище(проект)
    try:
        материал = склад.get(material_id)
        данные = склад.blob(material_id)
    except _materials.MaterialsError:
        raise _нет_такого(material_id) from None
    return Response(content=данные, media_type="application/octet-stream",
                    headers={
                        "Content-Disposition": upload.заголовок_имени(материал.name),
                        # Браузеру запрещено угадывать тип за нас — вторая
                        # половина того же заслона, что и octet-stream выше.
                        "X-Content-Type-Options": "nosniff",
                    })


@router.delete("/{material_id}",
               operation_id="delete_material",
               summary="Remove a material from the project",
               description=(
                   "Removes the material and the images extracted from it "
                   "(PDF and Word pages). An extracted image is kept when a tag "
                   "value of the project still refers to it; the response lists "
                   "what was removed and what was kept. 400 invalid_id, "
                   "403 forbidden, 404 not_found."))
def удалить(material_id: str, проект: РедакторПроекта) -> dict:
    """Убрать материал с тома: исходник, разбор и производные картинки.

    Корзины у материала нет намеренно (она есть у проекта и аккаунта):
    материал адресуется хешем содержимого, поэтому «удалил не то» лечится
    повторной загрузкой того же файла — он получит тот же идентификатор, и
    ссылки в значениях тегов снова сойдутся.

    Ответ — тело, а не `204`: удаление одного материала уносит несколько
    (`removed`), и один из детей может остаться (`kept`, на него ссылается
    значение тега). Пустое тело заставило бы клиента перечитывать опись, чтобы
    узнать, что вообще произошло.
    """
    проверить_ид(material_id)
    try:
        return service.удалить(проект, material_id)
    except _materials.MaterialsError:
        raise _нет_такого(material_id) from None


__all__ = ["router", "MATERIAL_ID_RE", "проверить_ид", "ПОЛЕ_РЕШЕНИЯ"]
