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
        turn(("list_project_files", {})),
        turn(("read_file", {"id": mid})),
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
    assert шаги == ["list_project_files", "read_file", "make_flowchart",
                    "set_tag", "set_tag", "preview"]


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
    assert any(p["code"] == "no_operator_channel" for p in out.problems)


def test_переключатель_allow_пускает_без_пометки(project, agent_endpoint,
                                                 monkeypatch):
    """Три режима заглушки обязаны различаться делом, а не только словом."""
    monkeypatch.setattr(tools_mod, "WITHOUT_OPERATOR_CHANNEL", "allow")
    ep, _ = agent_endpoint(turn(("set_tag", {"key": "цель", "value": ЦЕЛЬ})), done())
    out = orchestrator.fill_agent(project, endpoint=ep)

    assert out.ok and out.filled == ["цель"]
    assert project.head_version("цель").flags == []
    assert not any(p["code"] == "no_operator_channel" for p in out.problems)


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
    assert any(p["code"] == "type_mismatch" for p in out.problems)


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
    assert any(p["code"] == "kept" and p["key"] == "цель" for p in out.problems)


def test_все_теги_за_человеком_прогон_не_начинается(project, agent_endpoint):
    for key in ("цель", "введение", "таблица"):
        project.set_value(key, {"type": "markdown", "text": "моё"}, source="manual")
    ep, backend = agent_endpoint(done())
    with pytest.raises(orchestrator.OrchestratorError, match="overwrite=True"):
        orchestrator.fill_agent(project, endpoint=ep)
    assert backend.requests == []


# ── read_file: идентификатор, а не путь; кусок, а не всё ─────────────────────

def test_read_file_не_принимает_путь_и_незнакомый_идентификатор(project,
                                                                agent_endpoint):
    ep, backend = agent_endpoint(
        turn(("read_file", {"id": "../../etc/passwd"}),
             ("read_file", {"id": "0123456789abcdef"})),
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


def test_read_file_режет_кусок_и_говорит_об_этом(project, agent_endpoint,
                                                 monkeypatch):
    # Материал длиннее потолка. Потолок трогаем через модуль: число одно, и
    # проверять надо его, а не выдуманную в тесте копию.
    monkeypatch.setattr(tools_mod, "READ_CHARS", 20)
    mid = материал(project)
    ep, backend = agent_endpoint(turn(("read_file", {"id": mid})), done())
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
    assert any(p["code"] == "step_limit" and "(2)" in p["message"]
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
    assert any(p["code"] == "limit_stop" for p in out.problems)
