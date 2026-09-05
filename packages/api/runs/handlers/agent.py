"""
agent — прогон уровня 3: модель работает инструментами и ставит значения сама.

    payload   {"endpoint": "deepseek", "task": "…", "keys": [...],
               "max_steps": 12, "overwrite": false}
    result    {"filled": [...], "outcome": "done", "steps": 7, "calls": 11,
               "problems": N, "task_chars": 240, "key_source": "own"}

**`task` уезжает в модель недоверенным куском в рамке**: задача для агента
приходит из запроса, потолок — 15 000 знаков. Проводится он
`orchestrator.fill_agent(task=…)` той же дверью, что условие задачи и пожелания
человека (`prompt.data_parts`): текст писал не мы, и стоять рядом с нашими
указаниями он не имеет права — рамка заведена ровно для этого.

Потолок — `ЗАДАЧА_МАКС` знаков, и меряется он **знаками**, а не байтами: число
названо владельцем в знаках, и мерить его байтами значило бы пускать вдвое
меньше кириллицы, чем обещано. Длиннее — `400 task_too_long`, как `note_required`
у переделки: проверка формы `payload` живёт в обработчике, который эту форму и
читает, а не в маршруте, который про виды заданий ничего не знает.

**Текст ответа — одним куском.** У петли инструментов потока наружу нет
(`llm.run_tools` возвращает `Result`), поэтому кадр `text` здесь один, в конце.
Тот же случай, что у уровня 1, и по той же причине; подробности — в
`fill_tag.py`.

Отмена спрашивается проводом (`cancel=`): `run_tools` проверяет её перед каждым
ходом, а ход — это отдельный вызов модели, то есть отдельные деньги.

**Прогон, кончившийся не «готово», роняет задание** (`502 run_failed`).
Раньше такое задание уезжало наружу `done` с
`result.ok=false`, и человек читал «готово» над пустым списком поставленных
тегов. Форма отказа — та же, что у уровня 1 (`fill_tag`), и код тот же: беда
здесь не службы, а прогона, и различать их по уровню человеку незачем.
"""
from __future__ import annotations

import orchestrator

from ...errors import ApiError
from ...jobs.registry import AGENT, register
from .common import Прогон, отменено

AGENT_REFUSED = "agent_refused"
TASK_TOO_LONG = "task_too_long"
RUN_FAILED = "run_failed"

# Потолок задачи от человека в знаках.
ЗАДАЧА_МАКС = 15_000


def прогнать_агента(ctx) -> dict:
    """Уровень 3 целиком: инструменты, ходы, поставленные значения."""
    payload = ctx.job.payload or {}
    ключи = payload.get("keys") or None
    if ключи is not None:
        ключи = [str(k) for k in ключи]
    шагов = payload.get("max_steps")
    задача = _задача(payload)

    with Прогон(ctx) as прогон:
        ctx.progress(0, int(шагов or 0), note="agent")
        if ctx.cancelled():
            return отменено(ctx, "agent")
        try:
            итог = orchestrator.fill_agent(
                прогон.project, endpoint=прогон.ep, keys=ключи,
                cancel=прогон.отмена, task=задача,
                max_steps=int(шагов) if шагов else None,
                overwrite=bool(payload.get("overwrite")))
        except orchestrator.OrchestratorError as беда:
            raise ApiError(AGENT_REFUSED, str(беда), 409,
                           where="body.payload") from None
        прогон.текст(итог.text)
        for ключ in итог.filled:
            # Событие на каждый поставленный тег — та же форма, что у уровня 2:
            # интерфейс рисует их одним списком и не должен знать, каким
            # уровнем тег поставлен. Номера версии здесь нет: петля ставит
            # значения инструментом, и `TagFill` наружу не отдаёт.
            ctx.emit({"kind": "tag_closed", "key": ключ, "ok": True,
                      "version": None, "flags": []})
        ctx.progress(итог.steps, итог.steps, note="agent")

    if not итог.ok and not ctx.cancelled():
        # Отмена сюда не попадает намеренно: остановил прогон человек, и
        # `cancelled` — это его действие, а не беда. Объявить его `failed`
        # значило бы показать тревожный тост в ответ на нажатую им же кнопку.
        #
        # Прогон кончился не «готово»: модель оборвалась, отказалась или упёрлась
        # в потолок ходов. Задание при этом сделало всё, о чём его просили, — и
        # раньше уезжало наружу как `done`, а человек читал «готово» под пустым
        # списком поставленных тегов. Такое задание считается упавшим.
        # Форма та же, что у уровня 1 (`fill_tag`): код один на
        # оба уровня, а чем именно кончилось — словом `outcome`, потому что
        # «оборвался» и «отказался» человек чинит по-разному.
        #
        # Стоит это после `with`: события хода и поставленные теги уже уехали в
        # поток, и падение задания их не отменяет — закрытое сохранено.
        raise ApiError(RUN_FAILED,
                       f"The agent run ended as '{итог.outcome}', not 'done'",
                       502, where="body.payload.task")
    return {"filled": list(итог.filled), "outcome": итог.outcome,
            "ok": bool(итог.ok), "steps": итог.steps, "calls": итог.calls,
            "problems": len(итог.problems), "stop": итог.stop,
            "run": getattr(итог.run, "id", None),
            "task_chars": len(задача),
            "key_source": прогон.источник}


def _задача(payload: dict) -> str:
    """Задача от человека из `payload` или пусто. Длиннее потолка — отказ.

    Отказ, а не обрезка: обрезанная посередине задача — это другая задача, и
    молча подменять её значило бы отвечать человеку прогоном не по его просьбе.
    Пустая и отсутствующая — одно и то же: куска в промпте не будет ни в том, ни
    в другом случае (`prompt.data_parts` пустой текст пропускает).
    """
    задача = str(payload.get("task") or "").strip()
    if len(задача) > ЗАДАЧА_МАКС:
        raise ApiError(TASK_TOO_LONG,
                       f"task must be at most {ЗАДАЧА_МАКС} characters, "
                       f"got {len(задача)}", 400,
                       where="body.payload.task")
    return задача


def _зарегистрировать() -> None:
    """См. `fill_tag._зарегистрировать` — довод тот же."""
    register(AGENT, needs_secret=True)(прогнать_агента)


__all__ = ["прогнать_агента", "_зарегистрировать", "AGENT_REFUSED",
           "TASK_TOO_LONG", "RUN_FAILED", "ЗАДАЧА_МАКС"]
