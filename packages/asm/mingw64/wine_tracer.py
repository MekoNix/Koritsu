"""wine_tracer.py — трассировщик программ Windows x64 под настоящим Wine на ptrace.

Реализация договора `tracer.Tracer` (`name = 'wine-ptrace'`). Код программы исполняется на
процессоре по-настоящему, поэтому этот модуль работает только в контейнере-исполнителе
(`runner_service.py`): без сети, без тома данных, без прав. Воркер зовёт его через очередь
(`runner_client.py`).

**Запуск.** `fork`; потомок делает `PTRACE_TRACEME`, получает stdin — канал, stdout и stderr —
файлы во временном каталоге прогона, и `execve(/usr/lib/wine/wine64, C:\\prog.exe)` с
префиксом прогона (`wine_prefix.clone`). Wine сам загружает ntdll, kernel32 и образ в том же
процессе. Опции ptrace: `EXITKILL` (трассировщик упал — программа не живёт дальше),
`TRACECLONE`, `TRACEEXEC`; порождённый wineserver не трассируется.

**Точка входа** — аппаратная точка DR0 на `Image.entry`: её можно ставить до того, как образ
замаплен, память не трогается. Ядро сбрасывает DR при `exec` и не наследует их потокам —
точка ставится заново на событии `exec` и на первой остановке нового потока.

**Шаг.** `PTRACE_SINGLESTEP` → `waitpid` → `PTRACE_GETREGS`. Остановка SIGTRAP без события
(статус `0x57F`) после обычной команды — свой шаг, `siginfo` не нужен. Шаги пишутся только
внутри `Image.code`.

**Вызов за пределы кода — один шаг.** `call` в заглушку импорта (`jmp [rip+__imp_X]`, ячейка
из `Image.imports`) или шаг, уведший RIP из кода после `call`/`jmp`: на адрес возврата `[RSP]`
пишется `0xCC` через `/proc/pid/mem`, `PTRACE_CONT`, остановка SIGTRAP `SI_KERNEL` с RIP =
адрес + 1 — байт возвращается, RIP = адрес. У шага `call = 'kernel32.X'`: по ячейке IAT, или
по адресу функции, который загрузчик в эту ячейку записал.

**Флаг TF.** Шагу ptrace ставит TF, и программа может его увидеть. `pushf` под шагом кладёт в
стек RFLAGS с TF — после шага бит снимается в `[RSP]`. Шаг по `popf` ядро считает «программа
сама ставит TF» и дальше TF не снимает: он виден в трассе и уходит в код Wine при
`PTRACE_CONT` (вызов API идёт шагами — в сотни раз медленнее). Поэтому `popf` не шагается, а
исполняется здесь: из `[RSP]` переносятся биты CF PF AF ZF SF DF OF NT AC ID, RSP и RIP
сдвигаются, `PTRACE_SETREGS`.

**Сигналы.** SIGTRAP шага через `syscall` приходит с `TRAP_BRKPT` — он свой и не
доставляется. `int3` студента — SIGTRAP `SI_KERNEL` после `CC`/`CD 03`: шаг пишется, сигнал
доставляется, Wine завершает процесс с 0x80000003. SIGSEGV/SIGFPE/SIGILL/SIGBUS на шаге —
падение: команда не выполнилась, сигнал доставляется Wine (исключение Windows), причина
пишется по-русски по сигналу и `si_code` — код выхода Wine это лишь младший байт NTSTATUS.
Прочие сигналы доставляются потоку с `0xCC` на текущей команде: обработчик Wine отработает
без шагов, а возврат из него снова остановит программу на ней же.

**Ввод.** stdin программы — канал, в который трассировщик кладёт по одной строке перед
вызовом `ReadFile` со стандартного ввода (дескриптор — из `RTL_USER_PROCESS_PARAMETERS`
через PEB) или `ReadConsoleA/W`, если в канале пусто. Строка уходит с `\\r\\n`, как её отдаёт
консоль Windows по Enter. Строк больше нет — прогон кончается `waits_input` перед вызовом:
на консоли программа ждала бы. `stdin_pos` — байты исходного ввода (без `\\r`), прочитанные
к концу шага: написанное в канал минус непрочитанное (`FIONREAD`).

**Вывод.** stdout и stderr — файлы на tmpfs; трассировщик дочитывает их после каждого вызова
API и отдаёт байты в `out` этого шага. Канал для вывода не годится: заполнившись во время
`PTRACE_CONT`, он остановил бы Wine внутри `WriteFile`, пока трассировщик ждёт возврата.
Вывода больше `OUT_MAX` — прогон останавливается. stderr Wine (`Unhandled exception…`) после
падения уходит в конец сырого вывода.

**Конец.** `ExitProcess` — процесс кончается внутри вызова: шаг пишется без `next`,
`exited`. `ret` из точки входа уводит RIP в код запуска Wine: шаг пишется, `PTRACE_CONT` до
выхода, `exited` с кодом RAX. Переход из кода не через `call`/`ret` к началу — трасса
кончается, программа доигрывает без шагов, итог `crashed`. Лимит шагов — `SIGKILL`,
`step_limit`. Дедлайн и отмена проверяются таймером (`ITIMER_REAL`): блокирующий `waitpid`
прерывается, процесс снимается.

**Память.** До `limits.dump_steps` на каждом шаге читаются окна данных (`Image.data_windows`)
и стек `[RSP-0x40, RSP+stack_window)`; `writes` — разница с прошлым шагом (в стеке — только
по адресам не ниже нового RSP: ниже лежит мусор кадров вызванных функций). Дампы окон — у
шага 0 и у последнего шага за `dump_steps`. `memory_at` — перезапуск с тем же вводом до шага.

**Сырой вывод** — строка текста на шаг в `raw.txt` рабочего каталога: номер, адрес, команда,
изменённые регистры, вызов, запись в память, вывод. `RawStep.raw` — `(файл, смещение,
длина)`; после `RAW_MAX` строк больше не пишется, `raw = None`.
"""
from __future__ import annotations

