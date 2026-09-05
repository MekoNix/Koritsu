"""
projects — проекты, их каталоги на томе и корзина.

Проект здесь — две вещи сразу и обе нужны:

* **строка индекса** (`models.Project`): чей, в каком пространстве, как зовут,
  не в корзине ли. Без неё список проектов означал бы обход тома;
* **каталог** (`orchestrator.Project`): шаблон, манифест, материалы, значения
  тегов с версиями, журнал. Без него служба завела бы второе описание
  проекта — ровно то, что запрещено: значения остаются файлами, база хранит
  индекс.

Раскладка на томе — `{data_dir}/users/<owner>/projects/<project>/`, и
собирает её одно место: `service.dir_for`. Наружу путь не уезжает никогда:
клиент видит идентификаторы и число байт (`ids.py`).

Что отсюда нужно соседям (квоты и материалы):

    bytes_used(session, settings, owner_id) -> int      сколько занял владелец
    project_dir(session, settings, project_id) -> str   каталог проекта по его id
    workspaces.require_role(session, user_id, ws_id, role)   доступ

Корзина: `deleted_at` + `purge_after = deleted_at + settings.trash_days`.
Физически убирает `purge_expired(session, settings)` — её зовут консольная
команда `purge` и воркер очереди.
"""
from .models import Project
from .service import (bytes_used, dir_for, dir_size, project_dir, purge_expired,
                      restore, trash, user_dir)

__all__ = ["Project", "bytes_used", "dir_size", "dir_for", "user_dir",
           "project_dir", "purge_expired", "trash", "restore"]
