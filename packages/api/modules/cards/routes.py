"""
routes — тренажёр карточек: `/api/cards` и `/api/projects/{id}/cards`.

    GET    /api/cards/sets?workspace_id=                    200  наборы пространства с моим «знаю»
    POST   /api/cards/preview  {text, filename} | multipart 200  разбор файла в черновик
    POST   /api/cards/sets     {workspace_id, draft_id}     201  набор из черновика     (editor)
    GET    /api/cards/materials?workspace_id=               200  файлы для генерации
    POST   /api/cards/materials?workspace_id=  multipart    202  загрузить файл         (editor)
    POST   /api/cards/generate                              202  агент пишет черновик   (editor)
    GET    /api/cards/drafts/{draft_id}                     200  черновик
    PUT    /api/cards/drafts/{draft_id}  {text}             200  правка черновика
    POST   /api/cards/drafts/{draft_id}/save                201  черновик → набор
    GET    /api/projects/{p}/cards/sets/{id}                200  набор, мои настройки и прогресс
    GET    …/sets/{id}/cards?from=&to=&q=&topic=&keys=      200  карточки страницей
    PUT    …/sets/{id}/defaults                             200  рекомендуемые настройки (editor)
    PUT    …/sets/{id}/my-settings                          200  мои настройки
    POST   …/sets/{id}/replace/preview                      200  новый файл: проблемы и разница (editor)
    POST   …/sets/{id}/replace {draft_id}                   200  заменить новой версией  (editor)
    PATCH  …/sets/{id} {title?, description?}               200  переименовать           (editor)
    DELETE …/sets/{id}                                      204  удалить                 (editor)
    GET    …/sets/{id}/download?format=json                 200  канонический `.json`
    POST   …/sets/{id}/sessions                             201  начать заход
    GET    /api/projects/{p}/cards/sessions/{sid}           200  заход и его ответы
    POST   …/sessions/{sid}/answers                         200  ответ

**Набор — решение работы**, как доска и программа ассемблера
(`modules/board/routes.py` объясняет выбор подробно): запись журнала
`module: "cards"` и каталог решения под ней. Наборы спрашивают по пространству,
новый ложится в **неявную работу** «Тренажёр», которая заводится при первом
наборе. Работы в интерфейсе тренажёра не видно.

**Содержимое — на томе.** Исходный файл каждой загрузки лежит артефактом работы,
разобранный канонический набор — файлом версии в каталоге решения
(`orchestrator.cards`), а запись состояния `карточки-набор` держит название,
описание, перечень версий и пометки изменённых карточек. Отдельная запись
`карточки-ключи` — ключи текущей версии: по ним библиотека считает «знаю» по
каждому набору, не читая наборы целиком.

**Человек — в базе.** Заходы, попытки, прогресс и личные настройки
(`models.py`) видны только самому человеку. Роли: владелец и редактор
пространства загружают, заменяют, переименовывают, удаляют, создают агентом и
меняют рекомендуемые настройки; читатель решает, настраивает свои заходы и
скачивает файл.

**Формат набора — файл JSON** (`docs/cards-format.md`), вторым входом — таблица
CSV/TSV. Файл `.md` прежнего формата — отказ `415 unsupported_type`.

**Черновик — промежуточный шаг** между файлом или агентом и набором: каталог
черновиков человека на томе, семь дней с последней записи. Текст черновика —
всегда файл JSON набора, с отклонёнными карточками как они пришли; таблица
переводится в него при загрузке. Загрузка и замена сначала разбирают файл в
черновик и показывают проблемы с путём JSON (`cards[12].a`) или строкой; набор
заводится или заменяется вторым запросом по `draft_id`. Частичного импорта
молча нет: черновик с проблемами сохраняется только с явным `only_valid`, и
тогда в набор идут только годные карточки.

**Прогресс считает только служба.** Ответ пишется сразу попыткой, прогресс
карточки пересчитывается из её попыток: «знаю» — последняя неисправленная
попытка «Да». Повтор «Нет» внутри захода делает страница, служба принимает
повторные ответы на тот же ключ в одном заходе. Повтор запроса с тем же
`client_seq` — тот же ответ `200`, не вторая попытка.

**Замена файлом сохраняет прогресс по ключам.** Карточка с тем же ключом и
другим текстом получает пометку `changed`, которая видна человеку до его первого
ответа на неё после замены.

**Генерация — только через очередь** (`cards_generate`): у вызова модели есть
цена, месячный потолок, отмена и журнал. Файлы для генерации живут материалами
неявной работы и разбираются обычным заданием `parse`.

Коды отказа: `400 invalid_id` — форма идентификатора; `400 invalid_value` — тело
не годится; `400 endpoint_required`, `400 unknown_provider` — поставщик модели;
`402 limit_exhausted` — месяц кончился; `403 forbidden` — роли мало;
`404 not_found` — нет пространства, работы, набора, черновика, захода или
материала; `409 draft_busy` — черновик пишет агент; `409 version_conflict` —
набор заменили из другой вкладки; `410 unsupported_type` — черновик записан
прежним форматом Markdown; `413 file_too_large` — файл больше потолка;
`415 unsupported_type` — файл Markdown `.md`;
`422 cards_invalid` — у файла проблемы, а `only_valid` не просили, или годных
карточек нет; `422 nothing_to_play` — заходу нечего показать;
`422 nothing_to_add` — в черновике нет новых для набора карточек.
"""
from __future__ import annotations

import dataclasses
import datetime
import hashlib
import json
import os
import re
from typing import Literal

from fastapi import APIRouter, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, distinct, func, select, update
from sqlalchemy.exc import IntegrityError
from starlette.concurrency import run_in_threadpool

from orchestrator import cards as набор
from orchestrator.errors import OrchestratorError

from ...db import SessionDep, now
from ...errors import ApiError, INVALID_ID, NOT_FOUND
from ...ids import check_id, new_id
from ...jobs import service as задания
from ...jobs.models import FAILED, Job
from ...jobs.registry import CARDS_GENERATE, PARSE
from ...log import беды
from ...materials import jobs as разбор
from ...materials import service as материалы
from ...materials import upload
from ...materials.deps import (ROLES, CurrentUser, РедакторПроекта,
                               ЧитательПроекта, найти_проект)
from ...materials.service import открыть
from ...projects.models import NAME_MAX, Project, ProjectRun
from ...projects.routes import завести_работу, настройки
from ...projects.routes import открыть as открыть_работу
from ...projects.runs import завести
from ...projects.service import user_dir
from ...workspaces.service import EDITOR, VIEWER, iso, require_role
from .models import (ANSWERS, KEY_MAX, YES, CardsAttempt, CardsProgress,
                     CardsSession, CardsSettings)

router = APIRouter(tags=["cards"])

# Модуль, записями которого журнал держит наборы.
МОДУЛЬ = "cards"

# Неявная работа пространства. Имя, а не флаг, по той же причине, что у досок:
# переименованная работа перестаёт быть неявной, и следующий набор заведёт
# себе новую.
ИМЯ_РАБОТЫ = "Тренажёр"

# Записи состояния решения набора.
МЕТА = "карточки-набор"
КЛЮЧИ = "карточки-ключи"

# Сколько версий помнит запись набора. Артефакты старых версий остаются на томе
# до уборки работы; перечень нужен человеку, а не восстановлению.
ВЕРСИЙ_В_ЗАПИСИ = 50

# Сколько карточек отдаёт начало захода вместе с планом.
КАРТОЧЕК_В_НАЧАЛЕ = 20

# Страница карточек и потолок ключей в одном запросе.
СТРАНИЦА = 100
СТРАНИЦА_МАКС = 1000
КЛЮЧЕЙ_В_ЗАПРОСЕ = 100

# Значение `topic`, которым просят карточки без темы.
БЕЗ_ТЕМЫ = "-"

# Потолки текстов генерации: они уезжают в промпт.
ПРОСЬБА_МАКС = 4000
ВОПРОСЫ_МАКС = 100_000
ОПИСАНИЕ_МАКС = 2000
ТЕМА_МАКС = 200

# Сколько упавших разборов файлов показывает список материалов генерации.
УПАВШИХ_В_СПИСКЕ = 20

# Потолок числа карточек в заходе и в настройках.
КАРТОЧЕК_МАКС = 10_000

# Запас на экранирование JSON сверх потолка файла.
ЗАПАС_JSON = 64 * 1024

# Поля формы рядом с файлом. Форму принимают только оба превью, а они лишь
# разбирают файл в черновик: «сохранить одни годные» решается вторым запросом,
# формой набора или черновика, и в этой форме поля для него нет.
ПОЛЯ_ФОРМЫ = ("filename", "workspace_id")

_ИД_ЧЕРНОВИКА = re.compile(r"^[0-9a-f]{32}$")

# Коды отказа этого модуля.
INVALID_VALUE = "invalid_value"
CARDS_INVALID = "cards_invalid"
DRAFT_BUSY = "draft_busy"
VERSION_CONFLICT = "version_conflict"
NOTHING_TO_PLAY = "nothing_to_play"
NOTHING_TO_ADD = "nothing_to_add"
ENDPOINT_REQUIRED = "endpoint_required"
UNSUPPORTED_TYPE = "unsupported_type"

# Состояния черновика.
ГОТОВ = "ready"
ИДЁТ = "running"
СДЕЛАН = "done"
НЕ_ВЫШЛО = "failed"
ОТМЕНЁН = "cancelled"

# Описание тела «текст или файл» для OpenAPI: обработчик читает `Request`, чтобы
# оборвать приём по размеру (`materials/upload.py`), и вывести форму из подписи
# FastAPI не может.
ТЕЛО_ФАЙЛА = {
    "requestBody": {
        "required": True,
        "content": {
            "application/json": {"schema": {
                "type": "object",
                "properties": {
                    "text": {"type": "string",
                             "description": "The file as text, UTF-8"},
                    "filename": {"type": "string",
                                 "description": ("Name of the file; `.csv` and "
                                                 "`.tsv` are read as tables, "
                                                 "`.md` is refused, anything "
                                                 "else as a JSON card file")},
                    "workspace_id": {"type": "string"},
                },
                "required": ["text"]}},
            "multipart/form-data": {"schema": {
                "type": "object",
                "properties": {
                    upload.ПОЛЕ: {"type": "string", "format": "binary"},
                    "filename": {"type": "string"},
                    "workspace_id": {"type": "string"},
                },
                "required": [upload.ПОЛЕ]}},
        },
    }
}

