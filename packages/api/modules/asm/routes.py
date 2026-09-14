"""
routes — ассемблер: `/api/asm` и `/api/projects/{id}/asm`.

    GET    /api/asm/status                                  200  есть ли инструменты
    GET    /api/asm/programs?workspace_id=                  200  программы пространства
    POST   /api/asm/programs                                201  завести программу (editor)
    GET    /api/projects/{id}/asm/programs/{pid}            200  исходник, настройки, последний прогон
    PUT    …/programs/{pid}/source                          200  записать исходник (editor)
    PUT    …/programs/{pid}/settings                        200  записать настройки (editor)
    PATCH  …/programs/{pid}                                 200  переименовать (editor)
    DELETE …/programs/{pid}                                 204  снести программу (editor)
    POST   …/programs/{pid}/runs                            202  собрать / собрать и запустить (editor)
    GET    …/programs/{pid}/runs/{n}                        200  итог прогона или его ход
    GET    …/programs/{pid}/runs/{n}/steps?from=&to=        200  шаги трассы страницей
    GET    …/programs/{pid}/runs/{n}/debugx?from=&to=       200  сырой вывод отладчика куском
    POST   …/programs/{pid}/runs/{n}/memory                 202  дамп памяти на шаге (editor)
    GET    …/programs/{pid}/chat                            200  переписка с агентом
    POST   …/programs/{pid}/chat                            202  сообщение агенту (editor)

**Программа — это решение работы**, ровно как доска (`modules/board/routes.py`
объясняет выбор подробно): запись журнала запусков с `module: "asm"` и каталог
решения под ней. Своей таблицы нет; имя, номер и «кто завёл» уже описаны
журналом. Программы спрашивают по пространству, а новая ложится в **неявную
работу** «Ассемблер», которая заводится при первой программе.

**Исходник и настройки — записи состояния решения.** Исходник сохраняется по
паузе набора, и материал, адресуемый содержимым, плодил бы строку в описи работы
на каждое нажатие клавиши. `version` у исходника — счётчик оптимистической
блокировки: чужая версия отвечает `409 source_conflict` вместе с тем исходником,
который победил, — две вкладки теряют правку шумно, а не молча. Настройки
(ввод программы, лимит шагов, флаги сборки, точки останова, наблюдения)
заменяются целиком и версий не ведут: это не текст, который набирают вдвоём.

**Прогон — каталог под решением**, `asm-runs/<n>/`. Номер занимается созданием
каталога, туда же ложится снимок исходника и настроек на момент постановки, и
только потом ставится задание `asm_run`: трасса обязана описывать ту программу,
по которой нажали кнопку, а не ту, что в редакторе через минуту. Всё
остальное в каталоге пишет ядро. Хранится двадцать последних законченных
прогонов: трасса в полмиллиона шагов занимает сотни мегабайт, а смотрят
человек и агент последний прогон.

**Пока прогон идёт, итога нет, а статус есть.** `GET …/runs/{n}` читает
`summary.json`; нет его — статус складывается из задания очереди: `queued`,
`building` (этапы `tasm`, `tlink`), `running` (этап `trace`). Отменённое или
упавшее задание без итога отвечает `crashed` со словами беды: новых статусов
сайт не знает, а «прогон не состоялся» для окна прогона — одно событие.

**Трасса отдаётся кусками.** Шаги — страницей не больше 2000 по номерам шагов
`i`, полуинтервалом `[from, to)`; `total` — сколько шагов выполнено всего, даже
если середина трассы свёрнута. Сырой вывод отладчика — текстом за те же номера.

**Всё, что запускает эмулятор или зовёт модель, — через очередь.** Сборка,
дамп памяти на шаге и сообщение агенту ставят задания `asm_run`, `asm_memory`
и `asm_chat`: у запуска есть цена, месячный потолок, отмена и журнал, и
синхронный маршрут обошёл бы все четыре. Путей на томе здесь нет ни одного:
каталог прогонов знает `orchestrator.asm`.

**Модуль без инструментов не показывается** (`modules/asm/__init__.py`): TASM
и TLINK приходят каталогом с машины выката. Показанный настройкой
`KORITSU_ASM_SHOW` для разработки сайта, он честно отказывает в постановке
прогона — `503 asm_unavailable`.

Коды отказа: `400 invalid_id` — форма идентификатора; `400 invalid_value` —
тело не годится (флаг сборки не той формы, лимит шагов больше потолка, страница
длиннее 2000 шагов, якорь незнакомого вида); `400 source_too_big` — исходник
больше потолка; `400 endpoint_required` — не назван поставщик модели;
`403 forbidden` — роли мало; `402 limit_exhausted` — месяц кончился;
`404 not_found` — нет проекта, программы или прогона; `409 source_conflict` —
исходник переписали из другой вкладки; `409 run_not_ready` — у прогона нет
собранной программы; `503 asm_unavailable` — на машине нет инструментов.
"""
from __future__ import annotations

import datetime
import os
import re
from typing import Literal

from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from orchestrator import asm as ассемблер

from ...db import SessionDep
from ...errors import ApiError, ErrorBody, NOT_FOUND
from ...ids import check_id
from ...jobs import service as задания
from ...jobs.models import CANCELLED, FAILED, QUEUED, RUNNING, Job
from ...jobs.registry import ASM_CHAT, ASM_MEMORY, ASM_RUN
from ...log import беды
from ...materials.deps import CurrentUser, РедакторПроекта, ЧитательПроекта
from ...materials.service import открыть
from ...projects.models import NAME_MAX, Project, ProjectRun
from ...projects.routes import завести_работу, настройки
from ...projects.routes import открыть as открыть_работу
from ...projects.runs import завести
from ...workspaces.service import EDITOR, VIEWER, iso, require_role

router = APIRouter(tags=["asm"])

# Модуль, записями которого журнал держит программы.
МОДУЛЬ = "asm"

# Имена записей состояния решения. Три: исходник с версией, настройки прогона и
# переписка с агентом.
ИСХОДНИК = "асм-исходник"
НАСТРОЙКИ = "асм-настройки"
ЧАТ = "асм-чат"

# Неявная работа пространства, в которой заводятся программы. Имя, а не флаг,
# по той же причине, что у досок: переименованная работа перестаёт быть
# неявной, и следующая программа заведёт себе новую.
ИМЯ_РАБОТЫ = "Ассемблер"

# Потолок исходника. Учебная программа на ассемблере — сотни строк, а не
# мегабайты; исходник целиком уезжает в запись состояния на каждое
# автосохранение и в промпт агента.
ИСХОДНИК_МАКС = 256 * 1024

