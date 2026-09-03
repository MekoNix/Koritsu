"""
seams — швы к соседям: кого ждём, по какому адресу и с какой подписью.

Половина сценария сегодня стоит на том, чего у соседей нет. Записка назвала
это поимённо, и здесь оно записано данными, чтобы отказ был не словом «потом»,
а адресом: пакет, номер правки в записке, подпись ожидаемой функции и одна
строка про то, что сломается без неё.

**Ни одного `import` соседа.** Двери приходят аргументом — `Services`, — а не
импортом, и это не стилистика. Правило импорта, принятое 2026-08-31
(`orchestrator/__init__.py`: «из него не импортирует никто»), слоя над
оркестратором не предусматривает вовсе; поправка на порядок слоёв — открытая
развилка владельца (записка, Л.9), и она не закрыта. Пока она не закрыта,
`import orchestrator` в `kadai` был бы нарушением действующего решения, а
`import hokoku` — вторым средним слоем, то есть ровно тем, чего просили
избежать. Аргумент вместо импорта закрывает оба вопроса: правило соблюдено
дословно, а поправку можно принять или отвергнуть, не трогая этот пакет.

Побочная выгода, ради которой это стоило бы сделать и без правила: `kadai`
проверяется на подделках из стандартной библиотеки, и его тесты не зависят от
того, в каком состоянии сегодня четыре соседних пакета.

Как отказывает шов: `NotReady` с текстом «жду `X` от `Y` (И.N): подпись» и
припиской, что без него нельзя. Соблазн вернуть правдоподобную пустоту разобран
в `errors`: пустая структура доедет до человека под видом результата.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .errors import NotReady, hint


@dataclass(frozen=True)
class Seam:
    """Один шов. `signature` — дословная подпись, которую мы зовём, когда её напишут.

    Подпись хранится строкой, а не в голове автора: без неё сообщение об отказе
    говорит «сосед не готов», и сосед узнаёт, чего от него ждали, только придя
    спрашивать. С ней записка и код называют одно и то же одними словами.
    """

    name: str
    neighbor: str            # чей это пакет
    address: str             # номер правки в записке + место в коде
    signature: str           # что именно мы зовём
    awaits: str              # чего ждём словами
    without: str             # что нельзя сделать, пока шва нет


SEAMS: dict[str, Seam] = {
    "разбор условия": Seam(
        name="разбор условия",
        neighbor="materials + orchestrator",
        address="И.1 (materials/_pdf.py:92-124), И.16 (orchestrator.ask). "
                "Проверено по коду 2026-08-31",
        signature="materials: пометка происхождения на кусок — какой текст взят из "
                  "текстового слоя, а какой распознан OCR (сегодня это только "
                  "заметка на весь материал); "
                  "orchestrator: ask(project, schema, request, *, endpoint) -> dict",
        awaits="разбор .docx в materials уже появился (WORD_EXT, _docx.py), а вот "
               "распознанное OCR по кускам от текстового слоя не отделено: страница "
               "склеивается в общий текст, и «показать человеку распознанное» — "
               "решение владельца 2026-08-31 — показывать нечего",
        without="стадия «разбор задания» не выполнима: условие доедет до модели пустым"),
    "структура": Seam(
        name="структура",
        neighbor="orchestrator",
        address="И.16",
        signature="ask(project, schema, request, *, endpoint) -> dict",
        awaits="безтеговая дверь к модели: обе сегодняшние точки входа привязаны к "
               "тегам манифеста, а у стадий «разбор задания» и «структура» тега нет",
        without="структуру отчёта не на чем сочинить, не зовя llm из kadai"),
    "шаблон": Seam(
        name="шаблон",
        neighbor="orchestrator + hokoku",
        address="И.18 (orchestrator.make_template), И.3 (hokoku: шаг «разделы → теги»), "
                "И.4 (hokoku.check_template — уже есть). Проверено по коду 2026-08-31",
        signature="make_template(base: bytes, sections: list[dict]) -> tuple[bytes, Manifest]; "
                  "разделы приходят как kadai.profile.Section (key, title, type, "
                  "required, numbered, limits, prompt)",
        awaits="в hokoku появились blank_document(), document_bytes(), check_template() "
               "и стиль из примера — но шага «список разделов → документ с тегами "
               "{{ключ}} и манифестом» нет, и двери из orchestrator тоже нет",
        without="шаблон не собрать; сита 3 и 4 (check_manifest и validate на пустых "
                "значениях) выполнять не над чем"),
    "решение": Seam(
        name="решение",
        neighbor="orchestrator",
        address="И.9 (уровень 3): fill_agent и tools.py появились 2026-08-31",
        signature="fill_agent(project, *, endpoint, keys=None, max_steps=None, "
                  "max_units=None, overwrite=False) -> AgentResult — передаётся "
                  "полем Services.solve; плюс инструмент put_source(name, language, text) "
                  "в наборе tools.py",
        awaits="сама петля уже есть, но в наборе семи инструментов нет `put_source`: "
               "код, сочинённый моделью, положить некуда, а он и есть предмет сценария "
               "kadai (решение владельца К0). Ещё открыт вопрос владельца про уровень 3 "
               "на endpoint'е без операторского канала",
        without="код производить нечем: схемы строятся из материалов студента, а не из "
                "того, что написала модель — стадия «решение» для kadai неполна"),
    "состояние стадий": Seam(
        name="состояние стадий",
        neighbor="orchestrator",
        address="И.6б (Project)",
        signature="Project.put_state(name: str, d: dict) -> None / Project.state(name: str) -> dict",
        awaits="места, куда положить ход работы так, чтобы kadai не узнал ни одного пути",
        without="статус живёт в памяти процесса, а считает и показывает по "
                "действующему решению «всё через очередь» разные процессы"),
    "журнал производных": Seam(
        name="журнал производных",
        neighbor="orchestrator",
        address="И.6а (Project)",
        signature="Project.note_derived(art, tool, inputs, params, run) -> None / "
                  "Project.derived_of(art) -> dict | None",
        awaits="связи «этот артефакт произведён тем инструментом из тех входов»",
        without="по замечанию «схему переделай» неизвестно, из какого исходника она "
                "построена и не сменился ли исходник под ней"),
    "архив": Seam(
        name="архив",
        neighbor="orchestrator",
        address="И.17 (Project)",
        signature="Project.pack(entries: list[dict]) -> str",
        awaits="сборки ZIP на стороне того, кто знает пути",
        without="kadai пришлось бы ходить по out/ руками, и правило «os.path.join "
                "только в project.py» ломается на первой же строке"),
    "отпечаток входа": Seam(
        name="отпечаток входа",
        neighbor="orchestrator",
        address="И.8 (prompt.py:326)",
        signature="второй отпечаток только по кускам с stable=True",
        awaits="признака устарелости тега: сегодняшний prompt_hash считается по всем "
               "кускам, включая волатильных соседей, и меняется у всех тегов сразу",
        without="точечный пересчёт по замечанию вырождается в полный: отличить "
                "«вход этого тега изменился» от «был другой прогон» нечем"),
}


def seam(name: str) -> Seam:
    """Шов по имени. Опечатка — ошибка с подсказкой, а не молчаливый `None`."""
    try:
        return SEAMS[name]
    except KeyError:
        raise NotReady(f"шва «{name}» нет{hint(name, SEAMS)}") from None


def not_ready(name: str, extra: str = "") -> NotReady:
    """Готовый отказ по шву: кого ждём, по какому адресу, с какой подписью."""
    s = seam(name)
    tail = f" {extra}" if extra else ""
    return NotReady(
        f"шов «{s.name}» ещё не сведён: жду {s.neighbor} ({s.address}) — {s.signature}. "
        f"Сейчас: {s.awaits}. Без этого {s.without}.{tail}")


@dataclass(frozen=True)
class Services:
    """Двери среднего слоя, переданные снаружи. Ни одна не обязательна.

    `project` — объект `orchestrator.Project`, но `kadai` знает о нём только по
    именам методов: он никогда не спрашивает у него путь и не импортирует его
    класс. `ask` и `make_template` — функции модуля, а не методы, поэтому
    приходят полями.

    Почему `None` разрешён: пакет обязан быть полезен до того, как соседи
    допишут своё. Отсутствующая дверь даёт `NotReady` в тот момент, когда её
    позвали, — а не пустой результат и не падение на `AttributeError`, по
    которому не понять, кого ждать.
    """

    project: object = None
    ask: object = None                # orchestrator.ask (И.16)
    make_template: object = None      # orchestrator.make_template (И.18)
    solve: object = None              # уровень 3 (И.9)
    extra: dict = field(default_factory=dict)


def door(services: Services, attr: str, seam_name: str):
    """Дверь-функция из `Services` или внятный отказ по шву."""
    fn = getattr(services, attr, None) or services.extra.get(attr)
    if fn is None:
        raise not_ready(seam_name)
    return fn


def method(obj, attr: str, seam_name: str):
    """Метод `Project`, которого может ещё не быть, — или отказ по шву.

    Утиная проверка вместо импорта: как только метод у `Project` появится,
    вызов заработает сам, без правки здесь. Пока его нет — отказ называет
    подпись, которую надо написать, а не `AttributeError` с именем поля.
    """
    if obj is None:
        raise not_ready(seam_name, "проект не передан: Services.project пуст.")
    fn = getattr(obj, attr, None)
    if not callable(fn):
        raise not_ready(seam_name, f"у проекта нет метода {attr}().")
    return fn


__all__ = ["Seam", "SEAMS", "Services", "seam", "not_ready", "door", "method"]
