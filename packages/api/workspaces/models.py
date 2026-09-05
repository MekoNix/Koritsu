"""
models — две таблицы: рабочее пространство и его участники.

`workspaces` — обычная строка `Row` (`id`, `created_at`, `updated_at` даром).
`workspace_members` наследует `Base` напрямую и объявляет составной ключ, как и
велит докстрока `db.py`: у связки «пространство × человек» своего
идентификатора нет, а составной ключ — это ещё и обещанная уникальность пары,
которую иначе пришлось бы держать вторым ограничением.

**Внешние ключи на `users.id` настоящие, с `ON DELETE CASCADE`.** Довод записан
в `db.py`: без них «удаление пользователя оставит его сессии и проекты висеть на
несуществующем владельце». Таблицу `users` заводит другая миграция; на SQLite
ссылка на ещё не созданную таблицу при `CREATE TABLE` проходит и начинает
проверяться только на первой вставке, так что порядок применения двух миграций
роли не играет.

**Личное пространство помечено полем, а не именем.** Имя человек переименует
через час после регистрации, и правило «личное не удаляют» превратилось бы в
сравнение строк.

**Участие бывает не принятым.** Приглашение не делает человека участником
сразу: строка заводится со `status = "pending"` и становится `"active"`, только
когда приглашённый ответил «принять». Отдельная таблица приглашений здесь не
нужна и была бы хуже: у приглашения ровно те же поля, что у участия
(пространство, человек, роль), и вторая таблица означала бы перенос строки из
одной в другую на каждое согласие — то есть два места, где может остаться
половина.

**Корзина — те же два поля, что у проектов**: `deleted_at` (когда положили) и
`purge_after` (когда физически убирать). Оба на пространстве, а не только на
проектах, потому что удаление пространства кладёт в корзину и его проекты, и
восстановление обязано уметь достать оттуда ровно их — по совпадению `deleted_at`
(см. `service.restore`).
"""
from __future__ import annotations

import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base, Row
from ..ids import ID_LEN

# Длина имени. Не «сколько влезет»: имя показывается списком, и строка на
# мегабайт ломает не базу, а вёрстку у того, кому пространство прислали.
NAME_MAX = 200

# Длина состояния участия (`service.STATUSES`). Как у роли и по той же причине:
# список закрыт, и проверяет его код, а не `CHECK`.
STATUS_MAX = 16


class Workspace(Row):
    """Рабочее пространство: владелец, участники, проекты."""

    __tablename__ = "workspaces"

    name: Mapped[str] = mapped_column(String(NAME_MAX))
    owner_id: Mapped[str] = mapped_column(
        String(ID_LEN), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    # Личное заводится при регистрации и не удаляется никогда.
    personal: Mapped[bool] = mapped_column(Boolean, default=False)
    deleted_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), default=None, index=True)
    purge_after: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), default=None, index=True)


class WorkspaceMember(Base):
    """Участие человека в пространстве и его роль. Пара уникальна по ключу."""

    __tablename__ = "workspace_members"

    workspace_id: Mapped[str] = mapped_column(
        String(ID_LEN), ForeignKey("workspaces.id", ondelete="CASCADE"),
        primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(ID_LEN), ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True)
    # Значение из `service.ROLES`. Проверяется кодом, а не `CHECK`: список ролей
    # ещё поедет, а `CHECK` на SQLite меняется только
    # пересборкой таблицы.
    role: Mapped[str] = mapped_column(String(16))
    # `active` — участник, `pending` — позван и ещё не ответил. Умолчание
    # `active` стоит и на стороне базы: строки, заведённые до появления
    # приглашений, — это принятые участия, а не висящие приглашения.
    status: Mapped[str] = mapped_column(
        String(STATUS_MAX), default="active", server_default="active")
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.datetime.now(
            datetime.timezone.utc))


__all__ = ["Workspace", "WorkspaceMember", "NAME_MAX", "STATUS_MAX"]
