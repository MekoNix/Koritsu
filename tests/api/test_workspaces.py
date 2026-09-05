"""
Проверки рабочих пространств: личное, роли, участники, корзина.

Три вещи, ради которых эти проверки написаны, и все три — про доступ, а не про
формат ответа:

1. **личное заводится само** — при регистрации, хуком, а не отдельной кнопкой;
2. **чужое — 404, своё без прав — 403**:
   первое не выдаёт существования, второе не притворяется пропажей;
3. **личное не удаляется** — иначе человек остаётся без места под проекты.
"""
from __future__ import annotations

import sys

import pytest
from sqlalchemy import select

from api.accounts import User, on_user_created
from api.workspaces import (EDITOR, OWNER, VIEWER, Workspace,
                                  WorkspaceMember, create_personal,
                                  register_hooks, require_role)
from api.workspaces.service import personal_workspace

from .c_fixtures import (войти, завести, клиент, личное_id,  # noqa: F401
                         сосед, хозяин)


# ── личное пространство ──────────────────────────────────────────────────────

def test_личное_заводится_при_регистрации(app, клиент):
    """Регистрация и личное пространство — одна работа, а не две кнопки."""
    user = завести(app, клиент, "новичок@пример.рф")
    with app.state.db.session_scope() as s:
        ws = personal_workspace(s, user.id)
        assert ws is not None, "личного пространства после регистрации нет"
        assert ws.personal is True
        роль = s.scalar(select(WorkspaceMember.role).where(
            WorkspaceMember.workspace_id == ws.id,
            WorkspaceMember.user_id == user.id))
    assert роль == OWNER, "владелец личного пространства не записан участником"


def test_хук_ставится_на_каждой_сборке_приложения(settings, monkeypatch):
    """`create_app` обязана поставить хук, даже если список хуков пуст.

    Список хуков подменяется пустым на время теста. Так проверяется ровно то,
    что нужно: сборка приложения зовёт `register_hooks` сама, а не полагается на
    импорт модуля — импорт случается один раз на процесс, а приложений в
    процессе десятки, по штуке на тест.
    """
    from api import create_app
    from api.accounts import service as аккаунты

    monkeypatch.setattr(аккаунты, "on_user_created", [])
    create_app(settings)
    assert create_personal in аккаунты.on_user_created


def test_хук_стоит_в_настоящих_аккаунтах(app):
    """У живого приложения хук стоит в настоящем списке `accounts`."""
    assert create_personal in on_user_created


def test_личное_не_удаляется(клиент, хозяин):
    личное = личное_id(клиент)
    ответ = клиент.delete(f"/api/workspaces/{личное}")
    assert ответ.status_code == 409
    assert ответ.json()["error"]["code"] == "personal_workspace"


def test_личное_идёт_первым_в_списке(клиент, хозяин):
    клиент.post("/api/workspaces", json={"name": "кафедра"})
    список = клиент.get("/api/workspaces").json()["workspaces"]
    assert [w["personal"] for w in список] == [True, False]
    assert список[0]["role"] == OWNER


# ── создание и переименование ────────────────────────────────────────────────

def test_создать_и_переименовать(клиент, хозяин):
    ws = клиент.post("/api/workspaces", json={"name": "  кафедра  "}).json()
    assert ws["name"] == "кафедра", "имя не обрезано по краям"
    assert ws["personal"] is False and ws["role"] == OWNER

    ответ = клиент.patch(f"/api/workspaces/{ws['id']}", json={"name": "кафедра 2"})
    assert ответ.status_code == 200
    assert ответ.json()["name"] == "кафедра 2"


def test_пустое_имя_отвергается(клиент, хозяин):
    ответ = клиент.post("/api/workspaces", json={"name": ""})
    assert ответ.status_code == 422
    assert ответ.json()["error"]["where"] == "body.name"


def test_кривой_идентификатор_не_доходит_до_базы(клиент, хозяин):
    ответ = клиент.get("/api/workspaces/../../etc/passwd")
    assert ответ.status_code in (400, 404)
    if ответ.status_code == 400:
        assert ответ.json()["error"]["code"] == "invalid_id"