# Потолок ввода программы: то, что человек заранее набирает в окне «Ввод».
ВВОД_МАКС = 64 * 1024

# Флаги сборки уезжают в командную строку TASM и TLINK внутри DOS. Форма
# закрыта: косая, буквы, цифры и несколько знаков. Всё прочее — пробел, `&`,
# `>`, `|` — это уже не флаг, а вторая команда в сценарии эмулятора.
ФЛАГ = re.compile(r"^/[A-Za-z0-9:=._+-]{1,31}$")
ФЛАГОВ_МАКС = 16

ТОЧЕК_МАКС = 1000
НАБЛЮДЕНИЙ_МАКС = 100
НАБЛЮДЕНИЕ_МАКС = 128

# Страница трассы. Две тысячи шагов — около мегабайта JSON: окно листает
# трассу страницами, а не тянет её целиком.
ШАГОВ_НА_СТРАНИЦЕ = 2000

# Сколько законченных прогонов хранится у программы — см. докстроку модуля.
ПРОГОНОВ_ХРАНИТСЯ = 20

# Переписка: сколько хранится и сколько едет модели. Хранится больше, чем едет:
# человек листает свой разговор целиком, модели хватает последних реплик.
СООБЩЕНИЙ_МАКС = 200
СООБЩЕНИЙ_МОДЕЛИ = 20
СООБЩЕНИЕ_МАКС = 4000

# Дамп на шаге: сколько диапазонов за раз и сколько байт в диапазоне. Окно
# «Дамп» показывает страницу памяти, а не сегмент целиком.
ДИАПАЗОНОВ_МАКС = 16
ДИАПАЗОН_МАКС = 4096
ШЕСТНАДЦАТЕРИЧНОЕ = re.compile(r"^[0-9A-Fa-f]{1,8}$")

# Сколько секунд прогон без задания в базе считается ещё не записанным, а не
# потерянным: снимок ложится на том раньше, чем закрывается транзакция
# постановки.
ЗАПИСЬ_В_ПУТИ_С = 60

# Коды отказа этого модуля.
ASM_UNAVAILABLE = "asm_unavailable"
SOURCE_CONFLICT = "source_conflict"
SOURCE_TOO_BIG = "source_too_big"
RUN_NOT_READY = "run_not_ready"
INVALID_VALUE = "invalid_value"
ENDPOINT_REQUIRED = "endpoint_required"

# Настройки новой программы. Флаги — те, с которыми собирает договор ядра:
# `/zi /l` дают отладочные символы и листинг, `/v` — карту для отладчика.
УМОЛЧАНИЯ = {"stdin": "", "step_limit": 100_000, "mode32": False,
             "tasm_flags": ["/zi", "/l"], "tlink_flags": ["/v"],
             "breakpoints": [], "watches": []}

# Якорь сообщения агенту: вид → его поля и их тип.
ЯКОРЯ = {"line": {"line": int}, "register": {"name": str},
         "flag": {"name": str}, "cell": {"seg": str, "off": str},
         "doc": {"id": str}, "run": {},
         # Поля выделенного текста проверяет `якорь_текста`: они не укладываются
         # в «число от 1 или короткая строка».
         "text": {}}

# Якорь «выделенный текст»: из каких окон и сколько символов. Выделение едет в
# промпт целиком, поэтому потолок тот же, что у самого сообщения.
ОКНА_ТЕКСТА = ("source", "listing", "output", "debugx", "build")
ТЕКСТ_ЯКОРЯ_МАКС = 4000


# ── формы ────────────────────────────────────────────────────────────────────

class StatusOut(BaseModel):
    """Есть ли на машине то, чем собирается и трассируется программа."""

    available: bool = Field(
        description=("Whether programs can be built and traced here. False is "
                     "a state of the machine, not an error of the request."))
    dosbox: bool = Field(description="DOSBox-X is found")
    tasm: bool = Field(description="TASM.EXE is in the tools directory")
    tlink: bool = Field(description="TLINK.EXE is in the tools directory")
    debugx: bool = Field(description="DEBUGX.COM is found")


class ProgramCardOut(BaseModel):
    """Программа в ленте пространства."""

    project_id: str
    program_id: str = Field(description="Run id of this program in its project")
    name: str = Field(description="Empty means the interface names it itself")
    n: int = Field(description="Which program of its project, from 1")
    created_at: str | None = None
    updated_at: str | None = Field(
        default=None, description="When the source was last written")
    last_status: str | None = Field(
        default=None,
        description=("Status of the last run: queued, building, running, done, "
                     "build_error, step_limit, timeout or crashed. Null when "
                     "the program was never run."))


class ProgramCreateIn(BaseModel):
    """Тело заведения программы: в каком пространстве и как звать."""

    workspace_id: str = Field(
        description=("Which workspace the program goes to. The work it lands "
                     "in is chosen by the service."))
    name: str = Field(
        default="", max_length=NAME_MAX,
        description="What to call it. Empty is fine: the interface names it")


class ProgramCreatedOut(BaseModel):
    project_id: str
    program_id: str
    name: str
    n: int


class AsmSettingsModel(BaseModel):
    """Настройки прогона программы. Заменяются целиком."""

    stdin: str = Field(
        default="", max_length=ВВОД_МАКС,
        description=("Everything the program will read from standard input, "
                     "set in advance: a run does not pause for typing."))
    step_limit: int = Field(
        default=100_000, ge=1,
        description="How many steps the trace may take before it stops")
    mode32: bool = Field(default=False,
                         description="Trace 32-bit registers as well")
    tasm_flags: list[str] = Field(
        default_factory=lambda: ["/zi", "/l"], max_length=ФЛАГОВ_МАКС,
        description="Command line flags of TASM, each of the form /x")
    tlink_flags: list[str] = Field(
        default_factory=lambda: ["/v"], max_length=ФЛАГОВ_МАКС,
        description="Command line flags of TLINK, each of the form /x")
    breakpoints: list[int] = Field(
        default_factory=list, max_length=ТОЧЕК_МАКС,
        description="Source lines with a breakpoint, from 1")
    watches: list[str] = Field(
        default_factory=list, max_length=НАБЛЮДЕНИЙ_МАКС,
        description="Watch expressions, as the page shows them")


