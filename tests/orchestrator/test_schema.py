"""
Отбор тегов и схемы для модели.

Цена ошибки в отборе конкретная: схема из всего манифеста попросила бы модель
заполнить теги, которых нет в шаблоне и которые заполняет человек, а `required`
в такой схеме соврал бы — модель обязана вернуть то, чего у неё никто не просил,
и вернёт выдумку за настоящие токены.
"""
from __future__ import annotations

import pytest

import llm
import orchestrator
from orchestrator.errors import OrchestratorError


def test_отбираются_только_теги_модели(project):
    m = project.manifest()
    m.tags["введение"].source_hint = "manual"      # это пишет человек
    m.tags["таблица"].missing = True               # тега больше нет в шаблоне
    project.save_manifest(m)
    assert orchestrator.fillable(project.manifest()) == ["цель"]


def test_порядок_тегов_это_порядок_документа(project):
    """Он важен не для валидности, а для потока: первые закрывшиеся значения —
    начало документа, и частичный результат при обрыве осмыслен."""
    assert orchestrator.fillable(project.manifest()) == ["цель", "введение", "таблица"]
    схема = orchestrator.report_schema(project.manifest(),
                                       keys=orchestrator.fillable(project.manifest()))
    assert list(схема["properties"]) == ["цель", "введение", "таблица"]
    assert схема["additionalProperties"] is False


def test_схемы_годятся_слою_моделей(project):
    """Схема, которую слой не примет, обнаружилась бы первым живым вызовом."""
    m = project.manifest()
    llm.jsonschema.check_schema(orchestrator.report_schema(
        m, keys=orchestrator.fillable(m)))
    for key, spec in m.tags.items():
        llm.jsonschema.check_schema(orchestrator.tag_schema(spec))


def test_неизвестный_ключ_отказ_с_подсказкой(project):
    with pytest.raises(OrchestratorError) as exc:
        orchestrator.fillable(project.manifest(), keys=["цел"])
    assert "похоже на" in str(exc.value) and "цель" in str(exc.value)


def test_просить_нечего_это_отказ_а_не_пустой_вызов(project):
    m = project.manifest()
    for spec in m.tags.values():
        spec.source_hint = "manual"
    project.save_manifest(m)
    with pytest.raises(OrchestratorError):
        orchestrator.fill_report(project, endpoint="ep_test")
