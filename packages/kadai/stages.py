"""
stages — семь стадий работы, их состояния и единственный механизм остановки.

Границы между стадиями проведены там, где меняется цена ошибки, а не там, где
удобно рисовать полоску (записка Е.1). Отсюда семь, а не три и не двенадцать:
после стадии «шаблон» всё дорогое уже завязано на понимание условия и на
структуру, и исправлять их после стадии «тексты» значит выбрасывать оплаченное.

Что здесь важно и неочевидно.

**Пропущенная стадия — отдельное состояние.** У реферата не будет «решения»:
ему не нужны ни код, ни схемы. Показать её как мгновенно прошедшую значило бы
сказать человеку, что работа сделана, хотя её не было; показать как «ждёт» —
что прогон завис. Поэтому `пропущена` стоит рядом с `сделано` и различима.

**Остановка одна на два повода.** Просьба человека («покажи структуру») живёт в
плане, требование стадии (распознанное OCR условие обязано быть подтверждено —
решение владельца 2026-08-31) приходит в момент завершения стадии. Оба ведут в
одно состояние `waiting_user` через один вызов. Но снимок обязан говорить, ЧТО
именно показывают: без этого ожидание неотличимо от зависшей работы, и человек
нажмёт «отменить» — то есть выбросит оплаченное.

**Счётчик только там, где есть знаменатель.** Блоки — «написано 9 из 12»,
ходы петли — «шаг 4 из 12». У стадий 1–3 знаменателя нет, и полоска с
выдуманным знаменателем врёт: там называется действие, а не доля.

**События нумеруются.** Сайт дозапрашивает то, что после номера; время как
курсор ломается на двух записях в одну секунду. Номер — свой, маленький,
монотонный на работу.

Чего здесь нет: исполнения стадий. Машина знает, что стадия началась и чем
кончилась; кто её делает — `orchestrator` и швы.
"""
from __future__ import annotations

import datetime
import secrets
from dataclasses import asdict, dataclass, field

from .errors import KadaiError, hint
from .plan import Plan

# Состояния стадии. Значения по-русски: они доезжают до человека как есть.
WAITING, RUNNING, DONE, STUMBLED, SKIPPED = "ждёт", "идёт", "сделано", "споткнулась", "пропущена"
STAGE_STATES = (WAITING, RUNNING, DONE, STUMBLED, SKIPPED)

# Состояния работы целиком — ключи API (записка Е.4), поэтому латиницей.
# `waiting_user` отдельно от `running` намеренно: без него остановка на вопросе
# неотличима от зависшей работы.
WORK_STATES = ("running", "waiting_user", "done", "failed", "cancelled")


@dataclass(frozen=True)
class StageKind:
    """Одна из семи стадий как вид, а не как ход конкретной работы.

    `unit` пуст там, где знаменателя нет; по нему и решается, рисовать полоску
    или называть действие. Хранить это данными, а не знанием в интерфейсе,
    приходится потому, что интерфейсов будет несколько (CLI, сайт), и второй
    нарисовал бы полоску там, где первый её не рисует.
    """

    name: str
    n: int
    model: str          # чем стадия платит: «нет», «1 вызов», «петля», «поток»
    makes: str          # что произведено к её концу
    unit: str = ""      # единица счётчика, если знаменатель есть


STAGES: tuple = (
    StageKind("приём", 1, "нет", "материалы разобраны, опись готова", "материал"),
    StageKind("разбор задания", 2, "1 вызов", "требование: вид работы, тема, что дано, чего не хватает"),
    StageKind("шаблон", 3, "1 вызов", "строение работы и скелет: блоки-заголовки и места под содержимое"),
    StageKind("решение", 4, "петля", "код, схемы, таблицы — нетекстовые блоки", "шаг"),
    StageKind("тексты", 5, "поток", "связный текст всех блоков одним проходом", "блок"),
    StageKind("сборка", 6, "нет", "DOCX, PDF, список замечаний"),
    StageKind("архив", 7, "нет", "ZIP"),
)
STAGE_NAMES = tuple(s.name for s in STAGES)
BY_NAME = {s.name: s for s in STAGES}

