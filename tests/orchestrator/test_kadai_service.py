"""
Три обёртки `orchestrator.kadai`, которыми пользуется только служба.

Проверяется не «функция вернула словарь», а три обещания, каждое из которых
ломается молча:

1. **архив скачивается.** Стадия «архив» кладёт ZIP в `out/` и отдаёт наружу
   имя файла; по имени с сайта не скачивается ничего. Артефакт — единственная
   дорога наружу, и если идентификатор не доехал до `made`, кнопка на экране
   просто не появится, а работа при этом будет выглядеть законченной;
2. **вставшая работа возвращается в ход бесплатно.** До `restart` починить её
   можно было только замечанием к условию — оно переигрывает всё с разбора
   задания и стоит цены прогона;
3. **пожелания переживают вкладку.** Они пишутся до первого прогона, когда
   записи о работе ещё нет вовсе, и положить их в запись о задании нельзя:
   непустая запись означает для сценария «работу продолжаем».

Модель здесь не зовётся ни разу: стадия «приём» её не знает, а `restart`,
`wishes` и `_положить_архив` не знают её тем более.
"""
from __future__ import annotations

import io
import zipfile

import pytest

import kadai
import orchestrator
from kadai import run as run_mod
from orchestrator import kadai as обёртка

УСЛОВИЕ = "Написать программу сортировки массива и оформить отчёт."


def завести(tmp_path) -> tuple:
    """Проект с работой, прошедшей стадию «приём». → (двери, проект)."""
    services = обёртка.services(str(tmp_path / "работа"), create=True)
    services.project.add_material(УСЛОВИЕ.encode("utf-8"), "условие.txt",
                                  do_ocr=False, condition=True)
    сессия = run_mod.new(services)
    run_mod.run(сессия, until="приём")
    return сессия, services.project


# ── пожелания ────────────────────────────────────────────────────────────────

def test_пожелания_ложатся_в_проект_и_читаются(tmp_path):
    """Полный круг: записали — перечитали. Работы при этом не заводится."""
    project = orchestrator.Project.create(str(tmp_path / "работа"),
                                          template=обёртка.blank_template())
    assert обёртка.wishes(project) == {"text": "", "show_task": False,
                                       "show_structure": False}
    обёртка.set_wishes(project, text="покороче", show_structure=True)
    assert обёртка.wishes(project) == {"text": "покороче", "show_task": False,
                                       "show_structure": True}
    # Запись о задании не тронута: непустая означала бы «работа заведена», и
    # первый прогон пошёл бы продолжать работу, которой нет.
    assert kadai.task(project) == {}


def test_лишние_поля_пожеланий_не_доезжают_до_сценария(tmp_path):
    """`Wishes(**...)` упал бы `TypeError` на первом же лишнем ключе."""
    project = orchestrator.Project.create(str(tmp_path / "работа"),
                                          template=обёртка.blank_template())
    project.put_state(обёртка.WISHES_KEY, {"text": "а", "лишнее": 1})
    assert set(обёртка.wishes(project)) == {"text", "show_task",
                                            "show_structure"}
    assert kadai.Wishes(**обёртка.wishes(project)).text == "а"


# ── архив артефактом ─────────────────────────────────────────────────────────

def test_архив_из_out_ложится_артефактом_и_попадает_в_made(tmp_path):
    """Имя из `outputs` → байты из `out/` → идентификатор в `made.archive`.

    Байты архива кладутся здесь руками: производит их стадия «архив», а
    проверяется дорога от имени файла до артефакта, который можно скачать.
    """
    сессия, project = завести(tmp_path)
    имя = project.pack([{"name": "как-это-собрано.txt",
                         "text": "код не запускался"}])
    сессия.work.outputs["zip"] = имя

    сделано = обёртка._положить_архив(project, сессия.work)
    art = сделано[обёртка.ARCHIVE]
    assert обёртка.status(project)["made"][обёртка.ARCHIVE] == art
    # Артефакт — это те самые байты архива, а не имя и не путь.
    with zipfile.ZipFile(io.BytesIO(project.resolve_artifact(art))) as zf:
        assert zf.namelist() == ["как-это-собрано.txt"]


