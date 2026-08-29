"""
markdown — разбор Markdown в простое дерево блоков для DOCX.

Блоки: Para (обычный / заголовок / цитата / пункт списка), CodeBlock, Hr,
ImgBlock, TableBlock. Inline: Span (bold/italic/strike/code/link).
Не CommonMark целиком — то, что реально пишут в отчётах.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from itertools import groupby


@dataclass
class Span:
    text:   str
    bold:   bool = False
    italic: bool = False
    strike: bool = False
    code:   bool = False
    link:   str | None = None
    ref:    str | None = None      # ссылка на закладку подписи (поле REF); text — кэш номера
    math:   bool = False           # text — LaTeX, рендерится формулой OMML


@dataclass
class Para:
    spans: list[Span]
    kind:  str = "p"        # p | h1..h6 | quote | ul | ol
    level: int = 0          # вложенность списка или цитаты («> >» — 1)
    ordered_start: int = 1


@dataclass
class CodeBlock:
    text: str
    lang: str = ""


@dataclass
class Hr:
    pass


@dataclass
class ImgBlock:
    src:     str
    caption: str = ""
    width_cm: float | None = None
    align:   str | None = None


@dataclass
class MathBlock:
    latex: str


@dataclass
class TableBlock:
    rows:   list[list[list[Span]]]
    header: bool = True
    align:  list[str] = field(default_factory=list)   # left|center|right по колонкам


Block = Para | CodeBlock | Hr | ImgBlock | TableBlock | MathBlock

# ── inline ────────────────────────────────────────────────────────────────────

_INLINE_RE = re.compile(
    r"(?P<esc>\\[\\`*_~\[\]()#|$])"
    r"|\$(?P<math>[^$\n]+?)\$"
    r"|`(?P<code>[^`\n]+?)`"
    r"|\*\*\*(?P<bi>.+?)\*\*\*"
    r"|(?<!\w)___(?P<bi2>.+?)___(?!\w)"
    r"|\*\*(?P<b>.+?)\*\*"
    r"|(?<!\w)__(?P<b2>.+?)__(?!\w)"
    r"|\*(?P<i>[^*\n]+?)\*"
    r"|(?<!\w)_(?P<i2>[^_\n]+?)_(?!\w)"
    r"|~~(?P<s>.+?)~~"
    r"|\[(?P<lt>[^\]\n]+?)\]\((?P<lu>[^\s)]+)\)"
    r"|(?P<url>https?://[^\s<>()\"']+)"
    r"|\{ref:(?P<ref>[^\s{}]+)\}"
)


def parse_inline(text: str, **base) -> list[Span]:
    """Разобрать inline-разметку. base — атрибуты, наследуемые всеми span'ами."""
    out: list[Span] = []
    pos = 0

    def plain(s: str):
        if s:
            out.append(Span(s, **base))

    for m in _INLINE_RE.finditer(text):
        plain(text[pos:m.start()])
        g = next(k for k, v in m.groupdict().items() if v is not None)
        if g == "esc":
            plain(m.group("esc")[1])
        elif g == "math":
            out.append(Span(m.group("math"), math=True))
        elif g == "code":
            out.append(Span(m.group("code"), code=True, **{k: v for k, v in base.items() if k != "code"}))
        elif g in ("bi", "bi2"):
            out.extend(parse_inline(m.group(g), **{**base, "bold": True, "italic": True}))
        elif g in ("b", "b2"):
            out.extend(parse_inline(m.group(g), **{**base, "bold": True}))
        elif g in ("i", "i2"):
            out.extend(parse_inline(m.group(g), **{**base, "italic": True}))
        elif g == "s":
            out.extend(parse_inline(m.group("s"), **{**base, "strike": True}))
        elif g == "lt":
            out.extend(parse_inline(m.group("lt"), **{**base, "link": m.group("lu")}))
        elif g == "ref":
            out.append(Span("?", ref="_Ref_" + m.group("ref"), **{k: v for k, v in base.items() if k != "ref"}))
        elif g == "url":
            out.append(Span(m.group("url"), link=m.group("url"), **{k: v for k, v in base.items() if k != "link"}))
        pos = m.end()
    plain(text[pos:])
    return out


# ── blocks ────────────────────────────────────────────────────────────────────

_FENCE_RE   = re.compile(r"^\s*(```+|~~~+)\s*([\w+#.-]*)\s*$")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_HR_RE      = re.compile(r"^\s*([-*_])(\s*\1){2,}\s*$")
_UL_RE      = re.compile(r"^(\s*)[-*+]\s+(.*)$")
_OL_RE      = re.compile(r"^(\s*)(\d+)[.)]\s+(.*)$")
_QUOTE_RE   = re.compile(r"^\s*>\s?(.*)$")
_IMG_RE     = re.compile(r"^\s*!\[(?P<alt>[^\]]*)\]\((?P<src>[^\s)]+)(?:\s+\"[^\"]*\")?\)"
                         r"(?:\{(?P<attrs>[^}]*)\})?\s*$")
_MATH_OPEN_RE = re.compile(r"^\s*\$\$(.*)$")
_TASK_RE    = re.compile(r"^\[( |x|X)\]\s+(.*)$")
_TABLE_SEP_RE = re.compile(r"^\s*\|?\s*:?-{1,}:?\s*(\|\s*:?-{1,}:?\s*)*\|?\s*$")


