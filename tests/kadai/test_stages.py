"""
Семь стадий: порядок, пропуск, остановка и счётчик со знаменателем.

Тесты стерегут ровно то, что в интерфейсе выглядит правдоподобно и при этом
врёт: стадию, которой не было, показанную как пройденную; ожидание человека,
неотличимое от зависшей работы; полоску хода с выдуманным знаменателем; путь к
файлу, утёкший в статус под видом имени.
"""
from __future__ import annotations

import pytest

import kadai
from kadai import stages


def test_ненужная_стадия_помечена_пропущенной_а_не_сделанной(profile):
    записка = kadai.parse({"name": "записка", "stages": ["приём", "тексты", "сборка", "архив"],
                           "kinds": {}})
    work = kadai.new_work(kadai.plan_of(записка))
    решение = work.stage("решение")
    assert решение.state == stages.SKIPPED
    # Все семь стадий видны всегда: список из одних нужных отвечал бы на вопрос
    # «сколько осталось», но не на вопрос «а где же код».
    assert [s.name for s in work.stages] == list(kadai.STAGE_NAMES)


def test_пропущенную_стадию_нельзя_начать(profile):
    записка = kadai.parse({"name": "записка", "stages": ["приём", "сборка"], "kinds": {}})
    work = kadai.new_work(kadai.plan_of(записка))
    with pytest.raises(kadai.KadaiError, match="пропущена"):
        kadai.begin(work, "решение")


def test_порядок_стадий_держится(plan):
    """«Тексты» раньше «шаблона» написали бы значения по манифесту, которого ещё
    нет, и увидеть это можно было бы только по пустому отчёту."""
    work = kadai.new_work(plan)
    with pytest.raises(kadai.KadaiError, match="рано начинать"):
        kadai.begin(work, "тексты")


def test_счётчик_без_знаменателя_отказ(plan):
    work = kadai.new_work(plan)
    kadai.begin(work, "приём")
    with pytest.raises(kadai.KadaiError, match="знаменател"):
        kadai.step(work, "приём", done=3)


def test_счётчик_со_знаменателем_доезжает_до_снимка(plan):
    work = kadai.new_work(plan)
    kadai.begin(work, "приём")
    kadai.step(work, "приём", done=9, total=18, current="разбираю материалы")
    stage = kadai.snapshot(work)["stages"][0]
    assert stage["progress"] == {"done": 9, "total": 18, "unit": "материал"}
    assert kadai.snapshot(work)["current"] == "разбираю материалы"


def test_у_стадий_без_знаменателя_полоски_нет(plan):
    work = kadai.new_work(plan)
    kadai.begin(work, "приём"), kadai.finish(work, "приём")
    kadai.begin(work, "разбор задания")
    stage = [s for s in kadai.snapshot(work)["stages"] if s["name"] == "разбор задания"][0]
    assert "progress" not in stage


def test_просьба_человека_останавливает_прогон_и_называет_показанное(profile):
    plan = kadai.plan_of(profile, wishes=kadai.Wishes(show_structure=True))
    work = _до(plan, "шаблон")
    assert work.state == "waiting_user"
    # Без «что показываем» ожидание неотличимо от зависшей работы, и человек
    # нажмёт «отменить» — то есть выбросит оплаченное.
    assert work.hold.show == "структуру отчёта"
    with pytest.raises(kadai.KadaiError, match="waiting_user"):
        kadai.begin(work, "решение")
    kadai.resume(work)
    assert work.state == "running" and work.hold is None


def test_стадия_может_потребовать_остановки_сама(plan):
    """Распознанное OCR условие показывается человеку всегда, независимо от
    пожеланий: ошибка в формуле даёт безупречно решённую
    чужую задачу, и не заметит её никто."""
    work = kadai.new_work(plan)
    kadai.begin(work, "приём")
    kadai.finish(work, "приём", hold=kadai.Hold(stage="приём", show="распознанное условие"))
    assert work.state == "waiting_user" and work.hold.show == "распознанное условие"


def test_resume_на_идущей_работе_отказ(plan):
    work = kadai.new_work(plan)
    with pytest.raises(kadai.KadaiError):
        kadai.resume(work)


def test_последняя_стадия_закрывает_работу(plan):
    work = _до(plan, "архив")
    assert work.state == "done" and kadai.snapshot(work)["state"] == "done"


def test_споткнулась_переводит_работу_в_failed(plan):
    work = kadai.new_work(plan)
    kadai.begin(work, "приём")
    kadai.stumble(work, "приём", kadai.problem("нет_условия", "условие не приложено"))
    snap = kadai.snapshot(work)
    assert snap["state"] == "failed" and snap["problems"][0]["module"] == "kadai"
    assert work.stage("приём").state == kadai.STUMBLED


def test_путь_вместо_имени_готового_файла_отказ(plan):
    work = kadai.new_work(plan)
    kadai.begin(work, "приём")
    with pytest.raises(kadai.KadaiError, match="путь"):
        kadai.finish(work, "приём", outputs={"docx": "/home/u/out/отчёт.docx"})


def test_события_нумеруются_и_дозапрашиваются(plan):
    work = kadai.new_work(plan)
    kadai.begin(work, "приём")
    было = work.seq
    kadai.finish(work, "приём")
    свежие = kadai.events_since(work, было)
    assert свежие and all(e["n"] > было for e in свежие)
    assert [e["n"] for e in work.events] == list(range(1, len(work.events) + 1))


def _до(plan, last: str):
    work = kadai.new_work(plan)
    for kind in kadai.STAGES:
        if not plan.needs(kind.name):
            continue
        if work.state == "waiting_user":
            break
        kadai.begin(work, kind.name)
        kadai.finish(work, kind.name)
        if kind.name == last:
            break
    return work
