"""
Оснастка тестов доски: образцы сцен и сборка сцены из нескольких строк.

Две разные вещи, и смешивать их не надо.

**Образцы** (`samples/`) — сцены целиком плюс ожидаемые `steps.json` и
`digest.txt` рядом. Это договор между областями: по ним пишутся служба и сайт,
не дожидаясь друг друга, и их же читают глазами. Проверка «совпало знак в знак»
ловит не ошибку в логике, а **молчаливое изменение формы**: поправленная печать
выжимки или другой порядок полей в шаге ломают чужой код, который уже написан по
образцу.

**Сборщик** — короткие сцены под один вопрос («что будет, если кадров нет»,
«куда встанет росчерк без группы»). Разбирать такой случай на образце нельзя:
образец обязан выглядеть как настоящая доска, а тест обязан содержать ровно то,
что проверяет.

Координаты в сборщике задаются одним числом `y`: порядок чтения — единственное,
ради чего координаты вообще существуют в пакете.
"""
from __future__ import annotations

import json
from pathlib import Path

ОБРАЗЦЫ = Path(__file__).parent / "samples"

# Метка, с которой собраны `digest.txt` образцов. В жизни метка случайна на
# каждый вызов; у образца она обязана быть постоянной, иначе сравнивать нечего.
МЕТКА = "000000"


def образец(имя: str) -> dict:
    """Сцена образца по имени без расширения."""
    return json.loads((ОБРАЗЦЫ / f"{имя}.excalidraw").read_text("utf-8"))


def ожидаемые_шаги(имя: str) -> list:
    return json.loads((ОБРАЗЦЫ / f"{имя}.steps.json").read_text("utf-8"))


def ожидаемая_выжимка(имя: str) -> str:
    return (ОБРАЗЦЫ / f"{имя}.digest.txt").read_text("utf-8")


def имена_образцов() -> list:
    """Все образцы по алфавиту: тесты проходят по каждому, а не по избранным."""
    return sorted(p.name[: -len(".excalidraw")] for p in ОБРАЗЦЫ.glob("*.excalidraw"))


# ── сборка короткой сцены ───────────────────────────────────────────────────

def сцена(*элементы) -> dict:
    """Сцена Excalidraw из перечисленных элементов, в порядке перечисления."""
    return {"type": "excalidraw", "version": 2, "source": "koritsu/board",
            "elements": list(элементы),
            "appState": {"viewBackgroundColor": "#ffffff", "gridSize": None},
            "files": {}}


def _элемент(id: str, тип: str, y: float, x: float = 0.0, **прочее) -> dict:
    основа = {"id": id, "type": тип, "x": float(x), "y": float(y),
              "width": 100.0, "height": 20.0, "isDeleted": False,
              "groupIds": [], "frameId": None}
    основа.update(прочее)
    return основа


def кадр(id: str, y: float, имя: str = "", **прочее) -> dict:
    return _элемент(id, "frame", y, name=имя, width=400.0, height=120.0, **прочее)


def росчерк(id: str, y: float, *, группа: str | None = None, latex: str | None = None,
            подтверждена: bool = True, источник: str = "myscript",
            кадр_id: str | None = None, **прочее) -> dict:
    """Один элемент `freedraw`. `latex=None` — росчерк без `customData` вовсе."""
    данные = None if latex is None else {
        "kind": "formula", "latex": latex, "latexConfirmed": подтверждена,
        "latexSource": источник, "recognizedAt": "2026-09-10T14:02:11Z"}
    return _элемент(id, "freedraw", y, groupIds=([группа] if группа else []),
                    frameId=кадр_id, customData=данные, **прочее)


def текст(id: str, y: float, содержимое: str, *, кадр_id: str | None = None,
          **прочее) -> dict:
    return _элемент(id, "text", y, text=содержимое, frameId=кадр_id, **прочее)


__all__ = ["МЕТКА", "ОБРАЗЦЫ", "имена_образцов", "кадр", "образец",
           "ожидаемая_выжимка", "ожидаемые_шаги", "росчерк", "сцена", "текст"]
