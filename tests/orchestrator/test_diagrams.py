"""
Фасад схем: одна дверь к `fragmos` и `uml_generator` на весь проект.

Проверяется не «схема нарисовалась» — это дело тестов самих строителей
(`tests/fragmos`, `tests/uml_generator`), — а то, ради чего фасад заведён:

* перечни (языки, режимы, палитры) спрашиваются у строителей, а не пишутся
  вторым списком, который разойдётся с первым;
* язык называется одним словом на весь проект, а чужие имена принимаются;
* отказ разбираемый: у него есть код, и по коду видно, чья это беда —
  запроса (не тот язык, не тот режим) или исходника (не разобралось);
* предупреждение одно на всех — `kyotsu.Notice`, включая заметки трассировки,
  которые `objektis` отдаёт строками;
* знание «как позвать fragmos» осталось в одном месте: инструменты агента
  строителей больше не называют.

Сети здесь нет и не нужно: схемы строятся разбором, без модели.
"""
from __future__ import annotations

import io
import re
import tokenize
from pathlib import Path

import pytest

import orchestrator
from kyotsu import Notice
from orchestrator import diagrams

ЦИКЛ = ("def сумма(n):\n"
        "    s = 0\n"
        "    for i in range(n):\n"
        "        s = s + i\n"
        "    return s\n")

КЛАССЫ = ("class Сортировщик:\n"
          "    def __init__(self, данные):\n"
          "        self.данные = данные\n"
          "    def отсортировать(self):\n"
          "        return sorted(self.данные)\n")

ОБЪЕКТЫ = ("class Задача:\n"
           "    def __init__(self, имя):\n"
           "        self.имя = имя\n"
           "\n"
           "первая = Задача(\"написать\")\n")

# Точка входа и соседний файл: класс объявлен во втором, экземпляр создаётся в
# первом. На этой паре видно и то, что соседи разбираются, и то, что вход не
# разбирается дважды.
ВХОД = "д = Двигатель(120)\n"
БИБЛИОТЕКА = ("class Двигатель:\n"
              "    def __init__(self, мощность):\n"
              "        self.мощность = мощность\n")


# ── перечни ──────────────────────────────────────────────────────────────────

def test_языки_одним_словом_и_в_постоянном_порядке():
    """Порядок уезжает в выпадающий список на сайте, поэтому он закреплён."""
    assert diagrams.languages() == ("py", "cs", "cpp")


def test_режимы_спрашиваются_у_строителя_а_не_пишутся_списком():
    """Свой список разошёлся бы с `modes.yaml` на первом же новом режиме — и
    человек получал бы отказ на режим, который строитель прекрасно рисует.

    Единственное, чего в перечне нет, — псевдонимы (наружу уходит только
    `gost_19_701_90`): два имени одного режима — это два пункта
    в выпадающем списке, между которыми выбирать нечего.
    """
    from fragmos.builder.modes import list_modes

    режимы = diagrams.flowchart_modes()
    ожидаем = [m for m in list_modes()
               if m not in diagrams.ПСЕВДОНИМЫ_РЕЖИМОВ]
    assert [m["id"] for m in режимы] == ожидаем
    assert all(m["description"] for m in режимы), "режим без описания нечем выбрать"


def test_псевдоним_режима_принимается_но_наружу_не_показывается():
    """`loopLimit` лежит в чужих настройках и ссылках: отказ по нему сломал бы
    их ради вида перечня. Приводится он к каноническому имени в одном месте."""
    assert "loopLimit" not in [m["id"] for m in diagrams.flowchart_modes()]
    assert diagrams.mode("loopLimit") == "gost_19_701_90"
    assert diagrams.mode("gost_19_701_90") == "gost_19_701_90"
    assert diagrams.mode(None) == "default"
    with pytest.raises(diagrams.DiagramError):
        diagrams.mode("красивый")


def test_палитры_спрашиваются_у_строителя_и_css_среди_них():
    """`css` в yaml не лежит, но выбирается наравне: перечень обязан её назвать,
    иначе она есть и работает, а выбрать её нельзя."""
    from uml_generator.styles import list_themes

    assert diagrams.uml_themes() == list_themes()
    assert {"dark", "light", "css"} <= set(diagrams.uml_themes())


@pytest.mark.parametrize("чужое, наше", [
    ("python", "py"), ("PY", "py"), ("csharp", "cs"), ("c#", "cs"),
    ("cpp", "cpp"), ("c++", "cpp"), (" Python3 ", "py"),
])
def test_чужие_имена_языка_приводятся_к_нашему(чужое, наше):
    """Инструменты агента объявляют модели `python`/`csharp`/`cpp` и присылают
    их дословно: ломать их ради красоты входа незачем."""
    assert diagrams.lang(чужое) == наше


