"""
Оснастка тестов kadai.

Два правила обеспечиваются структурно, а не договорённостью.

1. **Соседей здесь нет вовсе.** `kadai` не импортирует ни одного пакета проекта
   (правило разреза, см. `kadai/__init__.py`), поэтому и тесты обходятся
   стандартной библиотекой и подделками. Выгода не только идейная: четыре
   соседних пакета сейчас переписываются, и тесты сценария не должны краснеть
   от чужой правки.
2. **Сети нет, потому что её неоткуда взять.** Ни одна функция пакета не зовёт
   модель: вызовы модели живут за швами, а швы в тестах отказывают. Отдельный
   запрет транспорта поэтому не нужен — нужен тест, что швы действительно
   отказывают (`test_seams.py`).

Подделка проекта повторяет ровно те методы, которыми `kadai` пользуется, и
позволяет убрать любой из них: половина этих методов у настоящего `Project`
ещё не написана, и поведение «метода нет» — рабочий случай, а не крайний.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pytest

import kadai


@dataclass
class FakeSpec:
    """Запись манифеста в том объёме, в каком её читает `kadai` (утиная типизация).

    Ровно четыре поля входа плюс `missing`: если `kadai` начнёт читать пятое,
    тест это заметит — подделка его не отдаст.
    """

    type: str = "markdown"
    prompt: str = ""
    limits: dict = field(default_factory=dict)
    depends_on: list = field(default_factory=list)
    missing: bool = False


class FakeProject:
    """Проект в объёме, нужном сценарию. Любой метод можно убрать через `without`."""

    def __init__(self, *, without=(), spent=None, cap=None):
        self._state: dict = {}
        self._packed: list | None = None
        self._derived: dict = {}
        self._spent = spent or {"calls": 2, "units": 41200.0, "cost": 1.83,
                                "estimated_share": 0.04}
        self._cap = cap
        for name in without:
            setattr(self, name, None)

    def put_state(self, name: str, d: dict) -> None:
        self._state[name] = d

    def state(self, name: str) -> dict:
        return self._state.get(name, {})

    def pack(self, entries) -> str:
        self._packed = entries
        return "работа.zip"

    def derived_of(self, art: str):
        return self._derived.get(art)

    def spent(self) -> dict:
        return dict(self._spent)

    def limit(self):
        return None if self._cap is None else FakeLimit(self._cap)


@dataclass
class FakeLimit:
    """Лимит в объёме `llm.Limit`: потолок и доля. Больше `kadai` от него не берёт."""

    cap_units: float
    spent_units: float = 41200.0

    def share(self) -> float:
        return self.spent_units / self.cap_units


@pytest.fixture
def profile():
    return kadai.load("kursovaya")


@pytest.fixture
def plan(profile):
    return kadai.plan_of(profile)


@pytest.fixture
def structure():
    """Годная структура курсовой: все обязательные виды, код и схема на месте."""
    return {"sections": [
        {"key": "титул", "title": "Титульный лист", "kind": "титульник"},
        {"key": "оглавление", "title": "Содержание", "kind": "оглавление"},
        {"key": "введение", "title": "Введение", "kind": "введение"},
        {"key": "постановка", "title": "Постановка задачи", "kind": "постановка"},
        {"key": "реализация", "title": "Реализация", "kind": "реализация"},
        {"key": "листинг_сортировки", "title": "Листинг", "kind": "листинг"},
        {"key": "схема_алгоритма", "title": "Схема алгоритма", "kind": "схема"},
        {"key": "результаты", "title": "Результаты", "kind": "результаты"},
        {"key": "заключение", "title": "Заключение", "kind": "заключение"},
    ]}


@pytest.fixture
def project():
    return FakeProject()
