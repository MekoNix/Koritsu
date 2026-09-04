"""
diagrams — общее для двух модулей схем: исходники, подпроцесс, артефакт, отказы.

Модуля два (`flowcharts` и `uml`), а работа под ними одна и та же: взять
исходник (текстом из тела или материалом проекта), проверить потолок, позвать
`orchestrator.diagrams` **в подпроцессе**, положить XML артефактом и перевести
отказ строителя в отказ службы. Разложить это по двум модулям значило бы завести
два потолка, два перевода кодов и две мерки «слишком большой исходник» — а
разошлись бы они на первом же изменении настройки.

**Почему подпроцесс, если код не выполняется.** Он и правда не выполняется:
`fragmos` и `uml_generator` разбирают исходник tree-sitter'ом. Подпроцесс здесь
не про исполнение, а про два потолка, которых в общем процессе не поставить:
время (разбор мегабайта склеенного кода упирается во время, а не в
правильность) и память (tree-sitter на патологическом входе растёт быстро, а
`RLIMIT_AS` в общем процессе ограничил бы сайт). Механизм — общий,
`api/subproc.py`, тот же, что у разбора материалов.

**Правило разреза соблюдается ровно здесь.** Служба зовёт `orchestrator`, а
`fragmos` и `uml_generator` не называет ни одной строкой — ни тут, ни в дитяти
(`ДИТЯ` зовёт `orchestrator.diagrams`). Проверяется это, а не обещается:
`tests/kyotsu/test_border.py` и `tests/api/test_modules.py`.

    Коды отказа этих двух модулей

    400 invalid_source   тела нет, оно пустое, или названы сразу source и
                         material_id (одно из двух, а не оба)
    400 unknown_lang     язык не из `orchestrator.diagrams.languages()`
    400 unknown_mode     режим не из `GET /api/flowcharts/modes`
    400 unknown_theme    тема не из `GET /api/uml/themes`
    413 source_too_large исходник длиннее `settings.file_max_bytes`
    429 rate_limited     больше `KORITSU_PREVIEW_PER_MINUTE` предпросмотров
                         в минуту одним человеком
    422 diagram_failed   строитель отказался: не разобралось, не нашлось ни
                         одного класса, ни одного экземпляра, подпроцесс не
                         уложился в лимиты

**`422` не рассказывает почему подробнее постоянного текста.** Настоящая причина
— текст исключения tree-sitter'а, а в нём бывает кусок разбираемого кода: чужой
код в чужом ответе. Причина уходит в журнал бед вместе с меткой запроса, как у
`parse_failed` в материалах, и там её видит тот, кому это можно.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import NoReturn

import materials as _materials
import orchestrator
from fastapi import Request
from kyotsu import Notice

from ..errors import ApiError, INVALID_ID, NOT_FOUND
from ..log import беды
from ..materials.deps import Проект
from ..materials.service import ДЛИНА_ИД, ИД_RE, открыть, хранилище
from ..settings import Settings
from ..subproc import ПодпроцессНеУдался, выполнить

INVALID_SOURCE = "invalid_source"
RATE_LIMITED = "rate_limited"
UNKNOWN_LANG = "unknown_lang"
UNKNOWN_MODE = "unknown_mode"
UNKNOWN_THEME = "unknown_theme"
SOURCE_TOO_LARGE = "source_too_large"
DIAGRAM_FAILED = "diagram_failed"

# Постоянный текст `422`. Один на все причины намеренно: причины различает
# журнал, а клиенту разница между «не разобралось» и «не нашлось классов» уже
# сказана — он прислал код, код не годится.
DIAGRAM_FAILED_MESSAGE = "The diagram could not be built from this source"

# Какие отказы строителя — наша беда входа (400), а какие — беда исходника (422).
# Таблица здесь, а не по маршрутам: кодов у строителя шесть, маршрутов семь, и
# перечислять их у каждого значило бы семь раз ошибиться.
_КОДЫ_400 = {
    orchestrator.diagrams.UNKNOWN_LANG: UNKNOWN_LANG,
    orchestrator.diagrams.UNKNOWN_MODE: UNKNOWN_MODE,
    orchestrator.diagrams.UNKNOWN_THEME: UNKNOWN_THEME,
    orchestrator.diagrams.INVALID_SOURCE: INVALID_SOURCE,
}

# Виды работы, которые умеет дитя. Строкой в задании, а не тремя дитятями: тело
# у них одно и то же, и три копии `ПРОЛОГ`а разошлись бы на первой правке.
FLOWCHART = "flowchart"
CLASSES = "classes"
OBJECTS = "objects"


class СхемаНеПостроилась(ПодпроцессНеУдался):
    """Дитя со схемой упало, было убито или не уложилось в лимиты.

    Свой тип, а не общий: ловят его здесь, а `РазборНеУдался` материалов ловят у
    себя, и один тип на двоих означал бы, что беда разбора материала чинится
    кодом схемы.
    """


@dataclass(frozen=True)
class Схема:
    """Построенная схема: XML, замечания словарями и что на ней нарисовано.

    Замечания уже словарями (`Notice.to_dict`), а не объектами: они приехали из
    подпроцесса разобранным JSON и уедут клиенту тем же JSON, и собирать из них
    объект посередине незачем — форма от этого не изменится.
    """

    xml: str
    notices: list[dict]
    items: list[str]


# Что делает дитя. Зовёт **фасад оркестратора**, а не строителей схем: правило
# разреза действует и здесь, хотя это отдельный процесс, — иначе первый же
# читающий решит, что в подпроцессе можно всё.
ДИТЯ = r"""
from orchestrator import diagrams

