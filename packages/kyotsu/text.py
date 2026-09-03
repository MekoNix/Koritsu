"""
text.py — оценка ширины строки в px для Helvetica/Arial (шрифт draw.io).

Точных метрик без шрифта нет, но ширины символов этих шрифтов хорошо
группируются по классам — ниже таблица в долях em (1 em = размер шрифта в px).
Погрешность на строке из 30 символов — единицы px.

Таблица одна на проект: до 2.0.0a4.2 она лежала тремя копиями
(`uml_generator/_text.py`, `fragmos/builder/shapes.py`, `hokoku/_text.py`).
Разъехавшиеся копии не падают — они рисуют текст, вылезающий за рамку блока, и
замечает это человек на собранной схеме. Последняя копия (`hokoku/_text.py`)
убрана в 2.0.0a4.2: `hokoku.docx_ops` меряет ширину отсюда.

Запас (`safety`) здесь не зашит: он не про шрифт, а про то, чем шрифт
подменят при экспорте, и у каждого потребителя свой (см. `uml_generator/_text.py`).
"""

EM = {
    "narrow":    0.28,   # i j l I . , : ; ! | ' `
    "thin":      0.36,   # f t r ( ) [ ] { } / \ - "
    "space":     0.28,
    "digit":     0.56,
    "lat_lower": 0.54,
    "lat_upper": 0.68,
    "cyr_lower": 0.58,
    "cyr_upper": 0.70,
    "wide":      0.85,   # m w M W % @ & ш щ ж ю ф Ш Щ Ж Ю Ф Д Ц
    "other":     0.60,
}

_NARROW = set("iljI.,:;!|'`")
_THIN = set('ftr()[]{}/\\-"')
_WIDE = set("mwMW%@&шщжюфШЩЖЮФДЦ")


def char_em(c: str) -> float:
    """Ширина одного символа в долях em."""
    if c == " ":
        return EM["space"]
    if c in _NARROW:
        return EM["narrow"]
    if c in _THIN:
        return EM["thin"]
    if c in _WIDE:
        return EM["wide"]
    if c.isdigit():
        return EM["digit"]
    if "a" <= c <= "z":
        return EM["lat_lower"]
    if "A" <= c <= "Z":
        return EM["lat_upper"]
    if "а" <= c <= "я" or c == "ё":
        return EM["cyr_lower"]
    if "А" <= c <= "Я" or c == "Ё":
        return EM["cyr_upper"]
    return EM["other"]


def text_width(s: str, font_px: float, *, bold: bool = False,
               safety: float = 1.0) -> float:
    """Оценка ширины строки в px; bold — примерно на 8 % шире."""
    w = sum(char_em(c) for c in s) * font_px * safety
    return w * 1.08 if bold else w
