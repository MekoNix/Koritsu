"""tasm.py — сообщения TASM/TLINK, листинг `.lst` и таблица символов.

Разбор написан по документации Borland (TASM 4.x/5.x, TLINK 7.x) и сделан терпимым: строка,
которая не узнана, пропускается, а не роняет сборку. Форматы у версий расходятся в мелочах —
табуляции против пробелов, `**Error**` против `**Fatal**`, лишний столбец уровня вложенности
у строк из `include` и макросов, — и отказ на незнакомой строке означал бы, что человек не
увидит ни одной ошибки из-за одной непонятной.

Сообщения TASM:

    **Error** prog.asm(5) Undefined symbol: X
    *Warning* prog.asm(7) Argument needs type override
    **Fatal** prog.asm(12) Unexpected end of file encountered
    **Error** prog.asm(20) MYMACRO(3) Illegal instruction

Сообщения TLINK:

    Error: Undefined symbol FOO in module PROG.ASM
    Warning: No stack
    Fatal: Unable to open file 'prog.obj'

Строка листинга TASM: номер строки, необязательный уровень вложенности, смещение (4 или 8 hex),
байты (слова — четырьмя знаками, с пометками поправок `r`, `s`, `e`, `+` — перенос на следующую
строку листинга), затем текст исходника после табуляций:

          7  0000  B8 0000s             mov ax, @data
         10  0007  BA 0000r             mov dx, offset msg
         11  000A  CD 21                int 21h
"""
from __future__ import annotations

import re

from .model import BuildMessage, ListingLine, Symbol

# ── сообщения ────────────────────────────────────────────────────────────────

_TASM_MSG = re.compile(r"^\s*\*+\s*(Error|Warning|Fatal)\s*\*+\s*(.*)$", re.I)
_TASM_LOC = re.compile(r"^(?P<file>[^\s()]+)\((?P<line>\d+)\)\s*(?P<text>.*)$")
_TLINK_MSG = re.compile(r"^\s*(Error|Warning|Fatal)\s*:\s*(.*)$", re.I)


def _severity(word: str) -> str:
    return "warning" if word.lower() == "warning" else "error"


def tasm_messages(text: str, source_name: str = "PROG.ASM") -> list[BuildMessage]:
    """Сообщения TASM. Номер строки ставится только для основного файла: у сообщения из
    `include` номер чужого файла, и подсветить его в редакторе значило бы соврать."""
    out: list[BuildMessage] = []
    for raw in text.splitlines():
        m = _TASM_MSG.match(raw)
        if not m:
            continue
        severity, rest = _severity(m.group(1)), m.group(2).strip()
        line = None
        loc = _TASM_LOC.match(rest)
        if loc:
            if loc.group("file").upper().endswith(source_name.upper()):
                line = int(loc.group("line"))
                rest = loc.group("text").strip()
        out.append(BuildMessage(severity=severity, tool="tasm", line=line, text=rest))
    return out


def tlink_messages(text: str) -> list[BuildMessage]:
    out: list[BuildMessage] = []
    for raw in text.splitlines():
        m = _TLINK_MSG.match(raw)
        if m:
            out.append(BuildMessage(severity=_severity(m.group(1)), tool="tlink", line=None,
                                    text=m.group(2).strip()))
    return out


# ── листинг ──────────────────────────────────────────────────────────────────

# Номер, уровень вложенности (цифра, за которой пробел), смещение. Смещение признаётся
# только сразу за номером — одной табуляцией или парой пробелов: текст исходника стоит
# дальше, за несколькими табуляциями, и метка вроде `ADD1` на его месте смещением не станет.
_LST_LINE = re.compile(
    r"^\s*(?P<n>\d+)"
    r"(?:[ ]+(?P<level>\d{1,2})(?=[ \t]))?"
    r"(?:(?:\t|[ ]{1,3})(?P<off>[0-9A-F]{8}|[0-9A-F]{4})(?=[ \t]|$))?"
    r"(?P<rest>.*)$")
_BYTES_RUN = re.compile(r"^[ ]{1,2}(?P<b>\S+(?: \S+)*)")
_BYTE_TOKEN = re.compile(r"^[0-9A-F?]*(?:\*?\(?[0-9A-F?]*\)?)*[rsefuci+]*$")


def _bytes_ok(run: str) -> bool:
    return all(_BYTE_TOKEN.match(tok) for tok in run.split(" "))


