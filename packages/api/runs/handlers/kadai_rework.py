"""
kadai_rework — замечание человека к готовой работе и минимальный пересчёт.

    payload   {"endpoint": "deepseek", "note": "введение не про то",
               "run_id": "<решение работы>", "block": "b-03", "kind": "кусок"}
    result    {"kind": "кусок", "block": "b-03", "stages": [...],
               "honest": "…", "state": "running", "stage": "тексты"}

Что переигрывается по замечанию, решает `kadai.rework` и только он: маршруты
(«кусок», «код», «схема», «структура», «условие»), их честная цена и запрет
угадывать маршрут по словам замечания записаны там. Здесь — обёртка задания:
ключ, лимит, события стадий.

**Какое решение переигрывается, говорит `run_id`** — то же поле и тот же
читатель (`JobContext.project`), что у `kadai_run`.

**Ни `block`, ни `kind` мы не додумываем.** Сценарий отказывает на замечании без
адреса, и отказ этот проводится наружу как есть (`422 kadai_failed`): угаданный
маршрут переписал бы не то, и узнал бы человек об этом по счёту.

**Остановка и ход — как у `kadai_run`.** `common.Отмена` уезжает дверям
сценария, поэтому кнопка «Остановить» действует и посреди переделки; события
`step` рассказывают, что делается сейчас. Остановленная переделка не роняет
работу: стадия возвращается в «ждёт», работа — в «остановлена», и повторное
замечание (или прогон) продолжает с неё.
"""
from __future__ import annotations

from orchestrator import kadai as сценарий

from ...errors import ApiError
from ...jobs.registry import KADAI_REWORK, register
from .common import Прогон, беда_словами, отменено

NOTE_REQUIRED = "note_required"
KADAI_FAILED = "kadai_failed"


def переиграть(ctx) -> dict:
    """Замечание → пересчёт → снимок хода работы."""
    payload = ctx.job.payload or {}
    замечание = str(payload.get("note") or "").strip()
    if not замечание:
        raise ApiError(NOTE_REQUIRED,
                       "payload.note must carry the remark to act on", 400,
                       where="body.payload.note")
    блок = str(payload.get("block") or "").strip() or None
    вид = str(payload.get("kind") or "").strip() or None

    with Прогон(ctx) as прогон:
        ctx.progress(0, 1, note=вид or блок or "rework")
        if ctx.cancelled():
            return отменено(ctx, "rework")

        стадия = [""]

        def на_ход(ход: dict) -> None:
            # То же, что в `kadai_run`: стадию называет сценарий, а ход петли
            # приходит из слоя инструментов, который про стадии не знает.
            имя = str(ход.get("stage") or "")
            if имя:
                стадия[0] = имя
            прогон.ход({**ход, "stage": имя or стадия[0]})

        try:
            итог = сценарий.rework(прогон.project, endpoint=прогон.ep,
                                   note=замечание, block=блок, kind=вид,
                                   on_step=на_ход, stop=прогон.отмена)
        except Exception as беда:                            # noqa: BLE001
            # Тот же довод, что в `kadai_run`: ловить сценарий по имени класса
            # значило бы импортировать `kadai` из службы, а текст беды
            # приводится к одной русской фразе (`common.беда_словами`).
            raise ApiError(KADAI_FAILED, беда_словами(беда), 422,
                           where="body.payload") from None
        снимок = итог.get("snapshot") or {}
        for st in снимок.get("stages") or ():
            прогон.стадия(str(st.get("name") or ""), str(st.get("state") or ""))
        ctx.progress(1, 1, note=вид or блок or "rework")

    решено = итог.get("rework") or {}
    return {"kind": решено.get("kind"), "block": решено.get("block"),
            "stages": list(решено.get("stages") or ()),
            "honest": решено.get("honest"), "note": решено.get("note"),
            "state": снимок.get("state"), "stage": снимок.get("stage")}


def _зарегистрировать() -> None:
    """См. `fill_tag._зарегистрировать` — довод тот же."""
    register(KADAI_REWORK, needs_secret=True)(переиграть)


__all__ = ["переиграть", "_зарегистрировать", "NOTE_REQUIRED", "KADAI_FAILED"]
