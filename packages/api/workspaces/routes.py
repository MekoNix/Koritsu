"""
routes — `/api/workspaces`: список, создание, переименование, участники, корзина.

Коды отказа этого модуля (разбирает их интерфейс, не текст):

    unauthorized        401  вошедшего нет (зависимость аккаунтов)
    invalid_id          400  идентификатор не uuid4
    not_found           404  нет такого или спрашивающий не участник
    forbidden           403  участник есть, роли мало
    personal_workspace  409  личное пространство удалять нельзя
    in_trash            409  уже в корзине
    not_in_trash        409  восстанавливать нечего
    no_such_user        404  приглашают почту, которой нет
    already_member      409  этот человек уже участник
    last_owner          409  убрать или понизить последнего владельца
    unknown_role        400  роль не из списка
    no_invite           404  отвечать не на что: приглашения нет

Имена форм запроса (`WorkspaceNameIn`, `MemberIn`, `MemberRoleIn`) и имена
операций (`operation_id`) — по-английски, как у аккаунтов и по той же причине:
и те, и другие уезжают в OpenAPI и становятся именами типов и методов в клиенте
сайта. Когда они были русскими, генератор выписывал из них `____` —
имя, которое ни набрать, ни отличить от соседнего. Имена самих обработчиков
остались русскими: их наружу не видно, а читают их здесь.

**Приглашение — это уведомление с двумя кнопками, а не молчаливое зачисление.**
`POST …/members` заводит участие в состоянии `pending` и кладёт человеку строку
в колокольчик (`notifications`); участником он становится, только ответив
`POST …/members/{user_id}/accept`, а `…/decline` убирает строку участия вовсе.
До ответа пространство для него не существует: `role_of` не видит `pending`, и
любой запрос к нему получает те же 404, что и чужой.

Отвечает на приглашение только тот, кого позвали, — иначе владелец мог бы
согласиться за человека. Чужой `user_id` в пути отвечает 404, как и всё, чего
спрашивающему видеть не положено.

Корзина показывается тем же маршрутом с `?trash=true`, а не отдельным
`/workspaces/trash`: отдельный путь пришлось бы объявлять раньше
`/{workspace_id}`, и первый же переставленный маршрут увёл бы слово «trash» в
идентификатор. Признак — параметр, а не адрес.
"""
from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from ..db import SessionDep
from ..errors import ApiError
from ..ids import check_id
from ..notifications import service as уведомления
from ..settings import Settings
from .deps import (CurrentUser, emails_by_ids, nicknames_by_ids,
                   user_id_by_email)
from .models import NAME_MAX, Workspace, WorkspaceMember
from .service import (ACTIVE, ALREADY_MEMBER, EDITOR, LAST_OWNER, NO_INVITE,
                      NO_SUCH_USER, OWNER, PENDING,
                      check_role, create_personal, iso, membership,
                      personal_workspace, require_role, restore, role_of)
from .service import trash as в_корзину   # имя занято параметром запроса `trash`

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


class WorkspaceNameIn(BaseModel):
    """Тело создания и переименования. Имя обрезается по краям и не бывает пустым."""

    name: str = Field(min_length=1, max_length=NAME_MAX)


class MemberIn(BaseModel):
    """Кого зовём и кем. Почта, а не идентификатор: чужой uuid человеку неоткуда
    взять, а почту коллеги он знает."""

    email: str = Field(min_length=3, max_length=320)
    role: str = EDITOR


class MemberRoleIn(BaseModel):
    role: str


def настройки(request: Request) -> Settings:
    """Настройки приложения. Живут на нём (`app.state`), а не в модуле."""
    return request.app.state.settings


def карточка(ws: Workspace, role: str) -> dict:
    """Пространство наружу. Роль — своя, спрашивающего: интерфейс по ней решает,
    показывать ли кнопки, и второй запрос за этим слать не должен."""
    return {"id": ws.id, "name": ws.name, "personal": ws.personal,
            "role": role, "created_at": iso(ws.created_at),
            "deleted_at": iso(ws.deleted_at), "purge_after": iso(ws.purge_after)}


@router.get("", summary="List workspaces the caller belongs to",
            operation_id="list_workspaces",
            description=(
                "Lists the workspaces the caller is a member of, personal one "
                "first, each with the caller's own role. `trash=true` lists the "
                "ones in the trash instead. 401 unauthorized."))
