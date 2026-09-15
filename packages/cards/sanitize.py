"""sanitize.py — безопасное подмножество Markdown внутри карточек.

Можно: абзацы, **жирный**, *курсив*, `код`, блоки кода, списки, таблицы, формулы KaTeX
`$…$` и `$$…$$`. Нельзя — и это проблема с номером строки, а не молчаливая чистка:

- сырой HTML (`<div>`, `<script>`, комментарии `<!-- -->`) и отдельно `<iframe>`;
- картинки `![…](…)` — в наборе v1 картинок нет вовсе;
- ссылки `[текст](адрес)`, `<https://…>`, определения `[id]: адрес` и голые адреса
  `https://…` — в карточках ссылок нет;
- команды KaTeX, открывающие адреса или добавляющие HTML: `\\href`, `\\url`,
  `\\includegraphics`, `\\htmlClass`, `\\htmlId`, `\\htmlStyle`, `\\htmlData`;
- управляющие символы.

HTML не вырезается, а запрещается: санитайзер разметки — гонка за новыми обходами, а отказ
не устаревает. Карточку чинит автор, и видит, что именно чинить.

Внутри блоков кода и `код` проверок нет: там всё показывается текстом. Внутри формул
проверяются только команды KaTeX: `a<b` в формуле — не HTML.
"""
from __future__ import annotations

import re

from .model import Problem, normalize_input
from .scan import scan

_CODE_SPAN = re.compile(r"(`+)(?!`)(.+?)(?<!`)\1(?!`)")
_MATH_SPAN = re.compile(r"(?<!\\)\$\$.+?(?<!\\)\$\$|(?<!\\)\$(?![\s$])(?:\\.|[^$\\])*?(?<![\s\\])\$")

_LATEX = re.compile(r"\\(href|url|includegraphics|htmlClass|htmlId|htmlStyle|htmlData)(?![A-Za-z])")
_IFRAME = re.compile(r"<\s*/?\s*iframe\b", re.I)
_AUTOLINK = re.compile(r"<(?:[A-Za-z][A-Za-z0-9+.-]{1,31}):[^<>\s]*>")
_HTML = re.compile(r"<(?:/?[A-Za-z][A-Za-z0-9:-]*(?=[\s/>]|$)|!--|![A-Za-z]|\?)")
_IMAGE = re.compile(r"!\[[^\]\n]*\]\s*[(\[]")
_LINK = re.compile(r"\[[^\]\n]*\]\([^)\n]*\)")
_REFDEF = re.compile(r"^ {0,3}\[[^\]\n]+\]:\s*\S")
_BARE_URL = re.compile(r"\b(?:https?|ftp|file|javascript|data):(?://)?\S+", re.I)
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f\u202a-\u202e\u2066-\u2069]")


def _snip(s: str, limit: int = 40) -> str:
    s = s.strip()
    return s if len(s) <= limit else s[: limit - 1] + "…"


def check_line(line: str, kind: str) -> list[tuple[str, str]]:
    """Одна строка → `(код, текст)` проблем, не больше одной на код."""
    if kind == "code":
        return []
    out: list[tuple[str, str]] = []
    seen: set[str] = set()

    def add(code: str, text: str) -> None:
        if code not in seen:
            seen.add(code)
            out.append((code, text))

    m = _CONTROL.search(line)
    if m:
        add("control_char", f"в строке управляющий символ U+{ord(m.group(0)):04X} — уберите его")

    s = line if kind == "math" else _CODE_SPAN.sub(lambda x: " " * len(x.group(0)), line)
    for m in _LATEX.finditer(s):
        cmd = m.group(1)
        if cmd in ("href", "url"):
            add("latex_link", f"команда `\\{cmd}` в формуле запрещена: в карточках нет ссылок")
        else:
            add("latex_command", f"команда `\\{cmd}` в формуле запрещена")
    if kind == "math":
        return out

    s = _MATH_SPAN.sub(lambda x: " " * len(x.group(0)), s)
    if _IFRAME.search(s):
        add("iframe", "встроенный фрейм `<iframe>` запрещён")
    m = _AUTOLINK.search(s)
    if m:
        add("link", f"ссылки в карточках не поддерживаются: `{_snip(m.group(0))}`")
    rest = _IFRAME.sub(" ", _AUTOLINK.sub(" ", s))
    m = _HTML.search(rest)
    if m:
        add("raw_html", f"сырой HTML не поддерживается: `{_snip(rest[m.start():m.start() + 40])}` "
                        "— пишите разметкой Markdown")

    # Картинка и ссылка ищутся порознь: `![a](b)` сама содержит `[a](b)`, поэтому ссылки
    # ищутся в строке, где картинки уже вырезаны.
    for m in _IMAGE.finditer(s):
        end = s.find(")", m.end())
        add("image", "картинки в карточках не поддерживаются: "
                     f"`{_snip(s[m.start():end + 1 if end >= 0 else m.start() + 40])}`")
    no_img = re.sub(r"!\[[^\]\n]*\]\s*(?:\([^)\n]*\)|\[[^\]\n]*\])?", " ", s)
    m = _LINK.search(no_img)
    if m:
        add("link", f"ссылки в карточках не поддерживаются: `{_snip(m.group(0))}` "
                    "— оставьте только текст")
    elif _REFDEF.search(no_img):
        add("link", f"определения ссылок не поддерживаются: `{_snip(no_img)}`")
    else:
        m = _BARE_URL.search(no_img)
        if m:
            add("link", f"адреса в карточках не поддерживаются: `{_snip(m.group(0))}`")
    return out


def unclosed_text(kind: str) -> tuple[str, str]:
    if kind == "code":
        return ("unclosed_fence", "блок кода, открытый в этой строке, не закрыт такой же оградой "
                                  "(```) — закройте его")
    return ("unclosed_math", "формула `$$`, открытая в этой строке, не закрыта `$$`")


def sanitize_md(text: str) -> list[Problem]:
    """Текст вопроса, ответа или разбора → проблемы подмножества §2.2, строки с 1."""
    lines = normalize_input(text).split("\n")
    kinds, unclosed = scan(lines)
    out: list[Problem] = []
    for i, kind in unclosed:
        code, msg = unclosed_text(kind)
        out.append(Problem(i + 1, code, msg))
    for i, (line, kind) in enumerate(zip(lines, kinds)):
        for code, msg in check_line(line, kind):
            out.append(Problem(i + 1, code, msg))
    out.sort(key=lambda p: (p.line or 0))
    return out


__all__ = ["sanitize_md", "check_line"]
