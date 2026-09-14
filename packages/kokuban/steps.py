"""steps.py — объекты доски → шаги решения и файл распознанного.

**Шаг — одна строка записи**, а не кадр и не формула-объект. Кадр остаётся
группировкой шагов («Шаг 1 — привести к каноническому виду» содержит две
строки) и едет в выжимку заголовком.

Из этого следует то, ради чего разделение и заведено: **единица сверки — переход
между соседними шагами**. Отдельная строка почти всегда верна синтаксически,
ошибка живёт между строками; поэтому в ответе модели `ok` у шага N означает
«переход от шага N−1 к шагу N верен», а у первого шага — «строка соответствует
условию». Без этой договорённости список `[{step, ok}]` вырождается в «все
строки синтаксически корректны», то есть в угадывание.

Нераспознанная и неподтверждённая строки из списка не исчезают: у них пустой
`latex` и `confirmed: false`. Исчезни они — и решение из пяти строк выглядело бы
решением из трёх, а пропуск, о котором стоило сказать, стал бы нашим молчанием.
Содержимое таких строк при этом не показывается никому: неверно распознанная
формула синтаксически безупречна, и ошибку распознавания ниже по течению уже не
поймать.

Координат в шаге нет ни одной. `elements` — настоящие идентификаторы
Excalidraw: они нужны браузеру, чтобы разрешить замечание в выноску у нужного
места холста.
"""
from __future__ import annotations

from . import scene as scene_mod


def steps_of(board: scene_mod.Board, lines=None) -> list:
    """Разобранная доска → шаги в порядке чтения.

    Порядок — кадры сверху вниз, внутри кадра сверху вниз; объекты вне кадров
    идут своим местом в общем порядке чтения. Нумерация сквозная: `n` — это
    место строки в решении, и она же печатается человеку в файле распознанного.

    `lines` — записанные строки, если распознанное хранится отдельно от сцены.
    Тогда список строится **по ним и в их порядке**: порядок записи — это то, в
    каком порядке человек подтверждал решение, и переставлять его по геометрии
    значило бы спорить с ним о том, что он сделал. Нарисованное при этом нужно
    по-прежнему: из сцены берутся идентификатор объекта (по нему браузер ставит
    выноску) и кадр, в котором строка лежит.
    """
    if lines is not None:
        return _from_lines(board, lines)
    out: list = []
    names = {f["id"]: f["name"] for f in board.frames}
    for obj in _in_reading_order(board):
        if not obj.line:
            continue
        formula = obj.formula or {}
        out.append({
            "n": len(out) + 1,
            "id": board.short.get(obj.key, ""),
            "latex": formula.get("latex", "") if formula.get("confirmed") else "",
            "source": formula.get("source", "") if formula.get("confirmed") else "",
            "confirmed": bool(formula.get("confirmed")),
            "elements": list(obj.ids),
            "frame": obj.frame,
            "frame_name": names.get(obj.frame, "") if obj.frame else "",
        })
    return out


def _from_lines(board: scene_mod.Board, lines) -> list:
    """Записанные строки → шаги той же формы, привязанные к объектам сцены.

    Строка, нарисованного за которой на доске не осталось (человек стёр
    росчерки, а запись ещё не пересобрали), из списка не исчезает: у неё
    остаётся её собственный идентификатор и пустой список элементов. Исчезни
    она — и решение молча стало бы короче, чем его подтверждал человек.
    """
    объекты = {obj.key: obj for obj in board.objects}
    out: list = []
    for line in lines or ():
        if not isinstance(line, dict):
            continue
        свои = [str(e) for e in (line.get("elements") or ())]
        якорь = None
        for element_id in свои:
            якорь = board.aliases.get(element_id)
            if якорь is not None:
                break
        объект = объекты.get(якорь) if якорь else None
        latex = line.get("latex")
        latex = latex.strip() if isinstance(latex, str) else ""
        source = line.get("source")
        out.append({
            "n": len(out) + 1,
            "id": board.short.get(якорь, "") or str(line.get("id") or ""),
            "latex": latex,
            "source": source if source in scene_mod.SOURCES else "",
            # Подтверждение строки — дело службы, записавшей её; здесь остаётся
            # один признак: есть ли что показать репетитору.
            "confirmed": bool(latex),
            "elements": list(объект.ids) if объект is not None else свои,
            "frame": объект.frame if объект is not None else line.get("frame"),
            "frame_name": _frame_name(board, объект, line),
        })
    return out