def список(s: SessionDep, user: CurrentUser, trash: bool = False) -> dict:
    """Свои пространства. `trash=true` — те, что лежат в корзине."""
    # Только принятые участия: пространство, в которое человека позвали и он ещё
    # не ответил, в списке не показывается — приглашение живёт в колокольчике.
    запрос = (select(Workspace, WorkspaceMember.role)
              .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
              .where(WorkspaceMember.user_id == user.id,
                     WorkspaceMember.status == ACTIVE))
    запрос = запрос.where(Workspace.deleted_at.is_not(None) if trash
                          else Workspace.deleted_at.is_(None))
    # Личное первым: оно у человека одно и с него начинается любой сеанс.
    строки = sorted(s.execute(запрос).all(),
                    key=lambda пара: (not пара[0].personal, пара[0].created_at))
    return {"workspaces": [карточка(ws, role) for ws, role in строки]}


@router.post("", status_code=201, summary="Create a workspace",
             operation_id="create_workspace",
             description=(
                 "Creates a workspace; the caller becomes its owner and its "
                 "first member. 422 validation_failed."))
def создать(тело: WorkspaceNameIn, s: SessionDep, user: CurrentUser) -> dict:
    """Новое пространство. Создатель сразу и владелец, и участник.

    Участником он записывается явно, а не «подразумевается по `owner_id`»: иначе
    у проверки доступа стало бы два источника правды, и владелец, снявший себя из
    участников, продолжал бы всё видеть — или наоборот, потерял бы своё.
    """
    ws = Workspace(name=тело.name.strip(), owner_id=user.id, personal=False)
    s.add(ws)
    s.flush()
    s.add(WorkspaceMember(workspace_id=ws.id, user_id=user.id, role=OWNER,
                          status=ACTIVE))
    s.flush()
    return карточка(ws, OWNER)


@router.get("/personal", summary="The caller's personal workspace",
            operation_id="get_personal_workspace",
            description=(
                "Returns the caller's personal workspace, creating it when the "
                "account is older than this code. 401 unauthorized."))
def личное(s: SessionDep, user: CurrentUser) -> dict:
    """Личное пространство. Заводится при регистрации; если аккаунт старше этого
    кода, заводим сейчас — «человек без личного пространства» не состояние, в
    котором интерфейсу есть что показать."""
    ws = personal_workspace(s, user.id) or create_personal(s, user)
    return карточка(ws, OWNER)


@router.get("/{workspace_id}", summary="One workspace",
            operation_id="get_workspace",
            description=(
                "One workspace with the caller's own role. A workspace the "
                "caller is not a member of answers 404, not 403. "
                "400 invalid_id, 404 not_found."))
def карточка_одного(workspace_id: str, s: SessionDep, user: CurrentUser) -> dict:
    ws = require_role(s, user.id, check_id(workspace_id, where="path.workspace_id"))
    return карточка(ws, role_of(s, user.id, ws.id))


@router.patch("/{workspace_id}", summary="Rename a workspace",
              operation_id="rename_workspace",
              description=(
                  "Renames a workspace. Owner only. 400 invalid_id, "
                  "403 forbidden, 404 not_found, 422 validation_failed."))
def переименовать(workspace_id: str, тело: WorkspaceNameIn, s: SessionDep,
                  user: CurrentUser) -> dict:
    ws = require_role(s, user.id, check_id(workspace_id, where="path.workspace_id"),
                      OWNER)
    ws.name = тело.name.strip()
    s.flush()
    return карточка(ws, OWNER)


@router.delete("/{workspace_id}", summary="Move a workspace to the trash",
               operation_id="trash_workspace",
               description=(
                   "Moves a workspace to the trash together with its projects; "
                   "they stay on the volume until purge_after. Owner only, and "
                   "the personal workspace cannot be trashed. 403 forbidden, "
                   "404 not_found, 409 personal_workspace, 409 in_trash."))
def удалить(workspace_id: str, request: Request, s: SessionDep,
            user: CurrentUser) -> dict:
    """В корзину вместе с проектами. Личное не удаляется — 409."""
    ws = require_role(s, user.id, check_id(workspace_id, where="path.workspace_id"),
                      OWNER)
    в_корзину(s, ws, настройки(request))
    return карточка(ws, OWNER)


@router.post("/{workspace_id}/restore", operation_id="restore_workspace",
             summary="Restore a workspace from the trash",
             description=(
                 "Restores a workspace from the trash. Owner only. "
                 "403 forbidden, 404 not_found, 409 not_in_trash."))
def восстановить(workspace_id: str, s: SessionDep, user: CurrentUser) -> dict:
    ws = require_role(s, user.id, check_id(workspace_id, where="path.workspace_id"),
                      OWNER, allow_deleted=True)
    restore(s, ws)
    return карточка(ws, OWNER)


# ── участники ────────────────────────────────────────────────────────────────

@router.get("/{workspace_id}/members", summary="List workspace members",
            operation_id="list_workspace_members",
            description=(
                "Lists the members with their roles, nicknames and email "
                "addresses. Any member may read it. 400 invalid_id, "
                "404 not_found."))
