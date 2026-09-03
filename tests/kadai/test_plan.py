"""
Два режима прохода — одно множество, а не две ветки.

Стерегутся три вещи. Первая: умолчание — проход без остановок (решение
владельца 2026-08-31), и никакая просьба не появляется сама. Вторая: остановка
включается флагом, а не сканированием текста пожеланий — сканер молча
пропустил бы «покажи, что получится по разделам» и отдал бы человеку
оплаченный до конца прогон вместо экрана с вопросом. Третья: просьбы из двух
мест складываются, а не затирают друг друга.
"""
from __future__ import annotations

import pytest

import kadai


def test_по_умолчанию_остановок_нет(profile):
    plan = kadai.plan_of(profile)
    assert plan.pause_after == frozenset()
    assert not plan.stops_after("шаблон")


def test_текст_пожеланий_сам_по_себе_ничего_не_включает(profile):
    """Пожелания — данные. Понять их словами может только стадия «разбор
    задания»; сканер слов здесь молча ошибся бы на первой же перефразировке."""
    plan = kadai.plan_of(profile, wishes=kadai.Wishes(text="покажи сначала структуру!"))
    assert plan.pause_after == frozenset()
    assert plan.wishes.text == "покажи сначала структуру!"


def test_флаг_включает_остановку_после_шаблона(profile):
    plan = kadai.plan_of(profile, wishes=kadai.Wishes(show_structure=True))
    assert plan.pause_after == {"шаблон"} and plan.stops_after("шаблон")


def test_просьбы_из_двух_мест_складываются(profile):
    plan = kadai.plan_of(profile, wishes=kadai.Wishes(show_task=True),
                         pause_after=["шаблон"])
    assert plan.pause_after == {"разбор задания", "шаблон"}


def test_остановка_после_несуществующей_стадии_ошибка_с_подсказкой(profile):
    with pytest.raises(kadai.KadaiError, match="похоже на"):
        kadai.plan_of(profile, pause_after=["шаблн"])


def test_план_знает_какие_стадии_нужны_этому_виду_работы(profile):
    """Профиль без стадии «решение» (реферат) — это данные, а не ветка кода."""
    реферат = kadai.parse({"name": "реферат",
                           "stages": ["приём", "разбор задания", "шаблон", "тексты",
                                      "сборка", "архив"],
                           "kinds": {"введение": {"required": True}}})
    plan = kadai.plan_of(реферат)
    assert not plan.needs("решение") and plan.needs("тексты")