ТЕЛО_МАТЕРИАЛА = {
    "requestBody": {
        "required": True,
        "content": {"multipart/form-data": {"schema": {
            "type": "object",
            "properties": {upload.ПОЛЕ: {"type": "string", "format": "binary"}},
            "required": [upload.ПОЛЕ]}}},
    }
}


# ── формы ────────────────────────────────────────────────────────────────────

class ProblemOut(BaseModel):
    line: int | None = Field(
        default=None,
        description=("Line of the source, from 1: for a file that is not valid "
                     "JSON and for CSV rows; null otherwise"))
    column: int | None = Field(
        default=None,
        description=("Column in `line`, from 1: for a file that is not valid "
                     "JSON; null otherwise"))
    code: str = Field(description="Machine code of the problem, e.g. empty_answer")
    text: str = Field(description="What is wrong, for a person")
    card: int | None = Field(
        default=None,
        description=("Number of the card in the source, from 0. Such a card is "
                     "rejected and is not in the set; null is a problem of the "
                     "file as a whole"))
    path: str | None = Field(
        default=None,
        description=("Path of the field in the JSON card file, e.g. "
                     "`cards[12].a` or `defaults.order`"))


class StatsOut(BaseModel):
    cards: int = Field(default=0, description="Cards that made it into the set")
    topics: int = 0
    valid: int = Field(default=0, description="The same as `cards`")
    rejected: int = Field(default=0,
                          description="Cards of the source rejected by problems")


class PreviewOut(BaseModel):
    draft_id: str
    problems: list[ProblemOut] = Field(default_factory=list)
    stats: StatsOut


class ReplacePreviewOut(PreviewOut):
    diff: dict = Field(
        default_factory=dict,
        description=("Keys added, changed and removed against the current "
                     "version: {added, changed, removed}"))


class SettingsModel(BaseModel):
    """Настройки захода: личные или рекомендуемые набора."""

    session_size: int | None = Field(
        default=20, ge=0, le=КАРТОЧЕК_МАКС,
        description="Cards in a session; 0 or null means all")
    order: str = Field(
        default="topic_random",
        description="file, random, topic_seq, topic_random or topics_shuffled")
    topics: list[str | None] | None = Field(
        default=None, max_length=501,
        description=("Topic ids to play; null in the list is the cards without "
                     "a topic; the whole field null means every topic"))
    include: str = Field(default="all", description="all, unknown or wrong")
    repeat_wrong: bool = Field(
        default=True,
        description="Bring a No back three cards later, at most twice a session")


class MySettingsIn(SettingsModel):
    reset: bool = Field(
        default=False,
        description="Forget my settings and use the recommended ones again")


class SetCardOut(BaseModel):
    project_id: str
    set_id: str
    title: str
    description: str = ""
    topics: int = 0
    cards: int = 0
    my_known: int = Field(default=0,
                          description="Cards whose last answer of mine is Yes")
    version: int = 0
    created_at: str | None = None
    updated_at: str | None = None


class CreateSetIn(BaseModel):
    workspace_id: str
    draft_id: str
    only_valid: bool = Field(
        default=False,
        description="Save only the valid cards when the draft has problems")


class CreatedOut(BaseModel):
    project_id: str
    set_id: str
    version: int = 1


class TopicOut(BaseModel):
    id: str
    title: str
    cards: int = 0


class TopicProgressOut(BaseModel):
    topic: str | None = Field(default=None,
                              description="Topic id; null for cards without one")
    title: str = ""
    known: int = 0
    total: int = 0


class ProgressOut(BaseModel):
    known: int = 0
    total: int = 0
    by_topic: list[TopicProgressOut] = Field(default_factory=list)


class VersionOut(BaseModel):
    n: int
    at: str | None = None
    filename: str = ""
    cards: int = 0


class OpenSessionOut(BaseModel):
    session_id: str
    pos: int = 0
    total: int = 0
    started_at: str | None = None


class SetOut(BaseModel):
    project_id: str
    set_id: str
    title: str
    description: str = ""
    language: str = ""
    topics: list[TopicOut] = Field(default_factory=list)
    cards_count: int = 0
    defaults: SettingsModel
    version: int = 0
    versions: list[VersionOut] = Field(default_factory=list)
    my_settings: SettingsModel
    my_progress: ProgressOut
    open_session: OpenSessionOut | None = Field(
        default=None,
        description=("My unfinished session of the current version younger "
                     "than the resume window, to offer Continue"))
    can_edit: bool = False
    updated_at: str | None = None


class CardOut(BaseModel):
    key: str
    topic: str | None = None
    q: str
    a: str
    note: str | None = None
    changed: bool = Field(
        default=False,
        description=("The question changed in a replacement after my last "
                     "answer to it"))
    my_last: str | None = Field(default=None, description="yes, no or null")


class CardsPageOut(BaseModel):
    cards: list[CardOut] = Field(default_factory=list)
    total: int = 0


class ReplaceIn(BaseModel):
    draft_id: str
    only_valid: bool = False


class ReplaceOut(BaseModel):
    version: int
    added: int = 0
    changed: int = 0
    removed: int = 0


class PatchIn(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=NAME_MAX)
    description: str | None = Field(default=None, max_length=ОПИСАНИЕ_МАКС)


class PatchOut(BaseModel):
    title: str
    description: str = ""


class SessionIn(BaseModel):
    preset: Literal["settings", "wrong", "all_file"] = Field(
        default="settings",
        description=("settings: my settings; wrong: every card whose last "
                     "answer is No; all_file: the whole set in file order"))
    keys: list[str] | None = Field(
        default=None, max_length=КАРТОЧЕК_МАКС,
        description=("Play exactly these cards in this order instead of a "
                     "preset; unknown keys are skipped"))


class SessionStartedOut(BaseModel):
    session_id: str
    version: int
    keys: list[str]
    settings: dict = Field(default_factory=dict)
    cards: list[CardOut] = Field(
        default_factory=list,
        description="The first cards of the plan; the rest by …/cards?keys=")


class AttemptOut(BaseModel):
    key: str
    answer: str
    shown: bool = False
    ms: int = 0
    client_seq: int
    corrects: int | None = Field(
        default=None, description="client_seq of the attempt this one corrects")
    at: str | None = None


class SessionOut(BaseModel):
    session_id: str
    set_id: str
    version: int
    keys: list[str]
    pos: int = 0
    settings: dict = Field(default_factory=dict)
    answers: list[AttemptOut] = Field(default_factory=list)
    started_at: str | None = None
    ended_at: str | None = None
    stale: bool = Field(default=False,
                        description="The set was replaced after this session began")


class AnswerIn(BaseModel):
    key: str = Field(max_length=KEY_MAX)
    answer: Literal["yes", "no"]
    shown: bool = False
    ms: int = Field(default=0, ge=0, le=86_400_000)
    client_seq: int = Field(ge=0,
                            description="Sequence number of the answer in the tab")
    corrects: int | None = Field(
        default=None, ge=0,
        description="client_seq of an earlier answer of this session it replaces")


class CardProgressOut(BaseModel):
    last_answer: str | None = None
    yes: int = 0
    no: int = 0


class AnswerOut(BaseModel):
    key: str
    client_seq: int
    pos: int
    total: int
    ended: bool = False
    progress: CardProgressOut


class GenerateIn(BaseModel):
    workspace_id: str
    project_id: str | None = Field(
        default=None, description="With set_id: add the cards to this set")
    set_id: str | None = None
    draft_id: str | None = Field(
        default=None, description="Write more cards into this draft of mine")
    topic: str | None = Field(
        default=None, max_length=ТЕМА_МАКС,
        description="Title of the topic to write more cards for")
    prompt: str = Field(default="", max_length=ПРОСЬБА_МАКС)
    questions: str | None = Field(
        default=None, max_length=ВОПРОСЫ_МАКС,
        description="Exam questions to answer, sections as topics")
    material_ids: list[str] = Field(
        default_factory=list, max_length=100,
        description="Files from GET /api/cards/materials")
    count: int = Field(ge=1, description="Cards to write in total")
    per_topic: int | None = Field(default=None, ge=1,
                                  description="Cards per topic instead of in total")
    length: Literal["short", "full"] = "short"
    language: str = Field(default="ru", max_length=16)
    endpoint: str = Field(default="", max_length=64,
                          description="Model provider preset that pays for it")


class GenerateOut(BaseModel):
    job_id: str
    draft_id: str


class TargetOut(BaseModel):
    project_id: str
    set_id: str


class DraftOut(BaseModel):
    draft_id: str
    source: Literal["upload", "agent"]
    status: str = Field(description="ready, running, done, failed or cancelled")
    job_id: str | None = Field(default=None, description="The last job writing it")
    error: str | None = None
    filename: str = ""
    text: str = Field(
        default="",
        description=("The draft as a JSON card file, rejected cards included "
                     "exactly as they came; empty while the agent has written "
                     "nothing"))
    set: dict | None = Field(
        default=None,
        description="The valid cards parsed into a set, null when nothing parses")
    problems: list[ProblemOut] = Field(default_factory=list)
    stats: StatsOut
    workspace_id: str | None = None
    target: TargetOut | None = Field(
        default=None, description="The set this draft replaces or adds to")
    saved: TargetOut | None = None
    created_at: str | None = None
    updated_at: str | None = None


class DraftIn(BaseModel):
    text: str = Field(description="The whole draft as a JSON card file")


class DraftSavedOut(BaseModel):
    problems: list[ProblemOut] = Field(default_factory=list)
    stats: StatsOut


class SaveDraftIn(BaseModel):
    workspace_id: str | None = Field(default=None,
                                     description="Create a new set in this workspace")
    project_id: str | None = Field(default=None,
                                   description="With set_id: add to this set")
    set_id: str | None = None
    only_valid: bool = False


class MaterialOut(BaseModel):
    material_id: str
    name: str = ""
    kind: str = ""
    status: Literal["ready", "pending", "failed"] = Field(
        description=("ready: parsed and can go to the agent; pending: being "
                     "parsed; failed: parsing failed, see `error`"))
    job_id: str | None = None
    error: str | None = Field(default=None,
                              description="Why parsing failed, for status failed")


# ── общее ────────────────────────────────────────────────────────────────────

def сейчас() -> str:
    return datetime.datetime.now(datetime.timezone.utc).replace(
        microsecond=0).isoformat().replace("+00:00", "Z")


