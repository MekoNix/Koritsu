"""
run — семь стадий, выполненных дверями: от условия до архива.

`stages` знает, что стадия началась и чем кончилась; здесь она делается. Разрез
между двумя файлами не косметический: машина стадий обязана быть проверяемой
без единой двери (её тесты не зовут никого), а исполнение — это сплошные чужие
вызовы, и держать их вперемешку значило бы, что «порядок стадий верен»
проверяется только вместе с «оркестратор ответил».

Порядок и цена, по записке Е.1 и решениям владельца 2026-09-04:

    1 приём          — без модели: материалы, условие, распознанный текст человеку
    2 разбор задания — один вопрос: как мы поняли задание
    3 шаблон         — один вопрос: строение работы; четыре сита; скелет блоками
    4 решение        — петля: код, таблицы, схемы; связный текст здесь не пишется
    5 тексты         — ОДИН проход по готовому списку блоков, видя соседей
    6 сборка         — без модели: проверка списка, статическая проверка кода, DOCX, PDF
    7 архив          — без модели: опись и ZIP

**Связный текст — одним проходом** (решение владельца 2026-09-04). Стадия 4
собирает скелет и то, чего текстом не написать; стадия 5 пишет весь текст
разом. Абзацы, написанные по одному в петле, связны поодиночке и
рассогласованы вместе, а увидит это тот, кто прочтёт работу целиком.

**Вид работы не фиксирован, и умолчания у него нет** (решение владельца
2026-09-04). До стадии 3 работа идёт по пустому строению, где есть только все
семь стадий; чем она окажется — решает сама стадия 3 по условию и пожеланиям
(`profile.compose`). Оттуда же берётся ответ на вопрос, нужна ли работе стадия
«решение» вовсе: там, где производить нечего, она обязана отсутствовать, а не
пройти вхолостую.

**Всё ценное сохраняется в момент производства.** Петля историю не переживает,
поэтому список блоков пишется версией на каждую правку (это делает
`orchestrator`), а ход работы — после каждой стадии (`status.save`). Обрыв
стоит одной стадии, а не прогона.

Чего здесь нет: своего хранилища, своих версий, своего вызова модели и своего
канала предупреждений. Всё это приходит дверями (`seams.Services`), а отказ
двери — `NotReady` с именем шва, а не пустой результат.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import archive as archive_mod, blocks as blocks_mod, profile as profile_mod, status
from .errors import KadaiError, NotReady, problem
from .plan import Plan, Wishes, plan_of
from .profile import check_structure, compose, sections_of
from .seams import Services, door, method
from .stages import (DONE, Hold, SKIPPED, STAGE_NAMES, WAITING, Work, begin, finish,
                     new_work, resume, step, stumble)

# Строение, с которым работа заводится: имени вида работы нет, стадии — все.
# Пустое, а не образец: образец был бы утверждением о том, чем работа окажется,
# а знает это одно условие (решение владельца 2026-09-04).
BLANK = profile_mod.Profile(name="", stages=tuple(STAGE_NAMES))

# Сколько ходов позволено петле решения (решение владельца 2026-09-04). Своё
# число, а не унаследованное от слоя: сценарий платит за прогон и обязан назвать
# потолок сам — умолчание среднего слоя тихо сменилось бы вместе с ним, а
# знаменатель полоски хода на стадии «решение» берётся отсюда же. Совпадать с
# `orchestrator.live.MAX_STEPS` оно не обязано: там потолок службы, здесь —
# сценария, и разойтись им позволено (служба свой применит как верхнюю границу).
MAX_STEPS = 50

# Умолчания, которые сценарий проставляет себе сам, если вызывающий не назвал
# своих. Словарём, а не веткой на каждое: второй потолок добавится строкой.
LIMITS = {"max_steps": MAX_STEPS}

# Схема ответа стадии «разбор задания». Записка Е.1: вид работы, тема, что надо
# сделать, что дано, чего не хватает. Ключи латиницей, значения по-русски: ключи
# читает служба, значения читает человек.
REQUIREMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "description": "что это за работа по условию"},
        "topic": {"type": "string", "description": "тема работы одной строкой"},
        "to_do": {"type": "array", "items": {"type": "string"},
                  "description": "что требуется сделать, по пунктам"},
        "given": {"type": "array", "items": {"type": "string"},
                  "description": "что дано условием: данные, ограничения, язык"},
        "missing": {"type": "array", "items": {"type": "string"},
                    "description": "чего в условии не хватает и что придётся выбрать самим"},
    },
    "required": ["topic", "to_do"],
    "additionalProperties": False,
}

REQUIREMENT_REQUEST = (
    "Прочитай условие задачи и пожелания человека и скажи, как ты понял задание: "
    "что это за работа, какая тема, что требуется сделать, что дано и чего в "
    "условии не хватает.\n"
    "Не решай задачу и не пиши текст работы — сейчас нужно только понимание. "
    "Чего в условии нет, то и перечисли в missing, а не додумывай молча: "
    "додуманное условие даёт безупречно решённую чужую задачу.")

SOLVE_TASK = (
    "Собери работу по этому строению: реши задачу и поставь на место всё, чего "
    "нельзя написать текстом.\n"
    "Замени черновики нетекстовых блоков настоящим содержимым: код — блоком "
    "code с языком, таблицы — блоком table, схемы — блоком diagram, построенным "
    "инструментом (make_flowchart, make_class_diagram, make_object_diagram).\n"
    "Связный текст сейчас НЕ пиши: его напишут одним проходом после тебя, и "
    "написанное тобой по одному абзацу было бы выброшено. Черновики текстовых "
    "блоков оставь как есть — можешь уточнить в них пометку, о чём писать.")

# Имя записи о задании в проекте — рядом с записью о ходе работы (`status.STATE_KEY`).
TASK_KEY = status.TASK_KEY


@dataclass
class Session:
    """Одна работа в работе: двери, план, ход стадий и то, что уже произведено.

    Живёт ровно один вызов CLI: считает работу один процесс, показывает другой
    (действующее решение «всё через очередь»), поэтому всё, что переживает
    вызов, лежит в проекте, а не здесь.
    """

    services: Services
    plan: Plan
    work: Work
    wishes: Wishes = field(default_factory=Wishes)
    limits: dict = field(default_factory=lambda: dict(LIMITS))
    task: str = ""      # задание петле, если стадию переигрывают по замечанию

    @property
    def project(self):
        if self.services.project is None:
            raise KadaiError("двери без проекта: Services.project пуст")
        return self.services.project

    def save(self) -> None:
        status.save(self.project, self.work)


# ── заведение и открытие работы ──────────────────────────────────────────────

def new(services: Services, *, wishes: Wishes | None = None, pause_after=(),
        limits: dict | None = None, work_id: str | None = None) -> Session:
    """Завести работу. Строения ещё нет, и выдумывать его нечем.

    Чем работа окажется, станет известно на стадии «шаблон», когда модель
    прочтёт условие; до тех пор она идёт по пустому строению (`BLANK`), и все
    семь стадий видны. Заводить работу после разбора условия нельзя: разбор —
    сам стадия, и показать его ход было бы негде.
    """
    wishes = wishes or Wishes()
    plan = plan_of(BLANK, wishes=wishes, pause_after=pause_after)
    work = new_work(plan, work_id=work_id)
    session = Session(services=services, plan=plan, work=work, wishes=wishes,
                      limits={**LIMITS, **dict(limits or {})})
    status.save_task(session.project, profile=profile_mod.as_dict(plan.profile),
                     wishes={"text": wishes.text, "show_task": wishes.show_task,
                             "show_structure": wishes.show_structure},
                     work=work.id)
    session.save()
    return session


def load(services: Services, *, limits: dict | None = None) -> Session:
    """Открыть заведённую работу из проекта: профиль, пожелания, ход стадий.

    Строение читается из записи о задании: оно сочинено под это условие, и
    подставить вместо него пустое значило бы объявить пропущенной стадию,
    которая шла, — или наоборот.
    """
    задание = status.task(services.project)
    if not задание:
        raise KadaiError("в проекте нет работы kadai: заведите её (new)")
    wishes = _wishes_of(задание)
    profile = (profile_mod.parse(задание["profile"], source="запись о задании")
               if задание.get("profile") else BLANK)
    raw = method(services.project, "state", "состояние стадий")(status.STATE_KEY)
    plan = plan_of(profile, wishes=wishes, pause_after=raw.get("pause_after") or ())
    work = status.load(services.project, plan)
    return Session(services=services, plan=plan, work=work, wishes=wishes,
                   limits={**LIMITS, **dict(limits or {})})


def _wishes_of(задание: dict) -> Wishes:
    raw = dict(задание.get("wishes") or {})
    return Wishes(text=str(raw.get("text") or ""),
                  show_task=bool(raw.get("show_task")),
                  show_structure=bool(raw.get("show_structure")))


# ── прогон ───────────────────────────────────────────────────────────────────

def run(session: Session, *, until: str | None = None) -> Session:
    """Пройти стадии подряд, пока работа идёт. `until` — последняя, которую делаем.

    Останавливается сама на трёх вещах: работа встала с вопросом
    (`waiting_user`), стадия споткнулась, стадии кончились. Ни одной ветки
    «а если режим такой» здесь нет: где остановиться, решает множество
    `plan.pause_after`, и второго механизма остановки в пакете не заведено.

    Повторный `run` по стоящей работе и есть ответ человека: он посмотрел, что
    ему показали, и велел продолжать. Отдельной команды «подтвердить» не
    заводится — она означала бы, что продолжить можно, не посмотрев, и разница
    между «согласен» и «просто нажал ещё раз» всё равно была бы выдуманной.
    """
    if until is not None and until not in STAGE_NAMES:
        raise KadaiError(f'стадии "{until}" не бывает: '
                         f"есть {', '.join(STAGE_NAMES)}")
    if session.work.state == "waiting_user":
        resume(session.work, note="человек ответил и велел продолжать")
        session.save()
    for name in STAGE_NAMES:
        if session.work.state != "running":
            break
        if session.work.stage(name).state not in (DONE, SKIPPED):
            STAGE_FUNS[name](session)
            session.save()
        # Проверка `until` стоит **после** пропуска намеренно: «дойди до
        # решения» у работы, которой решение не нужно, иначе прошло бы мимо
        # границы и оплатило бы всё остальное.
        if until is not None and name == until:
            break
    return session


def snapshot(session: Session, *, since: int = 0) -> dict:
    """Снимок для API и CLI: ход стадий плюс расход проекта.

    Расход считает проект (`Project.spent`/`limit`), а не мы: свой счётчик не
    увидел бы того, что записал чужой журнал, и разошёлся бы с ним молча.
    """
    try:
        spent = status.spent_of(session.project)
    except Exception:                       # noqa: BLE001 — расход не обязан быть
        # Проект без журнала расхода — законное состояние (ни одного вызова ещё
        # не было). Ронять показ статуса из-за этого нельзя: статус смотрят
        # именно тогда, когда что-то пошло не так.
        spent = status.empty_spent()
    return status.snapshot(session.work, spent=spent, since=since)


# ── стадия 1: приём ──────────────────────────────────────────────────────────

def stage_receive(session: Session) -> None:
    """Материалы разобраны, условие прочитано, распознанное показано человеку.

    Модель не зовётся ни разу. Единственное решение стадии — остановиться, если
    условие читано OCR: ошибка распознавания в формуле даёт безупречно решённую
    **чужую** задачу, и заметить её может только человек (решение владельца
    2026-08-31). Остановка эта не из пожеланий, а из самой стадии, и приходит
    тем же `hold`, что и просьба человека, — второго механизма паузы нет.
    """
    work = session.work
    begin(work, "приём", current="разбираю материалы")
    store = method(session.project, "store", "разбор условия")()
    материалы = list(store.list())
    step(work, "приём", done=len(материалы), total=len(материалы),
         current="читаю условие", note=f"материалов: {len(материалы)}")

    condition = method(session.project, "condition", "разбор условия")()
    if not condition:
        _stumble(session, "приём", problem(
            "нет_условия", "условие задачи не приложено: решать нечего. "
            "Положите файл условия (add_material(condition=True))"))
    material = store.get(condition)
    текст = store.read(condition).text
    читано_ocr = _ocr(material)
    work.condition = {"material": str(condition), "name": str(material.name),
                      "unit": str(getattr(material, "unit", "")),
                      "ocr": читано_ocr, "text": текст}
    if not текст.strip():
        _stumble(session, "приём", problem(
            "условие_пустое", f"из файла {material.name!r} не вынуто ни строки текста: "
            "решать по пустому условию нельзя", key=str(condition)))
    hold = (Hold(stage="приём", show="распознанное условие",
                 note="проверьте, верно ли распознан текст: ошибка в одной формуле "
                      "даёт безупречно решённую чужую задачу")
            if читано_ocr else None)
    finish(work, "приём",
           note=f"{len(материалы)} материалов; условие: {material.name}"
                + (" (читано OCR)" if читано_ocr else ""), hold=hold)


def _ocr(material) -> bool:
    """Читано ли условие распознаванием. Признак грубый, и это сказано в шве.

    Сегодня OCR отделим только целым материалом: у картинки текста нет вовсе,
    значит весь он распознан; у PDF пометка стоит на весь материал, а не на
    страницу. Ошибиться этот признак может только в сторону лишнего показа
    человеку — и это правильная сторона.
    """
    if str(getattr(material, "kind", "")) == "image":  # код вида из materials (английские коды с 2.0.0a5)
        return True
    заметки = " ".join(str(n) for n in (getattr(material, "notes", ()) or ()))
    return "скан" in заметки.lower() or "распозна" in заметки.lower()


# ── стадия 2: разбор задания ─────────────────────────────────────────────────

def stage_task(session: Session) -> None:
    """Один вопрос модели: как мы поняли задание. Ответ кладётся и показывается.

    Стадия отдельная не ради красоты полоски: исправить понимание условия до
    сочинения строения стоит один вызов, после стадии «тексты» — весь прогон
    (записка В.3 п.7). Показать её человеку можно и нужно, но останавливаться по
    умолчанию нельзя — решает тот, кто платит (решение владельца 2026-08-31).
    """
    work = session.work
    begin(work, "разбор задания", current="разбираю условие")
    answer = _ask(session, "разбор задания", REQUIREMENT_REQUEST,
                  schema=REQUIREMENT_SCHEMA, data=_data(session))
    требование = dict(answer.value or {})
    status.save_task(session.project, requirement=требование)
    finish(work, "разбор задания",
           note=_requirement_note(требование))


def _requirement_note(требование: dict) -> str:
    тема = str(требование.get("topic") or "").strip()
    чего_нет = list(требование.get("missing") or ())
    хвост = f"; в условии не хватает: {len(чего_нет)}" if чего_нет else ""
    return (тема or "задание разобрано") + хвост


# ── стадия 3: шаблон (строение и скелет) ─────────────────────────────────────

def stage_structure(session: Session) -> None:
    """Строение работы сочиняется, просеивается ситами и становится скелетом.

    Четыре сита записки В.4 — все дешёвые и без модели, порядок обратный по цене
    ошибки:

    1. строение против самого себя: тип раздела из перечня движка, объявленное
       обязательным на месте, разделов не больше потолка (`profile.check_structure`);
    2. уникальность ключей после NFC — внутри того же сита: два ключа,
       различающиеся только нормализацией, стали бы одним блоком, и второй
       раздел исчез бы молча;
    3. список блоков проверяется тем же валидатором, что стоит перед сборкой
       документа (`hokoku.live.validate_work`): пустых значений, битых ключей и
       повисших `{ref:}` в скелете быть не должно;
    4. в шаблонном пути четвёртым ситом был `validate` на пустых значениях —
       в живом режиме манифеста нет вовсе, и его работу делает то же
       `validate_work`: место под текст здесь черновик, а не пустота, и
       «соберётся ли» проверяется на настоящем списке.

    Чем окажется работа, решается здесь же и только здесь: `compose` строит её
    строение из ответа модели целиком, и от него зависит, нужна ли работе стадия
    «решение». Ни файла-образца, ни умолчания у этого решения нет.
    """
    work = session.work
    begin(work, "шаблон", current="сочиняю строение работы")
    answer = _ask(session, "шаблон",
                  profile_mod.structure_request(wishes=session.wishes.text),
                  schema=profile_mod.structure_schema(), data=_data(session))
    строение = dict(answer.value or {})

    try:
        profile = compose(строение, stages=STAGE_NAMES)
    except KadaiError as exc:
        _stumble(session, "шаблон", problem("строение_не_годится", str(exc)))
    беды = check_structure(profile, строение)
    work.problems.extend(p for p in беды if p["level"] != "error")
    жёсткие = [p for p in беды if p["level"] == "error"]
    if жёсткие:
        _stumble(session, "шаблон", жёсткие[0], rest=жёсткие[1:])
    sections = sections_of(profile, строение)

    step(work, "шаблон", current=f"собираю скелет: разделов {len(sections)}")
    # Строение уже сочинено и просеяно ситами — дверь его только раскладывает
    # блоками. `task` и `default` ей не передаются намеренно: они нужны, только
    # когда строение сочиняет она сама, а второй вызов модели за то же самое —
    # это оплаченный дважды ответ, из которых сита увидели бы только первый.
    записи = door(session.services, "make_template", "шаблон")(
        sections, data=_data(session))
    список = blocks_mod.work_of(записи, resolve_artifact=_resolver(session))
    беды = blocks_mod.validate(список)
    жёсткие = blocks_mod.errors_of(беды)
    if жёсткие:
        _stumble(session, "шаблон", жёсткие[0], rest=жёсткие[1:])
    work.problems.extend(p for p in беды if p["level"] != "error")

    _adopt(session, profile)
    status.save_task(session.project, profile=profile_mod.as_dict(profile),
                     structure=строение)
    finish(work, "шаблон",
           note=f'вид работы: {profile.name}; разделов {len(sections)}, '
                f"блоков {len(записи)}")


def _adopt(session: Session, profile) -> None:
    """Принять сочинённое строение: план на него, лишние стадии — пропущенными.

    Пропущенными, а не «пройденными мгновенно»: работа, которой не нужна стадия
    «решение», не должна показывать её сделанной — полоска хода, показавшая
    работу, которой не было, врёт ровно так же, как пустой раздел в отчёте.
    Уже сделанные стадии не трогаются: их сделали, и переписывать историю
    нельзя.
    """
    session.plan = plan_of(profile, wishes=session.wishes,
                           pause_after=session.plan.pause_after)
    session.work.plan = session.plan
    for st in session.work.stages:
        if st.state == WAITING and not session.plan.needs(st.name):
            st.state, st.note = SKIPPED, f'работе «{profile.name}» не нужна'
        elif st.state == SKIPPED and session.plan.needs(st.name):
            st.state, st.note = WAITING, ""


# ── стадия 4: решение ────────────────────────────────────────────────────────

def stage_solve(session: Session) -> None:
    """Петля живого режима: код, таблицы, схемы. Связный текст здесь не пишется.

    Прогон, не дошедший до конца, стадию не роняет: всё, что петля успела
    вставить, уже записано версией списка (это делает `orchestrator` в момент
    производства), и выбрасывать сделанное из-за упёршегося в потолок ходов
    прогона значило бы платить дважды. Беды прогона едут в замечания работы —
    человек увидит их в статусе и в архиве.

    Потолок ходов сценарий называет свой (`MAX_STEPS`, 50) и передаёт его дверью:
    он же знаменатель полоски хода, и без него счётчик остался бы без числа, а
    прогон шёл бы по умолчанию того слоя, который завтра его сменит. Снять
    потолок вызывающий по-прежнему может (`limits={"max_steps": None}`) — тогда
    решает служба, и полоска честно называет действие, а не долю.
    """
    work = session.work
    begin(work, "решение",
          current="переделываю по замечанию" if session.task else "решаю задачу инструментами")
    solve = door(session.services, "solve", "решение")
    kwargs = {"data": _data(session)}
    if session.limits.get("max_steps"):
        kwargs["max_steps"] = int(session.limits["max_steps"])
    result = solve(session.task or SOLVE_TASK, **kwargs)
    сделано = len(getattr(result, "changed", ()) or ())
    if session.limits.get("max_steps"):
        step(work, "решение", done=int(getattr(result, "steps", 0) or 0),
             total=int(session.limits["max_steps"]),
             current=f"правок в работе: {сделано}")
    work.problems.extend(blocks_mod.problem_dict(p)
                         for p in getattr(result, "problems", ()) or ())
    if not getattr(result, "ok", False):
        work.problems.append(problem(
            "петля_не_дошла", "прогон решения не дошёл до конца: "
            f"{getattr(result, 'outcome', '') or 'без итога'}. Сделанное сохранено, "
            "остальное придётся доделать замечанием", level="warning"))
    finish(work, "решение",
           note=f"правок в работе: {сделано}, ходов: {getattr(result, 'steps', 0)}")


# ── стадия 5: тексты ─────────────────────────────────────────────────────────

def stage_texts(session: Session) -> None:
    """Весь связный текст — одним проходом по готовому списку блоков.

    Решение владельца 2026-09-04, и оно же ответ на развилку из `status.md`.
    Здесь это ровно один вызов двери: что просить и по какой схеме, решает
    движок отчётов (`text_slots` → `texts_schema`), а блоки, написанные
    человеком, выбрасывает из просимого сама дверь по пометке `source`.
    Знать это правило дважды нельзя — разойдясь, второе знание затёрло бы
    написанное человеком.

    Знаменатель счётчика — места под текст, которые вправе писать модель:
    считать вместе с ручными значило бы навсегда показывать «9 из 12».
    """
    work = session.work
    begin(work, "тексты", current="пишу связный текст одним проходом")
    записи = method(session.project, "blocks", "список блоков")()
    мест = _slots_for_model(session, записи)
    if not мест:
        # Законное состояние, а не беда: человек мог написать всё сам, и звать
        # дверь ради отказа «писать нечего» значило бы уронить работу на том,
        # что она уже готова.
        finish(work, "тексты", note="писать нечего: текстовых мест не осталось")
        return
    step(work, "тексты", done=0, total=len(мест),
         current=f"пишу связный текст одним проходом: блоков {len(мест)}")
    result = door(session.services, "write_texts", "текст")(overwrite=False)
    написано = list(getattr(result, "filled", ()) or ())
    work.problems.extend(blocks_mod.problem_dict(p)
                         for p in getattr(result, "problems", ()) or ())
    step(work, "тексты", done=len(написано), total=max(len(мест), len(написано)))
    if not написано:
        _stumble(session, "тексты", problem(
            "текст_не_написан", "проход текста не вернул ни одного блока: "
            "работа осталась черновиками"))
    finish(work, "тексты", note=f"написано блоков: {len(написано)} из {len(мест)}")


def _slots_for_model(session: Session, записи) -> list:
    """Места под текст, которые вправе писать модель: без ручных и файловых."""
    свои = {r["key"] for r in записи if r.get("source") in ("manual", "file")}
    список = blocks_mod.work_of(записи, resolve_artifact=_resolver(session))
    return [s for s in blocks_mod.slots(список) if s["key"] not in свои]


# ── стадия 6: сборка ─────────────────────────────────────────────────────────

def stage_build(session: Session) -> None:
    """Проверка списка, статическая проверка кода, DOCX и PDF. Модель не зовётся.

    **Код проверяется статически и никогда не исполняется** (решения 2026-08-27
    и 2026-08-31): tree-sitter разбирает исходник, не запуская его, и ловит
    обрывки и синтаксический мусор — но не отвечает на вопрос, верно ли работает
    решение. Ответ на этот вопрос в первой версии не даёт никто, и в архиве это
    написано дословно.

    Дверь `check_code` есть с 2026-09-04 (`orchestrator.doors`), и зовётся она на
    каждый блок с кодом. Подменять её «ну и ладно» нельзя было и тогда, когда её
    не было: код без проверки, объявленный проверенным, — это то самое молчание,
    которое человек прочтёт как обещание. Поэтому при коде в работе и без двери
    стадия по-прежнему честно отказывает `NotReady` с адресом того, кого ждём.
    """
    work = session.work
    begin(work, "сборка", current="проверяю работу")
    записи = method(session.project, "blocks", "список блоков")()
    if not записи:
        _stumble(session, "сборка", problem(
            "работы_нет", "в проекте нет ни одного блока: собирать нечего"))
    список = blocks_mod.work_of(записи, resolve_artifact=_resolver(session))

    беды = blocks_mod.validate(список)
    беды += _check_code(session, записи)
    work.problems.extend(p for p in беды if p["level"] != "error")
    жёсткие = blocks_mod.errors_of(беды)
    if жёсткие:
        _stumble(session, "сборка", жёсткие[0], rest=жёсткие[1:])

    step(work, "сборка", current="собираю документ")
    try:
        docx = blocks_mod.assemble(список)
    except KadaiError as exc:
        _stumble(session, "сборка", problem("документ_не_собрался", str(exc)))
    art = method(session.project, "put_artifact", "артефакты")(
        docx, name=archive_mod.REPORT_DOCX)
    method(session.project, "note_derived", "журнал производных")(
        art, tool="hokoku.live.assemble", inputs=[b.key for b in список.blocks])
    сделано = {"docx": art}
    outputs = {"docx": archive_mod.REPORT_DOCX}

    pdf = _to_pdf(session, docx)
    if pdf is not None:
        сделано["pdf"] = method(session.project, "put_artifact", "артефакты")(
            pdf, name=archive_mod.REPORT_PDF)
        outputs["pdf"] = archive_mod.REPORT_PDF
    else:
        work.problems.append(problem(
            "без_pdf", "PDF не собран: LibreOffice не отозвался. В архиве будет "
            "только DOCX", level="info"))
    status.save_task(session.project, made=сделано)
    finish(work, "сборка", note=f"документ собран: {len(docx)} байт"
                                + ("" if pdf is None else f", PDF {len(pdf)} байт"),
           outputs=outputs)


def _check_code(session: Session, записи) -> list:
    """Статическая проверка каждого блока с кодом. Пусто — кода в работе нет."""
    код = [r for r in записи if str(r.get("kind")) == "code"]
    if not код:
        return []
    check = door(session.services, "check_code", "проверка кода")
    out: list = []
    for record in код:
        значение = record.get("value") or {}
        замечания = check(str(значение.get("text") or ""),
                          str(значение.get("lang") or ""))
        for p in замечания or ():
            беда = blocks_mod.problem_dict(p)
            беда.setdefault("key", record.get("key"))
            беда["key"] = беда.get("key") or record.get("key")
            out.append(беда)
    return out


def _to_pdf(session: Session, docx: bytes):
    """PDF: дверью, если её дали, иначе `hokoku` напрямую. Нет — так нет.

    Единственный шов, отказ которого не роняет стадию: записка Ж говорит про
    PDF «если просили и LibreOffice есть», и остальной архив без него собирается
    целиком. Врать о наличии PDF при этом нельзя — в замечаниях работы остаётся
    запись, почему его нет.
    """
    fn = getattr(session.services, "to_pdf", None) or session.services.extra.get("to_pdf")
    fn = fn or blocks_mod.to_pdf
    try:
        return fn(docx)
    except Exception:                       # noqa: BLE001 — чужой подпроцесс
        return None


# ── стадия 7: архив ──────────────────────────────────────────────────────────

def stage_archive(session: Session) -> None:
    """Опись и ZIP. Называет содержимое `kadai`, складывает `orchestrator`.

    В архиве по записке Ж: отчёт (DOCX и, если вышло, PDF), шаблон работы,
    исходники, схемы, `решение.md` и обязательный `как-это-собрано.txt` со
    строкой о том, что код не запускался. Строка обязательна и проверяется
    описью: компилируемый исходник без неё читается как проверенный.
    """
    work = session.work
    begin(work, "архив", current="собираю архив")
    записи = method(session.project, "blocks", "список блоков")()
    список = blocks_mod.work_of(записи, resolve_artifact=_resolver(session))
    задание = status.task(session.project)
    сделано = dict(задание.get("made") or {})

    шаблон = method(session.project, "put_artifact", "артефакты")(
        blocks_mod.template_bytes(список), name=archive_mod.TEMPLATE)
    исходники = [(archive_mod.source_name(r.get("key"),
                                          (r.get("value") or {}).get("lang")),
                  blocks_mod.text_of(r))
                 for r in записи if str(r.get("kind")) == "code"]
    # Схема лежит в значении блока либо идентификатором артефакта, либо XML'ем —
    # и обратно в запись движок отчётов пишет всегда XML. Один путь из двух
    # оставить нельзя: он молча даёт пустую папку `схемы/` в архиве, и узнаёт об
    # этом человек, распаковав его.
    схемы = [(r["key"], (r.get("value") or {}).get("artifact"))
             for r in записи if str(r.get("kind")) == "diagram"
             and (r.get("value") or {}).get("artifact")]
    схемы_текстом = [(r["key"], (r.get("value") or {}).get("xml"))
                     for r in записи if str(r.get("kind")) == "diagram"
                     and (r.get("value") or {}).get("xml")]

    notice = archive_mod.notice_text(
        work_id=work.id, profile=session.plan.profile.name,
        wishes=session.wishes.text,
        requirement=_requirement_text(задание.get("requirement") or {}),
        stages=[{"name": s.name, "state": s.state, "note": s.note} for s in work.stages],
        spent=_spent(session), versions=_versions(session), problems=work.problems)
    entries = archive_mod.plan_archive(
        notice=notice, report_artifact=сделано.get("docx"), pdf_artifact=сделано.get("pdf"),
        template_artifact=шаблон, source_texts=исходники, diagrams=схемы,
        diagram_texts=схемы_текстом,
        solution=archive_mod.solution_md(_solution(список)))
    имя = archive_mod.pack(session.project, entries)
    finish(work, "архив", note=f"в архиве файлов: {len(entries)}",
           outputs={"zip": имя})


def _solution(список) -> list:
    """`решение.md`: заголовки и текст под ними — производная от блоков работы.

    Производная, а не отдельный авторский путь: иначе появляется второй источник
    правды, человек правит `решение.md`, отчёт остаётся прежним, и объяснить
    расхождение нечем.
    """
    out, заголовок = [], ""
    for b in список.blocks:
        if b.kind == "heading":
            заголовок = b.text.lstrip("# ").strip()
            continue
        текст = b.text.strip()
        if текст and not текст.lower().startswith(blocks_mod.DRAFT_MARK):
            out.append((заголовок or b.label or b.key, текст))
    return out


def _requirement_text(требование: dict) -> str:
    """Разбор задания словами — для человека, читающего архив через полгода."""
    if not требование:
        return ""
    lines = [f"Тема: {требование.get('topic') or '—'}"]
    for поле, заголовок in (("to_do", "Что требуется"), ("given", "Что дано"),
                            ("missing", "Чего в условии нет")):
        пункты = list(требование.get(поле) or ())
        if пункты:
            lines.append(заголовок + ": " + "; ".join(str(p) for p in пункты))
    return "\n".join(lines)


def _versions(session: Session) -> dict:
    """Номер версии списка блоков на момент сборки: по нему архив узнаётся потом."""
    try:
        versions = method(session.project, "block_versions", "список блоков")()
    except NotReady:
        return {}
    return {"список блоков": versions[-1].n} if versions else {}


def _spent(session: Session) -> dict:
    try:
        return status.spent_of(session.project)
    except Exception:                       # noqa: BLE001
        return status.empty_spent()


# ── общее ────────────────────────────────────────────────────────────────────

STAGE_FUNS = {
    "приём": stage_receive,
    "разбор задания": stage_task,
    "шаблон": stage_structure,
    "решение": stage_solve,
    "тексты": stage_texts,
    "сборка": stage_build,
    "архив": stage_archive,
}
assert set(STAGE_FUNS) == set(STAGE_NAMES)      # стадия без исполнения молча не идёт


def _data(session: Session) -> list:
    """Чужой текст для промпта: условие, пожелания, разбор задания.

    Всё это едет кусками роли `files` в рамке со случайной меткой прогона —
    то есть **данными**, а не указаниями. Разница не косметическая: в чужом
    файле бывает написано «забудь предыдущие указания», и текст, приехавший
    вопросом, был бы для модели указанием.
    """
    out = [("условие задачи", session.work.condition_text),
           ("пожелания человека", session.wishes.text)]
    требование = (status.task(session.project) or {}).get("requirement")
    if требование:
        out.append(("как мы поняли задание", _requirement_text(требование)))
    return [(имя, текст) for имя, текст in out if str(текст).strip()]


def _ask(session: Session, stage: str, question: str, *, schema=None, data=()):
    """Вопрос модели с проверкой ответа. Молчание — беда стадии, а не пустой ответ."""
    answer = door(session.services, "ask", "структура")(question, schema=schema, data=data)
    if not getattr(answer, "ok", False) or not isinstance(getattr(answer, "value", None), dict):
        беды = [blocks_mod.problem_dict(p) for p in getattr(answer, "problems", ()) or ()]
        _stumble(session, stage, беды[0] if беды else problem(
            "модель_не_ответила", "модель не ответила по схеме, а без ответа стадию "
            "не пройти"), rest=беды[1:])
    return answer


def _stumble(session: Session, stage: str, беда: dict, *, rest=()) -> None:
    """Стадия споткнулась: запись в работу, ход на диск, ошибка наружу.

    Именно в таком порядке. Сохранить состояние обязательно до того, как ошибка
    улетит: статус смотрят как раз тогда, когда что-то пошло не так, и работа,
    оставшаяся в памяти умершего процесса, показала бы «идёт» навсегда.
    """
    stumble(session.work, stage, беда)
    session.work.problems.extend(rest)
    session.save()
    raise KadaiError(f'стадия "{stage}" споткнулась: {беда.get("message")}')


def _resolver(session: Session):
    """`Project.resolve_artifact` — им значение блока достаёт байты схемы и картинки."""
    return method(session.project, "resolve_artifact", "артефакты")


__all__ = ["Session", "BLANK", "REQUIREMENT_SCHEMA", "REQUIREMENT_REQUEST", "SOLVE_TASK",
           "STAGE_FUNS", "new", "load", "run", "snapshot",
           "stage_receive", "stage_task", "stage_structure", "stage_solve",
           "stage_texts", "stage_build", "stage_archive"]