# Что человеку показывают, когда прогон встал после этой стадии. Словами, а не
# именем стадии: «ждёт: шаблон» не говорит, чего от него хотят, и работа
# выглядит зависшей ровно так же, как если бы она зависла.
SHOWN = {
    "приём": "что разобрано из ваших файлов",
    "разбор задания": "как мы поняли задание",
    "шаблон": "структуру отчёта",
}


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


@dataclass
class StageState:
    """Ход одной стадии в одной работе."""

    name: str
    state: str = WAITING
    started: str | None = None
    finished: str | None = None
    done: int | None = None
    total: int | None = None
    unit: str = ""
    note: str = ""


@dataclass
class Hold:
    """Почему прогон стоит и что именно показывают человеку.

    `show` — не украшение: «ждёт подтверждения структуры» и «ждёт подтверждения
    распознанного условия» требуют от человека разного, и общая надпись «ждёт
    вас» заставила бы его открывать работу, чтобы понять, чего от него хотят.
    """

    stage: str
    show: str
    note: str = ""


@dataclass
class Work:
    """Одна работа: план, ход семи стадий, замечания, готовые файлы, счётчик событий.

    Хранится не в памяти процесса, а в проекте (`kadai.status.save`): считает
    один процесс, показывает другой — так решено («всё через очередь»), и
    состояние в памяти было бы видно только тому, кто его посчитал.
    """

    id: str
    plan: Plan
    stages: list = field(default_factory=list)
    condition: dict = field(default_factory=dict)
    state: str = "running"
    current: str = ""
    hold: Hold | None = None
    problems: list = field(default_factory=list)
    outputs: dict = field(default_factory=dict)
    events: list = field(default_factory=list)
    started: str = ""

    @property
    def condition_text(self) -> str:
        """Текст условия так, как его прочитали. Показывается человеку до решения.

        Держится в работе, а не добывается заново на каждый показ: условие могло
        быть распознано OCR, и человек обязан увидеть **ровно тот** текст, по
        которому считали, а не результат второго распознавания.
        """
        return str(self.condition.get("text") or "")

    @property
    def seq(self) -> int:
        """Номер последнего события — курсор для сайта."""
        return self.events[-1]["n"] if self.events else 0

    def stage(self, name: str) -> StageState:
        for s in self.stages:
            if s.name == name:
                return s
        raise KadaiError(f'стадии "{name}" в работе нет{hint(name, STAGE_NAMES)}')


def new_work(plan: Plan, *, work_id: str | None = None) -> Work:
    """Новая работа: все семь стадий, ненужные сразу помечены пропущенными.

    Все семь, а не только нужные: человек видит одну и ту же лестницу у любой
    работы и по ней понимает, чего у этого вида нет вовсе. Список из одних
    нужных стадий отвечал бы на вопрос «сколько осталось», но не на вопрос
    «а где же код».
    """
    stages = [StageState(name=k.name,
                         state=WAITING if plan.needs(k.name) else SKIPPED,
                         unit=k.unit)
              for k in STAGES]
    work = Work(id=work_id or _new_id(), plan=plan, stages=stages, started=_now())
    _event(work, stage="", state="running", note="работа заведена")
    return work


def _new_id() -> str:
    """Идентификатор работы: время плюс случайный хвост.

    Время впереди — чтобы работы сортировались чтением; хвост случайный — чтобы
    две работы, заведённые в одну секунду, не оказались одной.
    """
    return f"w-{datetime.datetime.now(datetime.timezone.utc):%Y%m%dT%H%M%S}-{secrets.token_hex(2)}"


# ── переходы ─────────────────────────────────────────────────────────────────

def begin(work: Work, name: str, *, current: str = "") -> Work:
    """Стадия началась. Отказ, если работа стоит или предыдущие стадии не кончены.

    Проверка порядка не формальность: стадия «тексты», начатая раньше стадии
    «шаблон», написала бы значения по манифесту, которого ещё нет, — и заметить
    это можно было бы только по пустому отчёту.
    """
    st = work.stage(name)
    _must_run(work, f'начать стадию "{name}"')
    if st.state == SKIPPED:
        raise KadaiError(f'стадия "{name}" пропущена планом этого вида работы: '
                         f"начинать её нечем")
    if st.state == RUNNING:
        raise KadaiError(f'стадия "{name}" уже идёт')
    unfinished = [s.name for s in work.stages
                  if _order(s.name) < _order(name) and s.state not in (DONE, SKIPPED)]
    if unfinished:
        raise KadaiError(f'стадию "{name}" рано начинать: не кончены {", ".join(unfinished)}')
    st.state, st.started, st.finished, st.note = RUNNING, _now(), None, ""
    work.current = current or f"стадия «{name}»"
    _event(work, stage=name, state=RUNNING, note=work.current)
    return work