class ProgramOut(BaseModel):
    """Программа целиком: исходник с версией, настройки, последний прогон."""

    project_id: str
    program_id: str
    name: str
    n: int
    source: str = ""
    version: int = Field(
        default=0,
        description=("Version counter of the source. Pass it back in PUT "
                     "source: a stale one loses to whoever wrote first."))
    at: str | None = Field(default=None, description="When the source was written")
    settings: AsmSettingsModel
    breakpoints: list[int] = Field(default_factory=list)
    watches: list[str] = Field(default_factory=list)
    last_run_no: int | None = Field(
        default=None, description="Number of the last run, null when never run")


class SourceIn(BaseModel):
    source: str = Field(max_length=ИСХОДНИК_МАКС)
    version: int = Field(
        default=0,
        description=("The version this edit is based on. A version that is not "
                     "the current one answers 409 with the current source."))


class SourceOut(BaseModel):
    version: int
    at: str | None = None


class SourceConflictOut(BaseModel):
    """Ответ `409`: отказ и рядом исходник, который победил."""

    error: ErrorBody
    source: str = ""
    version: int = 0


class RenameIn(BaseModel):
    name: str = Field(
        max_length=NAME_MAX,
        description="New name. Empty resets it to the default name")


class RenameOut(BaseModel):
    program_id: str
    name: str


class RunIn(BaseModel):
    mode: Literal["build", "run"] = Field(
        default="run",
        description="`build` assembles and links only, `run` also traces")


class RunStartedOut(BaseModel):
    job_id: str
    run_no: int


class JobStartedOut(BaseModel):
    job_id: str


class BuildMessageOut(BaseModel):
    severity: str = ""
    tool: str = ""
    line: int | None = None
    text: str = ""


class ListingLineOut(BaseModel):
    line: int = 0
    segment: str | None = None
    offset: str | None = None
    bytes: str = ""
    text: str = ""


class SegmentOut(BaseModel):
    name: str = ""
    cls: str = ""
    start: str = ""
    length: str = ""


class SymbolOut(BaseModel):
    name: str = ""
    segment: str = ""
    offset: str = ""
    kind: str = ""
    size: int | None = None


class BuildOut(BaseModel):
    ok: bool = False
    log: str = Field(default="", description="What TASM and TLINK printed")
    messages: list[BuildMessageOut] = Field(default_factory=list)
    listing: list[ListingLineOut] = Field(default_factory=list)
    segments: list[SegmentOut] = Field(default_factory=list)
    symbols: list[SymbolOut] = Field(default_factory=list)


class LoadOut(BaseModel):
    psp: str = ""
    cs: str = ""
    ds: str = ""
    ss: str = ""


class TotalsOut(BaseModel):
    steps: int = Field(default=0, description="Steps executed in the whole run")
    ms: int = 0
    exit_code: int | None = None


class TruncationOut(BaseModel):
    head: int = 0
    skipped: int = 0
    tail: int = 0


class DumpOut(BaseModel):
    step: int = 0
    seg: str = ""
    off: str = ""
    hex: str = ""


class RunSummaryOut(BaseModel):
    """Итог прогона без шагов, или его ход, пока итога нет.

    Поля, которые ядро допишет сверх перечисленных, уезжают как есть: итог
    читается с тома, и форма его — договор ядра с сайтом, а не выбор службы.
    """

    model_config = ConfigDict(extra="allow")

    run_no: int
    job_id: str | None = None
    status: str = Field(
        description=("queued, building or running while the job goes; done, "
                     "build_error, step_limit, timeout or crashed after"))
    source: str | None = Field(
        default=None,
        description=("The source this run was built from. Line numbers in "
                     "build messages, the listing and steps refer to it"))
    build: BuildOut | None = None
    load: LoadOut | None = None
    stdin: str = ""
    step_limit: int = 0
    mode32: bool = False
    totals: TotalsOut = Field(default_factory=TotalsOut)
    truncated: TruncationOut | None = None
    dumps: list[DumpOut] = Field(default_factory=list)
    error: str | None = None


class MemWriteOut(BaseModel):
    seg: str = ""
    off: str = ""
    old: str = ""
    new: str = ""


class StepNextOut(BaseModel):
    """Команда, которая выполнится следующей."""

    model_config = ConfigDict(extra="allow")

    cs: str = ""
    ip: str = ""
    line: int | None = None
    asm: str = ""
    bytes: str = ""


class StepOut(BaseModel):
    """Один шаг трассы: выполненная команда и состояние после неё.

    Шаг 0 — начальное состояние. Поля сверх перечисленных уезжают как есть:
    шаг — строка `trace.jsonl`, форму которой держит ядро.
    """

    model_config = ConfigDict(extra="allow")

    i: int
    cs: str = ""
    ip: str = ""
    line: int | None = None
    asm: str = ""
    bytes: str = ""
    reg: dict[str, str] = Field(default_factory=dict)
    reg32: dict[str, str] | None = None
    changed: list[str] = Field(default_factory=list)
    mem: list[MemWriteOut] = Field(default_factory=list)
    out: str = ""
    stdin_pos: int = 0
    next: StepNextOut | None = None


class StepsOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    from_: int = Field(alias="from")
    to: int
    total: int = Field(description="Steps executed in the whole run")
    truncated: TruncationOut | None = None
    steps: list[StepOut] = Field(default_factory=list)


class DebugxOut(BaseModel):
    text: str = Field(default="", description="Raw DebugX output of those steps")


class MemoryRangeIn(BaseModel):
    seg: str = Field(description="Segment, hex")
    off: str = Field(description="Offset, hex")
    len: int = Field(ge=1, le=ДИАПАЗОН_МАКС)


class MemoryIn(BaseModel):
    step: int = Field(ge=0, description="Step to dump the memory at")
    ranges: list[MemoryRangeIn] = Field(min_length=1, max_length=ДИАПАЗОНОВ_МАКС)


class ChatMessageOut(BaseModel):
    id: str
    role: Literal["user", "assistant"]
    text: str
    anchor: dict | None = None
    step: int | None = None
    run_no: int | None = None
    created_at: str | None = None


class ChatOut(BaseModel):
    messages: list[ChatMessageOut] = Field(default_factory=list)