def _utc(момент) -> datetime.datetime | None:
    if isinstance(момент, str):
        try:
            момент = datetime.datetime.fromisoformat(момент.replace("Z", "+00:00"))
        except ValueError:
            return None
    if not isinstance(момент, datetime.datetime):
        return None
    return момент if момент.tzinfo else момент.replace(tzinfo=datetime.timezone.utc)


def редактор(проект) -> bool:
    return (проект.role in ROLES
            and ROLES.index(проект.role) >= ROLES.index(EDITOR))


def черновики(settings, user_id: str) -> набор.Drafts:
    return набор.Drafts(user_dir(settings, user_id),
                        days=settings.cards_draft_days,
                        keep=settings.cards_drafts_max)


def ид_черновика(draft_id: str, *, where: str) -> str:
    if not _ИД_ЧЕРНОВИКА.match(str(draft_id or "")):
        raise ApiError(INVALID_ID, "Draft id is 32 hex characters", 400,
                       where=where)
    return draft_id


def черновик(склад: набор.Drafts, draft_id: str, *,
             where: str = "path.draft_id") -> dict:
    """Запись черновика человека или `404`. Чужого черновика не бывает вовсе."""
    мета = склад.read(ид_черновика(draft_id, where=where))
    if мета is None:
        raise ApiError(NOT_FOUND, "Draft not found", 404, where=where)
    if склад.outdated(draft_id):
        raise ApiError(UNSUPPORTED_TYPE,
                       "This draft is in the old Markdown format, which is no "
                       "longer read; start a new draft from a JSON file", 410,
                       where=where)
    return мета


def работа_наборов(s, settings, ws, user, *, завести_если_нет: bool = True):
    """Неявная работа пространства, где живут наборы. Самая старая из подходящих."""
    p = s.scalars(
        select(Project)
        .where(Project.workspace_id == ws.id, Project.deleted_at.is_(None),
               Project.module == МОДУЛЬ, Project.name == ИМЯ_РАБОТЫ)
        .order_by(Project.created_at)).first()
    if p is not None or not завести_если_нет:
        return p
    return завести_работу(s, settings, ws, user, name=ИМЯ_РАБОТЫ,
                          module=МОДУЛЬ, where="body.workspace_id")


def найти_набор(s, project_id: str, set_id: str, *,
                where: str = "path.set_id") -> ProjectRun:
    """Запись набора или `404`. Чужая и несуществующая отвечают одинаково."""
    запись = s.get(ProjectRun, check_id(set_id, where=where))
    if (запись is None or запись.project_id != project_id
            or запись.module != МОДУЛЬ):
        raise ApiError(NOT_FOUND, "Set not found", 404, where=where)
    return запись


def набор_целиком(проект, s, set_id: str):
    """Запись, вид решения, версия и канонический набор. → `(запись, вид, n, набор)`."""
    запись = найти_набор(s, проект.id, set_id)
    вид = открыть(проект).create_solution(запись.id)
    try:
        версия, карточки = набор.read_set(вид)
    except OrchestratorError:
        беды.exception("набор %s не читается", запись.id)
        версия, карточки = 0, None
    if карточки is None:
        raise ApiError(NOT_FOUND, "Set not found", 404, where="path.set_id")
    return запись, вид, версия, карточки


def _utf8(данные: bytes) -> str:
    try:
        return данные.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ApiError(INVALID_VALUE, "The file is not UTF-8 text", 400,
                       where=f"body.{upload.ПОЛЕ}") from None


async def текст_из_запроса(request: Request, предел: int) -> dict:
    """Тело «текст или файл» → `{text, filename, workspace_id?}`.

    Multipart — файлом в поле `file`, JSON — `{text, filename}`. Оба читаются с
    обрывом по размеру: потолок файла набора держится до разбора, а не после.
    """
    тип = (request.headers.get("content-type") or "").lower()
    if тип.startswith("multipart/form-data"):
        имя, данные, поля = await upload.принять_файл_и_поля(
            request, предел, ПОЛЯ_ФОРМЫ)
        return {**поля, "text": _utf8(данные),
                "filename": upload.имя_файла(поля.get("filename") or имя)}

    потолок = 2 * предел + ЗАПАС_JSON
    upload.проверить_длину(request, потолок)
    сырое = bytearray()
    async for кусок in request.stream():
        сырое += кусок
        if len(сырое) > потолок:
            raise ApiError(upload.FILE_TOO_LARGE,
                           f"File exceeds the {предел} byte limit", 413,
                           where="body.text")
    try:
        тело = json.loads(bytes(сырое) or b"{}")
    except ValueError:
        raise ApiError(INVALID_VALUE, "Body is JSON {text, filename} or a file",
                       400, where="body") from None
    if not isinstance(тело, dict) or not isinstance(тело.get("text"), str):
        raise ApiError(INVALID_VALUE, "text is the file as a string", 400,
                       where="body.text")
    текст = тело["text"]
    if len(текст.encode("utf-8")) > предел:
        raise ApiError(upload.FILE_TOO_LARGE,
                       f"File exceeds the {предел} byte limit", 413,
                       where="body.text")
    имя = тело.get("filename")
    out = {"text": текст,
           "filename": upload.имя_файла(имя) if isinstance(имя, str) and имя.strip()
           else ""}
    if тело.get("workspace_id") is not None:
        out["workspace_id"] = тело["workspace_id"]
    return out


def формат_файла(имя: str) -> None:
    """Файл прежнего формата Markdown — `415 unsupported_type`."""
    if набор.markdown_name(имя):
        raise ApiError(UNSUPPORTED_TYPE,
                       "Markdown card files are no longer supported: a card set "
                       "is a JSON file", 415, where="body.filename")


def разобрать(текст: str, имя: str) -> tuple:
    """Загруженный файл → `(набор | None, проблемы)` по расширению. Беда
    разборщика — `422`."""
    try:
        return набор.parse(текст, имя)
    except Exception:                                        # noqa: BLE001
        беды.exception("разбор набора карточек не удался")
        raise ApiError(CARDS_INVALID, "The file cannot be read as a card set",
                       422, where="body.text") from None


def разобрать_черновик(текст: str, имя: str) -> tuple:
    """Текст черновика (всегда JSON) → `(набор | None, проблемы)`."""
    try:
        return набор.parse_draft(текст, имя)
    except Exception:                                        # noqa: BLE001
        беды.exception("разбор черновика карточек не удался")
        raise ApiError(CARDS_INVALID, "The draft cannot be read as a card set",
                       422, where="body.text") from None


def имя_исходника(filename: str, title: str) -> str:
    """Имя исходного файла версии: основа загруженного имени или название набора, `.json`."""
    основа = os.path.splitext(filename)[0].strip() if filename else ""
    return upload.имя_файла(f"{основа or title or 'cards'}.json")


def сводка(карточки, проблемы) -> dict:
    число = len(карточки.cards) if карточки is not None else 0
    return {"cards": число,
            "topics": len(карточки.topics) if карточки is not None else 0,
            "valid": число, "rejected": набор.rejected(проблемы)}


def годный(текст: str, имя: str, only_valid: bool, *,
           where: str = "body.only_valid"):
    """Набор из текста черновика, который можно сохранить, или `422 cards_invalid`."""
    карточки, проблемы = разобрать_черновик(текст, имя)
    if карточки is None or not карточки.cards:
        raise ApiError(CARDS_INVALID, "There is not a single valid card", 422,
                       where=where)
    if проблемы and not only_valid:
        raise ApiError(CARDS_INVALID,
                       f"The file has {len(проблемы)} problems: fix them or save "
                       f"only the {len(карточки.cards)} valid cards", 422,
                       where=where)
    return карточки


# ── настройки ────────────────────────────────────────────────────────────────

def уставки(тело: SettingsModel, *, where: str) -> dict:
    """Настройки захода из тела → чистый словарь или `400`."""
    if тело.order not in набор.ORDERS:
        raise ApiError(INVALID_VALUE,
                       f"order must be one of: {', '.join(набор.ORDERS)}", 400,
                       where=f"{where}.order")
    if тело.include not in набор.INCLUDE:
        raise ApiError(INVALID_VALUE,
                       f"include must be one of: {', '.join(набор.INCLUDE)}", 400,
                       where=f"{where}.include")
    темы = None
    if тело.topics is not None:
        if any(t is not None and not 0 < len(t) <= 64 for t in тело.topics):
            raise ApiError(INVALID_VALUE, "A topic id is 1 to 64 characters",
                           400, where=f"{where}.topics")
        темы = list(dict.fromkeys(тело.topics))
    return {"session_size": int(тело.session_size or 0), "order": тело.order,
            "topics": темы, "include": тело.include,
            "repeat_wrong": bool(тело.repeat_wrong)}


def рекомендуемые(карточки) -> dict:
    """Рекомендуемые настройки набора словарём той же формы."""
    d = dataclasses.asdict(карточки.defaults)
    темы = d.get("topics")
    return {"session_size": int(d.get("session_size") or 0),
            "order": str(d.get("order") or "topic_random"),
            "topics": list(темы) if isinstance(темы, (list, tuple)) else None,
            "include": str(d.get("include") or "all"),
            "repeat_wrong": bool(d.get("repeat_wrong", True))}


def мои_настройки(s, user_id: str, set_id: str, карточки) -> dict:
    строка = s.get(CardsSettings, (user_id, set_id))
    if строка is None or not isinstance(строка.settings_json, dict):
        return рекомендуемые(карточки)
    return {**рекомендуемые(карточки), **строка.settings_json}


# ── прогресс ─────────────────────────────────────────────────────────────────

def прогресс(s, user_id: str, set_id: str) -> dict[str, CardsProgress]:
    return {п.card_key: п for п in s.scalars(
        select(CardsProgress).where(CardsProgress.user_id == user_id,
                                    CardsProgress.set_id == set_id))}


def изменена(ключ: str, мой, изменённые: dict) -> bool:
    """Вопрос изменился после моего последнего ответа на него."""
    когда = _utc(изменённые.get(ключ))
    if когда is None or мой is None:
        return False
    ответил = _utc(мой.last_at)
    return ответил is None or ответил < когда


def карточка(c, мой, изменённые: dict) -> dict:
    return {"key": c.key, "topic": c.topic, "q": c.q, "a": c.a, "note": c.note,
            "changed": изменена(c.key, мой, изменённые),
            "my_last": мой.last_answer if мой is not None else None}


