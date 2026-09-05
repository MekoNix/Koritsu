"""
saved — сохранённые схемы работы: заведение, перестройка, список, чтение.

Общее для двух модулей (`flowcharts` и `uml`), как и `diagrams.py` рядом: у
блок-схемы и диаграммы UML разные строители и разные параметры, но одинаковая
судьба — построилась, попала в журнал работы под своим номером, лежит там до тех
пор, пока её не убрали. Разложить эту судьбу по двум модулям значило бы завести
два способа сохранить схему, две формы ответа и два места, где однажды забудут
записать в журнал.

**Схема сохраняется сама, кнопки «сохранить в проект» нет.** Построенная схема —
уже результат работы: человек нажал «построить», получил картинку и ушёл, а
назавтра ищет её в работе. Кнопка сохранения означала бы, что половина
построенных схем теряется молча — ровно то, чего от неё и ждут. Отсюда: маршрут
построения в проект **и есть** сохранение, а перестройка той же схемы
(`PUT …/{run_id}`) новой записи не заводит: иначе пять нажатий подряд, пока
подбирается код, дали бы пять «Схема 1…5» в журнале.

**Имени схеме служба не сочиняет.** Имя по умолчанию — русское («Схема 2 —
Курсовая»), а наружу служба говорит по-английски; вторая таблица переводов в ней
разошлась бы с той, что в интерфейсе. Служба хранит номер (`n`) — тот, что
считает база, потому что два браузера, открывшие работу разом, придумали бы одно
и то же «Схема 2», — а рисует имя по нему интерфейс.

**Список — журнал плюс своё.** Что и когда запускали, знает `project_runs`;
чем это строили — знает `project_diagrams`. Список схем модуля собирается
соединением двух таблиц с отбором по модулю: у UML свой список, у блок-схем
свой, и одна схема не попадает в оба.

Исходники ложатся на том артефактом (`ProjectDiagram.source_id`), а не строкой в
базе: мегабайт чужого кода в индексе означал бы вычитывание всех исходников
работы всякий раз, когда человек открывает список.
"""
from __future__ import annotations

import json

import orchestrator
from pydantic import BaseModel, Field
from sqlalchemy import select

from ..errors import ApiError, NOT_FOUND
from ..ids import check_id
from ..materials.deps import Проект
from ..materials.service import открыть
from ..projects.models import ProjectRun
from ..projects.runs import завести
from ..workspaces.service import iso
from .models import ProjectDiagram

# Имя артефакта с исходниками. Наружу не уезжает и в путь не превращается:
# `put_artifact` адресует содержимым, а имя принимает для читаемости вызова.
ИМЯ_ИСХОДНИКОВ = "исходники"


class DiagramSource(BaseModel):
    """Один исходник схемы: как назывался файл и что в нём было."""

    name: str = Field(description="File name, for messages only")
    source: str = Field(description="Source code the diagram was built from")


class DiagramOut(BaseModel):
    """Строка списка сохранённых схем. Исходников в ней нет намеренно.

    Список читают, чтобы выбрать схему, а не чтобы её перестроить: класть в
    каждую строку по мегабайту кода значило бы вычитывать с тома всю работу
    ради одного экрана.
    """

    run_id: str = Field(description="Journal entry of this diagram; delete it "
                                    "to delete the diagram")
    project_id: str
    module: str = Field(description="flowcharts or uml")
    kind: str = Field(description="flowchart, classes or objects")
    name: str = Field(description="Empty means the interface names it itself")
    n: int = Field(description="Which diagram of this module in this project")
    artifact: str = Field(description="Artifact id of the drawio XML")
    lang: str
    mode: str = Field(default="", description="Drawing mode, flowcharts only")
    theme: str = Field(default="", description="Palette, uml only")
    created_at: str | None = None


class DiagramFullOut(DiagramOut):
    """Схема целиком: XML, исходники и замечания строителя.

    Отдаётся при построении и при открытии сохранённой схемы — то есть ровно
    тогда, когда её собираются показать в редакторе и править дальше. XML здесь
    же, а не отдельным запросом за артефактом: экран без картинки бесполезен, и
    второй поход за ней означал бы, что схема появляется рывком.
    """

    xml: str = Field(description="The drawio XML itself")
    sources: list[DiagramSource] = Field(
        default_factory=list,
        description="Sources the diagram was built from, in order")
    notices: list[dict] = Field(
        default_factory=list, description="What the builder had to say")


