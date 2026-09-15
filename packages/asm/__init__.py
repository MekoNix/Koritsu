"""
asm — модуль «Ассемблер»: сборка настоящими инструментами и трасса программы по шагам.

Пакет уровня ядра: из проекта не импортирует ничего, только стандартную библиотеку (как
`kokuban`). Режим «Ассемблера» — **набор инструментов** (`toolchain.py`): TASM (DOS, 16 бит,
DOSBox-X и DebugX) и MinGW x64 (Windows, 64 бит). Служба выбирает набор по `toolchain` из
снимка постановки и дальше зовёт только его:

    toolchain(id)                                   набор по id; неизвестный — АсмОшибка
    TOOLCHAINS                                      все наборы, подключённые на машине
    набор.status(env)                               что из инструментов есть, версии
    набор.find_tools(env, version)                  инструменты версии; None — нет
    набор.check_flags(tool, flags)                  чистые флаги сборки или АсмОшибка
    набор.request(snapshot)                         запрос ядра из request.json
    набор.build / run / memory_at(req, tools, …)    сборка, трасса, память на шаге

**Один прогон — вся трасса.** Браузер ходит по шагам сам: вперёд, назад, до курсора. Сервер
не держит живой отладчик на каждый клик — программа с заданным вводом детерминирована, и
трасса, снятая один раз, отвечает на любой вопрос о шаге. Паузы нет; её место занимает лимит
шагов. Ввод программы задаётся заранее и подаётся ровно в те шаги, где программа читает.

**Реестр.** TASM есть всегда. Остальные наборы подключаются при первом обращении к
`TOOLCHAINS`/`toolchain()`, а не при `import asm`: их зависимости не должны мешать TASM на
машине, где их нет. Подпакета нет — набора нет; подпакет не импортируется — набора тоже нет, а
причина лежит в `TOOLCHAIN_ERRORS`.

**Прежние имена** (`find_tools`, `build`, `run`, `memory_at`, `Tools`, `RunRequest`) — это
TASM: код, который зовёт ядро без выбора набора, работает как раньше.

Состав пакета:

    model.py       формы ответа (dataclass + to_json), общие у наборов
    toolchain.py   интерфейс набора, версии, состояние инструментов
    sink.py        запись trace.jsonl со свёрткой середины
    tasm/          TASM + TLINK в DOSBox-X, трасса DebugX
    mingw64/       GNU as/ld для Windows x64, трасса своим трассировщиком
"""
from __future__ import annotations

import importlib

from .model import (BuildMessage, BuildResult, Dump, ListingLine, MemWrite, RunRequest,
                    RunResult, Segment, Step, Symbol, Truncation, АсмОшибка)
from .toolchain import Cancelled, Progress, Range, Toolchain, ToolsStatus, VersionInfo
from .tasm import TOOLCHAIN as _TASM
from .tasm import TasmRequest, Tools, build, find_tools, memory_at, run

# Наборы, подключаемые при первом обращении к реестру: имя подпакета с `TOOLCHAIN`.
_OPTIONAL = ("mingw64",)

_registry: dict[str, Toolchain] | None = None

# Подпакет есть, но не импортировался: id → причина. Для журнала службы и разбора на машине.
TOOLCHAIN_ERRORS: dict[str, str] = {}


def _load() -> dict[str, Toolchain]:
    global _registry
    if _registry is not None:
        return _registry
    found: dict[str, Toolchain] = {_TASM.id: _TASM}
    for name in _OPTIONAL:
        qualified = f"{__name__}.{name}"
        try:
            chain = importlib.import_module(qualified).TOOLCHAIN
        except ModuleNotFoundError as e:
            if e.name != qualified:
                TOOLCHAIN_ERRORS[name] = f"{type(e).__name__}: {e}"
            continue
        except Exception as e:                               # noqa: BLE001
            TOOLCHAIN_ERRORS[name] = f"{type(e).__name__}: {e}"
            continue
        found[str(getattr(chain, "id", name))] = chain
    _registry = found
    return found


def toolchain(id: str) -> Toolchain:
    """Набор инструментов по id. Неизвестный или не подключённый на машине — `АсмОшибка`."""
    found = _load().get(id) if isinstance(id, str) else None
    if found is None:
        raise АсмОшибка(f"Режим {id!r} на этой машине не подключён")
    return found


def __getattr__(name: str):
    if name == "TOOLCHAINS":
        return _load()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["TOOLCHAINS", "TOOLCHAIN_ERRORS", "toolchain", "Toolchain", "VersionInfo",
           "ToolsStatus", "Progress", "Cancelled", "Range",
           "Tools", "TasmRequest", "find_tools", "RunRequest", "RunResult", "BuildResult",
           "BuildMessage", "ListingLine", "Segment", "Symbol", "Step", "MemWrite",
           "Truncation", "Dump", "build", "run", "memory_at", "АсмОшибка"]