def участники(workspace_id: str, s: SessionDep, user: CurrentUser) -> dict:
    """Видят все участники: список коллег — это чтение, и `viewer` его получает.

    Ник и почта в ответе, а не один идентификатор: показывать человеку строку
    из двух десятков шестнадцатеричных знаков и спрашивать, кого из них убрать,
    — это не список людей. Имя на экране — ник, почта
    осталась рядом: приглашают по ней, и без неё двух тёзок не различить.
    Берутся оба одним запросом каждый (`nicknames_by_ids`, `emails_by_ids`).

    Чужих почт этим не выдаётся: список видят только участники того же
    пространства, а приглашали их по этой же почте.

    `status` в каждой строке — `active` или `pending`: владелец обязан видеть,
    кто уже в пространстве, а кто только позван и молчит. Без этого «позвал, а
    его нет в списке» выглядело бы как потерянное приглашение.
    """
    ws = require_role(s, user.id, check_id(workspace_id, where="path.workspace_id"))
    строки = s.scalars(select(WorkspaceMember)
                       .where(WorkspaceMember.workspace_id == ws.id)).all()
    кто = [m.user_id for m in строки]
    почты = emails_by_ids(s, кто)
    ники = nicknames_by_ids(s, кто)
    return {"members": [{"user_id": m.user_id, "nickname": ники.get(m.user_id),
                         "email": почты.get(m.user_id),
                         "role": m.role, "status": m.status,
                         "created_at": iso(m.created_at)}
                        for m in строки]}


@router.post("/{workspace_id}/members", status_code=201,
             summary="Invite a member by email",
             operation_id="add_workspace_member",
             description=(
                 "Invites a person by email address: the membership is created "
                 "as `pending` and a `workspace_invite` notification is sent to "
                 "them. They join only after accepting it. Owner only. "
                 "400 unknown_role, 403 forbidden, 404 no_such_user, "
                 "409 already_member."))
def добавить(workspace_id: str, тело: MemberIn, s: SessionDep,
             user: CurrentUser) -> dict:
    """Позвать человека по почте. Только владелец.

    Участия здесь ещё нет — есть приглашение: строка `pending` и уведомление с
    кнопками «принять» и «отклонить». Повторное приглашение отвергается тем же
    `already_member`, что и попытка позвать участника: с точки зрения владельца
    оба случая — «этому человеку уже отправлено», и разводить их значило бы
    рассказывать, ответил ли тот на приглашение.
    """
    ws = require_role(s, user.id, check_id(workspace_id, where="path.workspace_id"),
                      OWNER)
    роль = check_role(тело.role)
    кого = user_id_by_email(s, тело.email)
    if кого is None:
        # 404, а не 400: почта не наша беда, а отсутствие человека. Существование
        # чужого аккаунта этим не выдаётся — спрашивающий и так назвал почту.
        raise ApiError(NO_SUCH_USER, "No user with this email", 404,
                       where="body.email")
    if membership(s, кого, ws.id) is not None:
        raise ApiError(ALREADY_MEMBER, "Already a member of this workspace", 409,
                       where="body.email")
    s.add(WorkspaceMember(workspace_id=ws.id, user_id=кого, role=роль,
                          status=PENDING))
    s.flush()
    уведомления.пригласили(s, user_id=кого, workspace_id=ws.id,
                           workspace_name=ws.name, role=роль,
                           from_nickname=getattr(user, "nickname", None))
    return {"user_id": кого, "role": роль, "status": PENDING}


@router.post("/{workspace_id}/members/{user_id}/accept",
             operation_id="accept_workspace_invite",
             summary="Accept an invitation to a workspace",
             description=(
                 "Accepts your own pending invitation: the membership becomes "
                 "active and the invitation notification is removed. Only the "
                 "invited person may call it. 400 invalid_id, 404 no_invite."))
def принять(workspace_id: str, user_id: str, s: SessionDep,
            user: CurrentUser) -> dict:
    """Принять приглашение. Отвечает только тот, кого позвали."""
    ws, участие = _приглашение(s, user, workspace_id, user_id)
    участие.status = ACTIVE
    s.flush()
    _убрать_приглашения(s, user.id, ws.id)
    return карточка(ws, участие.role)


@router.post("/{workspace_id}/members/{user_id}/decline",
             operation_id="decline_workspace_invite",
             summary="Decline an invitation to a workspace",
             description=(
                 "Declines your own pending invitation: the membership row and "
                 "the invitation notification are removed. Only the invited "
                 "person may call it. 400 invalid_id, 404 no_invite."))