def step(work: Work, name: str, *, current: str = "", done: int | None = None,
         total: int | None = None, note: str = "") -> Work:
    """Ход внутри стадии: счётчик и строка «что делает сейчас».

    Счётчик ставится только со знаменателем: `done` без `total` — это доля от
    неизвестного, и рисовать её нельзя (записка Е.2).
    """
    st = work.stage(name)
    if st.state != RUNNING:
        raise KadaiError(f'стадия "{name}" не идёт ({st.state}): ход записывать некуда')
    if done is not None and total is None and st.total is None:
        raise KadaiError(f'стадия "{name}": счётчик без знаменателя. '
                         "Полоска с выдуманным знаменателем врёт — назовите действие в current")
    if total is not None:
        st.total = total
    if done is not None:
        st.done = done
    if note:
        st.note = note
    if current:
        work.current = current
    _event(work, stage=name, state=RUNNING, note=current or note)
    return work


def finish(work: Work, name: str, *, note: str = "", hold: Hold | None = None,
           outputs: dict | None = None) -> Work:
    """Стадия кончилась. Здесь — единственное место, где заводится остановка.

    Оба повода остановиться сходятся в один вызов: просьба человека из плана
    (`plan.pause_after`) и требование самой стадии (`hold`). Второго пути нет
    намеренно: два места, умеющих ставить работу на паузу, разошлись бы в том,
    что показывать, и одно из них рано или поздно забыло бы про `hold.show`.
    """
    st = work.stage(name)
    if st.state != RUNNING:
        raise KadaiError(f'стадия "{name}" не идёт ({st.state}): завершать нечего')
    st.state, st.finished = DONE, _now()
    if note:
        st.note = note
    if outputs:
        work.outputs.update(_names_only(outputs))
    _event(work, stage=name, state=DONE, note=note)
    stop = hold or (Hold(stage=name, show=SHOWN.get(name, name), note="ждём подтверждения")
                    if work.plan.stops_after(name) else None)
    if stop is not None:
        work.state, work.hold = "waiting_user", stop
        work.current = f"ждём человека: {stop.show}"
        _event(work, stage=name, state="waiting_user", note=stop.show)
        return work
    if _all_done(work):
        work.state, work.current, work.hold = "done", "", None
        _event(work, stage=name, state="done", note="работа готова")
    return work


def reopen(work: Work, *, note: str = "") -> Work:
    """Работа кончилась (или споткнулась), а человек прислал замечание — открываем.

    Отдельно от `resume`: `resume` продолжает то, что стояло на вопросе, а
    `reopen` возвращает в работу законченное. Разница видна человеку — «ждали
    вас» и «переделываем по замечанию» это разные строки, — и по ней же считается
    расход: переделка стоит денег, а ответ на вопрос нет.
    """
    if work.state == "running":
        raise KadaiError("работа и так идёт: открывать нечего")
    work.state, work.hold, work.current = "running", None, ""
    _event(work, stage="", state="running", note=note or "замечание человека")
    return work


def resume(work: Work, *, note: str = "") -> Work:
    """Человек ответил — идём дальше. Отказ, если работа и не стояла.

    Отказ, а не молчаливое «ничего не делаем»: `resume` на идущей работе почти
    всегда означает, что вызывающий потерял её состояние, и молчание здесь
    спрятало бы вторую беду.
    """
    if work.state != "waiting_user":
        raise KadaiError(f"работа не ждёт человека ({work.state}): продолжать нечего")
    work.state, work.hold, work.current = "running", None, ""
    _event(work, stage="", state="running", note=note or "человек подтвердил")
    return work