def мой_прогресс(карточки, мои: dict) -> dict:
    названия = {t.id: t.title for t in карточки.topics}
    всего: dict = {}
    знаю: dict = {}
    for c in карточки.cards:
        всего[c.topic] = всего.get(c.topic, 0) + 1
        п = мои.get(c.key)
        if п is not None and п.last_answer == YES:
            знаю[c.topic] = знаю.get(c.topic, 0) + 1
    порядок = ([None] if None in всего else []) + [t.id for t in карточки.topics
                                                   if t.id in всего]
    return {"known": sum(знаю.values()), "total": len(карточки.cards),
            "by_topic": [{"topic": т, "title": названия.get(т, "") if т else "",
                          "known": знаю.get(т, 0), "total": всего[т]}
                         for т in порядок]}


def пересчитать(s, user_id: str, set_id: str, ключ: str) -> CardsProgress:
    """Прогресс карточки из её попыток: исправленные не считаются."""
    попытки = list(s.scalars(
        select(CardsAttempt)
        .where(CardsAttempt.user_id == user_id, CardsAttempt.set_id == set_id,
               CardsAttempt.card_key == ключ)
        .order_by(CardsAttempt.at, CardsAttempt.client_seq)))
    исправленные = {п.corrects_id for п in попытки if п.corrects_id}
    живые = [п for п in попытки if п.id not in исправленные]
    строка = s.get(CardsProgress, (user_id, set_id, ключ))
    if строка is None:
        строка = CardsProgress(user_id=user_id, set_id=set_id, card_key=ключ)
        s.add(строка)
    строка.yes = sum(1 for п in живые if п.answer == YES)
    строка.no = len(живые) - строка.yes
    строка.last_answer = живые[-1].answer if живые else None
    строка.last_at = живые[-1].at if живые else None
    s.flush()
    return строка


# ── версии набора ────────────────────────────────────────────────────────────

def записать_версию(вид, карточки, *, байты: bytes, filename: str,
                    user, изменённые: dict | None = None) -> int:
    """Новая версия набора: канонический файл, исходник `.json` артефактом, записи.

    `байты` — текст файла JSON версии. Номер занимается созданием файла версии:
    занят — `409 version_conflict`, набор заменили из другой вкладки.
    """
    мета = вид.state(МЕТА) or {}
    номера = набор.versions(вид)
    версия = (номера[-1] if номера else 0) + 1
    if not набор.write_set(вид, версия, карточки):
        raise ApiError(VERSION_CONFLICT,
                       "The set was changed from somewhere else; reload it", 409,
                       where="path.set_id")
    имя = имя_исходника(filename, карточки.title)
    артефакт = вид.put_artifact(байты, name="набор карточек", filename=имя)
    момент = сейчас()
    версии = list(мета.get("versions") or [])
    версии.append({"n": версия, "artifact": артефакт, "filename": имя,
                   "at": момент, "by": user.id, "cards": len(карточки.cards)})
    вид.put_state(МЕТА, {
        "title": карточки.title, "description": карточки.description,
        "version": версия, "versions": версии[-ВЕРСИЙ_В_ЗАПИСИ:],
        "changed": dict(изменённые if изменённые is not None
                        else мета.get("changed") or {}),
        "created_at": мета.get("created_at") or момент, "updated_at": момент})
    вид.put_state(КЛЮЧИ, {"version": версия,
                          "keys": [c.key for c in карточки.cards],
                          "topics": len(карточки.topics)})
    return версия


def разница(старый, новый) -> dict:
    """Две версии набора → `{added, changed, removed}` списками ключей.

    Ядро отдаёт ровно эти три поля списками ключей; словарь пересобирается,
    чтобы у маршрутов он был своим и переживал правку на месте.
    """
    сырая = набор.diff(старый, новый)
    return {поле: list(сырая[поле]) for поле in ("added", "changed", "removed")}


def завести_набор(s, settings, user, ws, текст: str, имя: str,
                  only_valid: bool) -> dict:
    """Набор из текста в неявной работе пространства. → `{project_id, set_id, version}`."""
    карточки = годный(текст, имя, only_valid)
    p = работа_наборов(s, settings, ws, user)
    на_томе = открыть_работу(p, settings)
    запись = завести(s, p, user, module=МОДУЛЬ,
                     name=(карточки.title or "")[:NAME_MAX])
    вид = на_томе.create_solution(запись.id)
    версия = записать_версию(вид, карточки,
                             байты=текст.encode("utf-8"), filename=имя, user=user,
                             изменённые={})
    return {"project_id": p.id, "set_id": запись.id, "version": версия}


def дополнить_набор(s, settings, user, project_id: str, set_id: str,
                    текст: str, имя: str, only_valid: bool) -> dict:
    """Добавить карточки черновика в набор новой версией."""
    проект = найти_проект(s, settings, user.id,
                          check_id(project_id, where="body.project_id"), EDITOR)
    запись, вид, _, старый = набор_целиком(проект, s, set_id)
    новые = годный(текст, имя, only_valid)
    итог, добавлено, _ = набор.merge(старый, новые)
    if not добавлено:
        raise ApiError(NOTHING_TO_ADD, "Every card of the draft is already in the set",
                       422, where="body.set_id")
    беды_набора = набор.validate(итог)
    if беды_набора:
        raise ApiError(CARDS_INVALID,
                       f"The set with these cards breaks its limits: "
                       f"{беды_набора[0].text}", 422, where="body.set_id")
    версия = записать_версию(
        вид, итог, байты=набор.write_json(итог).encode("utf-8"),
        filename="", user=user)
    return {"project_id": проект.id, "set_id": запись.id, "version": версия}


# ── наборы пространства ──────────────────────────────────────────────────────

@router.get("/cards/sets", operation_id="cards_sets",
            response_model=list[SetCardOut],
            summary="Card sets of a workspace",
            description=(
                "Every card set of one workspace, most recently updated first, "
                "with how many topics and cards it has and how many of them I "
                "know: cards whose last answer of mine is Yes. Works in the "
                "trash are left out. Viewer role. 400 invalid_id, "
                "404 not_found, 422 validation_failed."))
def наборы_пространства(request: Request, workspace_id: str, s: SessionDep,
                        user: CurrentUser) -> list[dict]:
    settings = настройки(request)
    ws = require_role(s, user.id,
                      check_id(workspace_id, where="query.workspace_id"),
                      VIEWER, where="query.workspace_id")
    работы = s.scalars(
        select(Project)
        .where(Project.workspace_id == ws.id, Project.deleted_at.is_(None))
        .order_by(Project.created_at)).all()
    записи: list[tuple] = []
    for p in работы:
        строки = list(s.scalars(select(ProjectRun).where(
            ProjectRun.project_id == p.id, ProjectRun.module == МОДУЛЬ)))
        if not строки:
            continue
        try:
            на_томе = открыть_работу(p, settings)
        except ApiError:
            беды.exception("работа %s: каталога нет, наборы пропущены", p.id)
            continue
        for запись in строки:
            записи.append((p, запись, на_томе.for_solution(запись.id)))

    знаю: dict[str, set] = {}
    if записи:
        for set_id, ключ in s.execute(
                select(CardsProgress.set_id, CardsProgress.card_key)
                .where(CardsProgress.user_id == user.id,
                       CardsProgress.last_answer == YES,
                       CardsProgress.set_id.in_([з.id for _, з, _ in записи]))):
            знаю.setdefault(set_id, set()).add(ключ)

    итог = []
    for p, запись, вид in записи:
        try:
            мета = вид.state(МЕТА) or {}
            ключи = вид.state(КЛЮЧИ) or {}
        except Exception:                                    # noqa: BLE001
            беды.exception("набор %s: записи не читаются", запись.id)
            continue
        if not мета:
            continue
        свои = знаю.get(запись.id, set())
        итог.append({
            "project_id": p.id, "set_id": запись.id,
            "title": str(мета.get("title") or запись.name or ""),
            "description": str(мета.get("description") or ""),
            "topics": int(ключи.get("topics") or 0),
            "cards": len(ключи.get("keys") or ()),
            "my_known": sum(1 for к in ключи.get("keys") or () if к in свои),
            "version": int(мета.get("version") or 0),
            "created_at": iso(запись.created_at),
            "updated_at": мета.get("updated_at") or iso(запись.created_at)})
    итог.sort(key=lambda к: к["updated_at"] or "", reverse=True)
    return итог


@router.post("/cards/preview", operation_id="cards_preview",
             response_model=PreviewOut,
             summary="Read a card file into a draft",
             description=(
                 "Reads a JSON card file (or a `.csv`/`.tsv` table) into a new "
                 "draft of mine and answers its problems, each with the JSON "
                 "path of the field (`cards[12].a`) or the line of a broken "
                 "file or a CSV row, with how many cards are valid and how many "
                 "were rejected. The draft keeps the file as JSON; a table is "
                 "turned into one. JSON `{text, filename}` or a multipart file, "
                 "at most 5 MB. A Markdown `.md` file is refused. Nothing is "
                 "created in a workspace: POST /api/cards/sets does that with "
                 "the draft id. With `workspace_id`, the editor role in it is "
                 "checked now rather than on save. 400 invalid_value, "
                 "403 forbidden, 404 not_found, 413 file_too_large, "
                 "415 unsupported_type, 422 cards_invalid."),
             openapi_extra=ТЕЛО_ФАЙЛА)
async def превью(request: Request, s: SessionDep, user: CurrentUser) -> dict:
    settings = настройки(request)
    тело = await текст_из_запроса(request, settings.cards_file_max_bytes)
    формат_файла(тело["filename"])

    def работа() -> dict:
        ws_id = str(тело.get("workspace_id") or "").strip()
        if ws_id:
            require_role(s, user.id, check_id(ws_id, where="body.workspace_id"),
                         EDITOR, where="body.workspace_id")
        карточки, проблемы = разобрать(тело["text"], тело["filename"])
        ид = черновики(settings, user.id).create(
            {"source": "upload", "status": ГОТОВ, "filename": тело["filename"],
             "workspace_id": ws_id or None, "user_id": user.id},
            набор.draft_text(тело["text"], тело["filename"]))
        return {"draft_id": ид,
                "problems": [набор.problem_json(п) for п in проблемы],
                "stats": сводка(карточки, проблемы)}

    return await run_in_threadpool(работа)