import ctypes
import fcntl
import os
import resource
import shutil
import signal
import struct
import threading
import time
from pathlib import Path
from typing import Callable, Mapping

from ..model import АсмОшибка
from . import ptrace as pt
from . import wine_prefix
from .tracer import REGISTERS, Image, RawStep, TraceEnd, TraceLimits

WINE64 = wine_prefix.WINE64
EXE_NAME = "prog.exe"
RAW_NAME = "raw.txt"

OUT_MAX = 1024 * 1024               # байт вывода программы за прогон
RAW_MAX = 64 * 1024 * 1024          # байт сырого вывода; 200 000 шагов — около 30 МБ
FILE_BYTES = 64 * 1024 * 1024       # потолок файла, который может написать процесс Wine
STDIN_PIPE = 1024 * 1024            # размер канала ввода (больше строки ввода)
STACK_BELOW = 0x40                  # байт ниже RSP, читаемых ради записи `push`
TICK_S = 0.1
PROGRESS_EVERY = 512
PAGE = 4096
FIONREAD = 0x541B
F_SETPIPE_SZ = 1031

_PREFIXES = frozenset((0x66, 0x67, 0xF2, 0xF3, 0x2E, 0x3E, 0x26, 0x36, 0x64, 0x65))
K_PLAIN, K_PUSHF, K_POPF, K_CALL, K_JMP, K_RET, K_INT3, K_SYSCALL = range(8)
POPF_MASK = 0x244CD5                # CF PF AF ZF SF DF OF NT AC ID
READ_FUNCS = frozenset(("ReadFile", "ReadConsoleA", "ReadConsoleW"))
EXIT_FUNCS = frozenset(("ExitProcess", "TerminateProcess", "RtlExitUserProcess"))

SEGV_MAPERR, SEGV_ACCERR = 1, 2
_UPPER = {name: name.upper() for name in REGISTERS}


class _Stop(Exception):
    """Таймер прервал блокирующее ожидание: дедлайн или отмена."""


def _u64(data: bytes) -> int:
    return int.from_bytes(data[:8].ljust(8, b"\0"), "little")


def _h(value: int) -> str:
    return f"{value & 0xFFFF_FFFF_FFFF_FFFF:016X}"


def _diff(va: int, old: bytes, new: bytes, floor: int, out: list) -> None:
    """Прогоны различающихся байт `old`/`new` (одинаковой длины) с адреса `va`; адреса ниже
    `floor` не пишутся."""
    n = min(len(old), len(new))
    if old[:n] == new[:n]:
        return
    k = 0
    while k < n:
        e = min(n, k + 64)
        if old[k:e] == new[k:e]:
            k = e
            continue
        j = k
        while j < e:
            if old[j] != new[j]:
                s = j
                while j < n and old[j] != new[j]:
                    j += 1
                if va + j > floor:
                    s = max(s, floor - va)
                    out.append((va + s, old[s:j], new[s:j]))
                e = max(e, j)
            else:
                j += 1
        k = max(e, j)


def _fault_text(sig: int, code: int, addr: int) -> str:
    if sig == signal.SIGSEGV:
        if code == SEGV_MAPERR:
            return f"нарушение доступа (исключение Windows 0xC0000005): по адресу {_h(addr)} нет памяти"
        if code == SEGV_ACCERR:
            return (f"нарушение доступа (исключение Windows 0xC0000005): к памяти {_h(addr)} "
                    "нет такого доступа — запись в код или в данные только для чтения")
        return "нарушение доступа (исключение Windows 0xC0000005)"
    if sig == signal.SIGFPE:
        return ("деление на ноль или частное не помещается в регистр "
                "(исключение Windows 0xC0000094)")
    if sig == signal.SIGILL:
        return "недопустимая команда (исключение Windows 0xC000001D)"
    if sig == signal.SIGBUS:
        return "ошибка шины (исключение Windows 0xC0000005)"
    return f"сигнал {signal.Signals(sig).name}"


class WineTracer:
    """Трассировщик под Wine. `base_prefix` — общий префикс образа, `run_dir` — свой
    временный каталог (tmpfs, исполняемый): в нём префикс прогона, stdout, stderr, HOME.
    `insns` — команды кода по VA: `(текст Intel, байты)` из `objdump` сборки."""

    name = "wine-ptrace"

    def __init__(self, base_prefix: Path, run_dir: Path, *,
                 insns: Mapping[int, tuple[str, bytes]] | None = None,
                 raw_name: str = RAW_NAME, block_syscalls: bool = True) -> None:
        self.base_prefix = Path(base_prefix)
        self.run_dir = Path(run_dir)
        self.insns = dict(insns or {})
        self.raw_name = raw_name
        self.block_syscalls = block_syscalls
        self._runs = 0

    def status(self, env: Mapping[str, str]) -> dict[str, bool]:
        wine = os.access(WINE64, os.X_OK)
        prefix = (self.base_prefix / "system.reg").is_file()
        return {"ready": wine and prefix, "wine": wine, "prefix": prefix}

    def trace(self, image: Image, stdin: bytes, workdir: Path, *, limits: TraceLimits,
              sink: Callable[[RawStep], None],
              progress: Callable[[int], None] | None = None,
              cancelled: Callable[[], bool] | None = None) -> TraceEnd:
        with self._prefix() as (prefix, home):
            session = _Session(self, image, stdin, Path(workdir), prefix, home, limits, sink,
                               progress, cancelled)
            return session.run()

    def memory_at(self, image: Image, stdin: bytes, workdir: Path, step: int,
                  ranges: list[tuple[int, int]], *, deadline: float,
                  cancelled: Callable[[], bool] | None = None) -> list[tuple[int, bytes]]:
        limits = TraceLimits(step_limit=max(1, step), dump_steps=0, deadline=deadline)
        with self._prefix() as (prefix, home):
            session = _Session(self, image, stdin, Path(workdir), prefix, home, limits,
                               None, None, cancelled, stop_at=step, ranges=ranges)
            end = session.run()
        if session.memory is not None:
            return session.memory
        if end.status == "timeout":
            raise АсмОшибка("Память на шаге не снята: прогон не уложился в отведённое время")
        if end.status == "cancelled":
            raise АсмОшибка("Прогон отменён")
        if session.i == step:
            raise АсмОшибка(f"На шаге {step} программа уже завершилась — памяти процесса нет")
        raise АсмОшибка(f"Шага {step} в программе нет: трасса кончилась на шаге {session.i}")

    # ── префикс прогона ──────────────────────────────────────────────────────

    class _PrefixCtx:
        def __init__(self, tracer: "WineTracer") -> None:
            tracer._runs += 1
            self.root = tracer.run_dir / f"wine-{os.getpid()}-{tracer._runs}"
            self.base = tracer.base_prefix

        def __enter__(self) -> tuple[Path, Path]:
            prefix = self.root / "prefix"
            home = self.root / "home"
            prefix.mkdir(parents=True, mode=0o700)
            home.mkdir(mode=0o700)
            wine_prefix.clone(self.base, prefix)
            return prefix, home

        def __exit__(self, *exc) -> None:
            wine_prefix.kill_server(self.root / "prefix", self.root / "home")
            shutil.rmtree(self.root, ignore_errors=True)

    def _prefix(self) -> "WineTracer._PrefixCtx":
        return WineTracer._PrefixCtx(self)


