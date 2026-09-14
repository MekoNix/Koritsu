"""
routes — доски: `/api/board` и `/api/projects/{id}/board`.

    GET    /api/board/session                      200  готово ли распознавание
    POST   /api/board/recognize                    200  строки записи → LaTeX
    GET    /api/board/boards?workspace_id=         200  доски всего пространства
    POST   /api/board/boards                       201  завести доску   (editor)
    GET    /api/projects/{id}/board/boards         200  доски этой работы
    POST   /api/projects/{id}/board/boards         201  завести доску   (editor)
    DELETE /api/projects/{id}/board/boards/{id}    204  снести доску    (editor)
    GET    /api/projects/{id}/board/scene?run=     200  сцена и её версия
    PUT    /api/projects/{id}/board/scene?run=     200  записать сцену  (editor)
    GET    /api/projects/{id}/board/steps?run=     200  строки решения
    PUT    /api/projects/{id}/board/steps?run=     200  записать строки  (editor)
    GET    /api/projects/{id}/board/task?run=      200  условие задачи текстом
    PUT    /api/projects/{id}/board/task?run=      200  записать условие (editor)

Распознавание живёт рядом (`ink.py`). Рабочий вход — пакетный
(`POST /api/board/recognize`): ему отдают целые строки записи, и потому строку
можно прочесть заново, когда её штрихи изменились. Живой сокет остался и висит
на своём пути: адрес его зашит в библиотеку распознавания и под `/api/board` не
переносится.

**Доска — это решение работы.** Одна доска — одна запись журнала запусков
(`module: "board"`) и каталог под ней, тот же носитель, что у «Решений» и
«Отчётов из задания». Своей таблицы доска не заводит: имя, номер, время и «кто
завёл» уже описаны журналом, а условие задачи, папка файлов и лента прогонов
достаются решению даром. Список досок работы — это записи журнала с
`module: "board"`, и второго списка нигде нет.

**Работы человек при этом не выбирает.** Доски живут в решении, но спрашивают
их по пространству: `GET /api/board/boards?workspace_id=` отдаёт все доски
пространства одной лентой, а `POST /api/board/boards` кладёт новую в **неявную
работу** — работу модуля `board` с именем «Доски», которая ищется в
пространстве и заводится, если её там ещё нет. Носитель от этого не меняется
ни на строку: меняется только то, кого спрашивают. Работа как понятие доске
ничего не даёт — материалы, потолок расхода и журнал у неё свои, — а выбор
работы перед первым росчерком стоил бы человеку экрана, на котором нечего
решать.

Лента пространства не отбирает работы по `projects.module`: решение живёт в
любой работе, и отбор означал бы, что доска видна или не видна в зависимости
от пункта сайдбара, под которым завели работу (то же правило, по которому
решения читаются маршрутами `…/kadai/*` в работе любого модуля).

Снос доски остался под работой (`DELETE /api/projects/{id}/board/boards/{id}`)
намеренно: карточка ленты несёт `project_id`, роль проверяется той же
зависимостью, что у остальных маршрутов доски, и второй адрес со своим разбором
доступа описывал бы то же самое второй раз.

**Рабочая сцена — запись состояния, а не материал.** Материал адресуется
содержимым, и холст, который сохраняется по паузе пера, плодил бы новый
идентификатор в описи работы на каждое движение — а опись целиком уезжает в
промпт карточками и оплачивается человеком. Поэтому сцена лежит записью
состояния решения (`Project.put_state`), которая заменяется целиком и версий не
ведёт: история правок холста не нужна никому, нужна история **проверок**, а она
в заданиях очереди.

Материалом становятся два производных, и оба — по нажатию: распознанное
(`<имя доски>.latex.md`, ровно один файл на доску) и снимок сцены для проверки
(артефакт, кладёт его прогон).

**`version` — счётчик оптимистической блокировки.** `PUT …/scene` с чужой
версией отвечает `409` и текущей сценой: две вкладки одной доски теряют правку
**шумно**, а не молча. Ответ несёт сцену целиком, чтобы вкладка, потерявшая
гонку, показала человеку то, что на доске сейчас, не переспрашивая вторым
запросом, — за время которого гонка повторилась бы.

**Распознанное перезаписывается, истории у него нет.** Правка — снять прежний
материал, убрать его из хранилища и положить новый одной операцией. Правда о
доске — сцена; распознанное пересобирается из неё в любой момент, а «история»
здесь означала бы новую строку в описи работы на каждое подтверждение формулы.

**`stale` — ответ на вопрос «распознанное отстало от доски?».** Если версия
сцены больше той, по которой собирались строки, экран показывает «доска
изменилась, распознать заново», а проверка на такой доске отказывается
(`board_check`), вместо того чтобы проверить вчерашний текст.

**Условие задачи — текст решения, а не материал.** Его набирает тот же человек,
что рисует доску, и уезжает оно отдельным недоверенным куском промпта. Файл
условия — обычный материал папки решения, это другая дорога.

**Проверка запускается только через очередь**: `POST /api/jobs` вида
`board_check`. Второй двери здесь нет намеренно — у вызова модели есть расход,
месячный потолок, отмена и журнал, и синхронный маршрут обошёл бы все четыре.

Ни строки разбора рукописи, ни одного пути на диске: всё, что про сцену, идёт
через `orchestrator`.

**Распознанное хранится рядом со сценой.** `PUT …/scene` несёт вторым полем
`recognized` — что страница уже прочла с этих штрихов, — и отдаёт его назад
слово в слово. Оно едет одной записью со сценой намеренно: кэш описывает ровно
эти штрихи, и запись его отдельно после первой же потерянной гонки объясняла бы
чужую доску.

Служба заглядывает в кэш в одном случае и в четыре поля (`box`, `elements`,
`latex`, `state`): когда строки решения отстали от доски, а кэш уже описывает
новые штрихи, — тогда строки собираются по нему на месте, без единого запроса к
распознаванию и без участия страницы. Всё остальное, что лежит в кэше, — вопрос
о рисунке, а рисунок дело страницы.

Коды отказа: `400 invalid_id` — форма идентификатора; `400 invalid_value` — в
теле нечего записать или строк в вызове распознавания больше потолка;
`400 scene_too_big` — сцена больше потолка; `403 forbidden` — роли мало;
`403 ink_no_keys` — у человека нет ключей распознавания; `404 not_found` — нет
проекта, спрашивающий не участник или нет такой доски; `409 scene_conflict` —
сцену переписали из другой вкладки; `422 steps_failed` — строки по этой сцене
не собираются; `429 rate_limited` — распознавание просят слишком часто;
`502 ink_unreachable` — распознавание не отвечает.
"""
from __future__ import annotations

import datetime
import json

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

import orchestrator

from ...db import SessionDep
from ...errors import ApiError, ErrorBody, NOT_FOUND
from ...ids import check_id
from ...jobs.models import DONE, Job
from ...jobs.registry import BOARD_CHECK
from ...log import беды
from ...materials.deps import CurrentUser, РедакторПроекта, ЧитательПроекта
from ...materials.service import открыть
from ...projects.models import NAME_MAX, Project, ProjectRun
from ...projects.routes import РЕШЕНИЕ, завести_работу, настройки
from ...projects.routes import открыть as открыть_работу
from ...projects.runs import завести
from ...workspaces.service import EDITOR, VIEWER, iso, require_role
from . import ink

router = APIRouter(tags=["board"])

# Модуль, записями которого журнал держит доски. Слово берётся у журнала, а не
# пишется здесь второй раз: разойтись им нельзя.
МОДУЛЬ = "board"