@router.post("/cards/sets", status_code=201, operation_id="cards_create_set",
             response_model=CreatedOut,
             summary="Create a card set from a draft",
             description=(
                 "Creates a set in the workspace from a draft of mine: a journal "
                 "entry in the workspace trainer work, created on the first set, "
                 "with the file as version 1. A draft with problems is refused "
                 "unless `only_valid` asks to keep only the valid cards. Saving "
                 "the same draft twice answers the set it already became. "
                 "Editor role in the workspace. 400 invalid_id, 403 forbidden, "
                 "404 not_found, 422 cards_invalid."))
def завести_из_черновика(тело: CreateSetIn, request: Request, s: SessionDep,
                         user: CurrentUser) -> dict:
    return сохранить_черновик(тело.draft_id,
                              SaveDraftIn(workspace_id=тело.workspace_id,
                                          only_valid=тело.only_valid),
                              request, s, user, where="body.draft_id")


# ── материалы для генерации ──────────────────────────────────────────────────

@router.get("/cards/materials", operation_id="cards_materials",
            response_model=list[MaterialOut],
            summary="Files for the card agent in a workspace",
            description=(
                "Files uploaded for generating cards in this workspace: parsed "
                "ones with status `ready`, files still being parsed with status "
                "`pending` and their job, and files whose parsing failed within "
                "the draft lifetime with status `failed` and the reason in "
                "`error`. They live in the workspace trainer work. Viewer role. "
                "400 invalid_id, 404 not_found."))
def материалы_генерации(request: Request, workspace_id: str, s: SessionDep,
                        user: CurrentUser) -> list[dict]:
    settings = настройки(request)
    ws = require_role(s, user.id,
                      check_id(workspace_id, where="query.workspace_id"),
                      VIEWER, where="query.workspace_id")
    p = работа_наборов(s, settings, ws, user, завести_если_нет=False)
    if p is None:
        return []
    проект = найти_проект(s, settings, user.id, p.id, VIEWER)
    готовые = [{"material_id": m.id, "name": m.name, "kind": m.kind,
                "status": "ready", "job_id": None}
               for m in материалы.хранилище(проект).list()]
    есть = {м["material_id"] for м in готовые}
    ждут = [{"material_id": str((з.payload or {}).get(разбор.КЛЮЧ) or ""),
             "name": str((з.payload or {}).get(разбор.ИМЯ) or ""), "kind": "",
             "status": "pending", "job_id": з.id}
            for з in задания.в_работе(s, p.id, kind=PARSE)]
    ждут = [м for м in ждут if м["material_id"] not in есть]
    # Упавший разбор показывается столько же, сколько живёт черновик: файл,
    # принесённый для генерации, не пропадает из списка молча. Тот же файл,
    # разобранный позже, в списке уже готовый.
    виденные = есть | {м["material_id"] for м in ждут}
    упавшие = []
    for з in s.scalars(
            select(Job)
            .where(Job.project_id == p.id, Job.kind == PARSE,
                   Job.status == FAILED,
                   Job.created_at >= now() - datetime.timedelta(
                       days=settings.cards_draft_days))
            .order_by(Job.created_at.desc()).limit(УПАВШИХ_В_СПИСКЕ)):
        mid = str((з.payload or {}).get(разбор.КЛЮЧ) or "")
        if not mid or mid in виденные:
            continue
        виденные.add(mid)
        беда = з.error if isinstance(з.error, dict) else {}
        упавшие.append({"material_id": mid,
                        "name": str((з.payload or {}).get(разбор.ИМЯ) or ""),
                        "kind": "", "status": "failed", "job_id": з.id,
                        "error": str(беда.get("message") or "") or None})
    return готовые + ждут + упавшие


@router.post("/cards/materials", status_code=202,
             operation_id="cards_upload_material", response_model=MaterialOut,
             summary="Upload a file for the card agent",
             description=(
                 "Accepts a file (multipart field `file`) into the workspace "
                 "trainer work, created if it is not there yet, and queues its "
                 "`parse` job, the same way as uploading a material into a "
                 "project. `status` is `ready` when the same file is already "
                 "parsed. Editor role in the workspace. 400 invalid_id, "
                 "400 no_file, 402 limit_exhausted, 403 forbidden, "
                 "404 not_found, 413 file_too_large, 413 quota_exceeded, "
                 "415 unsupported_type."),
             openapi_extra=ТЕЛО_МАТЕРИАЛА)
async def загрузить_материал(request: Request, workspace_id: str, s: SessionDep,
                             user: CurrentUser) -> dict:
    settings = настройки(request)
    ws = require_role(s, user.id,
                      check_id(workspace_id, where="query.workspace_id"),
                      EDITOR, where="query.workspace_id")
    имя, данные = await upload.принять_файл(request, settings.file_max_bytes)

    def работа() -> dict:
        p = работа_наборов(s, settings, ws, user)
        проект = найти_проект(s, settings, user.id, p.id, EDITOR)
        ключ, уже = материалы.принять(s, settings, проект, имя, данные)
        задание = задания.enqueue(s, user, PARSE,
                                  {разбор.КЛЮЧ: ключ, разбор.ИМЯ: имя},
                                  project_id=p.id, settings=settings)
        вид = ""
        if уже:
            try:
                вид = материалы.хранилище(проект).get(ключ).kind
            except Exception:                                # noqa: BLE001
                вид = ""
        return {"material_id": ключ, "name": имя, "kind": вид,
                "status": "ready" if уже else "pending", "job_id": задание.id}

    return await run_in_threadpool(работа)


# ── генерация ────────────────────────────────────────────────────────────────

@router.post("/cards/generate", status_code=202, operation_id="cards_generate",
             response_model=GenerateOut,
             summary="Have the agent write cards into a draft",
             description=(
                 "Queues a `cards_generate` job and answers at once with the job "
                 "and the draft it writes into. Without `draft_id` a new empty "
                 "draft of mine is created; with it the agent adds cards to that "
                 "draft (for `topic` when named). With `project_id` and `set_id` "
                 "the draft is meant to add cards to that set on save. Input: "
                 "a description, exam questions and files from "
                 "GET /api/cards/materials; `count` cards in total or "
                 "`per_topic`, at most 200; `length` short or full; `language`. "
                 "Progress frames: `progress` with step = cards written, "
                 "total = cards asked, note = topic; `text`. Editor role in the "
                 "workspace. 400 endpoint_required, 400 invalid_id, "
                 "400 invalid_value, 400 unknown_provider, 402 limit_exhausted, "
                 "403 forbidden, 404 not_found, 409 draft_busy."))
def сгенерировать(тело: GenerateIn, request: Request, s: SessionDep,
                  user: CurrentUser) -> dict:
    from ...runs.model import проверить_пресет                # noqa: PLC0415

    settings = настройки(request)
    ws = require_role(s, user.id,
                      check_id(тело.workspace_id, where="body.workspace_id"),
                      EDITOR, where="body.workspace_id")
    if not тело.endpoint.strip():
        raise ApiError(ENDPOINT_REQUIRED,
                       "endpoint must name a model provider preset", 400,
                       where="body.endpoint")
    пресет = проверить_пресет(тело.endpoint, where="body.endpoint")
    потолок = settings.cards_generate_max
    if тело.count > потолок or (тело.per_topic or 0) > потолок:
        raise ApiError(INVALID_VALUE, f"At most {потолок} cards at a time", 400,
                       where="body.count")
    if len(тело.material_ids) > settings.cards_materials_max:
        raise ApiError(INVALID_VALUE,
                       f"At most {settings.cards_materials_max} files at a time",
                       400, where="body.material_ids")
    if not (тело.prompt.strip() or (тело.questions or "").strip()
            or тело.material_ids or (тело.topic or "").strip()):
        raise ApiError(INVALID_VALUE,
                       "Say what the cards are about: prompt, questions or files",
                       400, where="body.prompt")

    цель = None
    if тело.project_id or тело.set_id:
        if not (тело.project_id and тело.set_id):
            raise ApiError(INVALID_VALUE, "project_id and set_id go together",
                           400, where="body.set_id")
        проект_набора = найти_проект(
            s, settings, user.id, check_id(тело.project_id, where="body.project_id"),
            EDITOR)
        if s.get(Project, проект_набора.id).workspace_id != ws.id:
            raise ApiError(NOT_FOUND, "Set not found", 404, where="body.set_id")
        найти_набор(s, проект_набора.id, тело.set_id, where="body.set_id")
        цель = {"project_id": проект_набора.id, "set_id": тело.set_id}

    p = работа_наборов(s, settings, ws, user)
    проект = найти_проект(s, settings, user.id, p.id, EDITOR)
    склад = материалы.хранилище(проект)
    ids = list(dict.fromkeys(тело.material_ids))
    for mid in ids:
        if not материалы.ИД_RE.match(mid):
            raise ApiError(INVALID_ID, "A material id is hex", 400,
                           where="body.material_ids")
        try:
            склад.get(mid)
        except Exception:                                    # noqa: BLE001
            raise ApiError(NOT_FOUND, f"Material {mid} is not ready or not here",
                           404, where="body.material_ids") from None

    drafts = черновики(settings, user.id)
    новый = тело.draft_id is None
    if новый:
        ид = drafts.create({"source": "agent", "status": ИДЁТ, "filename": "",
                            "workspace_id": ws.id, "target": цель,
                            "user_id": user.id})
        было = None
    else:
        ид = тело.draft_id
        было = черновик(drafts, ид, where="body.draft_id")
        if было.get("status") == ИДЁТ:
            raise ApiError(DRAFT_BUSY, "The agent is still writing this draft",
                           409, where="body.draft_id")
        drafts.update(ид, status=ИДЁТ, error=None)
    try:
        задание = задания.enqueue(
            s, user, CARDS_GENERATE,
            {"endpoint": пресет, "draft_id": ид, "append": not новый,
             "workspace_id": ws.id, "target": цель,
             "prompt": тело.prompt.strip(), "questions": тело.questions or "",
             "material_ids": ids, "count": тело.count,
             "per_topic": тело.per_topic, "length": тело.length,
             "language": тело.language.strip() or "ru",
             "topic": (тело.topic or "").strip() or None},
            project_id=p.id, settings=settings)
    except Exception:
        if новый:
            drafts.drop(ид)
        elif было is not None:
            drafts.update(ид, status=было.get("status") or ГОТОВ)
        raise
    drafts.update(ид, job_id=задание.id)
    return {"job_id": задание.id, "draft_id": ид}


# ── черновики ────────────────────────────────────────────────────────────────

