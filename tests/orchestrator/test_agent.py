"""
Уровень 3: агент с инструментами.

Проверяется не то, что «петля прокрутилась», а то, ради чего уровень устроен
поверх готовой механики: значение от инструмента проходит тот же валидатор, что
правка человека; правку человека прогон не трогает; материал адресуется
идентификатором, и путь вместо него — отказ; беда инструмента возвращается
модели так, что она чинится следующим ходом; потолок ходов и лимит
пользователя останавливают прогон, а всё, за что уже заплачено, остаётся в
проекте.

Модель подделана, сети нет (`conftest`). Ответ модели с вызовом инструмента —
это кусок `tool_call` в том же потоке, каким приходит текст: подделан по-прежнему
только провод, а разбор вызовов, история ходов, потолки и журнал — настоящие.
"""
from __future__ import annotations

import json

import pytest

import fragmos
import llm
from llm import usage as usage_mod
from llm.model import Chunk, ToolCall, Usage
from uml_generator import objektis

import orchestrator
from orchestrator import tools as tools_mod

from .conftest import LOOSE, journal_lines, script, set_prompts

ЦЕЛЬ = {"type": "markdown", "text": "Цель работы — сравнить алгоритмы сортировки."}

КЛАССЫ = (
    "class Сортировщик:\n"
    "    def __init__(self, данные):\n"
    "        self.данные = данные\n"
    "    def отсортировать(self):\n"
    "        return sorted(self.данные)\n"
)

# Классы и экземпляры: диаграмма объектов строится не по типам, а по снимку
# конкретных объектов, поэтому в исходнике обязано что-то создаваться.
ОБЪЕКТЫ = (
    "class Задача:\n"
    "    def __init__(self, имя):\n"
    "        self.имя = имя\n"
    "        self.владелец = None\n"
    "\n"
    "class Список:\n"
    "    def __init__(self):\n"
    "        self.задачи = []\n"
    "    def добавить(self, з):\n"
    "        self.задачи.append(з)\n"
    "\n"
    "список = Список()\n"
    "первая = Задача(\"написать\")\n"
    "список.добавить(первая)\n"
)

# C# нужен там, где проверяется склейка нескольких материалов: `cs_static`
# склеивает вход с соседями в один текст — и именно на этой склейке видно,
# разобрали вход один раз или два. С 2.0.0a4.2 соседей видит и `py_static`,
# но по-своему: у соседей берутся только объявления (PY_ВХОД / PY_БИБЛИОТЕКА).
CS_ВЕРХНИЙ_УРОВЕНЬ = (
    "class Двигатель { public int Мощность; "
    "public Двигатель(int м) { Мощность = м; } }\n"
    "class Машина { public Двигатель Д; public Машина(Двигатель д) { Д = д; } }\n"
    "Машина м = new Машина(new Двигатель(120));\n"
)
CS_ГЛАВНЫЙ = ("class Программа { static void Main() { "
              "Двигатель д = new Двигатель(120); } }\n")
CS_БИБЛИОТЕКА = ("class Двигатель { public int Мощность; "
                 "public Двигатель(int м) { Мощность = м; } }\n")

# Python: класс в одном материале, экземпляр — в другом. Обычная раскладка
# студенческой работы, до 2.0.0a4.2 дававшая пустую схему без объяснений.
PY_ВХОД = "д = Двигатель(120)\n"
PY_БИБЛИОТЕКА = ("class Двигатель:\n"
                 "    def __init__(self, мощность):\n"
                 "        self.мощность = мощность\n")


# ── оснастка ─────────────────────────────────────────────────────────────────

def turn(*calls, text: str = "", stop: str = llm.Stop.TOOL_USE):
    """Один ход модели: текст и вызовы инструментов. `calls` — пары (имя, аргументы).

    У вызова без аргументов `raw_arguments` пустые, а не `"{}"`, и это не
    придирка к подделке: сегодня петля считает `"{}"` при пустом разборе битыми
    аргументами и до инструмента не доводит (`llm/loop.py:252`). Пока это не
    поправлено в `llm`, инструменты без аргументов работают только у
    поставщика, который поле аргументов не присылает вовсе.
    """
    tail = [Chunk(kind="tool_call",
                  tool_call=ToolCall(id=f"c{i}", name=name, arguments=dict(args),
                                     raw_arguments=(json.dumps(args, ensure_ascii=False)
                                                    if args else "")))
            for i, (name, args) in enumerate(calls)]
    return script(text, stop=stop, tail=tail)


