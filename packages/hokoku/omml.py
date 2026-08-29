"""
omml — LaTeX-подобная запись формул → OMML (нативные формулы Word).

Поддерживается то, что реально пишут в отчётах:
  a^2, x_i, x_{i+1}, \\frac{a}{b}, \\sqrt{x}, \\sqrt[n]{x}, \\sum_{i=1}^{n}, \\prod, \\int_a^b,
  \\lim_{x \\to 0}, \\left( … \\right), \\{ … \\}, |x|, греческие буквы (\\alpha … \\Omega),
  \\cdot \\times \\pm \\mp \\leq \\geq \\neq \\approx \\infty \\to \\rightarrow \\partial \\nabla
  \\in \\notin \\subset \\forall \\exists \\ldots \\cdots, \\vec{a}, \\hat{x}, \\bar{x}, \\dot{x},
  \\overline{x}, \\text{…}, \\mathrm{…}, \\sin \\cos \\tg \\ln \\log \\exp \\max \\min.
Неизвестная команда → её имя как текст (формула не падает).
"""
from __future__ import annotations

from xml.sax.saxutils import escape

M = "http://schemas.openxmlformats.org/officeDocument/2006/math"

_GREEK = {
    "alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ", "epsilon": "ε", "varepsilon": "ε",
    "zeta": "ζ", "eta": "η", "theta": "θ", "vartheta": "ϑ", "iota": "ι", "kappa": "κ",
    "lambda": "λ", "mu": "μ", "nu": "ν", "xi": "ξ", "pi": "π", "rho": "ρ", "sigma": "σ",
    "tau": "τ", "upsilon": "υ", "phi": "φ", "varphi": "φ", "chi": "χ", "psi": "ψ", "omega": "ω",
    "Gamma": "Γ", "Delta": "Δ", "Theta": "Θ", "Lambda": "Λ", "Xi": "Ξ", "Pi": "Π",
    "Sigma": "Σ", "Upsilon": "Υ", "Phi": "Φ", "Psi": "Ψ", "Omega": "Ω",
}
_SYMBOLS = {
    "cdot": "·", "times": "×", "pm": "±", "mp": "∓", "leq": "≤", "le": "≤", "geq": "≥", "ge": "≥",
    "neq": "≠", "ne": "≠", "approx": "≈", "equiv": "≡", "infty": "∞", "to": "→", "rightarrow": "→",
    "leftarrow": "←", "Rightarrow": "⇒", "Leftrightarrow": "⇔", "partial": "∂", "nabla": "∇",
    "in": "∈", "notin": "∉", "subset": "⊂", "subseteq": "⊆", "cup": "∪", "cap": "∩",
    "forall": "∀", "exists": "∃", "ldots": "…", "cdots": "⋯", "dots": "…", "prime": "′",
    "deg": "°", "circ": "∘", "sim": "∼", "propto": "∝", "angle": "∠", "perp": "⊥",
    "parallel": "∥", "emptyset": "∅", "hbar": "ℏ", "Re": "ℜ", "Im": "ℑ", "quad": "  ",
    "qquad": "    ", ",": " ", ";": " ", " ": " ", "!": "",
}
_FUNCS = {"sin", "cos", "tg", "tan", "ctg", "cot", "ln", "log", "lg", "exp", "max", "min",
          "arcsin", "arccos", "arctg", "arctan", "sh", "ch", "th", "det", "dim", "gcd", "mod"}
_BIG = {"sum": "∑", "prod": "∏", "int": "∫", "iint": "∬", "oint": "∮", "bigcup": "⋃", "bigcap": "⋂"}
_ACCENTS = {"vec": "⃗", "hat": "̂", "bar": "̄", "dot": "̇", "ddot": "̈", "tilde": "̃"}
_BRACKETS = {"(": ")", "[": "]", "\\{": "\\}", "|": "|", "\\langle": "\\rangle", "\\lfloor": "\\rfloor",
             "\\lceil": "\\rceil", ".": "."}
_BR_CHARS = {"\\{": "{", "\\}": "}", "\\langle": "⟨", "\\rangle": "⟩", "\\lfloor": "⌊", "\\rfloor": "⌋",
             "\\lceil": "⌈", "\\rceil": "⌉", "|": "|", ".": ""}


# ── токенизация ───────────────────────────────────────────────────────────────

_TEXT_CMDS = ("text", "mathrm", "textbf", "mathbf", "operatorname", "mbox")


def _tokens(s: str) -> list[str]:
    out, i = [], 0
    while i < len(s):
        c = s[i]
        if c == "\\":
            j = i + 1
            if j < len(s) and s[j].isalpha():
                while j < len(s) and s[j].isalpha():
                    j += 1
            else:
                j += 1
            name = s[i + 1:j]
            if name in _TEXT_CMDS and j < len(s) and s[j] == "{":     # \text{…} — сырой текст
                depth, k = 1, j + 1
                while k < len(s) and depth:
                    depth += (s[k] == "{") - (s[k] == "}")
                    k += 1
                out.append("\x00" + s[j + 1:k - 1])
                i = k
                continue
            out.append(s[i:j])
            i = j
        elif c.isspace():
            i += 1
        elif c.isdigit():
            j = i
            while j < len(s) and (s[j].isdigit() or s[j] in ".,") and not (s[j] in ".," and (j + 1 >= len(s) or not s[j + 1].isdigit())):
                j += 1
            out.append(s[i:j])
            i = j
        else:
            out.append(c)
            i += 1
    return out


