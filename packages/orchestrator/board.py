"""board — дверь к доске: снимок сцены, куски промпта, один вызов, сверка ответа.

Ядро (`kokuban`) — чистые функции над JSON: сцена на входе, текст и словари на
выходе. Оно не знает ни про диск, ни про модель, ни про хранилище, и `llm.Part`
не собирает никогда. Собирать куски промпта, звать модель, класть снимок сцены
артефактом и записывать прогон — работа этой двери: роли `rules`/`files`/
`request` создаёт оркестратор, и второго места, где они создаются, в проекте нет.

**Один вызов, а не петля инструментов.** Проверка односнимковая: доска целиком
уезжает куском промпта, спрашивать у неё нечего, ходить по ней тоже. Петля
(`fill_agent`) стоила бы дюжину вызовов и историю, которая не сохраняется, а
дала бы то же самое.

**Два забора вокруг чужого текста.** Внутри выжимки — метка прогона у каждой
служебной строки (`kokuban.digest`), снаружи — рамка со случайной меткой,
которую слой модели ставит вокруг недоверенного куска. Условие задачи и
пожелания едут теми же недоверенными кусками: их пишет тот же человек, что
рисует доску.

**Снимок кладётся до вызова.** Артефакт адресуется содержимым, поэтому два
прогона по неизменившейся доске дают один артефакт, а оборвавшийся прогон всё
равно оставляет то, что проверялось. Чем построен снимок, пишется в журнал
производных: без версии сериализатора и метки прогона выжимку не пересобрать, а
хранить её текстом нельзя — через месяц он разойдётся с исправленным
сериализатором молча.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

import kokuban
import llm
from llm.model import Part

from . import fill as fill_mod, prompt as prompt_mod

# Как назван снимок сцены в журнале производных. Имя артефакта нигде не
# участвует в адресации (она по содержимому) и нужно человеку, читающему журнал.
SNAPSHOT = "доска"


@dataclass
class BoardCheck:
    """Итог одного прогона доски.

    Отдельный тип, а не словарь: у прогона бывает исход «модель отказала» и
    «оборвалось по проводу», и словарь отвечал бы на них правдоподобной
    пустотой — вердиктом `unclear` без указания, что вызова вовсе не было.
    `ok` означает «ответ есть и он по схеме»; всё остальное — в `problems`, в
    общей форме замечаний проекта.

    `steps` содержит запись на **каждую** строку доски, а не только на
    названные моделью: не названная строка — это `ok: null`, и человек должен
    видеть, что про неё не сказали.
    """

    run: object
    mode: str = "check"
    verdict: str = ""
    steps: list = field(default_factory=list)
    checked: list = field(default_factory=list)
    remarks: list = field(default_factory=list)
    hint: dict | None = None
    drill: dict | None = None
    reply: str = ""
    scene_artifact: str = ""
    digest_sha: str = ""
    mark: str = ""
    steps_total: int = 0
    unrecognized: int = 0
    usage: dict = field(default_factory=dict)
    problems: list = field(default_factory=list)
    ok: bool = False
    stop: str = ""


def check_board(project, *, endpoint: str, scene: dict, task: str = "",
                wishes: str = "", mode: str = "check", level: str = "explain",
                step: str = "", lines=None, message: str = "", history=None,
                cancel=None, effort=None) -> BoardCheck:
    """Доска + просьба человека → разбор, сверенный со сценой.

    `mode` — `check` (проверить), `hint` (подсказать по шагу `step`), `drill`
    (дать задачу на тренировку): одно задание с полем, а не три договора.
    `level` — сколько помощи дать (`hint` | `explain` | `solution`).

    `task` и `wishes` — условие задачи и то, что человек просил проверить
    словами. Едут недоверенными кусками, а не вопросом: в чужом тексте бывает
    написано «забудь предыдущие указания», и разница между «указание» и
    «данные» здесь несущая.

    `lines` — записанные строки решения, когда распознанное хранится отдельно от
    сцены. Тогда формулы репетитор видит из них, а сцена даёт объекты и порядок
    чтения. Не дали — распознанное читается из самой сцены.

    `message` и `history` — режим `chat`: последнее сообщение человека и
    прежняя переписка (записи `{"role": "you" | "tutor", "text": …}`). Едут
    теми же недоверенными кусками, что условие и пожелания: ответы репетитора в
    переписке — тоже текст, который человек мог поправить на томе.
    """
    mode = mode if mode in kokuban.MODES else kokuban.DEFAULT_MODE
    level = level if level in kokuban.LEVELS else kokuban.DEFAULT_LEVEL

    run = project.start_run(level=1, endpoint=endpoint)
    digest = kokuban.digest(scene, lines=lines)

    parts = [Part(role="rules", text=kokuban.rules(mode, level), stable=True)]
    parts += prompt_mod.data_parts([("условие задачи", task), ("пожелания", wishes)])
    if mode == "chat":
        # Чат: записи с доски — пронумерованным списком, без идентификаторов и
        # без выжимки с меткой. Ответ ни к чему на холсте не привязывается, и
        # идентификаторы в контексте только просились бы в ответ.
        parts += prompt_mod.data_parts([
            ("записи на доске", kokuban.lines_text(digest.steps)),
            ("переписка", _history_text(history)),
            ("сообщение человека", message)])
    else:
        parts += prompt_mod.data_parts([("выжимка доски", digest.text)])
    parts.append(Part(role="request", stable=False,
                      text=kokuban.request(mode, level, step)))
    # Метка рамки выпускается по всем кускам сразу и до первого рендера: только
    # тогда записанное в прогоне совпадает с тем, что уехало по проводу.
    fill_mod._seal(project, run, parts)

    art = project.put_artifact(_scene_bytes(scene), name=SNAPSHOT)
    project.note_derived(art, tool="board_check", inputs=[], run=run.id,
                         params={"mode": mode, "level": level, "mark": digest.mark,
                                 "digest_sha": digest.sha,
                                 "serializer": kokuban.DIGEST_VERSION})

    result = llm.generate_object(
        endpoint, kokuban.schema(mode), parts, effort=effort, cancel=cancel,
        limit=project.limit(), journal=project.journal(), frame_mark=run.mark,
        meta={"run": run.id, "level": 1, "board": mode})

    raw = result.value if result.ok and isinstance(result.value, dict) else {}
    settled = kokuban.settle(raw, digest, mode)

    out = BoardCheck(
        run=run, mode=mode, verdict=settled["verdict"], steps=settled["steps"],
        checked=settled["checked"], remarks=settled["remarks"],
        hint=settled["hint"], drill=settled["drill"],
        reply=str(settled.get("reply") or ""),
        scene_artifact=art, digest_sha=digest.sha, mark=digest.mark,
        steps_total=settled["steps_total"], unrecognized=settled["unrecognized"],
        usage=llm.usage_of(result), ok=bool(raw), stop=result.stop)
    if not out.ok:
        out.problems.append(fill_mod._problem("model_failed", None,
                                              fill_mod._why(result)))
    # Всё, что сверка изменила в ответе, — замечанием уровня «к сведению»:
    # понижённый вердикт человек увидит и в разборе, а почему он понижен, должно
    # остаться и в журнале прогона.
    for note in settled["notes"]:
        out.problems.append(fill_mod._problem("board_settled", None, note, "info"))

    run.steps.append({"board": mode, "mark": digest.mark, "scene": art,
                      "ok": out.ok, "stop": out.stop})
    project.finish_run(run, _outcome(out, result))
    return out


def steps(scene: dict, *, lines=None) -> list:
    """Сцена → шаги решения. Прямой проход к ядру для службы.

    Проход, а не импорт ядра службой: `kokuban` службе не виден по правилу
    разреза, а пересобрать шаги ей нужно на каждое подтверждение формулы.
    Здесь нет ни одного своего решения — только адрес.
    """
    return kokuban.steps(scene, lines=lines)


def latex_file(name: str, steps: list, at: str) -> str:
    """Шаги → текст файла распознанного рядом с доской. Тот же проход."""
    return kokuban.latex_file(name, steps, at)


def short_id(element_id: str, taken: dict) -> str:
    """`id` росчерка → короткий идентификатор его строки. Тот же проход.

    Нужен службе затем же, зачем ей `steps`: строки она иногда собирает сама —
    по тому, что страница уже прочла с этих штрихов, — и идентификатор такой
    строки обязан совпасть с тем, который выдаст ядро, разбирая ту же сцену.
    Разойдись они — и замечание репетитора указывало бы в пустоту.

    `taken` — уже выданные идентификаторы этой сборки: короткий идентификатор
    удлиняется, пока не станет однозначным, и знать об этом может только тот,
    кто выдаёт их подряд.
    """
    return kokuban.short_id(element_id, taken)


def _history_text(history) -> str:
    """Прежняя переписка одним куском: «Вы: …» и «Агент: …» по строке.

    Плоский текст, а не список сообщений ролями модели: ответы агента в
    переписке лежат на томе и правятся так же, как всё остальное, что человек
    пишет, — значит, и едут они данными, а не словами модели о самой себе.
    """
    lines: list = []
    for item in history or ():
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        who = "Агент" if item.get("role") == "tutor" else "Вы"
        lines.append(f"{who}: {text}")
    return "\n\n".join(lines)


def _scene_bytes(scene: dict) -> bytes:
    """Сцена в канонические байты снимка.

    С сортировкой ключей и без пробелов: артефакт адресуется содержимым, а из
    браузера один и тот же холст приезжает то с одним порядком ключей, то с
    другим. Без канонизации каждое сохранение плодило бы новый снимок той же
    доски.
    """
    return json.dumps(scene if isinstance(scene, dict) else {}, ensure_ascii=False,
                      sort_keys=True, separators=(",", ":")).encode("utf-8")


def _outcome(out: BoardCheck, result) -> str:
    """Итог прогона одним словом: done | refused | error.

    `refused` отделён от `error` по той же причине, что и у прочих прогонов:
    законный отказ модели повторять бессмысленно, а денег он стоил столько же.
    Промежуточного «interrupted» здесь нет — вызов один, и получить половину
    разбора нельзя.
    """
    if out.ok:
        return "done"
    return "refused" if result.stop == llm.Stop.REFUSED else "error"


__all__ = ["BoardCheck", "SNAPSHOT", "check_board", "latex_file", "short_id",
           "steps"]