def stumble(work: Work, name: str, problem: dict) -> Work:
    """Стадия споткнулась. Работа — `failed`, замечание кладётся рядом.

    Замечание в общей форме `{module, level, code, key, message}`: четвёртого
    канала предупреждений в проекте не заводится.

    **`failed` в первой версии — конечное состояние.** Продолжить споткнувшуюся
    работу с того же места нечем: прогон уровня 3 не возобновляется (история
    петли не переживает вызов), и «продолжу как-нибудь» доплатило бы за ходы,
    результат которых уже потерян. Повтор — это новая работа или замечание
    через `rework`; сохранённые значения и артефакты при этом никуда не
    деваются, потому что кладутся в момент производства, а не в конце.
    """
    st = work.stage(name)
    st.state, st.finished = STUMBLED, _now()
    st.note = str(problem.get("message") or "")
    work.problems.append(problem)
    work.state, work.current = "failed", ""
    _event(work, stage=name, state=STUMBLED, note=st.note)
    return work


def cancel(work: Work, *, note: str = "") -> Work:
    """Работу отменил человек. Отличается от `failed`: денег назад это не вернёт,
    но объяснить готовый архив и расход потом нечем, если не различать."""
    if work.state in ("done", "cancelled"):
        raise KadaiError(f"работа уже {work.state}: отменять нечего")
    work.state, work.current, work.hold = "cancelled", "", None
    _event(work, stage="", state="cancelled", note=note)
    return work


def stage_now(work: Work) -> str:
    """Стадия, на которой прогон стоит. Идущая, а если такой нет — первая незаконченная."""
    for s in work.stages:
        if s.state == RUNNING:
            return s.name
    if work.hold is not None:
        return work.hold.stage
    for s in work.stages:
        if s.state in (WAITING, STUMBLED):
            return s.name
    return work.stages[-1].name if work.stages else ""


def events_since(work: Work, n: int = 0) -> list:
    """События после номера — то, чем сайт дозапрашивает изменения."""
    return [e for e in work.events if e["n"] > n]


# ── внутреннее ───────────────────────────────────────────────────────────────

def _order(name: str) -> int:
    try:
        return BY_NAME[name].n
    except KeyError:
        raise KadaiError(f'стадии "{name}" не бывает{hint(name, STAGE_NAMES)}') from None


def _must_run(work: Work, what: str) -> None:
    if work.state != "running":
        raise KadaiError(f"{what} нельзя: работа в состоянии {work.state}"
                         + (f" ({work.hold.show})" if work.hold else ""))


def _all_done(work: Work) -> bool:
    return all(s.state in (DONE, SKIPPED) for s in work.stages)


def _names_only(outputs: dict) -> dict:
    """Готовые файлы называются именем, а не путём.

    Путь знает только `Project`, и утечка его в статус — это путь на экране у
    человека и в логах сайта. Проверка дешёвая, а без неё правило держится
    только на внимательности того, кто зовёт `finish`.
    """
    bad = {k: v for k, v in outputs.items() if isinstance(v, str) and ("/" in v or "\\" in v)}
    if bad:
        raise KadaiError("в готовых файлах путь, а нужно имя: "
                         + ", ".join(f"{k}={v!r}" for k, v in bad.items()))
    return outputs


def _event(work: Work, *, stage: str, state: str, note: str = "") -> dict:
    entry = {"n": work.seq + 1, "at": _now(), "stage": stage, "state": state, "note": note}
    work.events.append(entry)
    return entry


def as_dict(work: Work) -> dict:
    """Работа в JSON-совместимом виде — то, что кладётся через шов «состояние стадий».

    План внутрь не кладётся объектом: профиль — данные на диске пакета, и
    хранить его копию в состоянии значило бы, что правка профиля не доедет до
    уже заведённых работ, а разошедшиеся копии никто не заметит. Кладётся имя.
    """
    return {"work": work.id, "profile": work.plan.profile.name, "started": work.started,
            "state": work.state, "stage": stage_now(work), "condition": dict(work.condition),
            "pause_after": sorted(work.plan.pause_after),
            "stages": [asdict(s) for s in work.stages],
            "current": work.current, "hold": asdict(work.hold) if work.hold else None,
            "problems": list(work.problems), "outputs": dict(work.outputs),
            "events": list(work.events)}


__all__ = ["STAGES", "STAGE_NAMES", "STAGE_STATES", "WORK_STATES", "BY_NAME", "SHOWN",
           "WAITING", "RUNNING", "DONE", "STUMBLED", "SKIPPED",
           "StageKind", "StageState", "Hold", "Work",
           "new_work", "begin", "step", "finish", "resume", "reopen", "stumble", "cancel",
           "stage_now", "events_since", "as_dict"]
