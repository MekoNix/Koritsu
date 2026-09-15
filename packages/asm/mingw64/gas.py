"""gas.py — листинг GNU as (`as -a=prog.lst`): строки, секции, смещения, байты, символы.

Формат (binutils 2.44, `samples/lab.lst`, `samples/input.lst`):

    GAS LISTING lab.s 			page 1
    <пусто>
    <пусто>
       5 0000 00000000 	handle:     .quad   0
       5      00000000
      12 0067 00000000 	    .text
      12      00000000
      12      00
      13              	main:
      14 0000 55       	    push    rbp

- Первое число — **номер строки исходника** (`% 4d`), а не номер строки листинга: заголовки
  страниц (`\\f` и `GAS LISTING … page N` каждые 60 строк) и переносы байтов его не сдвигают.
  Строка без байтов — номер, пробелы и табуляция перед текстом.
- Дальше смещение от начала **секции** `prog.obj` (`%04x`, у больших секций шире). Если `as`
  нашёл ошибки, вместо смещения `????`.
- Байты — по 4 на строку; продолжение — строка с тем же номером, без смещения и без текста.
  Продолжений не больше четырёх (`--listing-cont-lines`), поэтому у `.space 64` в листинге 20
  байт из 64: длина куска считается до следующего смещения той же секции, а не по байтам.
- Байты с перемещениями показаны до компоновки (`E8000000 00` у `call`). Настоящие байты
  `build.py` берёт из образа.
- Текст справа режется по ширине столбца посреди символа UTF-8 — текст строки берётся из
  исходника, листинг даёт только номер, смещение и байты.
- В конце — `DEFINED SYMBOLS` (`lab.s:13  .text:0000000000000000 main`) и `UNDEFINED SYMBOLS`.

**Секция строки** в листинге не пишется: она выводится из директив исходника выше —
`.text`, `.data`, `.bss`, `.section`, `.pushsection`/`.popsection`, `.previous`. Байты на
строке с самой директивой относятся к секции **до** неё: это выравнивание, которое `as`
дописывает в конец прежней секции при переключении (`12 0067 00000000 .text` — хвост `.data`
до 0x70). Директивы внутри `.macro … .endm` не учитываются: они сработают при вызове, а вызов
в листинге не раскрыт.
"""
from __future__ import annotations

import bisect
import re
from dataclasses import dataclass, field

_HEADER = re.compile(r"^GAS LISTING ")
_FIRST = re.compile(r"^ *(?P<line>\d+) (?P<off>[0-9a-fA-F]{4,16}|\?{4}) (?P<bytes>[0-9A-Fa-f ]*)\t(?P<text>.*)$")
_PLAIN = re.compile(r"^ *(?P<line>\d+) {5,}\t(?P<text>.*)$")
_CONT = re.compile(r"^ *(?P<line>\d+) {6}(?P<bytes>[0-9A-Fa-f][0-9A-Fa-f ]*?) *$")
_SYMBOL = re.compile(r"^\s*(?:(?P<file>\S+):(?P<line>\d+))?\s+(?P<sec>\S+):(?P<val>[0-9a-fA-F]+) (?P<name>\S.*?)\s*$")
_LABEL = re.compile(r"^\s*[^\s\"',;#]+?:(?=\s|$)")


@dataclass
class GasLine:
    line: int                     # номер строки исходника
    section: str | None           # секция prog.obj ('.text', '.rdata$zzz'); None — до первой директивы не бывает
    offset: int | None            # смещение в секции; None — строка без байтов или `????`
    data: bytearray = field(default_factory=bytearray)
    text: str = ""                # текст из листинга (обрезан); исходник — у вызывающего


@dataclass(frozen=True)
class GasSymbol:
    name: str
    line: int | None
    section: str                  # '.text', '.data', '*ABS*', '*UND*', 'COMMON'
    value: int


@dataclass
class GasListing:
    lines: list[GasLine]
    symbols: list[GasSymbol]
    undefined: list[str]


# ── операторы и директивы ────────────────────────────────────────────────────

@dataclass
class _Scan:
    """Состояние чтения исходника по операторам: многострочный `/* */` и `.macro`."""
    in_comment: bool = False
    macro_depth: int = 0


