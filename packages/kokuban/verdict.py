"""verdict.py — ответ модели → ответ по договору, сверенный со сценой.

Разделение обязанностей здесь жёсткое и оно же — главная мысль файла.

    Модель отвечает **структурой**. Сверка сличает структуру со сценой и только
    потом отдаёт её наружу.

Почему так, а не «пусть модель напишет замечания текстом»: замечание без
привязки к месту — это разговор, а не проверка. Привязка возможна ровно одним
способом — идентификатором объекта: свободный текст ломается на повторяющихся
надписях, координата запрещена (модель их и не видела), порядковый номер — наше
соглашение, которое модель не обязана считать так же.

Правила сверки, каждое из которых закрывает свой способ ответить мимо:

1. вердикт, вид замечания и режим — только из объявленных наборов;
2. идентификаторы разрешаются в настоящие элементы сцены; **выдуманное не
   молчит** — замечание переезжает в общие с пометкой, а названный несуществующий
   шаг становится отдельным замечанием. Тихо отброшенная половина ответа видна
   только по счёту за токены;
3. `missing` всегда без объектов, даже если модель их назвала: отсутствующий шаг,
   привязанный к случайному соседу, хуже непривязанного;
4. строка списка шагов заводится на **каждую** строку доски, а не только на
   названные моделью: не названная строка — это `ok: null`, и человек должен
   видеть, что про неё не сказали, а не считать её проверенной;
5. у строки, содержимое которой модели не показали (не распознана или не
   подтверждена), `ok` гасится в `null`: `false` на такой строке — ложное
   обвинение, `true` — подтверждение того, чего никто не видел;
6. `correct` при пустом `checked` понижается до `unclear` — пустое подтверждение
   видно как пустое;
7. `correct` при нераспознанных строках понижается: на доске есть запись, которой
   репетитор не видел, и «верно» про неё сказать нельзя;
8. `correct` при хотя бы одном неверном переходе становится `wrong`: ответ,
   противоречащий сам себе, разрешается в пользу подробностей;
9. замечание без текста не выживает: выноска без слов — это только испуг.

Каждое изменение записывается в `notes`: человек должен видеть, ПОЧЕМУ ему не
сказали «верно», а не получить молча другой ответ.
"""
from __future__ import annotations

from . import schema as schema_mod

# Потолки на чужой текст, который пойдёт человеку на экран. Не защита от
# инъекции (для этого есть рамка и метка), а защита экрана: замечание на десять
# килобайт не читается, а выноску на холсте оно закрывает целиком.
NOTE_LIMIT = 500        # знаков на примечание к шагу
REMARK_LIMIT = 1000     # знаков на замечание
CHECKED_LIMIT = 40      # пунктов в перечне сверенного
REPLY_LIMIT = 6000      # знаков на ответ в переписке
DRILL_LIMITS = {"topic": 120, "task": 2000, "hint": 600, "answer": 600, "why": 600}

# Что сказать про строку, содержимое которой репетитору не показывали.
UNCONFIRMED_NOTE = "строка не подтверждена: репетитору её содержимое не показано"


def _text(value, limit: int) -> str:
    """Чужая строка с потолком. Не строка — пусто, а не `str(значение)`."""
    if not isinstance(value, (str, int, float)):
        return ""
    out = str(value).strip()
    return out[:limit] + "…" if len(out) > limit else out