# Имена записей состояния решения. Две: рабочая сцена и то, что из неё
# распознали. Условие задачи своей записи не заводит — оно уже есть у решения
# (`Project.condition_text`), и второе место для той же строки разошлось бы с
# первым ровно тогда, когда человек её поправит.
СЦЕНА = "доска"
РАЗБОР = "доска-разбор"

# Переписка с репетитором: запись `{"messages": [{"role", "text", "at"}]}`.
# Роли две — `you` и `tutor`. Пишет её задание проверки, читает страница; на
# томе она затем, чтобы открытая заново доска показывала тот же разговор.
ЧАТ = "доска-чат"

# Сколько сообщений переписки хранится и сколько из них едет модели. Хранится
# больше, чем едет: человек листает свой разговор целиком, а модели для
# связности хватает последних реплик — остальное только дороже.
СООБЩЕНИЙ_МАКС = 200
СООБЩЕНИЙ_МОДЕЛИ = 20

# Как зовут неявную работу пространства, в которой заводятся доски. Имя, а не
# флаг в таблице работ: работа с таким именем — обычная работа, её видно в
# списке работ, её можно переименовать и снести, и ни один маршрут не начнёт
# отвечать иначе оттого, что она есть. Переименованная перестаёт быть неявной,
# и следующая доска заведёт себе новую — это правильнее, чем прятать за флагом
# работу, которую человек сознательно назвал по-своему.
ИМЯ_РАБОТЫ = "Доски"

# Потолок сцены на записи. Четыре мегабайта — тот же потолок, что у одного
# сообщения на мосту распознавания, и берётся он не с потолка: сцена целиком
# уезжает в запись состояния на каждое автосохранение, а картинок в ней нет
# вовсе (вставка изображения на доску выключена). Холст, переросший это число,
# — не доска, а чей-то импорт, и записывать его на том молча нельзя.
СЦЕНА_МАКС = 4 * 1024 * 1024

# Коды отказа этого модуля.
SCENE_TOO_BIG = "scene_too_big"
SCENE_CONFLICT = "scene_conflict"
STEPS_FAILED = "steps_failed"
INVALID_VALUE = "invalid_value"

# Потолки записи строк телом. Строк на доске — столько, сколько их бывает в
# решении школьной задачи с большим запасом; знаков в строке — столько, сколько
# помещается в формулу, а не в страницу текста; элементов в строке — столько,
# сколько росчерков бывает в одной записанной строке. Числа стоят здесь, чтобы
# тело запроса не могло вырасти в файл: оно ложится на том и уезжает модели.
СТРОК_НА_ДОСКЕ = 500
СТРОКА_МАКС = 4000
ЭЛЕМЕНТОВ_В_СТРОКЕ = 500

# Состояние строки в кэше распознанного → откуда взялся её LaTeX. Состояний
# два — строку прочитал распознаватель или набрал человек, — и слово это
# показывается человеку в списке строк, ничего собой не решая. Незнакомое
# состояние источника не имеет: выдумывать за страницу служба не вправе.
ИСТОЧНИК_СОСТОЯНИЯ = {"recognized": "myscript", "manual": "manual"}

# Потолок условия задачи текстом. Тот же, что у решений: условие — это
# страница-другая задания, а не методичка, и едет оно в промпт целиком.
TASK_MAX = 40000

# Расширение файла с распознанным. Ровно один такой файл на доску, перезапись
# без истории.
LATEX_SUFFIX = ".latex.md"

# Что написано про кэш распознанного в трёх формах сцены сразу. Одной строкой,
# а не тремя одинаковыми: разойтись им нельзя, а читают их в одном документе.
ОПИСАНИЕ_РАСПОЗНАННОГО = (
    "What has already been recognised off this scene, kept beside it and "
    "handed back untouched. It rides along with the scene so that reopening a "
    "board recognises nothing again — every line whose strokes have not changed "
    "is already answered here. Empty is normal: a board nobody has written on "
    "has nothing recognised. Keyed by line, an entry carries at least `box` "
    "(where the line stands on the scene), `elements` (the strokes it is drawn "
    "with), `latex` (what was read, empty when nothing was) and `state` "
    "(`recognized` or `manual`). Those four are what lets the service rebuild "
    "the lines of the solution by itself when the board has been drawn on "
    "since they were last written; everything else in an entry belongs to the "
    "page and is never looked at.")


# ── формы ────────────────────────────────────────────────────────────────────

class BoardIn(BaseModel):
    """Тело заведения доски. Поле одно: как её звать."""

    name: str = Field(
        default="", max_length=NAME_MAX,
        description=("What to call this board. Empty is fine: the interface "
                     "names it itself, from the module and n."))


class BoardOut(BaseModel):
    """Доска наружу: запись журнала плюс то, что видно на её карточке."""

    id: str = Field(description="Run id of this board: the value of ?run=")
    project_id: str
    name: str = Field(description="Empty means the interface names it itself")
    n: int = Field(description="Which board of this project, from 1")
    user_id: str | None = None
    created_at: str | None = None
    steps: int = Field(
        default=0,
        description="How many lines the last recognition read off this board")
    checked_at: str | None = Field(
        default=None,
        description="When a tutor last finished checking this board")


class WorkspaceBoardOut(BoardOut):
    """Карточка доски в ленте пространства: та же, плюс имя её работы.

    Имя работы стоит в карточке не для показа, а для поиска: экран доски
    работы не называет вовсе, но доску, заведённую внутри работы, человек
    помнит по этой работе, и ответ без имени заставил бы спрашивать список
    работ вторым запросом.
    """

    project_name: str = Field(
        default="", description="Name of the work this board is a solution of")


class WorkspaceBoardIn(BaseModel):
    """Тело заведения доски без работы: в каком пространстве и как звать."""

    workspace_id: str = Field(
        description=("Which workspace the board goes to. The work it lands in "
                     "is chosen by the service: a board is a solution, and "
                     "picking a work before the first stroke is a screen with "
                     "nothing to decide on it."))
    name: str = Field(
        default="", max_length=NAME_MAX,
        description=("What to call this board. Empty is fine: the interface "
                     "names it itself, from the module and n."))


class SceneOut(BaseModel):
    """Рабочая сцена доски, её версия и то, что с неё уже распознали."""

    scene: dict = Field(
        default_factory=dict,
        description=("The drawing itself, as the canvas stores it. Empty on a "
                     "board nobody has drawn on yet, which is not an error."))
    version: int = Field(
        default=0,
        description=("Version counter of the scene, from 1. Pass it back in "
                     "PUT: a stale one loses to whoever wrote first."))
    recognized: dict = Field(
        default_factory=dict,
        description=ОПИСАНИЕ_РАСПОЗНАННОГО)
    at: str | None = Field(default=None, description="When it was last written")


class SceneIn(BaseModel):
    """Тело записи сцены: сама сцена и версия, поверх которой пишут."""

    scene: dict = Field(
        description=("The drawing as the canvas gives it. Scroll, zoom and "
                     "selection do not belong here: they are a property of the "
                     "person looking, not of the board, and every movement of "
                     "the canvas would otherwise be a write to the volume."))
    version: int = Field(
        default=0,
        description=("The version this edit is based on: the one the last GET "
                     "or PUT answered. Zero means the board was empty. A "
                     "version that is not the current one answers 409 and "
                     "carries the current scene, so the edit is lost loudly."))
    recognized: dict = Field(
        default_factory=dict,
        description=ОПИСАНИЕ_РАСПОЗНАННОГО)


