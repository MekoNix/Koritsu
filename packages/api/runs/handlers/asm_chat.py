"""
asm_chat — агент по трассе: один вызов модели на сообщение человека.

    payload   {"endpoint": "deepseek", "run_id": "<программа>",
               "text": "почему здесь ZF взведён?",
               "anchor": {"kind": "flag", "name": "zf"} | null,
               "step": 17 | null, "run_no": 3 | null}
    result    {"reply": "…", "message_id": "<32hex>", "question_id": "<32hex>",
               }

**Устроено как переписка доски** (`board_check`, режим `chat`): переписка лежит
записью состояния решения (`асм-чат`), задание читает её, чтобы модель видела
прежние реплики, и дописывает в неё вопрос вместе с ответом — одной записью,
когда ответ есть. Вопрос без ответа в переписке читался бы как вопрос, на
который ещё отвечают; пока задание идёт, вопрос показывает страница.

**Контекст собирает оркестратор** (`orchestrator.asm.context`): исходник с
номерами строк, сообщения сборки, итог прогона, состояние на шаге, соседние
шаги, данные программы с именами переменных, ввод и якорь. Служба называет
программу, прогон, шаг и якорь и не строит ни одного куска промпта. Исходник
берётся тот, что в редакторе сейчас: человек спрашивает про то, что видит, а
прогон мог собираться до последней правки — тогда агент видит оба.

**Не `agent` и не `board_check`.** Агент заполняет теги бланка, у доски своя
выжимка сцены и свои схемы ответа; здесь ни того, ни другого нет, а цена у
вызова та же, что у чата доски.

**События потока.** `progress` в начале и в конце, `text` с ответом целиком.
Терминальные `done`/`failed`/`cancelled` пишет воркер.
"""
from __future__ import annotations

import uuid

from orchestrator import asm as ассемблер

from ...errors import ApiError
from ...jobs.registry import ASM_CHAT, register
from .common import Прогон, ТЕКСТ, беда_словами, отменено

ASM_CHAT_FAILED = "asm_chat_failed"

# Что пишется в переписку, когда модель не ответила: вопрос без ответа читался
# бы как вопрос, на который ещё отвечают.
БЕЗ_ОТВЕТА = "Ответа не получилось: модель не ответила."


def _номер(значение, *, наименьший: int, where: str) -> int | None:
    if значение is None:
        return None
    if (not isinstance(значение, int) or isinstance(значение, bool)
            or значение < наименьший):
        raise ApiError("invalid_value", f"{where} is an integer from {наименьший}",
                       400, where=where)
    return значение


def ответить(ctx) -> dict:
    """Позвать агента по трассе и дописать вопрос с ответом в переписку."""
    from ...modules.asm.routes import (ИСХОДНИК,                # noqa: PLC0415
                                       СООБЩЕНИЕ_МАКС, СООБЩЕНИЙ_МОДЕЛИ,
                                       дописать_переписку, режим_программы,
                                       сейчас, сообщения_записи, якорь)

    payload = ctx.job.payload or {}
    текст = str(payload.get("text") or "").strip()[:СООБЩЕНИЕ_МАКС]
    if not текст:
        raise ApiError("invalid_value", "payload.text is the message to answer",
                       400, where="body.payload.text")
    привязка = якорь(payload.get("anchor"), where="body.payload.anchor")
    шаг = _номер(payload.get("step"), наименьший=0, where="body.payload.step")
    номер = _номер(payload.get("run_no"), наименьший=1,
                   where="body.payload.run_no")
    if not ctx.solution:
        raise ApiError("invalid_value", "payload.run_id names the program", 400,
                       where="body.payload.run_id")

    история = сообщения_записи(ctx.project)[-СООБЩЕНИЙ_МОДЕЛИ:]
    исходник = str((ctx.project.state(ИСХОДНИК) or {}).get("source") or "")
    # Режим программы — для разговора без прогона; у прогона свой режим в нём.
    набор, _ = режим_программы(ctx.project)
    with Прогон(ctx) as прогон:
        ctx.progress(0, 1, note="asm")
        if ctx.cancelled():
            return отменено(ctx, "asm")
        try:
            итог = ассемблер.chat(
                прогон.project, endpoint=прогон.ep, message=текст,
                run_no=номер, step=шаг, anchor=привязка, source=исходник,
                history=история, cancel=прогон.отмена, toolchain=набор)
        except Exception as беда:                            # noqa: BLE001
            raise ApiError(ASM_CHAT_FAILED, беда_словами(беда), 422,
                           where="body.payload") from None

    момент = сейчас()
    вопрос = {"id": uuid.uuid4().hex, "role": "user", "text": текст,
              "anchor": привязка, "step": шаг, "run_no": номер,
              "created_at": момент}
    реплика = {"id": uuid.uuid4().hex, "role": "assistant",
               "text": итог.reply or БЕЗ_ОТВЕТА, "anchor": None, "step": шаг,
               "run_no": номер, "created_at": момент}
    дописать_переписку(ctx.project, вопрос, реплика)
    if итог.reply:
        ctx.emit({"kind": ТЕКСТ, "text": итог.reply})
    ctx.progress(1, 1, note="asm")
    return {"reply": итог.reply, "message_id": реплика["id"],
            "question_id": вопрос["id"]}


def _зарегистрировать() -> None:
    """См. `fill_tag._зарегистрировать` — довод тот же."""
    register(ASM_CHAT, needs_secret=True)(ответить)


__all__ = ["ответить", "_зарегистрировать", "ASM_CHAT_FAILED", "БЕЗ_ОТВЕТА"]