def done(text: str = "готово"):
    """Последний ход: инструментов не зовём — петля на этом и заканчивается."""
    return script(text, stop=llm.Stop.END_TURN)


@pytest.fixture
def agent_endpoint(endpoint):
    """Тот же endpoint, что у остальных тестов, но с объявленными инструментами.

    Без `tools=True` петля отказывает до первого вызова (`llm.run_tools`), и
    проверялся бы этот отказ, а не уровень 3.
    """
    def register(*scripts, step: str = LOOSE, **overrides):
        overrides.setdefault("declared",
                             llm.Declared(structured_output=step, tools=True))
        return endpoint(*scripts, step=step, **overrides)
    return register


def материал(project) -> str:
    return project.store().list()[0].id


def положить(project, текст: str, имя: str) -> str:
    """Материал в хранилище проекта — возвращается идентификатор, а не путь.

    Тесты адресуют материал ровно тем же, чем адресует его модель: если бы
    здесь ходил путь, проверка «инструмент путей не принимает» опиралась бы на
    то, чего в жизни не бывает.
    """
    return project.store().add(текст.encode("utf-8"), name=имя, do_ocr=False).id


def ответы(backend, шаг: int) -> list:
    """Ответы инструментов, какими их увидела модель на шаге `шаг` (с 0).

    Читаются из истории следующего запроса: другого способа увидеть то, что
    уехало модели, нет, и именно это надо проверять — «ошибка возвращена так,
    что модель может исправиться» проверяется по её экземпляру ответа, а не по
    нашему объекту.
    """
    return [item for item in backend.requests[шаг + 1].history
            if item.get("role") == "tool_result"]


# ── цепочка: инструменты складываются в работу ───────────────────────────────

def test_цепочка_инструментов_доводит_схему_до_значения_тега(project, agent_endpoint):
    # Тег «таблица» объявляем схемой: уровень 3 и нужен ради того, чего нельзя
    # написать текстом.
    set_prompts(project, таблица={"type": "diagram"})
    mid = материал(project)
    исходник = project.store().read(mid).text
    art = orchestrator.artifact_id(
        fragmos.generate_xml(исходник, "python").encode("utf-8"))

    ep, backend = agent_endpoint(
        turn(("list_materials", {})),
        turn(("read_material", {"id": mid})),
        turn(("make_flowchart", {"id": mid, "language": "python"})),
        turn(("set_tag", {"key": "таблица",
                          "value": {"type": "diagram", "artifact": art}}),
             ("set_tag", {"key": "цель", "value": ЦЕЛЬ})),
        turn(("preview", {})),
        done("схема построена, цель написана"))
    out = orchestrator.fill_agent(project, endpoint=ep)

    assert out.ok and out.outcome == "done"
    assert sorted(out.filled) == ["таблица", "цель"]
    assert out.text == "схема построена, цель написана"
    # Опись зовётся list_materials и отдаёт материалы, а не файлы: слово «files»
    # ушло из ответа вместе с прежним именем инструмента, потому что уводило
    # модель к файловой системе, которой у неё нет.
    опись = json.loads(ответы(backend, 0)[0]["content"])
    assert [m["id"] for m in опись["materials"]] == [mid]
    # Значение доехало до проекта той же дорогой, что у уровней 1 и 2.
    assert project.value("таблица") == {"type": "diagram", "artifact": art}
    версия = project.head_version("таблица")
    assert версия.source == "agent" and версия.run == out.run.id
    assert len(версия.prompt_hash) == 64
    # Артефакт схемы лежит в проекте и достаётся тем же resolve_artifact,
    # который получит сборщик отчёта.
    assert project.resolve_artifact(art).startswith(b"<mxfile")
    # Список инструментов постоянен на весь прогон: он стоит в кэшируемом
    # префиксе, и меняться между ходами ему нельзя.
    for request in backend.requests:
        assert tuple(t.name for t in request.tools) == tools_mod.TOOL_NAMES
    # Ходы прогона записаны на диск, а не только в память.
    шаги = [s["tool"] for s in project.run(out.run.id).steps]
    assert шаги == ["list_materials", "read_material", "make_flowchart",
                    "set_tag", "set_tag", "preview"]