def settle(raw, digest, mode: str = "check") -> dict:
    """Сырой ответ модели + выжимка → ответ по договору.

    `digest` — та самая выжимка, которую модель видела: сверять ответ с другой
    сценой значило бы разрешать идентификаторы по доске, которой в этом прогоне
    не было.

    Возвращается словарь формы результата задания (без того, что знает только
    служба: снимка сцены, расхода и цены). Отказа здесь нет ни одного: любой
    ответ приводится к договору, а всё, что при этом изменено, названо в `notes`.
    """
    mode = schema_mod.normal_mode(mode)
    raw = raw if isinstance(raw, dict) else {}
    notes: list = []
    if not isinstance(raw, dict) or not raw:
        notes.append("модель вернула не объект: разбирать было нечего")

    if mode == "chat":
        # Переписка: ответ — слова, и сверять со сценой в них нечего. Вердикт
        # пустой — «не выносился», а не «не разобрал».
        return {"mode": mode, "verdict": "", "steps": [], "checked": [],
                "remarks": [], "hint": None, "drill": None,
                "reply": _text(raw.get("reply"), REPLY_LIMIT),
                "steps_total": len(digest.steps),
                "unrecognized": int(digest.unrecognized), "notes": notes}

    remarks, unknown_objects = _remarks(raw.get("remarks"), digest)
    if unknown_objects:
        notes.append("названы объекты, которых на доске нет: "
                     + ", ".join(sorted(unknown_objects)[:5]))

    steps, unknown_steps = _steps(raw.get("steps"), digest)
    if unknown_steps:
        listed = ", ".join(f"[{s}]" for s in sorted(unknown_steps)[:5])
        notes.append(f"названы строки, которых на доске нет: {listed}")
        remarks.append({"kind": "hint", "objects": [],
                        "text": f"Проверка сослалась на строки, которых на доске "
                                f"нет: {listed}. Эта часть разбора ни к чему не "
                                f"привязана."})

    checked = [_text(item, REMARK_LIMIT) for item in (raw.get("checked") or [])]
    checked = [item for item in checked if item][:CHECKED_LIMIT]

    unrecognized = int(digest.unrecognized)
    verdict = _verdict(raw.get("verdict"), steps=steps, checked=checked,
                       unrecognized=unrecognized, mode=mode, notes=notes,
                       remarks=remarks)

    out = {
        "mode": mode,
        "verdict": verdict,
        "steps": steps,
        "checked": checked,
        "remarks": remarks,
        "hint": None,
        "drill": None,
        "reply": "",
        "steps_total": len(digest.steps),
        "unrecognized": unrecognized,
        "notes": notes,
    }
    if mode == "hint":
        out["hint"] = _hint(raw.get("hint"), digest, notes)
    if mode == "drill":
        # В режиме задачи разбора решения не просили, и выдавать его за
        # состоявшийся нельзя: пустой вердикт — это «не выносился», а `unclear`
        # означало бы «смотрел и не понял».
        out["drill"] = _drill(raw.get("drill"), notes)
        out["verdict"] = ""
        out["steps"], out["checked"], out["remarks"] = [], [], remarks
    return out


def _steps(raw, digest) -> tuple:
    """Записи модели о шагах → запись на каждую строку доски, в порядке чтения.

    Список строится от доски, а не от ответа: строка, про которую модель
    промолчала, обязана быть видна человеку как «не сказано» (`ok: null`), иначе
    молчание читается как согласие.
    """
    said: dict = {}
    unknown: set = set()
    for item in (raw or []):
        if not isinstance(item, dict):
            continue
        step = digest.step_by(item.get("step"))
        if step is None:
            name = str(item.get("step") or "").strip().strip("[]")
            if name:
                unknown.add(name)
            continue
        ok = item.get("ok")
        said[step["id"]] = {"ok": ok if isinstance(ok, bool) else None,
                            "note": _text(item.get("note"), NOTE_LIMIT)}

    out: list = []
    for step in digest.steps:
        told = said.get(step["id"], {"ok": None, "note": ""})
        ok, note = told["ok"], told["note"]
        if not step["confirmed"]:
            # Ни обвинить, ни подтвердить строку, которой модель не видела: обе
            # стороны здесь одинаково неправдивы. Вынесенный про неё приговор
            # гасится вместе с объяснением — объяснять нечего, содержимого
            # строки не видел никто.
            note = note if ok is None and note else UNCONFIRMED_NOTE
            ok = None
        out.append({"step": step["id"], "ok": ok, "note": note})
    return out, unknown