def statements(line: str, scan: _Scan) -> list[str]:
    """Операторы строки GAS без комментариев: `#` до конца строки, `/* … */`, разделитель `;`
    (у x86 это разделитель операторов, а не комментарий). Строки в кавычках не режутся."""
    out: list[str] = []
    cur: list[str] = []
    i, n = 0, len(line)
    quote: str | None = None
    while i < n:
        ch = line[i]
        if scan.in_comment:
            end = line.find("*/", i)
            if end < 0:
                break
            scan.in_comment = False
            i = end + 2
            continue
        if quote:
            cur.append(ch)
            if ch == "\\" and i + 1 < n:
                cur.append(line[i + 1])
                i += 2
                continue
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch == '"':
            quote = ch
            cur.append(ch)
        elif ch == "'" and i + 1 < n:
            # Символьная константа `'a'` или `'a` — не строка до следующего апострофа.
            cur.append(line[i:i + 2])
            i += 2
            if i < n and line[i] == "'":
                cur.append("'")
                i += 1
            continue
        elif ch == "#":
            break
        elif ch == "/" and line.startswith("/*", i):
            scan.in_comment = True
            i += 2
            continue
        elif ch == ";":
            out.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
        i += 1
    out.append("".join(cur))
    return [s.strip() for s in out if s.strip()]


def head(statement: str) -> tuple[str, str]:
    """Первое слово оператора (без меток `x:` перед ним) и остаток."""
    rest = statement
    while True:
        m = _LABEL.match(rest)
        if not m:
            break
        rest = rest[m.end():]
    rest = rest.strip()
    if not rest:
        return "", ""
    parts = rest.split(None, 1)
    return parts[0], parts[1] if len(parts) > 1 else ""


def _section_name(args: str) -> str | None:
    args = args.strip()
    if not args:
        return None
    if args[0] == '"':
        end = args.find('"', 1)
        return args[1:end] if end > 0 else None
    return re.split(r"[\s,]", args, 1)[0] or None


class Sections:
    """Текущая секция по директивам исходника."""

    def __init__(self) -> None:
        self.current = ".text"
        self.previous = ".text"
        self.stack: list[tuple[str, str]] = []
        self.scan = _Scan()

    def _switch(self, name: str) -> None:
        self.previous, self.current = self.current, name

    def apply(self, source_line: str) -> None:
        for stmt in statements(source_line, self.scan):
            word, args = head(stmt)
            word = word.lower()
            if word == ".macro":
                self.scan.macro_depth += 1
                continue
            if word == ".endm":
                self.scan.macro_depth = max(0, self.scan.macro_depth - 1)
                continue
            if self.scan.macro_depth:
                continue
            if word in (".text", ".data", ".bss"):
                self._switch(word)
            elif word == ".section":
                name = _section_name(args)
                if name:
                    self._switch(name)
            elif word == ".pushsection":
                name = _section_name(args)
                if name:
                    self.stack.append((self.current, self.previous))
                    self._switch(name)
            elif word == ".popsection":
                if self.stack:
                    self.current, self.previous = self.stack.pop()
            elif word == ".previous":
                self.current, self.previous = self.previous, self.current


# ── листинг ──────────────────────────────────────────────────────────────────

def _hex_bytes(text: str) -> bytes:
    digits = text.replace(" ", "")
    if len(digits) % 2:
        digits = digits[:-1]
    try:
        return bytes.fromhex(digits)
    except ValueError:
        return b""