def test_чего_не_вошло_в_схему_доезжает_до_отчёта(project, agent_endpoint):
    """«В схему не вошло: goto case» — от `fragmos` до проверки перед сборкой.

    Три места, и все три нужны разным: ответ инструмента — модели (ей решать,
    ставить ли такую схему), `problems` прогона — человеку сейчас, замечание
    рядом с артефактом — человеку потом, когда он смотрит собранный отчёт и
    прогон давно кончился.

    `hokoku` про `fragmos` при этом по-прежнему не знает: замечание проводит
    служба. Проверять надо именно это — что канал один, а не что пакеты
    познакомились.
    """
    set_prompts(project, таблица={"type": "diagram"})
    mid = положить(project, "class P { void M(int x) { switch (x) { "
                            "case 1: A(); goto case 7; case 2: B(); break; } } }\n",
                   "P.cs")
    замечания: list = []
    art = orchestrator.artifact_id(fragmos.generate_xml(
        project.store().read(mid).text, "csharp", warnings=замечания).encode("utf-8"))
    assert [n.code for n in замечания] == ["goto_case_unresolved"]   # есть о чём говорить

    ep, backend = agent_endpoint(
        turn(("make_flowchart", {"id": mid, "language": "csharp"})),
        turn(("set_tag", {"key": "таблица",
                          "value": {"type": "diagram", "artifact": art}})),
        done())
    out = orchestrator.fill_agent(project, endpoint=ep)

    assert out.ok
    # 1. Модель увидела, чего в схеме нет, — общей формой, а не прозой в note.
    ответ = json.loads(ответы(backend, 0)[0]["content"])
    assert [w["code"] for w in ответ["warnings"]] == ["goto_case_unresolved"]
    assert ответ["warnings"][0]["module"] == "fragmos"
    # 2. Человек видит это в замечаниях прогона.
    assert any(p.code == "goto_case_unresolved" for p in out.problems)
    # 3. И в полной проверке перед сборкой — уже с тегом, в котором схема стоит.
    проблемы = orchestrator.check(project)
    схема = [p for p in проблемы if p.code == "goto_case_unresolved"]
    assert len(схема) == 1 and схема[0].key == "таблица"
    assert "goto case 7" in схема[0].message


def test_схема_без_пропусков_замечаний_не_добавляет(project, agent_endpoint):
    """Обратная половина: замечание, которое стоит на всякой схеме, не значит
    ничего, а перед сборкой ещё и прячет настоящие."""
    set_prompts(project, таблица={"type": "diagram"})
    mid = материал(project)
    art = orchestrator.artifact_id(
        fragmos.generate_xml(project.store().read(mid).text, "python").encode("utf-8"))

    ep, _ = agent_endpoint(
        turn(("make_flowchart", {"id": mid, "language": "python"})),
        turn(("set_tag", {"key": "таблица",
                          "value": {"type": "diagram", "artifact": art}})),
        done())
    out = orchestrator.fill_agent(project, endpoint=ep)

    assert out.ok
    assert [p for p in out.problems if p.module == "fragmos"] == []
    assert project.artifact_notices(art) == []
    assert [p for p in orchestrator.check(project) if p.module == "fragmos"] == []


def test_расход_ложится_в_журнал_по_ходам(project, agent_endpoint):
    ep, _ = agent_endpoint(turn(("preview", {})), turn(("preview", {})), done())
    out = orchestrator.fill_agent(project, endpoint=ep)

    записи = journal_lines(project)
    # Инструменты денег не стоят: цена прогона — это ходы, и каждый ход обязан
    # быть отдельной записью, иначе «что съело бюджет» не расследуется.
    assert len(записи) == out.steps == 3
    assert [z["step"] for z in записи] == [1, 2, 3]
    assert all(z["run"] == out.run.id and z["level"] == 3 for z in записи)
    assert out.usage["input"] == 300


