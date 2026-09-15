"""asm.mingw64 — набор инструментов MinGW x64: GNU as/ld для Windows x64, трасса по шагам.

Программа — GAS (`.intel_syntax noprefix` у лабы), соглашение Microsoft x64, WinAPI из
kernel32. Сборка — теми же командами, что под MSYS2 (`build.py`); трасса — трассировщиком за
договором `tracer.py`. Память плоская: адреса — 64-битные VA, сегментов нет.

`TOOLCHAIN` — этот набор за общим интерфейсом (`asm.toolchain.Toolchain`).

Состав:

    tools.py     поиск as, ld, libkernel32.a и трассировщика; состояние машины
    flags.py     перечень разрешённых ключей as/ld и запрет чтения файлов из исходника
    build.py     запуск as и ld с потолками, сообщения, итог сборки
    gas.py       листинг `as -a=`: строки, секции, смещения, байты, символы
    pe.py        разбор PE32+: база, точка входа, секции, импорт, символы COFF
    tracer.py    договор трассировщика: Image, RawStep, TraceEnd, NullTracer
    runner.py    сборка → трасса → trace.jsonl и summary.json; память на шаге
    samples/     настоящий листинг, objdump и заголовок PE лабы, собранной binutils 2.44
"""
from __future__ import annotations

from pathlib import Path
from types import MappingProxyType
from typing import Mapping, Sequence

from ..model import BuildResult, Dump, RunResult
from ..toolchain import Cancelled, Progress, Range, ToolsStatus, VersionInfo
from . import runner, tools as tools_mod
from .build import Mingw64Request
from .flags import check_flags
from .tools import VERSION, VERSION_TITLE, Mingw64Tools
from .tracer import Image, NullTracer, RawStep, TraceEnd, TraceLimits, Tracer

ID = runner.TOOLCHAIN_ID
VERSIONS = (VersionInfo(id=VERSION, title=VERSION_TITLE),)
DEFAULT_VERSION = VERSION
STEP_LIMIT_DEFAULT = 20_000


class Mingw64Toolchain:
    id = ID
    title = "MinGW x64"
    memory = "flat"
    stages = ("as", "ld", "trace")
    tools = ("as", "ld")
    versions = VERSIONS
    default_version = DEFAULT_VERSION
    # Ключей по умолчанию нет: лаба собирается голыми `as` и `ld`, остальное ставит ядро.
    default_settings: Mapping[str, object] = MappingProxyType({"as_flags": [], "ld_flags": []})
    raw_index = runner.RAW_INDEX
    raw_file = r"^raw[\w.-]{0,40}\.txt$"
    raw_encoding = "utf-8"

    def status(self, env: Mapping[str, str]) -> ToolsStatus:
        return tools_mod.status(env)

    def find_tools(self, env: Mapping[str, str], version: str = DEFAULT_VERSION) -> Mingw64Tools | None:
        return tools_mod.find_tools(env, str(version))

    def check_flags(self, tool: str, flags: Sequence[str]) -> list[str]:
        return check_flags(tool, flags)

    def request(self, snapshot: Mapping[str, object]) -> Mingw64Request:
        return Mingw64Request(
            source=str(snapshot.get("source") or ""),
            stdin=str(snapshot.get("stdin") or ""),
            step_limit=int(snapshot.get("step_limit") or STEP_LIMIT_DEFAULT),
            version=str(snapshot.get("version") or DEFAULT_VERSION),
            as_flags=tuple(str(f) for f in (snapshot.get("as_flags") or ())),
            ld_flags=tuple(str(f) for f in (snapshot.get("ld_flags") or ())))

    def build(self, req: Mingw64Request, tools: Mingw64Tools, workdir: Path, *,
              timeout_s: float) -> BuildResult:
        return runner.build(req, tools, workdir, timeout_s=timeout_s)

    def run(self, req: Mingw64Request, tools: Mingw64Tools, workdir: Path, *, timeout_s: float,
            progress: Progress | None = None,
            cancelled: Cancelled | None = None) -> RunResult:
        return runner.run(req, tools, workdir, timeout_s=timeout_s, progress=progress,
                          cancelled=cancelled)

    def memory_at(self, req: Mingw64Request, tools: Mingw64Tools, workdir: Path, step: int,
                  ranges: list[Range], *, timeout_s: float) -> list[Dump]:
        return runner.memory_at(req, tools, workdir, step, list(ranges or ()), timeout_s=timeout_s)


TOOLCHAIN = Mingw64Toolchain()

__all__ = ["TOOLCHAIN", "Mingw64Toolchain", "Mingw64Request", "Mingw64Tools", "Image", "RawStep",
           "TraceEnd", "TraceLimits", "Tracer", "NullTracer", "VERSIONS", "DEFAULT_VERSION", "ID"]