class ChatIn(BaseModel):
    text: str = Field(min_length=1, max_length=СООБЩЕНИЕ_МАКС)
    anchor: dict | None = Field(
        default=None,
        description=("What the message is about: {kind: line, line} | "
                     "{kind: register, name} | {kind: flag, name} | "
                     "{kind: cell, seg, off} | {kind: doc, id} | {kind: run} | "
                     "{kind: text, window, text, line_from, line_to} — text is "
                     "the selected text as is, at most 4000 characters; "
                     "window is one of source, listing, output, debugx, build; "
                     "line_from/line_to are source lines or null"))
    step: int | None = Field(default=None, ge=0,
                             description="Step the trace cursor stands on")
    run_no: int | None = Field(default=None, ge=1,
                               description="Run to look at; the last one if null")
    endpoint: str = Field(
        default="", max_length=64,
        description="Model provider preset the answer is paid with")


# ── общее ────────────────────────────────────────────────────────────────────

def сейчас() -> str:
    return datetime.datetime.now(datetime.timezone.utc).replace(
        microsecond=0).isoformat().replace("+00:00", "Z")


def окружение_инструментов(tools: str = "", dosbox: str = "",
                           debugx: str = "") -> dict:
    """Окружение, по которому ядро ищет инструменты.

    Мапа, а не `os.environ`: обработчик задания живёт в процессе с вычищенным
    окружением, и настройки доезжают до него каналом, а не переменными.
    """
    env = {"PATH": os.environ.get("PATH", "")}
    for имя, значение in (("KORITSU_ASM_TOOLS", tools),
                          ("KORITSU_ASM_DOSBOX", dosbox),
                          ("KORITSU_ASM_DEBUGX", debugx)):
        if значение:
            env[имя] = значение
    return env


def окружение_настроек(settings) -> dict:
    return окружение_инструментов(settings.asm_tools, settings.asm_dosbox,
                                  settings.asm_debugx)


def инструменты(settings, *, where: str | None = None):
    """Инструменты ядра или `503 asm_unavailable`."""
    try:
        найдено = ассемблер.find_tools(окружение_настроек(settings))
    except Exception:                                        # noqa: BLE001
        беды.exception("ассемблер: поиск инструментов не удался")
        найдено = None
    if найдено is None:
        raise ApiError(ASM_UNAVAILABLE,
                       "Assembler tools are not installed on this server: "
                       "TASM, TLINK, DOSBox-X or DebugX is missing",
                       503, where=where)
    return найдено


def записи_программ(s, project_id: str) -> list:
    return list(s.scalars(
        select(ProjectRun)
        .where(ProjectRun.project_id == project_id, ProjectRun.module == МОДУЛЬ)
        .order_by(ProjectRun.created_at.asc(), ProjectRun.n.asc())))


def найти_программу(s, project_id: str, program_id: str, *,
                    where: str = "path.program_id"):
    """Запись программы или `404`. Чужая и несуществующая отвечают одинаково."""
    запись = s.get(ProjectRun, check_id(program_id, where=where))
    if (запись is None or запись.project_id != project_id
            or запись.module != МОДУЛЬ):
        raise ApiError(NOT_FOUND, "Program not found", 404, where=where)
    return запись


def программа(проект, s, program_id: str):
    """Запись программы и проект глазами её решения. → `(запись, вид)`.

    Каталог решения заводится, если его нет: программа могла приехать из
    выгрузки без каталога, и без него первая же запись исходника легла бы не
    туда.
    """
    запись = найти_программу(s, проект.id, program_id)
    return запись, открыть(проект).create_solution(запись.id)


def номер_прогона(значение, *, where: str = "path.run_no") -> int:
    try:
        номер = int(значение)
    except (TypeError, ValueError):
        номер = 0
    if номер < 1:
        raise ApiError(INVALID_VALUE, "Run number is an integer from 1", 400,
                       where=where)
    return номер


def прогон(вид, run_no, *, where: str = "path.run_no") -> int:
    номер = номер_прогона(run_no, where=where)
    if not ассемблер.run_exists(вид, номер):
        raise ApiError(NOT_FOUND, "Run not found", 404, where=where)
    return номер


def исходник_записи(вид) -> dict:
    return вид.state(ИСХОДНИК) or {}


def настройки_программы(вид) -> dict:
    """Настройки программы с умолчаниями для того, чего в записи нет."""
    запись = вид.state(НАСТРОЙКИ) or {}
    return {ключ: запись.get(ключ, умолчание) if not isinstance(умолчание, list)
            else list(запись.get(ключ) or умолчание)
            for ключ, умолчание in УМОЛЧАНИЯ.items()}


def проверить_флаги(флаги, *, where: str) -> list[str]:
    чистые = [str(ф).strip() for ф in флаги or ()]
    for ф in чистые:
        if not ФЛАГ.match(ф):
            raise ApiError(INVALID_VALUE,
                           f"Build flag {ф[:40]!r} is not of the form /x", 400,
                           where=where)
    return чистые


def диапазоны(значение, *, where: str) -> list[dict]:
    """Диапазоны дампа из тела или `payload` → чистые словари или `400`."""
    if not isinstance(значение, list) or not 1 <= len(значение) <= ДИАПАЗОНОВ_МАКС:
        raise ApiError(INVALID_VALUE,
                       f"ranges is a list of 1 to {ДИАПАЗОНОВ_МАКС} ranges", 400,
                       where=where)
    out = []
    for р in значение:
        р = р.model_dump() if hasattr(р, "model_dump") else р
        if not isinstance(р, dict):
            raise ApiError(INVALID_VALUE, "A range is {seg, off, len}", 400,
                           where=where)
        seg, off = str(р.get("seg") or ""), str(р.get("off") or "")
        длина = р.get("len")
        if (not ШЕСТНАДЦАТЕРИЧНОЕ.match(seg) or not ШЕСТНАДЦАТЕРИЧНОЕ.match(off)
                or not isinstance(длина, int) or isinstance(длина, bool)
                or not 1 <= длина <= ДИАПАЗОН_МАКС):
            raise ApiError(INVALID_VALUE,
                           f"A range is hex seg and off and len from 1 to "
                           f"{ДИАПАЗОН_МАКС}", 400, where=where)
        out.append({"seg": seg.upper(), "off": off.upper(), "len": длина})
    return out


def якорь(значение, *, where: str = "body.anchor") -> dict | None:
    """Якорь сообщения → чистый словарь по договору или `400`. `None` законен."""
    if значение is None:
        return None
    вид = значение.get("kind") if isinstance(значение, dict) else None
    поля = ЯКОРЯ.get(вид) if isinstance(вид, str) else None
    if поля is None:
        raise ApiError(INVALID_VALUE,
                       f"anchor.kind must be one of: {', '.join(ЯКОРЯ)}", 400,
                       where=where)
    if вид == "text":
        return якорь_текста(значение, where=where)
    out: dict = {"kind": вид}
    for имя, тип in поля.items():
        v = значение.get(имя)
        if тип is int:
            годится = isinstance(v, int) and not isinstance(v, bool) and v >= 1
        else:
            годится = isinstance(v, str) and 0 < len(v.strip()) <= 64
            v = v.strip() if годится else v
        if not годится:
            raise ApiError(INVALID_VALUE, f"anchor.{имя} is missing or malformed",
                           400, where=f"{where}.{имя}")
        out[имя] = v
    return out


