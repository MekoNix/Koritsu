"""asm.tasm — набор инструментов TASM: TASM + TLINK в DOSBox-X, трасса отладчиком DebugX.

`TOOLCHAIN` — этот набор за общим интерфейсом (`asm.toolchain.Toolchain`). Под ним — прежние
функции `runner.build/run/memory_at` и `tools.find_tools` без изменений поведения: интерфейс
только выбирает версию, проверяет флаги и строит запрос из снимка постановки.

**Версии.** Каталог — то, что код умеет водить (`VERSIONS`). На машине версия — это каталог
инструментов: подкаталог `KORITSU_ASM_TOOLS/<версия>/`, а файлы прямо в корне
`KORITSU_ASM_TOOLS` — версия `KORITSU_ASM_TASM_VERSION` (умолчание `4.1`). Так том, на котором
TASM лежит в корне, продолжает работать без перекладки.

**Запрос.** `TasmRequest` — прежний `RunRequest` с версией: `runner` принимает его как есть, а
версия уезжает в `RunResult.version`. Голый `RunRequest` тоже годится — итог назовёт `4.1`.

Состав:

    tools.py     поиск инструментов
    tasm.py      сообщения TASM/TLINK, листинг, таблица символов
    linkmap.py   карта TLINK: сегменты, точка входа
    debugx.py    разбор вывода DebugX потоком
    feed.py      ввод программы: где читает и что подать
    dosbox.py    запуск DOSBox-X с потолками
    runner.py    сборка, трасса с перезапусками ради ввода, память на шаге
    samples/     настоящий вывод DebugX в DOSBox-X, по которому написан разборщик
"""
from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping, Sequence

from ..model import АсмОшибка, BuildResult, Dump, RunRequest, RunResult
from ..toolchain import Cancelled, Progress, Range, ToolsStatus, VersionInfo
from . import runner, tools as tools_mod
from .runner import build, memory_at, run
from .tools import Tools, find_file, find_tools

ID = "tasm"
VERSIONS = (VersionInfo(id="4.1", title="TASM 4.1 · TLINK 7.1"),)
DEFAULT_VERSION = runner.DEFAULT_VERSION

# Ключи уезжают в командную строку TASM и TLINK внутри DOS. Форма закрыта: косая, буквы,
# цифры и несколько знаков. Всё прочее — пробел, `&`, `>`, `|` — это уже не ключ, а вторая
# команда в сценарии эмулятора.
FLAG = re.compile(r"^/[A-Za-z0-9:=._+-]{1,31}$")
FLAGS_MAX = runner.FLAGS_MAX

_TOOL_NAMES = {"tasm": "TASM", "tlink": "TLINK"}


@dataclass(frozen=True)
class TasmRequest(RunRequest):
    version: str = DEFAULT_VERSION


def root_version(env: Mapping[str, str]) -> str:
    """Версия файлов, лежащих прямо в корне `KORITSU_ASM_TOOLS`."""
    return (env.get("KORITSU_ASM_TASM_VERSION") or "").strip() or DEFAULT_VERSION


def tools_dir(env: Mapping[str, str], version: str) -> Path | None:
    """Каталог инструментов версии или `None`. Файлов внутри не проверяет.

    Версия сверяется с каталогом до того, как стать частью пути: иначе `..` из снимка
    постановки назвало бы любой каталог машины.
    """
    if version not in {v.id for v in VERSIONS}:
        return None
    raw = (env.get("KORITSU_ASM_TOOLS") or "").strip()
    if not raw:
        return None
    root = Path(raw)
    sub = root / version
    if sub.is_dir():
        return sub
    if version == root_version(env) and root.is_dir():
        return root
    return None