# ── роли ─────────────────────────────────────────────────────────────────────

def test_чужое_пространство_это_404(app, клиент, хозяин, сосед):
    """Не участник получает то же, что и на несуществующий идентификатор."""
    ws = клиент.post("/api/workspaces", json={"name": "кафедра"}).json()
    войти(app, сосед)
    ответ = клиент.get(f"/api/workspaces/{ws['id']}")
    assert ответ.status_code == 404
    assert ответ.json()["error"]["code"] == "not_found"


def test_viewer_читает_но_не_меняет(app, клиент, хозяин, сосед):
    """Участник с малой ролью получает 403: он и так видит объект."""
    ws = клиент.post("/api/workspaces", json={"name": "кафедра"}).json()
    добавлен = клиент.post(f"/api/workspaces/{ws['id']}/members",
                           json={"email": сосед.email, "role": VIEWER})
    assert добавлен.status_code == 201

    войти(app, сосед)
    assert клиент.get(f"/api/workspaces/{ws['id']}").status_code == 200
    ответ = клиент.patch(f"/api/workspaces/{ws['id']}", json={"name": "чужое"})
    assert ответ.status_code == 403
    assert ответ.json()["error"]["code"] == "forbidden"


def test_editor_не_трогает_участников(app, клиент, хозяин, сосед):
    """Участники — дело владельца: `editor` меняет проекты, а не людей."""
    ws = клиент.post("/api/workspaces", json={"name": "кафедра"}).json()
    клиент.post(f"/api/workspaces/{ws['id']}/members",
                json={"email": сосед.email, "role": EDITOR})
    войти(app, сосед)
    ответ = клиент.post(f"/api/workspaces/{ws['id']}/members",
                        json={"email": "кто-то@пример.рф", "role": VIEWER})
    assert ответ.status_code == 403


def test_require_role_вне_запроса(app, хозяин):
    """Форма для соседей: сессия и идентификаторы, без `Request`."""
    from api.errors import ApiError

    with app.state.db.session_scope() as s:
        личное = personal_workspace(s, хозяин.id)
        assert require_role(s, хозяин.id, личное.id, OWNER).id == личное.id
        with pytest.raises(ApiError) as беда:
            require_role(s, "00000000-0000-4000-8000-000000000000", личное.id)
        assert беда.value.status == 404


# ── участники ────────────────────────────────────────────────────────────────

def test_участник_по_почте_и_смена_роли(клиент, хозяин, сосед):
    ws = клиент.post("/api/workspaces", json={"name": "кафедра"}).json()
    добавлен = клиент.post(f"/api/workspaces/{ws['id']}/members",
                           json={"email": сосед.email.upper(), "role": VIEWER})
    assert добавлен.status_code == 201, "почта сравнивается с учётом регистра"
    assert добавлен.json() == {"user_id": сосед.id, "role": VIEWER}

    ещё_раз = клиент.post(f"/api/workspaces/{ws['id']}/members",
                          json={"email": сосед.email, "role": EDITOR})
    assert ещё_раз.status_code == 409
    assert ещё_раз.json()["error"]["code"] == "already_member"

    смена = клиент.patch(f"/api/workspaces/{ws['id']}/members/{сосед.id}",
                         json={"role": EDITOR})
    assert смена.status_code == 200 and смена.json()["role"] == EDITOR

    убрали = клиент.delete(f"/api/workspaces/{ws['id']}/members/{сосед.id}")
    assert убрали.status_code == 200
    остались = клиент.get(f"/api/workspaces/{ws['id']}/members").json()["members"]
    assert [m["user_id"] for m in остались] == [хозяин.id]