def test_на_endpoint_без_операторского_канала_значение_помечено_проверить(
        project, agent_endpoint):
    # Заглушка владельца 2026-08-31: прогон разрешён, но каждое значение
    # помечено. Проверяем, что пометка доехала до версии, а не осталась словами.
    assert tools_mod.WITHOUT_OPERATOR_CHANNEL == "flag"
    ep, _ = agent_endpoint(turn(("set_tag", {"key": "цель", "value": ЦЕЛЬ})), done())
    out = orchestrator.fill_agent(project, endpoint=ep)

    assert out.ok
    assert tools_mod.UNVERIFIED_FLAG in project.head_version("цель").flags
    assert any(p.code == "no_operator_channel" for p in out.problems)


def test_переключатель_allow_пускает_без_пометки(project, agent_endpoint,
                                                 monkeypatch):
    """Три режима заглушки обязаны различаться делом, а не только словом."""
    monkeypatch.setattr(tools_mod, "WITHOUT_OPERATOR_CHANNEL", "allow")
    ep, _ = agent_endpoint(turn(("set_tag", {"key": "цель", "value": ЦЕЛЬ})), done())
    out = orchestrator.fill_agent(project, endpoint=ep)

    assert out.ok and out.filled == ["цель"]
    assert project.head_version("цель").flags == []
    assert not any(p.code == "no_operator_channel" for p in out.problems)


def test_опечатка_в_переключателе_не_проходит_молча(project, agent_endpoint,
                                                    monkeypatch):
    # Значение не из трёх сработало бы как молчаливое «пускать» — то есть
    # заглушка перестала бы быть одним переключателем.
    monkeypatch.setattr(tools_mod, "WITHOUT_OPERATOR_CHANNEL", "flg")
    ep, backend = agent_endpoint(done())
    with pytest.raises(orchestrator.OrchestratorError,
                       match="WITHOUT_OPERATOR_CHANNEL"):
        orchestrator.fill_agent(project, endpoint=ep)
    assert backend.requests == []


def test_переключатель_deny_не_пускает_прогон_вовсе(project, agent_endpoint,
                                                    monkeypatch):
    """Отказ до первого вызова: после пятого хода он стоил бы денег за пять ходов."""
    monkeypatch.setattr(tools_mod, "WITHOUT_OPERATOR_CHANNEL", "deny")
    ep, backend = agent_endpoint(done())
    with pytest.raises(orchestrator.OrchestratorError, match="операторского канала"):
        orchestrator.fill_agent(project, endpoint=ep)
    assert backend.requests == [] and journal_lines(project) == []


# ── set_tag: тот же валидатор и то же уважение к правке человека ─────────────

def test_set_tag_не_обходит_валидатор(project, agent_endpoint):
    # Тип значения не тот, что объявил манифест. Отдельного доверенного пути для
    # модели нет: ругается тот же hokoku.validate, что и на правке человека.
    ep, backend = agent_endpoint(
        turn(("set_tag", {"key": "цель",
                          "value": {"type": "table", "rows": [["а", "б"]]}})),
        done())
    out = orchestrator.fill_agent(project, endpoint=ep)

    assert project.value("цель") is None and project.versions("цель") == []
    ответ = ответы(backend, 0)[0]
    assert ответ["is_error"] is True
    разбор = json.loads(ответ["content"])
    assert разбор["error"] == "rejected"
    assert any("markdown" in m for m in разбор["problems"])
    assert any(p.code == "type_mismatch" for p in out.problems)


def test_set_tag_не_принимает_невыразимое_значение(project, agent_endpoint):
    ep, backend = agent_endpoint(
        turn(("set_tag", {"key": "цель",
                          "value": {"type": "markdown", "text": "текст",
                                    "выдумка": 1}})),
        done())
    orchestrator.fill_agent(project, endpoint=ep)

    assert project.versions("цель") == []
    разбор = json.loads(ответы(backend, 0)[0]["content"])
    assert разбор["error"] == "rejected"
    assert any("выдумка" in m for m in разбор["problems"])


