"""
agent — уровень 3: прогон с инструментами на петле `llm.run_tools`.

Тем же устройством, что уровни 1 и 2, а не рядом с ним. Совпадает всё, кроме
способа получить значение: тот же отбор тегов (`schema.fillable`), та же
раскладка промпта в пять ролей (`prompt.build_parts`), та же метка рамки на
прогон (`fill._seal`), тот же валидатор и та же единственная точка записи
(`fill._accept` → `Project.set_value`), тот же журнал и тот же лимит
пользователя. Отличие ровно одно: значения приходят вызовами `set_tag` по ходу
работы, а не разбором одного ответа.

Зачем уровень 3 вообще нужен, когда есть уровень 2. Он производит то, чего
нельзя написать текстом: схемы по исходникам студента, таблицы из его данных,
значения, для которых сначала надо прочитать материал. Связный текст отчёта
по-прежнему пишет уровень 2 — теги связаны, и петля, пишущая абзацы по одному,
даст рассогласованный отчёт, да ещё и самым дорогим способом (история растёт с
каждым ходом). Порядок применения: сначала уровень 3 — схемы и код, потом
уровень 2 — текст, уже видящий их соседями.

Чего у петли нет и что из этого следует (`llm/loop.py`): истории она не
сохраняет, обратного отсчёта модель не видит, наружу в реальном времени идут
только вызовы инструментов. Значит **всё ценное сохраняется в момент
производства**: артефакт кладётся сразу, значение ставится сразу, ход пишется в
`runs/<id>.json` сразу. Тогда обрыв или потолок ходов стоит одного хода, а не
прогона.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import llm

from . import fill as fill_mod, prompt as prompt_mod, schema as schema_mod, tools as tools_mod
from .errors import OrchestratorError

# Имя куска с задачей человека. Наша строка перед рамкой — единственное
# утверждение о чужом тексте, которое сам текст подделать не может, и потому
# оно должно быть постоянным: имя, написанное по месту, однажды напишется
# иначе, и модель увидит два разных куска там, где кусок один.
ИМЯ_ЗАДАЧИ = "задача от человека"


@dataclass
class AgentResult:
    """Итог прогона уровня 3. `ok` — прогон дошёл до конца, а не «всё заполнено».

    Разделение то же, что у `RunResult` уровня 2, и по той же причине: прогон,
    в котором модель поставила два тега из трёх и закончила, кончился штатно, а
    прогон, упёршийся в потолок ходов, — нет, хотя в обоих часть тегов пуста.

    `problems` — записи общей формы (`kyotsu.Notice`), и разбирать их надо по
    общим полям. Про тег там `hokoku.Problem` (есть `key`), про схему —
    замечание `fragmos` (есть `file`, ключа нет: он о схеме, а не о теге).
    Требовать `key` от каждой записи значит требовать, чтобы всякая беда была
    про тег, — а прогон, оборвавшийся связью, не про тег.
    """

    run: object
    filled: list = field(default_factory=list)
    problems: list = field(default_factory=list)
    usage: dict = field(default_factory=dict)
    steps: int = 0
    calls: int = 0
    text: str = ""
    stop: str = ""
    outcome: str = ""
    ok: bool = False


def fill_agent(project, *, endpoint: str, keys=None, chunks=(), max_steps=None,
               max_units=None, max_tokens=None, effort=None, cancel=None,
               overwrite: bool = False, task: str = "") -> AgentResult:
    """Прогон агента: модель работает инструментами и ставит значения сама.

    Порядок действий не переставляется: отбор тегов → ворота операторского
    канала → прогон → раскладка → метка → петля. Ворота стоят **до** первого
    вызова, потому что отказ после пятого хода стоил бы денег за пять ходов и
    ничего бы не изменил; отбор — до ворот, потому что «ставить нечего» дешевле
    узнать без обращения к слою вовсе.

    `overwrite` — то же слово, что у уровней 1 и 2, и значит то же: без него
    тег, чью текущую версию написал человек, в разрешённые не попадает, и
    `set_tag` на нём отказывает. У самой модели такого аргумента нет и быть не
    может — переписать чужое решает человек.

    Что происходит на потолке ходов: петля останавливается штатно
    (`Stop.MAX_TOKENS`, пометка `step_limit`), исход прогона — `interrupted`,
    поставленные значения остаются поставленными. Ронять здесь нечего: они уже
    на диске, а история петли всё равно не сохраняется, и повторный прогон
    начнётся с чистого листа — но с уже готовыми значениями в проекте.

    `task` — что человек просит сделать, его словами: задача для агента берётся
    из запроса. Едет **недоверенным куском в рамке**, той же дверью, что
    условие задачи и пожелания (`prompt.data_parts`), а не строкой запроса
    рядом с нашими указаниями: писал его человек, и указанием для модели он
    быть не может. Пустой — куска нет вовсе: «задача» без задачи стоила бы
    токенов и сказала бы модели, что задача была и она пуста.

    Потолок длины ставит тот, кто принимает текст снаружи (служба — 15 000
    знаков, `api/runs/handlers/agent.py`): здесь чужого потолка нет, потому что
    сюда зовут и из лаборатории, где текст пишет тот же, кто запускает.
    """
    manifest = project.manifest()
    wanted = schema_mod.fillable(manifest, keys=keys)
    kept: list = []
    if not overwrite:
        held = [(key, fill_mod._held_by(project, key)) for key in wanted]
        wanted = [key for key, who in held if who is None]
        kept = [fill_mod._problem(
            "kept", key,
            f"значение тега {key!r} поставлено не моделью ({who!r}): "
            "прогон его не трогает", "info")
            for key, who in held if who is not None]
        if not wanted and kept:
            raise OrchestratorError(
                "все запрошенные теги написаны не моделью: "
                + ", ".join(repr(p.key) for p in kept)
                + ". Переписать — overwrite=True")
    if not wanted:
        raise OrchestratorError("нечего просить у модели: ни одного заполняемого тега")

    extra_flags, gate_problems = tools_mod.operator_channel_gate(endpoint)

    run = project.start_run(level=3, endpoint=endpoint)
    parts = prompt_mod.build_parts(project, keys=wanted, level=3, manifest=manifest,
                                   chunks=chunks)
    # Задача человека — до печати рамки: метка выпускается по всему
    # недоверенному тексту сразу (`prompt.seal_mark`), и кусок, добавленный
    # после `_seal`, уехал бы к модели вне рамки.
    parts.extend(prompt_mod.data_parts([(ИМЯ_ЗАДАЧИ, task)]))
    fill_mod._seal(project, run, parts)

    box = tools_mod.ToolBox(project, run, manifest=manifest, parts=parts,
                            template=project.template(), allowed=wanted,
                            extra_flags=extra_flags)
    limits = llm.Limits(
        max_steps=int(max_steps or tools_mod.MAX_STEPS), max_units=max_units,
        **({} if max_tokens is None else {"max_tokens_per_call": max_tokens}))
    # `limits` и `limit` — разные вещи, и обе нужны: первое наши потолки одного
    # прогона (ходы и цена прогона), второе — денежный лимит пользователя,
    # проверяемый слоем перед каждым ходом. Метка передаётся явно: не передай —
    # слой выпустит свою на каждый ход, и в `runs/<id>.json` осталась бы метка,
    # которой модель не видела.
    result = llm.run_tools(endpoint, tools_mod.tools(), parts, box, limits=limits,
                           cancel=cancel, journal=project.journal(),
                           meta={"run": run.id, "level": 3}, effort=effort,
                           limit=project.limit(), frame_mark=run.mark)

    out = AgentResult(run=run, filled=list(box.filled),
                      problems=[*kept, *gate_problems, *box.problems],
                      usage=llm.usage_of(result), steps=result.attempts,
                      calls=box.calls, text=result.text or "", stop=result.stop)
    if result.error is not None:
        out.problems.append(fill_mod._problem("run_failed", None, str(result.error)))
    for code, message in _degraded_words(limits.max_steps).items():
        if code in result.degraded:
            out.problems.append(fill_mod._problem(code, None, message, "info"))
    out.outcome = _outcome(result, out.filled)
    out.ok = out.outcome == "done"
    project.finish_run(run, out.outcome)
    return out


def _degraded_words(max_steps: int) -> dict:
    """Пометки петли словами для человека. Потолок называется тот, что стоял.

    Не все пометки: `no_effort` и `no_operator_channel` — свойства endpoint'а, а
    не события прогона, и второе к тому же уже сказано воротами
    (`tools.operator_channel_gate`); повторять его вторым текстом значило бы
    завести два ответа на один вопрос.

    Число берётся из потолка прогона, а не из умолчания модуля: прогон с
    `max_steps=2`, объяснённый словами «упёрся в потолок 12», отвечает на
    вопрос «почему остановились» неправдой, выглядящей как правда.
    """
    return {
        "step_limit": (f"прогон упёрся в потолок ходов ({max_steps}): "
                       "модель не закончила, поставленное сохранено"),
        "budget_cut": "прогон оборван потолком цены: поставленное сохранено",
        "limit_stop": "прогон остановлен лимитом пользователя до следующего хода",
        "transport_error": "прогон оборвался по проводу",
    }


def _outcome(result, filled) -> str:
    """Итог прогона одним словом — те же слова, что у уровней 1 и 2.

    `interrupted` — заплатили и часть получили; `error` — не получили ничего;
    `refused` — законный отказ модели, повторять его бессмысленно, а стоил он
    столько же. Потолок ходов и потолок цены — это `interrupted`, а не `error`:
    ошибки не было, была граница, которую мы сами и поставили.
    """
    if result.stop == llm.Stop.REFUSED:
        return "refused"
    if result.stop == llm.Stop.CANCELLED:
        return "interrupted"
    if result.stop == llm.Stop.MAX_TOKENS:
        return "interrupted"
    if result.stop == llm.Stop.ERROR or result.error is not None:
        return "interrupted" if filled else "error"
    return "done"


__all__ = ["AgentResult", "fill_agent", "ИМЯ_ЗАДАЧИ"]
