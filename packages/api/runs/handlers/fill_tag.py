"""
fill_tag — заполнить один тег. Уровень 1 оркестратора, обёрнутый в задание.

    payload   {"key": "цель", "endpoint": "deepseek", "overwrite": false}
    result    {"key": …, "version": 3, "ok": true, "key_source": "own",
               "flags": [...], "stop": "end_turn"}

**Текст уезжает одним куском, а не по мере генерации, и это не недоделка.**
Уровень 1 зовёт `llm.generate_value` — вызов без потока (`llm/api.py`:
«лестницы с повторами в потоке нет намеренно: повтор посреди потока означал бы,
что напечатанное надо стереть»). Потока у него нет вовсе, значит и склеивать
нечего: событие `text` пишется одно, когда значение готово. Обещание «текст
по мере генерации» относится к прогону всего отчёта, где поток есть, — и там оно
исполнено (`fill_report.py`).

Отказ оркестратора («тег заполняет не модель», «значение написано человеком»)
— это `409 tag_refused`, а не беда обработчика: человек попросил невозможное, и
сказать ему об этом надо словами, а не `handler_failed`.
"""
from __future__ import annotations

import json

import orchestrator

from ...errors import ApiError
from ...jobs.registry import FILL_TAG, register
from .common import Прогон, отменено

TAG_REFUSED = "tag_refused"
RUN_FAILED = "run_failed"
KEY_REQUIRED = "key_required"


def заполнить_тег(ctx) -> dict:
    """Один тег: ключ из `payload`, пресет оттуда же, версия на диск.

    Порядок — образец `probe`: спросить отмену перед работой, сообщить о ходе
    после. Проверять отмену после единственного шага бессмысленно, поэтому
    здесь она спрашивается один раз — перед вызовом модели, где она ещё что-то
    экономит.
    """
    payload = ctx.job.payload or {}
    ключ = str(payload.get("key") or "").strip()
    if not ключ:
        raise ApiError(KEY_REQUIRED, "payload.key must name a tag", 400,
                       where="body.payload.key")

    with Прогон(ctx) as прогон:
        ctx.progress(0, 1, note=ключ)
        if ctx.cancelled():
            return отменено(ctx, ключ)
        try:
            fill = orchestrator.fill_tag(
                прогон.project, ключ, endpoint=прогон.ep, cancel=прогон.отмена,
                overwrite=bool(payload.get("overwrite")))
        except orchestrator.OrchestratorError as беда:
            # Текст оркестратора уезжает наружу целиком и намеренно: он
            # по-русски и объясняет ровно то, что человек может исправить сам
            # («тег заполняет не модель», «переписать — overwrite»). Пути на
            # томе в нём нет — там имя тега и слово `source`.
            raise ApiError(TAG_REFUSED, str(беда), 409,
                           where="body.payload.key") from None
        прогон.текст(_текстом(fill.value))
        прогон.тег_закрыт(fill)
        ctx.progress(1, 1, note=ключ)

    if not fill.ok:
        # Модель ответила, но негодно: беда прогона, а не службы. Подробности —
        # в `problems`, и они уже уехали событием; наружу код и одна строка.
        raise ApiError(RUN_FAILED,
                       f"The model did not produce a usable value for '{ключ}'",
                       502, where="body.payload.key")
    return {"key": fill.key, "ok": True,
            "version": getattr(fill.version, "n", None),
            "flags": list(fill.flags or ()), "stop": fill.stop,
            "key_source": прогон.источник}


def _текстом(value) -> str:
    """Значение тега в том виде, в каком его показывают человеку.

    У текстовых значений это сам текст; у прочих — JSON, потому что «таблица
    словами» — это не текст, а выдумка. Пустое значение даёт пустую строку, и
    события `text` тогда не будет вовсе: пустой кадр в потоке хуже отсутствия,
    он выглядит как ответ модели.
    """
    if not isinstance(value, dict):
        return ""
    for поле in ("text", "markdown", "code"):
        if isinstance(value.get(поле), str):
            return value[поле]
    return json.dumps(value, ensure_ascii=False)


def _зарегистрировать() -> None:
    """Поставить обработчик в реестр. Зовётся из `handlers.подключить`.

    Функцией, а не декоратором на уровне модуля, по той же причине, что у
    `jobs/probe.py`: регистрация декоратором случается на импорте, то есть один
    раз на процесс, и тест, почистивший реестр (`registry._забыть_всё`), обратно
    её уже не получит — модуль-то в `sys.modules` остался.
    """
    register(FILL_TAG, needs_secret=True)(заполнить_тег)


__all__ = ["заполнить_тег", "_зарегистрировать", "TAG_REFUSED", "RUN_FAILED",
           "KEY_REQUIRED"]