class SceneConflictOut(BaseModel):
    """Ответ `409`: та же форма отказа, и рядом с ней — сцена, которая победила.

    Форма отказа не меняется (`error` — то же тело `ErrorBody`: код, текст и
    место): меняется то, что к ней приложено. Без сцены вкладка, потерявшая
    гонку, пошла бы за нею вторым запросом — и за время этого запроса гонка
    повторилась бы.
    """

    error: ErrorBody
    scene: dict = Field(default_factory=dict)
    version: int = 0
    recognized: dict = Field(default_factory=dict)
    at: str | None = None


class StepOut(BaseModel):
    """Одна строка решения так, как её читает интерфейс."""

    n: int = Field(description="Reading order, from 1")
    id: str = Field(description="Short id of the line; the tutor names this")
    latex: str = Field(
        default="",
        description=("The line in LaTeX, without the dollar signs. Empty on a "
                     "line nobody has read: such a line stays in the list and "
                     "reaches the tutor as unavailable content."))
    source: str = Field(default="",
                        description="Where the LaTeX came from")
    confirmed: bool = Field(
        default=False,
        description=("Whether this line has content to show: true when its "
                     "LaTeX is not empty. There is no confirming step on the "
                     "board - the person sees what was read under their own "
                     "writing and corrects the strokes - so this answers "
                     "whether there is anything here for the tutor to see, and "
                     "nothing else."))
    elements: list[str] = Field(
        default_factory=list,
        description="Ids of the scene objects this line is drawn with")
    frame: str | None = Field(
        default=None,
        description=("Id of the frame this line belongs to, null when it "
                     "belongs to none. A frame is a caption over a group of "
                     "lines, not a step of the solution."))
    frame_name: str = Field(default="", description="What that frame is called")


class StepLineIn(BaseModel):
    """Одна строка решения так, как её прислала страница."""

    id: str = Field(
        max_length=NAME_MAX,
        description=("Short id of the line. The tutor names lines by it and "
                     "the page resolves a remark back into strokes by it, so "
                     "it has to be the same id on both roads."))
    latex: str = Field(
        default="", max_length=СТРОКА_МАКС,
        description=("The line in LaTeX, without the dollar signs. Empty on a "
                     "line that was not read. It is what decides whether the "
                     "line reaches the tutor: there is nothing else to show "
                     "and nothing else to ask."))
    elements: list[str] = Field(
        default_factory=list, max_length=ЭЛЕМЕНТОВ_В_СТРОКЕ,
        description="Ids of the scene objects this line is drawn with")
    confirmed: bool = Field(
        default=True,
        description=("Kept so that a page written against an older shape is "
                     "still understood; nothing is decided by it. There is no "
                     "confirming step on the board, and `latex` alone says "
                     "whether the line has content."))
    source: str = Field(
        default="", max_length=32,
        description=("Where the LaTeX came from, when the page knows: it is "
                     "shown beside the line and nothing is decided by it."))


class StepsIn(BaseModel):
    """Тело записи строк: готовые строки в порядке чтения."""

    lines: list[StepLineIn] = Field(
        default_factory=list, max_length=СТРОК_НА_ДОСКЕ,
        description=("The lines of the solution, top to bottom. Reading order "
                     "is the order of this list: which line stands above which "
                     "is a fact about the drawing, and the page is the one "
                     "looking at it."))


class StepsOut(BaseModel):
    """Строки решения и то, не отстали ли они от доски."""

    steps: list[StepOut] = Field(default_factory=list)
    scene_version: int = Field(
        default=0, description="Version of the scene these lines were read off")
    latex_material: str = Field(
        default="",
        description=("Id of the `<board>.latex.md` material of this solution, "
                     "the one the model sees along with the rest of the "
                     "context folder. Empty until the lines are first built."))
    unrecognized: int = Field(
        default=0,
        description=("How many lines nobody has read: lines with empty LaTeX. "
                     "Such a line stays in the list and reaches the tutor as "
                     "unavailable content: a verdict cannot be `correct` "
                     "while the board carries writing nobody has read."))
    stale: bool = Field(
        default=False,
        description=("True when the board has been drawn on since these lines "
                     "were read. A check refuses on a stale board rather than "
                     "checking yesterday's text."))
    at: str | None = Field(default=None, description="When they were read")


class TaskOut(BaseModel):
    """Условие задачи этой доски, словами."""

    text: str = Field(default="", description="The assignment in words")


class TaskIn(BaseModel):
    """Тело записи условия. Пустая строка стирает записанное."""

    text: str = Field(
        max_length=TASK_MAX,
        description=("The assignment in words. It travels to the tutor as a "
                     "separate untrusted part of the prompt: the person who "
                     "typed it is the person who drew the board."))


class ChatMessageOut(BaseModel):
    """Одно сообщение переписки с репетитором."""

    role: str = Field(description="`you` for the person, `tutor` for the agent")
    text: str = Field(description="The message; formulas as LaTeX between dollars")
    at: str | None = Field(default=None, description="When it was written")
    scene_version: int | None = Field(
        default=None,
        description="Scene version the person's message was sent with")


class ChatOut(BaseModel):
    """Переписка с репетитором целиком, старые сообщения первыми."""

    messages: list[ChatMessageOut] = Field(default_factory=list)


class SessionOut(BaseModel):
    """Готово ли распознавание рукописи и чем открывать сокет."""

    ready: bool = Field(
        description=("Whether handwriting recognition works for this person. "
                     "False is a state, not an error: the board still draws "
                     "and still lets a formula be typed."))
    reason: str = Field(
        default="",
        description="Why not, when it is not: `no_keys`. Empty when ready.")
    scheme: str = Field(
        default="",
        description="`wss` or `ws`, as seen from this request")
    host: str = Field(
        default="",
        description=("Host this request came to. The recognition library "
                     "builds the socket address out of it, so the page appends "
                     "its own base path before handing it over."))
    application_key: str = Field(
        default=ink.ПОДСТАВНОЙ_КЛЮЧ,
        description=("What to give the recognition library as its application "
                     "key. A constant, and deliberately not a key: the real "
                     "one never leaves the service, and the bridge substitutes "
                     "it on the way out."))
    hmac_key: str = Field(
        default=ink.ПОДСТАВНОЙ_КЛЮЧ,
        description=("What to give the library as its HMAC key. The same "
                     "constant, for the same reason: the bridge answers the "
                     "signature challenge itself."))
    requests_this_month: int = Field(
        default=0,
        description=("Recognition requests this month by this person: batch "
                     "calls plus sockets opened. The tariff counts requests, "
                     "not strokes, so this is the number to watch."))
    opens_this_month: int = Field(
        default=0,
        description=("Sockets opened this month, of those requests. The live "
                     "socket is the part a forgotten tab can keep spending on, "
                     "which is why it is also counted on its own."))


# ── общее ────────────────────────────────────────────────────────────────────

def записи_досок(s, project_id: str) -> list:
    """Записи журнала о досках этой работы, старые сверху."""
    return list(s.scalars(
        select(ProjectRun)
        .where(ProjectRun.project_id == project_id, ProjectRun.module == МОДУЛЬ)
        .order_by(ProjectRun.created_at.asc(), ProjectRun.n.asc())))


def найти_доску(s, project_id: str, run_id: str, *, where: str = "query.run"):
    """Запись доски или `404`. Чужая и несуществующая отвечают одинаково."""
    запись = s.get(ProjectRun, check_id(run_id, where=where))
    if (запись is None or запись.project_id != project_id
            or запись.module != МОДУЛЬ):
        raise ApiError(NOT_FOUND, "Board not found", 404, where=where)
    return запись


