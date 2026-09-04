"""
`python -m orchestrator.kadai` — тонкая обёртка: разбор чужой, двери свои.

Проверяется ровно то, ради чего обёртка заведена: владелец гоняет всю систему
одной командой, **не ставя себе переменную окружения**, и получает те же самые
двери, что собирает `kadai_services`. Разбор аргументов при этом не свой:
второй CLI разошёлся бы с первым на первом же новом ключе, и проверять пришлось
бы оба.

Часть проверок идёт **подпроцессом**, а не вызовом функции, и это не
перестраховка: `python -m` собирает пакет заново, и опечатка в имени модуля,
циклический импорт или тень имени (`orchestrator.kadai` рядом с пакетом
`kadai`) видны только так. Сети в этих запусках нет по существу: команды `new`,
`--help` и `status` модель не зовут ни разу — endpoint у них даже не
регистрируется.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import hokoku
import kadai
import orchestrator
from orchestrator import kadai as обёртка

# Каталог `packages/`: подпроцессу его надо назвать самому — он запускается
# без нашей оснастки.
ПАКЕТЫ = str(Path(orchestrator.__file__).parent.parent)


def запустить(*args, timeout: float = 180) -> subprocess.CompletedProcess:
    """`python -m orchestrator.kadai …` подпроцессом, с `PYTHONPATH=packages`."""
    return subprocess.run(
        [sys.executable, "-m", "orchestrator.kadai", *args],
        capture_output=True, text=True, timeout=timeout,
        env={**os.environ, "PYTHONPATH": ПАКЕТЫ})


def условие(tmp_path) -> str:
    путь = tmp_path / "условие.txt"
    путь.write_text("Написать программу сортировки массива и оформить отчёт.",
                    encoding="utf-8")
    return str(путь)


# ── подпроцессом ─────────────────────────────────────────────────────────────

def test_help_называет_себя_своим_именем():
    """Подсказка, зовущая к `python -m kadai`, звала бы к команде, которая без
    переменной окружения не работает: `prog` приносит тот, кто запустил."""
    итог = запустить("--help")
    assert итог.returncode == 0
    assert "python -m orchestrator.kadai" in итог.stdout
    for команда in ("new", "run", "status", "rework", "archive"):
        assert команда in итог.stdout


def test_new_заводит_работу_без_переменной_окружения(tmp_path):
    """То, ради чего обёртка и есть: проект, условие и заведённая работа одной
    командой. Модель здесь не зовётся ни разу — стадия «приём» её не знает."""
    каталог = str(tmp_path / "работа")
    итог = запустить("new", каталог, "--condition", условие(tmp_path),
                     "--wish", "покороче")
    assert итог.returncode == 0, итог.stderr
    assert "заведена: условие условие.txt" in итог.stdout
    # Подсказка «дальше» зовёт к той же команде, которой запустили.
    assert "дальше: python -m orchestrator.kadai run " + каталог in итог.stdout

    project = orchestrator.Project(каталог)
    assert project.condition() is not None
    assert kadai.task(project)["wishes"]["text"] == "покороче"

    # `status` печатает ровно ту форму, которую будет отдавать API.
    снимок = json.loads(запустить("status", каталог).stdout)
    assert снимок["state"] == "running" and снимок["stage"] == "приём"
    assert [s["name"] for s in снимок["stages"]] == list(kadai.STAGE_NAMES)

    # Стадия «приём» модель не зовёт вовсе, поэтому её можно пройти и здесь —
    # и именно она кладёт в снимок текст условия так, как его прочитали.
    приём = запустить("run", каталог, "--until", "приём")
    assert приём.returncode == 0, приём.stderr
    снимок = json.loads(запустить("status", каталог).stdout)
    assert снимок["condition_text"].startswith("Написать программу")
    assert снимок["stages"][0]["state"] == "сделано"
    assert снимок["stages"][1]["state"] == "ждёт"


def test_new_поверх_готового_проекта_отказывает(tmp_path):
    """«Создать» и «сменить шаблон» — разные намерения, и решает это `Project`."""
    каталог = str(tmp_path / "работа")
    assert запустить("new", каталог, "--condition", условие(tmp_path)).returncode == 0
    второй = запустить("new", каталог, "--condition", условие(tmp_path))
    assert второй.returncode == 1 and "уже есть проект" in второй.stderr


def test_каталога_нет_говорится_словами(tmp_path):
    """Код возврата 1 — «позвали неправильно», а не 3 («сосед не готов»)."""
    итог = запустить("run", str(tmp_path / "нет-такого"))
    assert итог.returncode == 1 and "каталога проекта нет" in итог.stderr


# ── фабрика дверей ───────────────────────────────────────────────────────────

def test_фабрика_отдаёт_те_же_двери_что_kadai_services(tmp_path, endpoint):
    """Подпись фабрики обещана обеим сторонам дословно (`kadai.__main__`).

    Проверяется не «функция вызвалась», а что за ней настоящие двери: сценарий
    отличает готовый шов от неготового только этим.
    """
    ep, _ = endpoint()
    services = обёртка.services(str(tmp_path / "работа"), endpoint=ep, create=True)
    assert isinstance(services, kadai.Services)
    for имя, шов in (("ask", "структура"), ("make_template", "шаблон"),
                     ("solve", "решение"), ("write_texts", "текст"),
                     ("check_code", "проверка кода")):
        assert callable(kadai.seams.door(services, имя, шов))
    # Endpoint записан в проект: переспрашивать его на каждой команде незачем.
    assert services.project.settings()["endpoint"] == ep
    без_endpoint = обёртка.services(str(tmp_path / "работа"))
    assert без_endpoint.project.settings()["endpoint"] == ep


def test_проект_живого_режима_заводится_с_пустым_шаблоном(tmp_path):
    """Шаблона у живого режима нет вовсе: работа — список блоков.

    Пустой DOCX и есть честная запись этого положения — тегов ноль, манифест
    пуст, и ни один шаблонный путь на такой проект не позовётся молча: ему
    нечего заполнять.
    """
    assert обёртка.blank_template()[:2] == b"PK"
    assert hokoku.manifest_from_template(обёртка.blank_template()).tags == {}
    services = обёртка.services(str(tmp_path / "работа"), create=True)
    assert services.project.manifest().tags == {}
    assert services.project.blocks() == []