def _цель(значение) -> dict | None:
    if isinstance(значение, dict) and значение.get("project_id") and значение.get("set_id"):
        return {"project_id": str(значение["project_id"]),
                "set_id": str(значение["set_id"])}
    return None


@router.get("/cards/drafts/{draft_id}", operation_id="cards_draft",
            response_model=DraftOut,
            summary="A draft of mine",
            description=(
                "The draft as a JSON card file with every card as it came, "
                "rejected ones included; the valid cards parsed into a set; "
                "its problems with the JSON path and card number; counts; "
                "where it came from (`upload` or `agent`), the last job "
                "writing it and its status. Drafts are private and live seven "
                "days from their last change. 400 invalid_id, 404 not_found, "
                "410 unsupported_type."))
def черновик_целиком(draft_id: str, request: Request, user: CurrentUser) -> dict:
    drafts = черновики(настройки(request), user.id)
    мета = черновик(drafts, draft_id)
    текст = drafts.text(draft_id)
    карточки, проблемы = разобрать_черновик(текст, str(мета.get("filename") or ""))
    return {"draft_id": draft_id,
            "source": "agent" if мета.get("source") == "agent" else "upload",
            "status": str(мета.get("status") or ГОТОВ),
            "job_id": мета.get("job_id"), "error": мета.get("error"),
            "filename": str(мета.get("filename") or ""), "text": текст,
            "set": набор.set_json(карточки) if карточки is not None else None,
            "problems": [набор.problem_json(п) for п in проблемы],
            "stats": сводка(карточки, проблемы),
            "workspace_id": мета.get("workspace_id"),
            "target": _цель(мета.get("target")),
            "saved": _цель(мета.get("saved")),
            "created_at": мета.get("created_at"),
            "updated_at": мета.get("updated_at")}


@router.put("/cards/drafts/{draft_id}", operation_id="cards_put_draft",
            response_model=DraftSavedOut,
            summary="Rewrite a draft of mine",
            description=(
                "Replaces the draft with the whole JSON card file and answers "
                "its problems and counts. A draft the agent is still writing is "
                "refused. At most 5 MB. 400 invalid_id, 404 not_found, "
                "409 draft_busy, 410 unsupported_type, 413 file_too_large."))
def записать_черновик(draft_id: str, тело: DraftIn, request: Request,
                      user: CurrentUser) -> dict:
    settings = настройки(request)
    drafts = черновики(settings, user.id)
    мета = черновик(drafts, draft_id)
    if мета.get("status") == ИДЁТ:
        raise ApiError(DRAFT_BUSY, "The agent is still writing this draft", 409,
                       where="path.draft_id")
    if len(тело.text.encode("utf-8")) > settings.cards_file_max_bytes:
        raise ApiError(upload.FILE_TOO_LARGE,
                       f"Text exceeds the {settings.cards_file_max_bytes} byte "
                       "limit", 413, where="body.text")
    drafts.update(draft_id, text=тело.text, saved=None)
    карточки, проблемы = разобрать_черновик(тело.text, str(мета.get("filename") or ""))
    return {"problems": [набор.problem_json(п) for п in проблемы],
            "stats": сводка(карточки, проблемы)}


@router.post("/cards/drafts/{draft_id}/save", status_code=201,
             operation_id="cards_save_draft", response_model=CreatedOut,
             summary="Save a draft of mine as a set",
             description=(
                 "With `workspace_id`: creates a new set from the draft. With "
                 "`project_id` and `set_id`: adds the cards of the draft that "
                 "the set does not have yet as a new version; cards with a key "
                 "the set already has are skipped. A draft with problems is "
                 "refused unless `only_valid`. Saving the same draft to the same "
                 "place twice answers the first result. Editor role. "
                 "400 invalid_id, 400 invalid_value, 403 forbidden, "
                 "404 not_found, 409 draft_busy, 409 version_conflict, "
                 "422 cards_invalid, 422 nothing_to_add."))
def сохранить(draft_id: str, тело: SaveDraftIn, request: Request, s: SessionDep,
              user: CurrentUser) -> dict:
    return сохранить_черновик(draft_id, тело, request, s, user)


def сохранить_черновик(draft_id: str, тело: SaveDraftIn, request: Request, s,
                       user, *, where: str = "path.draft_id") -> dict:
    settings = настройки(request)
    drafts = черновики(settings, user.id)
    мета = черновик(drafts, draft_id, where=where)
    if мета.get("status") == ИДЁТ:
        raise ApiError(DRAFT_BUSY, "The agent is still writing this draft", 409,
                       where=where)
    в_набор = bool(тело.project_id or тело.set_id)
    if в_набор == bool(тело.workspace_id) or (в_набор and not (тело.project_id
                                                             and тело.set_id)):
        raise ApiError(INVALID_VALUE,
                       "Name either workspace_id or project_id with set_id", 400,
                       where="body")
    сохранён = мета.get("saved") if isinstance(мета.get("saved"), dict) else None
    if сохранён and (
            (в_набор and сохранён.get("set_id") == тело.set_id
             and сохранён.get("appended"))
            or (not в_набор and сохранён.get("workspace_id") == тело.workspace_id
                and not сохранён.get("appended"))):
        return {"project_id": сохранён["project_id"],
                "set_id": сохранён["set_id"],
                "version": int(сохранён.get("version") or 1)}

    текст = drafts.text(draft_id)
    имя = str(мета.get("filename") or "")
    if в_набор:
        итог = дополнить_набор(s, settings, user, тело.project_id, тело.set_id,
                               текст, имя, тело.only_valid)
    else:
        ws = require_role(s, user.id,
                          check_id(тело.workspace_id, where="body.workspace_id"),
                          EDITOR, where="body.workspace_id")
        итог = завести_набор(s, settings, user, ws, текст, имя, тело.only_valid)
    drafts.update(draft_id, saved={**итог, "appended": в_набор,
                                   "workspace_id": тело.workspace_id})
    return итог


# ── набор ────────────────────────────────────────────────────────────────────

ПУТЬ = "/projects/{project_id}/cards/sets/{set_id}"


def открытый_заход(s, settings, user_id: str, set_id: str, версия: int):
    порог = now() - datetime.timedelta(hours=settings.cards_resume_hours)
    return s.scalars(
        select(CardsSession)
        .where(CardsSession.user_id == user_id, CardsSession.set_id == set_id,
               CardsSession.ended_at.is_(None), CardsSession.version == версия,
               CardsSession.started_at >= порог)
        .order_by(CardsSession.started_at.desc())).first()


@router.get(ПУТЬ, operation_id="cards_set", response_model=SetOut,
            summary="One card set with my settings and progress",
            description=(
                "The set: title, description, topics with their card counts, "
                "the recommended settings, the version and its history, my "
                "settings (the recommended ones until I change them), my "
                "progress in the set and per topic, and my unfinished session "
                "to continue when there is one. Viewer role. 400 invalid_id, "
                "404 not_found."))
def набор_маршрут(set_id: str, request: Request, проект: ЧитательПроекта,
                  s: SessionDep, user: CurrentUser) -> dict:
    settings = настройки(request)
    запись, вид, версия, карточки = набор_целиком(проект, s, set_id)
    мета = вид.state(МЕТА) or {}
    в_теме: dict = {}
    for c in карточки.cards:
        в_теме[c.topic] = в_теме.get(c.topic, 0) + 1
    заход = открытый_заход(s, settings, user.id, запись.id, версия)
    return {
        "project_id": проект.id, "set_id": запись.id,
        "title": str(мета.get("title") or карточки.title or запись.name),
        "description": str(мета.get("description") or карточки.description or ""),
        "language": карточки.language or "",
        "topics": [{"id": t.id, "title": t.title, "cards": в_теме.get(t.id, 0)}
                   for t in карточки.topics],
        "cards_count": len(карточки.cards),
        "defaults": рекомендуемые(карточки), "version": версия,
        "versions": [{"n": int(в.get("n") or 0), "at": в.get("at"),
                      "filename": str(в.get("filename") or ""),
                      "cards": int(в.get("cards") or 0)}
                     for в in мета.get("versions") or () if isinstance(в, dict)],
        "my_settings": мои_настройки(s, user.id, запись.id, карточки),
        "my_progress": мой_прогресс(карточки, прогресс(s, user.id, запись.id)),
        "open_session": None if заход is None else {
            "session_id": заход.id, "pos": int(заход.pos or 0),
            "total": len(set(заход.keys_json or ())),
            "started_at": iso(заход.started_at)},
        "can_edit": редактор(проект),
        "updated_at": мета.get("updated_at")}


@router.get(ПУТЬ + "/cards", operation_id="cards_set_cards",
            response_model=CardsPageOut,
            summary="Cards of a set, a page at a time",
            description=(
                "Cards in file order with my last answer and the `changed` mark. "
                "`q` searches questions, answers and notes; `topic` is a topic "
                "id, or `-` for cards without a topic. `keys` — up to 100 keys "
                "separated by commas — returns exactly those cards in that "
                "order. `from`/`to` page the result, `to` not included, at most "
                "1000 at a time. `total` counts the result before paging. "
                "Viewer role. 400 invalid_id, 400 invalid_value, "
                "404 not_found."))
def карточки_набора(set_id: str, проект: ЧитательПроекта, s: SessionDep,
                    user: CurrentUser,
                    from_: int = Query(0, alias="from", ge=0),
                    to: int | None = Query(None, ge=0),
                    q: str = Query("", max_length=200),
                    topic: str = Query("", max_length=64),
                    keys: str = Query("", max_length=КЛЮЧЕЙ_В_ЗАПРОСЕ * (KEY_MAX + 1))
                    ) -> dict:
    запись, вид, _, карточки = набор_целиком(проект, s, set_id)
    конец = from_ + СТРАНИЦА if to is None else to
    if конец < from_ or конец - from_ > СТРАНИЦА_МАКС:
        raise ApiError(INVALID_VALUE,
                       f"to must be from `from` to `from` + {СТРАНИЦА_МАКС}", 400,
                       where="query.to")
    отобраны = list(карточки.cards)
    if keys.strip():
        названные = [к.strip() for к in keys.split(",") if к.strip()]
        if len(названные) > КЛЮЧЕЙ_В_ЗАПРОСЕ:
            raise ApiError(INVALID_VALUE,
                           f"At most {КЛЮЧЕЙ_В_ЗАПРОСЕ} keys at a time", 400,
                           where="query.keys")
        по_ключу = {c.key: c for c in отобраны}
        отобраны = [по_ключу[к] for к in названные if к in по_ключу]
    if topic:
        нужна = None if topic == БЕЗ_ТЕМЫ else topic
        отобраны = [c for c in отобраны if c.topic == нужна]
    if q.strip():
        иголка = q.strip().casefold()
        отобраны = [c for c in отобраны
                    if иголка in c.q.casefold() or иголка in c.a.casefold()
                    or иголка in (c.note or "").casefold()]
    мои = прогресс(s, user.id, запись.id)
    изменённые = (вид.state(МЕТА) or {}).get("changed") or {}
    return {"cards": [карточка(c, мои.get(c.key), изменённые)
                      for c in отобраны[from_:конец]],
            "total": len(отобраны)}


