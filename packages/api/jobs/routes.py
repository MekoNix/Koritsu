"""
routes — `/api/jobs`: поставить, посмотреть, отменить, дочитать события.

    POST   /api/jobs                202  поставить задание (роль editor)
    GET    /api/jobs                200  свои задания (фильтры project_id, status)
    GET    /api/jobs/{id}           200  карточка; двигает `last_seen_at`
    POST   /api/jobs/{id}/cancel    200  попросить остановиться
    GET    /api/jobs/{id}/events    200  события с номера `after`

**202, а не 201.** Задание принято, но не сделано; `201 Created` обещал бы, что
за `Location` лежит готовый результат. Разница не педантская: клиент, увидевший
`201`, вправе не опрашивать состояние, — а опрашивать придётся.

**Чужое задание — 404, а не 403.** Тот же довод, что у чужого проекта:
`403` сообщил бы, что задание с таким идентификатором существует. Обработчики
поэтому не проверяют доступ отдельно — они зовут `service.получить`, а он
чужого не находит вовсе.

**Событий отдаётся простой список, а не поток.** SSE (`text/event-stream`)
встаёт поверх той же выборки (`service.события`). Здесь список нужен ровно
затем, чтобы очередь была проверяема и полезна до появления потока: клиент, у
которого SSE не работает
(старый прокси, выключенный JavaScript), дочитывает поток опросом с `after=`.

Коды отказа перечислены в `service`; своих у маршрутов нет.
"""
from __future__ import annotations

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field

from ..db import SessionDep, now
from ..ids import check_id
from ..workspaces.deps import CurrentUser
from . import service
from .registry import ВИДЫ
from .models import STATUSES

router = APIRouter(prefix="/jobs", tags=["jobs"])


class JobIn(BaseModel):
    """Тело постановки задания.

    Имя по-английски, как у соседей (`ProjectPatchIn`, `ModelKeyIn`): оно уезжает
    в OpenAPI и становится именем типа в клиенте сайта.
    """

    kind: str = Field(
        description=f"What to do; one of: {', '.join(ВИДЫ)}")
    project_id: str | None = Field(
        default=None,
        description="Project the job works in; required by most kinds")
    payload: dict = Field(
        default_factory=dict,
        description="Arguments of the job; the shape depends on the kind")


@router.post("", status_code=202, operation_id="jobs_create",
             summary="Put a job into the queue",
             description=(
                 "Accepts a job and answers at once with its card; the work "
                 "happens in a worker process. Editor role in the project. A "
                 "second job of the same user waits in the queue instead of "
                 "being refused. 400 unknown_job_kind, 400 project_required, "
                 "402 limit_exhausted, 403 forbidden, 404 not_found, "
                 "409 in_trash."))
def поставить(тело: JobIn, request: Request, s: SessionDep,
              user: CurrentUser) -> dict:
    """Положить задание в очередь и сразу отдать его карточку.

    `settings` передаются намеренно: по ним постановка проверяет месячный
    лимит расхода против **цены этого вида** и отказывает
    `402 limit_exhausted` — до того, как задание ляжет в очередь и человек
    прождёт его минуту.
    """
    задание = service.enqueue(s, user, тело.kind.strip(), тело.payload,
                              project_id=тело.project_id,
                              settings=request.app.state.settings)
    return service.карточка(задание)


@router.get("", operation_id="jobs_list",
            summary="List your jobs",
            description=(
                "Your own jobs, newest first. Jobs of other people are never "
                "listed, not even in a shared project. `workspace_id` narrows "
                "the list down to the jobs of that workspace's projects, plus "
                "the ones that belong to no project at all. 400 invalid_id, "
                "400 unknown_job_status."))
def список(s: SessionDep, user: CurrentUser,
           project_id: str | None = Query(
               None, description="Only jobs of this project"),
           workspace_id: str | None = Query(
               None, description="Only jobs of this workspace's projects"),
           status: str | None = Query(
               None, description=f"Only jobs in this state: {', '.join(STATUSES)}"),
           limit: int = Query(100, ge=1, le=500)) -> dict:
    """Свои задания, новые сверху.

    Пространство — отбор, а не обязательный параметр: задание принадлежит
    человеку, а не пространству, и задание без проекта (проверка ключа модели)
    не лежит ни в одном из них. Экраны сайта отбор ставят всегда — они
    показывают то, что происходит в текущем пространстве.
    """
    строки = service.мои(s, user.id, project_id=project_id,
                         workspace_id=workspace_id, status=status,
                         limit=limit)
    return {"jobs": [service.карточка(j) for j in строки]}


@router.get("/{job_id}", operation_id="jobs_get",
            summary="One job",
            description=(
                "One job of yours: state, progress, result or error. Asking "
                "resets the retention clock: a job is kept for as long as it is "
                "looked at. 400 invalid_id, 404 not_found."))
def карточка_одного(job_id: str, s: SessionDep, user: CurrentUser) -> dict:
    """Карточка задания. Заодно двигает `last_seen_at` — по нему считается срок
    хранения («90 дней с последнего обращения»)."""
    задание = service.получить(s, user.id, job_id)
    задание.last_seen_at = now()
    return service.карточка(задание)


@router.post("/{job_id}/cancel", operation_id="jobs_cancel",
             summary="Ask a job to stop",
             description=(
                 "A waiting job is cancelled at once; a running one is asked to "
                 "stop between steps, so whatever it has already finished is "
                 "kept. 400 invalid_id, 404 not_found, 409 already_finished."))
def отменить(job_id: str, s: SessionDep, user: CurrentUser) -> dict:
    задание = service.получить(s, user.id, job_id)
    return service.карточка(service.отменить(s, задание))


@router.get("/{job_id}/events", operation_id="jobs_events",
            summary="Events of a job since a sequence number",
            description=(
                "Events of one job in order, starting after `after`. Text "
                "pieces are already glued together, roughly every 100 ms. The "
                "same rows a server-sent stream reads. 400 invalid_id, "
                "404 not_found."))
def события(job_id: str, s: SessionDep, user: CurrentUser,
            after: int = Query(0, ge=0,
                               description="Return events with seq greater than this"),
            limit: int = Query(500, ge=1, le=2000)) -> dict:
    """События задания с места обрыва. Состояние — рядом, чтобы клиенту не
    приходилось спрашивать вторым запросом, кончилось ли задание."""
    задание = service.получить(s, user.id, check_id(job_id, where="path.job_id"))
    задание.last_seen_at = now()
    строки = service.события(s, задание.id, after=after, limit=limit)
    return {"job_id": задание.id, "status": задание.status,
            "events": [service.карточка_события(e) for e in строки]}


__all__ = ["router", "JobIn"]