def якорь_текста(значение: dict, *, where: str) -> dict:
    """Якорь выделенного текста → чистый словарь или `400`.

    Текст хранится ровно таким, каким его выделили, без обрезки пробелов:
    отступы в ассемблере и столбцы дампа — часть смысла. Строки — обе или ни
    одной: половина диапазона ничего не говорит.
    """
    окно = значение.get("window")
    if окно not in ОКНА_ТЕКСТА:
        raise ApiError(INVALID_VALUE,
                       f"anchor.window must be one of: {', '.join(ОКНА_ТЕКСТА)}",
                       400, where=f"{where}.window")
    текст = значение.get("text")
    if not isinstance(текст, str) or not текст.strip():
        raise ApiError(INVALID_VALUE, "anchor.text is the selected text", 400,
                       where=f"{where}.text")
    if len(текст) > ТЕКСТ_ЯКОРЯ_МАКС:
        raise ApiError(INVALID_VALUE,
                       f"anchor.text is longer than {ТЕКСТ_ЯКОРЯ_МАКС} characters",
                       400, where=f"{where}.text")
    строки: list[int | None] = []
    for имя in ("line_from", "line_to"):
        v = значение.get(имя)
        if v is not None and (not isinstance(v, int) or isinstance(v, bool)
                              or v < 1):
            raise ApiError(INVALID_VALUE,
                           f"anchor.{имя} is a line number from 1 or null", 400,
                           where=f"{where}.{имя}")
        строки.append(v)
    с, по = строки
    if (с is None) != (по is None) or (с is not None and по is not None and по < с):
        raise ApiError(INVALID_VALUE,
                       "anchor.line_from and anchor.line_to are both null or "
                       "a range of source lines", 400, where=f"{where}.line_to")
    return {"kind": "text", "window": окно, "text": текст,
            "line_from": с, "line_to": по}


def сводка_прогона(s, вид, run_no: int) -> dict:
    """Итог прогона с тома, а пока его нет — ход по заданию очереди."""
    снимок = ассемблер.read_request(вид, run_no)
    job_id = str(снимок.get("job_id") or "") or None
    итог = ассемблер.read_summary(вид, run_no)
    # Исходник, из которого собран прогон: номера строк в сообщениях, листинге
    # и трассе — от этого текста, и сайт по нему сдвигает их к нынешнему.
    исходник = снимок.get("source")
    исходник = исходник if isinstance(исходник, str) else None
    if итог is not None:
        return {**итог, "run_no": run_no, "job_id": job_id, "source": исходник}

    задание = s.get(Job, job_id) if job_id else None
    статус, беда, шагов = "crashed", None, 0
    if задание is None:
        if _недавно(снимок.get("at")):
            статус = "queued"
        else:
            беда = "прогон потерян: задания в очереди нет"
    elif задание.status == QUEUED:
        статус = "queued"
    elif задание.status == RUNNING:
        ход = задание.progress or {}
        if ход.get("note") == "trace":
            статус, шагов = "running", int(ход.get("step") or 0)
        else:
            статус = "building"
    elif задание.status == CANCELLED:
        беда = "прогон отменён"
    elif задание.status == FAILED:
        беда = str((задание.error or {}).get("message") or "прогон не удался")
    else:
        беда = "прогон кончился без итога"
    return {"run_no": run_no, "job_id": job_id, "status": статус,
            "source": исходник, "build": None, "load": None,
            "stdin": str(снимок.get("stdin") or ""),
            "step_limit": int(снимок.get("step_limit") or 0),
            "mode32": bool(снимок.get("mode32")),
            "totals": {"steps": шагов, "ms": 0, "exit_code": None},
            "truncated": None, "dumps": [], "error": беда}


def _недавно(момент) -> bool:
    try:
        когда = datetime.datetime.fromisoformat(str(момент).replace("Z", "+00:00"))
    except ValueError:
        return False
    return (datetime.datetime.now(datetime.timezone.utc) - когда
            ).total_seconds() < ЗАПИСЬ_В_ПУТИ_С


def карточка_программы(s, запись, вид) -> dict:
    """Программа в ленте: запись журнала плюс время исходника и последний статус."""
    последний = ассемблер.last_run_no(вид)
    статус = None
    if последний is not None:
        try:
            статус = сводка_прогона(s, вид, последний)["status"]
        except Exception:                                    # noqa: BLE001
            беды.exception("программа %s: прогон %s не читается",
                           запись.id, последний)
    return {"project_id": запись.project_id, "program_id": запись.id,
            "name": запись.name, "n": int(запись.n),
            "created_at": iso(запись.created_at),
            "updated_at": исходник_записи(вид).get("at") or iso(запись.created_at),
            "last_status": статус}


# ── инструменты и программы пространства ─────────────────────────────────────

@router.get("/asm/status", operation_id="asm_status", response_model=StatusOut,
            summary="Whether assembler tools are installed",
            description=(
                "Says whether this server can build and trace programs: "
                "DOSBox-X, TASM, TLINK and DebugX, each on its own. "
                "`available` false is a state, not an error: the module can be "
                "shown for development without the tools, and starting a run "
                "then answers 503 asm_unavailable. 401 unauthenticated."))
def состояние(request: Request, user: CurrentUser) -> dict:
    return ассемблер.tools_status(окружение_настроек(настройки(request)))


def работа_программ(s, settings, ws, user) -> Project:
    """Работа пространства, в которой живут программы. Нет — завести.

    Самая старая из подходящих — по той же причине, что у досок: две вкладки,
    заведшие первую программу разом, не должны разложить следующие по двум
    одноимённым работам.
    """
    p = s.scalars(
        select(Project)
        .where(Project.workspace_id == ws.id, Project.deleted_at.is_(None),
               Project.module == МОДУЛЬ, Project.name == ИМЯ_РАБОТЫ)
        .order_by(Project.created_at)).first()
    if p is not None:
        return p
    return завести_работу(s, settings, ws, user, name=ИМЯ_РАБОТЫ,
                          module=МОДУЛЬ, where="body.workspace_id")