def доска(проект, s, run: str, *, where: str = "query.run"):
    """Проект глазами одной доски. `?run=` обязателен: доска — это решение.

    Обязателен, в отличие от решений: там пустой `run` означает работу, какой
    она была, пока решение в ней было одно, а доски такого прошлого не имеют
    вовсе — первая из них заведена уже в своём каталоге.
    """
    если = str(run or "").strip()
    if не_задано(если):
        raise ApiError(INVALID_VALUE, "Name the board with `run`", 400,
                       where=where)
    найти_доску(s, проект.id, если, where=where)
    return открыть(проект, solution=если)


def не_задано(значение: str) -> bool:
    return not str(значение or "").strip()


def сцена_записи(вид) -> dict:
    """Запись сцены с тома: `{scene, version, at, by}`. Пусто — не рисовали."""
    return вид.state(СЦЕНА) or {}


def разбор_записи(вид) -> dict:
    """Запись распознанного с тома. Пусто — строк ещё не собирали."""
    return вид.state(РАЗБОР) or {}


def сейчас() -> str:
    """Время записи в ISO 8601 с зоной. Одна дверь на модуль."""
    return datetime.datetime.now(datetime.timezone.utc).replace(
        microsecond=0).isoformat().replace("+00:00", "Z")


def _нераспознанных(шаги) -> int:
    """Сколько строк доски никто не прочёл: строк с пустым LaTeX.

    Подтверждения у строки нет: человек видит прочитанное прямо под своей
    записью и правит штрихи, пока оно не совпадёт с написанным. Значит и
    вопрос один — есть ли что показать репетитору, — и отвечает на него
    непустой `latex`.

    Считается в одном месте и потребляется двумя (запись разбора и ответ
    маршрута): два счёта одного и того же однажды дали бы два разных числа на
    одном экране.

    Непрочитанная строка из списка не исчезает — она и есть «здесь есть
    запись, которую я не вижу», и модель обязана узнать о ней, иначе доложит о
    пропущенном шаге.
    """
    return sum(1 for ш in шаги or () if not str(ш.get("latex") or "").strip())


def карточка_доски(запись, вид=None, проверено: str | None = None) -> dict:
    """Запись журнала плюс то, что видно на карточке доски.

    `steps` берётся из записи разбора, а не считается по сцене: пересборка
    строк — платная по времени работа над каждой доской списка, а число на
    карточке отвечает на вопрос «есть ли тут что показывать репетитору», и
    вчерашнего ответа для него достаточно.
    """
    разбор = разбор_записи(вид) if вид is not None else {}
    return {"id": запись.id, "project_id": запись.project_id,
            "name": запись.name, "n": int(запись.n), "user_id": запись.user_id,
            "created_at": iso(запись.created_at),
            "steps": len(разбор.get("steps") or ()),
            "checked_at": проверено}


def проверено_когда(s, project_id: str) -> dict[str, str]:
    """Когда каждую доску работы последний раз проверил репетитор.

    Одним запросом на весь список, а не по доске: досок в работе бывает
    десяток, и десять обходов таблицы заданий ради одной колонки времени стоят
    дороже, чем всё остальное в этом ответе вместе.

    Отбор по доске идёт в памяти, а не в `WHERE`: доска названа в `payload`,
    то есть внутри JSON, и запрос по нему был бы запросом, который SQLite
    исполняет перебором той же таблицы — только уже без индекса по проекту.
    """
    строки = s.scalars(
        select(Job)
        .where(Job.project_id == project_id, Job.kind == BOARD_CHECK,
               Job.status == DONE)
        .order_by(Job.finished_at.asc()))
    когда: dict[str, str] = {}
    for задание in строки:
        доска_ид = str((задание.payload or {}).get("run_id") or "")
        момент = iso(задание.finished_at)
        if доска_ид and момент:
            когда[доска_ид] = момент
    return когда


def свести_каталоги(на_томе, строки) -> None:
    """Каталог на каждую доску, у которой его на томе нет.

    Каталог заводится вместе с записью, но работа могла приехать из выгрузки
    или пережить беду на полпути: доска без каталога читалась бы как чужая, и
    вторая доска работы писала бы в её состояние.
    """
    свои = set(на_томе.solutions())
    for запись in строки:
        if запись.id not in свои:
            на_томе.create_solution(запись.id)


# ── доски пространства ───────────────────────────────────────────────────────

def работа_досок(s, settings, ws, user) -> Project:
    """Работа пространства, в которой живут доски. Нет — завести.

    Самая старая из подходящих, а не любая: два браузера, нажавшие «новая
    доска» разом, завели бы две одноимённые работы, и следующая доска обязана
    лечь в ту же, что и первая, а не в ту, которую вернул порядок строк.

    Каталог заводится общей дверью (`projects.routes.завести_работу`), а не
    вторым таким же кодом рядом: две дороги к созданию работы однажды разошлись
    бы, и одна из них оставила бы строку в базе без каталога на томе.
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


@router.get("/board/boards", operation_id="board_workspace_boards",
            response_model=list[WorkspaceBoardOut],
            summary="Boards of every project in a workspace",
            description=(
                "Every board of one workspace, newest first, each named "
                "together with the work it is a solution of. This is the list "
                "the board screen is made of: a board is opened and started "
                "without picking a work first. `workspace_id` is required: a "
                "list of everything the caller can reach would show the boards "
                "of one workspace while another one is open. Works in the "
                "trash are left out. Viewer role. 400 invalid_id, "
                "404 not_found, 422 validation_failed."))
def доски_пространства(request: Request, workspace_id: str, s: SessionDep,
                       user: CurrentUser) -> list[dict]:
    """Доски всех работ пространства одной лентой, новые сверху.

    Один запрос, а не по запросу на работу: экран досок показывает всё
    нарисованное человеком сразу, и собирать эту ленту на стороне клиента
    значило бы список работ плюс запрос на каждую из них — то есть ответ,
    время которого растёт вместе с числом работ.

    Работы корзины пропущены: их не показывает и список работ, а доска из
    корзины на общем экране означала бы предложение открыть удалённое.

    Работа, каталога которой на томе нет, пропускается со строкой в журнале, а
    не роняет весь ответ отказом: одна испорченная работа не должна унести с
    экрана доски всех остальных.
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
        строки = записи_досок(s, p.id)
        if not строки:
            # Каталог на томе не трогаем вовсе: у работы без досок ни читать,
            # ни чинить нечего.
            continue
        try:
            на_томе = открыть_работу(p, settings)
        except ApiError:
            беды.exception("работа %s: каталога нет, доски пропущены", p.id)
            continue
        свести_каталоги(на_томе, строки)
        проверено = проверено_когда(s, p.id)
        for запись in строки:
            итог.append({**карточка_доски(запись, на_томе.for_solution(запись.id),
                                          проверено.get(запись.id)),
                         "project_name": p.name})

    # Новые сверху: лента без выбора работы читается как «что я решал
    # последним», а не как история работы по порядку. Внутри одной секунды
    # порядок решает номер доски.
    итог.sort(key=lambda к: (к["created_at"] or "", int(к.get("n") or 0)),
              reverse=True)
    return итог


@router.post("/board/boards", status_code=201,
             operation_id="board_workspace_create",
             response_model=WorkspaceBoardOut,
             summary="Start a new board in a workspace",
             description=(
                 "Starts a board without naming a work: a journal entry and "
                 "its own directory on the volume, with its own assignment, "
                 "its own context folder and its own scene. The work it lands "
                 "in is the workspace board work, created on the first board "
                 "if it is not there yet. Nothing is drawn and nothing is "
                 "charged here. Editor role in the workspace. 400 invalid_id, "
                 "403 forbidden, 404 not_found, 409 project_exists."))