@router.put(ПУТЬ + "/defaults", operation_id="cards_put_defaults",
            response_model=SettingsModel,
            summary="Write the recommended settings of a set",
            description=(
                "Replaces the recommended session settings of the set. People "
                "who never changed their own settings start from these; the "
                "downloaded file carries them. Editor role. 400 invalid_id, "
                "400 invalid_value, 403 forbidden, 404 not_found."))
def записать_рекомендуемые(set_id: str, тело: SettingsModel,
                           проект: РедакторПроекта, s: SessionDep) -> dict:
    _, вид, _, карточки = набор_целиком(проект, s, set_id)
    значения = уставки(тело, where="body")
    набор.rewrite_set(вид, набор.with_identity(карточки, defaults=значения))
    мета = вид.state(МЕТА) or {}
    вид.put_state(МЕТА, {**мета, "updated_at": сейчас()})
    return значения


@router.put(ПУТЬ + "/my-settings", operation_id="cards_put_my_settings",
            response_model=SettingsModel,
            summary="Write my session settings for a set",
            description=(
                "Replaces my own session settings for this set; nobody else "
                "sees them. `reset` forgets them and answers the recommended "
                "ones. Viewer role. 400 invalid_id, 400 invalid_value, "
                "404 not_found."))
def записать_мои(set_id: str, тело: MySettingsIn, проект: ЧитательПроекта,
                 s: SessionDep, user: CurrentUser) -> dict:
    запись, _, _, карточки = набор_целиком(проект, s, set_id)
    строка = s.get(CardsSettings, (user.id, запись.id))
    if тело.reset:
        if строка is not None:
            s.delete(строка)
            s.flush()
        return рекомендуемые(карточки)
    значения = уставки(тело, where="body")
    if строка is None:
        s.add(CardsSettings(user_id=user.id, set_id=запись.id,
                            settings_json=значения))
    else:
        строка.settings_json = значения
    s.flush()
    return значения


@router.post(ПУТЬ + "/replace/preview", operation_id="cards_replace_preview",
             response_model=ReplacePreviewOut,
             summary="Read a new file for a set into a draft",
             description=(
                 "Reads a new version of the set file into a draft of mine and "
                 "answers its problems and how it differs from the current "
                 "version: keys added, changed (same key, other text) and "
                 "removed. Nothing changes in the set until POST …/replace. "
                 "A JSON card file or a `.csv`/`.tsv` table: JSON "
                 "`{text, filename}` or a multipart file, at most 5 MB; a "
                 "Markdown `.md` file is refused. "
                 "Editor role. 400 invalid_id, 400 invalid_value, "
                 "403 forbidden, 404 not_found, 413 file_too_large, "
                 "415 unsupported_type, 422 cards_invalid."),
             openapi_extra=ТЕЛО_ФАЙЛА)
async def превью_замены(set_id: str, request: Request, проект: РедакторПроекта,
                        s: SessionDep, user: CurrentUser) -> dict:
    settings = настройки(request)
    тело = await текст_из_запроса(request, settings.cards_file_max_bytes)
    формат_файла(тело["filename"])

    def работа() -> dict:
        запись, _, _, старый = набор_целиком(проект, s, set_id)
        карточки, проблемы = разобрать(тело["text"], тело["filename"])
        ид = черновики(settings, user.id).create(
            {"source": "upload", "status": ГОТОВ, "filename": тело["filename"],
             "target": {"project_id": проект.id, "set_id": запись.id},
             "user_id": user.id},
            набор.draft_text(тело["text"], тело["filename"]))
        return {"draft_id": ид,
                "problems": [набор.problem_json(п) for п in проблемы],
                "stats": сводка(карточки, проблемы),
                "diff": (разница(старый, карточки) if карточки is not None
                         else {"added": [], "changed": [], "removed": []})}

    return await run_in_threadpool(работа)


@router.post(ПУТЬ + "/replace", operation_id="cards_replace",
             response_model=ReplaceOut,
             summary="Replace a set with a new version from a draft",
             description=(
                 "Makes the draft the next version of the set. Progress stays "
                 "with every key that is still there; a card whose key stayed "
                 "and whose text changed is marked `changed` for people who "
                 "answered it before, until they answer it again; cards whose "
                 "key is gone leave the set, their attempts stay. The title and "
                 "description of the set stay; the recommended settings come "
                 "from the file. Editor role. 400 invalid_id, 403 forbidden, "
                 "404 not_found, 409 draft_busy, 409 version_conflict, "
                 "422 cards_invalid."))
def заменить(set_id: str, тело: ReplaceIn, request: Request,
             проект: РедакторПроекта, s: SessionDep, user: CurrentUser) -> dict:
    settings = настройки(request)
    запись, вид, _, старый = набор_целиком(проект, s, set_id)
    drafts = черновики(settings, user.id)
    мета_черновика = черновик(drafts, тело.draft_id, where="body.draft_id")
    if мета_черновика.get("status") == ИДЁТ:
        raise ApiError(DRAFT_BUSY, "The agent is still writing this draft", 409,
                       where="body.draft_id")
    текст = drafts.text(тело.draft_id)
    имя = str(мета_черновика.get("filename") or "")
    новый = годный(текст, имя, тело.only_valid)
    новый = набор.with_identity(новый, title=старый.title,
                                description=старый.description)
    d = разница(старый, новый)
    мета = вид.state(МЕТА) or {}
    ключи = {c.key for c in новый.cards}
    изменённые = {к: когда for к, когда in (мета.get("changed") or {}).items()
                  if к in ключи}
    # Момент замены — с долями секунды: пометка сравнивается с моментом ответа,
    # и ответ, данный в ту же секунду до замены, иначе оказался бы «позже» неё.
    момент = datetime.datetime.now(datetime.timezone.utc).isoformat().replace(
        "+00:00", "Z")
    for к in d["changed"]:
        изменённые[к] = момент
    версия = записать_версию(вид, новый, байты=текст.encode("utf-8"),
                             filename=имя, user=user, изменённые=изменённые)
    drafts.update(тело.draft_id, saved={"project_id": проект.id,
                                        "set_id": запись.id, "version": версия,
                                        "appended": False, "replaced": True})
    return {"version": версия, "added": len(d["added"]),
            "changed": len(d["changed"]), "removed": len(d["removed"])}


@router.patch(ПУТЬ, operation_id="cards_patch_set", response_model=PatchOut,
              summary="Rename a set or change its description",
              description=(
                  "Changes the title and/or description; a field left null is "
                  "kept. Editor role. 400 invalid_id, 403 forbidden, "
                  "404 not_found, 422 validation_failed."))
def поправить(set_id: str, тело: PatchIn, проект: РедакторПроекта,
              s: SessionDep) -> dict:
    запись, вид, _, карточки = набор_целиком(проект, s, set_id)
    мета = вид.state(МЕТА) or {}
    название = (тело.title.strip() if тело.title is not None
                else str(мета.get("title") or карточки.title))
    if not название:
        raise ApiError(INVALID_VALUE, "title is not empty", 400, where="body.title")
    описание = (тело.description.strip() if тело.description is not None
                else str(мета.get("description") or карточки.description or ""))
    набор.rewrite_set(вид, набор.with_identity(карточки, title=название,
                                               description=описание))
    вид.put_state(МЕТА, {**мета, "title": название, "description": описание,
                         "updated_at": сейчас()})
    запись.name = название[:NAME_MAX]
    s.flush()
    return {"title": название, "description": описание}


@router.delete(ПУТЬ, status_code=204, operation_id="cards_delete_set",
               summary="Delete a set",
               description=(
                   "Removes the set: its journal entry, its versions and the "
                   "sessions, attempts, progress and settings of everyone in "
                   "it. Uploaded source files stay as artifacts of the work "
                   "until the work is cleaned up. Editor role. 400 invalid_id, "
                   "403 forbidden, 404 not_found."),
               response_class=Response)
def удалить(set_id: str, проект: РедакторПроекта, s: SessionDep) -> Response:
    запись = найти_набор(s, проект.id, set_id)
    for таблица in (CardsAttempt, CardsProgress, CardsSettings, CardsSession):
        s.execute(delete(таблица).where(таблица.set_id == запись.id))
    на_томе = открыть(проект)
    на_томе.drop_solution(запись.id)
    s.delete(запись)
    s.flush()
    return Response(status_code=204)


@router.get(ПУТЬ + "/download", operation_id="cards_download",
            response_class=Response,
            responses={200: {"content": {"application/json": {}},
                             "description": "The set as a JSON card file"}},
            summary="Download a set as a JSON card file",
            description=(
                "The current version as a canonical JSON card file, with an id "
                "on every card and topics by title, so a file downloaded, "
                "edited and uploaded again keeps everyone's progress. The file "
                "is named after the set. Only `format=json`. Viewer role. "
                "400 invalid_id, 400 invalid_value, 404 not_found."))
def скачать(set_id: str, проект: ЧитательПроекта, s: SessionDep,
            format: str = Query("json")) -> Response:
    if format != "json":
        raise ApiError(INVALID_VALUE, "format must be json", 400,
                       where="query.format")
    запись, вид, _, карточки = набор_целиком(проект, s, set_id)
    текст = набор.write_json(карточки)
    имя = upload.имя_файла(f"{карточки.title or запись.name or 'cards'}.json")
    return Response(content=текст.encode("utf-8"),
                    media_type="application/json; charset=utf-8",
                    headers={"Content-Disposition": upload.заголовок_имени(имя)})


# ── заходы ───────────────────────────────────────────────────────────────────