class DiagramBuiltOut(DiagramFullOut):
    """Только что построенная схема: к сохранённому добавлено `items`.

    `items` — что строитель нарисовал: имена классов, имена экземпляров. Это
    ответ строителя, а не свойство схемы, и в базе его нет: по нему человек
    видит, что диаграмма про его код, **до** того, как откроет картинку, — а
    открыв сохранённую, он видит это на самой картинке.
    """

    items: list[str] = Field(
        default_factory=list,
        description="What got drawn: class names, instance names")


# ── исходники на томе ────────────────────────────────────────────────────────

def положить_исходники(проект: Проект, исходники: list[tuple[str, str]]) -> str:
    """Список `[(имя, текст)]` → артефакт с JSON. → идентификатор артефакта.

    JSON, а не сам текст: исходников у диаграммы UML несколько, и у каждого есть
    имя, которое видно в замечаниях разбора. Склеить их в один файл значило бы
    потерять границы, а завести по артефакту на файл — хранить порядок где-то
    ещё (у диаграммы объектов первый исходник — точка входа, порядок значащий).
    """
    тело = json.dumps([{"name": имя, "source": код} for имя, код in исходники],
                      ensure_ascii=False)
    return открыть(проект).put_artifact(тело.encode("utf-8"),
                                        name=ИМЯ_ИСХОДНИКОВ)


def словарями(исходники: list[tuple[str, str]]) -> list[dict]:
    """Исходники в форме ответа. Только что записанные читать с тома незачем."""
    return [{"name": имя, "source": код} for имя, код in исходники]


def прочитать_исходники(проект: Проект, source_id: str) -> list[dict]:
    """Исходники схемы с тома. Нет их или они испортились — пустой список.

    Пустой список, а не отказ: исходник — подспорье («вот чем это построено»),
    а схема остаётся схемой и без него. Уронить открытие сохранённой картинки
    из-за пропавшего текста значило бы наказать человека за уборку тома.
    """
    if not source_id:
        return []
    try:
        данные = открыть(проект).resolve_artifact(source_id)
        разобрано = json.loads(данные.decode("utf-8"))
    except (orchestrator.OrchestratorError, OSError, ValueError):
        return []
    if not isinstance(разобрано, list):
        return []
    return [{"name": str(кусок.get("name", "")),
             "source": str(кусок.get("source", ""))}
            for кусок in разобрано if isinstance(кусок, dict)]


# ── карточки наружу ──────────────────────────────────────────────────────────

def карточка(запись: ProjectRun, схема: ProjectDiagram) -> dict:
    """Строка списка: журнал плюс параметры постройки."""
    return {"run_id": запись.id, "project_id": запись.project_id,
            "module": запись.module, "kind": схема.kind, "name": запись.name,
            "n": int(запись.n), "artifact": запись.artifact_id or "",
            "lang": схема.lang, "mode": схема.mode, "theme": схема.theme,
            "created_at": iso(запись.created_at)}


def полная(проект: Проект, запись: ProjectRun, схема: ProjectDiagram, *,
           xml: str, sources: list[dict] | None = None,
           notices: list[dict] | None = None,
           items: list[str] | None = None) -> dict:
    """Карточка вместе с XML, исходниками и замечаниями.

    `items` ставится только там, где он и есть, — сразу после постройки: у
    сохранённой схемы его неоткуда взять, и пустой список в ответе соврал бы,
    что на схеме ничего не нарисовано.
    """
    готово = {**карточка(запись, схема), "xml": xml,
              "sources": (sources if sources is not None
                          else прочитать_исходники(проект, схема.source_id)),
              "notices": notices if notices is not None else []}
    return готово if items is None else {**готово, "items": list(items)}


# ── заведение и перестройка ──────────────────────────────────────────────────