def test_set_tag_не_затирает_правку_человека(project, agent_endpoint):
    project.set_value("цель", {"type": "markdown", "text": "написано студентом"},
                      source="manual")
    ep, backend = agent_endpoint(
        turn(("set_tag", {"key": "цель", "value": ЦЕЛЬ})), done())
    out = orchestrator.fill_agent(project, endpoint=ep)

    # Версия одна и та же, чужая: прогон её не трогал.
    assert len(project.versions("цель")) == 1
    assert project.value("цель")["text"] == "написано студентом"
    разбор = json.loads(ответы(backend, 0)[0]["content"])
    assert разбор["error"] == "unknown_key" and "цель" not in разбор["known"]
    assert any(p.code == "kept" and p.key == "цель" for p in out.problems)


def test_все_теги_за_человеком_прогон_не_начинается(project, agent_endpoint):
    for key in ("цель", "введение", "таблица"):
        project.set_value(key, {"type": "markdown", "text": "моё"}, source="manual")
    ep, backend = agent_endpoint(done())
    with pytest.raises(orchestrator.OrchestratorError, match="overwrite=True"):
        orchestrator.fill_agent(project, endpoint=ep)
    assert backend.requests == []


# ── read_material: идентификатор, а не путь; кусок, а не всё ─────────────────

def test_read_material_не_принимает_путь_и_незнакомый_идентификатор(
        project, agent_endpoint):
    ep, backend = agent_endpoint(
        turn(("read_material", {"id": "../../etc/passwd"}),
             ("read_material", {"id": "0123456789abcdef"})),
        done())
    orchestrator.fill_agent(project, endpoint=ep)

    путь, чужой = ответы(backend, 0)
    assert путь["is_error"] and json.loads(путь["content"])["error"] == "bad_id"
    # Проверка формы стоит ДО хранилища: Store складывает из идентификатора путь.
    assert "Пути не принимаются" in json.loads(путь["content"])["message"]
    разбор = json.loads(чужой["content"])
    assert чужой["is_error"] and разбор["error"] == "unknown_id"
    # Модель должна суметь исправиться: известные идентификаторы названы.
    assert разбор["known"] == [материал(project)]


def test_read_material_режет_кусок_и_говорит_об_этом(project, agent_endpoint,
                                                     monkeypatch):
    # Материал длиннее потолка. Потолок трогаем через модуль: число одно, и
    # проверять надо его, а не выдуманную в тесте копию.
    monkeypatch.setattr(tools_mod, "READ_CHARS", 20)
    mid = материал(project)
    ep, backend = agent_endpoint(turn(("read_material", {"id": mid})), done())
    orchestrator.fill_agent(project, endpoint=ep)

    разбор = json.loads(ответы(backend, 0)[0]["content"])
    assert разбор["truncated"] is True and len(разбор["text"]) == 20
    # По total и границам куска модель просит продолжение сама.
    assert разбор["total"] == project.store().get(mid).count
    assert разбор["from"] == 1 and разбор["anchor"]


# ── беда инструмента лечится следующим ходом ─────────────────────────────────

def test_модель_чинится_по_ответу_инструмента(project, agent_endpoint):
    ep, backend = agent_endpoint(
        turn(("set_tag", {"key": "цел", "value": ЦЕЛЬ})),        # опечатка в ключе
        turn(("set_tag", {"key": "цель", "value": ЦЕЛЬ})),       # поправилась
        done())
    out = orchestrator.fill_agent(project, endpoint=ep)

    разбор = json.loads(ответы(backend, 0)[0]["content"])
    assert разбор["error"] == "unknown_key" and "похоже на" in разбор["message"]
    assert разбор["known"] == ["введение", "таблица", "цель"]
    # Прогон не упал на опечатке — значение поставлено следующим ходом.
    assert out.ok and out.filled == ["цель"]
    assert project.value("цель")["text"].startswith("Цель работы")


def test_несуществующий_инструмент_не_роняет_прогон(project, agent_endpoint):
    ep, backend = agent_endpoint(turn(("write_file", {"path": "/etc/passwd"})), done())
    out = orchestrator.fill_agent(project, endpoint=ep)

    разбор = json.loads(ответы(backend, 0)[0]["content"])
    assert разбор["error"] == "unknown_tool"
    assert разбор["known"] == list(tools_mod.TOOL_NAMES)
    assert out.outcome == "done"


