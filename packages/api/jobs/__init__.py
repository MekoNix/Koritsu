"""
jobs — очередь заданий и воркер: всё, что служба делает не в момент запроса.

Работа, ради которой Koritsu существует, — заполнить
тег, собрать отчёт, разобрать присланный файл — длится минуты, а HTTP-запрос
столько не живёт: браузер оборвёт его, прокси оборвёт его, а человек уйдёт со
страницы. Поэтому запрос делает одно: кладёт задание в таблицу и отвечает `202`
с его идентификатором. Работу делает другой процесс.

    models.py     таблицы `jobs` и `job_events`
    registry.py   какие бывают виды заданий и кто их исполняет
    context.py    `JobContext` — то единственное, что видит обработчик
    child.py      что происходит в подпроцессе задания
    worker.py     захват, исполнение, отмена, потерянные, уборка
    probe.py      проба очереди: единственный обработчик, живущий здесь
    service.py    постановка, выборка своих, отмена, уборка старых
    routes.py     `/api/jobs`

    Как добавить новый вид задания
    ------------------------------

Три шага, и все три описаны в докстроке `registry.py` (там же — пример
обработчика целиком):

1. имя вида — в `registry.ВИДЫ`;
2. функция `fn(ctx: JobContext) -> dict` под декоратором
   `@register("имя", needs_project=…, needs_secret=…)`, в **своём** модуле —
   не в этом пакете: очередь не знает ни про прогоны модели, ни про архивы;
3. строка импорта — в `registry.load_handlers()`.

Из кода задание ставится одной строкой:

    from ..jobs import service as jobs
    задание = jobs.enqueue(s, user, "parse", {"material": mid},
                           project_id=проект.id)

Обработчик пишет о ходе работы через контекст:

    ctx.progress(3, 10, note="цель")          # и колонка, и событие в поток
    ctx.emit({"kind": "text", "text": "…"})   # склеивается, ~100 мс
    ctx.emit({"kind": "tag_closed", "key": "цель"})
    ctx.charge(50)                            # доплата сверх цены вида, редко
    if ctx.cancelled(): ...                   # между шагами, обязательно

    Что здесь не решается
    ---------------------

**SSE** — поток встал поверх той же выборки (`service.события`), а не поверх
второй таблицы. **Сколько человеку положено** — не здесь: очередь пишет
потраченное (`spent_units`, цена вида при захвате), но потолок — свойство
подписки, а не задания, и живёт он в `runs/limits`.
**Уведомления** — B. **Админка очереди** — C.

    Границы
    -------

Пакет не импортирует ни `orchestrator`, ни `hokoku` — кроме одного места и
лениво: `JobContext.project` открывает каталог проекта, потому что обработчику
нужен именно `orchestrator.Project`, а не путь. Всё остальное про предметную
работу живёт у обработчиков, то есть в чужих модулях.
"""
from __future__ import annotations

from .context import JobContext
from .models import (CANCELLED, DONE, FAILED, Job, JobEvent, QUEUED, RUNNING,
                     STATUSES, TERMINAL)
from .registry import (register, load_handlers, check_kind, handler_for,
                       needs_project, needs_secret, ВИДЫ)
from .routes import router
from .service import (enqueue, карточка, карточка_события, мои, отменить,
                      получить, события, убрать_старые)
from .worker import Worker, новое_имя

__all__ = ["Job", "JobEvent", "JobContext", "Worker", "router",
           "register", "load_handlers", "check_kind", "handler_for",
           "needs_project", "needs_secret", "ВИДЫ",
           "enqueue", "мои", "получить", "события", "отменить",
           "убрать_старые", "карточка", "карточка_события", "новое_имя",
           "QUEUED", "RUNNING", "DONE", "FAILED", "CANCELLED", "STATUSES",
           "TERMINAL"]