# ── разбор в дерево: список узлов ─────────────────────────────────────────────
# узел: ("r", text) | ("sup", base, sup) | ("sub", base, sub) | ("subsup", base, sub, sup)
#       ("frac", num, den) | ("rad", deg|None, body) | ("nary", char, sub, sup, body)
#       ("delim", open, close, body) | ("acc", char, body) | ("bar", body) | ("func", name, arg)

class OmmlError(ValueError):
    """Формулу не удалось разобрать: незакрытая скобка, нет аргумента, окружение."""


class _Parser:
    def __init__(self, s: str):
        self.t = _tokens(s)
        self.i = 0

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else None

    def next(self):
        tok = self.peek()
        self.i += 1
        return tok

    def parse(self, stop=()) -> list:
        nodes = []
        while self.peek() is not None and self.peek() not in stop:
            node = self.atom()
            if node is None:
                continue
            node = self.scripts(node)
            nodes.append(node)
        return nodes

    def group(self) -> list:
        """{…} или один атом. Незакрытая группа — ошибка: раньше `\\frac{1}{` собирался
        молча в дробь с пустым знаменателем, и формула тихо пропадала из отчёта."""
        if self.peek() == "{":
            self.next()
            body = self.parse(stop=("}",))
            if self.peek() != "}":
                raise OmmlError("не закрыта фигурная скобка")
            self.next()
            return body
        node = self.atom()
        if node is None:
            raise OmmlError("не хватает аргумента после команды")
        return [node]

    def scripts(self, base):
        sub = sup = None
        while self.peek() in ("^", "_"):
            op = self.next()
            arg = self.group()
            if op == "^":
                sup = arg
            else:
                sub = arg
        if sub is None and sup is None:
            return base
        if base[0] == "nary":
            return ("nary", base[1], sub, sup, base[4])
        if sub is not None and sup is not None:
            return ("subsup", [base], sub, sup)
        return ("sup", [base], sup) if sup is not None else ("sub", [base], sub)

    def atom(self):
        tok = self.next()
        if tok is None:
            return None
        if tok == "{":
            body = self.parse(stop=("}",))
            if self.peek() != "}":
                raise OmmlError("не закрыта фигурная скобка")
            self.next()
            return ("grp", body)
        if tok == "}":
            return None
        if tok.startswith("\x00"):
            return ("r", tok[1:])
        if tok in ("^", "_"):
            return ("r", tok)
        if tok == "\\left":
            op = self.next()
            body = self.parse(stop=("\\right",))
            self.next()
            cl = self.next() or ""
            return ("delim", _BR_CHARS.get(op, op), _BR_CHARS.get(cl, cl), body)
        if tok in ("(", "[", "\\{", "\\langle", "\\lfloor", "\\lceil"):
            close = _BRACKETS[tok]
            body = self.parse(stop=(close,))
            if self.peek() == close:
                self.next()
            return ("delim", _BR_CHARS.get(tok, tok), _BR_CHARS.get(close, close), body)
        if tok == "|":
            body = self.parse(stop=("|",))
            if self.peek() == "|":
                self.next()
            return ("delim", "|", "|", body)
        if tok.startswith("\\"):
            name = tok[1:]
            if name == "frac":
                return ("frac", self.group(), self.group())
            if name == "sqrt":
                deg = None
                if self.peek() == "[":
                    self.next()
                    deg = self.parse(stop=("]",))
                    self.next()
                return ("rad", deg, self.group())
            if name in _BIG:
                return ("nary", _BIG[name], None, None, None)
            if name == "lim":
                return ("nary", "lim", None, None, None)
            if name in _ACCENTS:
                return ("acc", _ACCENTS[name], self.group())
            if name in ("overline", "bar"):
                return ("bar", self.group())
            if name in _TEXT_CMDS:
                return ("r", "")
            if name in _FUNCS:
                return ("func", name, self.group() if self.peek() == "{" else [])
            if name in _GREEK:
                return ("r", _GREEK[name])
            if name in _SYMBOLS:
                return ("r", _SYMBOLS[name])
            if name in ("\\",):
                return ("r", " ")
            if name in ("begin", "end"):                     # \\begin{matrix} рассыпался в буквы
                raise OmmlError(f"окружения не поддерживаются: \\{name}")
            return ("r", name)                               # неизвестная команда — текстом
        if tok in ("*",):
            return ("r", "∗")
        return ("r", tok)


# ── OMML ──────────────────────────────────────────────────────────────────────

def _r(text: str, style: str | None = None) -> str:
    if text == "":
        return ""
    rpr = f'<m:rPr><m:sty m:val="{style}"/></m:rPr>' if style else ""
    return f'<m:r>{rpr}<m:t xml:space="preserve">{escape(text)}</m:t></m:r>'


