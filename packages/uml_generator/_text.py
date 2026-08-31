"""
_text — оценка ширины текста в px для шрифта, которым draw.io рисует блоки.

Точных метрик без шрифта нет, но ширины символов хорошо группируются по
классам (доли em). Таблица та же, что у fragmos (модули независимы — копия).

Про запас (`SAFETY`): таблица набрана по Helvetica/Arial, а экспорт идёт под
Linux, где Helvetica нет и подставляется DejaVu Sans — она шире. Замер на
корпусе реальных строк членов и заголовков: DejaVu/оценка от 1.06 до 1.23.
Без запаса длинные строки вылезали за правую границу блока — это было видно
на собранной диаграмме («# Name: string { get; private set; }» выходил за рамку).
Ошибка в большую сторону безобидна (блок чуть шире), в меньшую — ломает вид.
"""

_EM = {
    "narrow": 0.28, "thin": 0.36, "space": 0.28, "digit": 0.56,
    "lat_lower": 0.54, "lat_upper": 0.68, "cyr_lower": 0.58, "cyr_upper": 0.70,
    "wide": 0.85, "other": 0.60,
}
_NARROW = set("iljI.,:;!|'`")
_THIN = set('ftr()[]{}/\\-"')
_WIDE = set("mwMW%@&шщжюфШЩЖЮФДЦ")


def _char_em(c: str) -> float:
    if c == " ":
        return _EM["space"]
    if c in _NARROW:
        return _EM["narrow"]
    if c in _THIN:
        return _EM["thin"]
    if c in _WIDE:
        return _EM["wide"]
    if c.isdigit():
        return _EM["digit"]
    if "a" <= c <= "z":
        return _EM["lat_lower"]
    if "A" <= c <= "Z":
        return _EM["lat_upper"]
    if "а" <= c <= "я" or c == "ё":
        return _EM["cyr_lower"]
    if "А" <= c <= "Я" or c == "Ё":
        return _EM["cyr_upper"]
    return _EM["other"]


SAFETY = 1.24                       # запас под подстановку шрифта, см. шапку модуля


def text_width(s: str, font_px: float, bold: bool = False) -> float:
    """Оценка ширины строки в px; bold — примерно на 8 % шире."""
    w = sum(_char_em(c) for c in s) * font_px * SAFETY
    return w * 1.08 if bold else w