@router.get("/asm/programs", operation_id="asm_programs",
            response_model=list[ProgramCardOut],
            summary="Assembler programs of a workspace",
            description=(
                "Every assembler program of one workspace, most recently "
                "edited first, with the status of its last run. Works in the "
                "trash are left out. Viewer role. 400 invalid_id, "
                "404 not_found, 422 validation_failed."))
def программы_пространства(request: Request, workspace_id: str, s: SessionDep,
                           user: CurrentUser) -> list[dict]:
    """Программы всех работ пространства одной лентой.

    Работа без каталога на томе пропускается со строкой в журнале: одна
    испорченная работа не должна унести с экрана все остальные программы.
    """
    settings = настройки(request)
    ws = require_role(s, user.id,
                      check_id(workspace_id, where="query.workspace_id"),
                      VIEWER, where="query.workspace_id")
    работы = s.scalars(
        select(Project)
        .where(Project.workspace_id == ws.id, Project.deleted_at.is_(None))
        .order_by(Project.created_at)).all()
    итог: list[dict] = []
    for p in работы:
        строки = записи_программ(s, p.id)
        if not строки:
            continue
        try:
            на_томе = открыть_работу(p, settings)
        except ApiError:
            беды.exception("работа %s: каталога нет, программы пропущены", p.id)
            continue
        for запись in строки:
            итог.append(карточка_программы(
                s, запись, на_томе.create_solution(запись.id)))
    итог.sort(key=lambda к: (к["updated_at"] or "", к["n"]), reverse=True)
    return итог


@router.post("/asm/programs", status_code=201,
             operation_id="asm_create_program",
             response_model=ProgramCreatedOut,
             summary="Start a new assembler program in a workspace",
             description=(
                 "Starts a program without naming a work: a journal entry and "
                 "its own directory on the volume, in the workspace assembler "
                 "work, created on the first program. The source starts empty "
                 "and nothing is built or charged here. Editor role in the "
                 "workspace. 400 invalid_id, 403 forbidden, 404 not_found, "
                 "409 project_exists."))
def завести_программу(тело: ProgramCreateIn, request: Request, s: SessionDep,
                      user: CurrentUser) -> dict:
    settings = настройки(request)
    ws = require_role(s, user.id,
                      check_id(тело.workspace_id, where="body.workspace_id"),
                      EDITOR, where="body.workspace_id")
    p = работа_программ(s, settings, ws, user)
    на_томе = открыть_работу(p, settings)
    запись = завести(s, p, user, module=МОДУЛЬ, name=тело.name)
    на_томе.create_solution(запись.id)
    return {"project_id": p.id, "program_id": запись.id, "name": запись.name,
            "n": int(запись.n)}


# ── программа ────────────────────────────────────────────────────────────────

ПУТЬ = "/projects/{project_id}/asm/programs/{program_id}"


@router.get(ПУТЬ, operation_id="asm_program", response_model=ProgramOut,
            summary="One assembler program",
            description=(
                "The source with its version counter, the run settings and the "
                "number of the last run. A program nobody has typed in yet has "
                "an empty source with version 0, which is not an error. Viewer "
                "role. 400 invalid_id, 404 not_found."))
def программа_целиком(program_id: str, проект: ЧитательПроекта,
                      s: SessionDep) -> dict:
    запись, вид = программа(проект, s, program_id)
    исходник = исходник_записи(вид)
    уставки = настройки_программы(вид)
    return {"project_id": проект.id, "program_id": запись.id,
            "name": запись.name, "n": int(запись.n),
            "source": str(исходник.get("source") or ""),
            "version": int(исходник.get("version") or 0),
            "at": исходник.get("at"), "settings": уставки,
            "breakpoints": уставки["breakpoints"], "watches": уставки["watches"],
            "last_run_no": ассемблер.last_run_no(вид)}


@router.put(ПУТЬ + "/source", operation_id="asm_put_source",
            response_model=SourceOut,
            responses={409: {"model": SourceConflictOut,
                             "description": ("The source was written from "
                                             "somewhere else; the current "
                                             "source comes with the refusal")}},
            summary="Write the source of a program",
            description=(
                "Replaces the source and bumps its version. `version` in the "
                "body is the one this edit is based on; if it is not the "
                "current one, the answer is 409 and carries the source that "
                "won. Runs already queued keep the source they were started "
                "with. Editor role. 400 invalid_id, 400 source_too_big, "
                "403 forbidden, 404 not_found, 409 source_conflict."))
def записать_исходник(program_id: str, тело: SourceIn, проект: РедакторПроекта,
                      s: SessionDep, user: CurrentUser):
    _, вид = программа(проект, s, program_id)
    if len(тело.source.encode("utf-8")) > ИСХОДНИК_МАКС:
        raise ApiError(SOURCE_TOO_BIG,
                       f"Source must be at most {ИСХОДНИК_МАКС} bytes", 400,
                       where="body.source")
    запись = исходник_записи(вид)
    текущая = int(запись.get("version") or 0)
    if int(тело.version) != текущая:
        беда = ApiError(SOURCE_CONFLICT,
                        f"The source has moved on to version {текущая}", 409,
                        where="body.version")
        return JSONResponse(status_code=409, content={
            **беда.to_dict(), "source": str(запись.get("source") or ""),
            "version": текущая})
    момент = сейчас()
    вид.put_state(ИСХОДНИК, {"source": тело.source, "version": текущая + 1,
                             "at": момент, "by": user.id})
    return {"version": текущая + 1, "at": момент}


@router.put(ПУТЬ + "/settings", operation_id="asm_put_settings",
            response_model=AsmSettingsModel,
            summary="Write the run settings of a program",
            description=(
                "Replaces the input, step limit, 16/32-bit mode, build flags, "
                "breakpoints and watches at once. A build flag is a slash and "
                "a short word (`/zi`); the step limit is capped by the server. "
                "Editor role. 400 invalid_id, 400 invalid_value, "
                "403 forbidden, 404 not_found."))
