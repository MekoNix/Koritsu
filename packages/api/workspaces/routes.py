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

Имена форм запроса (`WorkspaceNameIn`, `MemberIn`, `MemberRoleIn`) и имена
операций (`operation_id`) — по-английски, как у аккаунтов и по той же причине:
и те, и другие уезжают в OpenAPI и становятся именами типов и методов в клиенте
сайта (§5). До сведения они были русскими, и генератор выписывал из них `____` —
имя, которое ни набрать, ни отличить от соседнего. Имена самих обработчиков
остались русскими: их наружу не видно, а читают их здесь.

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
from ..settings import Settings
from .deps import CurrentUser, user_id_by_email
from .models import NAME_MAX, Workspace, WorkspaceMember
from .service import (ALREADY_MEMBER, EDITOR, LAST_OWNER, NO_SUCH_USER, OWNER,
                      check_role, create_personal, iso, personal_workspace,
                      require_role, restore, role_of)
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
    запрос = (select(Workspace, WorkspaceMember.role)
              .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
              .where(WorkspaceMember.user_id == user.id))
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
    s.add(WorkspaceMember(workspace_id=ws.id, user_id=user.id, role=OWNER))
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
                "Lists the members and their roles. Any member may read it. "
                "400 invalid_id, 404 not_found."))
def участники(workspace_id: str, s: SessionDep, user: CurrentUser) -> dict:
    """Видят все участники: список коллег — это чтение, и `viewer` его получает."""
    ws = require_role(s, user.id, check_id(workspace_id, where="path.workspace_id"))
    строки = s.scalars(select(WorkspaceMember)
                       .where(WorkspaceMember.workspace_id == ws.id)).all()
    return {"members": [{"user_id": m.user_id, "role": m.role,
                         "created_at": iso(m.created_at)} for m in строки]}


@router.post("/{workspace_id}/members", status_code=201,
             summary="Add a member by email",
             operation_id="add_workspace_member",
             description=(
                 "Invites a person by email address. Owner only. "
                 "400 unknown_role, 403 forbidden, 404 no_such_user, "
                 "409 already_member."))
def добавить(workspace_id: str, тело: MemberIn, s: SessionDep,
             user: CurrentUser) -> dict:
    """Позвать человека по почте. Только владелец (§7)."""
    ws = require_role(s, user.id, check_id(workspace_id, where="path.workspace_id"),
                      OWNER)
    роль = check_role(тело.role)
    кого = user_id_by_email(s, тело.email)
    if кого is None:
        # 404, а не 400: почта не наша беда, а отсутствие человека. Существование
        # чужого аккаунта этим не выдаётся — спрашивающий и так назвал почту.
        raise ApiError(NO_SUCH_USER, "No user with this email", 404,
                       where="body.email")
    if role_of(s, кого, ws.id) is not None:
        raise ApiError(ALREADY_MEMBER, "Already a member of this workspace", 409,
                       where="body.email")
    s.add(WorkspaceMember(workspace_id=ws.id, user_id=кого, role=роль))
    s.flush()
    return {"user_id": кого, "role": роль}


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
    return {"removed": кого}


def _последний_владелец(s, ws: Workspace, участник: WorkspaceMember,
                        *, новая: str | None) -> None:
    """Не дать пространству остаться без владельца.

    Пространство без `owner` — это пространство, которое никто не может ни
    удалить, ни переименовать, ни позвать в него человека: все три маршрута
    требуют `owner`, и починить это можно было бы только руками в базе.
    """
    if участник.role != OWNER or новая == OWNER:
        return
    владельцев = s.scalar(select(WorkspaceMember.user_id).where(
        WorkspaceMember.workspace_id == ws.id, WorkspaceMember.role == OWNER,
        WorkspaceMember.user_id != участник.user_id))
    if владельцев is None:
        raise ApiError(LAST_OWNER, "A workspace must keep at least one owner",
                       409, where="path.user_id")


__all__ = ["router"]