def сохранить(s, проект: Проект, user, *, module: str, kind: str,
              artifact: str, исходники: list[tuple[str, str]], lang: str,
              mode: str = "", theme: str = "") -> tuple[ProjectRun,
                                                        ProjectDiagram]:
    """Построенная схема → запись журнала и строка параметров. Обе разом.

    Имя записи остаётся пустым: его рисует интерфейс из модуля и номера
    (см. шапку модуля).
    """
    запись = завести(s, проект, user, module=module, artifact_id=artifact)
    схема = ProjectDiagram(run_id=запись.id, kind=kind, lang=lang, mode=mode,
                           theme=theme,
                           source_id=положить_исходники(проект, исходники))
    s.add(схема)
    s.flush()
    return запись, схема


def перестроить(s, проект: Проект, запись: ProjectRun, схема: ProjectDiagram,
                *, kind: str, artifact: str,
                исходники: list[tuple[str, str]], lang: str, mode: str = "",
                theme: str = "") -> None:
    """Та же схема, построенная заново: новый XML, новый код, те же имя и номер.

    Номер и имя не трогаются намеренно: человек правит один и тот же рисунок, а
    не заводит второй, и «Схема 1» после третьего нажатия обязана остаться
    «Схемой 1».
    """
    запись.artifact_id = artifact
    схема.kind = kind
    схема.lang = lang
    схема.mode = mode
    схема.theme = theme
    схема.source_id = положить_исходники(проект, исходники)
    s.flush()


# ── чтение ───────────────────────────────────────────────────────────────────

def найти(s, проект: Проект, run_id: str,
          module: str) -> tuple[ProjectRun, ProjectDiagram]:
    """Схема работы по записи журнала — или `404`.

    Чужая запись, запись другого модуля и запись без схемы отвечают одинаково:
    разные ответы рассказывали бы, что такая строка есть у кого-то другого.
    """
    запись = s.get(ProjectRun, check_id(run_id, where="path.run_id"))
    схема = None
    if запись is not None and запись.project_id == проект.id:
        схема = s.scalar(select(ProjectDiagram)
                         .where(ProjectDiagram.run_id == запись.id))
    if запись is None or схема is None or запись.module != module:
        raise ApiError(NOT_FOUND, "Diagram not found", 404, where="path.run_id")
    return запись, схема


def список(s, проект: Проект, module: str) -> list[dict]:
    """Сохранённые схемы одного модуля, новые сверху.

    Отбор по модулю — не украшение списка, а его смысл: у UML свой список, у
    блок-схем свой, и диаграмма классов не обязана мешаться среди блок-схем
    только потому, что и то и другое рисует draw.io.
    """
    пары = s.execute(
        select(ProjectRun, ProjectDiagram)
        .join(ProjectDiagram, ProjectDiagram.run_id == ProjectRun.id)
        .where(ProjectRun.project_id == проект.id, ProjectRun.module == module)
        .order_by(ProjectRun.created_at.desc(), ProjectRun.n.desc()))
    return [карточка(запись, схема) for запись, схема in пары]


def xml_артефакта(проект: Проект, artifact: str) -> str:
    """XML сохранённой схемы с тома. Нет артефакта — пустая строка.

    Пустая строка, а не отказ, по той же причине, что и у исходников: открытие
    сохранённой схемы не должно падать из-за прибранного тома — параметры и код
    при этом целы, и построить заново есть чем.
    """
    if not artifact:
        return ""
    try:
        return открыть(проект).resolve_artifact(artifact).decode("utf-8")
    except (orchestrator.OrchestratorError, OSError, UnicodeDecodeError):
        return ""


def замечания(проект: Проект, artifact: str) -> list[dict]:
    """Замечания, с которыми схема построена. Лежат рядом с артефактом."""
    if not artifact:
        return []
    try:
        return [n.to_dict() for n in открыть(проект).artifact_notices(artifact)]
    except (orchestrator.OrchestratorError, OSError):
        return []


__all__ = ["DiagramSource", "DiagramOut", "DiagramFullOut",
           "DiagramBuiltOut", "карточка",
           "словарями",
           "полная", "сохранить", "перестроить", "найти", "список",
           "положить_исходники", "прочитать_исходники", "xml_артефакта",
           "замечания"]