class TasmToolchain:
    id = ID
    title = "TASM"
    memory = "segmented"
    stages = ("tasm", "tlink", "trace")
    tools = ("tasm", "tlink")
    versions = VERSIONS
    default_version = DEFAULT_VERSION
    # Флаги — те, с которыми собирает договор ядра: `/zi /l` дают отладочные символы и
    # листинг, `/v` — карту для отладчика.
    default_settings: Mapping[str, object] = MappingProxyType(
        {"tasm_flags": ["/zi", "/l"], "tlink_flags": ["/v"], "mode32": False})
    raw_index = runner.RAW_INDEX
    raw_file = r"^debugx[\w.-]{0,40}\.txt$"
    raw_encoding = "cp437"

    # ── инструменты ──

    def find_tools(self, env: Mapping[str, str], version: str = DEFAULT_VERSION) -> Tools | None:
        directory = tools_dir(env, str(version))
        if directory is None:
            return None
        return find_tools({**env, "KORITSU_ASM_TOOLS": str(directory)})

    def _ready(self, env: Mapping[str, str], version: str) -> bool:
        try:
            return self.find_tools(env, version) is not None
        except Exception:                                    # noqa: BLE001
            return False

    def status(self, env: Mapping[str, str]) -> ToolsStatus:
        """Флаги компонентов — для версии по умолчанию: человеку, который поднимает машину,
        важно знать, чего именно нет, а `find_tools` отвечает на это одним `None`."""
        dosbox = (env.get("KORITSU_ASM_DOSBOX") or "").strip() or tools_mod.DOSBOX_DEFAULT
        try:
            has_dosbox = (os.path.isfile(dosbox) if os.sep in dosbox
                          else shutil.which(dosbox, path=env.get("PATH")) is not None)
        except OSError:
            has_dosbox = False
        try:
            directory = tools_dir(env, DEFAULT_VERSION)
            names = {name.upper() for name in os.listdir(directory)} if directory else set()
        except OSError:
            names = set()
        debugx = (env.get("KORITSU_ASM_DEBUGX") or "").strip() or tools_mod.DEBUGX_DEFAULT
        parts = {"dosbox": has_dosbox,
                 "tasm": "TASM.EXE" in names, "tlink": "TLINK.EXE" in names,
                 "debugx": os.path.isfile(debugx)}
        versions = [(v, self._ready(env, v.id)) for v in VERSIONS]
        return ToolsStatus(available=any(ok for _, ok in versions), parts=parts,
                           versions=versions)

    def check_flags(self, tool: str, flags: Sequence[str]) -> list[str]:
        name = _TOOL_NAMES.get(tool)
        if name is None:
            raise АсмОшибка(f"У TASM нет инструмента {tool!r}")
        if isinstance(flags, (str, bytes)):
            raise АсмОшибка(f"Ключи {name} — список")
        clean = [str(flag).strip() for flag in flags or ()]
        if len(clean) > FLAGS_MAX:
            raise АсмОшибка(f"У {name} больше {FLAGS_MAX} ключей")
        for flag in clean:
            if not FLAG.match(flag):
                raise АсмОшибка(f"Недопустимый ключ {name}: {flag[:40]!r} — ключи пишутся как /x")
        return clean

    # ── прогон ──

    def request(self, snapshot: Mapping[str, object]) -> TasmRequest:
        return TasmRequest(
            source=str(snapshot.get("source") or ""),
            stdin=str(snapshot.get("stdin") or ""),
            step_limit=int(snapshot.get("step_limit") or 100_000),
            mode32=bool(snapshot.get("mode32")),
            tasm_flags=tuple(str(f) for f in (snapshot.get("tasm_flags") or ())),
            tlink_flags=tuple(str(f) for f in (snapshot.get("tlink_flags") or ())),
            version=str(snapshot.get("version") or DEFAULT_VERSION))

    def build(self, req: RunRequest, tools: Tools, workdir: Path, *,
              timeout_s: float) -> BuildResult:
        return build(req, tools, workdir, timeout_s=timeout_s)

    def run(self, req: RunRequest, tools: Tools, workdir: Path, *, timeout_s: float,
            progress: Progress | None = None,
            cancelled: Cancelled | None = None) -> RunResult:
        return run(req, tools, workdir, timeout_s=timeout_s, progress=progress,
                   cancelled=cancelled)

    def memory_at(self, req: RunRequest, tools: Tools, workdir: Path, step: int,
                  ranges: list[Range], *, timeout_s: float) -> list[Dump]:
        if any(not isinstance(r, (tuple, list)) or len(r) != 3 or r[0] is None for r in ranges or ()):
            raise АсмОшибка("Адрес памяти TASM — сегмент и смещение")
        return memory_at(req, tools, workdir, step, [tuple(r) for r in ranges],
                         timeout_s=timeout_s)


TOOLCHAIN = TasmToolchain()

__all__ = ["TOOLCHAIN", "TasmToolchain", "TasmRequest", "Tools", "find_tools", "find_file",
           "build", "run", "memory_at", "tools_dir", "root_version", "VERSIONS",
           "DEFAULT_VERSION", "ID"]