class _Segments:
    """Какой сегмент открыт на строке листинга — по директивам в тексте.

    В самом листинге сегмента у строки нет; без него смещение `0000` есть и у первой
    команды, и у первой переменной. Имена — те, что упрощённые директивы дают у Borland:
    `_TEXT`, `_DATA`, `_BSS`, `CONST`, `STACK`, для моделей medium и выше код — `<ИМЯ>_TEXT`.
    """

    _SIMPLE = [
        (re.compile(r"^\.data\?", re.I), "_BSS"),
        (re.compile(r"^udataseg\b", re.I), "_BSS"),
        (re.compile(r"^\.data\b", re.I), "_DATA"),
        (re.compile(r"^dataseg\b", re.I), "_DATA"),
        (re.compile(r"^\.const\b", re.I), "CONST"),
        (re.compile(r"^\.stack\b", re.I), "STACK"),
        (re.compile(r"^\.fardata\?", re.I), "FAR_BSS"),
        (re.compile(r"^\.fardata\b", re.I), "FAR_DATA"),
    ]
    _CODE = re.compile(r"^(?:\.code|codeseg)\b(?:\s+(?P<name>[\w@$?]+))?", re.I)
    _MODEL = re.compile(r"^(?:\.model|model)\s+(?:\w+\s+)?(?P<m>tiny|small|compact|medium|large|huge|tchuge|flat)\b", re.I)
    _SEG_MASM = re.compile(r"^(?P<name>[\w@$?]+)\s+segment\b", re.I)
    _SEG_IDEAL = re.compile(r"^segment\s+(?P<name>[\w@$?]+)", re.I)
    _ENDS = re.compile(r"^(?:[\w@$?]+\s+ends\b|ends\b)", re.I)

    def __init__(self, module: str = "PROG") -> None:
        self.module = module.upper()
        self.model = "small"
        self.stack: list[str] = []
        self.current: str | None = None

    def before(self, text: str) -> str | None:
        """Сегмент, к которому относится строка с этим текстом."""
        t = text.split(";", 1)[0].strip()
        if not t:
            return self.current
        m = self._MODEL.match(t)
        if m:
            self.model = m.group("m").lower()
            return self.current
        m = self._CODE.match(t)
        if m:
            name = m.group("name")
            if not name:
                name = "_TEXT" if self.model in ("tiny", "small", "compact", "flat") \
                    else f"{self.module}_TEXT"
            self.current = name.upper()
            self.stack = []
            return self.current
        for pattern, name in self._SIMPLE:
            if pattern.match(t):
                self.current = name
                self.stack = []
                return self.current
        m = self._SEG_MASM.match(t) or self._SEG_IDEAL.match(t)
        if m:
            if self.current:
                self.stack.append(self.current)
            self.current = m.group("name").upper()
            return self.current
        if self._ENDS.match(t):
            seg = self.current
            self.current = self.stack.pop() if self.stack else None
            return seg
        return self.current


# Строка листинга TASM после раскрытия табуляций (шаг 8) стоит по столбцам: уровень
# вложенности (цифра в первом столбце у строк раскрытия макроса), номер строки листинга,
# смещение с 8-го столбца, байты с 14-го, исходник — с 37-го (у 32-битных сегментов смещение
# длиннее, поэтому столбец исходника ищется по файлу).
_LST_NUM = re.compile(r"^(?P<level>\d)?\s*(?P<n>\d+)\s*$")
_LST_OFF = re.compile(r"^(?P<off>[0-9A-F]{8}|[0-9A-F]{4})(?=\s|$)")
_SRC_COL_DEFAULT = 37


def _source_column(lines: list[str]) -> int:
    """Столбец, с которого в этом листинге начинается текст исходника.

    TASM ставит исходник на пять пробелов за табуляционной остановкой. Отступ самого
    исходника TASM сжимает в табуляцию, поэтому у строк с отступом текст начинается дальше —
    столбец определяют пять пробелов, а не первый символ текста. Берётся первая остановка,
    за которой пять пробелов у большинства строк: строки, чьи байты залезли в столбец
    (`07+  long`), в меньшинстве.
    """
    for stop in (32, 40, 48):
        long_rows = [ex for ex in lines if len(ex) > stop + 5]
        if not long_rows:
            continue
        spaced = sum(1 for ex in long_rows if ex[stop:stop + 5] == "     ")
        if spaced * 10 >= len(long_rows) * 6:
            return stop + 5
    return _SRC_COL_DEFAULT


