"""ptrace.py — обвязка `ptrace(2)` для трассировщика программ Windows x64 под Wine.

Только `ctypes` и стандартная библиотека: исполнитель ставится без колёс, а нужно от ядра
немного — запустить процесс под трассировкой, шагнуть, прочитать и записать регистры и
память, поставить аппаратную точку.

Числа — из заголовков Linux x86-64 (`sys/ptrace.h`, `sys/user.h`, `asm/debugreg.h`).
Порядок полей `Regs` — `struct user_regs_struct`, 27 полей по 8 байт; `DR_OFFSET` —
`offsetof(struct user, u_debugreg)`.
"""
from __future__ import annotations

import ctypes
import os

_libc = ctypes.CDLL(None, use_errno=True)
_libc.ptrace.restype = ctypes.c_long
_libc.ptrace.argtypes = [ctypes.c_long, ctypes.c_long, ctypes.c_void_p, ctypes.c_void_p]

TRACEME = 0
POKEUSER = 6
CONT = 7
SINGLESTEP = 9
GETREGS = 12
SETREGS = 13
SETOPTIONS = 0x4200
GETEVENTMSG = 0x4201
GETSIGINFO = 0x4202

O_TRACECLONE = 0x8
O_TRACEEXEC = 0x10
O_EXITKILL = 0x100000

EV_CLONE = 3
EV_EXEC = 4
EV_STOP = 0x80

WALL = 0x40000000

# `si_code` у SIGTRAP: шаг, шаг через `syscall`, аппаратная точка, `int3`/`0xCC`.
TRAP_BRKPT = 1
TRAP_TRACE = 2
TRAP_HWBKPT = 4
SI_KERNEL = 0x80

DR_OFFSET = 848
TF = 0x100

REG_FIELDS = ("r15", "r14", "r13", "r12", "rbp", "rbx", "r11", "r10", "r9", "r8", "rax", "rcx",
              "rdx", "rsi", "rdi", "orig_rax", "rip", "cs", "eflags", "rsp", "ss", "fs_base",
              "gs_base", "ds", "es", "fs", "gs")


class Regs(ctypes.Structure):
    _fields_ = [(name, ctypes.c_ulong) for name in REG_FIELDS]


class SigInfo(ctypes.Structure):
    _fields_ = [("signo", ctypes.c_int), ("errno", ctypes.c_int), ("code", ctypes.c_int),
                ("pad", ctypes.c_int), ("addr", ctypes.c_ulong), ("rest", ctypes.c_byte * 112)]


REGS_SIZE = ctypes.sizeof(Regs)
raw_ptrace = _libc.ptrace


def call(request: int, tid: int, addr: int = 0, data: int = 0) -> int:
    """`ptrace` с проверкой ошибки: -1 и ненулевой errno — `OSError`."""
    ctypes.set_errno(0)
    result = _libc.ptrace(request, tid, ctypes.c_void_p(addr), ctypes.c_void_p(data))
    if result == -1:
        err = ctypes.get_errno()
        if err:
            raise OSError(err, f"ptrace({request}, {tid}): {os.strerror(err)}")
    return result


def traceme() -> None:
    """В потомке до `execve`: родитель становится трассировщиком. Ни прав, ни
    `CAP_SYS_PTRACE` не нужно — трассируется собственный потомок."""
    _libc.ptrace(TRACEME, 0, None, None)


def getregs(tid: int, regs: Regs) -> Regs:
    if _libc.ptrace(GETREGS, tid, None, ctypes.byref(regs)) == -1:
        raise OSError(ctypes.get_errno(), "PTRACE_GETREGS")
    return regs


def setregs(tid: int, regs: Regs) -> None:
    if _libc.ptrace(SETREGS, tid, None, ctypes.byref(regs)) == -1:
        raise OSError(ctypes.get_errno(), "PTRACE_SETREGS")


def siginfo(tid: int) -> SigInfo:
    info = SigInfo()
    _libc.ptrace(GETSIGINFO, tid, None, ctypes.byref(info))
    return info


def eventmsg(tid: int) -> int:
    value = ctypes.c_ulong()
    _libc.ptrace(GETEVENTMSG, tid, None, ctypes.byref(value))
    return value.value


def set_hw_exec(tid: int, addr: int) -> None:
    """Аппаратная точка исполнения DR0. Её можно ставить до того, как образ замаплен:
    память процесса не трогается."""
    call(POKEUSER, tid, DR_OFFSET + 7 * 8, 0)
    call(POKEUSER, tid, DR_OFFSET, addr)
    call(POKEUSER, tid, DR_OFFSET + 7 * 8, 1)          # L0, исполнение, длина 1


def clear_hw(tid: int) -> None:
    call(POKEUSER, tid, DR_OFFSET + 7 * 8, 0)
    call(POKEUSER, tid, DR_OFFSET + 6 * 8, 0)


__all__ = ["Regs", "SigInfo", "call", "traceme", "getregs", "setregs", "siginfo", "eventmsg",
           "set_hw_exec", "clear_hw", "raw_ptrace", "REG_FIELDS", "REGS_SIZE"]
