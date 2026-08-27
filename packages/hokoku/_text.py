"""
_text — оценка ширины текста в px для Helvetica/Arial (шрифт draw.io).

Точных метрик без шрифта нет, но ширины символов хорошо группируются по
классам (доли em). Таблица та же, что у fragmos и uml_generator (пакеты независимы — копия).
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


def text_width(s: str, font_px: float, bold: bool = False) -> float:
    """Оценка ширины строки в px; bold — примерно на 8 % шире."""
    w = sum(_char_em(c) for c in s) * font_px
    return w * 1.08 if bold else w
