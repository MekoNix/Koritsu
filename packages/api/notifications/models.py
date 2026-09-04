"""
models — таблица `notifications`: колокольчик и ничего больше.

Решение владельца §11: **писем нет**. Единственный способ узнать, что работа
кончилась, — увидеть это в интерфейсе: точку на колокольчике и строку в списке.
Отсюда и таблица: уведомление обязано пережить закрытую вкладку, а поток
событий (`api/events`) её не переживает. Человек, закрывший ноутбук на прогоне
в двадцать минут, вернётся к списку, а не к пустому экрану.

    notifications   id, user_id, job_id, kind, data, read_at, created_at

**`job_id` отдельной колонкой, а не только внутри `data`.** Колонка нужна ровно
для одного — для `UNIQUE`: уведомление о задании должно появиться ровно один
раз, а «ровно один раз» либо обеспечено схемой, либо не обеспечено ничем.
Проверка «нет ли уже такого» на стороне Python — это два воркера, закрывшие
задание одновременно, и две одинаковые строки в колокольчике. Заодно колонка
даёт каскад: убрали задание по сроку хранения (90 дней) — ушло и уведомление о
нём, иначе колокольчик ссылался бы на карточку, которой нет.

**`data` — JSON без единого объявленного поля**, как `payload` у задания и по
той же причине: что показать человеку, знает тот, кто уведомление завёл. Договор
один и он снаружи: `kind` — короткое слово, по которому интерфейс выбирает
текст и картинку, `data` — то, чем этот текст заполняется.

**`read_at`, а не `read` булевым.** «Когда прочитал» отвечает и на «прочитал
ли», а обратно не работает; а знать, когда человек увидел, что прогон упал,
однажды понадобится — например, чтобы не показывать ту же беду второй раз.
"""
from __future__ import annotations

import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Row
from ..ids import ID_LEN

# Длина имени вида уведомления. Самое длинное сегодня — `limit_exhausted`.
KIND_MAX = 32


class Notification(Row):
    """Одна строка колокольчика.

    `id`, `created_at`, `updated_at` — от `Row`. `updated_at` здесь не лишний,
    в отличие от `job_events`: строка меняется, когда её прочитали.
    """

    __tablename__ = "notifications"

    # Чьё. `CASCADE` — то же обещание §7, что у заданий: удалили аккаунт, значит
    # и уведомлений его нет.
    user_id: Mapped[str] = mapped_column(
        String(ID_LEN), ForeignKey("users.id", ondelete="CASCADE"))

    # О каком задании. Необязателен: уведомление бывает и не про задание
    # (сегодня таких нет, но `limit_exhausted` при постановке — очевидный
    # следующий). `UNIQUE` — см. докстроку модуля.
    job_id: Mapped[str | None] = mapped_column(
        String(ID_LEN), ForeignKey("jobs.id", ondelete="CASCADE"), default=None,
        unique=True)

    kind: Mapped[str] = mapped_column(String(KIND_MAX))

    data: Mapped[dict] = mapped_column(JSON, default=dict)

    read_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), default=None)

    __table_args__ = (
        # Что спрашивает колокольчик: «мои непрочитанные, новые сверху».
        # Тройка, а не три индекса по одному: запрос один и он всегда такой.
        Index("ix_notifications_user_read", "user_id", "read_at", "created_at"),
    )


__all__ = ["Notification", "KIND_MAX"]