@router.post(ПУТЬ + "/sessions", status_code=201,
             operation_id="cards_start_session",
             response_model=SessionStartedOut,
             summary="Start a session on a set",
             description=(
                 "Plans a session and answers its keys in order with the first "
                 "20 cards. `settings` plays by my settings, `wrong` every card "
                 "whose last answer of mine is No, `all_file` the whole set in "
                 "file order; `keys` plays exactly the cards named. Shuffling "
                 "is stable within the session. My earlier unfinished sessions "
                 "of this set are closed. Viewer role. 400 invalid_id, "
                 "400 invalid_value, 404 not_found, 422 nothing_to_play."))
def начать(set_id: str, request: Request, проект: ЧитательПроекта,
           s: SessionDep, user: CurrentUser,
           тело: SessionIn | None = None) -> dict:
    тело = тело or SessionIn()
    запись, вид, версия, карточки = набор_целиком(проект, s, set_id)
    мои = прогресс(s, user.id, запись.id)
    мои_уставки = мои_настройки(s, user.id, запись.id, карточки)
    ид = new_id()
    if тело.keys is not None:
        есть = {c.key for c in карточки.cards}
        план = [к for к in dict.fromkeys(тело.keys) if к in есть]
        уставки_захода = {**мои_уставки, "preset": "keys"}
    else:
        if тело.preset == "wrong":
            уставки_захода = {**мои_уставки, "session_size": 0, "topics": None,
                              "include": "wrong"}
        elif тело.preset == "all_file":
            уставки_захода = {**мои_уставки, "session_size": 0, "topics": None,
                              "include": "all", "order": "file"}
        else:
            уставки_захода = dict(мои_уставки)
        уставки_захода["preset"] = тело.preset
        последние = {к: (п.last_answer == YES) if п.last_answer else None
                     for к, п in мои.items()}
        try:
            план = набор.plan_session(
                карточки, последние,
                size=int(уставки_захода.get("session_size") or 0) or None,
                order=str(уставки_захода.get("order")),
                topics=уставки_захода.get("topics"),
                include=str(уставки_захода.get("include")),
                seed=int(hashlib.sha1(ид.encode()).hexdigest()[:8], 16))
        except Exception:                                    # noqa: BLE001
            беды.exception("набор %s: план захода не составлен", запись.id)
            raise ApiError(INVALID_VALUE, "These settings cannot make a session",
                           400, where="body") from None
    if not план:
        raise ApiError(NOTHING_TO_PLAY, "There are no cards for this session",
                       422, where="body")
    момент = now()
    s.execute(update(CardsSession)
              .where(CardsSession.user_id == user.id,
                     CardsSession.set_id == запись.id,
                     CardsSession.ended_at.is_(None))
              .values(ended_at=момент))
    s.add(CardsSession(id=ид, user_id=user.id, set_id=запись.id, version=версия,
                       keys_json=list(план), pos=0,
                       settings_json=уставки_захода, started_at=момент))
    s.flush()
    изменённые = (вид.state(МЕТА) or {}).get("changed") or {}
    по_ключу = {c.key: c for c in карточки.cards}
    return {"session_id": ид, "version": версия, "keys": list(план),
            "settings": уставки_захода,
            "cards": [карточка(по_ключу[к], мои.get(к), изменённые)
                      for к in план[:КАРТОЧЕК_В_НАЧАЛЕ]]}


ПУТЬ_ЗАХОДА = "/projects/{project_id}/cards/sessions/{session_id}"


def мой_заход(s, проект, user_id: str, session_id: str) -> CardsSession:
    """Заход этого человека в наборе этой работы или `404`."""
    заход = s.get(CardsSession, check_id(session_id, where="path.session_id"))
    if заход is None or заход.user_id != user_id:
        raise ApiError(NOT_FOUND, "Session not found", 404, where="path.session_id")
    запись = s.get(ProjectRun, заход.set_id)
    if запись is None or запись.project_id != проект.id or запись.module != МОДУЛЬ:
        raise ApiError(NOT_FOUND, "Session not found", 404, where="path.session_id")
    return заход


@router.get(ПУТЬ_ЗАХОДА, operation_id="cards_session", response_model=SessionOut,
            summary="One session of mine",
            description=(
                "The plan of the session, how many of its cards are answered, "
                "every answer in the order they were given (`corrects` is the "
                "client_seq of the answer it replaced) and whether the set was "
                "replaced since. Only my own sessions. Viewer role. "
                "400 invalid_id, 404 not_found."))
def заход_маршрут(session_id: str, проект: ЧитательПроекта, s: SessionDep,
                  user: CurrentUser) -> dict:
    return заход_наружу(s, проект, мой_заход(s, проект, user.id, session_id))


@router.get(ПУТЬ + "/sessions/open", operation_id="cards_open_session",
            response_model=SessionOut,
            responses={204: {"description": "No session to continue"}},
            summary="My unfinished session of a set",
            description=(
                "My latest unfinished session of the current version of this "
                "set, started within the resume window (12 hours), in the same "
                "shape as GET …/sessions/{session_id}; 204 when there is none. "
                "Lets Continue work across devices. Viewer role. "
                "400 invalid_id, 404 not_found."))
def открытый_заход_маршрут(set_id: str, request: Request,
                           проект: ЧитательПроекта, s: SessionDep,
                           user: CurrentUser):
    запись = найти_набор(s, проект.id, set_id)
    вид = открыть(проект).create_solution(запись.id)
    версия = int((вид.state(МЕТА) or {}).get("version") or 0)
    заход = открытый_заход(s, настройки(request), user.id, запись.id, версия)
    if заход is None:
        return Response(status_code=204)
    return заход_наружу(s, проект, заход)


def заход_наружу(s, проект, заход: CardsSession) -> dict:
    """Заход с его ответами в форме `SessionOut`."""
    попытки = list(s.scalars(select(CardsAttempt)
                             .where(CardsAttempt.session_id == заход.id)
                             .order_by(CardsAttempt.client_seq)))
    номер = {п.id: п.client_seq for п in попытки}
    вид = открыть(проект).create_solution(заход.set_id)
    текущая = int((вид.state(МЕТА) or {}).get("version") or 0)
    return {"session_id": заход.id, "set_id": заход.set_id,
            "version": int(заход.version), "keys": list(заход.keys_json or ()),
            "pos": int(заход.pos or 0), "settings": dict(заход.settings_json or {}),
            "answers": [{"key": п.card_key, "answer": п.answer, "shown": п.shown,
                         "ms": п.ms, "client_seq": п.client_seq,
                         "corrects": номер.get(п.corrects_id) if п.corrects_id
                         else None,
                         "at": iso(п.at)} for п in попытки],
            "started_at": iso(заход.started_at), "ended_at": iso(заход.ended_at),
            "stale": bool(текущая and текущая != int(заход.version))}


def ответ_захода(s, заход: CardsSession, попытка: CardsAttempt) -> dict:
    строка = s.get(CardsProgress, (заход.user_id, заход.set_id, попытка.card_key))
    return {"key": попытка.card_key, "client_seq": попытка.client_seq,
            "pos": int(заход.pos or 0), "total": len(set(заход.keys_json or ())),
            "ended": заход.ended_at is not None,
            "progress": {"last_answer": строка.last_answer if строка else None,
                         "yes": int(строка.yes) if строка else 0,
                         "no": int(строка.no) if строка else 0}}


@router.post(ПУТЬ_ЗАХОДА + "/answers", operation_id="cards_answer",
             response_model=AnswerOut,
             summary="Answer a card in a session",
             description=(
                 "Writes my Yes or No for a card of the session at once and "
                 "recounts my progress on that card: it is known when its last "
                 "answer is Yes. The same card may be answered again within the "
                 "session. `corrects` names, by client_seq, an earlier answer "
                 "of this session to the same card that this one replaces. A "
                 "repeat with a client_seq already written answers 200 with the "
                 "same result and writes nothing. Viewer role. 400 invalid_id, "
                 "400 invalid_value, 404 not_found."))
def ответить(session_id: str, тело: AnswerIn, проект: ЧитательПроекта,
             s: SessionDep, user: CurrentUser) -> dict:
    заход = мой_заход(s, проект, user.id, session_id)

    def уже_есть():
        return s.scalars(select(CardsAttempt).where(
            CardsAttempt.session_id == заход.id,
            CardsAttempt.client_seq == тело.client_seq)).first()

    было = уже_есть()
    if было is not None:
        return ответ_захода(s, заход, было)
    ключи = list(заход.keys_json or ())
    if тело.key not in ключи:
        raise ApiError(INVALID_VALUE, "This card is not in the session", 400,
                       where="body.key")
    if тело.answer not in ANSWERS:
        raise ApiError(INVALID_VALUE, "answer is yes or no", 400,
                       where="body.answer")
    исправляет = None
    if тело.corrects is not None:
        прежняя = s.scalars(select(CardsAttempt).where(
            CardsAttempt.session_id == заход.id,
            CardsAttempt.client_seq == тело.corrects)).first()
        if прежняя is None or прежняя.card_key != тело.key:
            raise ApiError(INVALID_VALUE,
                           "corrects names an earlier answer to this card", 400,
                           where="body.corrects")
        исправляет = прежняя.id

    попытка = CardsAttempt(user_id=user.id, set_id=заход.set_id,
                           card_key=тело.key, session_id=заход.id,
                           answer=тело.answer, shown=bool(тело.shown),
                           ms=int(тело.ms), client_seq=тело.client_seq,
                           corrects_id=исправляет, at=now())
    s.add(попытка)
    try:
        s.flush()
    except IntegrityError:
        # Тот же ответ пришёл вторым запросом одновременно с первым.
        s.rollback()
        заход = мой_заход(s, проект, user.id, session_id)
        было = уже_есть()
        if было is None:
            raise
        return ответ_захода(s, заход, было)

    пересчитать(s, user.id, заход.set_id, тело.key)
    отвечено = int(s.scalar(
        select(func.count(distinct(CardsAttempt.card_key)))
        .where(CardsAttempt.session_id == заход.id)) or 0)
    заход.pos = min(отвечено, len(set(ключи)))
    if заход.ended_at is None and заход.pos >= len(set(ключи)):
        заход.ended_at = now()
    s.flush()
    return ответ_захода(s, заход, попытка)


__all__ = ["router", "МОДУЛЬ", "ИМЯ_РАБОТЫ", "МЕТА", "КЛЮЧИ", "ГОТОВ", "ИДЁТ",
           "СДЕЛАН", "НЕ_ВЫШЛО", "ОТМЕНЁН", "черновики", "работа_наборов",
           "найти_набор", "разобрать", "сводка", "сейчас"]