def _split_row(line: str) -> list[str]:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|") and not s.endswith("\\|"):
        s = s[:-1]
    cells, cur, i = [], "", 0
    while i < len(s):
        if s[i] == "\\" and i + 1 < len(s) and s[i + 1] == "|":
            cur += "|"
            i += 2
            continue
        if s[i] == "|":
            cells.append(cur.strip())
            cur = ""
        else:
            cur += s[i]
        i += 1
    cells.append(cur.strip())
    return cells


def parse(text: str) -> list[Block]:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    blocks: list[Block] = []
    para_buf: list[str] = []
    i = 0

    def flush():
        if para_buf:
            joined = " ".join(l.strip() for l in para_buf)
            blocks.append(Para(parse_inline(joined)))
            para_buf.clear()

    while i < len(lines):
        line = lines[i]
        if not line.strip():
            flush()
            i += 1
            continue
        m = _FENCE_RE.match(line)
        if m:
            flush()
            fence, lang = m.group(1), m.group(2)
            body = []
            i += 1
            while i < len(lines) and not re.match(r"^\s*" + re.escape(fence[0]) + "{" + str(len(fence)) + r",}\s*$", lines[i]):
                body.append(lines[i])
                i += 1
            i += 1
            blocks.append(CodeBlock("\n".join(body), lang))
            continue
        m = _MATH_OPEN_RE.match(line)
        if m:
            flush()
            rest = m.group(1)
            if rest.rstrip().endswith("$$"):                    # $$ … $$ в одну строку
                blocks.append(MathBlock(rest.rstrip()[:-2].strip()))
                i += 1
                continue
            body = [rest] if rest.strip() else []
            i += 1
            while i < len(lines) and "$$" not in lines[i]:
                body.append(lines[i])
                i += 1
            if i < len(lines):
                body.append(lines[i].split("$$")[0])
                i += 1
            blocks.append(MathBlock(" ".join(x.strip() for x in body if x.strip())))
            continue
        m = _IMG_RE.match(line)
        if m:
            flush()
            width, align = None, None
            for a in (m.group("attrs") or "").replace(",", " ").split():
                k, _, v = a.partition("=")
                if k == "width" and v:
                    try:
                        width = float(v.lower().replace("cm", "").replace("см", ""))
                    except ValueError:
                        pass
                elif k == "align" and v in ("left", "center", "right"):
                    align = v
            blocks.append(ImgBlock(m.group("src"), m.group("alt"), width, align))
            i += 1
            continue
        if _HR_RE.match(line) and not _UL_RE.match(line):
            flush()
            blocks.append(Hr())
            i += 1
            continue
        m = _HEADING_RE.match(line)
        if m:
            flush()
            blocks.append(Para(parse_inline(m.group(2)), kind=f"h{len(m.group(1))}"))
            i += 1
            continue
        if "|" in line and i + 1 < len(lines) and _TABLE_SEP_RE.match(lines[i + 1]) and "|" in lines[i + 1]:
            flush()
            header = _split_row(line)
            seps = _split_row(lines[i + 1])
            align = []
            for s in seps:
                s = s.strip()
                align.append("center" if s.startswith(":") and s.endswith(":") else
                             "right" if s.endswith(":") else "left")
            rows = [[parse_inline(c) for c in header]]
            i += 2
            while i < len(lines) and "|" in lines[i] and lines[i].strip():
                cells = _split_row(lines[i])
                cells += [""] * (len(header) - len(cells))
                rows.append([parse_inline(c) for c in cells[:len(header)]])
                i += 1
            blocks.append(TableBlock(rows, True, align))
            continue
        m = _QUOTE_RE.match(line)
        if m:
            flush()
            q = []                                  # (глубина, строка)
            while i < len(lines) and _QUOTE_RE.match(lines[i]):
                rest, depth = _QUOTE_RE.match(lines[i]).group(1), 1
                while (mm := _QUOTE_RE.match(rest)) is not None:   # вложенные «> >»
                    rest, depth = mm.group(1), depth + 1
                q.append((depth, rest.strip()))
                i += 1
            # строки одной глубины подряд — один абзац; смена глубины начинает новый
            for depth, group in groupby(q, key=lambda x: x[0]):
                text = " ".join(x for _, x in group if x)
                if text:
                    blocks.append(Para(parse_inline(text), kind="quote", level=depth - 1))
            continue
        m_ul, m_ol = _UL_RE.match(line), _OL_RE.match(line)
        if m_ul or m_ol:
            flush()
            while i < len(lines):
                m_ul, m_ol = _UL_RE.match(lines[i]), _OL_RE.match(lines[i])
                if not (m_ul or m_ol):
                    break
                indent = len((m_ul or m_ol).group(1).replace("\t", "    "))
                level = min(indent // 2, 3) if indent else 0
                body = m_ul.group(2) if m_ul else m_ol.group(3)
                t = _TASK_RE.match(body)
                if t:
                    body = ("☑ " if t.group(1).lower() == "x" else "☐ ") + t.group(2)
                i += 1
                # продолжение пункта — строки с отступом, не начинающиеся новым пунктом
                while i < len(lines) and lines[i].strip() and lines[i].startswith((" ", "\t")) \
                        and not _UL_RE.match(lines[i]) and not _OL_RE.match(lines[i]):
                    body += " " + lines[i].strip()
                    i += 1
                blocks.append(Para(parse_inline(body), kind="ul" if m_ul else "ol", level=level,
                                   ordered_start=int(m_ol.group(2)) if m_ol else 1))
            continue
        para_buf.append(line)
        i += 1
    flush()
    return blocks