def test_неизвестный_язык_отказ_с_кодом_а_не_KeyError():
    with pytest.raises(diagrams.DiagramError) as беда:
        diagrams.flowchart(ЦИКЛ, "java")
    assert беда.value.code == diagrams.UNKNOWN_LANG
    # Текст английский: его читает клиент службы.
    assert беда.value.message.isascii()


def test_неизвестный_режим_отказ_и_перечень_в_тексте():
    with pytest.raises(diagrams.DiagramError) as беда:
        diagrams.flowchart(ЦИКЛ, "py", mode="красивый")
    assert беда.value.code == diagrams.UNKNOWN_MODE
    assert "default" in беда.value.message


def test_неизвестная_палитра_отказ():
    with pytest.raises(diagrams.DiagramError) as беда:
        diagrams.class_diagram([("a.py", КЛАССЫ)], "py", theme="малиновая")
    assert беда.value.code == diagrams.UNKNOWN_THEME


# ── блок-схема ───────────────────────────────────────────────────────────────

def test_блок_схема_отдаётся_строкой_drawio():
    """Строкой, а не путём: вызывающему нужен XML, а на диск его кладёт тот, у
    кого есть хранилище."""
    готово = diagrams.flowchart(ЦИКЛ, "py")
    assert "<mxfile" in готово.xml and "mxGraphModel" in готово.xml
    assert готово.notices == () and готово.items == ()


def test_режим_меняет_картинку_а_не_только_ответ():
    """Иначе выбор режима — украшение: два режима обязаны рисовать по-разному."""
    обычный = diagrams.flowchart(ЦИКЛ, "py", mode="default").xml
    гост = diagrams.flowchart(ЦИКЛ, "py", mode="loopLimit").xml
    assert обычный != гост


def test_одинаковый_вход_даёт_одинаковый_xml():
    """Иначе схему нельзя ни кэшировать, ни адресовать хешем содержимого — а
    артефакт проекта адресуется именно так."""
    assert diagrams.flowchart(ЦИКЛ, "py").xml == diagrams.flowchart(ЦИКЛ, "py").xml


def test_пустой_исходник_отказ_а_не_пустая_схема():
    """Пустой лист, вставленный в отчёт схемой, выглядит как поломка сборки."""
    with pytest.raises(diagrams.DiagramError) as беда:
        diagrams.flowchart("   \n\n", "py")
    assert беда.value.code == diagrams.INVALID_SOURCE


def test_не_тот_язык_отказ_с_настоящей_причиной_внутри():
    """`cause` нужен вызывающему, чтобы отличить «не тот язык» от всего
    остального; наружу он при этом не уезжает — это решает служба."""
    with pytest.raises(diagrams.DiagramError) as беда:
        diagrams.flowchart(ЦИКЛ, "cpp")
    assert беда.value.code == diagrams.INVALID_SOURCE
    assert isinstance(беда.value.cause, SyntaxError)


# ── диаграмма классов ────────────────────────────────────────────────────────

def test_классы_собираются_со_всех_исходников():
    """Связи между классами из разных файлов иначе просто не нашлись бы."""
    готово = diagrams.class_diagram(
        [("a.py", КЛАССЫ), ("b.py", "class Второй:\n    pass\n")], "py")
    assert готово.items == ("Сортировщик", "Второй")
    assert "mxGraphModel" in готово.xml


def test_исходники_принимаются_и_парами_и_словарями():
    """Служба присылает словари, инструменты агента — пары; форма входа не
    должна быть поводом писать вторую функцию."""
    парами = diagrams.class_diagram([("a.py", КЛАССЫ)], "py")
    словарями = diagrams.class_diagram([{"name": "a.py", "source": КЛАССЫ}], "py")
    assert парами.xml == словарями.xml


def test_нет_классов_отказ_а_не_лист_нет_классов():
    with pytest.raises(diagrams.DiagramError) as беда:
        diagrams.class_diagram([("a.py", "x = 1\n")], "py")
    assert беда.value.code == diagrams.NO_CLASSES


def test_имя_исходника_называется_в_отказе(monkeypatch):
    """Из восьми файлов по номеру не покажешь, какой не разобрался.

    Падение разбора подделано намеренно: tree-sitter терпелив и на битом входе
    отдаёт то, что понял, а не исключение. Проверяется здесь не «когда он
    падает», а что фасад делает с падением, когда оно всё-таки случается.
    """
    import uml_generator

    настоящий = uml_generator.extract_py

    def падает(текст):
        if "Сортировщик" in текст:
            return настоящий(текст)
        raise RuntimeError("грамматика кончилась")

    monkeypatch.setattr(uml_generator, "extract_py", падает)
    with pytest.raises(diagrams.DiagramError) as беда:
        diagrams.class_diagram([("a.py", КЛАССЫ), ("плохой.py", "???")], "py")
    assert беда.value.code == diagrams.INVALID_SOURCE
    assert беда.value.where == "плохой.py"
    assert isinstance(беда.value.cause, RuntimeError)


