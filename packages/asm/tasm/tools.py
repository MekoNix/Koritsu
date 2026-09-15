"""tools.py — где лежат DOSBox-X, TASM/TLINK и DebugX.

TASM и TLINK — проприетарные программы Borland: в репозиторий и в образ они не кладутся и
приезжают каталогом с машины выката (`KORITSU_ASM_TOOLS`, в compose — том только для чтения).
DebugX открытый и ставится в образ пинованной версией в `/opt/asm/debugx/`. DOSBox-X — пакет
Debian.

`find_tools` ничего не запускает: только проверяет, что файлы есть. Нет чего-то одного —
`None`, и служба показывает модуль недоступным, а не падает на первом прогоне.
"""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

DEBUGX_DEFAULT = "/opt/asm/debugx/DEBUGX.COM"
DOSBOX_DEFAULT = "dosbox-x"

# Без них сборки нет. Остальное (RTM.EXE, DPMI16BI.OVL у TLINK 7 и TASM 5) у разных версий
# разное, и проверять его по списку значило бы отказывать работающему набору.
REQUIRED = ("TASM.EXE", "TLINK.EXE")


@dataclass(frozen=True)
class Tools:
    dosbox: Path          # исполняемый dosbox-x
    tools_dir: Path       # TASM.EXE, TLINK.EXE (+ всё, что им нужно: RTM.EXE, DPMI16BI.OVL …)
    debugx: Path          # DEBUGX.COM

    def tool_file(self, name: str) -> Path | None:
        """Файл в каталоге инструментов без учёта регистра: DOS имён не различает, а
        каталог, скопированный с Windows, бывает и `tasm.exe`, и `TASM.EXE`."""
        return find_file(self.tools_dir, name)


def find_file(directory: Path, name: str) -> Path | None:
    try:
        for entry in directory.iterdir():
            if entry.name.upper() == name.upper() and entry.is_file():
                return entry
    except OSError:
        return None
    return None


def find_tools(env: Mapping[str, str]) -> Tools | None:
    """Инструменты по окружению или `None`, если чего-то нет.

    KORITSU_ASM_DOSBOX  исполняемый DOSBox-X: путь или имя в PATH (умолч. `dosbox-x`)
    KORITSU_ASM_TOOLS   каталог с TASM.EXE и TLINK.EXE (умолчания нет)
    KORITSU_ASM_DEBUGX  DEBUGX.COM (умолч. /opt/asm/debugx/DEBUGX.COM)
    """
    dosbox_name = (env.get("KORITSU_ASM_DOSBOX") or "").strip() or DOSBOX_DEFAULT
    if os.sep in dosbox_name:
        dosbox = Path(dosbox_name)
        if not (dosbox.is_file() and os.access(dosbox, os.X_OK)):
            return None
    else:
        found = shutil.which(dosbox_name, path=env.get("PATH") or os.environ.get("PATH"))
        if not found:
            return None
        dosbox = Path(found)

    tools_raw = (env.get("KORITSU_ASM_TOOLS") or "").strip()
    if not tools_raw:
        return None
    tools_dir = Path(tools_raw)
    if not tools_dir.is_dir():
        return None
    if any(find_file(tools_dir, name) is None for name in REQUIRED):
        return None

    debugx_raw = (env.get("KORITSU_ASM_DEBUGX") or "").strip() or DEBUGX_DEFAULT
    debugx = Path(debugx_raw)
    if not debugx.is_file():
        found = find_file(debugx.parent, debugx.name) if debugx.parent.is_dir() else None
        if found is None:
            return None
        debugx = found

    return Tools(dosbox=dosbox, tools_dir=tools_dir, debugx=debugx)


__all__ = ["Tools", "find_tools", "find_file", "DEBUGX_DEFAULT", "DOSBOX_DEFAULT", "REQUIRED"]