def записать_настройки(program_id: str, тело: AsmSettingsModel,
                       request: Request, проект: РедакторПроекта,
                       s: SessionDep) -> dict:
    _, вид = программа(проект, s, program_id)
    потолок = int(настройки(request).asm_step_limit_max)
    if тело.step_limit > потолок:
        raise ApiError(INVALID_VALUE,
                       f"step_limit must be at most {потолок}", 400,
                       where="body.step_limit")
    наблюдения = [н.strip() for н in тело.watches]
    if any(not н or len(н) > НАБЛЮДЕНИЕ_МАКС for н in наблюдения):
        raise ApiError(INVALID_VALUE,
                       f"A watch is 1 to {НАБЛЮДЕНИЕ_МАКС} characters", 400,
                       where="body.watches")
    уставки = {"stdin": тело.stdin, "step_limit": int(тело.step_limit),
               "mode32": bool(тело.mode32),
               "tasm_flags": проверить_флаги(тело.tasm_flags,
                                             where="body.tasm_flags"),
               "tlink_flags": проверить_флаги(тело.tlink_flags,
                                              where="body.tlink_flags"),
               "breakpoints": sorted({int(т) for т in тело.breakpoints if т >= 1}),
               "watches": наблюдения}
    вид.put_state(НАСТРОЙКИ, уставки)
    return уставки


@router.patch(ПУТЬ, operation_id="asm_rename_program", response_model=RenameOut,
              summary="Rename a program",
              description=(
                  "Renames the program. An empty name resets it: the interface "
                  "names it from the module and n again. Editor role. "
                  "400 invalid_id, 403 forbidden, 404 not_found."))
def переименовать(program_id: str, тело: RenameIn, проект: РедакторПроекта,
                  s: SessionDep) -> dict:
    запись = найти_программу(s, проект.id, program_id)
    запись.name = тело.name.strip()
    s.flush()
    return {"program_id": запись.id, "name": запись.name}


@router.delete(ПУТЬ, status_code=204, operation_id="asm_delete_program",
               summary="Delete a program",
               description=(
                   "Removes the program: its journal entry, source, settings, "
                   "conversation and every run with its trace. Editor role. "
                   "400 invalid_id, 403 forbidden, 404 not_found."),
               response_class=Response)
def снести(program_id: str, проект: РедакторПроекта, s: SessionDep) -> Response:
    запись = найти_программу(s, проект.id, program_id)
    на_томе = открыть(проект)
    for mid in на_томе.solution_materials(запись.id):
        на_томе.unbind_material(mid, запись.id)
    на_томе.drop_solution(запись.id)
    s.delete(запись)
    s.flush()
    return Response(status_code=204)


# ── прогоны ──────────────────────────────────────────────────────────────────

@router.post(ПУТЬ + "/runs", status_code=202, operation_id="asm_start_run",
             response_model=RunStartedOut,
             summary="Build, or build and trace, a program",
             description=(
                 "Takes the source and settings as they are now and queues an "
                 "`asm_run` job: `build` assembles and links, `run` also traces "
                 "the whole program up to the step limit. Progress stages are "
                 "`tasm`, `tlink` and `trace`. The run number answers at once; "
                 "its summary is read from GET …/runs/{run_no}. Editor role. "
                 "400 invalid_id, 402 limit_exhausted, 403 forbidden, "
                 "404 not_found, 503 asm_unavailable."))
def запустить(program_id: str, request: Request, проект: РедакторПроекта,
              s: SessionDep, user: CurrentUser,
              тело: RunIn | None = None) -> dict:
    settings = настройки(request)
    запись, вид = программа(проект, s, program_id)
    инструменты(settings)
    режим = тело.mode if тело is not None else "run"
    уставки = настройки_программы(вид)
    исходник = исходник_записи(вид)
    номер = ассемблер.claim_run(вид)
    try:
        задание = задания.enqueue(
            s, user, ASM_RUN,
            {"run_id": запись.id, "run_no": номер, "mode": режим},
            project_id=проект.id, settings=settings)
        ассемблер.write_request(вид, номер, {
            "mode": режим, "job_id": задание.id,
            "source": str(исходник.get("source") or ""),
            "source_version": int(исходник.get("version") or 0),
            "stdin": str(уставки["stdin"] or ""),
            "step_limit": min(int(уставки["step_limit"] or 1),
                              int(settings.asm_step_limit_max)),
            "mode32": bool(уставки["mode32"]),
            "tasm_flags": list(уставки["tasm_flags"]),
            "tlink_flags": list(уставки["tlink_flags"]),
            "at": сейчас(), "by": user.id})
    except Exception:
        ассемблер.drop_run(вид, номер)
        raise
    try:
        ассемблер.prune_runs(вид, ПРОГОНОВ_ХРАНИТСЯ, spare={номер})
    except OSError:
        беды.exception("программа %s: старые прогоны не убраны", запись.id)
    return {"job_id": задание.id, "run_no": номер}


@router.get(ПУТЬ + "/runs/{run_no}", operation_id="asm_run",
            response_model=RunSummaryOut,
            summary="Summary of one run",
            description=(
                "The run without its steps: build result with messages, "
                "listing, segments and symbols, load addresses, totals, "
                "truncation and memory dumps. While the job goes, `status` is "
                "queued, building or running and the rest is empty; a job "
                "cancelled or failed before a summary answers `crashed` with "
                "the reason in `error`. Viewer role. 400 invalid_id, "
                "400 invalid_value, 404 not_found."))
def сводка(program_id: str, run_no: int, проект: ЧитательПроекта,
           s: SessionDep) -> dict:
    _, вид = программа(проект, s, program_id)
    return сводка_прогона(s, вид, прогон(вид, run_no))


def _страница(from_: int, to: int | None, where: str) -> tuple[int, int]:
    конец = from_ + ШАГОВ_НА_СТРАНИЦЕ if to is None else to
    if конец < from_ or конец - from_ > ШАГОВ_НА_СТРАНИЦЕ:
        raise ApiError(INVALID_VALUE,
                       f"to must be from `from` to `from` + {ШАГОВ_НА_СТРАНИЦЕ}",
                       400, where=where)
    return from_, конец


@router.get(ПУТЬ + "/runs/{run_no}/steps", operation_id="asm_run_steps",
            response_model=StepsOut,
            summary="A page of trace steps",
            description=(
                "Steps with numbers in [from, to), at most 2000 at a time. "
                "Step 0 is the state before the first command; step i is the "
                "command executed and the state after it, with `next` the "
                "command to run after. `total` is how many steps the whole run "
                "executed; when the middle of a long trace is folded "
                "(`truncated`), steps from it are simply absent. Viewer role. "
                "400 invalid_id, 400 invalid_value, 404 not_found."))