def test_повторная_укладка_архива_ничего_не_меняет(tmp_path):
    """Артефакт адресуется содержимым: тот же архив — тот же идентификатор."""
    сессия, project = завести(tmp_path)
    сессия.work.outputs["zip"] = project.pack(
        [{"name": "как-это-собрано.txt", "text": "код не запускался"}])
    первый = обёртка._положить_архив(project, сессия.work)
    второй = обёртка._положить_архив(project, сессия.work)
    assert первый == второй


def test_пропавший_архив_не_роняет_работу(tmp_path):
    """Собранное уже сохранено, и «нечего положить» — не повод объявить прогон
    упавшим. Молчания при этом нет: `archive` в `made` просто не появляется."""
    сессия, project = завести(tmp_path)
    сессия.work.outputs["zip"] = "которого-нет.zip"
    assert обёртка.ARCHIVE not in обёртка._положить_архив(project, сессия.work)


# ── начать стадию заново ─────────────────────────────────────────────────────

def test_вставшая_работа_возвращается_в_ход_с_нужной_стадии(tmp_path):
    """`failed` → `running`, споткнувшаяся стадия и всё за ней снова «ждёт».

    Сделанное до неё остаётся сделанным: платили за него один раз, и переигрывать
    его — это ровно то, чем плохо замечание к условию.
    """
    сессия, project = завести(tmp_path)
    kadai.stumble(сессия.work, "разбор задания",
                  kadai.problem("не_прочиталось", "условие не прочиталось"))
    сессия.save()

    снимок = обёртка.restart(project)
    assert снимок["restarted"] == "разбор задания"
    assert снимок["state"] == "running"
    состояния = {st["name"]: st["state"] for st in снимок["stages"]}
    assert состояния["приём"] == kadai.DONE
    assert состояния["разбор задания"] == kadai.WAITING
    assert состояния["решение"] == kadai.WAITING
    # Прочитанное с тома вторым процессом видит то же самое: ход работы сохранён.
    assert обёртка.status(project)["state"] == "running"


def test_названная_стадия_сбрасывает_и_то_что_после_неё(tmp_path):
    """«Переделай с приёма» — законная просьба, и она сбрасывает всё дальше."""
    сессия, project = завести(tmp_path)
    kadai.stumble(сессия.work, "разбор задания",
                  kadai.problem("не_прочиталось", "условие не прочиталось"))
    сессия.save()

    снимок = обёртка.restart(project, stage="приём")
    состояния = {st["name"]: st["state"] for st in снимок["stages"]}
    assert состояния["приём"] == kadai.WAITING
    assert состояния["разбор задания"] == kadai.WAITING


def test_идущая_работа_никуда_не_вставшая_это_отказ(tmp_path):
    """Молчание здесь спрятало бы вторую беду: вызывающий потерял состояние."""
    _сессия, project = завести(tmp_path)
    with pytest.raises(orchestrator.OrchestratorError, match="никуда не встала"):
        обёртка.restart(project)


def test_стадии_с_таким_именем_не_бывает(tmp_path):
    """Отказ с перечнем, а не молчаливое «ничего не сделано»."""
    _сессия, project = завести(tmp_path)
    with pytest.raises(orchestrator.OrchestratorError, match="приём"):
        обёртка.restart(project, stage="разбор")


def test_заново_обходится_без_endpoint_вовсе(tmp_path):
    """Ни одного вызова модели, и доказывается это тем, что звать нечем.

    Endpoint не зарегистрирован ни один (оснастка чистит реестр перед каждым
    тестом), а сеть в тестах оркестратора запрещена. Пройди `restart` хоть шаг
    сценария — он упал бы здесь, а не «когда-нибудь на боевой машине».
    """
    сессия, project = завести(tmp_path)
    kadai.stumble(сессия.work, "разбор задания",
                  kadai.problem("не_прочиталось", "условие не прочиталось"))
    сессия.save()
    assert обёртка.restart(project)["state"] == "running"