def завести_доску_в_пространстве(тело: WorkspaceBoardIn, request: Request,
                                 s: SessionDep, user: CurrentUser) -> dict:
    """Новая доска пространства: работа найдётся сама, запись и каталог — её.

    Роль спрашивается у пространства, а не у работы: работы человек не
    называл, и требовать роль в ней значило бы требовать роль в том, о чём он
    не знает. Роль редактора — та же, что нужна, чтобы завести работу руками.
    """
    settings = настройки(request)
    ws = require_role(s, user.id,
                      check_id(тело.workspace_id, where="body.workspace_id"),
                      EDITOR, where="body.workspace_id")
    p = работа_досок(s, settings, ws, user)
    на_томе = открыть_работу(p, settings)
    запись = завести(s, p, user, module=МОДУЛЬ, name=тело.name)
    на_томе.create_solution(запись.id)
    return {**карточка_доски(запись), "project_name": p.name}


# ── доски работы ─────────────────────────────────────────────────────────────

@router.get("/projects/{project_id}/board/boards",
            operation_id="board_boards", response_model=list[BoardOut],
            summary="Boards of this project",
            description=(
                "Every board of the project, oldest first: what it is called, "
                "which board of this project it is, how many lines the last "
                "recognition read off it and when a tutor last checked it. A "
                "board is one solution of the work: it carries its own "
                "assignment, its own context folder and its own run history, "
                "and its id is what the other routes take as `run`. Viewer "
                "role. 400 invalid_id, 404 not_found."))
def доски(проект: ЧитательПроекта, s: SessionDep) -> list[dict]:
    """Доски работы карточками. Пустой список — законное состояние новой работы."""
    на_томе = открыть(проект)
    строки = записи_досок(s, проект.id)
    свести_каталоги(на_томе, строки)
    проверено = проверено_когда(s, проект.id)
    return [карточка_доски(з, на_томе.for_solution(з.id), проверено.get(з.id))
            for з in строки]


@router.post("/projects/{project_id}/board/boards", status_code=201,
             operation_id="board_create", response_model=BoardOut,
             summary="Start a new board in this project",
             description=(
                 "Starts a board: a journal entry and its own directory on the "
                 "volume, with its own assignment, its own context folder and "
                 "its own scene. Nothing is drawn and nothing is charged here. "
                 "Editor role. 400 invalid_id, 403 forbidden, 404 not_found."))
def завести_доску(тело: BoardIn, проект: РедакторПроекта, s: SessionDep,
                  user: CurrentUser) -> dict:
    """Новая доска: запись журнала и каталог под её идентификатором.

    Каталог заводится сразу, а не при первом росчерке: без него «доска есть, но
    на ней не рисовали» и «доски нет» на диске неразличимы.
    """
    на_томе = открыть(проект)
    запись = завести(s, проект, user, module=МОДУЛЬ, name=тело.name)
    на_томе.create_solution(запись.id)
    return карточка_доски(запись)


@router.delete("/projects/{project_id}/board/boards/{run_id}", status_code=204,
               operation_id="board_delete",
               summary="Delete one board of this project",
               description=(
                   "Removes a board: its journal entry, its scene, the lines "
                   "read off it and its assignment. Its context files are "
                   "unbound from it; files attached to the project as a whole "
                   "are left alone, and so are artifacts: a snapshot is "
                   "addressed by its content and may still be what a finished "
                   "check refers to. Editor role. 400 invalid_id, "
                   "403 forbidden, 404 not_found."),
               response_class=Response)
def снести_доску(run_id: str, проект: РедакторПроекта,
                 s: SessionDep) -> Response:
    """Снести доску вместе с её каталогом и привязкой файлов контекста."""
    запись = найти_доску(s, проект.id, run_id, where="path.run_id")
    на_томе = открыть(проект)
    for mid in на_томе.solution_materials(запись.id):
        на_томе.unbind_material(mid, запись.id)
    на_томе.drop_solution(запись.id)
    s.delete(запись)
    s.flush()
    return Response(status_code=204)


# ── сцена ────────────────────────────────────────────────────────────────────

@router.get("/projects/{project_id}/board/scene", operation_id="board_scene",
            response_model=SceneOut,
            summary="The working scene of this board",
            description=(
                "The drawing as it was last written, and the version counter "
                "to pass back when writing. An empty scene with version 0 is "
                "the answer for a board nobody has drawn on yet, which is not "
                "an error: the page opens before the first stroke. Viewer "
                "role. 400 invalid_id, 400 invalid_value, 404 not_found."))
def сцена(проект: ЧитательПроекта, s: SessionDep, run: str = РЕШЕНИЕ) -> dict:
    """Рабочая сцена доски с тома вместе с кэшем распознанного."""
    запись = сцена_записи(доска(проект, s, run))
    return {"scene": dict(запись.get("scene") or {}),
            "version": int(запись.get("version") or 0),
            "recognized": dict(запись.get("recognized") or {}),
            "at": запись.get("at")}


@router.put("/projects/{project_id}/board/scene", operation_id="board_put_scene",
            response_model=SceneOut,
            responses={409: {"model": SceneConflictOut,
                             "description": ("The board was written from "
                                             "somewhere else; the current "
                                             "scene comes with the refusal")}},
            summary="Write the working scene of this board",
            description=(
                "Replaces the drawing and bumps its version. `version` in the "
                "body is the one this edit is based on; if it is not the "
                "current one, the answer is 409 and carries the scene that "
                "won, so two tabs of one board lose an edit loudly rather "
                "than silently. Editor role. 400 invalid_id, "
                "400 invalid_value, 400 scene_too_big, 403 forbidden, "
                "404 not_found, 409 scene_conflict."))
def записать_сцену(тело: SceneIn, проект: РедакторПроекта, s: SessionDep,
                   user: CurrentUser, run: str = РЕШЕНИЕ):
    """Записать сцену и кэш распознанного поверх названной версии.

    Чужая версия — `409` с тем, что на доске сейчас. Проверка потолка идёт до
    сравнения версий: сцена, которую всё равно не записать, не должна выигрывать
    гонку и объявлять себя текущей.

    Кэш распознанного едет одной записью со сценой намеренно: он описывает
    ровно эти штрихи, и разъехаться им нельзя — кэш, записанный отдельно, после
    первой же потерянной гонки объяснял бы чужую доску.
    """
    вид = доска(проект, s, run)
    размер = len(json.dumps(тело.scene, ensure_ascii=False).encode("utf-8"))
    if размер > СЦЕНА_МАКС:
        raise ApiError(SCENE_TOO_BIG,
                       f"Scene must be at most {СЦЕНА_МАКС} bytes of JSON",
                       400, where="body.scene")
    размер += len(json.dumps(тело.recognized,
                             ensure_ascii=False).encode("utf-8"))
    if размер > СЦЕНА_МАКС:
        raise ApiError(SCENE_TOO_BIG,
                       f"Scene and what was recognised off it must be at most "
                       f"{СЦЕНА_МАКС} bytes of JSON together", 400,
                       where="body.recognized")
    запись = сцена_записи(вид)
    текущая = int(запись.get("version") or 0)
    if int(тело.version) != текущая:
        беда = ApiError(SCENE_CONFLICT,
                        f"The board has moved on to version {текущая}", 409,
                        where="body.version")
        return JSONResponse(
            status_code=409,
            content={**беда.to_dict(),
                     "scene": dict(запись.get("scene") or {}),
                     "version": текущая,
                     "recognized": dict(запись.get("recognized") or {}),
                     "at": запись.get("at")})
    момент = сейчас()
    вид.put_state(СЦЕНА, {"scene": тело.scene, "version": текущая + 1,
                          "recognized": тело.recognized, "at": момент,
                          "by": user.id})
    return {"scene": тело.scene, "version": текущая + 1,
            "recognized": тело.recognized, "at": момент}