class _Session:
    """Один запуск программы под трассировкой."""

    def __init__(self, tracer: WineTracer, image: Image, stdin: bytes, workdir: Path,
                 prefix: Path, home: Path, limits: TraceLimits,
                 sink: Callable[[RawStep], None] | None,
                 progress: Callable[[int], None] | None,
                 cancelled: Callable[[], bool] | None, *, stop_at: int | None = None,
                 ranges: list[tuple[int, int]] | None = None) -> None:
        self.t = tracer
        self.image = image
        self.workdir = workdir
        self.prefix = prefix
        self.home = home
        self.limits = limits
        self.sink = sink
        self.progress = progress
        self.cancelled = cancelled
        self.stop_at = stop_at
        self.ranges = ranges or []
        self.memory: list[tuple[int, bytes]] | None = None

        self.code = sorted(image.code)
        self.lo, self.hi = self.code[0] if self.code else (0, 0)
        self.code_bytes: list[tuple[int, bytes]] = []
        self.kinds: dict[int, tuple[int, int]] = {}
        self.iat_by_value: dict[int, str] = {}

        self.pid = 0
        self.tid = 0
        self.threads: set[int] = set()
        self.seen_stop: set[int] = set()
        self.memfd = -1
        self.regs = pt.Regs()
        self.alive = False
        self.exit_code: int | None = None

        self.i = 0
        self.prev: dict[str, int] | None = None
        self.load: dict = {"image_base": image.image_base, "entry": image.entry, "rsp": None}
        self.entry_ret = 0
        self.stdin_handle = None
        self.dump_steps = limits.dump_steps if sink is not None else 0
        self.win_prev: list[bytes] = []
        self.stack_prev: tuple[int, bytes] | None = None

        # ввод
        self.lines = self._split_input(stdin)
        self.line_no = 0
        self.fed: list[tuple[int, int, int, bool]] = []    # (начало в канале, начало во вводе, длина текста, есть ли \n)
        self.fed_total = 0
        self.in_pending = b""
        self.in_r = self.in_w = -1
        self.stdin_pos = 0

        # вывод
        self.out_r = self.err_r = -1
        self.out_total = 0

        # сырой вывод
        self.raw_fh = None
        self.raw_off = 0

        # таймер
        self.stop: str | None = None
        self.blocking = False
        self.cleanup_guard: float | None = None
        self._old_handler = None
        self._timer = False

    # ── ввод ─────────────────────────────────────────────────────────────────

    @staticmethod
    def _split_input(stdin: bytes) -> list[tuple[bytes, bool]]:
        parts = stdin.split(b"\n")
        lines = [(p, True) for p in parts[:-1]]
        if parts[-1]:
            lines.append((parts[-1], False))
        return lines

    def _pipe_left(self) -> int:
        buf = ctypes.c_int(0)
        try:
            fcntl.ioctl(self.in_r, FIONREAD, buf)
        except OSError:
            return 0
        return buf.value

    def _push_input(self) -> None:
        if not self.in_pending:
            return
        try:
            n = os.write(self.in_w, self.in_pending)
        except BlockingIOError:
            n = 0
        self.in_pending = self.in_pending[n:]

    def _feed(self) -> bool:
        """Перед чтением ввода программой: в канале пусто — положить следующую строку.
        Строк больше нет — False."""
        if self._pipe_left() > 0:
            return True
        if self.in_pending:
            self._push_input()
            return True
        if self.line_no >= len(self.lines):
            return False
        text, newline = self.lines[self.line_no]
        self.line_no += 1
        orig_start = self.fed[-1][1] + self.fed[-1][2] + (1 if self.fed[-1][3] else 0) if self.fed else 0
        data = text + (b"\r\n" if newline else b"")
        self.fed.append((self.fed_total, orig_start, len(text), newline))
        self.fed_total += len(data)
        self.in_pending = data
        self._push_input()
        return True

    def _consumed(self) -> int:
        """Сколько байт исходного ввода программа прочитала."""
        if not self.fed:
            return 0
        in_pipe = self._pipe_left() + len(self.in_pending)
        consumed = self.fed_total - in_pipe
        for conv_start, orig_start, length, newline in reversed(self.fed):
            if consumed >= conv_start:
                k = consumed - conv_start
                if not newline:
                    return orig_start + min(k, length)
                if k <= length:
                    return orig_start + k
                return orig_start + length + (1 if k >= length + 2 else 0)
        return 0

    # ── память ───────────────────────────────────────────────────────────────

    def _read(self, addr: int, n: int) -> bytes:
        if n <= 0 or addr < 0:
            return b""
        try:
            data = os.pread(self.memfd, n, addr)
            if len(data) == n:
                return data
        except OSError:
            data = b""
        out = bytearray(data)
        pos = addr + len(out)
        while len(out) < n:
            chunk = min(n - len(out), PAGE - (pos % PAGE))
            try:
                part = os.pread(self.memfd, chunk, pos)
            except OSError:
                break
            if not part:
                break
            out += part
            pos += len(part)
        return bytes(out)

    def _in_code(self, va: int) -> bool:
        for lo, hi in self.code:
            if lo <= va < hi:
                return True
        return False

    def _code_at(self, va: int, n: int) -> bytes:
        for lo, data in self.code_bytes:
            if lo <= va < lo + len(data):
                return data[va - lo: va - lo + n]
        return b""

    def _classify(self, rip: int) -> tuple[int, int]:
        """Вид команды по байтам кода: (вид, длина); длина нужна только `popf`."""
        data = self._code_at(rip, 16)
        k = 0
        p66 = False
        while k < len(data) and (data[k] in _PREFIXES or 0x40 <= data[k] <= 0x4F):
            p66 = p66 or data[k] == 0x66
            k += 1
        op = data[k] if k < len(data) else 0x90
        nxt = data[k + 1] if k + 1 < len(data) else 0
        kind = K_PLAIN
        if op == 0x9C:
            kind = K_PUSHF
        elif op == 0x9D:
            kind = K_POPF
        elif op == 0xE8:
            kind = K_CALL
        elif op == 0xFF and ((nxt >> 3) & 7) in (2, 3):
            kind = K_CALL
        elif op in (0xE9, 0xEB, 0xEA) or (op == 0xFF and ((nxt >> 3) & 7) in (4, 5)):
            kind = K_JMP
        elif op in (0xC3, 0xC2, 0xCB, 0xCA, 0xCF):
            kind = K_RET
        elif op in (0xCC, 0xF1) or (op == 0xCD and nxt == 0x03):
            kind = K_INT3
        elif (op == 0x0F and nxt in (0x05, 0x34)) or (op == 0xCD and nxt == 0x80):
            kind = K_SYSCALL
        elif op == 0xCD:
            kind = K_INT3
        result = (kind, (k + 1) if kind == K_POPF else (2 if p66 else 8))
        if kind == K_POPF:
            result = (kind, (k + 1) | ((2 if p66 else 8) << 8))
        self.kinds[rip] = result
        return result

    def _stub_cell(self, va: int) -> int | None:
        """Адрес ячейки IAT, если по `va` лежит заглушка импорта `jmp [rip+disp32]`."""
        data = self._code_at(va, 6)
        if len(data) == 6 and data[0] == 0xFF and data[1] == 0x25:
            cell = va + 6 + struct.unpack_from("<i", data, 2)[0]
            if cell in self.image.imports:
                return cell
        return None

    def _asm(self, va: int | None) -> tuple[str, bytes]:
        if va is None:
            return "", b""
        return self.t.insns.get(va, ("", b""))

    # ── таймер ───────────────────────────────────────────────────────────────

    def _tick(self, signum, frame) -> None:
        now = time.monotonic()
        if self.cleanup_guard is not None:
            if self.blocking and now > self.cleanup_guard:
                raise _Stop()
            return
        if self.stop is None:
            if now > self.limits.deadline:
                self.stop = "timeout"
            elif self.cancelled is not None:
                try:
                    if self.cancelled():
                        self.stop = "cancelled"
                except Exception:                                    # noqa: BLE001
                    pass
        if self.stop is not None and self.blocking:
            raise _Stop()

    def _start_timer(self) -> None:
        if threading.current_thread() is not threading.main_thread():
            return
        self._old_handler = signal.signal(signal.SIGALRM, self._tick)
        signal.setitimer(signal.ITIMER_REAL, TICK_S, TICK_S)
        self._timer = True

    def _stop_timer(self) -> None:
        if self._timer:
            signal.setitimer(signal.ITIMER_REAL, 0, 0)
            signal.signal(signal.SIGALRM, self._old_handler or signal.SIG_DFL)
            self._timer = False

    def _wait(self, pid: int) -> tuple[int, int]:
        self.blocking = True
        try:
            if self.stop is not None and self.cleanup_guard is None:
                raise _Stop()
            return os.waitpid(pid, pt.WALL)
        finally:
            self.blocking = False

    # ── запуск ───────────────────────────────────────────────────────────────

    def run(self) -> TraceEnd:
        self._start_timer()
        try:
            try:
                self._spawn()
                if not self._wait_entry():
                    return self._end("crashed", self._no_entry_text())
                self._at_entry()
                return self._loop()
            except _Stop:
                return self._end(self.stop if self.stop in ("timeout", "cancelled") else "timeout",
                                 None)
        finally:
            self._cleanup()
            self._stop_timer()

    def _spawn(self) -> None:
        drive_c = self.prefix / "drive_c"
        shutil.copyfile(self.image.exe, drive_c / EXE_NAME)
        out_path = self.home / "stdout"
        err_path = self.home / "stderr"
        out_w = os.open(out_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        err_w = os.open(err_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        self.out_r = os.open(out_path, os.O_RDONLY)
        self.err_r = os.open(err_path, os.O_RDONLY)
        self.in_r, self.in_w = os.pipe()
        try:
            fcntl.fcntl(self.in_w, F_SETPIPE_SZ, STDIN_PIPE)
        except OSError:
            pass
        os.set_blocking(self.in_w, False)
        if self.sink is not None:
            self.raw_fh = open(self.workdir / self.t.raw_name, "wb")        # noqa: SIM115
        env = wine_prefix.wine_env(self.prefix, self.home)
        cpu_s = max(5, int(self.limits.deadline - time.monotonic()) + 5)
        pid = os.fork()
        if pid == 0:                                                       # потомок
            try:
                os.chdir(drive_c)
                os.dup2(self.in_r, 0)
                os.dup2(out_w, 1)
                os.dup2(err_w, 2)
                os.closerange(3, 4096)
                resource.setrlimit(resource.RLIMIT_FSIZE, (FILE_BYTES, FILE_BYTES))
                resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
                resource.setrlimit(resource.RLIMIT_CPU, (cpu_s, cpu_s + 2))
                pt.traceme()
                os.execve(WINE64, [WINE64, "C:\\" + EXE_NAME], env)
            finally:
                os._exit(127)
        os.close(out_w)
        os.close(err_w)
        self.pid = self.tid = pid
        self.alive = True
        self.threads.add(pid)
        _, st = self._wait(pid)
        if not os.WIFSTOPPED(st):
            self.alive = False
            self.exit_code = os.WEXITSTATUS(st) if os.WIFEXITED(st) else -os.WTERMSIG(st)
            raise АсмОшибка(f"Wine не запустился (код {self.exit_code})")
        pt.call(pt.SETOPTIONS, pid, 0, pt.O_EXITKILL | pt.O_TRACECLONE | pt.O_TRACEEXEC)
        self.memfd = os.open(f"/proc/{pid}/mem", os.O_RDWR)

    def _no_entry_text(self) -> str:
        err = b""
        try:
            err = os.pread(self.err_r, 400, 0)
        except OSError:
            pass
        text = err.decode("utf-8", "replace").strip()
        tail = f": {text}" if text else ""
        return f"Wine завершил программу до точки входа (код {self.exit_code}){tail}"

    def _wait_entry(self) -> bool:
        entry = self.image.entry
        pt.set_hw_exec(self.pid, entry)
        pt.call(pt.CONT, self.pid, 0, 0)
        while True:
            tid, st = self._wait(-1)
            if os.WIFEXITED(st) or os.WIFSIGNALED(st):
                self.threads.discard(tid)
                if tid == self.pid:
                    self.alive = False
                    self.exit_code = os.WEXITSTATUS(st) if os.WIFEXITED(st) else -os.WTERMSIG(st)
                    return False
                continue
            if not os.WIFSTOPPED(st):
                continue
            sig = os.WSTOPSIG(st)
            ev = st >> 16
            if ev == pt.EV_CLONE:
                self.threads.add(pt.eventmsg(tid))
                self._resume(tid, 0)
                continue
            if ev == pt.EV_EXEC:
                os.close(self.memfd)
                self.memfd = os.open(f"/proc/{self.pid}/mem", os.O_RDWR)
                pt.set_hw_exec(tid, entry)
                self._resume(tid, 0)
                continue
            if ev == pt.EV_STOP or (sig == signal.SIGSTOP and tid not in self.seen_stop):
                self.seen_stop.add(tid)
                self.threads.add(tid)
                try:
                    pt.set_hw_exec(tid, entry)
                except OSError:
                    pass
                self._resume(tid, 0)
                continue
            if sig == signal.SIGTRAP and ev == 0:
                info = pt.siginfo(tid)
                if info.code == pt.TRAP_HWBKPT:
                    pt.getregs(tid, self.regs)
                    if self.regs.rip == entry:
                        self.tid = tid
                        for t in list(self.threads):
                            try:
                                pt.clear_hw(t)
                            except OSError:
                                pass
                        return True
                if info.code in (pt.TRAP_HWBKPT, pt.TRAP_TRACE, pt.TRAP_BRKPT):
                    self._resume(tid, 0)
                    continue
            self._resume(tid, sig)

    @staticmethod
    def _resume(tid: int, sig: int) -> None:
        try:
            pt.call(pt.CONT, tid, 0, sig)
        except OSError:
            pass

    def _at_entry(self) -> None:
        regs = self.regs
        self.load["rsp"] = regs.rsp
        self.entry_ret = _u64(self._read(regs.rsp, 8))
        for lo, hi in self.code:
            self.code_bytes.append((lo, self._read(lo, hi - lo)))
        for cell, name in self.image.imports.items():
            value = _u64(self._read(cell, 8))
            if value:
                self.iat_by_value.setdefault(value, name)
        try:
            peb = _u64(self._read(regs.gs_base + 0x60, 8))
            params = _u64(self._read(peb + 0x20, 8))
            self.stdin_handle = _u64(self._read(params + 0x20, 8))
        except (OSError, ValueError):
            self.stdin_handle = None
        # Шаг 0: состояние до первой команды, дампы окон целиком.
        dumps = []
        for lo, hi in self.image.data_windows:
            data = self._read(lo, hi - lo)
            self.win_prev.append(data)
            if self.dump_steps > 0 or self.sink is not None:
                dumps.append((lo, data))
        stack_lo = regs.rsp - STACK_BELOW
        stack = self._read(stack_lo, STACK_BELOW + self.image.stack_window)
        self.stack_prev = (stack_lo, stack)
        if self.sink is not None:
            dumps.append((regs.rsp, stack[STACK_BELOW:]))
        self._emit_state(0, None, None, [], dumps, b"", None)
        if self.stop_at == 0:
            self._capture_memory()

    # ── главный цикл ─────────────────────────────────────────────────────────

    def _loop(self) -> TraceEnd:
        regs = self.regs
        tid = self.tid
        raw_ptrace = pt.raw_ptrace
        regs_ref = ctypes.byref(regs)
        waitpid = os.waitpid
        kinds = self.kinds
        classify = self._classify
        lo, hi = self.lo, self.hi
        limit = self.limits.step_limit
        while True:
            if self.stop is not None:
                return self._stopped()
            if self.i >= limit:
                return self._end("step_limit", None)
            rip = regs.rip
            kind = kinds.get(rip) or classify(rip)
            k = kind[0]
            if k == K_POPF:
                self._popf(rip, kind[1])
                self._step_done(rip, None, b"")
                continue
            if k == K_SYSCALL and self.t.block_syscalls:
                asm = self._asm(rip)[0] or "syscall"
                return self._end("crashed", f"Команда `{asm}` по адресу {_h(rip)} — прямой "
                                            "системный вызов Linux в обход Windows API; "
                                            "прогон остановлен до её исполнения")
            self.blocking = True
            try:
                if self.stop is not None:
                    raise _Stop()
                raw_ptrace(pt.SINGLESTEP, tid, None, None)
                _, st = waitpid(tid, pt.WALL)
            finally:
                self.blocking = False
            if st != 0x57F or k == K_INT3:
                end = self._slow_stop(st, rip, k)
                if end is not None:
                    return end
            raw_ptrace(pt.GETREGS, tid, None, regs_ref)
            if k == K_PUSHF:
                sp = regs.rsp
                word = self._read(sp, 2)
                if len(word) == 2:
                    os.pwrite(self.memfd, (int.from_bytes(word, "little") & ~pt.TF)
                              .to_bytes(2, "little"), sp)
            new = regs.rip
            if (lo <= new < hi) or self._in_code(new):
                if k == K_CALL:
                    cell = self._stub_cell(new)
                    if cell is not None:
                        end = self._call_out(rip, _u64(self._read(regs.rsp, 8)),
                                             self.image.imports[cell])
                        if end is not None:
                            return end
                        continue
                self._step_done(rip, None, b"")
                continue
            if k in (K_CALL, K_JMP):
                ret = _u64(self._read(regs.rsp, 8))
                if self._in_code(ret):
                    end = self._call_out(rip, ret, self.iat_by_value.get(new))
                    if end is not None:
                        return end
                    continue
            return self._leave(rip, k)

    def _popf(self, rip: int, info: int) -> None:
        regs = self.regs
        length, width = info & 0xFF, info >> 8
        value = int.from_bytes(self._read(regs.rsp, width).ljust(width, b"\0"), "little")
        mask = POPF_MASK if width == 8 else POPF_MASK & 0xFFFF
        regs.eflags = (regs.eflags & ~mask) | (value & mask)
        regs.rsp += width
        regs.rip = rip + length
        pt.setregs(self.tid, regs)

    def _slow_stop(self, st: int, rip: int, k: int) -> TraceEnd | None:
        """Остановка после шага, отличная от обычной. None — шаг выполнен, идти дальше."""
        tid = self.tid
        while True:
            if os.WIFEXITED(st) or os.WIFSIGNALED(st):
                self.alive = False
                self.exit_code = os.WEXITSTATUS(st) if os.WIFEXITED(st) else -os.WTERMSIG(st)
                asm = self._asm(rip)[0] or "?"
                return self._end("crashed", f"Процесс завершился на команде `{asm}` по адресу "
                                            f"{_h(rip)} (код выхода {self.exit_code})")
            sig = os.WSTOPSIG(st)
            ev = st >> 16
            if ev:
                if ev == pt.EV_CLONE:
                    self.threads.add(pt.eventmsg(tid))
                st = self._restep(tid, 0)
                continue
            if sig == signal.SIGTRAP:
                info = pt.siginfo(tid)
                if info.code in (pt.TRAP_TRACE, pt.TRAP_BRKPT, pt.TRAP_HWBKPT):
                    return None
                if k == K_INT3 and info.code == pt.SI_KERNEL:
                    return self._int3(rip)
                return self._deliver_async(rip, sig)
            if sig in (signal.SIGSEGV, signal.SIGBUS, signal.SIGILL, signal.SIGFPE):
                return self._fault(rip, sig)
            if sig == signal.SIGSTOP and tid not in self.seen_stop:
                self.seen_stop.add(tid)
                st = self._restep(tid, 0)
                continue
            end = self._deliver_async(rip, sig)
            if end is not None:
                return end
            return None

    def _restep(self, tid: int, sig: int) -> int:
        self.blocking = True
        try:
            if self.stop is not None:
                raise _Stop()
            pt.raw_ptrace(pt.SINGLESTEP, tid, None, ctypes.c_void_p(sig))
            return os.waitpid(tid, pt.WALL)[1]
        finally:
            self.blocking = False

    def _deliver_async(self, rip: int, sig: int) -> TraceEnd | None:
        """Чужой сигнал на шаге: доставить с `0xCC` на команде, где стоит поток, дождаться
        возврата из обработчика, затем повторить шаг, если команда не выполнилась."""
        tid = self.tid
        regs = pt.getregs(tid, pt.Regs())
        at = regs.rip
        if not self._in_code(at):
            st = self._restep(tid, sig)
            if st == 0x57F:
                return None
            return self._slow_stop(st, rip, K_PLAIN)
        orig = self._read(at, 1)
        os.pwrite(self.memfd, b"\xcc", at)
        result = self._run_until_break(at, sig)
        if result != "returned":
            return self._exited_during(rip, None, b"")
        os.pwrite(self.memfd, orig, at)
        if at == rip:
            st = self._restep(tid, 0)
            if st == 0x57F:
                return None
            return self._slow_stop(st, rip, K_PLAIN)
        return None

    def _int3(self, rip: int) -> TraceEnd:
        pt.getregs(self.tid, self.regs)
        asm = self._asm(rip)[0] or "int3"
        self._step_done(rip, None, b"", final=True)
        error = (f"Команда `{asm}` на шаге {self.i} по адресу {_h(rip)}: точка останова "
                 "(исключение Windows 0x80000003) без отладчика — Wine завершил программу")
        self._resume(self.tid, signal.SIGTRAP)
        self._wait_exit()
        return self._end("crashed", error)

    def _fault(self, rip: int, sig: int) -> TraceEnd:
        tid = self.tid
        info = pt.siginfo(tid)
        pt.getregs(tid, self.regs)
        asm = self._asm(rip)[0] or "?"
        text = _fault_text(sig, info.code, info.addr)
        error = f"Программа упала на шаге {self.i + 1}: команда `{asm}` по адресу {_h(rip)} — {text}"
        if self._classify(rip)[0] == K_RET:
            top = _u64(self._read(self.regs.rsp, 8))
            error += (f". На вершине стека [RSP={_h(self.regs.rsp)}] лежит {_h(top)} — "
                      "это не адрес возврата в программу")
        self._resume(tid, sig)
        code = self._wait_exit()
        if code is not None:
            error += f". Wine завершил процесс с кодом {code}"
        return self._end("crashed", error)

    def _leave(self, rip: int, k: int) -> TraceEnd:
        """Шаг увёл RIP из кода не вызовом: `ret` из точки входа или переход неизвестно куда."""
        new = self.regs.rip
        normal = k == K_RET and new == self.entry_ret
        self._step_done(rip, None, b"", final=True, alive=True)
        self._resume(self.tid, 0)
        code = self._wait_exit()
        self._tail_output()
        if normal:
            return self._end("exited", None, code)
        asm = self._asm(rip)[0] or "?"
        return self._end("crashed", f"Команда `{asm}` на шаге {self.i} увела программу из её "
                                    f"кода по адресу {_h(new)}; дальше она шла без трассы и "
                                    f"завершилась с кодом {code}")

    # ── вызов за пределы кода ────────────────────────────────────────────────

    def _call_out(self, pc: int, ret: int, name: str | None) -> TraceEnd | None:
        func = name.rsplit(".", 1)[-1] if name else ""
        if func in READS_STDIN:
            reads_stdin = func != "ReadFile" or self.regs.rcx == self.stdin_handle
            if reads_stdin and not self._feed():
                return self._end("waits_input",
                                 f"Программа ждёт ввод ({func}), а заданный ввод кончился")
        regs = self.regs
        if regs.eflags & pt.TF:
            regs.eflags &= ~pt.TF
            pt.setregs(self.tid, regs)
        orig = self._read(ret, 1)
        os.pwrite(self.memfd, b"\xcc", ret)
        result = self._run_until_break(ret, 0)
        out = self._take_output()
        if result == "returned":
            os.pwrite(self.memfd, orig, ret)
            self.stdin_pos = self._consumed()
            self._step_done(pc, name, out)
            if self.out_total > OUT_MAX:
                return self._end("crashed", f"Программа вывела больше {OUT_MAX // 1024} КБ — "
                                            "прогон остановлен")
            return None
        return self._exited_during(pc, name, out)

    def _exited_during(self, pc: int, name: str | None, out: bytes) -> TraceEnd:
        func = name.rsplit(".", 1)[-1] if name else ""
        self._step_done(pc, name, out, final=True, alive=False)
        if func in EXIT_FUNCS:
            return self._end("exited", None, self.exit_code)
        what = f"вызова {name}" if name else "вызова за пределы программы"
        return self._end("crashed", f"Программа завершилась внутри {what} на шаге {self.i} "
                                    f"(код выхода {self.exit_code})")

    def _run_until_break(self, at: int, sig: int) -> str:
        """`PTRACE_CONT` до своей `0xCC` по `at` в главном потоке: 'returned' или 'exited'."""
        tid = self.tid
        pt.call(pt.CONT, tid, 0, sig)
        while True:
            t, st = self._wait(-1)
            if os.WIFEXITED(st) or os.WIFSIGNALED(st):
                self.threads.discard(t)
                if t == self.pid:
                    self.alive = False
                    self.exit_code = os.WEXITSTATUS(st) if os.WIFEXITED(st) else -os.WTERMSIG(st)
                    return "exited"
                continue
            if not os.WIFSTOPPED(st):
                continue
            s = os.WSTOPSIG(st)
            ev = st >> 16
            if ev == pt.EV_CLONE:
                self.threads.add(pt.eventmsg(t))
                self._resume(t, 0)
                continue
            if ev:
                self._resume(t, 0)
                continue
            if s == signal.SIGSTOP and t not in self.seen_stop:
                self.seen_stop.add(t)
                self._resume(t, 0)
                continue
            if s == signal.SIGTRAP:
                info = pt.siginfo(t)
                if info.code == pt.SI_KERNEL and t == tid:
                    pt.getregs(t, self.regs)
                    if self.regs.rip == at + 1:
                        self.regs.rip = at
                        pt.setregs(t, self.regs)
                        return "returned"
                if info.code in (pt.TRAP_TRACE, pt.TRAP_BRKPT, pt.TRAP_HWBKPT):
                    self._resume(t, 0)
                    continue
            self._resume(t, s)

    def _wait_exit(self) -> int | None:
        """Процесс отпущен: дождаться выхода, доставляя сигналы. Код выхода."""
        while self.alive:
            t, st = self._wait(-1)
            if os.WIFEXITED(st) or os.WIFSIGNALED(st):
                self.threads.discard(t)
                if t == self.pid:
                    self.alive = False
                    self.exit_code = os.WEXITSTATUS(st) if os.WIFEXITED(st) else -os.WTERMSIG(st)
                continue
            if not os.WIFSTOPPED(st):
                continue
            s = os.WSTOPSIG(st)
            if (st >> 16) or s == signal.SIGSTOP:
                self._resume(t, 0)
                continue
            if s == signal.SIGTRAP:
                info = pt.siginfo(t)
                if info.code in (pt.TRAP_TRACE, pt.TRAP_BRKPT, pt.TRAP_HWBKPT):
                    self._resume(t, 0)
                    continue
            self._resume(t, s)
        return self.exit_code

    # ── вывод ────────────────────────────────────────────────────────────────

    @staticmethod
    def _drain(fd: int, limit: int) -> bytes:
        chunks = []
        total = 0
        while total < limit:
            try:
                part = os.read(fd, min(65536, limit - total))
            except OSError:
                break
            if not part:
                break
            chunks.append(part)
            total += len(part)
        return b"".join(chunks)

    def _take_output(self) -> bytes:
        room = max(0, OUT_MAX + 1 - self.out_total)
        data = self._drain(self.out_r, room) if room else b""
        err = self._drain(self.err_r, max(0, room - len(data))) if room > len(data) else b""
        out = data + err
        self.out_total += len(out)
        return out

    def _tail_output(self) -> None:
        """Остаток stdout/stderr после конца: в сырой вывод, программе он уже не принадлежит."""
        rest = self._drain(self.out_r, 4096) + self._drain(self.err_r, 4096)
        if rest and self.raw_fh is not None and self.raw_off < RAW_MAX:
            text = rest.decode("utf-8", "replace").rstrip("\n").replace("\n", "\n# ")
            line = f"# {text}\n".encode("utf-8")
            self.raw_fh.write(line)
            self.raw_off += len(line)

    # ── шаги ─────────────────────────────────────────────────────────────────

    def _step_done(self, pc: int, call: str | None, out: bytes, *, final: bool = False,
                   alive: bool = True) -> None:
        self.i += 1
        i = self.i
        regs = self.regs
        writes = None
        dumps: list = []
        if i <= self.dump_steps and alive and self.alive:
            writes = []
            for n, (lo, hi) in enumerate(self.image.data_windows):
                data = self._read(lo, hi - lo)
                old = self.win_prev[n]
                if data != old:
                    _diff(lo, old, data, lo, writes)
                    self.win_prev[n] = data
            stack_lo = regs.rsp - STACK_BELOW
            stack = self._read(stack_lo, STACK_BELOW + self.image.stack_window)
            if self.stack_prev is not None:
                plo, pdata = self.stack_prev
                a = max(plo, stack_lo)
                b = min(plo + len(pdata), stack_lo + len(stack))
                if a < b:
                    _diff(a, pdata[a - plo:b - plo], stack[a - stack_lo:b - stack_lo], regs.rsp,
                          writes)
            self.stack_prev = (stack_lo, stack)
        elif (i > self.dump_steps and self.sink is not None and alive and self.alive
              and (final or i >= self.limits.step_limit)):
            for lo, hi in self.image.data_windows:
                dumps.append((lo, self._read(lo, hi - lo)))
            dumps.append((regs.rsp, self._read(regs.rsp, self.image.stack_window)))
        next_pc = None if final or not alive else regs.rip
        self._emit_state(i, pc, next_pc, writes, dumps, out, call)
        if self.stop_at is not None and i == self.stop_at and alive and self.alive and not final:
            self._capture_memory()
        elif self.stop_at is not None and i == self.stop_at and final and alive and self.alive:
            self._capture_memory()

    def _capture_memory(self) -> None:
        self.memory = [(va, self._read(va, n)) for va, n in self.ranges]
        self.stop = "memory"

    def _regs_dict(self) -> dict[str, int]:
        r = self.regs
        return {"rax": r.rax, "rbx": r.rbx, "rcx": r.rcx, "rdx": r.rdx, "rsi": r.rsi,
                "rdi": r.rdi, "rbp": r.rbp, "rsp": r.rsp, "r8": r.r8, "r9": r.r9,
                "r10": r.r10, "r11": r.r11, "r12": r.r12, "r13": r.r13, "r14": r.r14,
                "r15": r.r15, "rip": r.rip, "rflags": r.eflags, "cs": r.cs, "ds": r.ds,
                "ss": r.ss, "es": r.es, "fs": r.fs, "gs": r.gs}

    def _emit_state(self, i: int, pc: int | None, next_pc: int | None, writes, dumps,
                    out: bytes, call: str | None) -> None:
        if self.sink is None:
            return
        regs = self._regs_dict()
        asm, code = self._asm(pc)
        next_asm, next_code = self._asm(next_pc)
        prev = self.prev
        changed = regs if prev is None else {k: v for k, v in regs.items() if prev[k] != v}
        raw = self._raw_line(i, pc, asm, changed, writes, out, call)
        self.sink(RawStep(i=i, pc=pc, asm=asm, bytes=code, regs=regs, next_pc=next_pc,
                          next_asm=next_asm, next_bytes=next_code, writes=writes, dumps=dumps,
                          out=out, stdin_pos=self.stdin_pos, call=call, raw=raw))
        self.prev = regs
        if self.progress is not None and i % PROGRESS_EVERY == 0:
            self.progress(i)

    def _raw_line(self, i: int, pc: int | None, asm: str, changed: dict[str, int], writes,
                  out: bytes, call: str | None) -> tuple[str, int, int] | None:
        """Строка сырого вывода: регистры — только изменившиеся (у шага 0 — все)."""
        if self.raw_fh is None or self.raw_off >= RAW_MAX:
            return None
        parts = [f"{i:>6} {_h(pc) if pc is not None else '-' * 16}  {asm or '(вход)':<36}"]
        upper = _UPPER
        parts.extend(f"{upper[name]}={value:X}" for name, value in changed.items())
        if call:
            parts.append(f"call={call}")
        for va, old, new in (writes or ())[:4]:
            parts.append(f"[{va:X}]={old.hex().upper()}>{new.hex().upper()}")
        if writes and len(writes) > 4:
            parts.append(f"(+{len(writes) - 4} записей)")
        if out:
            parts.append("out=" + repr(out[:80].decode("utf-8", "replace")))
        line = (" ".join(parts) + "\n").encode("utf-8")
        off = self.raw_off
        self.raw_fh.write(line)
        self.raw_off += len(line)
        return (self.t.raw_name, off, len(line))

    # ── конец ────────────────────────────────────────────────────────────────

    def _stopped(self) -> TraceEnd:
        if self.stop == "memory":
            return self._end("exited", None)
        return self._end(self.stop or "timeout", None)

    def _end(self, status: str, error: str | None, exit_code: int | None = None) -> TraceEnd:
        if status == "timeout" and error is None:
            error = "Прогон не уложился в отведённое время"
        if status == "cancelled":
            error = "Прогон отменён"
        if status in ("exited",) and exit_code is None:
            exit_code = self.exit_code
        return TraceEnd(status=status, exit_code=exit_code if status == "exited" else None,  # type: ignore[arg-type]
                        error=error, load=dict(self.load))

    def _cleanup(self) -> None:
        self.cleanup_guard = time.monotonic() + 5
        if self.alive and self.pid:
            try:
                os.kill(self.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            try:
                while self.alive:
                    t, st = self._wait(-1)
                    if (os.WIFEXITED(st) or os.WIFSIGNALED(st)) and t == self.pid:
                        self.alive = False
            except (_Stop, ChildProcessError):
                self.alive = False
        if self.raw_fh is not None:
            try:
                self._tail_output()
            except (OSError, ValueError):
                pass
            self.raw_fh.close()
        for fd in (self.memfd, self.in_r, self.in_w, self.out_r, self.err_r):
            if fd >= 0:
                try:
                    os.close(fd)
                except OSError:
                    pass
        self.memfd = self.in_r = self.in_w = self.out_r = self.err_r = -1


READS_STDIN = READ_FUNCS

__all__ = ["WineTracer", "RAW_NAME", "EXE_NAME", "OUT_MAX", "RAW_MAX"]