def _remarks(raw, digest) -> tuple:
    """Замечания модели → замечания с настоящими идентификаторами элементов."""
    out: list = []
    unknown_all: set = set()
    for item in (raw or []):
        if not isinstance(item, dict):
            continue
        text = _text(item.get("text"), REMARK_LIMIT)
        if not text:
            continue
        kind = item.get("kind")
        kind = kind if kind in schema_mod.REMARK_KINDS else "hint"

        objects: list = []
        unknown: list = []
        for name in (item.get("objects") or []):
            if not isinstance(name, (str, int, float)):
                continue
            found = digest.resolve(str(name))
            if found is None:
                unknown.append(str(name).strip().strip("[]"))
            elif found not in objects:
                objects.append(found)
        unknown_all |= set(unknown)

        if kind == "missing":
            # Договор: у «недостающего» объектов нет. Названные моделью здесь не
            # ошибка модели, а неверно выбранный вид, — и упоминание о них
            # полезнее в тексте, чем выноской не на том месте.
            if objects or unknown:
                text += " (замечание про пропуск: к объектам не привязывается)"
            objects = []
        elif unknown:
            listed = ", ".join(sorted(set(unknown))[:5])
            text += (f" (часть названных объектов на доске не найдена: {listed})"
                     if objects else
                     f" (замечание без привязки: названных объектов на доске нет: "
                     f"{listed})")
        out.append({"kind": kind, "objects": objects, "text": text})
    return out, unknown_all


def _verdict(raw, *, steps: list, checked: list, unrecognized: int, mode: str,
             notes: list, remarks: list) -> str:
    """Вердикт из объявленных, понижённый там, где подтверждать нечем."""
    verdict = raw if raw in schema_mod.VERDICTS else "unclear"
    if raw not in schema_mod.VERDICTS and raw is not None:
        notes.append("вердикт назван словом не из объявленных — принят как unclear")
    if verdict != "correct":
        return verdict

    if any(step["ok"] is False for step in steps):
        notes.append("вердикт «верно» назван при неверном переходе — принят как wrong")
        return "wrong"
    if not checked:
        notes.append("вердикт «верно» назван без перечня сверенного — понижен")
        remarks.append({
            "kind": "hint", "objects": [],
            "text": "Проверка объявила решение верным, но не перечислила, что именно "
                    "сверила. Такое подтверждение не засчитывается: попросите "
                    "проверить ещё раз или сверьте ход сами.",
        })
        return "unclear"
    if unrecognized:
        notes.append("вердикт «верно» назван при нераспознанных строках — понижен")
        remarks.append({
            "kind": "hint", "objects": [],
            "text": f"На доске есть записи, содержимое которых репетитору не "
                    f"показано ({unrecognized}). Подтвердить решение целиком по "
                    f"такой доске нельзя: подтвердите распознанное или наберите "
                    f"эти строки.",
        })
        return "unclear"
    return verdict


def _hint(raw, digest, notes: list):
    """Подсказка: одна строка текста и якорь, разрешённый в шаг доски."""
    if not isinstance(raw, dict):
        notes.append("подсказки в ответе не оказалось")
        return None
    text = _text(raw.get("text"), REMARK_LIMIT)
    if not text:
        notes.append("подсказка пришла без слов — отброшена")
        return None
    step = digest.step_by(raw.get("step"))
    if step is None and str(raw.get("step") or "").strip():
        notes.append("подсказка сослалась на строку, которой на доске нет")
    return {"step": step["id"] if step else "", "text": text}


def _drill(raw, notes: list):
    """Задача на тренировку. Без условия или без «почему» — не задача.

    `why` обязательно потому, что задача без объяснения, какой шаг не сошёлся,
    неотличима от случайной: человек сел за доску не за упражнениями вообще.
    """
    if not isinstance(raw, dict):
        notes.append("задачи в ответе не оказалось")
        return None
    out = {name: _text(raw.get(name), limit) for name, limit in DRILL_LIMITS.items()}
    if not out["task"]:
        notes.append("задача пришла без условия — отброшена")
        return None
    if not out["why"]:
        notes.append("задача пришла без объяснения, какой шаг не сошёлся")
    return out


__all__ = ["CHECKED_LIMIT", "DRILL_LIMITS", "NOTE_LIMIT", "REMARK_LIMIT",
           "UNCONFIRMED_NOTE", "settle"]