# ── строки решения ───────────────────────────────────────────────────────────

@router.get("/projects/{project_id}/board/steps", operation_id="board_steps",
            response_model=StepsOut,
            summary="Lines of the solution read off this board",
            description=(
                "The lines the last recognition read off this board, in "
                "reading order, and whether they have fallen behind the "
                "drawing. `stale` true means the board has been drawn on "
                "since; a check refuses on a stale board rather than checking "
                "yesterday's text. `latex_material` is the file of recognised "
                "lines that sits in the context folder of this board. Reading "
                "costs nothing: nothing is rebuilt here. Viewer role. "
                "400 invalid_id, 400 invalid_value, 404 not_found."))
def строки(проект: ЧитательПроекта, s: SessionDep, run: str = РЕШЕНИЕ) -> dict:
    """Распознанные строки с тома. Пусто — их ещё не собирали."""
    вид = доска(проект, s, run)
    разбор = разбор_записи(вид)
    шаги = list(разбор.get("steps") or ())
    собраны_по = int(разбор.get("scene_version") or 0)
    return {"steps": шаги,
            "scene_version": собраны_по,
            "latex_material": str(разбор.get("latex_material") or ""),
            "unrecognized": int(разбор.get("unrecognized") or 0),
            "stale": int(сцена_записи(вид).get("version") or 0) > собраны_по,
            "at": разбор.get("at")}


@router.put("/projects/{project_id}/board/steps",
            operation_id="board_read_steps", response_model=StepsOut,
            summary="Write the lines of this board",
            description=(
                "Writes the lines of the solution and rewrites the "
                "`<board>.latex.md` file of this board's context folder, so "
                "the tutor and the rest of the work see the same text. With a "
                "body, the lines are the ones given, in the order given: the "
                "page grouped the strokes into lines and had them recognised, "
                "and reading the scene a second time here would answer the "
                "same question differently. Without a body, they are built "
                "from what has already been recognised off the scene, and only "
                "when nothing has - read off the scene itself, which is the "
                "road for everything that has no page. The "
                "previous file is replaced, not kept beside it: the truth "
                "about a board is its scene, the lines are rebuilt from it at "
                "any moment, and a version per formula would grow "
                "the inventory of the work, which travels in every prompt. "
                "A line reaches the tutor when its LaTeX is not empty; a line "
                "nobody has read stays in the list and reaches the tutor as "
                "unavailable content. Editor role. 400 invalid_id, "
                "400 invalid_value, 403 forbidden, 404 not_found, "
                "422 steps_failed."))
def пересобрать_строки(проект: РедакторПроекта, s: SessionDep,
                       тело: StepsIn | None = None,
                       run: str = РЕШЕНИЕ) -> dict:
    """Записать строки решения и переписать файл распознанного.

    Два входа, и второй не замена первому. С телом строки берутся из него: их
    читает страница — она же и разложила штрихи по строкам и спросила
    распознавание, — и второй разбор той же сцены на стороне службы отвечал бы
    на тот же вопрос по-своему. Без тела служба собирает строки сама: сперва по
    тому, что с этой сцены уже прочитано (`recognized` записи сцены), и только
    на доске, с которой не прочитано ничего, — разбором самой сцены ядром. Это
    дорога для всего, у чего страницы нет, — внешнего ключа, выгрузки, проверки
    доски, приехавшей из чужой установки, — и она же дорога страницы, которая
    просит пересобрать строки, не пересказывая службе свой кэш.

    Порядок чтения в теле — порядок списка: какая строка выше какой, знает тот,
    кто смотрит на холст.
    """
    запись_доски = найти_доску(s, проект.id, run)
    вид = открыть(проект, solution=запись_доски.id)
    запись = сцена_записи(вид)
    if тело is not None:
        шаги = шаги_из_тела(тело.lines)
    else:
        шаги = (строки_из_распознанного(запись.get("recognized") or {})
                or _строки_по_сцене(запись.get("scene") or {}))
    return записать_строки(вид, запись_доски, шаги,
                           int(запись.get("version") or 0))


def _строки_по_сцене(сцена) -> list[dict]:
    """Сцена → строки решения разбором ядра. Второй ход записи без тела."""
    try:
        return orchestrator.board.steps(dict(сцена or {}))
    except Exception as беда:                                # noqa: BLE001
        # Ядро бросает своё, и ловить его по имени значило бы импортировать
        # `kokuban` — ровно то, чего служба не делает. Наружу уезжает код, а
        # подробности — в журнал службы.
        raise ApiError(STEPS_FAILED, "The lines of this board cannot be read",
                       422, where="query.run") from беда


def шаги_из_тела(строки) -> list[dict]:
    """Строки от страницы → шаги в форме, которую знает вся служба.

    Дописываются два поля, которых в теле нет и быть не может. `n` — порядок
    чтения: он и есть порядок списка, а числом его делает служба, чтобы
    нумерация в файле распознанного и в панели была одна. `frame` — кадр, в
    котором стоит строка; кадры читает ядро по сцене, и страница, которая
    прислала строки готовыми, о них ничего не говорит.

    `confirmed` тела не спрашивают: строку показывает репетитору её непустой
    `latex`, и пустой строке подтверждение содержимого не добавит. Поле у тела
    осталось ради страницы, написанной под прежнюю форму, и переписывается
    здесь тем, что о строке известно на самом деле.
    """
    out: list[dict] = []
    for с in строки or ():
        latex = str(с.latex or "").strip()
        out.append({"n": len(out) + 1, "id": с.id, "latex": latex,
                    "source": с.source, "confirmed": bool(latex),
                    "elements": list(с.elements),
                    "frame": None, "frame_name": ""})
    return out


def строки_из_распознанного(распознанное) -> list[dict]:
    """Кэш распознанного рядом со сценой → строки решения в порядке чтения.

    Единственное место, где служба читает кэш, и читает она четыре поля:
    `box` — где строка стоит на сцене, `elements` — из каких росчерков собрана,
    `latex` — что в ней прочитано, `state` — прочитал её распознаватель или
    набрал человек. Остальное в записи принадлежит странице.

    Зачем это службе, если строки присылает страница: доска, на которой
    дописали строку, иначе отказывала бы проверку до вызова модели, а кэш к
    этому времени уже описывает новые штрихи — значит строки собираются по нему
    на месте, без единого запроса к распознаванию и без участия человека.

    Порядок — сверху вниз, при равном верхе — слева направо: тот же порядок
    чтения, каким ядро читает сцену. Идентификатор строки — шесть hex от
    sha256 первого её росчерка, и такой же выдаст ядро, разбирая ту же сцену:
    ответ репетитора обязан разрешаться в объект холста, кто бы строки ни
    собрал.

    Потолки те же, что у тела запроса, и здесь они единственные: кэш пришёл из
    браузера записью сцены, а записью сцены его никто не разбирал.
    """
    отобранные: list[tuple] = []
    for ключ, запись in (распознанное or {}).items():
        if not isinstance(запись, dict):
            continue
        коробка = запись.get("box")
        коробка = коробка if isinstance(коробка, dict) else {}
        элементы = [э for э in (запись.get("elements") or ())
                    if isinstance(э, str) and э][:ЭЛЕМЕНТОВ_В_СТРОКЕ]
        отобранные.append((_число(коробка.get("y")), _число(коробка.get("x")),
                           str(ключ), запись, элементы))
    # Сортировка устойчива, и строки без `box` сохраняют порядок записи: доска
    # без координат — это не доска, но и терять на ней строки не за что.
    отобранные.sort(key=lambda с: (с[0], с[1]))

    выданные: dict = {}
    шаги: list[dict] = []
    for _верх, _левее, ключ, запись, элементы in отобранные[:СТРОК_НА_ДОСКЕ]:
        latex = запись.get("latex")
        latex = latex.strip()[:СТРОКА_МАКС] if isinstance(latex, str) else ""
        шаги.append({
            "n": len(шаги) + 1,
            "id": orchestrator.board.short_id(элементы[0] if элементы else ключ,
                                              выданные),
            "latex": latex,
            "source": ИСТОЧНИК_СОСТОЯНИЯ.get(str(запись.get("state") or ""), ""),
            "confirmed": bool(latex),
            "elements": элементы,
            "frame": None, "frame_name": ""})
    return шаги


