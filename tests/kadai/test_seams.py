"""
Швы: незаконченное называется незаконченным и падает с адресом.

Главное, что здесь стережётся, — отсутствие правдоподобной пустоты. Шов,
который вместо отказа вернул бы пустую структуру или «архив собран, файлов
нет», отдал бы человеку пустоту под видом результата, и узнал бы он об этом на
кафедре. Второе: отказ обязан называть пакет, адрес правки и подпись — иначе
сосед узнаёт, чего от него ждали, только придя спрашивать.
"""
from __future__ import annotations

import pytest

import kadai
from kadai import seams

from .conftest import FakeProject


def test_каждый_шов_называет_соседа_адрес_и_подпись():
    for name, s in kadai.SEAMS.items():
        assert s.neighbor and s.address and s.signature, name
        assert s.awaits and s.without, name


def test_отказ_шва_печатает_подпись_которую_ждём():
    with pytest.raises(kadai.NotReady) as поймали:
        raise kadai.not_ready("шаблон")
    текст = str(поймали.value)
    assert "make_template" in текст and "hokoku" in текст and "И.3" in текст


def test_шва_с_опечаткой_нет_с_подсказкой():
    with pytest.raises(kadai.NotReady, match="похоже на"):
        kadai.seam("шаблн")


def test_дверь_которой_не_дали_отказывает_а_не_молчит():
    services = kadai.Services(project=FakeProject())
    with pytest.raises(kadai.NotReady, match="ask"):
        seams.door(services, "ask", "структура")


def test_дверь_которую_дали_зовётся_как_есть():
    """Как только сосед допишет своё, вызов заработает без правки здесь."""
    services = kadai.Services(project=FakeProject(), ask=lambda *a, **k: {"sections": []})
    assert seams.door(services, "ask", "структура")() == {"sections": []}


def test_метод_проекта_проверяется_утиной_типизацией():
    assert callable(seams.method(FakeProject(), "pack", "архив"))
    with pytest.raises(kadai.NotReady, match="note_derived"):
        seams.method(FakeProject(), "note_derived", "журнал производных")


def test_без_проекта_отказ_называет_причину():
    with pytest.raises(kadai.NotReady, match="Services.project"):
        seams.method(None, "pack", "архив")


def test_notready_ловится_как_ошибка_пакета():
    """Тот, кто ловит ошибки сценария целиком, обязан поймать и это: иначе
    прогон, упёршийся в ненаписанного соседа, выглядит падением службы."""
    assert issubclass(kadai.NotReady, kadai.KadaiError)


def test_решение_названо_неполным_а_не_готовым():
    """Уровень 3 в orchestrator появился, но `put_source` в наборе инструментов
    нет: код, сочинённый моделью, положить некуда — а он и есть предмет kadai."""
    assert "put_source" in kadai.seam("решение").signature


def test_разбор_условия_требует_отделимости_распознанного():
    """Решение владельца: распознанное OCR показывается человеку. Если оно не
    отделено от текстового слоя, показывать нечего."""
    assert "OCR" in kadai.seam("разбор условия").signature
