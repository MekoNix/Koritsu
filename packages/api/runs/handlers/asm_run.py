"""
asm_run — сборка программы и трасса её выполнения.

    payload   {"run_id": "<программа>", "run_no": 3, "mode": "build" | "run"}
    result    {"run_no": 3, "status": "done", "steps": 1834, "ms": 2210}

Что собирать, берётся не из `payload`, а из снимка постановки в каталоге
прогона (`request.json`): его кладёт маршрут `POST …/runs` до постановки
задания, и в `payload` поэтому только номер. Исходник в `payload` означал бы
программу строкой в базе у каждого задания очереди, а место содержимому — на
томе (`jobs/models.py`).

**Итог — на томе, а не в `result`.** `summary.json` пишет ядро или
`orchestrator.asm.run`; окно прогона читает его маршрутом `GET …/runs/{n}`. В
`result` — только статус и числа, чтобы карточка задания говорила, чем кончилось.

**Прогресс — этапами** `tasm` → `tlink` → `trace` (для трассы — шаги из лимита).
Ядро сообщает о ходе на каждом шаге, а шагов бывает полмиллиона: запись в базу
на каждый — это полмиллиона транзакций и потолок событий задания за секунду.
Поэтому этап пишется сразу, как сменился, а ход внутри этапа — не чаще раза в
полсекунды.

**Отмена** спрашивается у базы тем же `Отмена`, что у прогонов модели: ядро
спрашивает её между шагами, и ответ «нет» живёт четверть секунды.

Секрета этому виду не достаётся (`needs_secret=False`): в эмуляторе исполняется
чужая программа, и рядом с ней не должно быть того, чем расшифровываются ключи.
"""
from __future__ import annotations

import time

from orchestrator import asm as ассемблер

from ...errors import ApiError, NOT_FOUND
from ...jobs.registry import ASM_RUN, register
from .common import Отмена, отменено

# Не чаще чем раз в столько секунд ход внутри этапа уезжает в базу.
ХОД_С = 0.5


class Ход:
    """Прогресс ядра `(этап, n, всего)` → `ctx.progress`, прореженный по времени."""

    def __init__(self, ctx, период: float = ХОД_С):
        self.ctx = ctx
        self._период = float(период)
        self._этап: str | None = None
        self._когда = 0.0
        self.последний: tuple[str, int, int] = ("tasm", 0, 1)

    def __call__(self, этап: str, n: int, всего: int) -> None:
        этап = str(этап or "")
        self.последний = (этап, int(n), int(всего))
        момент = time.monotonic()
        if этап == self._этап and момент - self._когда < self._период:
            return
        self._этап, self._когда = этап, момент
        self.ctx.progress(int(n), max(1, int(всего)), note=этап)


def собрать_и_запустить(ctx) -> dict:
    """Собрать программу прогона и, в режиме `run`, снять трассу."""
    from ...modules.asm.routes import инструменты, номер_прогона  # noqa: PLC0415

    payload = ctx.job.payload or {}
    номер = номер_прогона(payload.get("run_no"), where="body.payload.run_no")
    if not ctx.solution:
        raise ApiError("invalid_value", "payload.run_id names the program", 400,
                       where="body.payload.run_id")
    найдено = инструменты(ctx.settings, where="body.payload")
    проект = ctx.project
    if not ассемблер.run_exists(проект, номер):
        raise ApiError(NOT_FOUND, "Run not found", 404,
                       where="body.payload.run_no")

    ход = Ход(ctx)
    ход("tasm", 0, 1)
    отмена = Отмена(ctx)
    if отмена():
        return отменено(ctx, "tasm")

    итог = ассемблер.run(проект, номер, tools=найдено,
                         timeout_s=float(ctx.settings.asm_timeout_s),
                         progress=ход, cancelled=отмена)

    всего = итог.get("totals") if isinstance(итог.get("totals"), dict) else {}
    этап, n, из = ход.последний
    ctx.progress(n, max(1, из), note=этап)
    return {"run_no": номер, "status": str(итог.get("status") or ""),
            "steps": int(всего.get("steps") or 0),
            "ms": int(всего.get("ms") or 0)}


def _зарегистрировать() -> None:
    """См. `fill_tag._зарегистрировать` — довод тот же."""
    register(ASM_RUN, needs_secret=False)(собрать_и_запустить)


__all__ = ["собрать_и_запустить", "_зарегистрировать", "Ход", "ХОД_С"]