def _число(значение) -> float:
    """Координата из кэша числом. Не число — ноль, как и у ядра."""
    return float(значение) if isinstance(значение, (int, float)) else 0.0


def записать_строки(вид, запись_доски, шаги: list, версия: int) -> dict:
    """Строки на том, файл распознанного заново. → тело ответа маршрута.

    Одна дверь на оба пути записи: строки от страницы и строки, собранные
    службой, ложатся одинаково — иначе проверка, пересобравшая их за человека,
    оставила бы файл контекста от прежней доски.
    """
    момент = сейчас()
    mid = _переписать_распознанное(вид, запись_доски, шаги, момент)
    не_разобрано = _нераспознанных(шаги)
    вид.put_state(РАЗБОР, {"steps": шаги, "latex_material": mid,
                           "scene_version": версия, "at": момент,
                           "unrecognized": не_разобрано})
    return {"steps": шаги, "scene_version": версия, "latex_material": mid,
            "unrecognized": не_разобрано, "stale": False, "at": момент}


def имя_файла(запись) -> str:
    """Как зовётся файл с распознанным этой доски.

    Имя доски, если человек его дал, — он выбрал его сам, и в папке решения из
    шести файлов оно единственное говорит, что внутри. Безымянная доска берёт
    свой номер: сочинять за интерфейс слово «Доска» служба не вправе — имена на
    экране пишет он и на своём языке.
    """
    основа = str(запись.name or "").strip() or f"board-{int(запись.n)}"
    return основа[:NAME_MAX - len(LATEX_SUFFIX)] + LATEX_SUFFIX


def _переписать_распознанное(вид, запись_доски, шаги, момент: str) -> str:
    """Заменить файл распознанного новым. → идентификатор материала.

    Снять привязку, убрать из хранилища, положить новый — одной операцией и в
    этом порядке: материал адресуется содержимым, и оставленный прежний висел
    бы в описи работы вторым ответом на тот же вопрос.

    Прежнего файла может не быть на томе вовсе (его унесли отдельным
    действием) — это не беда: просили состояние «в папке лежит нынешний файл»,
    и половина его уже наступила.
    """
    прежний = str(разбор_записи(вид).get("latex_material") or "")
    текст = orchestrator.board.latex_file(str(запись_доски.name or ""), шаги,
                                          момент)
    if прежний:
        вид.unbind_material(прежний, запись_доски.id)
        try:
            вид.store().remove(прежний)
        except Exception:                                    # noqa: BLE001
            pass
    материал = вид.add_material(текст.encode("utf-8"),
                                имя_файла(запись_доски), do_ocr=False)
    return str(материал.id)


# ── условие задачи ───────────────────────────────────────────────────────────

@router.get("/projects/{project_id}/board/task", operation_id="board_task",
            response_model=TaskOut,
            summary="The assignment this board is solving",
            description=(
                "The assignment of this board, in words. Empty is not an "
                "error: a board is allowed to be a scratch pad. It reaches the "
                "tutor as a separate untrusted part of the prompt, because the "
                "person who typed it is the person who drew the board. A file "
                "with the assignment is an ordinary material of this board's "
                "context folder, which is a different road. Viewer role. "
                "400 invalid_id, 400 invalid_value, 404 not_found."))
def условие(проект: ЧитательПроекта, s: SessionDep, run: str = РЕШЕНИЕ) -> dict:
    """Условие задачи этой доски с тома."""
    return {"text": доска(проект, s, run).condition_text() or ""}


@router.put("/projects/{project_id}/board/task",
            operation_id="board_set_task", response_model=TaskOut,
            summary="Write the assignment of this board",
            description=(
                "Writes the assignment in words. An empty string erases it. "
                "Writing the same text twice is the same state, which is why "
                "this is a PUT. Editor role. 400 invalid_id, "
                "400 invalid_value, 403 forbidden, 404 not_found."))
def записать_условие(тело: TaskIn, проект: РедакторПроекта, s: SessionDep,
                     run: str = РЕШЕНИЕ) -> dict:
    """Записать условие задачи текстом."""
    вид = доска(проект, s, run)
    вид.set_condition_text(тело.text)
    return {"text": вид.condition_text() or ""}


# ── переписка ───────────────────────────────────────────────────────────────

@router.get("/projects/{project_id}/board/chat", operation_id="board_chat",
            response_model=ChatOut,
            summary="The conversation with the tutor on this board",
            description=(
                "Every message exchanged with the tutor on this board, oldest "
                "first. A new message is sent by enqueueing a `board_check` "
                "job with `mode: \"chat\"` and `message`; the answer lands "
                "here when the job is done. Empty for a board nobody has "
                "talked on. Viewer role. 400 invalid_id, 400 invalid_value, "
                "404 not_found."))
def переписка(проект: ЧитательПроекта, s: SessionDep, run: str = РЕШЕНИЕ) -> dict:
    """Переписка с репетитором с тома."""
    return {"messages": сообщения_записи(доска(проект, s, run))}


def сообщения_записи(вид) -> list[dict]:
    """Сообщения переписки доски в порядке записи; чужое в записи пропускается."""
    запись = вид.state(ЧАТ) or {}
    out: list[dict] = []
    for м in (запись.get("messages") or ()):
        if not isinstance(м, dict):
            continue
        текст = str(м.get("text") or "")
        if not текст:
            continue
        версия = м.get("scene_version")
        out.append({"role": "tutor" if м.get("role") == "tutor" else "you",
                    "text": текст, "at": м.get("at"),
                    "scene_version": int(версия) if isinstance(версия, int) else None})
    return out[-СООБЩЕНИЙ_МАКС:]


def дописать_переписку(вид, *новые: dict) -> None:
    """Дописать сообщения в конец переписки, не длиннее потолка."""
    было = сообщения_записи(вид)
    вид.put_state(ЧАТ, {"messages": (было + list(новые))[-СООБЩЕНИЙ_МАКС:]})


# ── распознавание рукописи ───────────────────────────────────────────────────

@router.get("/board/session", operation_id="board_session",
            response_model=SessionOut,
            summary="Whether handwriting recognition is ready for you",
            description=(
                "Says whether this person's boards recognise handwriting, and "
                "what to hand the recognition library so it talks to the "
                "bridge instead of the cloud. `ready` false with reason "
                "`no_keys` is a state and not an error: the board draws, saves "
                "and lets a formula be typed without any key at all, and a "
                "check works the same on typed formulas. The keys in the "
                "answer are constants, never real ones: the real pair stays in "
                "the service and the bridge substitutes it. "
                "`requests_this_month` counts what the recognition tariff "
                "counts: batch calls plus sockets opened. 401 "
                "unauthenticated."))
