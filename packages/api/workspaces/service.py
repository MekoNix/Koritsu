"""
service — роли, проверка доступа и жизнь пространства (включая корзину).

Здесь нет ни одного `Request`: всё принимает сессию и идентификаторы. Так это
зовут и маршруты, и материалы, и уборщик корзины, который живёт вне
запроса. Проверка доступа, написанная как зависимость FastAPI и только как
зависимость, второй раз пишется в первом же фоновом задании — и второй раз
пишется чуть иначе.

**Роли сравниваются числом, а не перечислением случаев.** `РАНГ` — единственное
место, где сказано, что `owner` сильнее `editor`; без него каждое место доступа
завело бы свой `role in ("owner", "editor")`, и добавление четвёртой роли стало
бы правкой двадцати списков.

**Личное пространство.** Заводится хуком `on_user_created` пакета аккаунтов
`Callable[[Session, User], None]`. Ставится хук в `routes.collect()`,
то есть на каждой сборке приложения, и идемпотентно — `create_app` в тестах
зовут по разу на тест, а список хуков у модуля один на процесс.

Удалить личное нельзя. Проверяется по полю `personal`, а не по имени: имя
человек переименует.

**Приглашённый — ещё не участник.** У строки участия есть состояние: `pending`
у позванного, `active` у согласившегося. Роль спрашивают через `role_of`, и она
видит только `active` — то есть позванный не получает ни строки чужого
пространства, пока не ответил «принять». Так и задумано: приглашение приходит
уведомлением с двумя кнопками, а не молча подкладывает человеку чужие работы.
"""
from __future__ import annotations

import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import now
from ..errors import ApiError
from .models import Workspace, WorkspaceMember

OWNER = "owner"
EDITOR = "editor"
VIEWER = "viewer"

# Список закрыт: только `viewer` и `editor` плюс `owner` как создатель.
ROLES = (VIEWER, EDITOR, OWNER)

# Сила роли. Единственное место, где записано, кто кого старше.
РАНГ = {VIEWER: 1, EDITOR: 2, OWNER: 3}

# Состояние участия. `active` — человек в пространстве; `pending` — позван и
# ещё не ответил. Список закрыт так же, как список ролей.
ACTIVE = "active"
PENDING = "pending"
STATUSES = (ACTIVE, PENDING)

# Запасное имя личного пространства: им зовутся строки, заведённые до того, как
# у аккаунта появился ник. Обычное имя собирает `personal_name` из ника.
PERSONAL_NAME = "Personal"

# Хвост имени личного пространства: `<ник>-workspace`. По-английски, как и
# `PERSONAL_NAME`, и по той же причине — наружу служба говорит по-английски.
PERSONAL_SUFFIX = "-workspace"

NOT_FOUND = "not_found"
FORBIDDEN = "forbidden"
PERSONAL_WORKSPACE = "personal_workspace"
NOT_IN_TRASH = "not_in_trash"
IN_TRASH = "in_trash"
ALREADY_MEMBER = "already_member"
LAST_OWNER = "last_owner"
UNKNOWN_ROLE = "unknown_role"
NO_SUCH_USER = "no_such_user"
NO_INVITE = "no_invite"


