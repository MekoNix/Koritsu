"""
Перечень кодов отказа: он полон и он уезжает в документ OpenAPI.

Код — договор с интерфейсом: по нему, а не по тексту, сайт решает, что показать
человеку. Пока перечня не было, новый код доезжал до экрана английским текстом
службы посреди русской страницы, и замечал это человек, а не проверка. Здесь
проверка и стоит:

* каждый код, брошенный где-нибудь в `packages/api`, записан в `errors.КОДЫ`;
* `КОДЫ` уезжают в `openapi.json` полем `x-error-codes` — по нему сайт сверяет
  свой словарь переводов (`web/src/i18n/ru/errors.json`).

Разбор идёт по исходникам (`ast`), а не по вызовам: отказы разбросаны по сорока
маршрутам, и позвать их все в тесте — значит написать сорок первый способ
ошибиться. Имена констант резолвятся по всем модулям сразу: `NOT_FOUND` в пяти
файлах — это одно и то же слово.
"""
from __future__ import annotations

import ast
import pathlib

from api import errors

ПАКЕТ = pathlib.Path(errors.__file__).resolve().parent


def _исходники() -> dict[pathlib.Path, ast.Module]:
    return {ф: ast.parse(ф.read_text(encoding="utf-8"))
            for ф in sorted(ПАКЕТ.rglob("*.py"))}


def _константы(деревья) -> tuple[dict, dict]:
    """Строковые константы и словари верхнего уровня всего пакета."""
    строки: dict[str, set[str]] = {}
    словари: dict[str, ast.Dict] = {}
    for дерево in деревья.values():
        for узел in ast.walk(дерево):
            if not isinstance(узел, ast.Assign):
                continue
            for цель in узел.targets:
                if not isinstance(цель, ast.Name):
                    continue
                if (isinstance(узел.value, ast.Constant)
                        and isinstance(узел.value.value, str)):
                    строки.setdefault(цель.id, set()).add(узел.value.value)
                elif isinstance(узел.value, ast.Dict):
                    словари.setdefault(цель.id, узел.value)
    return строки, словари


def _значения(узел, строки, словари) -> set[str]:
    """Во что превращается первый аргумент `ApiError(...)`.

    Четыре вида, и все четыре в службе встречаются: строка на месте,
    константа, константа соседнего модуля (`ключи.INVALID_TOKEN`) и выбор из
    словаря по коду оркестратора (`_КОДЫ_400[код]`).
    """
    if isinstance(узел, ast.Constant) and isinstance(узел.value, str):
        return {узел.value}
    if isinstance(узел, ast.Name):
        return set(строки.get(узел.id, ()))
    if isinstance(узел, ast.Attribute):
        return set(строки.get(узел.attr, ()))
    if isinstance(узел, ast.Subscript) and isinstance(узел.value, ast.Name):
        словарь = словари.get(узел.value.id)
        if словарь is not None:
            найдено: set[str] = set()
            for значение in словарь.values:
                найдено |= _значения(значение, строки, словари)
            return найдено
    return set()


def брошенные() -> dict[str, set[str]]:
    """Код → файлы, в которых он бросается. Сам `errors.py` не считается: там
    код приходит переменной, а перечня в нём и так нет смысла проверять."""
    деревья = _исходники()
    строки, словари = _константы(деревья)
    найдено: dict[str, set[str]] = {}
    for файл, дерево in деревья.items():
        if файл.name == "errors.py":
            continue
        for узел in ast.walk(дерево):
            if (isinstance(узел, ast.Call) and isinstance(узел.func, ast.Name)
                    and узел.func.id == "ApiError" and узел.args):
                значения = _значения(узел.args[0], строки, словари)
                assert значения, f"{файл}: не разобрать код отказа"
                for код in значения:
                    найдено.setdefault(код, set()).add(файл.name)
    return найдено


def test_каждый_брошенный_код_записан_в_перечне():
    """Новый код без строки в `errors.КОДЫ` роняет проверку здесь, а перевода
    к нему — проверку сайта: иначе он доедет до экрана английским текстом."""
    лишние = {код: sorted(файлы) for код, файлы in брошенные().items()
              if код not in errors.КОДЫ}
    assert not лишние, f"кодов нет в errors.КОДЫ: {лишние}"


def test_в_перечне_нет_выдуманных_кодов():
    """Обратная сторона: код, который никто не бросает и не кладёт в беду
    задания, — это строка, которую забыли убрать вместе с маршрутом."""
    живые = set(брошенные()) | set(errors.КОДЫ_ЗАДАНИЙ)
    # Каркас бросает свои коды сам, изнутри `errors.py`.
    живые |= {errors.NOT_FOUND, errors.METHOD_NOT_ALLOWED,
              errors.VALIDATION_FAILED, errors.INVALID_ID, errors.INTERNAL,
              errors.HTTP_ERROR}
    assert not set(errors.КОДЫ) - живые


def test_коды_уезжают_в_документ_openapi(app):
    """Сайт читает список из `openapi.json`, а не из питона."""
    документ = app.openapi()
    assert документ["x-error-codes"] == list(errors.КОДЫ)
    assert "not_found" in документ["x-error-codes"]
