"""
routes — одна кнопка: `POST /api/projects/{id}/export`.

    POST …/export   202  поставить задание `export` (роль editor)

Скачивание — не здесь: архив кладётся артефактом проекта, и забирается он
`GET /api/projects/{id}/artifacts/{aid}`, тем же маршрутом, что схема и
собранный отчёт. Идентификатор архива приходит клиенту в `result` задания.

**Роль — `editor`, а не `viewer`.** Соблазн отдать выгрузку читателю понятен
(«он же и так всё видит»), но архив ложится **на том**, в квоту владельца
проекта: право потратить чужие байты — это право писать, а не смотреть. Ту же
роль требует и постановка задания с проектом (`jobs.service.enqueue`), так что
проверок здесь всё равно две, и разойтись они не могут.

`payload` пустой: экспортируется проект задания целиком. Выбор «только
материалы» или «только последняя версия» сюда не заводится, пока его никто не
просил, — а завести его потом можно полем в `payload`, не трогая ни маршрут, ни
скачивание.
"""
from __future__ import annotations

from fastapi import APIRouter, Request

from ..db import SessionDep
from ..jobs import service as задания
from ..jobs.registry import EXPORT
from ..materials.deps import CurrentUser, РедакторПроекта

router = APIRouter(prefix="/projects/{project_id}/export", tags=["export"])


@router.post("", status_code=202, operation_id="export_project",
             summary="Export the files of a project",
             description=(
                 "Queues an `export` job: the original materials and the "
                 "artifacts of the project, plus the current tag values and "
                 "block list, are packed into one zip and stored as a project "
                 "artifact. Answers 202 with the job card; when the job is done "
                 "its result carries `artifact`, which "
                 "`GET /api/projects/{project_id}/artifacts/{artifact_id}` "
                 "downloads. Editor role. 400 invalid_id, 403 forbidden, "
                 "402 limit_exhausted, 404 not_found, 409 in_trash."))
def выгрузить(request: Request, s: SessionDep, user: CurrentUser,
              проект: РедакторПроекта) -> dict:
    """Поставить задание на выгрузку. → карточка задания.

    Ни одного слова о том, сколько это займёт и что войдёт: обо всём этом
    расскажет само задание — прогрессом, пока идёт, и `result`, когда кончится.
    Маршрут же обязан вернуться немедленно (§1: всё, что зовёт внешний процесс
    или ходит по тому, — в очередь).

    Настройки уезжают в постановку ради месячного лимита (§12): у выгрузки есть
    своя цена, как у всякого запуска нашего кода, и отказ по ней человек должен
    получить здесь, а не упавшим заданием через минуту ожидания.
    """
    задание = задания.enqueue(s, user, EXPORT, {}, project_id=проект.id,
                              settings=request.app.state.settings)
    return {"job": задания.карточка(задание)}


__all__ = ["router", "выгрузить"]
