"""
build — собрать DOCX/PDF из текущих значений проекта. Модель не зовётся.

    payload   {"outputs": ["docx", "pdf"], "keys": [...], "name": "отчёт.docx"}
    result    {"ok": true, "artifacts": {"docx": "9f2…", "pdf": "1a0…"},
               "problems": N, "errors": [...]}

**`needs_secret=False`** — единственный из пяти прогонов, кому секрет сервера не
достаётся, и это не экономия. Сборка зовёт LibreOffice, то есть чужую программу
в подпроцессе; всё, что лежит в окружении рядом с ней, достаётся и ей. Ключей
модели здесь не нужно ни одного: значения уже на диске.

**В результате — идентификаторы, а не файлы.** `store_artifact` кладёт собранное
в хранилище артефактов проекта (`Project.put_artifact`), и наружу уезжает по
шестнадцать знаков на выход. Так собранный отчёт скачивается тем же маршрутом,
что и всё прочее содержимое проекта, а `job.result` остаётся указателем, а не
местом, где лежит сорокастраничный документ (`jobs/models.py`).

`ok` означает ровно одно: DOCX собран. Отчёт с тремя замечаниями и одним пустым
тегом — это `ok: true` и файл, который человек откроет и поправит; отказ отдал бы
ему пустоту за уже потраченные на модель деньги (то же правило, что у
`hokoku.build_report`).
"""
from __future__ import annotations

import orchestrator

from ...errors import ApiError
from ...jobs.registry import BUILD, register
from .common import отменено

BUILD_FAILED = "build_failed"
BAD_OUTPUTS = "bad_outputs"

ВЫХОДЫ = ("docx", "pdf")


def собрать(ctx) -> dict:
    """Значения проекта → проверка → документ → артефакты."""
    payload = ctx.job.payload or {}
    выходы = [str(o).strip().lower() for o in (payload.get("outputs") or ["docx"])]
    if not выходы or any(o not in ВЫХОДЫ for o in выходы):
        raise ApiError(BAD_OUTPUTS,
                       f"payload.outputs must be a non-empty list of: "
                       f"{', '.join(ВЫХОДЫ)}", 400,
                       where="body.payload.outputs")
    ключи = payload.get("keys") or None
    if ключи is not None:
        ключи = [str(k) for k in ключи]

    ctx.progress(0, 1, note="build")
    if ctx.cancelled():
        return отменено(ctx, "build")

    проект = ctx.project
    итог = orchestrator.build(проект, keys=ключи, outputs=выходы,
                              name=str(payload.get("name") or "") or None,
                              store=True)
    отчёт = итог.get("report") or {}
    if не_собралось(отчёт):
        # Беда самой сборки (шаблон подменён, задание не то) приходит полем
        # `error` результата, а не исключением. Наружу — её код и текст: они уже
        # написаны для человека и путей на томе не содержат.
        беда = отчёт.get("error") or {}
        raise ApiError(BUILD_FAILED,
                       str(беда.get("message") or "The report was not built"),
                       422, where="body.payload")

    артефакты = {вид: тело.get("artifact")
                 for вид, тело in (отчёт.get("outputs") or {}).items()
                 if isinstance(тело, dict) and тело.get("artifact")}
    for вид, art in артефакты.items():
        ctx.emit({"kind": "artifact", "output": вид, "artifact": art})
    ctx.progress(1, 1, note="build")

    return {"ok": bool(итог.get("ok")), "artifacts": артефакты,
            "problems": len(итог.get("problems") or ()),
            "errors": list(отчёт.get("errors") or ()),
            "unfilled": list(отчёт.get("unfilled") or ())}


def не_собралось(отчёт: dict) -> bool:
    """Отличить «собрано с замечаниями» от «не собрано вовсе».

    Отдельной функцией, потому что различие это — договор с `hokoku`, а не наше
    удобство: `ok=False` вместе с заполненным `error` означает, что документа
    нет; `ok=False` без `error` не бывает, но проверять надо оба, иначе первое
    же изменение формы отчёта превратит «нет файла» в «пустой результат».
    """
    return not отчёт.get("ok") and bool(отчёт.get("error"))


def _зарегистрировать() -> None:
    """См. `fill_tag._зарегистрировать` — довод тот же.

    `needs_secret` здесь **не** ставится: см. докстроку модуля.
    """
    register(BUILD)(собрать)


__all__ = ["собрать", "не_собралось", "_зарегистрировать", "BUILD_FAILED",
           "BAD_OUTPUTS", "ВЫХОДЫ"]