def сессия(request: Request, s: SessionDep, user: CurrentUser) -> dict:
    """Готово ли распознавание у этого человека и чем открывать сокет.

    Ключи спрашиваются свои и только свои: общего ключа у распознавания не
    бывает (`keys.service.source_of` объясняет, почему), и ответ «готово» на
    чужой ключ обернулся бы закрытым сокетом через секунду после первого
    росчерка.
    """
    settings = request.app.state.settings
    есть = ink.ключи_есть(s, settings, user.id)
    схема, хост = ink.адрес_моста(request)
    return {"ready": есть, "reason": "" if есть else ink.НЕТ_КЛЮЧЕЙ,
            "scheme": схема, "host": хост,
            "application_key": ink.ПОДСТАВНОЙ_КЛЮЧ,
            "hmac_key": ink.ПОДСТАВНОЙ_КЛЮЧ,
            "requests_this_month": ink.расход_за_месяц(s, user.id),
            "opens_this_month": ink.открытий_за_месяц(s, user.id)}


class StrokeIn(BaseModel):
    """Один росчерк: где вело перо и когда."""

    x: list[float] = Field(
        description="Horizontal coordinates of the points, in canvas pixels")
    y: list[float] = Field(
        description="Vertical coordinates, the same length as `x`")
    t: list[float] | None = Field(
        default=None,
        description=("Milliseconds of each point, the same length as `x`. May "
                     "be left out; timing sharpens recognition but is not "
                     "required by it."))


class RecognizeLineIn(BaseModel):
    """Одна строка записи, как её собрала страница: имя и все её росчерки."""

    id: str = Field(
        max_length=NAME_MAX,
        description=("How the page calls this line. It is handed back "
                     "untouched, so the answer needs no matching up by order."))
    strokes: list[StrokeIn] = Field(
        default_factory=list,
        description="Every stroke of this line, in the order they were drawn")


class RecognizeIn(BaseModel):
    """Тело распознавания: строки записи и разрешение, в котором они мерены."""

    lines: list[RecognizeLineIn] = Field(
        default_factory=list,
        description=("The lines to read, at most eight. A line is sent when "
                     "its strokes have changed and not otherwise: recognition "
                     "of a line depends on nothing but that line, so the answer "
                     "to an unchanged one is already known."))
    dpi: int = Field(
        default=ink.DPI, ge=1, le=4000,
        description=("Resolution the coordinates are in. The service answers "
                     "in millimetres, and this is what turns them back into "
                     "the numbers that were sent."))


class RecognizedLineOut(BaseModel):
    """Одна распознанная строка: что прочли и что помешало."""

    id: str = Field(description="The id this line was sent under")
    latex: str = Field(
        default="",
        description=("The line in LaTeX, without the dollar signs. Empty when "
                     "nothing was read off it."))
    text: str = Field(
        default="",
        description=("The service's own one-line signature of what it read, "
                     "when it gave one. A fallback for showing the line to a "
                     "person: it is prose, not LaTeX, and nothing is built out "
                     "of it. Empty when the call carried more than one line, "
                     "because the signature then describes them all at once."))
    jiix: dict | None = Field(
        default=None,
        description=("The service's own answer for this line, whole. It "
                     "carries the bounding box of every expression and the "
                     "strokes behind it, which is what a line has to be split "
                     "by when the person wrote two formulas in one go. Null "
                     "when nothing was read."))
    error: str | None = Field(
        default=None,
        description=("Why this line was not read, in the words of whoever "
                     "refused. A line that failed does not fail the call: the "
                     "board keeps working, and the trouble is shown where it "
                     "happened."))


class UnmatchedOut(BaseModel):
    """Выражение, не легшее ни на одну присланную строку."""

    latex: str = Field(default="", description="The expression in LaTeX")
    jiix: dict = Field(
        default_factory=dict,
        description="The expression as the service returned it")


class RecognizeOut(BaseModel):
    """Ответ распознавания: строки, цена вызова и то, что не легло никуда."""

    lines: list[RecognizedLineOut] = Field(
        default_factory=list,
        description="One answer per line sent, in the order they were sent")
    requests: int = Field(
        default=0,
        description=("How many requests this call cost. One, normally: all the "
                     "lines travel in a single request, because the tariff "
                     "counts requests. Zero means nothing was sent at all."))
    unmatched: list[UnmatchedOut] = Field(
        default_factory=list,
        description=("What was read but belongs to none of the lines sent. It "
                     "is handed over rather than dropped: silently losing it "
                     "would read on screen as a line that recognised empty."))


@router.post("/board/recognize", operation_id="board_recognize",
             response_model=RecognizeOut,
             summary="Read handwritten lines off a board",
             description=(
                 "Reads lines of handwriting into LaTeX with this person's own "
                 "recognition keys. A line is a group of strokes as the page "
                 "sees them on the canvas, and the answer depends on nothing "
                 "but that line: a line whose strokes changed can be read "
                 "again, and one that did not change need not be sent at all. "
                 "All the lines of a call travel in a single request, because "
                 "the recognition tariff counts requests. At most eight lines "
                 "a call, at most two thousand points a line, at most twenty "
                 "requests a minute. A line the service refuses carries the "
                 "refusal in its own `error` and does not fail the call; only "
                 "an unreachable service refuses the whole call. No key of any "
                 "kind leaves the service, here or anywhere. 400 invalid_value, "
                 "401 unauthenticated, 403 ink_no_keys, 422 validation_failed, "
                 "429 rate_limited, 502 ink_unreachable."))
def распознать_строки(тело: RecognizeIn, request: Request, s: SessionDep,
                      user: CurrentUser) -> dict:
    """Строки записи → LaTeX. Ключи свои, наружу не уезжают.

    Обычной, а не асинхронной функцией — по той же причине, что и проброс
    версии: так её исполняет отдельный поток, а запрос наружу идёт тем же
    клиентом, каким служба ходит в сеть везде, и тем же, который в проверках
    перекрыт, чтобы ни одна из них не ушла в интернет.

    Работы в запросе нет: доска — это решение работы, но распознавание не
    касается ни доски, ни работы вовсе. Ему дают штрихи и ключи человека, и
    требовать роль в работе значило бы спрашивать про то, что на ответ не
    влияет.
    """
    from ...accounts.service import client_ip                # noqa: PLC0415

    settings = настройки(request)
    return ink.распознать(s, request.app.state.db, settings, user.id,
                          [с.model_dump() for с in тело.lines], int(тело.dpi),
                          ip=client_ip(request, settings))


# Мост распознавания висит на своём пути (`/api/v4.0/iink/…`): адрес сокета
# зашит в библиотеку распознавания и под `/api/board` не переносится. Маршруты
# его вешаются на этот же роутер, чтобы модуль оставался одной строкой в
# реестре.
ink.подключить(router)


__all__ = ["router", "МОДУЛЬ", "СЦЕНА", "РАЗБОР", "СЦЕНА_МАКС", "TASK_MAX",
           "LATEX_SUFFIX", "SCENE_TOO_BIG", "SCENE_CONFLICT", "STEPS_FAILED",
           "INVALID_VALUE", "СТРОК_НА_ДОСКЕ", "СТРОКА_МАКС",
           "ЭЛЕМЕНТОВ_В_СТРОКЕ", "ОПИСАНИЕ_РАСПОЗНАННОГО",
           "ИСТОЧНИК_СОСТОЯНИЯ",
           "записи_досок", "найти_доску", "доска", "сцена_записи",
           "разбор_записи", "карточка_доски", "имя_файла", "шаги_из_тела",
           "строки_из_распознанного", "записать_строки"]
