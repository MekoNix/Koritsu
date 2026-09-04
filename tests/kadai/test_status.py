"""
Форма снимка для сайта: ключ в ключ по записке, и ни одной выдуманной цифры.

Стерегутся четыре решения, каждое из которых иначе тихо превращается в ложь:
`waiting_user` отдельно от `running`; доля расхода рядом с долей оценённого;
отсутствие потолка как `None`, а не как ноль; курсор номером, а не временем.
Плюс хранение: ход работы обязан лежать в проекте, потому что считает и
показывает его разные процессы.
"""
from __future__ import annotations

import pytest

import kadai
from kadai import status

from .conftest import FakeProject


def test_форма_снимка_называет_обещанные_ключи(plan):
    work = kadai.new_work(plan, work_id="w-2026-1")
    snap = kadai.snapshot(work)
    # `condition_text` рядом с остальными: распознанное условие показывается
    # человеку до решения (решение владельца 2026-08-31), а то, за чем надо идти
    # вторым запросом, не показывают.
    assert set(snap) == {"work", "state", "stage", "stages", "current", "hold",
                         "spent", "problems", "outputs", "since", "events",
                         "condition_text", "condition"}
    assert snap["work"] == "w-2026-1" and snap["state"] in kadai.stages.WORK_STATES
    assert snap["stage"] == "приём"


def test_расход_без_потолка_не_печатает_процентов(project):
    """«Потолка нет» и «потолок огромный» — разные утверждения, и первое не
    должно показывать долю от выдуманного числа."""
    spent = status.spent_of(project)
    assert spent["cap"] is None and spent["share"] is None
    assert spent["units"] == 41200.0


def test_доля_оценённого_едет_рядом_с_долей_расхода():
    """Показать «потрачено 21 %», не сказав, что часть этого — прикидка, значит
    соврать точной цифрой."""
    spent = status.spent_of(FakeProject(cap=200000.0))
    assert round(spent["share"], 3) == 0.206 and spent["estimated_share"] == 0.04


def test_курсор_это_номер_события_а_не_время(plan):
    work = kadai.new_work(plan)
    kadai.begin(work, "приём")
    snap = kadai.snapshot(work, since=1)
    assert isinstance(snap["since"], int) and snap["since"] == work.seq
    assert [e["n"] for e in snap["events"]] == [2]


def test_ход_работы_кладётся_в_проект_и_поднимается_обратно(plan, project):
    work = kadai.new_work(plan, work_id="w-1")
    kadai.begin(work, "приём")
    kadai.step(work, "приём", done=4, total=18, current="разбираю материалы")
    status.save(project, work)
    снова = status.load(project, plan)
    assert снова.id == "w-1" and снова.current == "разбираю материалы"
    assert снова.stage("приём").done == 4 and снова.seq == work.seq


def test_запись_с_чужим_профилем_не_принимается(plan, project):
    status.save(project, kadai.new_work(plan))
    другой = kadai.plan_of(kadai.parse({"name": "записка", "stages": ["приём"], "kinds": {}}))
    with pytest.raises(kadai.KadaiError, match="профил"):
        status.load(project, другой)


def test_без_шва_состояния_отказ_с_адресом(plan):
    """Пока `Project.put_state` не написан, писать ход некуда — и молчаливая
    запись в память была бы статусом, которого не увидит сайт."""
    бедный = FakeProject(without=["put_state", "state"])
    with pytest.raises(kadai.NotReady, match="put_state"):
        status.save(бедный, kadai.new_work(plan))


def test_запись_о_задании_копится_а_не_затирается(project):
    """Профиль кладёт одна стадия, требование — другая, собранный отчёт —
    третья. «Последний победил» терял бы всё, чего не знал последний писавший."""
    status.save_task(project, wishes={"text": "покороче"})
    status.save_task(project, requirement={"topic": "Сортировка"})
    status.save_task(project, made={"docx": "a01"})
    запись = status.task(project)
    assert запись["wishes"]["text"] == "покороче"
    assert запись["requirement"]["topic"] == "Сортировка"
    assert запись["v"] == 3


def test_у_задания_своя_маленькая_нумерация_версий(project):
    """Пожеланиям и требованию версий взять неоткуда: значением служебного ключа
    их не сделать — ключ вне работы давал бы предупреждение при каждой проверке,
    а замечания показываются человеку."""
    status.save_task(project, requirement={"topic": "Сортировка"})
    status.save_task(project, requirement={"topic": "Поиск"})
    вернули = status.rollback_task(project, 1)
    assert вернули["requirement"]["topic"] == "Сортировка"
    # Возврат — новой версией, а не откатом номера: иначе двое, глядя на
    # «версию 2», видят разные записи.
    assert вернули["v"] == 3


def test_версии_задания_которой_нет_ошибка_со_списком(project):
    status.save_task(project, requirement={"topic": "Сортировка"})
    with pytest.raises(kadai.KadaiError, match="есть"):
        status.rollback_task(project, 7)


def test_потерянная_просьба_об_остановке_не_проходит_молча(profile, project):
    """Работа, заведённая с остановкой на структуре, и план без неё — это
    прогон, который не встанет там, где человек его ждёт."""
    с_остановкой = kadai.plan_of(profile, wishes=kadai.Wishes(show_structure=True))
    status.save(project, kadai.new_work(с_остановкой))
    with pytest.raises(kadai.KadaiError, match="остановк"):
        status.load(project, kadai.plan_of(profile))
