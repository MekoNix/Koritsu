"""tools.py — где лежат GNU as/ld для Windows x64, библиотека импорта kernel32 и трассировщик.

Инструменты — пакеты Debian: `binutils-mingw-w64-x86-64` (`x86_64-w64-mingw32-as`, `-ld`) и
`mingw-w64-x86-64-dev` (`/usr/x86_64-w64-mingw32/lib/libkernel32.a`). Версия у режима одна —
`2.44`, та, что в Debian trixie; строка версии, найденная на машине, показывается подписью.

    KORITSU_ASM_MINGW_PREFIX  префикс имён (умолч. `x86_64-w64-mingw32-`)
    KORITSU_ASM_MINGW_BIN     каталог с `<префикс>as` и `<префикс>ld` (умолч. — поиск в PATH)
    KORITSU_ASM_MINGW_LIB     каталог с `libkernel32.a` (умолч. `/usr/x86_64-w64-mingw32/lib`)

`find_tools` ничего не запускает: только проверяет, что файлы есть. Трассировщик в
готовность сборки не входит — без него `find_tools` всё равно отдаёт инструменты, сборка
идёт, а трасса отвечает `АсмОшибка` (`tracer.NullTracer`). Готов ли режим целиком, говорит
`status()`.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

from ..toolchain import ToolsStatus, VersionInfo
from .tracer import NullTracer, Tracer

PREFIX_DEFAULT = "x86_64-w64-mingw32-"
LIB_DEFAULT = "/usr/x86_64-w64-mingw32/lib"
KERNEL32 = "libkernel32.a"

VERSION = "2.44"
VERSION_TITLE = "GNU as/ld 2.44 · UCRT64"

# Префикс становится частью имени файла: без каталогов и `..`.
_PREFIX = re.compile(r"^[A-Za-z0-9_.+-]{0,64}$")
VERSION_TIMEOUT_S = 5.0


@dataclass(frozen=True)
class Mingw64Tools:
    prefix: str = PREFIX_DEFAULT          # 'x86_64-w64-mingw32-' → as, ld
    bin_dir: Path | None = None           # None — из PATH
    lib_dir: Path = Path(LIB_DEFAULT)     # libkernel32.a
    tracer: Tracer = field(default_factory=NullTracer)

    def executable(self, name: str, search_path: str | None = None) -> str | None:
        """Полный путь к `<префикс><name>` или `None`."""
        filename = self.prefix + name
        if self.bin_dir is not None:
            path = self.bin_dir / filename
            return str(path) if path.is_file() and os.access(path, os.X_OK) else None
        return shutil.which(filename, path=search_path or os.environ.get("PATH"))


def _settings(env: Mapping[str, str]) -> tuple[str, Path | None, Path] | None:
    prefix = env.get("KORITSU_ASM_MINGW_PREFIX")
    prefix = PREFIX_DEFAULT if prefix is None or not prefix.strip() else prefix.strip()
    if not _PREFIX.match(prefix) or ".." in prefix:
        return None
    bin_raw = (env.get("KORITSU_ASM_MINGW_BIN") or "").strip()
    lib_raw = (env.get("KORITSU_ASM_MINGW_LIB") or "").strip() or LIB_DEFAULT
    return prefix, (Path(bin_raw) if bin_raw else None), Path(lib_raw)


def find_tracer(env: Mapping[str, str]) -> Tracer:
    """Трассировщик машины.

    Задан `KORITSU_ASM_MINGW_QUEUE` и исполнитель жив (свежее сердцебиение в очереди) —
    клиент очереди `runner_client.QueueTracer`: программа исполняется в контейнере
    `asm-runner`, а не здесь. Иначе — `NullTracer`: трасса и память отвечают «трассировщик не
    установлен», сборка работает."""
    queue = (env.get("KORITSU_ASM_MINGW_QUEUE") or "").strip()
    if not queue:
        return NullTracer()
    from .runner_client import QueueTracer
    objdump = None
    settings = _settings(env)
    if settings is not None:
        prefix, bin_dir, lib_dir = settings
        objdump = Mingw64Tools(prefix=prefix, bin_dir=bin_dir, lib_dir=lib_dir) \
            .executable("objdump", env.get("PATH"))
    tracer = QueueTracer(Path(queue), objdump=objdump)
    if not tracer.status(env).get("ready"):
        return NullTracer()
    return tracer


def find_tools(env: Mapping[str, str], version: str = VERSION) -> Mingw64Tools | None:
    """Инструменты по окружению или `None`, если нет `as`, `ld` или `libkernel32.a`."""
    if str(version) != VERSION:
        return None
    settings = _settings(env)
    if settings is None:
        return None
    prefix, bin_dir, lib_dir = settings
    if bin_dir is not None and not bin_dir.is_dir():
        return None
    probe = Mingw64Tools(prefix=prefix, bin_dir=bin_dir, lib_dir=lib_dir)
    search = env.get("PATH")
    if probe.executable("as", search) is None or probe.executable("ld", search) is None:
        return None
    if not (lib_dir / KERNEL32).is_file():
        return None
    return Mingw64Tools(prefix=prefix, bin_dir=bin_dir, lib_dir=lib_dir, tracer=find_tracer(env))


_version_cache: dict[tuple[str, float], str] = {}


def version_line(as_path: str) -> str:
    """Первая строка `as --version` (`GNU assembler (GNU Binutils) 2.44`), запомненная по пути и
    времени файла: состояние спрашивают на каждый заход на страницу, а инструмент меняется
    только с образом."""
    try:
        key = (as_path, os.stat(as_path).st_mtime)
    except OSError:
        return ""
    if key in _version_cache:
        return _version_cache[key]
    try:
        done = subprocess.run([as_path, "--version"], capture_output=True, timeout=VERSION_TIMEOUT_S,
                              env={"PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8",
                                   "LC_ALL": "C.UTF-8"},
                              stdin=subprocess.DEVNULL, check=False)
        line = done.stdout.decode("utf-8", "replace").split("\n", 1)[0].strip()
    except (OSError, subprocess.SubprocessError, ValueError):
        line = ""
    _version_cache[key] = line
    return line


def status(env: Mapping[str, str]) -> ToolsStatus:
    """Что есть на машине: `as`, `ld`, `kernel32`, `tracer`. Не бросает."""
    parts = {"as": False, "ld": False, "kernel32": False, "tracer": False}
    detail = ""
    try:
        settings = _settings(env)
        if settings is not None:
            prefix, bin_dir, lib_dir = settings
            probe = Mingw64Tools(prefix=prefix, bin_dir=bin_dir, lib_dir=lib_dir)
            search = env.get("PATH")
            as_path = probe.executable("as", search)
            parts["as"] = as_path is not None
            parts["ld"] = probe.executable("ld", search) is not None
            parts["kernel32"] = (lib_dir / KERNEL32).is_file()
            if as_path is not None:
                detail = version_line(as_path)
        parts["tracer"] = bool(find_tracer(env).status(env).get("ready"))
    except Exception:                                        # noqa: BLE001
        pass
    available = all(parts.values())
    return ToolsStatus(available=available, parts=parts,
                       versions=[(VersionInfo(id=VERSION, title=VERSION_TITLE, detail=detail),
                                  available)])


__all__ = ["Mingw64Tools", "find_tools", "find_tracer", "status", "version_line",
           "PREFIX_DEFAULT", "LIB_DEFAULT", "KERNEL32", "VERSION", "VERSION_TITLE"]