def отклонить(workspace_id: str, user_id: str, s: SessionDep,
              user: CurrentUser) -> dict:
    """Отклонить приглашение: строка участия уходит совсем.

    Уходит, а не остаётся отказом: отказ, лежащий в таблице, не даст позвать
    человека второй раз («уже участник»), а передумать после «нет» — обычное
    дело.
    """
    ws, участие = _приглашение(s, user, workspace_id, user_id)
    s.delete(участие)
    s.flush()
    _убрать_приглашения(s, user.id, ws.id)
    return {"declined": ws.id}


def _приглашение(s, user, workspace_id: str, user_id: str):
    """Пространство и своё не принятое приглашение в него — или 404.

    Один отказ на все беды (нет пространства, нет строки участия, она уже
    принята, в пути чужой человек) — то же правило, что и у `require_role`:
    спрашивающий не вправе узнать, какая из них случилась. Разные ответы
    превратили бы этот маршрут в способ перебрать чужие пространства.
    """
    ид = check_id(workspace_id, where="path.workspace_id")
    кого = check_id(user_id, where="path.user_id")
    ws = s.get(Workspace, ид)
    участие = membership(s, кого, ид) if ws is not None else None
    if (ws is None or участие is None or кого != user.id
            or участие.status != PENDING or ws.deleted_at is not None):
        raise ApiError(NO_INVITE, "No pending invitation to this workspace", 404,
                       where="path.workspace_id")
    return ws, участие


def _убрать_приглашения(s, user_id: str, workspace_id: str) -> None:
    """Убрать строки колокольчика об этом приглашении: отвечать больше не на что."""
    for строка in уведомления.приглашения(s, user_id, workspace_id):
        уведомления.убрать(s, строка)


@router.patch("/{workspace_id}/members/{user_id}",
              operation_id="set_workspace_member_role",
              summary="Change a member's role",
              description=(
                  "Changes a member's role (owner, editor, viewer). Owner only, "
                  "and the last owner cannot be demoted. 400 unknown_role, "
                  "403 forbidden, 404 not_found, 409 last_owner."))
def сменить_роль(workspace_id: str, user_id: str, тело: MemberRoleIn, s: SessionDep,
                 user: CurrentUser) -> dict:
    ws = require_role(s, user.id, check_id(workspace_id, where="path.workspace_id"),
                      OWNER)
    кого = check_id(user_id, where="path.user_id")
    роль = check_role(тело.role)
    участник = s.get(WorkspaceMember, {"workspace_id": ws.id, "user_id": кого})
    if участник is None:
        raise ApiError("not_found", "Member not found", 404, where="path.user_id")
    _последний_владелец(s, ws, участник, новая=роль)
    участник.role = роль
    s.flush()
    return {"user_id": кого, "role": роль}


@router.delete("/{workspace_id}/members/{user_id}", summary="Remove a member",
               operation_id="remove_workspace_member",
               description=(
                   "Removes a member from the workspace. Owner only, and the "
                   "last owner cannot be removed. 403 forbidden, 404 not_found, "
                   "409 last_owner."))
def убрать(workspace_id: str, user_id: str, s: SessionDep,
           user: CurrentUser) -> dict:
    ws = require_role(s, user.id, check_id(workspace_id, where="path.workspace_id"),
                      OWNER)
    кого = check_id(user_id, where="path.user_id")
    участник = s.get(WorkspaceMember, {"workspace_id": ws.id, "user_id": кого})
    if участник is None:
        raise ApiError("not_found", "Member not found", 404, where="path.user_id")
    _последний_владелец(s, ws, участник, новая=None)
    s.delete(участник)
    s.flush()
    # Позванного убрали, не дождавшись ответа, — кнопки «принять» в его
    # колокольчике не должны пережить приглашение.
    _убрать_приглашения(s, кого, ws.id)
    return {"removed": кого}


def _последний_владелец(s, ws: Workspace, участник: WorkspaceMember,
                        *, новая: str | None) -> None:
    """Не дать пространству остаться без владельца.

    Считаются только принятые участия: позванный в владельцы, но не ответивший,
    пространством пока не распоряжается и удержать его от безвластия не может.

    Пространство без `owner` — это пространство, которое никто не может ни
    удалить, ни переименовать, ни позвать в него человека: все три маршрута
    требуют `owner`, и починить это можно было бы только руками в базе.
    """
    if участник.role != OWNER or новая == OWNER:
        return
    владельцев = s.scalar(select(WorkspaceMember.user_id).where(
        WorkspaceMember.workspace_id == ws.id, WorkspaceMember.role == OWNER,
        WorkspaceMember.status == ACTIVE,
        WorkspaceMember.user_id != участник.user_id))
    if владельцев is None:
        raise ApiError(LAST_OWNER, "A workspace must keep at least one owner",
                       409, where="path.user_id")


__all__ = ["router"]
