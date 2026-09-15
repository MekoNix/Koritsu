"""tracer.py — договор трассировщика MinGW x64: что он получает от сборки и что отдаёт.

Сборка (`build.py`), разбор образа (`pe.py`) и превращение сырых шагов в шаги сайта
(`runner.py`) от способа трассы не зависят. Всё, что зависит, — за протоколом `Tracer`: как
запустить `prog.exe`, как пройти его по командам, как подать ввод и снять вывод. Реализация
живёт в соседнем модуле и подключается в `tools.find_tracer`; пока её нет, там стоит
`NullTracer` — сборка работает, трасса отвечает «трассировщик не установлен».

**Что обязан делать любой трассировщик.**

- Шаги пишутся только внутри кода образа (`Image.code`). Вызов функции из DLL — **один шаг**:
  внутрь kernel32 трасса не заходит, у шага `call = 'kernel32.WriteFile'`, регистры — после
  возврата, по соглашению Microsoft x64 (результат в RAX, RCX RDX R8–R11 могут измениться).
  Вызов через заглушку импорта `jmp [rip+__imp_X]` в конце `.text` — тоже один шаг.
- Ввод: `ReadFile(STD_INPUT)` и `ReadConsoleA` берут байты из `stdin`, `stdin_pos` растёт.
  `stdin` приходит с переводами строк `\\n`; как консоль Windows отдаёт Enter (`\\r\\n`),
  решает трассировщик. Ввод кончился на чтении — `TraceEnd.status = 'waits_input'`.
- Вывод: `WriteFile(STD_OUTPUT/STD_ERROR)` и `WriteConsoleA` → байты в `RawStep.out` того шага,
  который вызвал функцию. Байты — как программа их записала, без перекодировки.
- `ExitProcess(n)` или `ret` из точки входа → `exited`, `exit_code = n` (у `ret` — RAX).
- Падение программы (переход по мусору после `pop bp` вместо `pop rbp`, деление на ноль, чужая
  память) → `crashed` и `error` по-русски, для человека: что и на каком шаге.
- Изоляция: без сети, без файловой системы машины кроме `workdir`, с потолками времени и памяти.
- `memory_at` детерминирован: тот же образ и ввод — та же память на том же шаге.

**Регистры** — `REGISTERS`, значения целыми. Сегментные у Windows x64 почти не меняются, но
показываются свёрнутыми, поэтому в словаре они есть.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal, Mapping, Protocol

from ..model import АсмОшибка, Segment

REGISTERS = ("rax", "rbx", "rcx", "rdx", "rsi", "rdi", "rbp", "rsp",
             "r8", "r9", "r10", "r11", "r12", "r13", "r14", "r15",
             "rip", "rflags", "cs", "ds", "ss", "es", "fs", "gs")
SEGMENT_REGISTERS = ("cs", "ds", "ss", "es", "fs", "gs")

NOT_INSTALLED = "трассировщик не установлен"


@dataclass(frozen=True)
class Image:
    """Собранная программа глазами трассировщика. Адреса — виртуальные, 64 бит."""
    exe: Path
    image_base: int
    entry: int                                   # VA точки входа
    sections: list[Segment]                      # секции PE: `start`/`length` — hex 16 по VA
    code: list[tuple[int, int]]                  # [start, end) VA исполняемых секций: шаги вне — не пишутся
    imports: dict[int, str]                      # VA ячейки IAT → 'kernel32.WriteFile'
    data_windows: list[tuple[int, int]]          # [start, end) VA: что дампить на шаг (.data/.bss/.rdata, до потолка)
    stack_window: int = 0x100                    # байт выше RSP, которые дампятся вместе с окнами данных


@dataclass(frozen=True)
class TraceLimits:
    step_limit: int
    dump_steps: int                              # до этого шага включительно — дампы окон на каждом шаге
    deadline: float                              # time.monotonic(), к которому трасса должна кончиться


@dataclass
class RawStep:
    """Шаг так, как его видит трассировщик. `runner` превращает его в `model.Step`."""
    i: int                                       # 0 — состояние до первой команды
    pc: int | None                               # RIP выполненной команды; None у шага 0
    asm: str                                     # команда в синтаксисе Intel
    bytes: bytes                                 # её байты
    regs: dict[str, int]                         # REGISTERS — после шага
    next_pc: int | None                          # RIP следующей команды; None — процесс завершён
    next_asm: str
    next_bytes: bytes
    writes: list[tuple[int, bytes, bytes]] | None    # (va, old, new); None — не знает, runner считает по дампам
    dumps: list[tuple[int, bytes]]               # (va, данные) окон на этом шаге; [] — не снимались
    out: bytes                                   # вывод программы за шаг
    stdin_pos: int                               # сколько байт ввода прочитано к концу шага
    call: str | None                             # 'kernel32.WriteFile' — вызов API, выполненный шагом целиком
    raw: tuple[str, int, int] | None             # (файл сырого вывода, смещение, длина) или None


TraceStatus = Literal["exited", "step_limit", "timeout", "crashed", "waits_input", "cancelled"]


@dataclass
class TraceEnd:
    status: TraceStatus
    exit_code: int | None
    error: str | None                            # по-русски, для человека
    load: dict                                   # {image_base, entry, rsp} — целые, при загрузке


class Tracer(Protocol):
    name: str                                    # 'wine-ptrace' | 'emu'

    def status(self, env: Mapping[str, str]) -> dict[str, bool]:
        """Что есть на машине; ключ `ready` обязателен. Не бросает."""
        ...

    def trace(self, image: Image, stdin: bytes, workdir: Path, *, limits: TraceLimits,
              sink: Callable[[RawStep], None],
              progress: Callable[[int], None] | None = None,
              cancelled: Callable[[], bool] | None = None) -> TraceEnd:
        """Пройти программу по шагам, отдавая каждый в `sink` по порядку `i`."""
        ...

    def memory_at(self, image: Image, stdin: bytes, workdir: Path, step: int,
                  ranges: list[tuple[int, int]], *, deadline: float) -> list[tuple[int, bytes]]:
        """Память `(va, len)` на шаге `step` → `(va, данные)`. Шага нет в программе — `АсмОшибка`."""
        ...


class NullTracer:
    """Трассировщика на машине нет: сборка работает, трасса и память — `АсмОшибка`."""
    name = "none"

    def status(self, env: Mapping[str, str]) -> dict[str, bool]:
        return {"ready": False}

    def trace(self, image: Image, stdin: bytes, workdir: Path, *, limits: TraceLimits,
              sink: Callable[[RawStep], None],
              progress: Callable[[int], None] | None = None,
              cancelled: Callable[[], bool] | None = None) -> TraceEnd:
        raise АсмОшибка(NOT_INSTALLED)

    def memory_at(self, image: Image, stdin: bytes, workdir: Path, step: int,
                  ranges: list[tuple[int, int]], *, deadline: float) -> list[tuple[int, bytes]]:
        raise АсмОшибка(NOT_INSTALLED)


__all__ = ["Image", "TraceLimits", "RawStep", "TraceEnd", "TraceStatus", "Tracer", "NullTracer",
           "REGISTERS", "SEGMENT_REGISTERS", "NOT_INSTALLED"]
