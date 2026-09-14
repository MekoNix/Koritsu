"""
asm — модуль «Ассемблер»: TASM и TLINK в DOSBox-X, отладка по трассе DebugX.

Человек пишет программу для DOS, собирает её настоящими TASM и TLINK и получает
трассу всей программы за один прогон: браузер ходит по ней сам — вперёд,
назад, до курсора, до точки останова, — и ни один шаг не стоит запроса к
эмулятору. Ввод программы задаётся заранее, паузы нет, вместо неё — лимит
шагов. Рядом — агент, который объясняет программу по цифрам трассы.

Файлы:

    routes.py                             программы, исходник, прогоны, переписка
    ../../runs/handlers/asm_run.py        сборка и трасса — задание очереди
    ../../runs/handlers/asm_memory.py     дамп памяти на шаге
    ../../runs/handlers/asm_chat.py       агент по трассе
    ../../../orchestrator/asm.py          каталог прогонов, ядро, контекст агента

**Программа — решение работы**, как доска: запись журнала и каталог под ней
(`routes.py` объясняет подробно).

**Без инструментов модуля нет.** TASM и TLINK проприетарные и в образ не
кладутся: их каталог приходит с машины выката. Машина без них показывать модуль
не должна — пункт сайдбара, за которым любая кнопка отвечает «нечем собрать»,
хуже его отсутствия. Решается это при сборке реестра, по окружению процесса, а
не по `Settings`: реестр модулей наполняется раньше, чем есть приложение с
настройками, и читает те же переменные `KORITSU_ASM_*`, что и настройки.
`KORITSU_ASM_SHOW` показывает модуль и без инструментов — сайт в разработке
верстают на машине без TASM.
"""
from __future__ import annotations

import os

from orchestrator import asm as ассемблер

from .. import ModuleInfo
from ...errors import ConfigError
from ...log import беды
from ...settings import _bool
from .routes import router, окружение_инструментов


def _готов() -> bool:
    """Показывать ли модуль: инструменты найдены или показ включён настройкой."""
    try:
        if _bool(os.environ, "ASM_SHOW", False):
            return True
    except ConfigError:
        # Мусор в переменной служба увидит при чтении настроек и откажется
        # стартовать сама; реестр второй раз об этом не кричит.
        return False
    env = окружение_инструментов(
        (os.environ.get("KORITSU_ASM_TOOLS") or "").strip(),
        (os.environ.get("KORITSU_ASM_DOSBOX") or "").strip(),
        (os.environ.get("KORITSU_ASM_DEBUGX") or "").strip())
    try:
        return bool(ассемблер.tools_status(env)["available"])
    except Exception:                                        # noqa: BLE001
        беды.exception("ассемблер: состояние инструментов не читается")
        return False


MODULE = ModuleInfo(id="asm", title="Assembler", ready=_готов(),
                    routes_prefix="/api/asm")

__all__ = ["MODULE", "router"]