def _e(nodes) -> str:
    return "".join(_node(n) for n in nodes)


def _node(n) -> str:
    k = n[0]
    if k == "r":
        return _r(n[1])
    if k == "grp":
        return _e(n[1])
    if k == "func":
        _, name, arg = n
        body = f'<m:fName>{_r(name, "p")}</m:fName><m:e>{_e(arg) if arg else ""}</m:e>'
        return f"<m:func>{body}</m:func>" if arg else _r(name, "p")
    if k == "sup":
        return f"<m:sSup><m:e>{_e(n[1])}</m:e><m:sup>{_e(n[2])}</m:sup></m:sSup>"
    if k == "sub":
        return f"<m:sSub><m:e>{_e(n[1])}</m:e><m:sub>{_e(n[2])}</m:sub></m:sSub>"
    if k == "subsup":
        return (f"<m:sSubSup><m:e>{_e(n[1])}</m:e><m:sub>{_e(n[2])}</m:sub>"
                f"<m:sup>{_e(n[3])}</m:sup></m:sSubSup>")
    if k == "frac":
        return f"<m:f><m:num>{_e(n[1])}</m:num><m:den>{_e(n[2])}</m:den></m:f>"
    if k == "rad":
        deg = f"<m:deg>{_e(n[1])}</m:deg>" if n[1] else '<m:radPr><m:degHide m:val="1"/></m:radPr><m:deg/>'
        return f"<m:rad>{deg}<m:e>{_e(n[2])}</m:e></m:rad>"
    if k == "nary":
        _, ch, sub, sup, body = n
        if ch == "lim":
            # предел — это функция с именем-пределом: <m:func><m:fName><m:limLow>…</m:fName><m:e>тело.
            # Голый limLow с телом-соседом Word и LibreOffice рисуют как общую дробь:
            # «lim_{x→0} \frac{sin x}{x}» выходит «(lim sin x)/x», то есть формула читается неверно.
            fname = f"<m:limLow><m:e>{_r('lim', 'p')}</m:e><m:lim>{_e(sub or [])}</m:lim></m:limLow>"
            tail = _e(sup) if sup else ""
            if body:
                return f"<m:func><m:fName>{fname}</m:fName><m:e>{_e(body)}</m:e></m:func>{tail}"
            return fname + tail
        pr = f'<m:naryPr><m:chr m:val="{ch}"/><m:limLoc m:val="undOvr"/>'
        pr += ('<m:subHide m:val="1"/>' if sub is None else "") + ('<m:supHide m:val="1"/>' if sup is None else "") + "</m:naryPr>"
        return (f"<m:nary>{pr}<m:sub>{_e(sub or [])}</m:sub><m:sup>{_e(sup or [])}</m:sup>"
                f"<m:e>{_e(body or [])}</m:e></m:nary>")
    if k == "delim":
        _, op, cl, body = n
        pr = f'<m:dPr><m:begChr m:val="{escape(op)}"/><m:endChr m:val="{escape(cl)}"/></m:dPr>'
        return f"<m:d>{pr}<m:e>{_e(body)}</m:e></m:d>"
    if k == "acc":
        return f'<m:acc><m:accPr><m:chr m:val="{n[1]}"/></m:accPr><m:e>{_e(n[2])}</m:e></m:acc>'
    if k == "bar":
        return f'<m:bar><m:barPr><m:pos m:val="top"/></m:barPr><m:e>{_e(n[1])}</m:e></m:bar>'
    return ""


def _descend(n: tuple) -> tuple:
    """Тот же узел, но со вложенными списками, пропущенными через _attach_bodies:
    сумма внутри дроби или под корнем — такой же оператор, как на верхнем уровне."""
    return tuple(_attach_bodies(x) if isinstance(x, list) else x for x in n)


def _attach_bodies(nodes: list) -> list:
    """Для ∑/∫: следующий за оператором фрагмент до знака +/-/=/, — тело оператора."""
    out, i = [], 0
    while i < len(nodes):
        n = _descend(nodes[i])
        if n[0] == "nary" and n[4] is None:
            body, j = [], i + 1
            while j < len(nodes) and not (nodes[j][0] == "r" and nodes[j][1] in ("+", "-", "=", ",", "±", "→", "≤", "≥", "<", ">")):
                body.append(nodes[j])
                j += 1
            out.append(("nary", n[1], n[2], n[3], _attach_bodies(body)))
            i = j
        else:
            out.append(n)
            i += 1
    return out


def latex_to_omml(latex: str, display: bool = False) -> str:
    """OMML-строка <m:oMath>…</m:oMath> (для display — внутри <m:oMathPara>)."""
    nodes = _attach_bodies(_Parser(latex).parse())
    inner = f'<m:oMath xmlns:m="{M}">{_e(nodes)}</m:oMath>'
    if display:
        return f'<m:oMathPara xmlns:m="{M}"><m:oMathParaPr><m:jc m:val="center"/></m:oMathParaPr>{inner}</m:oMathPara>'
    return inner


def omml_element(latex: str, display: bool = False):
    from docx.oxml import parse_xml
    return parse_xml(latex_to_omml(latex, display))
