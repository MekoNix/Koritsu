"""
cards — короткая карточка материала и опись проекта.

Карточка считается без модели: тип, имя, размер, сколько страниц или строк,
язык, первые осмысленные строки. Из карточек собирается опись — то единственное,
что уходит в промпт по умолчанию. Полный текст модель запрашивает сама, кусками
по идентификатору, поэтому идентификатор стоит первым в карточке.

Опись должна быть дешёвой: десяток строк на материал, а не абзац. Предел жёсткий
(`CARD_MAX_LINES`) — иначе один разговорчивый PDF съест бюджет за всю опись.
"""
from __future__ import annotations

from ._text import first_lines
from .model import (KIND_DOCX, KIND_IMAGE, KIND_PDF, KIND_UNKNOWN, KIND_WORDS,
                    LANG_WORDS, UNIT_LINE, UNIT_WORDS, Card, Material)

# Больше этого карточка не бывает: 20 материалов × 8 строк — это ещё промпт,
# а не простыня.
CARD_MAX_LINES = 8
# Сколько первых строк содержимого показывать и какой длины.
PREVIEW_LINES = 3
PREVIEW_WIDTH = 90


def human_size(size: int) -> str:
    if size < 1024:
        return f"{size} Б"
    if size < 1024 * 1024:
        return f"{size / 1024:.0f} КБ"
    return f"{size / 1024 / 1024:.1f} МБ".replace(".", ",")


def _plural(n: int, forms: tuple[str, str, str]) -> str:
    """Русское согласование числительного: 1 страница, 2 страницы, 5 страниц."""
    n = abs(n)
    if n % 10 == 1 and n % 100 != 11:
        return forms[0]
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return forms[1]
    return forms[2]


def _amount(m: Material) -> str:
    """«12 страниц» — числом и словом. Слово берётся по коду единицы
    (`UNIT_WORDS`): без своей строки для абзацев карточка word-документа
    сказала бы «12 строк» про двенадцать абзацев."""
    if not m.unit or not m.count:
        return ""
    forms = UNIT_WORDS.get(m.unit, UNIT_WORDS[UNIT_LINE])
    return f"{m.count} {_plural(m.count, forms)}"


def preview_of(units: list[str]) -> list[str]:
    """Превью содержимого для карточки. Считается один раз при добавлении и
    кладётся в метаданные: опись потом собирается, не читая содержимое с диска."""
    return first_lines(units, count=PREVIEW_LINES, width=PREVIEW_WIDTH)


def card(material: Material) -> Card:
    """Карточка одного материала — коротко, без модели, не длиннее CARD_MAX_LINES."""
    m = material
    # Вид — словом, а не кодом: карточку читает человек, а `kind` в ней уже
    # есть у того, кто читает карточку службы (`api`) или ответ list_materials.
    head = [KIND_WORDS.get(m.kind, m.kind), human_size(m.size)]
    amount = _amount(m)
    if amount:
        head.append(amount)
    if m.kind == KIND_IMAGE and m.extra.get("width"):
        head.append(f"{m.extra['width']}×{m.extra['height']} пикселей")
    if m.lang:
        head.append(LANG_WORDS.get(m.lang, m.lang))
    lines = [f"[{m.id}] {m.name} — " + ", ".join(head)]

    if m.origin and m.origin.get("parent_name"):
        # Откуда вынули: у PDF это страница, у Word — номер абзаца. Без этой
        # строки картинку в описи не отличить от отдельно загруженной.
        page, para = m.origin.get("page"), m.origin.get("paragraph")
        where = f", страница {page}" if page else (f", абзац {para}" if para else "")
        lines.append(f"источник: «{m.origin['parent_name']}»{where}")

    if m.kind in (KIND_PDF, KIND_DOCX):
        if m.extra.get("title"):
            lines.append(f"заголовок: {m.extra['title']}")
        counts = []
        if m.extra.get("images"):
            n = m.extra["images"]
            counts.append(f"{n} {_plural(n, ('картинка', 'картинки', 'картинок'))} отдельными материалами")
        if m.extra.get("tables"):
            n = len(m.extra["tables"])
            counts.append(f"{n} {_plural(n, ('таблица', 'таблицы', 'таблиц'))}")
        if counts:
            lines.append("извлечено: " + ", ".join(counts))

    for note in m.notes:
        lines.append(note)

    preview = list(m.extra.get("preview") or ())
    if preview:
        label = "распознано" if m.kind == KIND_IMAGE else "начало"
        room = CARD_MAX_LINES - len(lines) - 1
        preview = preview[:max(0, room)]
        if preview:
            lines.append(f"{label}: {preview[0]}")
            lines.extend(f"  {s}" for s in preview[1:])
    elif m.kind == KIND_UNKNOWN and not m.notes:
        lines.append("содержимое недоступно")

    return Card(id=m.id, lines=lines[:CARD_MAX_LINES])


def inventory(materials: list[Material]) -> str:
    """Опись проекта: карточки всех материалов подряд — это и есть то, что
    уходит в промпт по умолчанию."""
    n = len(materials)
    head = f"Материалы проекта ({n} {_plural(n, ('материал', 'материала', 'материалов'))}):"
    return "\n\n".join([head, *(card(m).text for m in materials)])
