"""
asm_memory — дамп памяти программы на шаге трассы.

    payload   {"run_id": "<программа>", "run_no": 3, "step": 5210,
               "ranges": [{"seg": "0B7E", "off": "0000", "len": 256}]}
    result    {"run_no": 3, "step": 5210,
               "dumps": [{"step": 5210, "seg": "0B7E", "off": "0000", "hex": "…"}]}

Трасса записывает память на каждом шаге только в начале длинного прогона; дальше
окно «Дамп» спрашивает нужные ячейки этим заданием. Ядро перезапускает ту же
программу с тем же вводом до шага и снимает дамп: другой ввод дал бы другую
память, поэтому исходник и ввод берутся из снимка прогона, а не из записей
программы.

Дамп — в `result`, а не на томе: это несколько сотен байт, которые окно читает
один раз, и отдельный файл на каждый вопрос «что в этой ячейке» плодил бы мусор
в каталоге прогона.

Секрета виду не достаётся — довод тот же, что у `asm_run`.
"""
from __future__ import annotations

from orchestrator import asm as ассемблер

from ...errors import ApiError, NOT_FOUND
from ...jobs.registry import ASM_MEMORY, register
from .common import беда_словами, отменено

ASM_FAILED = "asm_failed"


def снять_дамп(ctx) -> dict:
    """Перезапустить трассу до шага и снять дамп названных диапазонов."""
    from ...modules.asm.routes import (диапазоны, инструменты,  # noqa: PLC0415
                                       номер_прогона)

    payload = ctx.job.payload or {}
    номер = номер_прогона(payload.get("run_no"), where="body.payload.run_no")
    шаг = payload.get("step")
    if not isinstance(шаг, int) or isinstance(шаг, bool) or шаг < 0:
        raise ApiError("invalid_value", "payload.step is a step number from 0",
                       400, where="body.payload.step")
    куски = диапазоны(payload.get("ranges"), where="body.payload.ranges")
    if not ctx.solution:
        raise ApiError("invalid_value", "payload.run_id names the program", 400,
                       where="body.payload.run_id")
    найдено = инструменты(ctx.settings, where="body.payload")
    проект = ctx.project
    if not ассемблер.run_exists(проект, номер):
        raise ApiError(NOT_FOUND, "Run not found", 404,
                       where="body.payload.run_no")

    ctx.progress(0, 1, note="memory")
    if ctx.cancelled():
        return отменено(ctx, "memory")
    try:
        дампы = ассемблер.memory(проект, номер, шаг, куски, tools=найдено,
                                 timeout_s=float(ctx.settings.asm_timeout_s))
    except Exception as беда:                                # noqa: BLE001
        # Ядро бросает своё, и ловить его по имени службе незачем: написанное
        # для человека уезжает как есть, остальное — одной фразой.
        raise ApiError(ASM_FAILED, беда_словами(беда), 422,
                       where="body.payload") from None
    ctx.progress(1, 1, note="memory")
    return {"run_no": номер, "step": шаг, "dumps": дампы}


def _зарегистрировать() -> None:
    """См. `fill_tag._зарегистрировать` — довод тот же."""
    register(ASM_MEMORY, needs_secret=False)(снять_дамп)


__all__ = ["снять_дамп", "_зарегистрировать", "ASM_FAILED"]