def test_схема_классов_отказывает_понятно_и_строит_когда_есть_из_чего(
        project, agent_endpoint):
    mid = project.store().add(КЛАССЫ.encode("utf-8"), name="классы.py",
                              do_ocr=False).id
    пустой = материал(project)
    ep, backend = agent_endpoint(
        turn(("make_class_diagram", {"ids": [пустой], "language": "python"}),
             ("make_class_diagram", {"ids": [mid], "language": "cpp"}),
             ("make_class_diagram", {"ids": [mid], "language": "python"})),
        done())
    orchestrator.fill_agent(project, endpoint=ep)

    без_классов, не_тот_язык, годный = ответы(backend, 0)
    assert json.loads(без_классов["content"])["error"] == "no_classes"
    assert не_тот_язык["is_error"] is True
    разбор = json.loads(годный["content"])
    assert разбор["classes"] == ["Сортировщик"]
    assert b"mxGraphModel" in project.resolve_artifact(разбор["artifact"])


# ── make_object_diagram: снимок экземпляров, и ни одного пути ────────────────

def test_схема_объектов_доводится_до_значения_тега(project, agent_endpoint):
    """Нормальный путь: трассировка → артефакт в хранилище → значение тега.

    Идентификатор считается здесь тем же `artifact_id`, каким его считает
    проект. Вернуть модели что-то другое инструмент не может незаметно: тогда
    `set_tag` следующим ходом не пройдёт, и видно это будет не по строке
    ответа, а по пустому тегу.
    """
    set_prompts(project, таблица={"type": "diagram"})
    mid = положить(project, ОБЪЕКТЫ, "объекты.py")
    текст = project.store().read(mid).text
    art = orchestrator.artifact_id(
        objektis.build_xml(objektis.extract_objects(текст, "python"),
                           "dark").encode("utf-8"))

    ep, backend = agent_endpoint(
        turn(("make_object_diagram", {"ids": [mid], "language": "python"})),
        turn(("set_tag", {"key": "таблица",
                          "value": {"type": "diagram", "artifact": art}})),
        done("схема объектов построена"))
    out = orchestrator.fill_agent(project, endpoint=ep)

    разбор = json.loads(ответы(backend, 0)[0]["content"])
    assert разбор["artifact"] == art
    # Экземпляры названы так, как их зовёт студент: по этим именам модель и
    # понимает, что схема про его код, а не про чужой.
    assert разбор["objects"] == ["список", "первая"]
    assert разбор["notes"] == []
    # Артефакт лежит в проекте и достаётся тем же resolve_artifact, который
    # получит сборщик отчёта.
    assert b"mxGraphModel" in project.resolve_artifact(art)
    assert out.ok and out.filled == ["таблица"]
    assert project.value("таблица") == {"type": "diagram", "artifact": art}
    assert [s["tool"] for s in project.run(out.run.id).steps] == [
        "make_object_diagram", "set_tag"]


