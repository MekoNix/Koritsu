"""
status — форма того, что API отдаёт сайту, и хранение хода работы там, где его увидят оба.

HTTP здесь не проектируется и не пишется. Отдаётся снимок плюс курсор — ровно
форма записки Е.4, ключ в ключ. Ключи латиницей, значения по-русски: ключи
читает сайт, значения — человек.

Четыре решения, которые эта форма несёт и которые дороже, чем кажутся.

**`state: waiting_user` отдельно от `running`.** Стадия, остановившаяся с
вопросом, иначе неотличима от зависшей работы, и человек нажмёт «отменить» —
то есть выбросит оплаченное. Рядом с состоянием едет `hold`: что именно ему
показывают.

**`spent.share` и `spent.estimated_share` рядом.** Журнал знает, какая доля
расхода оценена, а не измерена. Показать «потрачено 21 %» без пометки, что
четверть этого — прикидка, значит соврать точной цифрой.

**Потолка может не быть.** `cap` и `share` тогда `None`, а не ноль и не
бесконечность: «потолка нет» и «потолок огромный» — разные утверждения, и
первое не должно печатать проценты от выдуманного числа (то же решение, что в
`Project.limit`).

**`since` — номер, а не время.** Сайт дозапрашивает события после номера;
время как курсор ломается на двух записях в одну секунду.

Чего в снимке нет никогда: путей, промпта, метки рамки, OOXML и сырого ответа
модели. Метка особенно: она случайна на прогон именно затем, чтобы её нельзя
было узнать заранее, и утечка её в интерфейс возвращает закрытую дыру.
Готовые файлы называются именем, а не путём, — это проверяется в `stages`.

Хранится ход работы в проекте, а не в памяти процесса: считает один процесс,
показывает другой («всё через очередь»). Дверь для этого — шов «состояние
стадий»; пока его нет, `save`/`load` отказывают с адресом, а не пишут мимо.
"""
from __future__ import annotations

from dataclasses import asdict

from .errors import KadaiError
from .plan import Plan
from .seams import method
from .stages import Hold, StageState, Work, as_dict, stage_now

# Имя записи состояния в проекте. Одно на пакет: две записи разошлись бы, и
# «какая из них настоящая» решалось бы по времени файла.
STATE_KEY = "kadai"


def snapshot(work: Work, *, spent: dict | None = None, problems=(), since: int = 0) -> dict:
    """Снимок для API: стадия, ход, расход, замечания, готовые файлы, курсор.

    Чистая функция от записи о работе и сводки расхода — ни одного обращения к
    диску и ни одного вызова модели. Иначе показ статуса стоил бы денег, а
    сайт опрашивает его раз в секунду.
    """
    stages = []
    for st in work.stages:
        item = {"name": st.name, "state": st.state,
                "started": st.started, "finished": st.finished, "note": st.note}
        if st.total is not None:
            # Полоска рисуется только со знаменателем. Где его нет (стадии 1–3),
            # человеку называют действие строкой `current`, а не долю от неизвестного.
            item["progress"] = {"done": st.done or 0, "total": st.total, "unit": st.unit}
        stages.append(item)
    return {
        "work": work.id,
        "state": work.state,
        "stage": stage_now(work),
        "stages": stages,
        "current": work.current,
        "hold": asdict(work.hold) if work.hold else None,
        "spent": spent if spent is not None else empty_spent(),
        "problems": list(work.problems) + list(problems),
        "outputs": dict(work.outputs),
        "since": work.seq,
        "events": [e for e in work.events if e["n"] > since],
    }


def empty_spent() -> dict:
    """Расход, о котором ещё ничего не известно. Нули, а не выдуманный потолок."""
    return {"units": 0.0, "cost": None, "cap": None, "share": None, "estimated_share": 0.0}


def spent_of(project) -> dict:
    """Сводка расхода проекта в форме снимка: единицы, деньги, потолок, доли.

    Считает `Project.spent()` и `Project.limit()` — свой счётчик здесь завести
    нельзя: лимит считает по записям своего журнала, и второй экземпляр не
    увидел бы того, что записал первый.
    """
    raw = dict(project.spent())
    limit = project.limit()
    cap = getattr(limit, "cap_units", None) if limit is not None else None
    share = limit.share() if limit is not None else None
    return {"units": raw.get("units", 0.0), "cost": raw.get("cost"),
            "cap": cap, "share": share,
            "estimated_share": raw.get("estimated_share", 0.0)}


# ── хранение через шов ───────────────────────────────────────────────────────

def save(project, work: Work) -> None:
    """Ход работы — в проект. Пока шва нет — отказ с подписью, а не запись мимо."""
    method(project, "put_state", "состояние стадий")(STATE_KEY, as_dict(work))


def load(project, plan: Plan) -> Work:
    """Ход работы из проекта. `plan` приходит снаружи: профиль — данные пакета.

    Профиль не хранится в записи копией намеренно: правка профиля тогда не
    доехала бы до уже заведённых работ, а расхождение копий увидеть было бы
    нечем. Плата — вызывающий обязан назвать профиль сам, и запись это
    проверяет: имя профиля в ней сверяется с переданным планом.
    """
    raw = method(project, "state", "состояние стадий")(STATE_KEY)
    if not raw:
        raise KadaiError("в проекте нет записи о работе kadai: сохранять было нечего")
    if raw.get("profile") and raw["profile"] != plan.profile.name:
        raise KadaiError(f'работа заведена по профилю "{raw["profile"]}", '
                         f'а план построен по "{plan.profile.name}"')
    было = set(raw.get("pause_after") or ())
    if было != set(plan.pause_after):
        # Просьба «покажи структуру», потерянная при перезагрузке, тише всего:
        # работа просто не остановится там, где человек её ждал, и он увидит
        # оплаченный до конца прогон вместо экрана с вопросом.
        raise KadaiError(f"работа заведена с остановками {sorted(было) or 'без остановок'}, "
                         f"а план построен с {sorted(plan.pause_after) or 'без остановок'}")
    hold = raw.get("hold")
    return Work(id=raw["work"], plan=plan,
                stages=[StageState(**s) for s in raw.get("stages", ())],
                state=raw.get("state", "running"), current=raw.get("current", ""),
                hold=Hold(**hold) if hold else None,
                problems=list(raw.get("problems", ())), outputs=dict(raw.get("outputs", {})),
                events=list(raw.get("events", ())), started=raw.get("started", ""))


__all__ = ["STATE_KEY", "snapshot", "spent_of", "empty_spent", "save", "load"]
