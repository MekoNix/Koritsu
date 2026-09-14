"""
kokuban (黒板, «доска») — сцена доски → шаги, выжимка для репетитора, разбор ответа.

Модуль службы называется `board`, пакет — `kokuban`: имена японские у всех
предметных пакетов (`hokoku`, `kadai`, `fragmos`, `kyotsu`, `zuhyo`), а слово
интерфейса от имени пакета не зависит (тот же разрыв у `hokoku` ↔ модуля
«Отчёты»).

**Что делает пакет.** Человек решает задачу от руки на холсте Excalidraw;
написанное распознаётся в браузере и подтверждается человеком. Дальше начинается
эта работа: сцена разбирается в **шаги** (одна распознанная строка — один шаг),
из шагов и прочего нарисованного собирается **выжимка** — плоский текст, который
видит модель, — а её ответ **сличается со сценой** прежде, чем показаться
человеку.

    steps(scene)                     сцена → строки решения в порядке чтения
    digest(scene, mark)              сцена → текст для модели и обратная дорога
    schema(mode)                     схема ответа режима check | hint | drill
    rules(mode, level)               правила поведения репетитора
    request(mode, level, step)       что просим сделать сейчас
    latex_file(name, steps, at)      распознанное файлом рядом с доской
    settle(raw, digest, mode)        ответ модели → ответ по договору

**Чистый пакет, и граница узкая.** Вход — JSON сцены, выход — текст и словари.
Ни диска (`open(`, `os.path.join`), ни модели (`import llm`), ни хранилища
(`import materials`), ни оркестратора здесь нет и быть не может: всё это делает
дверь `orchestrator/board.py` — она собирает куски промпта, зовёт модель, кладёт
снимок сцены артефактом и записывает прогон. Проверяется правило грепом и
тестом (`tests/kokuban/test_border.py`), как и у соседей.

**Чего здесь нет намеренно.** MyScript и JIIX: распознавание живёт в браузере —
там есть штрихи и рамки строк, которых у службы нет вовсе, — и в пакет приезжает
уже размеченная сцена. Координат в том, что уезжает наружу, нет ни одной: они
потребляются при разборе сцены ради порядка чтения, а обратная дорога —
идентификатор (модель называет `[a1b2c3]`, браузер находит элемент и берёт
координаты у себя). Механической сверки переходов (символьной алгебры, Lean)
тоже нет: шов под неё оставлен формой шага — пары «идентификатор + LaTeX» в
порядке чтения, — но вердикт сегодня выносит модель.

Состав пакета:

    scene.py      сцена → объекты, кадры, связи, порядок чтения, короткие id
    steps.py      объекты → шаги решения и файл распознанного
    digest.py     доска → выжимка: метка прогона, отступы, потолки
    schema.py     схемы трёх режимов, правила репетитора, текст запроса
    verdict.py    ответ модели → ответ по договору, сверенный со сценой
"""
from __future__ import annotations

from . import scene as _scene
from . import steps as _steps
from . import digest as _digest
from . import schema as _schema
from . import verdict as _verdict

from .digest import (DIGEST_LIMIT, Digest, INDENT, MARK_LEN, TEXT_LIMIT,
                     VERSION as DIGEST_VERSION, new_mark)
from .scene import Board, Object, SHORT_LEN, SOURCES, read, short_id
from .schema import (DEFAULT_LEVEL, DEFAULT_MODE, DEPTH, LEVELS, MODES, MODE_RULES,
                     REMARK_KINDS, RULES, SCHEMAS, VERDICTS)
from .steps import unrecognized_of
from .verdict import UNCONFIRMED_NOTE


def steps(scene: dict, *, lines=None) -> list:
    """Сцена Excalidraw → шаги решения (§«Форма шага»).

    Шаг — одна строка записи: `{n, id, latex, source, confirmed, elements,
    frame, frame_name}`. Нераспознанная строка из списка не исчезает — у неё
    пустой `latex` и `confirmed: false`.

    `lines` — записанные строки, если распознанное хранится отдельно от сцены.
    Тогда список строится по ним и в их порядке, а сцена даёт объекты: их
    идентификаторы и кадры. Не дали — распознанное читается из `customData`
    сцены, как было, пока оно там и жило.
    """
    return _steps.steps_of(_scene.read(scene, lines), lines)


def digest(scene: dict, mark: str | None = None, *, lines=None) -> Digest:
    """Сцена Excalidraw → выжимка для модели.

    `mark` — метка прогона, шесть hex. Не дали — выпускается своя: метка
    принадлежит вызову, а не процессу, иначе подсмотренная в чужой выжимке
    метка годилась бы вечно.

    `lines` — записанные строки решения (см. `steps`). Источник распознанного
    ровно один: даны строки — сцена о формулах не спрашивается вовсе.
    """
    return _digest.build(scene, mark, lines=lines)


def schema(mode: str) -> dict:
    """Схема ответа режима `check` | `hint` | `drill`. Плоская и закрытая."""
    return _schema.schema(mode)


def rules(mode: str, level: str) -> str:
    """Правила поведения репетитора: общие + про режим + про уровень помощи."""
    return _schema.rules(mode, level)


def request(mode: str, level: str, step: str = "") -> str:
    """Что просим сделать сейчас. `step` читается только режимом `hint`."""
    return _schema.request(mode, level, step)


def latex_file(name: str, steps: list, at: str) -> str:
    """Шаги → текст файла `<имя доски>.latex.md` рядом с доской."""
    return _steps.latex_file(name, steps, at)


def lines_text(steps: list) -> str:
    """Шаги → пронумерованные записи для чата, без идентификаторов."""
    return _steps.lines_text(steps)


def settle(raw, digest, mode: str = "check") -> dict:
    """Ответ модели + выжимка того же прогона → ответ по договору."""
    return _verdict.settle(raw, digest, mode)


__all__ = [
    "steps", "digest", "schema", "rules", "request", "latex_file", "lines_text",
    "settle",
    "Board", "Digest", "Object",
    "MODES", "VERDICTS", "REMARK_KINDS", "LEVELS", "SCHEMAS", "RULES", "DEPTH",
    "MODE_RULES", "DEFAULT_MODE", "DEFAULT_LEVEL",
    "SOURCES", "SHORT_LEN", "MARK_LEN", "INDENT", "TEXT_LIMIT", "DIGEST_LIMIT",
    "UNCONFIRMED_NOTE", "DIGEST_VERSION", "new_mark", "read", "short_id",
    "unrecognized_of",
]
