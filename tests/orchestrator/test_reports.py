"""
Документы одной работы: у каждого отчёта свой бланк и свои значения.

Стережётся здесь то, ради чего документ вообще отделён от работы: два отчёта в
одной работе не видят значений друг друга, материалы и артефакты у них общие, а
работа, заведённая до появления второго документа, своих значений не теряет.
"""
from __future__ import annotations

import os
import pathlib

import pytest

import orchestrator
from orchestrator.errors import OrchestratorError

from .conftest import markdown_value, template_bytes


def test_у_документа_свои_значения(project):
    """Значение, записанное в отчёт, не видно ни работе, ни соседнему отчёту."""
    первый = project.create_report("отчёт-1", template=template_bytes())
    второй = project.create_report("отчёт-2", template=template_bytes())

    первый.set_value("цель", markdown_value("первая цель"), source="manual")
    второй.set_value("цель", markdown_value("вторая цель"), source="manual")

    assert первый.value("цель")["text"] == "первая цель"
    assert второй.value("цель")["text"] == "вторая цель"
    # Корневой документ работы не тронут: до этого в нём значений не было.
    assert project.value("цель") is None


def test_у_документа_своя_история(project):
    отчёт = project.create_report("отчёт-1", template=template_bytes())
    отчёт.set_value("цель", markdown_value("раз"), source="manual")
    отчёт.set_value("цель", markdown_value("два"), source="agent")
    assert [в.n for в in отчёт.versions("цель")] == [1, 2]
    # У соседнего отчёта истории нет вовсе — она принадлежит документу.
    сосед = project.create_report("отчёт-2", template=template_bytes())
    assert сосед.versions("цель") == []


def test_у_документа_свой_бланк(project):
    """Смена бланка в отчёте не переписывает бланк работы и соседнего отчёта."""
    отчёт = project.create_report("отчёт-1", template=template_bytes())
    другой = template_bytes(tags=("вывод",))
    отчёт.update_template(другой)

    assert set(отчёт.manifest().tags) == {"цель", "введение", "таблица", "вывод"}
    assert list(project.manifest().tags) == ["цель", "введение", "таблица"]
    assert отчёт.template_artifact() != project.template_artifact()


def test_материалы_и_артефакты_общие(project):
    """Файл, принесённый человеком, принадлежит работе, а не одному отчёту."""
    отчёт = project.create_report("отчёт-1", template=template_bytes())
    assert [м.name for м in отчёт.store().list()] == \
           [м.name for м in project.store().list()]

    art = отчёт.put_artifact(b"picture-bytes", name="картинка")
    # Тот же артефакт достаётся из работы и из соседнего отчёта: хранилище одно.
    assert project.resolve_artifact(art) == b"picture-bytes"
    сосед = project.create_report("отчёт-2")
    assert сосед.resolve_artifact(art) == b"picture-bytes"


def test_потолок_расхода_остаётся_у_работы(tmp_path):
    """Документ не заводит своего потолка: он один на работу."""
    p = orchestrator.Project.create(str(tmp_path / "п"), template=template_bytes(),
                                    cap_units=7.0)
    отчёт = p.create_report("отчёт-1", template=template_bytes())
    assert отчёт.settings()["cap_units"] == 7.0
    # Смена бланка отчёта не делает снимка потолка работы в его настройках.
    отчёт.update_template(template_bytes(tags=("вывод",)))
    свои = pathlib.Path(отчёт.doc_path()) / "project.json"
    assert "cap_units" not in свои.read_text(encoding="utf-8")


def test_отчёт_без_каталога_читает_корневой_документ(project):
    """Отчёт, заведённый до появления каталогов, своих значений не теряет."""
    project.set_value("цель", markdown_value("написано раньше"), source="manual")
    старый = orchestrator.Project(project.path, report="его-нет-на-томе")
    assert старый.value("цель")["text"] == "написано раньше"
    assert старый.doc_path() == project.path


def test_список_документов_и_повтор(project):
    project.create_report("отчёт-1")
    project.create_report("отчёт-2")
    assert project.reports() == ["отчёт-1", "отчёт-2"]
    # Завести поверх существующего — отказ: «завести» и «сменить бланк» разные
    # намерения, и второе делает update_template.
    with pytest.raises(OrchestratorError):
        project.create_report("отчёт-1")


def test_удаление_документа_не_трогает_соседа(project):
    первый = project.create_report("отчёт-1", template=template_bytes())
    второй = project.create_report("отчёт-2", template=template_bytes())
    первый.set_value("цель", markdown_value("остаётся"), source="manual")
    art = второй.put_artifact("нужный файл".encode("utf-8"), name="файл")

    assert project.drop_report("отчёт-2") is True
    assert project.reports() == ["отчёт-1"]
    assert первый.value("цель")["text"] == "остаётся"
    # Артефакт адресуется содержимым и может стоять значением тега в соседнем
    # отчёте — вслед за документом он не уходит.
    assert project.resolve_artifact(art) == "нужный файл".encode("utf-8")
    # Снести то, чего нет, — не отказ, а то же состояние.
    assert project.drop_report("отчёт-2") is False


def test_имя_документа_не_путь(project):
    """Разделитель пути в имени документа умирает на входе, а не на томе."""
    for имя in ("../чужое", "а/б", ".."):
        with pytest.raises(OrchestratorError):
            project.create_report(имя)
        with pytest.raises(OrchestratorError):
            orchestrator.Project(project.path, report=имя)


def test_каталог_сборки_у_каждого_свой(project):
    первый = project.create_report("отчёт-1", template=template_bytes())
    второй = project.create_report("отчёт-2", template=template_bytes())
    assert первый.outdir() != второй.outdir()
    assert os.path.dirname(первый.outdir()) == первый.doc_path()
