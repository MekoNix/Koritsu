"""
artifacts — скачивание того, что производят модули: `…/projects/{id}/artifacts/`.

    GET …/artifacts/{aid}          200  байты артефакта (роль viewer)
    GET …/artifacts/{aid}/notices  200  замечания, с которыми он построен

**Маршрут один на всех производителей.** Артефакт кладут схемы (drawio-XML),
сборка отчёта (DOCX и PDF) и экспорт (zip): по три маршрута скачивания на трёх
владельцев означали бы три разных `Content-Disposition`, три проверки формы
идентификатора и три места, где однажды забудут `nosniff`. Поэтому файл лежит в
`modules/`, но модулем не является и в `GET /api/modules` не попадает — иначе
общий маршрут оказался бы приписан одному из трёх.

**Идентификатор артефакта — не uuid службы**, а 16 hex от sha256 содержимого
(`orchestrator.artifact_id`), как у материалов, и по той же причине: тот же
файл — тот же идентификатор. Форма проверяется своей регуляркой и **до** похода
на том: хранилище складывает из идентификатора путь, и `..` обязан умереть на
входе, а не внутри.

**Тип определяется по содержимому, а не по имени.** Имени у артефакта нет вовсе
— `put_artifact` принимает его только для читаемости вызова и нигде не хранит, —
так что гадать не по чему, кроме первых байт. Тип при этом не значит «браузер,
покажи это»: по умолчанию ответ `attachment` и всегда с `X-Content-Type-Options:
nosniff`. Разница с материалами (там всё отдаётся `application/octet-stream`)
намеренная: материал загрузил человек, и `text/html` на его файле — хранимая XSS
на нашем домене; артефакт произвела служба, и «скачать XML» из макета должно
скачивать XML, а не безымянный поток байт.

**`?inline=1` — показать, а не скачать**. Просмотрщик PDF
на сайте — встроенный, браузерный (`<embed>` на этот же адрес), а `attachment`
сильнее любого тега: браузер скачивает файл вместо того, чтобы нарисовать его.
Сайт до сих пор обходил это выкачиванием байтов в `blob:` — то есть держал
копию отчёта в памяти вкладки и ходил за ним вторым запросом; параметр убирает
и то, и другое.

Показывать можно **не всё, что отдаётся**: `inline` действует только на типы из
`ПОКАЗУЕМЫЕ` — PDF и растровые картинки. Остальное (drawio-XML, DOCX, zip)
уезжает вложением, даже если попросили показать. Причина та же, по которой в
`ВИДЫ` нет `image/svg+xml`: XML, нарисованный браузером на нашем домене, — это
чужой документ в нашем происхождении (у него бывает `xml-stylesheet`), а
показывать zip и вовсе нечего. Отказывать в таком случае незачем: человек
просил показать файл, показать его нельзя, и скачивание — ровно то, чего он
хотел добиться.

**Роль — `viewer`.** Артефакт показывают, а не правят: тот, кому дали смотреть
проект, обязан видеть и схемы в нём, иначе «поделиться отчётом» не работает.
"""
from __future__ import annotations

import io
import re
import zipfile

import orchestrator
from fastapi import APIRouter, Response

from ..errors import ApiError, INVALID_ID, NOT_FOUND
from ..materials.deps import Проект, ЧитательПроекта
from ..materials.service import открыть
from ..materials.upload import заголовок_имени

router = APIRouter(prefix="/projects/{project_id}/artifacts", tags=["artifacts"])

# Длина берётся у оркестратора, а не пишется числом: он единственный, кто знает,
# сколько знаков sha256 оставляет `artifact_id`, и переезд с 16 на 20 не должен
# требовать правки здесь.
ДЛИНА_ИД = len(orchestrator.artifact_id(b""))
ARTIFACT_ID_RE = re.compile(r"\A[0-9a-f]{%d}\Z" % ДЛИНА_ИД)

# По каким первым байтам узнаётся вид. Список закрыт и короткий: всё, чего в нём
# нет, отдаётся потоком байт. Дописывать сюда `image/svg+xml` нельзя — SVG
# исполняет скрипты, и «показать в браузере» на нём означает чужой код на нашем
# домене.
ВИДЫ: tuple[tuple[bytes, str, str], ...] = (
    (b"%PDF-", "application/pdf", ".pdf"),
    (b"<mxfile", "application/xml", ".xml"),
    (b"<?xml", "application/xml", ".xml"),
    (b"\x89PNG\r\n", "image/png", ".png"),
    (b"\xff\xd8\xff", "image/jpeg", ".jpg"),
)

ПОТОК = ("application/octet-stream", "")

# Что разрешено показывать в окне по `?inline=1`. Список отдельный от `ВИДЫ` и
# короче него намеренно: узнать тип и согласиться нарисовать его на своём
# домене — разные решения. Здесь только то, что браузер рисует своим
# просмотрщиком и что не является документом с разметкой.
ПОКАЗУЕМЫЕ = frozenset({"application/pdf", "image/png", "image/jpeg"})

# Два вида, начинающиеся одинаково: DOCX — это zip, и по первым байтам их не
# различить. Отличает их опись внутри архива: у документа OOXML первым лежит
# `[Content_Types].xml`, а у zip'а экспорта — материалы проекта. Отдавать zip
# экспорта как DOCX нельзя: Word откроет его и скажет, что файл повреждён, —
# то есть человек решит, что сломалась сборка, а не тип в заголовке.
ZIP_НАЧАЛО = b"PK\x03\x04"
ООXML_ОПИСЬ = "[Content_Types].xml"
DOCX = ("application/vnd.openxmlformats-officedocument."
        "wordprocessingml.document", ".docx")