вид = задание["вид"]
try:
    if вид == "flowchart":
        готово = diagrams.flowchart(задание["source"], задание["lang"],
                                    mode=задание["mode"])
    elif вид == "classes":
        готово = diagrams.class_diagram(задание["sources"], задание["lang"],
                                        theme=задание["theme"])
    else:
        готово = diagrams.object_diagram(задание["sources"], задание["lang"],
                                         theme=задание["theme"])
except diagrams.DiagramError as беда:
    ответ({"error": беда.code, "message": беда.message,
           "cause": беда.cause is not None,
           "notices": [n.to_dict() for n in беда.notices]})
else:
    ответ({"xml": готово.xml, "items": list(готово.items),
           "notices": [n.to_dict() for n in готово.notices]})
"""


# ── проверки входа: до подпроцесса и до тома ─────────────────────────────────

def проверить_язык(значение: str) -> str:
    """Язык из перечня фасада или `400 unknown_lang`. Перечня своего здесь нет."""
    try:
        return orchestrator.diagrams.lang(значение)
    except orchestrator.diagrams.DiagramError as беда:
        raise ApiError(UNKNOWN_LANG, беда.message, 400, where="body.lang") from None


def проверить_режим(значение: str) -> str:
    """Режим отрисовки блок-схемы или `400 unknown_mode`. Своего списка нет.

    Спрашивается у фасада (`orchestrator.diagrams.mode`), как и язык, а не
    сверяется со своим перечнем: у режима есть псевдоним (`loopLimit` — прежнее
    имя ГОСТ-режима, §12), и второе место, знающее про него, разошлось бы с
    первым. Наружу возвращается приведённое имя — то самое, которое человек
    видит в `GET /api/flowcharts/modes`.
    """
    try:
        return orchestrator.diagrams.mode(значение)
    except orchestrator.diagrams.DiagramError as беда:
        raise ApiError(UNKNOWN_MODE, беда.message, 400,
                       where="body.mode") from None


def проверить_тему(значение: str) -> str:
    """Палитра диаграммы UML или `400 unknown_theme`."""
    известные = orchestrator.diagrams.uml_themes()
    имя = str(значение or "dark")
    if имя not in известные:
        raise ApiError(UNKNOWN_THEME, f"theme must be one of {', '.join(известные)}",
                       400, where="body.theme")
    return имя


def проверить_размер(исходники: list[tuple[str, str]], settings: Settings,
                     *, where: str) -> None:
    """Потолок исходника — тот же `file_max_bytes`, что у загрузки файла.

    Тот же, а не свой: с точки зрения человека это одно и то же — «сколько
    текста служба берёт за раз», — и два числа он различал бы только по коду
    отказа. Меряется в байтах UTF-8, а не в знаках: потолок настроен в байтах, и
    мерить его знаками значило бы пускать вдвое больше кириллицы.
    """
    всего = sum(len(код.encode("utf-8")) for _, код in исходники)
    if всего > settings.file_max_bytes:
        raise ApiError(SOURCE_TOO_LARGE,
                       f"Source exceeds the {settings.file_max_bytes} byte limit",
                       413, where=where)


def исходник_материала(проект: Проект, material_id: str) -> tuple[str, str]:
    """Материал проекта как исходник: `(имя, текст)`.

    Форма идентификатора проверяется до похода на том — тем же выражением, что у
    маршрутов материалов: `Store` складывает из идентификатора путь, и `..`
    обязан умереть на входе, а не внутри.

    Не текстовый материал — `400 invalid_source`, а не `422`: схему строят по
    исходнику, и «вы прислали картинку» — беда запроса, а не кода.
    """
    if not ИД_RE.match(str(material_id or "")):
        raise ApiError(INVALID_ID,
                       f"Material id must be {ДЛИНА_ИД} hex characters", 400,
                       where="body.material_id")
    склад = хранилище(проект)
    try:
        материал = склад.get(material_id)
    except _materials.MaterialsError:
        raise ApiError(NOT_FOUND, "Material not found", 404,
                       where="body.material_id") from None
    if материал.kind != _materials.KIND_TEXT:
        raise ApiError(INVALID_SOURCE,
                       "This material is not source code", 400,
                       where="body.material_id") from None
    return материал.name, склад.read(material_id).text


def один_исходник(проект: Проект | None, source: str | None,
                  material_id: str | None) -> tuple[str, str]:
    """Ровно одно из двух: текст в теле или материал проекта. → `(имя, текст)`.

    «Ровно одно», а не «что-нибудь из двух»: прислав оба, человек не узнал бы,
    какой из них попал на схему, — а узнал бы это по картинке, то есть поздно.

    `проект=None` — предпросмотр: проекта нет, материалов нет, остаётся текст.
    Отдельной функции для него не завели намеренно: правило «ровно одно из
    двух» и мерка пустого исходника у обоих маршрутов одни.
    """
    названо = [n for n, v in (("source", source), ("material_id", material_id))
               if v is not None]
    if len(названо) != 1:
        raise ApiError(INVALID_SOURCE,
                       "Give exactly one of source and material_id", 400,
                       where="body.source")
    if material_id is not None:
        if проект is None:
            raise ApiError(INVALID_SOURCE,
                           "Material ids need a project; send source instead",
                           400, where="body.material_id")
        return исходник_материала(проект, material_id)
    if not str(source or "").strip():
        raise ApiError(INVALID_SOURCE, "Source code is empty", 400,
                       where="body.source")
    return "source", str(source)


def несколько_исходников(проект: Проект | None, sources) -> list[tuple[str, str]]:
    """Список исходников: идентификаторы материалов или пары `{name, source}`.

    Смешивать можно: человек присылает три файла проекта и один набросок, и
    запрещать это значило бы заставить его сначала загрузить набросок
    материалом. Пустой список — `400 invalid_source`: строить не из чего.
    """
    готово: list[tuple[str, str]] = []
    for n, кусок in enumerate(sources or ()):
        где = f"body.sources.{n}"
        if isinstance(кусок, str):
            if проект is None:
                raise ApiError(INVALID_SOURCE,
                               "Material ids need a project; send name and source",
                               400, where=где)
            готово.append(исходник_материала(проект, кусок))
            continue
        имя = str(getattr(кусок, "name", "") or "")
        текст = str(getattr(кусок, "source", "") or "")
        if not текст.strip():
            raise ApiError(INVALID_SOURCE, "Source code is empty", 400, where=где)
        готово.append((имя or f"source{n + 1}", текст))
    if not готово:
        raise ApiError(INVALID_SOURCE, "No sources given", 400,
                       where="body.sources")
    return готово


# ── темп предпросмотра ───────────────────────────────────────────────────────

# Приставка ключа в общем окне запросов (`tokens.service.в_пределах`). С
# приставкой, а не голым `user.id`: окно одно на процесс, и человек, у которого
# есть ещё и внешний ключ, иначе тратил бы на предпросмотрах лимит своего
# ключа — или наоборот.
ОКНО_ПРЕДПРОСМОТРА = "preview:"


def не_чаще(request: Request, settings: Settings, user) -> None:
    """Не слишком ли часто этот человек просит предпросмотр. Иначе `429`.

    Решение владельца §12: 30 запросов в минуту на человека. Предпросмотр —
    единственный тяжёлый маршрут службы, который любой вошедший дёргает без
    проекта, без роли и без задания в очереди: он зовёт подпроцесс с
    tree-sitter'ом на каждое нажатие клавиши в редакторе, и ничем, кроме этого
    числа, не ограничен. Постановке заданий такой счётчик не нужен — там
    ограничивают слоты и месячный потолок.

    Считается **скользящим окном в памяти процесса** — тем же, что считает
    запросы внешних ключей (`tokens.service.в_пределах`), и с той же осознанной
    платой: счётчик не переживает перезапуск и не общий на два процесса API,
    то есть настоящий потолок — 30 × число процессов. База стоила бы записи на
    каждое нажатие клавиши; когда процессов станет много, лимит переедет на
    прокси, где ему и место.

    Событие безопасности пишется, как у ключей: `rate_limited` без подробностей
    — по нему владелец и увидит, что кто-то стучится редактором в цикле.
    """
    from ..admin import models as виды                        # noqa: PLC0415
    from ..admin import service as журнал                     # noqa: PLC0415
    from ..tokens.service import в_пределах                   # noqa: PLC0415

    user_id = str(getattr(user, "id", "") or "")
    if в_пределах(ОКНО_ПРЕДПРОСМОТРА + user_id,
                  лимит=int(settings.preview_per_minute)):
        return
    журнал.событие(request, виды.RATE_LIMITED, user=user_id or None,
                   route="preview")
    raise ApiError(RATE_LIMITED,
                   f"More than {settings.preview_per_minute} preview requests "
                   "per minute", 429)


# ── построение ───────────────────────────────────────────────────────────────

def построить(request: Request, settings: Settings, вид: str,
              задание: dict) -> Схема:
    """Позвать строителя схем в подпроцессе. Отказ строителя — наш `ApiError`.

    Ни XML, ни исходник в журнал не уезжают: в журнал уезжает причина отказа, и
    ровно потому, что клиенту её не отдают.
    """
    try:
        ответ = выполнить(ДИТЯ, {**задание, "вид": вид}, что=f"схема ({вид})",
                          таймаут=settings.parse_timeout_s,
                          память=settings.parse_memory_bytes,
                          беда=СхемаНеПостроилась)
    except СхемаНеПостроилась as беда:
        _в_журнал(request, беда)
        raise ApiError(DIAGRAM_FAILED, DIAGRAM_FAILED_MESSAGE, 422,
                       where="body.source") from None

    код = ответ.get("error")
    if код:
        _отказ(request, ответ, код)
    return Схема(xml=str(ответ.get("xml", "")),
                 notices=list(ответ.get("notices") or ()),
                 items=[str(i) for i in ответ.get("items") or ()])


def _отказ(request: Request, ответ: dict, код: str) -> NoReturn:
    """Отказ строителя → отказ службы. Возврата отсюда нет, только исключение."""
    сообщение = str(ответ.get("message") or "")
    # `cause` — «внутри было чужое исключение», то есть в тексте бывает кусок
    # разбираемого кода. Такой текст наружу не уезжает никогда, даже с кодом
    # 400: он уезжает в журнал.
    if ответ.get("cause") or код not in _КОДЫ_400:
        _в_журнал(request, сообщение)
        raise ApiError(DIAGRAM_FAILED, DIAGRAM_FAILED_MESSAGE, 422,
                       where="body.source")
    raise ApiError(_КОДЫ_400[код], сообщение or "Bad source", 400,
                   where="body.source")


def _в_журнал(request: Request, причина) -> None:
    """Подробность — в журнал бед, вместе с меткой запроса. Как `parse_failed`."""
    беды.warning("rid=%s схема не построилась: %s",
                 getattr(request.state, "request_id", "-"), причина)


def положить_артефакт(проект: Проект, схема: Схема, *, name: str) -> str:
    """XML схемы — артефактом проекта, вместе с её замечаниями. → идентификатор.

    Замечания ложатся рядом с артефактом, а не в ответ и только: одну и ту же
    схему можно поставить в два тега, правда о ней одна, и живёт она ровно
    столько, сколько живёт артефакт. Достаёт их потом
    `GET …/artifacts/{id}/notices` и полная проверка перед сборкой отчёта.
    """
    заметки = [Notice(module=n.get("module", ""), level=n.get("level", "warning"),
                      code=n.get("code", ""), message=n.get("message", ""),
                      file=n.get("file"), line=n.get("line"))
               for n in схема.notices]
    return открыть(проект).put_artifact(схема.xml.encode("utf-8"), name=name,
                                        notices=заметки)


__all__ = ["Схема", "СхемаНеПостроилась", "построить", "положить_артефакт",
           "проверить_язык", "проверить_режим", "проверить_тему",
           "проверить_размер", "один_исходник", "несколько_исходников",
           "исходник_материала", "FLOWCHART", "CLASSES", "OBJECTS",
           "INVALID_SOURCE", "UNKNOWN_LANG", "UNKNOWN_MODE", "UNKNOWN_THEME",
           "SOURCE_TOO_LARGE", "DIAGRAM_FAILED", "DIAGRAM_FAILED_MESSAGE",
           "не_чаще", "RATE_LIMITED", "ОКНО_ПРЕДПРОСМОТРА"]