def шаги(program_id: str, run_no: int, проект: ЧитательПроекта, s: SessionDep,
         from_: int = Query(0, alias="from", ge=0),
         to: int | None = Query(None, ge=0)) -> dict:
    _, вид = программа(проект, s, program_id)
    номер = прогон(вид, run_no)
    начало, конец = _страница(from_, to, "query.to")
    итог = сводка_прогона(s, вид, номер)
    return {"from": начало, "to": конец,
            "total": int((итог.get("totals") or {}).get("steps") or 0),
            "truncated": итог.get("truncated"),
            "steps": ассемблер.steps_page(вид, номер, начало, конец)}


@router.get(ПУТЬ + "/runs/{run_no}/debugx", operation_id="asm_run_debugx",
            response_model=DebugxOut,
            summary="Raw debugger output for a range of steps",
            description=(
                "What DebugX printed for steps [from, to), as text, at most "
                "2000 steps and two megabytes at a time. Viewer role. "
                "400 invalid_id, 400 invalid_value, 404 not_found."))
def сырой_вывод(program_id: str, run_no: int, проект: ЧитательПроекта,
                s: SessionDep, from_: int = Query(0, alias="from", ge=0),
                to: int | None = Query(None, ge=0)) -> dict:
    _, вид = программа(проект, s, program_id)
    номер = прогон(вид, run_no)
    начало, конец = _страница(from_, to, "query.to")
    return {"text": ассемблер.debugx_text(вид, номер, начало, конец)}


@router.post(ПУТЬ + "/runs/{run_no}/memory", status_code=202,
             operation_id="asm_run_memory", response_model=JobStartedOut,
             summary="Dump memory at a step of a run",
             description=(
                 "Queues an `asm_memory` job that replays the run with the same "
                 "source and input up to `step` and dumps the ranges asked for. "
                 "The job result carries `dumps`. For cells the trace did not "
                 "record after the first few thousand steps. Editor role. "
                 "400 invalid_id, 400 invalid_value, 402 limit_exhausted, "
                 "403 forbidden, 404 not_found, 409 run_not_ready, "
                 "503 asm_unavailable."))
def дамп(program_id: str, run_no: int, тело: MemoryIn, request: Request,
         проект: РедакторПроекта, s: SessionDep, user: CurrentUser) -> dict:
    settings = настройки(request)
    запись, вид = программа(проект, s, program_id)
    номер = прогон(вид, run_no)
    итог = ассемблер.read_summary(вид, номер) or {}
    if not (итог.get("build") or {}).get("ok"):
        raise ApiError(RUN_NOT_READY,
                       "This run has no built program to replay", 409,
                       where="path.run_no")
    инструменты(settings)
    задание = задания.enqueue(
        s, user, ASM_MEMORY,
        {"run_id": запись.id, "run_no": номер, "step": тело.step,
         "ranges": диапазоны(тело.ranges, where="body.ranges")},
        project_id=проект.id, settings=settings)
    return {"job_id": задание.id}


# ── переписка с агентом ─────────────────────────────────────────────────────

def сообщения_записи(вид) -> list[dict]:
    """Сообщения переписки в порядке записи; чужое в записи пропускается."""
    out: list[dict] = []
    for м in (вид.state(ЧАТ) or {}).get("messages") or ():
        if not isinstance(м, dict) or not str(м.get("text") or ""):
            continue
        out.append({"id": str(м.get("id") or ""),
                    "role": "assistant" if м.get("role") == "assistant" else "user",
                    "text": str(м["text"]),
                    "anchor": м.get("anchor") if isinstance(м.get("anchor"), dict) else None,
                    "step": м.get("step") if isinstance(м.get("step"), int) else None,
                    "run_no": м.get("run_no") if isinstance(м.get("run_no"), int) else None,
                    "created_at": м.get("created_at")})
    return out[-СООБЩЕНИЙ_МАКС:]


def дописать_переписку(вид, *новые: dict) -> None:
    было = сообщения_записи(вид)
    вид.put_state(ЧАТ, {"messages": (было + list(новые))[-СООБЩЕНИЙ_МАКС:]})


@router.get(ПУТЬ + "/chat", operation_id="asm_chat", response_model=ChatOut,
            summary="The conversation with the agent on a program",
            description=(
                "Every message exchanged with the agent on this program, oldest "
                "first. The question and the answer land here together when the "
                "`asm_chat` job is done. Viewer role. 400 invalid_id, "
                "404 not_found."))
def переписка(program_id: str, проект: ЧитательПроекта, s: SessionDep) -> dict:
    _, вид = программа(проект, s, program_id)
    return {"messages": сообщения_записи(вид)}


@router.post(ПУТЬ + "/chat", status_code=202, operation_id="asm_send_chat",
             response_model=JobStartedOut,
             summary="Ask the agent about a program",
             description=(
                 "Queues an `asm_chat` job: the agent answers in words, looking "
                 "at the source, the build messages and the trace of the run at "
                 "the step named, and at what the message is anchored to. "
                 "`endpoint` names the model provider preset that pays for it. "
                 "Editor role. 400 endpoint_required, 400 invalid_id, "
                 "400 invalid_value, 402 limit_exhausted, 403 forbidden, "
                 "404 not_found."))
def спросить(program_id: str, тело: ChatIn, request: Request,
             проект: РедакторПроекта, s: SessionDep, user: CurrentUser) -> dict:
    запись, вид = программа(проект, s, program_id)
    if not тело.endpoint.strip():
        raise ApiError(ENDPOINT_REQUIRED,
                       "endpoint must name a model provider preset", 400,
                       where="body.endpoint")
    if тело.run_no is not None:
        прогон(вид, тело.run_no, where="body.run_no")
    задание = задания.enqueue(
        s, user, ASM_CHAT,
        {"endpoint": тело.endpoint.strip(), "run_id": запись.id,
         "text": тело.text.strip(), "anchor": якорь(тело.anchor),
         "step": тело.step, "run_no": тело.run_no},
        project_id=проект.id, settings=настройки(request))
    return {"job_id": задание.id}


__all__ = ["router", "МОДУЛЬ", "ИСХОДНИК", "НАСТРОЙКИ", "ЧАТ", "ИМЯ_РАБОТЫ",
           "СООБЩЕНИЙ_МОДЕЛИ", "СООБЩЕНИЕ_МАКС", "ASM_UNAVAILABLE",
           "SOURCE_CONFLICT", "SOURCE_TOO_BIG", "RUN_NOT_READY", "INVALID_VALUE",
           "ENDPOINT_REQUIRED", "окружение_инструментов", "окружение_настроек",
           "инструменты", "номер_прогона", "диапазоны", "якорь", "якорь_текста",
           "сообщения_записи", "дописать_переписку", "сейчас"]