def _frame_name(board: scene_mod.Board, объект, line) -> str:
    """Подпись кадра: из сцены, если объект нашёлся, иначе из самой записи."""
    кадр = объект.frame if объект is not None else line.get("frame")
    if кадр:
        for f in board.frames:
            if f["id"] == кадр:
                return f["name"]
    имя = line.get("frame_name")
    return имя if isinstance(имя, str) else ""


def _in_reading_order(board: scene_mod.Board) -> list:
    """Объекты доски по порядку чтения с учётом кадров.

    Кадр — группировка, и строки внутри него читаются подряд, даже если
    геометрически между ними затесался чужой объект. Объекты вне кадров идут
    после всех кадров — тем же правилом, по которому они печатаются в выжимке
    отдельным разделом: «вне шагов» это место, а не порядок.
    """
    out: list = []
    printed: set = set()
    for frame in board.frames:
        own = [o for o in board.objects if o.frame == frame["id"]]
        out.extend(own)
        printed |= {o.key for o in own}
    out.extend(o for o in board.objects if o.key not in printed)
    return out


def lines_text(steps: list) -> str:
    """Шаги → записи для чата: номер и формула, без идентификаторов.

    Без идентификаторов намеренно: в чате ответ не привязывается к объектам
    холста, и шестёрка hex в контексте только просилась бы в ответ. Номер — тот
    же порядок чтения, что в файле распознанного. Непрочитанная строка не
    исчезает: о ней сказано, что она есть и не прочитана.
    """
    out: list = []
    for step in steps or ():
        latex = str(step.get("latex") or "").strip()
        n = step.get("n") or len(out) + 1
        out.append(f"строка {n}: ${latex}$" if latex else f"строка {n}: (не прочитано)")
    return "\n".join(out) if out else "(на доске пока ничего не прочитано)"


def unrecognized_of(steps: list) -> int:
    """Сколько строк записи агенту не показано.

    Считаются и нераспознанные росчерки, и распознанные, но не подтверждённые
    человеком формулы: и то и другое для агента одинаково — «здесь написано
    что-то, чего я не вижу».
    """
    return sum(1 for step in steps or () if not step.get("confirmed"))


def _strokes_word(n: int) -> str:
    """«росчерк» в нужном числе. Строка читается человеком, а не разбирается."""
    tail = abs(n) % 100
    if 11 <= tail <= 14:
        return "росчерков"
    tail %= 10
    if tail == 1:
        return "росчерк"
    if 2 <= tail <= 4:
        return "росчерка"
    return "росчерков"


def latex_file(name: str, steps: list, at: str) -> str:
    """Шаги → текст файла `<имя доски>.latex.md`.

    Это и есть «файл контекста рядом с доской»: приписанный решению материал,
    который уезжает любому прогону этой работы обычной дорогой — тем же куском
    `files` в рамке, что и методичка. Оттого формат — плоский markdown: его
    разбирает как текст хранилище материалов и читает глазами человек.

    Числа — порядок чтения по всей доске, а не по списку ниже: нераспознанные
    строки в файл не попадают, и сквозная нумерация оставила бы их без следа.
    Пропуск в нумерации — след, а строка «не распознано» под списком — его
    объяснение.

    Идентификаторы `[da9bb7]` — те же, что уезжают в выжимку прогона. Одна
    система идентификаторов на обе двери: иначе замечание, полученное от
    репетитора, не разрешается в объект доски.
    """
    lines = [f"Доска «{scene_mod.one_line(name, 80)}», распознано "
             f"{scene_mod.one_line(at, 40)}", ""]
    shown = [step for step in steps or () if step.get("confirmed") and step.get("latex")]
    if shown:
        for step in shown:
            lines.append(f"{step.get('n')}. [{step.get('id')}] ${step.get('latex')}$")
    else:
        lines.append("распознанных строк нет")
    missed = unrecognized_of(steps)
    if missed:
        lines += ["", f"не распознано: {missed} {_strokes_word(missed)}"]
    return "\n".join(lines) + "\n"


__all__ = ["latex_file", "lines_text", "steps_of", "unrecognized_of"]
