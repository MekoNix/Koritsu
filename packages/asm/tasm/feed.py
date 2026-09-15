"""feed.py — ввод программы: где программа читает и что ей подать.

DebugX и программа читают один и тот же перенаправленный stdin. Поэтому ввод вставляется в
сценарий байтами сразу за командой `T` того шага, на котором программа читает, — и ровно
столько, сколько она съест: лишний байт DebugX прочтёт как команду (`a` уводит его в режим
ассемблера до конца сценария), недостающий программа доберёт из следующих команд.

Сколько съедает чтение, снято с DOSBox-X (`samples/exe-*`):

    01h, 07h, 08h, 06h (DL=FFh)   один байт, без эха
    0Ah                           до CR включительно, с эхом; сверх буфера — BEL, но читает до CR
    3Fh, BX=0                     ровно CX байт: stdin — файл, а не консоль

Человек задаёт ввод текстом, как набрал бы с клавиатуры, поэтому перевод строки подаётся так,
как его даёт консоль: Enter для 01h/0Ah — один CR; строка для 3Fh — строка и CR LF, и чтение
возвращает не больше одной строки (перед шагом сценарий ставит `R CX <сколько>`, после —
возвращает прежний CX). Кончившийся ввод для 3Fh — конец файла (`R CX 0`, AX=0); для
посимвольных функций подать нечего, и трасса честно останавливается.

Текст ввода — в CP866: кириллица в DOS-программе живёт в этой кодировке.
"""
from __future__ import annotations

from dataclasses import dataclass

ENCODING = "cp866"


@dataclass(frozen=True)
class Read:
    kind: str            # 'char' | 'line' | 'bytes'
    cx: int = 0          # для 'bytes'


def normalize(stdin: str) -> str:
    """CR LF → LF; непустой ввод без перевода строки в конце получает его: человек, набравший
    «42» в поле ввода, имел в виду «42 и Enter»."""
    text = stdin.replace("\r\n", "\n").replace("\r", "\n")
    if text and not text.endswith("\n"):
        text += "\n"
    return text


def read_at(asm: str, regs: dict[str, int]) -> Read | None:
    """Прочтёт ли программа stdin командой `asm` при этих регистрах."""
    words = asm.upper().split()
    if len(words) != 2 or words[0] != "INT":
        return None
    vector = words[1].rstrip("H")
    ah, al = regs["ax"] >> 8, regs["ax"] & 0xFF
    if vector == "21":
        func = ah
        if func == 0x0C:
            func = al
        if func in (0x01, 0x07, 0x08):
            return Read("char")
        if func == 0x06 and (regs["dx"] & 0xFF) == 0xFF:
            return Read("char")
        if func == 0x0A:
            return Read("line")
        if ah == 0x3F and regs["bx"] == 0:
            return Read("bytes", regs["cx"])
    return None


def waits_keyboard(asm: str, regs: dict[str, int]) -> bool:
    """Ждёт ли команда клавиатуру через BIOS (int 16h, AH=00h/10h/20h). В пакетном прогоне
    клавиатуры нет, и такая программа висит до таймаута."""
    words = asm.upper().split()
    if len(words) != 2 or words[0] != "INT" or words[1].rstrip("H") != "16":
        return False
    return (regs["ax"] >> 8) in (0x00, 0x10, 0x20)


def _enc(text: str) -> bytes:
    return text.encode(ENCODING, "replace")


class Feed:
    """Позиция в тексте ввода и то, что осталось от строки, прочитанной через 3Fh не целиком."""

    def __init__(self, stdin: str) -> None:
        self.text = normalize(stdin)
        self.pos = 0
        self.pending = b""

    @property
    def exhausted(self) -> bool:
        return not self.pending and self.pos >= len(self.text)

    def take(self, read: Read) -> bytes | None:
        """Байты для этого чтения или `None`, если подать нечего."""
        if read.kind == "char":
            if self.pending:
                b, self.pending = self.pending[:1], self.pending[1:]
                return b
            if self.pos >= len(self.text):
                return None
            ch = self.text[self.pos]
            self.pos += 1
            return b"\r" if ch == "\n" else _enc(ch)
        if read.kind == "line":
            if self.pending:
                cut = self.pending.find(b"\r")
                if cut >= 0:
                    b, self.pending = self.pending[:cut + 1], self.pending[cut + 1:]
                    return b
                head, self.pending = self.pending, b""
                rest = self._line_keyboard()
                return head + (rest if rest is not None else b"\r")
            return self._line_keyboard()
        # bytes
        if read.cx == 0:
            return b""
        if not self.pending:
            if self.pos >= len(self.text):
                return b""
            nl = self.text.find("\n", self.pos)
            line = self.text[self.pos:nl]
            self.pos = nl + 1
            self.pending = _enc(line) + b"\r\n"
        b, self.pending = self.pending[:read.cx], self.pending[read.cx:]
        return b

    def _line_keyboard(self) -> bytes | None:
        if self.pos >= len(self.text):
            return None
        nl = self.text.find("\n", self.pos)
        line = self.text[self.pos:nl]
        self.pos = nl + 1
        return _enc(line) + b"\r"

    def snapshot(self) -> tuple[int, bytes]:
        return self.pos, self.pending

    def restore(self, snap: tuple[int, bytes]) -> None:
        self.pos, self.pending = snap


__all__ = ["Feed", "Read", "read_at", "waits_keyboard", "normalize", "ENCODING"]
