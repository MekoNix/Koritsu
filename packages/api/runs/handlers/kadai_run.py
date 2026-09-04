"""
kadai_run — сценарий работы над документом: семь стадий от условия до архива.

    payload   {"endpoint": "deepseek",
               "wishes": {"text": "…", "show_task": true,
                          "show_structure": false},
               "until": "тексты"}
    result    {"work": "w-…", "state": "running", "stage": "тексты",
               "stages": [{"name": …, "state": …}, …],
               "outputs": {...}, "key_source": "shared"}

**Сценарий зовётся через `orchestrator.kadai`, а не напрямую.** `api` не
импортирует `kadai` ни одной строкой: соседей знает только оркестратор (решение
2026-08-31), и обработчик задания — последнее место, где эту стрелку стоило бы
разворачивать. Обёртки живут в `orchestrator/kadai.py` и там же объяснены.

**Стадия — единица доклада.** После каждой в поток уезжает событие `stage`, а в
`progress` — «сделано N из семи». Одним куском на весь прогон это выглядело бы
как зависшая полоска на полчаса: сценарий идёт стадиями по нескольку минут, и
человек смотрит именно на них.

**Отмена спрашивается между стадиями.** Внутри стадии её ловит провод
(`common.Отмена` уезжает дверям через endpoint), а между — мы: там остановка
ничего не стоит, потому что ход работы сохраняется после каждой стадии
(`status.save`), и повторный запуск продолжит с той же точки.
"""
from __future__ import annotations

from orchestrator import kadai as сценарий

from ...errors import ApiError
from ...jobs.registry import KADAI_RUN, register
from .common import Прогон, отменено

KADAI_FAILED = "kadai_failed"
UNKNOWN_STAGE = "unknown_stage"


def прогнать(ctx) -> dict:
    """Пройти стадии сценария, докладывая о каждой."""
    payload = ctx.job.payload or {}
    пожелания = _пожелания(payload.get("wishes"))
    до = str(payload.get("until") or "").strip() or None
    имена = сценарий.stage_names()
    if до is not None and до not in имена:
        raise ApiError(UNKNOWN_STAGE,
                       f"payload.until must be one of: {', '.join(имена)}",
                       400, where="body.payload.until")

    сделано = [0]
    with Прогон(ctx) as прогон:
        ctx.progress(0, len(имена), note="")
        if ctx.cancelled():
            return отменено(ctx, "")

        def на_стадию(имя: str, снимок: dict) -> None:
            сделано[0] += 1
            состояние = _состояние(снимок, имя)
            прогон.стадия(имя, состояние, note=str(снимок.get("current") or ""))
            ctx.progress(сделано[0], len(имена), note=имя)

        try:
            снимок = сценарий.work(прогон.project, endpoint=прогон.ep,
                                   wishes=пожелания, until=до,
                                   on_stage=на_стадию, stop=ctx.cancelled)
        except Exception as беда:                            # noqa: BLE001
            # Сценарий бросает своё (`KadaiError`, `NotReady`), и ловить его по
            # имени значило бы импортировать `kadai` — ровно то, чего этот
            # модуль не делает. Текст уезжает наружу: он по-русски, написан для
            # человека и путей на томе не содержит (`kadai/errors.py`).
            raise ApiError(KADAI_FAILED, str(беда), 422,
                           where="body.payload") from None

    return {"work": снимок.get("work"), "state": снимок.get("state"),
            "stage": снимок.get("stage"),
            "stages": [{"name": st.get("name"), "state": st.get("state")}
                       for st in (снимок.get("stages") or ())],
            "hold": снимок.get("hold"),
            "outputs": dict(снимок.get("outputs") or {}),
            "problems": len(снимок.get("problems") or ()),
            "key_source": прогон.источник}


def _пожелания(сырое) -> dict:
    """Пожелания человека из `payload`, приведённые к полям `kadai.Wishes`.

    Приводим здесь, а не отдаём словарь как есть: лишний ключ уронил бы
    `Wishes(**...)` беспричинным `TypeError`, а список полей — договор
    сценария, и повторять его в клиенте незачем.
    """
    сырое = сырое if isinstance(сырое, dict) else {}
    return {"text": str(сырое.get("text") or ""),
            "show_task": bool(сырое.get("show_task")),
            "show_structure": bool(сырое.get("show_structure"))}


def _состояние(снимок: dict, имя: str) -> str:
    for st in снимок.get("stages") or ():
        if st.get("name") == имя:
            return str(st.get("state") or "")
    return ""


def _зарегистрировать() -> None:
    """См. `fill_tag._зарегистрировать` — довод тот же."""
    register(KADAI_RUN, needs_secret=True)(прогнать)


__all__ = ["прогнать", "_зарегистрировать", "KADAI_FAILED", "UNKNOWN_STAGE"]
