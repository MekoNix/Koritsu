"""debugx.py — разбор вывода DebugX, перенаправленного в файл. Потоком.

Формат снят с настоящего DebugX 2.51 в DOSBox-X (`samples/`). Что в нём есть:

    -T                                                  эхо команды (приглашение `-`)
    Hi                                                  вывод программы на этом шаге
    AX=0924 BX=0000 CX=0120 DX=0000 SP=0100 BP=0000 SI=0000 DI=0000
    DS=0F75 ES=0F55 SS=0F85 CS=0F65 IP=000C NV UP EI PL ZR NA PE NC
    0F65:000C B401              MOV     AH,01           следующая команда (+ `DS:0010=00`)

После `RX` регистры печатаются тремя строками (`EAX=… EBP=`, `ESI=… EFL=… флаги`,
`DS=… GS=`). `T n` печатает блок после КАЖДОГО шага, эхо — одно на всю пачку. Вывод
программы без перевода строки приклеивается к строке регистров слева (`AAX=0241 …`), поэтому
строка регистров ищется с конца строки, а всё левее — вывод. Выход программы:
пустая строка и `Program terminated normally (0005)`. INT 3 в программе — строка
`Unexpected breakpoint interrupt` перед блоком, и пачка `T n` на этом обрывается.

Эхо узнаётся только в тех формах, в которых сценарий команды пишет (`T`, `T 400`, `R CX 4`,
`D 0F75:0000 L 40`, `RX`, `R`, `Q`): вывод программы, случайно похожий на команду, так
отличить нельзя, но похожий ровно на нашу команду — почти невозможно.

Разборщик ничего не решает про программу: он отдаёт блоки, дампы, выход и странности, а что с
ними делать — дело `runner`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

H4 = rb"[0-9A-F]{4}"
H8 = rb"[0-9A-F]{8}"
_FLAGS = rb"(NV|OV) (UP|DN) (EI|DI) (PL|NG) (NZ|ZR) (NA|AC) (PO|PE) (NC|CY)"

_R16_1 = re.compile(rb"AX=(" + H4 + rb") BX=(" + H4 + rb") CX=(" + H4 + rb") DX=(" + H4 +
                    rb") SP=(" + H4 + rb") BP=(" + H4 + rb") SI=(" + H4 + rb") DI=(" + H4 +
                    rb") ?$")
_R16_2 = re.compile(rb"^DS=(" + H4 + rb") ES=(" + H4 + rb") SS=(" + H4 + rb") CS=(" + H4 +
                    rb") IP=(" + H4 + rb") " + _FLAGS + rb" ?$")
_R32_1 = re.compile(rb"EAX=(" + H8 + rb") EBX=(" + H8 + rb") ECX=(" + H8 + rb") EDX=(" + H8 +
                    rb") ESP=(" + H8 + rb") EBP=(" + H8 + rb") ?$")
_R32_2 = re.compile(rb"^ESI=(" + H8 + rb") EDI=(" + H8 + rb") EIP=(" + H8 + rb") EFL=(" + H8 +
                    rb") " + _FLAGS + rb" ?$")
_R32_3 = re.compile(rb"^DS=(" + H4 + rb") ES=(" + H4 + rb") SS=(" + H4 + rb") CS=(" + H4 +
                    rb") FS=(" + H4 + rb") GS=(" + H4 + rb") ?$")
_DISASM = re.compile(rb"^([0-9A-F]{4}):([0-9A-F]{4,8}) ([0-9A-F]+) +(.*?) *$")
_MEMREF = re.compile(rb" {2,}(?:[A-Z]S:)?[0-9A-F]{4,8}=[0-9A-F]+$")
_DUMP = re.compile(rb"^([0-9A-F]{4}):([0-9A-F]{4}) ")
_ECHO = re.compile(rb"^!?[-#](T(?: [0-9A-F]{1,4})?|RX|R|R CX [0-9A-F]{1,4}|Q"
                   rb"|D [0-9A-F]{4}:[0-9A-F]{4} L [0-9A-F]{1,4})$")
_TERMINATED = re.compile(rb"Program terminated\b[^(\r\n]*(?:\(([0-9A-F]{4})\))?")
_ERROR = re.compile(rb"^ *\^ Error")
_BREAK = re.compile(rb"^Unexpected breakpoint interrupt")
_RX_NOTE = re.compile(rb"^386 regs (on|off)")

FLAG_BITS = {"cf": 0, "pf": 2, "af": 4, "zf": 6, "sf": 7, "if": 9, "df": 10, "of": 11}
_SET = {b"OV": "of", b"DN": "df", b"EI": "if", b"NG": "sf", b"ZR": "zf", b"AC": "af",
        b"PE": "pf", b"CY": "cf"}
FLAG_ORDER = ("of", "df", "if", "sf", "zf", "af", "pf", "cf")


@dataclass
class Instr:
    cs: int
    ip: int
    bytes: str      # «B8 75 0F»
    asm: str        # «MOV AX,0F75»


@dataclass
class Block:
    """Регистры после шага и следующая команда."""
    regs: dict[str, int]              # ax bx cx dx sp bp si di ds es ss cs ip flags
    reg32: dict[str, int] | None      # eax … edi, eip, eflags, fs, gs
    flags: dict[str, bool]
    next: Instr | None
    out: bytes                        # вывод программы перед блоком
    start: int
    end: int
    breakpoint: bool = False          # перед блоком было «Unexpected breakpoint interrupt»


@dataclass
class Termination:
    exit_code: int | None
    out: bytes
    start: int
    end: int


@dataclass
class DumpChunk:
    after_block: int                  # индекс блока, после которого снят дамп
    seg: int
    off: int
    data: bytearray = field(default_factory=bytearray)


@dataclass
class Command:
    """Эхо команды: какая и после какого блока."""
    text: str
    after_block: int


def _h(x: bytes) -> int:
    return int(x, 16)


def _flags_of(groups: tuple) -> dict[str, bool]:
    return {name: (g in _SET) for g, name in zip(groups, FLAG_ORDER)}


def flags_word(flags: dict[str, bool]) -> int:
    """Слово флагов по мнемоникам. В 16-битном виде DebugX слова не печатает, поэтому бит 1
    стоит всегда, а IOPL/NT/TF, которых по мнемоникам не видно, — нули."""
    word = 0x0002
    for name, bit in FLAG_BITS.items():
        if flags.get(name):
            word |= 1 << bit
    return word


def _asm_text(raw: bytes) -> str:
    raw = _MEMREF.sub(b"", raw).rstrip()
    text = raw.decode("latin-1")
    parts = text.split(None, 1)
    return parts[0] if len(parts) == 1 else f"{parts[0]} {parts[1].strip()}"


def _spaced(hexrun: bytes) -> str:
    s = hexrun.decode("ascii")
    return " ".join(s[i:i + 2] for i in range(0, len(s), 2))


class Parser:
    """Кормится кусками байтов по мере роста файла, отдаёт разобранное в списки.

    Смещения (`start`, `end`) — байтовые, от начала файла: по ним служба режет сырой вывод
    для окна DebugX. Блок шага — от конца прошлого блока до конца строки дизассемблера; эхо
    `D`/`R`/`RX` и строки дампа, идущие следом, приписываются к блоку, после которого сняты.
    """

    def __init__(self) -> None:
        self.blocks: list[Block] = []
        self.dumps: list[DumpChunk] = []
        self.commands: list[Command] = []
        self.terminated: Termination | None = None
        self.errors: list[tuple[int, str]] = []     # (после блока, строка)
        self.breaks_early: list[int] = []           # блоки, на которых оборвалась пачка T n
        self._buf = bytearray()
        self._pos = 0                  # смещение начала `_buf` в файле
        self._cursor = 0               # где начнётся следующий блок
        self._out = bytearray()
        # Строки регистров, пока не пришла строка дизассемблера: (совпадение, начало, конец, байты).
        self._pending: list[tuple[re.Match, int, int, bytes]] = []
        self._pending_prefix = b""
        self._dump: DumpChunk | None = None
        self._t_left = 0
        self._break = False

    # ── поток ──

    def feed(self, data: bytes) -> None:
        self._buf += data
        while True:
            nl = self._buf.find(b"\n")
            if nl < 0:
                break
            line = bytes(self._buf[:nl + 1])
            del self._buf[:nl + 1]
            start = self._pos
            self._pos += len(line)
            self._line(line, start, self._pos)

    def finish(self) -> None:
        """Файл больше не растёт. Хвост без перевода строки — вывод программы, повисшей на
        середине строки; он остаётся в `pending_out`."""
        if self._buf:
            self._out += self._buf
            self._pos += len(self._buf)
            self._buf.clear()

    @property
    def pending_out(self) -> bytes:
        return bytes(self._out)

    # ── строки ──

    def _attach(self, end: int) -> None:
        """Строка принадлежит последнему блоку (эхо D/R, дамп): блок растёт до неё."""
        if self.blocks and self.terminated is None:
            self.blocks[-1].end = end
            self._cursor = end

    def _line(self, line: bytes, start: int, end: int) -> None:
        if self.terminated is not None:
            return
        body = line.rstrip(b"\r\n")

        if self._pending:
            if self._continue_block(body, start, end):
                return
            # Ожидали следующую строку регистров, а пришло иное: найденное было выводом
            # программы, похожим на регистры, и выводом остаётся.
            for _, _, _, raw in self._pending:
                self._out += raw
            self._pending = []
            self._pending_prefix = b""

        m = _ECHO.match(body)
        if m:
            self._echo(m.group(1).decode("ascii"), start, end)
            return

        if self._dump is not None:
            d = _DUMP.match(body)
            if d:
                self._dump_line(body, d)
                self._attach(end)
                return
            self._dump = None

        if _RX_NOTE.match(body):
            self._attach(end)
            return
        if _ERROR.match(body):
            self.errors.append((len(self.blocks) - 1, body.decode("latin-1").strip()))
            self._attach(end)
            return
        if _BREAK.match(body):
            self._break = True
            return

        t = _TERMINATED.search(body)
        if t:
            out = bytes(self._out) + body[:t.start()]
            if out.endswith(b"\r\n"):
                out = out[:-2]
            code = _h(t.group(1)) if t.group(1) else None
            self.terminated = Termination(exit_code=code, out=out, start=self._cursor, end=end)
            self._out.clear()
            return

        r = _R32_1.search(body) or _R16_1.search(body)
        if r:
            self._pending = [(r, start, end, line)]
            self._pending_prefix = body[:r.start()]
            return

        self._out += line

    def _echo(self, cmd: str, start: int, end: int) -> None:
        after = len(self.blocks) - 1
        if cmd.startswith("T"):
            if self._t_left > 0 and self.blocks:
                self.breaks_early.append(len(self.blocks) - 1)
            parts = cmd.split()
            self._t_left = _h(parts[1].encode()) if len(parts) > 1 else 1
            self.commands.append(Command(cmd, after))
            return                                   # эхо T — начало следующего блока
        self.commands.append(Command(cmd, after))
        if cmd.startswith("D "):
            _, addr, _, _ = cmd.split()
            seg, off = addr.split(":")
            self._dump = DumpChunk(after_block=after, seg=int(seg, 16), off=int(off, 16))
            self.dumps.append(self._dump)
        self._attach(end)

    def _dump_line(self, body: bytes, d: re.Match) -> None:
        assert self._dump is not None
        line_off = _h(d.group(2))
        base = d.end() + 1
        for k in range(16):
            cell = body[base + 3 * k: base + 3 * k + 2]
            if len(cell) == 2 and re.fullmatch(rb"[0-9A-F]{2}", cell):
                at = line_off + k - self._dump.off
                if at < 0:
                    continue
                if at > len(self._dump.data):
                    self._dump.data += b"\x00" * (at - len(self._dump.data))
                if at == len(self._dump.data):
                    self._dump.data.append(int(cell, 16))
                else:
                    self._dump.data[at] = int(cell, 16)

    def _continue_block(self, body: bytes, start: int, end: int) -> bool:
        first = self._pending[0][0]
        is32 = first.re is _R32_1
        n = len(self._pending)
        if is32:
            if n == 1:
                m = _R32_2.match(body)
            elif n == 2:
                m = _R32_3.match(body)
            else:
                m = None
            if m:
                self._pending.append((m, start, end, body + b"\r\n"))
                return True
            if n == 3:
                return self._close_block(body, start, end)
            return False
        if n == 1:
            m = _R16_2.match(body)
            if m:
                self._pending.append((m, start, end, body + b"\r\n"))
                return True
            return False
        return self._close_block(body, start, end)

    def _close_block(self, body: bytes, start: int, end: int) -> bool:
        d = _DISASM.match(body)
        rows = [m for m, _, _, _ in self._pending]
        if rows[0].re is _R32_1:
            g1, g2, g3 = rows[0].groups(), rows[1].groups(), rows[2].groups()
            reg32 = {"eax": _h(g1[0]), "ebx": _h(g1[1]), "ecx": _h(g1[2]), "edx": _h(g1[3]),
                     "esp": _h(g1[4]), "ebp": _h(g1[5]), "esi": _h(g2[0]), "edi": _h(g2[1]),
                     "eip": _h(g2[2]), "eflags": _h(g2[3]), "fs": _h(g3[4]), "gs": _h(g3[5])}
            flags = _flags_of(g2[4:12])
            regs = {"ax": reg32["eax"] & 0xFFFF, "bx": reg32["ebx"] & 0xFFFF,
                    "cx": reg32["ecx"] & 0xFFFF, "dx": reg32["edx"] & 0xFFFF,
                    "sp": reg32["esp"] & 0xFFFF, "bp": reg32["ebp"] & 0xFFFF,
                    "si": reg32["esi"] & 0xFFFF, "di": reg32["edi"] & 0xFFFF,
                    "ds": _h(g3[0]), "es": _h(g3[1]), "ss": _h(g3[2]), "cs": _h(g3[3]),
                    "ip": reg32["eip"] & 0xFFFF, "flags": reg32["eflags"] & 0xFFFF}
        else:
            g1, g2 = rows[0].groups(), rows[1].groups()
            reg32 = None
            flags = _flags_of(g2[5:13])
            regs = {"ax": _h(g1[0]), "bx": _h(g1[1]), "cx": _h(g1[2]), "dx": _h(g1[3]),
                    "sp": _h(g1[4]), "bp": _h(g1[5]), "si": _h(g1[6]), "di": _h(g1[7]),
                    "ds": _h(g2[0]), "es": _h(g2[1]), "ss": _h(g2[2]), "cs": _h(g2[3]),
                    "ip": _h(g2[4]), "flags": flags_word(flags)}
        nxt = None
        if d:
            nxt = Instr(cs=_h(d.group(1)), ip=_h(d.group(2)), bytes=_spaced(d.group(3)),
                        asm=_asm_text(d.group(4)))
        block_end = end if d else self._pending[-1][2]
        block = Block(regs=regs, reg32=reg32, flags=flags, next=nxt,
                      out=bytes(self._out) + self._pending_prefix,
                      start=self._cursor, end=block_end, breakpoint=self._break)
        self.blocks.append(block)
        self._cursor = block_end
        self._out.clear()
        self._pending = []
        self._pending_prefix = b""
        if self._t_left > 0:
            self._t_left -= 1
        if self._break:
            if self._t_left > 0:
                self.breaks_early.append(len(self.blocks) - 1)
            self._t_left = 0
            self._break = False
        if not d:
            # Дизассемблера нет — строка не наша, разбираем её заново.
            self._line(body + b"\r\n", start, end)
        return True


def dump_command(seg: int, off: int, length: int) -> str:
    return f"D {seg:04X}:{off:04X} L {length:X}"


__all__ = ["Parser", "Block", "Instr", "Termination", "DumpChunk", "Command", "flags_word",
           "dump_command", "FLAG_ORDER", "FLAG_BITS"]