# ── диаграмма объектов ───────────────────────────────────────────────────────

def test_объекты_это_снимок_экземпляров_а_не_типов():
    готово = diagrams.object_diagram([("a.py", ОБЪЕКТЫ)], "py")
    assert готово.items == ("первая",)
    assert "mxGraphModel" in готово.xml


def test_соседний_исходник_виден_а_вход_не_разбирается_дважды():
    """Класс объявлен во втором исходнике, экземпляр создаётся в первом: без
    соседа схема была бы пуста, а вход, поданный дважды, дал бы второй
    экземпляр, которого в коде нет."""
    готово = diagrams.object_diagram(
        [("вход.py", ВХОД), ("двигатель.py", БИБЛИОТЕКА)], "py")
    assert готово.items == ("д",)


def test_точка_входа_называется_именем_или_номером():
    """Порядок исходников значащий, но переставлять их ради службы незачем."""
    пара = [("двигатель.py", БИБЛИОТЕКА), ("вход.py", ВХОД)]
    по_имени = diagrams.object_diagram(пара, "py", entry="вход.py")
    по_номеру = diagrams.object_diagram(пара, "py", entry=1)
    assert по_имени.items == по_номеру.items == ("д",)


def test_точка_входа_мимо_списка_отказ():
    with pytest.raises(diagrams.DiagramError) as беда:
        diagrams.object_diagram([("a.py", ОБЪЕКТЫ)], "py", entry="чужой.py")
    assert беда.value.code == diagrams.INVALID_SOURCE


def test_заметки_трассировки_приезжают_общей_формой():
    """`objektis` отдаёт их строками; второй вид предупреждения означал бы
    второй разбор в интерфейсе — ровно то, ради чего `kyotsu.Notice` и есть."""
    with pytest.raises(diagrams.DiagramError) as беда:
        diagrams.object_diagram([("a.py", "class A:\n    pass\n")], "py")
    assert беда.value.code == diagrams.NO_OBJECTS
    assert беда.value.notices, "немой отказ заставляет чинить наугад"
    for заметка in беда.value.notices:
        assert isinstance(заметка, Notice) and заметка.module == "objektis"


def test_заметки_не_теряются_и_на_удачной_схеме():
    """Если трассировка чего-то не поняла, это правда и про построенную схему —
    и именно она попадает в отчёт утверждением."""
    from uml_generator import objektis

    правда = objektis.extract_objects(ОБЪЕКТЫ, "python")
    готово = diagrams.object_diagram([("a.py", ОБЪЕКТЫ)], "py")
    assert [n.message for n in готово.notices] == list(правда.notes)


# ── одна дверь: знание не размазано ──────────────────────────────────────────

def _код(path: Path) -> str:
    """Исходник без строк и комментариев — как в `tests/kyotsu/test_border.py`."""
    out = []
    for tok in tokenize.generate_tokens(io.StringIO(path.read_text("utf-8")).readline):
        if tok.type in (tokenize.COMMENT, tokenize.STRING):
            continue
        out.append("\n" if tok.type in (tokenize.NL, tokenize.NEWLINE) else tok.string)
    return "\n".join(out)


def test_строителей_схем_зовёт_только_фасад():
    """Второй вызывающий `fragmos` — это второй набор умолчаний.

    До 2.0.0a5.1 их звал `tools.py`, и служба, которой схемы понадобились
    наружу, переписала бы те же двадцать строк у себя. Теперь дверь одна, и
    проверяется это по коду, а не по обещанию в докстроке.
    """
    корень = Path(orchestrator.__file__).parent
    свои = re.compile(r"^\s*(?:import (?:fragmos|uml_generator)\b"
                      r"|from (?:fragmos|uml_generator)[.\s])", re.MULTILINE)
    виновные = [p.name for p in sorted(корень.rglob("*.py"))
                if p.name != "diagrams.py" and свои.search(_код(p))]
    assert not виновные, виновные


def test_фасад_виден_из_пакета_одним_именем():
    """Служба зовёт его как `orchestrator.diagrams.flowchart` — этот путь и есть
    договор, а не подробность раскладки файлов."""
    assert orchestrator.diagrams is diagrams
    assert orchestrator.DiagramError is diagrams.DiagramError
    assert orchestrator.DiagramResult is diagrams.DiagramResult
