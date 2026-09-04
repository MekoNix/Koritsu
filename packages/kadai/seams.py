"""
seams — швы к соседям: кого ждём, по какому адресу и с какой подписью.

Половина сценария сегодня стоит на том, чего у соседей нет. Записка назвала
это поимённо, и здесь оно записано данными, чтобы отказ был не словом «потом»,
а адресом: пакет, номер правки в записке, подпись ожидаемой функции и одна
строка про то, что сломается без неё.

**Ни одного `import` службы.** Двери приходят аргументом — `Services`, — а не
импортом, и это не стилистика. Правило импорта, принятое 2026-08-31
(`orchestrator/__init__.py`: «из него не импортирует никто»), слоя над
оркестратором не предусматривает вовсе; поправка на порядок слоёв — открытая
развилка владельца (записка, Л.9), и она не закрыта. Пока она не закрыта,
`import orchestrator` в `kadai` был бы нарушением действующего решения.
Аргумент вместо импорта закрывает вопрос: правило соблюдено дословно, а
поправку можно принять или отвергнуть, не трогая этот пакет. Движок отчётов —
исключение (правило разреза 2.0.0a4.3 разрешает `hokoku` чистыми функциями), и
живёт оно в одном файле `blocks.py`, а не расползается по швам.

Побочная выгода, ради которой это стоило бы сделать и без правила: `kadai`
проверяется на подделках из стандартной библиотеки, и его тесты не зависят от
того, в каком состоянии сегодня четыре соседних пакета.

Как отказывает шов: `NotReady` с текстом «жду `X` от `Y` (И.N): подпись» и
припиской, что без него нельзя. Соблазн вернуть правдоподобную пустоту разобран
в `errors`: пустая структура доедет до человека под видом результата.

Состояние на 2026-09-04 (сведение, версия 2.0.0a4.3). Сведены все швы, кроме
двух, и оба недоведённых названы здесь поимённо: **разбор условия** (распознанное
OCR отделимо только целым материалом — человеку показывается весь текст условия с
пометкой, а не распознанные куски) и **отпечаток входа** (второго `prompt_hash`
по стабильным кускам нет, поэтому «этот блок устарел» от «был другой прогон» не
отличается). Ни один из двух не отказывает вызовом: они не двери, а точность —
работа идёт, просто грубее, чем задумано. Всё остальное зовётся по-настоящему.
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
        address="И.1 (materials/_pdf.py:92-124), И.16 (orchestrator.doors.ask). "
                "Проверено по коду 2026-09-04",
        signature="Project.condition() -> id | None, Project.store().read(id) -> Chunk(.text); "
                  "materials: пометка происхождения на кусок — какой текст взят из "
                  "текстового слоя, а какой распознан OCR",
        awaits="условие принимается (add_material(condition=True), разбор .docx есть, "
               "tesseract зовётся), но распознанное OCR отделимо только целым "
               "материалом: внутри PDF страница со сканом склеивается с остальными в "
               "общий текст. Значит человеку показывается весь текст условия с "
               "пометкой «читано OCR», а не распознанные куски отдельно",
        without="решение владельца 2026-08-31 «показать распознанное до работы» "
                "выполняется грубее, чем задумано: ошибку в одной формуле человек "
                "ищет глазами по всему условию"),
    "структура": Seam(
        name="структура",
        neighbor="orchestrator",
        address="И.16 (orchestrator.doors.ask). Сведено 2026-09-04",
        signature="ask(question, *, schema=None, data=()) -> Answer(ok, value, text, "
                  "problems, usage) — приходит полем Services.ask, project и endpoint "
                  "уже связаны",
        awaits="дверь есть и зовётся: безтеговый вопрос с рамкой вокруг чужого текста, "
               "схема ответа своя, версии тега не заводится",
        without="строение работы не на чем сочинить, не зовя llm из kadai"),
    "шаблон": Seam(
        name="шаблон",
        neighbor="orchestrator + hokoku",
        address="И.18 (orchestrator.doors.make_template), И.3 (hokoku.live: блоки "
                "вместо тегов). Сведено 2026-09-04",
        signature="make_template(structure, *, task='', default=(), data=()) -> "
                  "list записей блоков; разделы приходят как kadai.profile.Section "
                  "(key, title, kind, type, required, prompt)",
        awaits="шаблона как документа больше нет вовсе: работа — список блоков, и "
               "make_template кладёт по два блока на раздел (заголовок и место под "
               "содержимое). `before=` появился 2026-09-04: повторная сборка "
               "переносит блоки человека (source manual/file) в раздел с тем же "
               "заголовком, сохраняя им ключ и пометку. Не умеет она одного — "
               "узнать ПЕРЕИМЕНОВАННЫЙ заголовок: для неё это «раздел убрали и "
               "добавили другой», и блок уезжает в конец списка с пометкой в "
               "версии, а не молча в чужой раздел",
        without="скелет работы не собрать, а собранный второй раз затирал бы правки "
                "человека молча (см. rework, маршрут «структура»)"),
    "решение": Seam(
        name="решение",
        neighbor="orchestrator",
        address="И.9 (orchestrator.live.solve, tools.py). Сведено 2026-09-04",
        signature="solve(task, *, tools=None, data=(), max_steps=None) -> "
                  "LiveResult(ok, blocks, version, changed, problems, usage, steps, calls)",
        awaits="петля с инструментами живого режима есть (правка блоков, чтение "
               "материалов, схемы), и с 2026-09-04 в наборе есть `put_source`: "
               "модель кладёт сочинённый ею исходник материалом и строит по тому же "
               "идентификатору схему тем же make_flowchart. Связка «пишет код и "
               "рисует по нему схему» работает целиком",
        without="без put_source схемы строились бы только по исходникам, которые "
                "принёс человек"),
    "текст": Seam(
        name="текст",
        neighbor="orchestrator",
        address="orchestrator.live.write_texts, приходит Services.extra['write_texts']. "
                "Сведено 2026-09-04",
        signature="write_texts(*, overwrite=False, data=()) -> TextsResult(ok, filled, "
                  "version, problems, usage)",
        awaits="проход текста одним вызовом по готовому списку блоков (решение "
               "владельца 2026-09-04); блоки с source manual/file он выбрасывает сам",
        without="связный текст пришлось бы писать петлёй по блоку, а это и дороже, и "
                "даёт рассогласованные абзацы"),
    "проверка кода": Seam(
        name="проверка кода",
        neighbor="orchestrator (fragmos/kyotsu)",
        address="решение владельца 2026-08-31 (К0): код проверяется статически. "
                "orchestrator.doors.check_code. Сведено 2026-09-04",
        signature="check_code(text, language) -> list замечаний "
                  "{module, level, code, key, message} — Services.extra['check_code']",
        awaits="дверь есть и зовётся стадией «сборка»: tree-sitter разбирает исходник, "
               "не запуская его, и отвечает на один вопрос — целый ли он. Три исхода: "
               "пусто (error), язык не из разбираемых (warning, «уедет непроверенным»), "
               "не разбирается (error с номером строки). Знание о языках осталось в "
               "службе — сценарию оно не принадлежит (решение 2026-09-04)",
        without="код в архиве не был бы проверен вовсе, а обещан проверенным "
                "статически: обрывок и синтаксический мусор доехали бы до человека"),
    "PDF": Seam(
        name="PDF",
        neighbor="hokoku",
        address="hokoku.docx_bytes_to_pdf — чистая функция байт→байты; дверь "
                "Services.extra['to_pdf'] её замещает",
        signature="to_pdf(docx: bytes) -> bytes",
        awaits="LibreOffice в системе; без него PDF не собирается",
        without="в архиве не будет отчёта в PDF — но это единственная потеря, и "
                "остальной архив собирается"),
    "список блоков": Seam(
        name="список блоков",
        neighbor="orchestrator",
        address="Project.blocks / set_blocks / block_versions / rollback_blocks. "
                "Сведено 2026-09-04",
        signature="Project.blocks() -> list; Project.set_blocks(blocks, *, source, "
                  "note='', run=None) -> BlockVersion",
        awaits="хранения работы списком блоков с версиями и пометкой источника",
        without="ни показать состав работы, ни переписать один блок по замечанию"),
    "артефакты": Seam(
        name="артефакты",
        neighbor="orchestrator",
        address="Project.put_artifact / resolve_artifact. Сведено 2026-09-04",
        signature="Project.put_artifact(data, *, name='') -> id; "
                  "Project.resolve_artifact(id) -> bytes",
        awaits="хранилища байтов по содержимому: собранный отчёт и синтетический "
               "шаблон кладутся туда, а в опись архива едет идентификатор, не путь",
        without="отчёт в архив пришлось бы нести путём — а путей в kadai нет"),
    "состояние стадий": Seam(
        name="состояние стадий",
        neighbor="orchestrator",
        address="И.6б (Project.put_state / state). Сведено 2026-09-04",
        signature="Project.put_state(name: str, d: dict) -> None / Project.state(name: str) -> dict",
        awaits="места, куда положить ход работы так, чтобы kadai не узнал ни одного пути",
        without="статус живёт в памяти процесса, а считает и показывает по "
                "действующему решению «всё через очередь» разные процессы"),
    "журнал производных": Seam(
        name="журнал производных",
        neighbor="orchestrator",
        address="И.6а (Project.note_derived / derived_of). Сведено 2026-09-04",
        signature="Project.note_derived(art, *, tool, inputs=(), params=None, run=None) -> None / "
                  "Project.derived_of(art) -> dict | None",
        awaits="журнал есть, и с 2026-09-04 в него пишут сами строители схем "
               "(make_flowchart и обе диаграммы). Остаётся одна дыра, и она не в "
               "журнале: значение блока `diagram` держит схему XML'ем, а не "
               "идентификатором (hokoku.wire эмитит xml, не artifact), поэтому по "
               "блоку найти его производную нечем — искать придётся по содержимому",
        without="по замечанию «схему переделай» неизвестно, из какого исходника она "
                "построена и не сменился ли исходник под ней"),
    "архив": Seam(
        name="архив",
        neighbor="orchestrator",
        address="И.17 (Project.pack). Сведено 2026-09-04",
        signature="Project.pack(entries: list[dict], *, name='работа.zip') -> str (имя, не путь)",
        awaits="сборки ZIP на стороне того, кто знает пути",
        without="kadai пришлось бы ходить по out/ руками, и правило «os.path.join "
                "только в project.py» ломается на первой же строке"),
    "отпечаток входа": Seam(
        name="отпечаток входа",
        neighbor="orchestrator",
        address="И.8 (prompt.py:326)",
        signature="второй отпечаток только по кускам с stable=True",
        awaits="признака устарелости блока: сегодняшний prompt_hash считается по всем "
               "кускам, включая волатильных соседей, и меняется у всех сразу",
        without="точечный пересчёт по замечанию считается по ключам блоков и журналу "
                "производных, а не по входу: «этот блок устарел» отличить от «был "
                "другой прогон» нечем"),
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
