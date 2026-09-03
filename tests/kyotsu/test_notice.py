"""
Одна форма предупреждения на все пакеты — проверяется, а не обещается.

До 2.0.0a4.2 форм было четыре: словарь у `hokoku`, свой словарь у службы,
голая строка у `llm`, у `fragmos` — ничего вовсе. Проверять тут надо не
«dataclass существует», а то, ради чего его завели: что запись одна на всех,
что незаданное не притворяется заданным и что подкласс не заводит второго
`to_dict`.
"""
from __future__ import annotations

import dataclasses

import pytest

import hokoku
import kyotsu


def test_обязательные_поля_и_есть_вся_запись():
    """Минимум, который обязан быть у любого замечания: кто, насколько, что."""
    n = kyotsu.Notice(module="fragmos", level="warning", code="goto_case_unresolved",
                      message="в схему не вошло")
    assert n.to_dict() == {"module": "fragmos", "level": "warning",
                           "code": "goto_case_unresolved", "message": "в схему не вошло"}


def test_позиции_в_исходнике_нет_и_она_не_врёт_нулём():
    """`file`/`line` необязательны намеренно (пункт про позицию в status.md ещё
    не сделан), и незаданные они в JSON не попадают.

    `{"file": null}` читается как «спрашивали и файла нет», а правда другая:
    позицию сюда пока никто не кладёт. Разница видна тому, кто по этому JSON
    будет подсвечивать строку кода.
    """
    без = kyotsu.Notice(module="llm", level="info", code="c", message="m").to_dict()
    assert "file" not in без and "line" not in без
    с = kyotsu.Notice(module="fragmos", level="warning", code="c", message="m",
                      file="Program.cs", line=12).to_dict()
    assert с["file"] == "Program.cs" and с["line"] == 12


def test_уровень_проверяется_на_входе():
    """Опечатка в уровне — не косметика: `err` вместо `error` тихо превращает
    беду в замечание, которое никого не остановит."""
    with pytest.raises(ValueError):
        kyotsu.Notice(module="hokoku", level="err", code="c", message="m")


def test_замечание_не_переписывается_по_дороге():
    """Свидетельство о том, что было в момент проверки. Список замечаний идёт
    через три пакета, и правка на месте нашлась бы не раньше готового отчёта."""
    n = kyotsu.Notice(module="hokoku", level="error", code="c", message="m")
    with pytest.raises(dataclasses.FrozenInstanceError):
        n.message = "другое"


def test_подкласс_не_заводит_второго_to_dict():
    """`hokoku.Problem` добавляет поля тега, и они попадают в JSON сами —
    потому что `to_dict` идёт по полям dataclass'а, а не по списку имён.
    Список имён и был бы тем местом, где ключ теряется молча.
    """
    p = hokoku.Problem(module="hokoku", level="error", code="type_mismatch",
                       key="замеры", message="не тот тип", expected="table", got="markdown")
    assert isinstance(p, kyotsu.Notice)
    assert p.to_dict() == {"module": "hokoku", "level": "error", "code": "type_mismatch",
                           "key": "замеры", "message": "не тот тип",
                           "expected": "table", "got": "markdown"}


def test_замечание_без_тега_ключом_не_притворяется():
    """Беды бывают не про тег (прогон оборвался, файл не разобрался): пустой
    `key` в JSON не попадает вовсе."""
    p = hokoku.Problem(module="orchestrator", level="error", code="run_failed",
                       message="прогон не удался")
    assert "key" not in p.to_dict()


def test_общий_пакет_не_знает_ни_одного_кода():
    """Заслон: коды остаются у пакетов, которые их выдают. Стоит `kyotsu`
    завести их список — и каждый новый код станет правкой общего пакета,
    то есть поводом ему разрастись.
    """
    исходник = (kyotsu.notice.__file__)
    with open(исходник, encoding="utf-8") as f:
        текст = f.read()
    for код in ("unresolved_ref", "unknown_key", "goto_case_unresolved", "type_mismatch"):
        assert код not in текст