def parse_listing(text: str, module: str = "PROG") -> list[ListingLine]:
    """`.lst` → строки исходника с сегментом, смещением и байтами.

    **Номер в листинге — это номер строки листинга, а не исходника.** Байты, не влезшие в
    свой столбец, TASM переносит на следующую строку листинга со своим номером (прошлые байты
    кончаются `+`), а раскрытие макроса добавляет строки с уровнем вложенности. Поэтому
    `ListingLine.line` считается заново: переносы байтов приклеиваются к своей строке, строки
    раскрытия относятся к строке, где макрос вызван, остальные идут по порядку исходника.
    Таблица символов в конце файла сюда не входит: она начинается строкой `Symbol Table`.
    """
    rows: list[str] = []
    for raw in text.replace("\f", "\n").splitlines():
        if raw.strip().lower().startswith("symbol table"):
            break
        ex = raw.expandtabs(8)
        if _LST_NUM.match(ex[:8] if len(ex) >= 8 else ex):
            rows.append(ex)
    src_col = _source_column(rows)

    out: list[ListingLine] = []
    segs = _Segments(module)
    source_line = 0
    for ex in rows:
        head = _LST_NUM.match(ex[:8] if len(ex) >= 8 else ex)
        level = head.group("level") if head else None
        middle = ex[8:src_col] if len(ex) > 8 else ""
        text_part = ex[src_col:].strip() if len(ex) > src_col else ""
        # Смещение стоит вплотную к 8-му столбцу; у переносов байтов и строк без кода там пробелы.
        m = _LST_OFF.match(middle)
        off = m.group("off") if m else None
        run = middle[m.end():].strip() if m else middle.strip()
        run = " ".join(run.split())
        if run and not _bytes_ok(run):
            # Не байты — значит, строка без столбцов (например, короткая пустая): весь хвост
            # за номером считается исходником.
            text_part = (middle + text_part).strip() if not text_part else text_part
            run = ""

        prev = out[-1] if out else None
        if off is None and run and not text_part and prev is not None and prev.bytes.endswith("+"):
            prev.bytes = (prev.bytes[:-1].rstrip() + " " + run).strip()
            continue

        if level:
            line = source_line or 1
        else:
            source_line += 1
            line = source_line
        segment = segs.before(text_part)
        out.append(ListingLine(line=line, segment=segment, offset=off, bytes=run, text=text_part))
    return out


# ── таблица символов ─────────────────────────────────────────────────────────

_SIZES = {"byte": 1, "word": 2, "dword": 4, "fword": 6, "pword": 6, "qword": 8, "tbyte": 10}
_VALUE = re.compile(r"^(?P<seg>[\w@$?]+):(?P<off>[0-9A-F]{4}(?:[0-9A-F]{4})?)$")


def parse_symbols(text: str) -> list[Symbol]:
    """Метки и переменные из таблицы символов листинга (`MSG  Byte  DGROUP:0000`).

    Служебные имена TASM (`??DATE`, `@CODE` …) и числа (`EQU`) пропускаются: у них нет
    адреса, а окно дампа и агент спрашивают именно адрес. `segment` — как в таблице: имя
    группы (`DGROUP`) или сегмента.
    """
    out: list[Symbol] = []
    inside = False
    for raw in text.replace("\f", "\n").splitlines():
        s = raw.strip()
        if not inside:
            if s.lower().startswith("symbol name"):
                inside = True
            continue
        if s.lower().startswith(("groups & segments", "error messages", "warning messages")):
            break
        if not s or s.startswith(("??", "@")) or s.lower().startswith(("turbo assembler", "symbol")):
            continue
        parts = [p for p in re.split(r"\t+| {2,}", s) if p]
        if len(parts) < 3:
            continue
        name, kind = parts[0], parts[1]
        value = _VALUE.match(parts[-1].strip())
        if not value:
            continue
        base = kind.split("[", 1)[0].strip().lower()
        count = 1
        arr = re.search(r"\[(\d+)\]", kind)
        if arr:
            count = int(arr.group(1))
        size = _SIZES.get(base)
        out.append(Symbol(name=name, segment=value.group("seg"), offset=value.group("off"),
                          kind=base, size=size * count if size else None))
    return out


__all__ = ["tasm_messages", "tlink_messages", "parse_listing", "parse_symbols"]
