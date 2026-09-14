"""scene.py — сцена Excalidraw → объекты доски и порядок чтения.

Здесь и только здесь живут координаты. `x`, `y`, `width`, `height` нужны ровно
затем, чтобы разложить нарисованное в порядок чтения (кадры сверху вниз, внутри
кадра сверху вниз), и дальше этого модуля не идут: ни в шаги, ни в выжимку, ни
тем более в запрос к модели. Обратная дорога есть и она другая — идентификатор:
модель называет `[a1b2c3]`, браузер находит по нему элемент и берёт координаты
у себя. Идентификаторы едут наружу, координаты приезжают внутрь.

Что такое объект доски. Единица печати — не всегда элемент Excalidraw:

* росчерки одной формулы нарисованы десятком элементов `freedraw`, объединённых
  общим `groupIds[0]`, и печатаются одной строкой. Наружу такая группа известна
  по **якорю** — первому её элементу в порядке массива `elements`: другого
  общего понятия «первый» у браузера и у службы нет, и на нём же по договору
  лежит `customData`;
* подпись фигуры (`text` с `containerId`) своей строки не имеет — она приезжает
  содержимым своего контейнера. Иначе у каждой фигуры с надписью появился бы
  двойник без смысла, и замечания привязывались бы к нему;
* стрелки печатаются отдельным разделом связей, а не объектами: стрелка говорит
  не о себе, а об отношении двух других объектов.

Короткий идентификатор объекта — шесть hex от sha256 идентификатора якоря. Не
порядковый номер (порядок — наше соглашение, модель не обязана считать так же)
и не `id` Excalidraw (двадцать с лишним знаков случайного мусора на объект —
это токены и лишний повод ошибиться). При столкновении шестёрка удлиняется:
короткий идентификатор обязан быть функцией от `id` и только от него, иначе
один и тот же объект в двух выжимках назывался бы по-разному.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

# Длина короткого идентификатора и метки прогона. Шесть hex на объект: доска
# студента — это десятки объектов, а не тысячи, и столкновение здесь не теряется
# (см. `short_id`), а удлиняет идентификатор.
SHORT_LEN = 6

# Потолок чужого текста внутри служебной строки: имя кадра и подпись стрелки
# печатаются в нашей строке, и длина у них должна быть наша.
LINE_LIMIT = 200

# Имена типов по-русски. Модель читает выжимку, а не документацию Excalidraw;
# «rectangle» ей ничего не сообщает о том, что это блок решения.
TYPES = {
    "rectangle": "прямоугольник",
    "ellipse": "эллипс",
    "diamond": "ромб",
    "text": "текст",
    "line": "линия",
    "arrow": "стрелка",
    "freedraw": "росчерк",
    "image": "картинка",
    "frame": "кадр",
    "magicframe": "кадр",
    "embeddable": "врезка",
    "iframe": "врезка",
    "selection": "выделение",
}

# Типы кадра: кадр группирует строки решения и сам строкой решения не бывает.
FRAME_TYPES = ("frame", "magicframe")

# Откуда взялся LaTeX. Перечень закрытый: «неизвестно откуда» — это повод
# спросить, а не значение поля.
SOURCES = ("myscript", "manual", "mathlive")

_SPACES = re.compile(r"\s+")


def one_line(text: str, limit: int = LINE_LIMIT) -> str:
    """Чужой текст, пригодный для служебной строки: без переносов, с потолком.

    Имя кадра и подпись стрелки написал человек, а печатаются они внутри нашей
    строки. Перенос строки — единственное, чем чужой текст может испортить нашу
    разметку, поэтому переносы схлопываются в пробел. Подделать нашу строку это
    всё равно не даёт: строка начинается с метки прогона, а метки человек не
    знает.
    """
    tight = _SPACES.sub(" ", (text or "")).strip()
    return tight[:limit] + "…" if len(tight) > limit else tight


def short_id(element_id: str, taken: dict) -> str:
    """`id` элемента → короткий идентификатор, без столкновений.

    Берём начало sha256 и удлиняем, пока не станет однозначным. Удлинение, а не
    счётчик-суффикс: суффикс зависел бы от порядка обхода, и одна и та же сцена
    давала бы разные выжимки.
    """
    full = hashlib.sha256(str(element_id).encode("utf-8")).hexdigest()
    length = SHORT_LEN
    while length <= len(full):
        candidate = full[:length]
        before = taken.get(candidate)
        if before is None or before == element_id:
            taken[candidate] = element_id
            return candidate
        length += 1
    # Сюда попасть можно только на двух разных `id` с одинаковым sha256 целиком.
    taken[full] = element_id
    return full


def live(scene: dict) -> list:
    """Элементы сцены без удалённых, в порядке файла (он же порядок рисования).

    Порядок файла важен не сам по себе, а ради якоря группы: «первый элемент
    группы» определён только им.
    """
    elements = (scene or {}).get("elements")
    if not isinstance(elements, list):
        return []
    return [el for el in elements
            if isinstance(el, dict) and el.get("id") and not el.get("isDeleted")]


def order_key(el: dict) -> tuple:
    """Ключ чтения: сверху вниз, при равной высоте — слева направо.

    Здесь координаты и потребляются; дальше этой функции они не идут.
    """
    def number(value):
        return float(value) if isinstance(value, (int, float)) else 0.0
    return (number(el.get("y")), number(el.get("x")))


def group_key(el: dict) -> str:
    """Ключ группы: первый `groupId`, а нет группы — сам элемент.

    Формула из десяти росчерков и формула из одного должны обрабатываться одним
    кодом, иначе одиночная тихо выпадет в «содержимое недоступно».
    """
    groups = el.get("groupIds")
    if isinstance(groups, list) and groups and isinstance(groups[0], str):
        return groups[0]
    return el["id"]


def formula_of(el: dict) -> dict | None:
    """`customData` формулы или None, если элемент формулой не объявлен.

    Возвращается и неподтверждённая формула: она существует, и потерять её
    молча нельзя — просто содержимое такой строки агенту не показывается
    (`confirmed=False`). `latexConfirmed` проверяется на тождество `True`, а не
    на истинность: строка «false», единица и непустой словарь — не подтверждение
    человека, а мусор, приехавший из чужого файла.
    """
    data = el.get("customData")
    if not isinstance(data, dict) or data.get("kind") != "formula":
        return None
    latex = data.get("latex")
    latex = latex.strip() if isinstance(latex, str) else ""
    source = data.get("latexSource")
    return {"latex": latex,
            "source": source if source in SOURCES else "",
            "confirmed": data.get("latexConfirmed") is True and bool(latex)}


@dataclass
class Object:
    """Одна печатаемая единица доски: элемент или группа росчерков.

    `content` и `note` разделены не для порядка, а ради границы, на которой
    держится защита от инъекции: `content` написал человек и печатается с
    отступом, `note` написали мы и печатается в служебной строке. Слей их в одно
    поле — и чужой текст иногда оказывался бы там, где ожидается наш.
    """

    key: str                       # id якоря: под ним объект известен наружу
    type: str                      # чем называем объект в выжимке
    content: str = ""              # текст человека, печатается с отступом
    note: str = ""                 # наша приписка вместо содержимого
    order: tuple = (0.0, 0.0)
    frame: str | None = None       # `frameId` — в каком кадре объект лежит
    ids: list = field(default_factory=list)   # все элементы, из которых он собран
    formula: dict | None = None    # `formula_of` якоря
    line: bool = False             # строка записи: из неё выйдет шаг решения


@dataclass
class Board:
    """Сцена, разобранная один раз: объекты, кадры, связи и обе адресации."""

    objects: list = field(default_factory=list)     # в порядке чтения
    frames: list = field(default_factory=list)      # [{"id", "name"}], сверху вниз
    links: list = field(default_factory=list)       # строки связей для выжимки
    short: dict = field(default_factory=dict)       # id якоря → id6
    aliases: dict = field(default_factory=dict)     # id6 или любой id → id якоря


def _labels(elements: list) -> dict:
    """`containerId` → подпись. Подпись своей строки в выжимке не имеет."""
    out: dict = {}
    for el in elements:
        if el.get("type") == "text" and isinstance(el.get("containerId"), str):
            out.setdefault(el["containerId"], el)
    return out


def _text_of(el: dict, labels: dict) -> str:
    """Содержимое объекта: собственный текст либо привязанная подпись."""
    own = el.get("text")
    if isinstance(own, str) and own.strip():
        return own
    label = labels.get(el["id"])
    if label is not None and isinstance(label.get("text"), str):
        return label["text"]
    return ""


def _type_word(el: dict) -> str:
    """Как назвать элемент. `customData.kind` сильнее типа Excalidraw.

    Человек рисует прямоугольник и объявляет его «условием»; печатать
    «прямоугольник» значило бы потерять единственное, что он про этот блок
    сказал. Не объявил — печатаем тип и добавляем «без типа»: это честно и
    заметно.
    """
    data = el.get("customData")
    if isinstance(data, dict):
        kind = data.get("kind")
        if isinstance(kind, str) and kind.strip() and kind != "formula":
            return one_line(kind, 40)
    word = TYPES.get(el.get("type"), str(el.get("type") or "объект"))
    безликие = ("rectangle", "ellipse", "diamond")
    return f"{word} без типа" if el.get("type") in безликие else word


def _links(arrows: list, by_id: dict, labels: dict, anchor_of: dict,
           short: dict) -> list:
    """Стрелки → строки «[a] → [b] «подпись»».

    Связь собирается по привязкам `startBinding`/`endBinding`, а не по близости
    концов: привязка — то, что человек действительно соединил, а расстояние
    между концом стрелки и фигурой — наша догадка о его намерении. Стрелка, не
    соединяющая ничего, печатается тоже: «ведёт в пустоту» — часто самое
    полезное замечание к чужому решению.
    """
    out: list = []
    for arrow in sorted(arrows, key=order_key):
        def name(target):
            if not target or target not in by_id:
                return "(ни к чему)"
            id6 = short.get(anchor_of.get(target, target))
            return f"[{id6}]" if id6 else "(вне выжимки)"

        own = arrow.get("label")
        if isinstance(own, dict):
            own = own.get("text")
        if not isinstance(own, str) or not own.strip():
            label = labels.get(arrow["id"])
            own = label.get("text") if label else ""
        caption = one_line(own or "")
        tail = f" «{caption}»" if caption else ""
        out.append(f"{name((arrow.get('startBinding') or {}).get('elementId'))} → "
                   f"{name((arrow.get('endBinding') or {}).get('elementId'))}{tail}")
    return out


def _by_element(lines) -> dict | None:
    """`elements` записанных строк → сама строка. Нет строк — None.

    None и пустой список — разные вещи: «распознанное хранится в сцене» и
    «хранится отдельно, и там пусто». Во втором случае формул на доске нет, и
    вычитать их из `customData` было бы возвращением второго источника правды.
    """
    if lines is None:
        return None
    out: dict = {}
    for line in lines:
        if not isinstance(line, dict):
            continue
        for element_id in (line.get("elements") or ()):
            out.setdefault(str(element_id), line)
    return out


def _stroke_key(el: dict, записанное: dict | None) -> str:
    """Ключ группы росчерка: его строка записи, а без записи — группа сцены.

    Ключ строки — её первый росчерк: тот же, по которому служба выдаёт
    идентификатор строки. Росчерк, записью не описанный, остаётся при своей
    группе сцены, как и на доске без записи вовсе.
    """
    line = (записанное or {}).get(el["id"])
    if line is not None:
        first = next((str(e) for e in (line.get("elements") or ()) if e), "")
        if first:
            return first
    return group_key(el)


def _formula_for(ids: list, anchor: dict, записанное: dict | None, lines):
    """Распознанное объекта: из записанных строк, а при их отсутствии — из сцены.

    Приоритета здесь нет и быть не может: источник ровно один. Пока сайт писал
    распознанное в `customData`, им была сцена; когда записанное приходит
    отдельно, им становятся строки, и `customData` не читается даже как запасной
    вариант — устаревшая догадка выглядела бы как подтверждённая формула.
    """
    if lines is None:
        return formula_of(anchor)
    for element_id in ids:
        line = (записанное or {}).get(str(element_id))
        if line is None:
            continue
        latex = line.get("latex")
        latex = latex.strip() if isinstance(latex, str) else ""
        source = line.get("source")
        return {"latex": latex,
                "source": source if source in SOURCES else "",
                # Подтверждение здесь не отдельный флаг: строку записала служба
                # по подтверждению человека, и пустой `latex` — это «строка есть,
                # содержимого нет».
                "confirmed": bool(latex)}
    return None


def read(scene: dict, lines=None) -> Board:
    """Сцена Excalidraw → `Board`. Единственный разбор сцены в пакете.

    Один на всех: и шаги, и выжимка, и сверка ответа обязаны видеть одну и ту же
    доску с одними и теми же короткими идентификаторами. Два разбора разошлись
    бы молча — и замечание модели указывало бы не на ту строку.

    `lines` — записанные строки решения, если распознанное хранится отдельно от
    сцены. Тогда **распознанное берётся только из них**: `customData` сцены не
    читается вовсе, и строка считается показанной репетитору по одному признаку —
    непустому `latex`. Два источника правды об одной формуле разошлись бы молча
    и по-разному: сцена помнила бы вчерашнюю догадку, а запись — сегодняшнее
    исправление человека. Связь строки с нарисованным — по `elements`.
    """
    elements = live(scene)
    by_id = {el["id"]: el for el in elements}
    labels = _labels(elements)

    frames = sorted((el for el in elements if el.get("type") in FRAME_TYPES),
                    key=order_key)
    arrows = [el for el in elements if el.get("type") == "arrow"]

    записанное = _by_element(lines)

    # Росчерки — по строкам записи, а нет записи — по группам сцены; в обоих
    # случаях в порядке рисования. Строка записи сильнее группы: страница
    # собирает строку из штрихов сама и группами Excalidraw не пользуется, и без
    # этого правила девять росчерков одной формулы печатались бы девятью
    # формулами с девятью идентификаторами, ни один из которых не совпал бы с
    # идентификатором строки.
    groups: dict = {}
    for el in elements:
        if el.get("type") == "freedraw":
            groups.setdefault(_stroke_key(el, записанное), []).append(el)

    skip = {label["id"] for label in labels.values()}
    skip |= {el["id"] for el in frames} | {el["id"] for el in arrows}
    skip |= {el["id"] for el in elements if el.get("type") == "freedraw"}

    objects: list = []
    for el in elements:
        if el["id"] in skip:
            continue
        text = _text_of(el, labels)
        formula = _formula_for([el["id"]], el, записанное, lines)
        objects.append(Object(
            key=el["id"],
            type="формула" if formula else _type_word(el),
            content=(f"${formula['latex']}$" if formula and formula["confirmed"]
                     else ("" if formula else text)),
            # «(пусто)» и «содержимое недоступно» — наши слова, поэтому они в
            # служебной строке, а не с отступом: с отступом идёт только чужое.
            note=("содержимое недоступно" if formula and not formula["confirmed"]
                  else ("" if text.strip() else "(пусто)")),
            order=order_key(el),
            frame=el.get("frameId"),
            ids=[el["id"]],
            formula=formula,
            line=formula is not None,
        ))

    for key, members in groups.items():
        # Якорь — первый элемент группы в порядке сцены; у строки записи — её
        # первый росчерк, по которому выдан идентификатор строки. Разойдись
        # они — и замечание репетитора указывало бы на строку, которой нет.
        anchor = next((m for m in members if m["id"] == key), members[0])
        свои = [m["id"] for m in members]
        formula = _formula_for(свои, anchor, записанное, lines)
        shown = bool(formula and formula["confirmed"])
        objects.append(Object(
            key=anchor["id"],
            type="формула" if shown else "росчерк",
            content=(f"${formula['latex']}$" if shown else ""),
            # Договор: росчерк без распознанной строки печатается честной
            # строкой, а не исчезает. Модель должна знать, что запись тут есть и
            # что содержимое ей не показано, — иначе она достроит пропуск сама.
            note="" if shown else "содержимое недоступно",
            order=min(order_key(m) for m in members),
            frame=anchor.get("frameId"),
            ids=свои,
            # Росчерк — всегда строка записи, распознанная или нет: «здесь
            # что-то написано» — это и есть то, что теряется при молчании.
            formula=formula or {"latex": "", "source": "", "confirmed": False},
            line=True,
        ))

    objects.sort(key=lambda o: o.order)

    # Короткие идентификаторы выдаются в порядке чтения, чтобы одна и та же
    # сцена всегда давала одну и ту же выжимку (кроме метки прогона).
    taken: dict = {}
    short: dict = {}
    aliases: dict = {}
    for obj in objects:
        id6 = short_id(obj.key, taken)
        short[obj.key] = id6
        aliases[id6] = obj.key
        # Соседние росчерки формулы разрешаются в якорь: модель их не видела, но
        # назвать любой из них мог человек или заготовка ответа.
        for own in obj.ids:
            aliases.setdefault(own, obj.key)

    anchor_of = {own: obj.key for obj in objects for own in obj.ids}
    return Board(
        objects=objects,
        frames=[{"id": f["id"],
                 "name": one_line(_text_of(f, labels) or f.get("name") or "")}
                for f in frames],
        links=_links(arrows, by_id, labels, anchor_of, short),
        short=short, aliases=aliases,
    )


__all__ = ["Board", "Object", "SHORT_LEN", "SOURCES", "TYPES", "formula_of",
           "group_key", "live", "one_line", "order_key", "read", "short_id"]