def test_схема_объектов_отказывает_понятно_и_ничего_не_кладёт(project,
                                                              agent_endpoint):
    """Шесть бед подряд, все чинимые: прогон не падает ни на одной.

    Ответ разбираемый, и по нему видно, что именно поправить, — иначе модель
    будет чинить наугад, а каждая попытка это ход и деньги.
    """
    mid = положить(project, ОБЪЕКТЫ, "объекты.py")
    пусто = положить(project, "   \n\n", "пусто.py")
    ep, backend = agent_endpoint(
        turn(("make_object_diagram", {"ids": [], "language": "python"}),
             ("make_object_diagram", {"ids": ["материалы/объекты.py"],
                                      "language": "python"}),
             ("make_object_diagram", {"ids": ["0123456789abcdef"],
                                      "language": "python"}),
             ("make_object_diagram", {"ids": [mid], "language": "java"}),
             ("make_object_diagram", {"ids": [mid] * (tools_mod.MAX_SOURCES + 1),
                                      "language": "python"}),
             ("make_object_diagram", {"ids": [пусто], "language": "python"})),
        done())
    out = orchestrator.fill_agent(project, endpoint=ep)

    без_ids, путь, чужой, язык, много, пустой = ответы(backend, 0)
    assert all(о["is_error"] is True
               for о in (без_ids, путь, чужой, язык, много, пустой))
    assert json.loads(без_ids["content"])["error"] == "bad_ids"
    # Путь умирает на входе: `Store` складывает из идентификатора путь, и
    # проверка формы обязана стоять до обращения к хранилищу.
    разбор = json.loads(путь["content"])
    assert разбор["error"] == "bad_id" and "Пути не принимаются" in разбор["message"]
    # Незнакомый идентификатор — с перечнем известных: по нему модель исправится.
    разбор = json.loads(чужой["content"])
    assert разбор["error"] == "unknown_id" and mid in разбор["known"]
    # Язык вне перечня: схема инструмента до слабого поставщика не доезжает,
    # поэтому перечень проверяется ещё и здесь.
    разбор = json.loads(язык["content"])
    assert разбор["error"] == "bad_argument" and "python" in разбор["message"]
    assert json.loads(много["content"])["error"] == "too_many"
    assert json.loads(пустой["content"])["error"] == "empty_source"
    # Ни одного значения и ни одной удачной записи хода: отказ есть отказ.
    assert out.filled == [] and project.value("таблица") is None
    assert [s["ok"] for s in project.run(out.run.id).steps] == [False] * 6


def test_схема_объектов_без_экземпляров_отдаёт_заметки_дословно(project,
                                                                agent_endpoint):
    """Экземпляров нет — отказ с заметками разбора, а не пустая схема в отчёт.

    Заметки едут модели дословно: пересказать их короче значило бы решить за
    неё, какая недосказанность неважна, — а именно она и попадает потом в отчёт
    утверждением.
    """
    mid = положить(project, КЛАССЫ, "классы.py")   # классы есть, экземпляров нет
    текст = project.store().read(mid).text
    ep, backend = agent_endpoint(
        turn(("make_object_diagram", {"ids": [mid], "language": "python"})),
        done())
    orchestrator.fill_agent(project, endpoint=ep)

    разбор = json.loads(ответы(backend, 0)[0]["content"])
    assert разбор["error"] == "no_objects"
    assert разбор["notes"] == list(objektis.extract_objects(текст, "python").notes)
    assert разбор["notes"], "заметка о непонятом обязана быть, иначе отказ немой"


def test_схема_объектов_не_выдумывает_экземпляров_и_видит_соседние_материалы(
        project, agent_endpoint):
    """Точка входа разбирается один раз, а соседние материалы — разбираются.

    Было наоборот: первый материал уезжал и точкой входа, и первым соседом, а
    `cs_static` склеивает вход со всеми соседями в один текст — то есть код
    разбирался дважды. На операторах верхнего уровня это давало лишний
    экземпляр: `new Двигатель(120)` в исходнике один, а на схеме их два.
    Выдуманный объект в отчёте хуже отсутствующей схемы — его не с чем сверить.
    """
    вход = положить(project, CS_ВЕРХНИЙ_УРОВЕНЬ, "программа.cs")
    главный = положить(project, CS_ГЛАВНЫЙ, "главный.cs")
    библиотека = положить(project, CS_БИБЛИОТЕКА, "двигатель.cs")
    ep, backend = agent_endpoint(
        turn(("make_object_diagram", {"ids": [вход], "language": "csharp"}),
             ("make_object_diagram", {"ids": [главный, библиотека],
                                      "language": "csharp"})),
        done())
    orchestrator.fill_agent(project, endpoint=ep)

    один, два = ответы(backend, 0)
    # Ровно то же, что даёт трассировка одного исходника без соседей.
    текст = project.store().read(вход).text
    правда = objektis.extract_objects(текст, "csharp")
    assert json.loads(один["content"])["objects"] == [i.name for i in правда.instances]
    assert json.loads(один["content"])["objects"] == ["м", "двигатель1"]
    # Соседний материал при этом не потерялся: класс объявлен во втором, а
    # экземпляр создаётся в первом, и без второго схема была бы пуста.
    assert json.loads(два["content"])["objects"] == ["д"]


