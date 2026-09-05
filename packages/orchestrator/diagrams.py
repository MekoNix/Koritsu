"""
diagrams — единственная дверь к строителям схем: `fragmos` и `uml_generator`.

Зачем дверь. Правило разреза (`tests/kyotsu/test_border.py`) разрешает службе
`api` знать только про `orchestrator`, `materials`, `kyotsu` и `llm`: строители
схем службе не видны, а показать блок-схему сайту она обязана. До этого модуля
знание «как позвать fragmos» лежало ровно в одном месте — в инструментах агента
(`tools._make_flowchart` и два соседа), — и второй вызывающий поставил бы службу
перед выбором: либо нарушить разрез, либо переписать те же двадцать строк у
себя. Переписанные, они разошлись бы молча: агент строит схему одним режимом,
сайт — другим, а человек видит две разные картинки по одному коду.

Поэтому здесь собрано всё, что раньше было размазано по трём методам `ToolBox`:
перечни языков, режимов и тем, приведение чужих имён языка к нашим, единая
форма предупреждения и единая форма отказа. Инструменты агента с 2.0.0a5.1
зовут этот модуль, а не `fragmos` напрямую (`tools.py`), — знание осталось в
одном месте, а вызывающих стало двое.

    flowchart(code, lang, mode=…)          блок-схема алгоритма → DiagramResult
    class_diagram(sources, lang, theme=…)  диаграмма классов UML
    object_diagram(sources, lang, entry=…) диаграмма объектов UML
    flowchart_modes()                      режимы отрисовки с описаниями
    mode(значение)                         имя режима или псевдоним → наше имя
    uml_themes()                           палитры диаграмм UML
    languages()                            языки, которые разбираются

**Пользовательский код не выполняется нигде и никогда.** И `fragmos`, и
`uml_generator` разбирают исходник tree-sitter'ом; ни `exec`, ни подпроцесса, ни
похода в сеть здесь нет. Подпроцесс, в котором служба зовёт эти функции, заведён
не ради безопасности исполнения, а ради потолка памяти и времени: разбор
миллиона строк упирается во время, а не в правильность (`api/subproc.py`).

**Язык называется одним словом на весь проект** — `py`, `cs`, `cpp`. Внутри
соседи зовут те же языки иначе (`fragmos` ждёт `python` и `csharp`), и
приведение стоит здесь, в одном месте: таблица, размноженная по вызывающим, —
это тот же расход, что и переписанные двадцать строк. Чужие имена на входе
принимаются (`python`, `csharp`, `c++`) — инструменты агента объявляют модели
свой перечень и присылают его дословно, и ломать их ради красоты входа незачем.

**Предупреждение — одно: `kyotsu.Notice`.** `fragmos` уже отдаёт их такими
(«в схему не вошло: goto case»), а `objektis` отдаёт свои заметки строками — и
строки здесь заворачиваются в ту же форму. Второй вид предупреждения означал бы
второй разбор в интерфейсе; ровно ради этого `kyotsu.Notice` и заводился.

**Отказ — `DiagramError`, и он не `OrchestratorError`.** Разница та же, что у
`ToolError`: `OrchestratorError` означает «службу позвали неправильно» и обязан
долететь до человека, а «этот код не разобрался как C++» — законный ответ на
законный вопрос, и его показывают тому, кто прислал код. Слить их значило бы
либо ронять службу на опечатке студента, либо прятать от неё настоящую поломку.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import fragmos
import uml_generator
from fragmos.builder.modes import get_mode, list_modes
from kyotsu import Notice
from uml_generator import objektis
from uml_generator.styles import list_themes

# Языки, которые мы разбираем, — по одному короткому слову на язык. Порядок
# постоянный: он уезжает в перечень OpenAPI и в выпадающий список на сайте.
LANGS = ("py", "cs", "cpp")

# Чужие имена того же языка → наши. Таблица односторонняя намеренно: наружу
# уезжает только левый столбец `LANGS`, а правый нужен, чтобы принять то, что
# присылает модель (инструменты объявляют ей `python`/`csharp`/`cpp`).
_ПРИВЕДЕНИЕ = {
    "py": "py", "python": "py", "python3": "py",
    "cs": "cs", "csharp": "cs", "c#": "cs",
    "cpp": "cpp", "c++": "cpp", "cxx": "cpp",
}

# Как этот же язык зовут соседи. Два словаря, а не один: `fragmos` и
# `uml_generator` называют язык по-разному, и складывать их имена в одно поле
# значило бы завести третье имя, которого не знает ни один из них.
_ДЛЯ_FRAGMOS = {"py": "python", "cs": "csharp", "cpp": "cpp"}
_ДЛЯ_OBJEKTIS = {"py": "python", "cs": "csharp", "cpp": "cpp"}

# Коды отказов. Перечисляются здесь, потому что выдаёт их этот модуль; служба
# переводит их в коды HTTP у себя (`api/modules/diagrams.py`), а инструменты
# агента — в свои `ToolError` (`tools.py`).
UNKNOWN_LANG = "unknown_lang"
UNKNOWN_MODE = "unknown_mode"
UNKNOWN_THEME = "unknown_theme"
INVALID_SOURCE = "invalid_source"
NO_CLASSES = "no_classes"
NO_OBJECTS = "no_objects"


class DiagramError(Exception):
    """Схема не построилась, и починить это может тот, кто прислал исходник.

    `code` — короткое слово из перечня выше; по нему служба выбирает код HTTP, а
    инструмент агента — свой `ToolError`. `cause` — настоящее исключение соседа,
    если оно было: вызывающему бывает нужно отличить `SyntaxError` («не тот
    язык») от всего остального, а текст соседа наружу не уезжает никогда — в нём
    бывает кусок разбираемого кода.

    `notices` — то, что разбор успел сказать до отказа. У `no_objects` это
    единственное объяснение, почему схема пуста, и терять его нельзя: немой
    отказ заставляет чинить наугад.
    """

    def __init__(self, code: str, message: str, *, cause: Exception | None = None,
                 where: str = "", notices=()):
        super().__init__(message)
        self.code = code
        self.message = message
        self.cause = cause
        # Имя исходника, на котором всё кончилось, — когда их было несколько.
        # Именем, а не номером: номер в списке вызывающий и так знает, а вот
        # какой из восьми файлов не разобрался, по номеру не покажешь человеку.
        self.where = where
        self.notices: tuple[Notice, ...] = tuple(notices)


@dataclass(frozen=True)
class DiagramResult:
    """Построенная схема: XML, предупреждения и что на ней нарисовано.

    `xml` — строка draw.io (`mxfile`), а не путь и не файл: строкой её отдают и
    `fragmos`, и `uml_generator`, а вызывающему (службе, прогону отчёта) нужен
    именно XML — на диск его кладёт тот, у кого есть хранилище.

    `items` — имена того, что попало на схему: классы у диаграммы классов,
    экземпляры у диаграммы объектов, у блок-схемы пусто. Одно поле вместо двух с
    разными именами: показывают их в одном месте и одинаково, а два поля
    означали бы две ветки в интерфейсе там, где смысл один.

    Неизменяемый, как `kyotsu.Notice`, и по той же причине: это свидетельство о
    том, что получилось, а дописывать его по дороге к интерфейсу некому.
    """

    xml: str
    notices: tuple[Notice, ...] = ()
    items: tuple[str, ...] = field(default=())


# ── перечни ──────────────────────────────────────────────────────────────────

def languages() -> tuple[str, ...]:
    """Языки, которые разбираются: `py`, `cs`, `cpp`. Порядок постоянный."""
    return LANGS


# Псевдонимы режимов: чужое имя → наше. Принимаются на вход, но наружу в
# перечне не показываются: наружу уходит только `gost_19_701_90`, а псевдоним
# `loopLimit` из списка режимов убран.
#
# Убрать его из `modes.yaml` было бы неправдой другого рода: `loopLimit` —
# исторический идентификатор того же режима, он лежит в чужих настройках и в
# ссылках, и отказывать по нему значило бы сломать их ради вида перечня.
# Поэтому режим один, имён у него два, и наружу называется одно.
ПСЕВДОНИМЫ_РЕЖИМОВ: dict[str, str] = {"loopLimit": "gost_19_701_90"}


def flowchart_modes() -> list[dict]:
    """Режимы отрисовки блок-схемы: `[{"id": …, "description": …}]`.

    Спрашиваем у `fragmos` (`modes.yaml`), а не держим свой список: перечень
    режимов — его дело, и второй список разошёлся бы с первым на первом же
    добавленном режиме. Описание идёт как есть, по-русски: это данные для
    человека, а не код ошибки (наружу по-английски уходят коды и тексты бед);
    переводит его сайт.

    Псевдонимы (`ПСЕВДОНИМЫ_РЕЖИМОВ`) в перечень не попадают: два имени одного
    режима в списке выбора — это два пункта, между которыми человеку предложено
    выбрать, хотя разницы между ними нет.
    """
    return [{"id": mode_id, "description": str(get_mode(mode_id).get("description", ""))}
            for mode_id in list_modes() if mode_id not in ПСЕВДОНИМЫ_РЕЖИМОВ]


def uml_themes() -> list[str]:
    """Палитры диаграмм UML из `uml_generator/styles.yaml`, плюс `css`.

    Перечень спрашивается у самого `uml_generator`, а не пишется здесь: свой
    список разошёлся бы с yaml на первой же новой палитре.
    """
    return list_themes()


def lang(значение: object) -> str:
    """Чужое имя языка → наше, или `DiagramError`. Единственное место таблицы."""
    имя = _ПРИВЕДЕНИЕ.get(str(значение or "").strip().lower())
    if имя is None:
        raise DiagramError(UNKNOWN_LANG,
                           f"language must be one of {', '.join(LANGS)}")
    return имя


def mode(значение: object) -> str:
    """Чужое имя режима → наше, или `DiagramError`. Единственное место таблицы.

    Псевдоним принимается и приводится к каноническому имени: снаружи может
    прийти `loopLimit` (он лежал в перечне раньше и остался в чужих настройках),
    а наружу мы обязаны называть один идентификатор — тот, что назван в перечне.
    Приведение здесь, а не у вызывающего: второе такое место разошлось бы с этим
    на первом же новом псевдониме.
    """
    имя = str(значение or "default").strip()
    имя = ПСЕВДОНИМЫ_РЕЖИМОВ.get(имя, имя)
    известные = [m["id"] for m in flowchart_modes()]
    if имя not in известные:
        raise DiagramError(UNKNOWN_MODE,
                           f"mode must be one of {', '.join(известные)}")
    return имя


# Прежнее имя того же: зовут его отсюда же, из `flowchart`.
_режим = mode


def _тема(значение: object) -> str:
    имя = str(значение or "dark").strip()
    if имя not in uml_themes():
        raise DiagramError(UNKNOWN_THEME,
                           f"theme must be one of {', '.join(uml_themes())}")
    return имя


def _исходники(sources) -> list[tuple[str, str]]:
    """`[(имя, код)]` из чего угодно похожего. Пустой список — отказ.

    Имя нужно и разбору (`fragmos` пишет его в замечание «файл не разобрался»),
    и человеку в ответе; путём оно не является и в путь не превращается нигде.
    """
    готово: list[tuple[str, str]] = []
    for кусок in sources or ():
        if isinstance(кусок, dict):
            имя, код = кусок.get("name") or "", кусок.get("source") or ""
        else:
            имя, код = кусок
        готово.append((str(имя or ""), str(код or "")))
    if not готово or not any(код.strip() for _, код in готово):
        raise DiagramError(INVALID_SOURCE, "No source code to draw a diagram from")
    return готово


# ── схемы ────────────────────────────────────────────────────────────────────

def flowchart(code: str, lang_: str, *, mode: str = "default",
              cfg: dict | None = None) -> DiagramResult:
    """Блок-схема алгоритма по исходнику. Одна страница на функцию.

    Резать многостраничный `mxfile` здесь нельзя и не нужно: `fragmos` отдаёт
    схемы всех функций сразу, а выбор листа — дело того, кто вставляет схему в
    отчёт (поле `page` у значения тега). Разрезание, однажды убранное из кода,
    возвращаться не должно.

    Что в схему не вошло, `fragmos` говорит вслух — эти замечания едут в
    `notices` и дальше рядом с артефактом на диск: смотреть отчёт человек будет
    позже и другим глазом.
    """
    язык = lang(lang_)
    режим = _режим(mode)
    текст = str(code or "")
    if not текст.strip():
        raise DiagramError(INVALID_SOURCE, "Source code is empty")
    notices: list[Notice] = []
    try:
        xml = fragmos.generate_xml(текст, _ДЛЯ_FRAGMOS[язык], mode_id=режим,
                                   cfg_overrides=cfg, warnings=notices)
    except SyntaxError as беда:
        raise DiagramError(INVALID_SOURCE, f"{беда}", cause=беда,
                           notices=notices) from None
    except Exception as беда:                    # noqa: BLE001 — fragmos бросает своё
        raise DiagramError(INVALID_SOURCE, f"{type(беда).__name__}: {беда}",
                           cause=беда, notices=notices) from None
    return DiagramResult(xml=xml, notices=tuple(notices))


def class_diagram(sources, lang_: str, *, theme: str = "dark",
                  cfg: dict | None = None) -> DiagramResult:
    """Диаграмма классов UML по нескольким исходникам.

    `sources` — `[(имя, код)]` или `[{"name":…, "source":…}]`. Классы
    собираются со всех и рисуются одной схемой: связи между классами из разных
    файлов иначе просто не нашлись бы.

    Пустая диаграмма — отказ `no_classes`, а не лист «нет классов». Лист без
    единого блока, вставленный в отчёт схемой, выглядит как поломка сборки, а
    отказ говорит правду: строить не из чего.
    """
    язык = lang(lang_)
    палитра = _тема(theme)
    добыть = {"py": uml_generator.extract_py,
              "cs": uml_generator.extract_cs,
              "cpp": uml_generator.extract_cpp}[язык]
    классы: list = []
    for имя, код in _исходники(sources):
        try:
            классы.extend(добыть(код))
        except Exception as беда:                # noqa: BLE001 — чужой разбор
            raise DiagramError(
                INVALID_SOURCE,
                f"{имя or 'source'}: {type(беда).__name__}: {беда}",
                cause=беда, where=имя) from None
    if not классы:
        raise DiagramError(NO_CLASSES, "No classes found in these sources")
    return DiagramResult(xml=uml_generator.build_xml(классы, палитра, cfg),
                         items=tuple(c.name for c in классы))


def object_diagram(sources, lang_: str, *, theme: str = "dark",
                   entry: int | str | None = None,
                   cfg: dict | None = None) -> DiagramResult:
    """Диаграмма объектов UML: какие экземпляры создаёт код и как они связаны.

    Трассировка статическая, код не выполняется. Точка входа — один исходник
    (модуль, `Main()`, `main()`), остальные едут соседними файлами; `entry`
    называет её номером или именем, по умолчанию это первый исходник.

    **Точка входа в соседи не повторяется.** `cs_static` и `cpp_static`
    склеивают вход со всеми соседями в один текст, и вход, поданный дважды,
    разбирался бы дважды: на C# с операторами верхнего уровня из-за этого на
    схеме появлялся второй экземпляр, которого в коде нет. Придуманный объект
    хуже отсутствующей схемы — его не с чем сверить.

    Заметки трассировки («чего разбор не понял») возвращаются `Notice`
    дословно, в том числе при отказе `no_objects`: пересказать их короче значило
    бы решить за читателя, какая недосказанность неважна, — а именно она и
    попадает потом в отчёт утверждением.
    """
    язык = lang(lang_)
    палитра = _тема(theme)
    исходники = _исходники(sources)
    вход = _точка_входа(исходники, entry)
    соседи = [{"filename": имя, "code": код}
              for n, (имя, код) in enumerate(исходники) if n != вход]
    граф = objektis.extract_objects(исходники[вход][1], _ДЛЯ_OBJEKTIS[язык],
                                    files=соседи)
    notices = tuple(_заметка(текст) for текст in граф.notes)
    if граф.is_empty():
        raise DiagramError(NO_OBJECTS,
                           "No instances of user classes were traced",
                           notices=notices)
    return DiagramResult(xml=objektis.build_xml(граф, палитра, cfg),
                         notices=notices,
                         items=tuple(i.name for i in граф.instances))


def _точка_входа(исходники: list[tuple[str, str]], entry) -> int:
    """Номер исходника, который считается точкой входа. По умолчанию первый."""
    if entry is None:
        return 0
    if isinstance(entry, int) and not isinstance(entry, bool):
        if 0 <= entry < len(исходники):
            return entry
        raise DiagramError(INVALID_SOURCE, f"entry {entry} is out of range")
    for n, (имя, _) in enumerate(исходники):
        if имя == str(entry):
            return n
    raise DiagramError(INVALID_SOURCE, f"entry {str(entry)!r} is not among sources")


def _заметка(текст: str) -> Notice:
    """Строка-заметка `objektis` → общая форма замечания.

    Уровень `warning`, а не `info`: заметка говорит, чего трассировка не поняла,
    то есть схема построена с изъяном, видимым человеку, — ровно то, что этот
    уровень и означает.
    """
    return Notice(module="objektis", level="warning", code="trace_note",
                  message=str(текст))


__all__ = ["DiagramResult", "DiagramError", "flowchart", "class_diagram",
           "object_diagram", "flowchart_modes", "uml_themes", "languages",
           "lang", "mode", "ПСЕВДОНИМЫ_РЕЖИМОВ",
           "LANGS", "UNKNOWN_LANG", "UNKNOWN_MODE", "UNKNOWN_THEME",
           "INVALID_SOURCE", "NO_CLASSES", "NO_OBJECTS"]