def parse_listing(text: str, source: str | None = None) -> GasListing:
    """Листинг `as -a=`. `source` — исходник: по нему идут секции (текст в листинге обрезан)."""
    src_lines = source.split("\n") if source is not None else None
    sections = Sections()
    applied = 0                     # строки исходника до этой включительно уже учтены

    def catch_up(upto: int) -> None:
        nonlocal applied
        if src_lines is None:
            return
        while applied < upto:
            applied += 1
            if applied <= len(src_lines):
                sections.apply(src_lines[applied - 1])

    lines: list[GasLine] = []
    symbols: list[GasSymbol] = []
    undefined: list[str] = []
    mode = "lines"
    last: GasLine | None = None

    for raw in text.split("\n"):
        row = raw.rstrip("\r").lstrip("\f")
        if _HEADER.match(row):
            continue
        stripped = row.strip()
        if stripped in ("DEFINED SYMBOLS", "NO DEFINED SYMBOLS"):
            mode = "symbols"
            continue
        if stripped in ("UNDEFINED SYMBOLS", "NO UNDEFINED SYMBOLS"):
            mode = "undefined"
            continue
        if mode == "symbols":
            m = _SYMBOL.match(row)
            if m:
                symbols.append(GasSymbol(name=m.group("name"),
                                         line=int(m.group("line")) if m.group("line") else None,
                                         section=m.group("sec"), value=int(m.group("val"), 16)))
            continue
        if mode == "undefined":
            if stripped:
                undefined.append(stripped)
            continue

        m = _FIRST.match(row)
        if m:
            n = int(m.group("line"))
            catch_up(n - 1)
            off = m.group("off")
            data = _hex_bytes(m.group("bytes"))
            entry = GasLine(line=n, section=sections.current,
                            offset=None if off.startswith("?") else int(off, 16),
                            data=bytearray(data), text=m.group("text"))
            lines.append(entry)
            last = entry
            if src_lines is None:
                sections.apply(entry.text)
            else:
                catch_up(n)
            continue
        m = _PLAIN.match(row)
        if m:
            n = int(m.group("line"))
            catch_up(n - 1)
            entry = GasLine(line=n, section=sections.current, offset=None, text=m.group("text"))
            lines.append(entry)
            last = entry
            if src_lines is None:
                sections.apply(entry.text)
            else:
                catch_up(n)
            continue
        m = _CONT.match(row)
        if m and last is not None and int(m.group("line")) == last.line:
            last.data.extend(_hex_bytes(m.group("bytes")))
            continue
    return GasListing(lines=lines, symbols=symbols, undefined=undefined)


# ── строка по адресу ─────────────────────────────────────────────────────────

class LineIndex:
    """Строка исходника по смещению в секции `prog.obj` или по VA образа.

    Кусок строки — от её смещения до смещения следующей строки с байтами в той же секции; у
    последней — до конца её байтов. Так `.space 64` занимает все 64 байта, хотя в листинге их
    20, а выравнивание перед сменой секции достаётся строке, которая его породила.
    """

    def __init__(self, lines: list[GasLine], bases: dict[str, int] | None = None) -> None:
        per: dict[str, list[tuple[int, int, int]]] = {}
        for ln in lines:
            if ln.offset is None or not ln.data or ln.section is None:
                continue
            per.setdefault(ln.section, []).append((ln.offset, len(ln.data), ln.line))
        self.sections: dict[str, tuple[list[int], list[int], list[int]]] = {}
        for sec, items in per.items():
            items.sort(key=lambda t: t[0])
            starts, ends, nums = [], [], []
            for k, (off, size, num) in enumerate(items):
                if starts and starts[-1] == off:
                    continue                       # первая строка на смещении выигрывает
                nxt = next((o for o, _, _ in items[k + 1:] if o > off), None)
                starts.append(off)
                ends.append(nxt if nxt is not None else off + size)
                nums.append(num)
            self.sections[sec] = (starts, ends, nums)
        self.bases = dict(bases or {})

    def end(self, section: str) -> int:
        entry = self.sections.get(section)
        return entry[1][-1] if entry and entry[1] else 0

    def at_offset(self, section: str, offset: int) -> int | None:
        entry = self.sections.get(section)
        if entry is None:
            return None
        starts, ends, nums = entry
        k = bisect.bisect_right(starts, offset) - 1
        if k >= 0 and offset < ends[k]:
            return nums[k]
        return None

    def at(self, va: int | None) -> int | None:
        if va is None:
            return None
        for sec, base in self.bases.items():
            if base <= va < base + self.end(sec):
                line = self.at_offset(sec, va - base)
                if line is not None:
                    return line
        return None


__all__ = ["GasLine", "GasSymbol", "GasListing", "LineIndex", "Sections", "parse_listing",
           "statements", "head"]
