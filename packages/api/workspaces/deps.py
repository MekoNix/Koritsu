"""
deps — кто спрашивает: одна точка, через которую зона C берёт вошедшего.

Аккаунты — зона агента B (`api.accounts`: модель `User`, зависимость
`current_user`, псевдоним `CurrentUser`). Пока его пакета нет, маршруты
пространств и проектов всё равно обязаны собираться: иначе половина службы не
импортируется, пока не готова другая половина, и два агента ждут друг друга
вместо работы.

Отсюда заглушка — и она устроена так, что **не может тихо остаться в проде**:
без аккаунтов любой защищённый маршрут отвечает `401 unauthorized`, а не пускает
безымянного. Заглушка ничего не разрешает; она лишь позволяет собрать
приложение и подменить зависимость в тесте
(`app.dependency_overrides[current_user] = ...`).

Импортируют отсюда, а не из `..accounts` напрямую, ровно по одной причине:
подмена в тестах работает по **объекту функции**, и второй импорт того же имени
из другого места дал бы второй ключ в `dependency_overrides` — то есть
подменённую зависимость в одном маршруте и настоящую в соседнем.
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Annotated, Any

from fastapi import Depends
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from ..errors import ApiError

UNAUTHORIZED = "unauthorized"

try:                                                    # пакет B, когда он есть
    from ..accounts import CurrentUser, current_user    # type: ignore
except Exception:                                       # noqa: BLE001 — B ещё нет
    def current_user() -> Any:
        """Заглушка на время, пока нет аккаунтов: вошедших не бывает."""
        raise ApiError(UNAUTHORIZED, "Authentication required", 401)

    CurrentUser = Annotated[Any, Depends(current_user)]


def user_id_by_email(s: Session, email: str) -> str | None:
    """Найти человека по почте. Нужно ровно одному месту — «добавить участника».

    Почта сравнивается без регистра: человек, приглашающий коллегу, набирает её
    руками, и `Ivan@` вместо `ivan@` — это не другой человек, а другая раскладка.

    Две ветки, потому что таблица `users` принадлежит B, а маршрут — нам: пока
    его модели нет, читаем ту же таблицу через Core. Когда B на месте, работает
    первая ветка, и запасная не выполняется вовсе.
    """
    нужная = (email or "").strip().lower()
    if not нужная:
        return None
    try:
        from ..accounts import User                     # type: ignore
    except Exception:                                   # noqa: BLE001 — B ещё нет
        row = s.execute(text("SELECT id FROM users WHERE lower(email) = :e"),
                        {"e": нужная}).first()
        return None if row is None else str(row[0])
    from sqlalchemy import func
    return s.scalar(select(User.id).where(func.lower(User.email) == нужная))


def emails_by_ids(s: Session, ids: Sequence[str]) -> dict[str, str]:
    """Почты по идентификаторам: `{id: email}`. Нужно списку участников.

    Список участников хранит только идентификаторы (`workspace_members`), а
    человеку показывать нечего: чужой uuid не отличить от соседнего, и «кого
    убрать» по нему не решается. Почта — то единственное имя, которое у
    аккаунта есть (своего имени служба не хранит), и знает её тот же, кто по
    ней приглашал.

    Одним запросом на весь список, а не по строке: пространство на два десятка
    человек иначе стоило бы два десятка обходов таблицы ради одной колонки.

    Две ветки — по той же причине, что и у `user_id_by_email`: таблица `users`
    принадлежит аккаунтам, а маршрут — нам.
    """
    нужные = [str(i) for i in ids if i]
    if not нужные:
        return {}
    try:
        from ..accounts import User                     # type: ignore
    except Exception:                                   # noqa: BLE001 — B ещё нет
        места = ", ".join(f":i{n}" for n in range(len(нужные)))
        строки = s.execute(
            text(f"SELECT id, email FROM users WHERE id IN ({места})"),
            {f"i{n}": знач for n, знач in enumerate(нужные)}).all()
        return {str(строка[0]): str(строка[1]) for строка in строки}
    return {str(айди): str(почта) for айди, почта in
            s.execute(select(User.id, User.email).where(User.id.in_(нужные))).all()}


__all__ = ["current_user", "CurrentUser", "user_id_by_email", "emails_by_ids",
           "UNAUTHORIZED"]
