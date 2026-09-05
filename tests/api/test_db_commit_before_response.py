"""
Коммит сессии запроса — до отправки ответа, а не после.

Зачем это проверять отдельно: FastAPI (с 0.118) по умолчанию доигрывает код
после `yield` в зависимости уже после того, как ответ ушёл клиенту. Тогда
«200 + cookie сессии» приезжает в браузер раньше, чем строка сессии оказывается
в базе, и следующий запрос того же браузера (`/api/auth/me` сразу после входа)
получает 401. Последовательный `TestClient` этого окна не видит — запросы идут
по очереди, и коммит всегда успевает. Поэтому здесь приложение оборачивается
в чистый ASGI-слой, который в момент отправки тела ответа заглядывает в базу
**другой** сессией: строка обязана быть уже там.
"""
from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from api.accounts.models import User

ПОЧТА = "commit-before-response@example.com"


def _обёртка(app, увидено: list[int]):
    """ASGI-слой: при первом кадре тела ответа считает пользователей в базе
    отдельной сессией и запоминает число. Одна сессия на подсчёт, а не
    сессия запроса: та ещё открыта, и через неё видна собственная
    незакоммиченная запись — проверка была бы бессмысленной."""
    async def приложение(scope, receive, send):
        async def отправить(сообщение):
            if сообщение["type"] == "http.response.body":
                with app.state.db.session_scope() as s:
                    увидено.append(
                        s.scalar(select(func.count()).select_from(User)
                                 .where(User.email == ПОЧТА)) or 0)
            await send(сообщение)
        await app(scope, receive, отправить)
    return приложение


def test_запись_видна_другой_сессии_уже_при_отправке_ответа(app):
    увидено: list[int] = []
    with TestClient(_обёртка(app, увидено), raise_server_exceptions=False) as c:
        r = c.post("/api/auth/register",
                   json={"email": ПОЧТА, "password": "Пароль-очень-длинный-123"})
    assert r.status_code == 201, r.text
    # Первый кадр тела — и пользователь уже в базе. Без `scope="function"` у
    # `SessionDep` здесь был бы ноль: коммит прошёл бы после этого кадра.
    assert увидено and увидено[0] == 1, увидено