def test_схема_объектов_на_python_видит_соседний_материал(project, agent_endpoint):
    """Класс во втором материале, экземпляр в первом — объект на схеме есть.

    До 2.0.0a4.2 `py_static.extract` аргумент `files` игнорировал, так что
    второй материал пропадал молча: схема выходила пустой, а «в коде нет
    классов» звучало как приговор коду студента, а не как наша недоделка.
    """
    вход = положить(project, PY_ВХОД, "программа.py")
    библиотека = положить(project, PY_БИБЛИОТЕКА, "двигатель.py")
    ep, backend = agent_endpoint(
        turn(("make_object_diagram", {"ids": [вход, библиотека],
                                      "language": "python"})),
        done())
    orchestrator.fill_agent(project, endpoint=ep)

    (ответ,) = ответы(backend, 0)
    assert json.loads(ответ["content"])["objects"] == ["д"]


def test_схема_объектов_не_показывает_модели_путей(project, agent_endpoint):
    """Модель видит идентификаторы и имена — и ничего, что можно открыть.

    Проверяется не формулировка описания, а весь текст, уехавший модели: путь
    проекта в нём не встречается, косой черты нет вовсе, а состав ответа
    закреплён — новое поле с путём не проскочит незамеченным.
    """
    mid = положить(project, ОБЪЕКТЫ, "объекты.py")
    ep, backend = agent_endpoint(
        turn(("make_object_diagram", {"ids": [mid], "language": "python"})),
        done())
    orchestrator.fill_agent(project, endpoint=ep)

    содержимое = ответы(backend, 0)[0]["content"]
    assert project.path not in содержимое and "/" not in содержимое
    разбор = json.loads(содержимое)
    assert set(разбор) == {"artifact", "objects", "notes"}
    # Идентификатор артефакта — хеш содержимого, а не дорога до файла.
    assert len(разбор["artifact"]) == 16 and разбор["artifact"].isalnum()


# ── потолки ──────────────────────────────────────────────────────────────────

def test_потолок_ходов_обрывает_прогон_но_не_отменяет_сделанного(project,
                                                                 agent_endpoint):
    ep, _ = agent_endpoint(
        turn(("set_tag", {"key": "цель", "value": ЦЕЛЬ})),
        turn(("preview", {})))
    out = orchestrator.fill_agent(project, endpoint=ep, max_steps=2)

    # Потолок — исход, а не ошибка: расход настоящий, значение сохранено.
    assert out.stop == llm.Stop.MAX_TOKENS
    assert out.outcome == "interrupted" and out.ok is False
    assert out.filled == ["цель"] and project.value("цель") is not None
    # Потолок назван тот, что стоял в этом прогоне, а не умолчание модуля.
    assert any(p.code == "step_limit" and "(2)" in p.message
               for p in out.problems)
    assert project.run(out.run.id).outcome == "interrupted"


def test_лимит_останавливает_прогон_посреди_петли(project, agent_endpoint):
    ep, backend = agent_endpoint(
        turn(("set_tag", {"key": "цель", "value": ЦЕЛЬ})),
        turn(("preview", {})),
        done())
    # Потолок ставится между первым и вторым ходом: оценка одного хода проходит,
    # а «потрачено за первый ход + оценка второго» — уже нет.
    parts = orchestrator.build_parts(project, keys=["цель"], level=3)
    шаг = usage_mod.units(Usage(input=100, output=50), backend.spec.prices)
    оценка = llm.estimate(ep, parts, max_tokens=llm.Limits().max_tokens_per_call).units
    settings = project.settings()
    settings["cap_units"] = оценка + шаг / 2
    project.save_settings(settings)

    out = orchestrator.fill_agent(project, endpoint=ep, keys=["цель"])

    # Первый ход состоялся и оплачен, второго не было вовсе.
    assert out.steps == 1 and len(backend.requests) == 1
    assert len(journal_lines(project)) == 1
    assert out.filled == ["цель"] and project.value("цель") is not None
    assert out.outcome == "interrupted"
    assert any(p.code == "limit_stop" for p in out.problems)