def iso(dt: datetime.datetime | None) -> str | None:
    """Время наружу: ISO 8601 в UTC, всегда с зоной.

    Зона дописывается, потому что SQLite её теряет: `DateTime(timezone=True)`
    там хранит строку без смещения и возвращает наивное время. Отдать наивное
    наружу значило бы отдать «12:00» и предоставить браузеру гадать, чьё оно, —
    а браузер прочитает его как местное, и корзина у человека из Владивостока
    будет убираться на семь часов раньше, чем написано.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.astimezone(datetime.timezone.utc).isoformat()


def check_role(role: str, *, where: str = "body.role") -> str:
    """Роль из запроса или внятный отказ. Список закрыт, опечатке молчать нельзя."""
    if role not in ROLES:
        raise ApiError(UNKNOWN_ROLE, f"Role must be one of: {', '.join(ROLES)}",
                       400, where=where)
    return role


# ── доступ ───────────────────────────────────────────────────────────────────

def role_of(s: Session, user_id: str, workspace_id: str) -> str | None:
    """Роль человека в пространстве или None, если он не участник.

    Позванный, но не ответивший (`pending`), участником здесь не считается: он
    ещё не решил, хочет ли туда. Отсюда же берётся и весь отказ в доступе —
    `require_role` увидит `None` и ответит 404, ровно как чужому.
    """
    return s.scalar(select(WorkspaceMember.role).where(
        WorkspaceMember.workspace_id == workspace_id,
        WorkspaceMember.user_id == user_id,
        WorkspaceMember.status == ACTIVE))


def membership(s: Session, user_id: str, workspace_id: str) -> WorkspaceMember | None:
    """Строка участия любого состояния — в том числе не принятое приглашение.

    Нужна ровно тем двум маршрутам, которые с приглашением и работают
    («принять» и «отклонить»): им запрещено ходить через `role_of`, потому что
    та по замыслу не видит `pending`.
    """
    return s.get(WorkspaceMember, {"workspace_id": workspace_id,
                                   "user_id": user_id})


def require_role(s: Session, user_id: str, workspace_id: str,
                 min_role: str = VIEWER, *, where: str = "path.workspace_id",
                 allow_deleted: bool = False) -> Workspace:
    """Пространство, если этот человек имеет в нём хотя бы такую роль.

    Точка входа для всех, кто трогает чужое: маршруты пространств, маршруты
    проектов и материалы. Отказы — те самые два, что описаны в
    докстроке пакета: **404**, если человек не участник (существование чужого
    пространства не раскрывается), и **403**, если участник, но роли мало.

    `allow_deleted` — для восстановления из корзины: удалённое пространство
    иначе не отличить от несуществующего, а достать его оттуда нужно.
    """
    ws = s.get(Workspace, workspace_id)
    роль = None if ws is None else role_of(s, user_id, workspace_id)
    if ws is None or роль is None or (ws.deleted_at is not None and not allow_deleted):
        # Один и тот же ответ на «нет такого» и «не твоё»: разные ответы
        # превратили бы перебор идентификаторов в способ узнать, какие из них
        # заняты.
        raise ApiError(NOT_FOUND, "Workspace not found", 404, where=where)
    if РАНГ[роль] < РАНГ[min_role]:
        raise ApiError(FORBIDDEN, f"Role '{min_role}' or higher is required",
                       403, where=where)
    return ws


# ── личное пространство ──────────────────────────────────────────────────────

def personal_workspace(s: Session, user_id: str) -> Workspace | None:
    """Личное пространство человека или None, если его почему-то нет."""
    return s.scalar(select(Workspace).where(Workspace.owner_id == user_id,
                                            Workspace.personal.is_(True)))


def personal_name(nickname: str | None) -> str:
    """Имя личного пространства по умолчанию: `<ник>-workspace`.

    Имя, а не подстановка на экране: человек видит его в переключателе, в
    поиске и в списке пространств, и «Личное» рядом с «кафедрой» не отвечало на
    вопрос, чьё оно. Ник у аккаунта обязателен; пустой остаётся только у строк,
    заведённых до того, как он появился, — им достаётся `PERSONAL_NAME`.

    Переименовать личное пространство человек вправе: имя — обычное поле, а
    «личное» — флаг `personal`.
    """
    ник = (nickname or "").strip()
    return f"{ник}{PERSONAL_SUFFIX}" if ник else PERSONAL_NAME


def create_personal(s: Session, user) -> Workspace:
    """Завести личное пространство. Идемпотентно: второй вызов вернёт то же.

    Аргумент — объект пользователя (нужен только `id`), потому что такова форма
    хука: `Callable[[Session, User], None]`. Идемпотентность здесь не
    перестраховка: хук зовут внутри той же транзакции, что и регистрацию, а
    повторная регистрация той же почты — обычное дело на кривой сети.
    """
    уже = personal_workspace(s, user.id)
    if уже is not None:
        return уже
    ws = Workspace(name=personal_name(getattr(user, "nickname", None)),
                   owner_id=user.id, personal=True)
    s.add(ws)
    # `id` ставится умолчанием на стороне Python, то есть на сбросе: без него
    # участнику нечего записать в `workspace_id`.
    s.flush()
    s.add(WorkspaceMember(workspace_id=ws.id, user_id=user.id, role=OWNER,
                          status=ACTIVE))
    s.flush()
    return ws


def register_hooks() -> bool:
    """Поставить `create_personal` в `on_user_created` аккаунтов. Идемпотентно.

    Зовётся из `routes.collect()`, то есть на каждой сборке приложения, а не при
    импорте модуля: импорт случается один раз на процесс, и приложение, собранное
    вторым (а в тестах их десятки), осталось бы без хука, если бы к тому моменту
    список хуков успели почистить.

    Возвращает, стоит ли хук на месте: `False` означает «аккаунтов ещё нет» —
    не беда, а рабочее состояние, пока подпакет аккаунтов недоступен.
    """
    try:
        from ..accounts.service import on_user_created  # type: ignore
    except Exception:                                   # noqa: BLE001 — их ещё нет
        return False
    if create_personal not in on_user_created:
        on_user_created.append(create_personal)
    return True


# ── корзина ──────────────────────────────────────────────────────────────────

def trash(s: Session, ws: Workspace, settings) -> datetime.datetime:
    """Положить пространство в корзину вместе с его проектами. → момент удаления.

    Личное не кладётся никогда: это единственное место, где у человека заведомо
    есть куда деть проект, и без него «создать проект» перестаёт работать вовсе.

    Проекты помечаются **тем же** `deleted_at`, что и пространство, — по нему
    восстановление и узнаёт, какие из них попали в корзину вместе с ним, а какие
    лежали там своей жизнью и должны там остаться.
    """
    if ws.personal:
        raise ApiError(PERSONAL_WORKSPACE, "Personal workspace cannot be deleted",
                       409, where="path.workspace_id")
    if ws.deleted_at is not None:
        raise ApiError(IN_TRASH, "Workspace is already in the trash", 409,
                       where="path.workspace_id")
    момент = now()
    срок = момент + datetime.timedelta(days=settings.trash_days)
    ws.deleted_at, ws.purge_after = момент, срок

    from ..projects.models import Project             # локально: круг импортов
    for p in s.scalars(select(Project).where(Project.workspace_id == ws.id,
                                             Project.deleted_at.is_(None))):
        p.deleted_at, p.purge_after = момент, срок
    s.flush()
    return момент


def restore(s: Session, ws: Workspace) -> None:
    """Достать пространство из корзины вместе с теми проектами, что легли с ним."""
    if ws.deleted_at is None:
        raise ApiError(NOT_IN_TRASH, "Workspace is not in the trash", 409,
                       where="path.workspace_id")
    момент = ws.deleted_at

    from ..projects.models import Project             # локально: круг импортов
    for p in s.scalars(select(Project).where(Project.workspace_id == ws.id,
                                             Project.deleted_at == момент)):
        p.deleted_at, p.purge_after = None, None
    ws.deleted_at, ws.purge_after = None, None
    s.flush()


__all__ = ["OWNER", "EDITOR", "VIEWER", "ROLES", "РАНГ", "PERSONAL_NAME",
           "PERSONAL_SUFFIX", "ACTIVE", "PENDING", "STATUSES",
           "iso", "check_role", "role_of", "membership", "require_role",
           "personal_workspace", "personal_name",
           "create_personal", "register_hooks", "trash", "restore",
           "NOT_FOUND", "FORBIDDEN", "PERSONAL_WORKSPACE", "NOT_IN_TRASH",
           "IN_TRASH", "ALREADY_MEMBER", "LAST_OWNER", "UNKNOWN_ROLE",
           "NO_SUCH_USER", "NO_INVITE"]
