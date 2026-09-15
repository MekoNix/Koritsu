"""toolchain.py — набор инструментов: общий интерфейс TASM и MinGW x64.

Набор — это всё, что отличает один режим «Ассемблера» от другого: где лежат инструменты и
какие у них версии, как проверяются флаги сборки, как из снимка постановки (`request.json`)
получается запрос, как идут сборка, трасса и память на шаге. Формы ответа (`model.py`) и
запись трассы (`sink.py`) у наборов общие, поэтому служба читает итоги и трассы любого
режима одним кодом, а выбирает набор только по `toolchain` из снимка.

Запрос и найденные инструменты у каждого набора свои (`RunRequest` TASM не похож на запрос
MinGW x64), и здесь они — `object`: служба их не разбирает, а только передаёт из
`request()`/`find_tools()` обратно в тот же набор.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Protocol, Sequence

from .model import BuildResult, Dump, RunResult

# Ход прогона: (этап, n, всего). Этапы — `Toolchain.stages`.
Progress = Callable[[str, int, int], None]
# Спрашивается между шагами: `True` — прогон отменён.
Cancelled = Callable[[], bool]
# Диапазон памяти (seg, off, len): seg — hex сегмента или `None` у плоской памяти, off — hex.
Range = tuple[str | None, str, int]


@dataclass(frozen=True)
class VersionInfo:
    id: str                  # '4.1'
    title: str               # 'TASM 4.1 · TLINK 7.1'
    detail: str = ""         # строка версии, найденная на машине ('GNU as 2.44')


@dataclass(frozen=True)
class ToolsStatus:
    available: bool                              # собрать и протрассировать можно
    parts: dict[str, bool]                       # компонент → есть ли он на машине
    versions: list[tuple[VersionInfo, bool]]     # каталог версий и готовность каждой


class Toolchain(Protocol):
    id: str                                  # 'tasm' | 'mingw64'
    title: str                               # 'TASM' | 'MinGW x64'
    memory: str                              # 'segmented' | 'flat'
    stages: tuple[str, str, str]             # ('tasm', 'tlink', 'trace') | ('as', 'ld', 'trace')
    tools: tuple[str, str]                   # ('tasm', 'tlink') | ('as', 'ld')
    versions: tuple[VersionInfo, ...]        # каталог: какие версии код умеет водить
    default_version: str
    # Настройки сборки новой программы. Только для чтения: служба копирует их себе.
    default_settings: Mapping[str, object]
    raw_index: str                           # 'debugx.idx.json' | 'raw.idx.json'
    raw_file: str                            # регулярка имён файлов сырого вывода
    raw_encoding: str                        # 'cp437' | 'utf-8'

    def status(self, env: Mapping[str, str]) -> ToolsStatus:
        """Что есть на машине. Ничего не запускает и не бросает."""
        ...

    def find_tools(self, env: Mapping[str, str], version: str) -> object | None:
        """Инструменты версии или `None`, если чего-то нет."""
        ...

    def check_flags(self, tool: str, flags: Sequence[str]) -> list[str]:
        """Чистые флаги инструмента `tool` (из `tools`) или `АсмОшибка`."""
        ...

    def request(self, snapshot: Mapping[str, object]) -> object:
        """Запрос ядра из снимка постановки (`request.json`)."""
        ...

    def build(self, req, tools, workdir: Path, *, timeout_s: float) -> BuildResult:
        ...

    def run(self, req, tools, workdir: Path, *, timeout_s: float,
            progress: Progress | None = None,
            cancelled: Cancelled | None = None) -> RunResult:
        ...

    def memory_at(self, req, tools, workdir: Path, step: int, ranges: list[Range],
                  *, timeout_s: float) -> list[Dump]:
        ...


__all__ = ["Toolchain", "VersionInfo", "ToolsStatus", "Progress", "Cancelled", "Range"]