def test_список_участников_называет_почты(клиент, хозяин, сосед):
    """Список участников — это список людей, а не идентификаторов.

    Почта в ответе нужна интерфейсу: своего имени у аккаунта нет, и решение
    «кого убрать» человек принимает по почте, а не по uuid.
    """
    ws = клиент.post("/api/workspaces", json={"name": "кафедра"}).json()
    клиент.post(f"/api/workspaces/{ws['id']}/members",
                json={"email": сосед.email, "role": EDITOR})
    участники = клиент.get(f"/api/workspaces/{ws['id']}/members").json()["members"]
    почты = {m["user_id"]: m["email"] for m in участники}
    assert почты == {хозяин.id: хозяин.email, сосед.id: сосед.email}
    assert all(m["created_at"] for m in участники), "даты вступления нет"


def test_неизвестная_почта_и_неизвестная_роль(клиент, хозяин, сосед):
    ws = клиент.post("/api/workspaces", json={"name": "кафедра"}).json()
    нет = клиент.post(f"/api/workspaces/{ws['id']}/members",
                      json={"email": "никого@пример.рф", "role": VIEWER})
    assert нет.status_code == 404 and нет.json()["error"]["code"] == "no_such_user"

    роль = клиент.post(f"/api/workspaces/{ws['id']}/members",
                       json={"email": сосед.email, "role": "админ"})
    assert роль.status_code == 400
    assert роль.json()["error"]["code"] == "unknown_role"


def test_последнего_владельца_не_убрать(клиент, хозяин):
    ws = клиент.post("/api/workspaces", json={"name": "кафедра"}).json()
    убрать = клиент.delete(f"/api/workspaces/{ws['id']}/members/{хозяин.id}")
    assert убрать.status_code == 409
    assert убрать.json()["error"]["code"] == "last_owner"

    понизить = клиент.patch(f"/api/workspaces/{ws['id']}/members/{хозяин.id}",
                            json={"role": EDITOR})
    assert понизить.status_code == 409


# ── корзина ──────────────────────────────────────────────────────────────────

def test_корзина_и_восстановление(клиент, хозяин):
    ws = клиент.post("/api/workspaces", json={"name": "кафедра"}).json()
    удалено = клиент.delete(f"/api/workspaces/{ws['id']}")
    assert удалено.status_code == 200
    тело = удалено.json()
    assert тело["deleted_at"] and тело["purge_after"] > тело["deleted_at"]

    обычный = клиент.get("/api/workspaces").json()["workspaces"]
    assert ws["id"] not in [w["id"] for w in обычный], "удалённое видно в списке"
    в_корзине = клиент.get("/api/workspaces", params={"trash": True}).json()
    assert [w["id"] for w in в_корзине["workspaces"]] == [ws["id"]]

    # Обычные маршруты удалённого не показывают: оно есть только в корзине.
    assert клиент.get(f"/api/workspaces/{ws['id']}").status_code == 404

    вернули = клиент.post(f"/api/workspaces/{ws['id']}/restore")
    assert вернули.status_code == 200 and вернули.json()["deleted_at"] is None
    assert клиент.post(f"/api/workspaces/{ws['id']}/restore").status_code == 409


def test_создать_личное_дважды_нельзя(app, хозяин):
    """`create_personal` идемпотентна: повторная регистрация той же почты —
    обычное дело на кривой сети, и второго личного пространства она не заводит."""
    with app.state.db.session_scope() as s:
        user = s.get(User, хозяин.id)
        первое = create_personal(s, user)
        второе = create_personal(s, user)
        assert первое.id == второе.id
        сколько = len(s.scalars(select(Workspace).where(
            Workspace.owner_id == user.id, Workspace.personal.is_(True))).all())
    assert сколько == 1


def test_хук_молчит_без_аккаунтов(monkeypatch):
    """Пока пакета аккаунтов нет, `register_hooks` отвечает `False`, а не падает.

    Это не украшение: без этого пространства не собирались бы, пока нет
    аккаунтов, и два подпакета требовали бы друг друга.
    """
    monkeypatch.setitem(sys.modules, "api.accounts", None)
    monkeypatch.setitem(sys.modules, "api.accounts.service", None)
    assert register_hooks() is False
