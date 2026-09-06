"""
kadai_run — сценарий работы над документом: семь стадий от условия до архива.

    payload   {"endpoint": "deepseek", "run_id": "<решение работы>",
               "wishes": {"text": "…", "show_task": true,
                          "show_structure": false},
               "until": "тексты"}
    result    {"work": "w-…", "state": "running", "stage": "тексты",
               "stages": [{"name": …, "state": …}, …],
               "outputs": {...}, "artifacts": {"archive": …, "docx": …},
               "key_source": "shared"}

**Какое решение работы считается, говорит `run_id`.** В работе их несколько, и
у каждого свой ход стадий, своё условие и свой список блоков; читает поле
`JobContext.project`, а не этот обработчик, — иначе пять обработчиков прочли бы
одно поле по-разному. Поля нет — работа целиком, как она выглядела, пока
решение в ней было одно.

**Что модель видит из файлов работы**, решает `Project.context_ids`: файлы
папки самого решения, его условие и общие файлы работы, с которых человек не
снял галочку (`PUT …/kadai/context`). Общие входят по умолчанию — методичку
кладут один раз на работу, а нужна она в каждой её задаче.

**Пожелания без `payload` берутся из проекта** (`PUT …/kadai/wishes`).
Названное в задании старше записанного: прогон «с
другими пожеланиями» иначе повторял бы прежние.

**`artifacts` — то, что можно скачать.** `outputs` сценария это **имена**
файлов, и по имени с сайта не скачивается ничего; идентификаторы кладёт
`orchestrator.kadai` (DOCX и PDF — стадия «сборка», ZIP — стадия «архив»), а
поле называется так же, как у `build`, потому что читает его один и тот же
колокольчик.

**Сценарий зовётся через `orchestrator.kadai`, а не напрямую.** `api` не
импортирует `kadai` ни одной строкой: соседей знает только оркестратор, и
обработчик задания — последнее место, где эту стрелку стоило бы
разворачивать. Обёртки живут в `orchestrator/kadai.py` и там же объяснены.

**Стадия — единица доклада.** После каждой в поток уезжает событие `stage`, а в
`progress` — «сделано N из семи». Одним куском на весь прогон это выглядело бы
как зависшая полоска на полчаса: сценарий идёт стадиями по нескольку минут, и
человек смотрит именно на них.

**Отмена спрашивается между стадиями.** Внутри стадии её ловит провод
(`common.Отмена` уезжает дверям через endpoint), а между — мы: там остановка
ничего не стоит, потому что ход работы сохраняется после каждой стадии
(`status.save`), и повторный запуск продолжит с той же точки.
"""
from __future__ import annotations

from orchestrator import kadai as сценарий

from ...errors import ApiError
from ...jobs.registry import KADAI_RUN, register
from .common import Прогон, отменено

KADAI_FAILED = "kadai_failed"
UNKNOWN_STAGE = "unknown_stage"


def прогнать(ctx) -> dict:
    """Пройти стадии сценария, докладывая о каждой."""
    payload = ctx.job.payload or {}
    до = str(payload.get("until") or "").strip() or None
    имена = сценарий.stage_names()
    if до is not None and до not in имена:
        raise ApiError(UNKNOWN_STAGE,
                       f"payload.until must be one of: {', '.join(имена)}",
                       400, where="body.payload.until")

    сделано = [0]
    with Прогон(ctx) as прогон:
        пожелания = _пожелания(payload.get("wishes"), прогон.project)
        ctx.progress(0, len(имена), note="")
        if ctx.cancelled():
            return отменено(ctx, "")

        def на_стадию(имя: str, снимок: dict) -> None:
            сделано[0] += 1
            состояние = _состояние(снимок, имя)
            прогон.стадия(имя, состояние, note=str(снимок.get("current") or ""))
            ctx.progress(сделано[0], len(имена), note=имя)

        try:
            снимок = сценарий.work(прогон.project, endpoint=прогон.ep,
                                   wishes=пожелания, until=до,
                                   on_stage=на_стадию, stop=ctx.cancelled)
        except Exception as беда:                            # noqa: BLE001
            # Сценарий бросает своё (`KadaiError`, `NotReady`), и ловить его по
            # имени значило бы импортировать `kadai` — ровно то, чего этот
            # модуль не делает. Текст уезжает наружу: он по-русски, написан для
            # человека и путей на томе не содержит (`kadai/errors.py`).
            raise ApiError(KADAI_FAILED, str(беда), 422,
                           where="body.payload") from None

    собрано = dict(снимок.get("made") or {})
    итог = {"work": снимок.get("work"), "state": снимок.get("state"),
            "stage": снимок.get("stage"),
            "stages": [{"name": st.get("name"), "state": st.get("state")}
                       for st in (снимок.get("stages") or ())],
            "hold": снимок.get("hold"),
            "outputs": dict(снимок.get("outputs") or {}),
            "problems": len(снимок.get("problems") or ()),
            "key_source": прогон.источник}
    if собрано:
        # `artifacts` — то же поле, каким отвечает `build` (`runs/handlers/build.py`),
        # и читает его колокольчик (`notifications.service.артефакты`). Без него
        # ссылка «Скачать» в уведомлении о законченной работе не появилась бы
        # вовсе: `outputs` — это **имена** файлов, а скачивают по идентификатору.
        итог["artifacts"] = собрано
    return итог


def _пожелания(сырое, project) -> dict:
    """Пожелания к работе: из `payload`, а пусто — из проекта.

    Приводим к трём известным полям, а не отдаём словарь как есть: лишний ключ
    уронил бы `Wishes(**...)` беспричинным `TypeError`, а список полей —
    договор сценария, и повторять его в клиенте незачем.

    Пусто в задании — читаем проект (`PUT …/kadai/wishes`). Порядок именно
    такой: названное в задании старше записанного,
    иначе прогон «с другими пожеланиями» повторял бы прежние. Обратный порядок
    к тому же сделал бы запись бесполезной — сайт кладёт пожелания в первый
    прогон, и они всегда были бы непустыми.
    """
    сырое = сырое if isinstance(сырое, dict) else {}
    просьба = {"text": str(сырое.get("text") or ""),
               "show_task": bool(сырое.get("show_task")),
               "show_structure": bool(сырое.get("show_structure"))}
    if any(просьба.values()):
        return просьба
    return сценарий.wishes(project)


def _состояние(снимок: dict, имя: str) -> str:
    for st in снимок.get("stages") or ():
        if st.get("name") == имя:
            return str(st.get("state") or "")
    return ""


def _зарегистрировать() -> None:
    """См. `fill_tag._зарегистрировать` — довод тот же."""
    register(KADAI_RUN, needs_secret=True)(прогнать)


__all__ = ["прогнать", "_зарегистрировать", "KADAI_FAILED", "UNKNOWN_STAGE"]
