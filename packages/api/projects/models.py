"""
models — одна таблица: индекс проектов. Содержимое проекта лежит на томе.

Решение владельца §7 (третий круг): «значения тегов остаются файлами, база
хранит индекс». Поэтому здесь нет ни тегов, ни версий, ни манифеста — только то,
без чего проект не найти: чей он, в каком пространстве, как называется и не в
корзине ли. Всё остальное умеет `orchestrator.Project`, и второе описание
проекта в базе разошлось бы с каталогом на первом же переименовании тега.

**`owner_id` — кто создал, а не кто пользуется.** Квота считается на владельца
(§1: «чужие проекты в общем workspace едят место того, кто их создал»), и
каталог на томе лежит у него же: `/data/users/<owner>/projects/<project>/`.
Отсюда важное следствие: `owner_id` не меняется никогда — смена владельца
означала бы переезд каталога, а путь к нему помнят материалы и артефакты.

Пути в базе не хранится. Он вычисляется из двух uuid (`service.project_dir`),
и это не экономия места: путь в строке — это путь, который однажды разойдётся с
диском, и вычислить его заново будет уже неоткуда.
"""
from __future__ import annotations

import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Row
from ..ids import ID_LEN

NAME_MAX = 200


class Project(Row):
    """Строка индекса одного проекта. Тёзка `orchestrator.Project` — намеренно:
    это одна и та же вещь с двух сторон, база знает «чей и где», каталог —
    «что внутри». Внутри пакета оркестраторный зовут через модуль
    (`orchestrator.Project`), чтобы имена не путались."""

    __tablename__ = "projects"

    workspace_id: Mapped[str] = mapped_column(
        String(ID_LEN), ForeignKey("workspaces.id", ondelete="CASCADE"),
        index=True)
    owner_id: Mapped[str] = mapped_column(
        String(ID_LEN), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(NAME_MAX))
    deleted_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), default=None, index=True)
    purge_after: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), default=None, index=True)


__all__ = ["Project", "NAME_MAX"]