ZIP = ("application/zip", ".zip")


def проверить_ид(artifact_id: str) -> str:
    """Форма идентификатора артефакта — до тома и до хранилища."""
    if not ARTIFACT_ID_RE.match(artifact_id or ""):
        raise ApiError(INVALID_ID,
                       f"Artifact id must be {ДЛИНА_ИД} hex characters", 400,
                       where="path.artifact_id")
    return artifact_id


def вид(данные: bytes) -> tuple[str, str]:
    """Содержимое → `(тип, расширение)`. Неузнанное — поток байт."""
    for метка, тип, расширение in ВИДЫ:
        if данные.startswith(метка):
            return тип, расширение
    if данные.startswith(ZIP_НАЧАЛО):
        return DOCX if _это_ooxml(данные) else ZIP
    return ПОТОК


def _это_ooxml(данные: bytes) -> bool:
    """Есть ли в архиве опись OOXML. Читается опись, а не содержимое.

    Опись — это центральный каталог zip'а, то есть имена и размеры; распаковки
    здесь нет, поэтому и zip-бомба ничего не стоит. Битый архив — не наше дело:
    отдадим его как zip, и разбираться будет тот, кто его скачал.
    """
    try:
        with zipfile.ZipFile(io.BytesIO(данные)) as архив:
            return ООXML_ОПИСЬ in архив.namelist()
    except (zipfile.BadZipFile, OSError, ValueError):
        return False


def байты(проект: Проект, artifact_id: str) -> bytes:
    """Содержимое артефакта или `404`.

    Спрашивается `Project.resolve_artifact` — та же дверь, что получает сборщик
    отчёта. Своего чтения с тома здесь нет намеренно: раскладку каталогов знает
    оркестратор, и второе место, знающее её, разошлось бы с первым на первом же
    переименовании.
    """
    проверить_ид(artifact_id)
    try:
        return открыть(проект).resolve_artifact(artifact_id)
    except orchestrator.OrchestratorError:
        raise ApiError(NOT_FOUND, "Artifact not found", 404,
                       where="path.artifact_id") from None


@router.get("/{artifact_id}", operation_id="download_artifact",
            summary="Download a project artifact",
            description=(
                "The bytes of an artifact produced in this project: a drawio "
                "XML diagram, a built report, an export. The content type "
                "follows the bytes; the answer is an attachment and is "
                "never sniffed by the browser. With inline=1 a PDF or a raster "
                "image is served for display in the browser instead, so the "
                "page can embed it directly; anything else stays an "
                "attachment. Viewer role. 400 invalid_id, 404 not_found."),
            response_class=Response)
def скачать_артефакт(artifact_id: str, проект: ЧитательПроекта,
                     inline: bool = False) -> Response:
    """Артефакт байт в байт, с типом по содержимому и безопасным именем.

    Имя собирается из идентификатора и расширения, а не берётся от клиента:
    клиент имени артефакта и не знает — у артефакта его нет. Зато собранное так
    имя невозможно превратить в путь, и человек по нему различает файлы в папке
    «Загрузки».

    `inline` — просьба показать, а не скачать; исполняется только для
    `ПОКАЗУЕМЫЕ` типов (см. шапку модуля), для прочих молча остаётся
    вложением.
    """
    данные = байты(проект, artifact_id)
    тип, расширение = вид(данные)
    return Response(content=данные, media_type=тип,
                    headers={
                        "Content-Disposition":
                            заголовок_имени(f"{artifact_id}{расширение}",
                                            inline=inline and тип in ПОКАЗУЕМЫЕ),
                        # Браузеру запрещено угадывать тип за нас: угаданный
                        # `text/html` на чужих байтах — это чужой скрипт на
                        # нашем домене.
                        "X-Content-Type-Options": "nosniff",
                    })


@router.get("/{artifact_id}/notices", operation_id="artifact_notices",
            summary="Notices the artifact was built with",
            description=(
                "What the builder said while making this artifact: what did not "
                "make it into the diagram, what the tracer did not understand. "
                "An empty list means there was nothing to say. Viewer role. "
                "400 invalid_id, 404 not_found."))
def замечания(artifact_id: str, проект: ЧитательПроекта) -> list[dict]:
    """Замечания артефакта. Форма — общая (`kyotsu.Notice`), как везде.

    Лежат они рядом с артефактом, а не в значении тега: замечание описывает
    **схему**, а не тег (одну схему можно поставить в два тега, и правда о ней
    одна), и живёт ровно столько, сколько живёт артефакт.
    """
    # Байты спрашиваются ради `404`: замечаний у артефакта может не быть вовсе,
    # и пустой список на несуществующий идентификатор соврал бы, что артефакт
    # есть и он безупречен.
    байты(проект, artifact_id)
    return [n.to_dict() for n in открыть(проект).artifact_notices(artifact_id)]


__all__ = ["router", "скачать_артефакт", "замечания", "байты", "вид",
           "проверить_ид", "ARTIFACT_ID_RE", "ДЛИНА_ИД", "ВИДЫ", "DOCX", "ZIP",
           "ПОТОК", "ПОКАЗУЕМЫЕ"]
