"""runner.py — сборка, трасса и память на шаге.

    build(req, tools, workdir, timeout_s)            TASM → TLINK, листинг, карта, символы
    run(req, tools, workdir, timeout_s, …)           сборка → трасса целиком
    memory_at(req, tools, workdir, step, ranges, …)  перезапуск до шага и дампы диапазонов

**Трасса снимается одним сценарием DebugX.** Сценарий — `R`, дальше `T` на каждый шаг
(пока шагов с дампами) или пачками `T n`, после шагов — `D` окон данных и стека. Вывод
разбирается потоком, пока DOSBox-X ещё работает: как только ясно, что дальше продолжать нельзя
или незачем (программа завершилась, ждёт ввод, которого сценарий не подал, пачка оборвалась на
INT 3), эмулятор гасится, а не дожидается конца сценария.

**Ввод программы подбирается перезапусками.** Где программа читает, заранее не известно: это
видно только по регистрам перед `int 21h`. Первый запуск идёт без ввода; найдя шаг, на котором
программа прочтёт stdin, ядро гасит эмулятор, вписывает в план байты для этого шага (сколько
именно съест чтение — `feed.py`) и запускает заново. Прогон детерминирован, поэтому начало
трассы повторяется байт в байт, и каждый перезапуск продвигается хотя бы на одно чтение.
Потолок — `MAX_RESTARTS`.

**Пачки `T n` и обрывы.** Счётчик `T` шестнадцатеричный и не больше FFFF. Пачка обрывается
раньше срока на INT 3 в программе; тогда шаг обрыва вписывается в план как граница пачки, и
трасса снимается заново — иначе ввод, привязанный к номеру шага, уехал бы.

**Время запуска.** `-time-limit` каждого запуска — не остаток общего таймаута, а оценка по
сценарию: старт эмулятора `LAUNCH_S` и `TIME_MARGIN` раз цена его команд (одиночная `T`, шаг
пачки, строка дампа — замеры в `samples/command.txt`). Причина — зависшая программа: вывод
DebugX на диске появляется только при выходе эмулятора, поэтому разбор на лету зависания не
видит, и без своего потолка прогон ждал бы весь общий таймаут. Эмулятор, вышедший по
`-time-limit`, свой вывод дописал; он разбирается, и прогон кончается `timeout` с шагами до
места зависания и причиной в `error` — по последней команде, которую DebugX не довёл до конца.
Общий таймаут остаётся верхней границей: оценка, не влезающая в остаток, урезается до него.

Трасса с дампами снимается ступенями: сначала `FIRST_REACH` шагов, дальше в `REACH_GROWTH` раз
больше, до лимита. При лимите в сотню тысяч шагов оценка полного сценария — десятки секунд, и
программа, повисшая на пятом шаге, ждала бы их; первая ступень гасит её за несколько секунд.
Ступень, дошедшая до своего конца, — перезапуск со следующей, как у ввода: начало трассы
повторяется байт в байт, а лишняя работа — меньше десятой части длинного прогона.

**Память.** Окно данных (сегменты данных из `.map`, до `DATA_WINDOW_MAX` байт) и окно стека
(`STACK_WINDOW` байт под SP при загрузке) дампятся после каждого шага, пока шагов не больше
`DUMP_STEPS_MAX` и пока строк дампа не больше `DUMP_LINES_BUDGET` — вывод DebugX в DOSBox-X
идёт примерно 50 мкс на строку, и дампы большого окна на каждом шаге съели бы всё время
прогона. Дальше дампы — только на границах пачек, `mem` у шагов пуст, остальное —
`memory_at`.

**Что пишется в каталог прогона.** `prog.asm/.obj/.exe/.lst/.map`, `tasm.txt`, `tlink.txt`,
`script<N>.txt` и `debugx<N>.txt` каждой попытки, `debugx.idx.json` (где в сыром выводе
последней попытки блок каждого сохранённого шага), `trace.jsonl` (шаги построчно),
`summary.json` (итог без шагов), `plan.json` (подобранный ввод — им пользуется `memory_at`).
`memory_at` пишет свои файлы под именами `m<метка>…` (метка своя у каждого вызова: дампов на
одной трассе бывает несколько сразу, а DOS видит только имена 8.3) и после удачного дампа их
убирает; неудачный оставляет их для разбора.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import dosbox
from .debugx import Block, Parser, dump_command
from .feed import ENCODING, Feed, Read, read_at, waits_keyboard, normalize
from .linkmap import parse_map
from ..model import (АсмОшибка, BuildMessage, BuildResult, Dump, ListingLine, MemWrite,
                     RunRequest, RunResult, Segment, Step, Truncation)
from ..sink import HEAD, TAIL, TraceSink
from ..toolchain import Cancelled, Progress
from .tasm import parse_listing, parse_symbols, tasm_messages, tlink_messages
from .tools import Tools, find_file

# Индекс сырого вывода DebugX: где в `debugx<N>.txt` блок каждого шага трассы.
RAW_INDEX = "debugx.idx.json"
# Версия, которую итог называет, когда запрос её не несёт (голый `RunRequest`).
DEFAULT_VERSION = "4.1"

SOURCE_MAX = 512_000            # знаков исходника
STDIN_MAX = 64_000              # знаков ввода
STEP_LIMIT_CEIL = 1_000_000     # потолок ядра; потолок продукта ставит служба
FLAGS_MAX = 16

CHUNK = 0x1000                  # шагов в пачке `T n` за пределами пошаговых дампов
DUMP_STEPS_MAX = 5000
DUMP_LINES_BUDGET = 60_000
DATA_WINDOW_MAX = 0x400
STACK_WINDOW = 0x80
# HEAD, TAIL и потолок целой трассы — в `sink.py`: свёртка у всех наборов одна.
MAX_RESTARTS = 96               # 64 чтения ввода и запас на обрывы пачек и ступени
FIRST_REACH = 500               # шагов в первой ступени трассы с дампами
REACH_GROWTH = 16
# Цена сценария, с. Замеры: 10 000 шагов `T` одной пачкой — 1,5 с, 100 000 — 6,2 с; `T` по
# шагу с дампом двух окон по 40h байт — 0,8 мс на шаг, из них дамп — 10 строк по 50 мкс.
LAUNCH_S = 2.0                  # старт DOSBox-X и загрузка DebugX, с запасом на занятую машину
STEP_S = 0.3e-3                 # одиночная `T`
CHUNK_STEP_S = 0.1e-3           # шаг внутри пачки `T n`
DUMP_LINE_S = 50e-6             # строка дампа `D`
TIME_MARGIN = 3
POLL_S = 0.05
PROGRESS_EVERY_S = 0.25

_FLAG = re.compile(r"^/[A-Za-z0-9][A-Za-z0-9:=._+\-]{0,31}$")
_HEX = re.compile(r"^[0-9A-Fa-f]{1,4}$")


# ── общее ────────────────────────────────────────────────────────────────────

def _check(req: RunRequest) -> None:
    if not isinstance(req.source, str) or len(req.source) > SOURCE_MAX:
        raise АсмОшибка(f"Исходник длиннее {SOURCE_MAX} знаков")
    if not isinstance(req.stdin, str) or len(req.stdin) > STDIN_MAX:
        raise АсмОшибка(f"Ввод программы длиннее {STDIN_MAX} знаков")
    if not isinstance(req.step_limit, int) or not 1 <= req.step_limit <= STEP_LIMIT_CEIL:
        raise АсмОшибка(f"Лимит шагов — от 1 до {STEP_LIMIT_CEIL}")
    for flags, tool in ((req.tasm_flags, "TASM"), (req.tlink_flags, "TLINK")):
        if len(flags) > FLAGS_MAX:
            raise АсмОшибка(f"У {tool} больше {FLAGS_MAX} ключей")
        for flag in flags:
            # Ключи уезжают в командную строку DOS: `>`, `|` и пробел в них — это уже не
            # ключ, а вторая команда.
            if not isinstance(flag, str) or not _FLAG.match(flag):
                raise АсмОшибка(f"Недопустимый ключ {tool}: {flag!r}")


def _dos_text(text: str) -> bytes:
    body = text.replace("\r\n", "\n").replace("\r", "\n")
    if not body.endswith("\n"):
        body += "\n"
    return body.replace("\n", "\r\n").encode(ENCODING, "replace")


def _read_dos(path: Path) -> str:
    try:
        return path.read_bytes().decode(ENCODING, "replace").replace("\r\n", "\n")
    except OSError:
        return ""


def _remove(workdir: Path, name: str) -> None:
    for entry in list(workdir.iterdir()):
        if entry.name.upper() == name.upper() and entry.is_file():
            entry.unlink()


def _lowercase(workdir: Path, name: str) -> Path | None:
    """Файлы, созданные из DOS, названы ВЕРХНИМ регистром; договор с сайтом — нижним."""
    found = find_file(workdir, name)
    if found is None:
        return None
    target = workdir / name.lower()
    if found.name != target.name:
        found.rename(target)
    return target


def _out_text(raw: bytes) -> str:
    return raw.decode(ENCODING, "replace").replace("\r\n", "\n")


def _h4(v: int) -> str:
    return f"{v & 0xFFFF:04X}"


def _h8(v: int) -> str:
    return f"{v & 0xFFFFFFFF:08X}"


def _request_key(req: RunRequest) -> str:
    raw = json.dumps([req.source, normalize(req.stdin), req.mode32, list(req.tasm_flags),
                      list(req.tlink_flags)], ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _target(req: RunRequest) -> str:
    com = any(f.lower() in ("/t", "/tdc") for f in req.tlink_flags)
    return "PROG.COM" if com else "PROG.EXE"


def _write_json(path: Path, data) -> None:
    # Временное имя своё у процесса: `plan.json` пишут и дампы памяти, идущие параллельно.
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


# ── сборка ───────────────────────────────────────────────────────────────────

@dataclass
class _Built:
    result: BuildResult
    target: str
    probe: Block | None = None
    timed_out: bool = False
    cancelled: bool = False


def _build(req: RunRequest, tools: Tools, workdir: Path, deadline: float,
           progress: Progress | None, cancelled: Cancelled | None) -> _Built:
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / "exec").mkdir(exist_ok=True)
    target = _target(req)
    for name in ("PROG.ASM", "PROG.OBJ", "PROG.EXE", "PROG.COM", "PROG.LST", "PROG.MAP",
                 "TASM.TXT", "TLINK.TXT", "PROBE.TXT", "PROBE.OUT", "BUILD.BAT"):
        _remove(workdir, name)
    (workdir / "prog.asm").write_bytes(_dos_text(req.source))
    (workdir / "probe.txt").write_bytes(b"R\r\nQ\r\n")
    for name in ("tasm.txt", "tlink.txt", "probe.out"):
        (workdir / name).write_bytes(b"")

    tasm_flags = list(req.tasm_flags)
    # Без листинга трасса не знает строк исходника, а это половина окна отладчика.
    if not any(f.lower().startswith("/l") for f in tasm_flags):
        tasm_flags.append("/l")
    tasm = dosbox.dos_name(tools.tool_file("TASM.EXE") or Path("TASM.EXE"))
    tlink = dosbox.dos_name(tools.tool_file("TLINK.EXE") or Path("TLINK.EXE"))
    debugx = dosbox.dos_name(tools.debugx)

    # `goto`, а не `if exist … > файл`: оболочка DOSBox открывает перенаправление раньше, чем
    # проверяет условие, и создаёт файл даже при ложном.
    dosbox.write_bat(workdir, "build.bat", [
        "@echo off",
        "cd \\",
        f"D:\\{tasm} {' '.join(tasm_flags)} PROG.ASM > C:\\TASM.TXT",
        "if not exist C:\\PROG.OBJ goto end",
        f"D:\\{tlink} {' '.join(req.tlink_flags)} PROG.OBJ > C:\\TLINK.TXT",
        f"if not exist C:\\{target} goto end",
        "cd \\EXEC",
        f"E:\\{debugx} /s C:\\{target} < C:\\PROBE.TXT > C:\\PROBE.OUT",
        ":end",
    ])
    conf = dosbox.write_conf(workdir, "build.conf",
                             dosbox.autoexec_prefix(tools) + ["CALL C:\\BUILD.BAT", "exit"])

    if progress:
        progress("tasm", 0, 1)
    timed_out = was_cancelled = False
    linking = False
    seconds = max(1.0, deadline - time.monotonic())
    with dosbox.Process(tools, workdir, conf, seconds=seconds, log_name="build.log") as proc:
        while proc.poll() is None:
            if not linking and find_file(workdir, "PROG.OBJ") is not None:
                linking = True
                if progress:
                    progress("tlink", 0, 1)
            if cancelled and cancelled():
                was_cancelled = True
                break
            if time.monotonic() > deadline:
                timed_out = True
                break
            time.sleep(POLL_S)

    for name in ("PROG.OBJ", "PROG.EXE", "PROG.COM", "PROG.LST", "PROG.MAP"):
        _lowercase(workdir, name)

    tasm_log = _read_dos(workdir / "tasm.txt")
    tlink_log = _read_dos(workdir / "tlink.txt")
    messages = tasm_messages(tasm_log) + tlink_messages(tlink_log)
    lst = _read_dos(workdir / "prog.lst")
    listing = parse_listing(lst) if lst else []
    symbols = parse_symbols(lst) if lst else []
    segments, _entry = parse_map(_read_dos(workdir / "prog.map"))
    has_obj = (workdir / "prog.obj").exists()
    has_exe = (workdir / target.lower()).exists()

    errors = [m for m in messages if m.severity == "error"]
    ok = has_exe and not errors and not timed_out and not was_cancelled
    if not ok and not errors:
        if was_cancelled:
            text, tool = "Сборка отменена", "tasm"
        elif timed_out:
            text, tool = "Сборка не уложилась в отведённое время", "tasm"
        elif not has_obj:
            text, tool = "TASM не создал объектный файл — подробности в логе сборки", "tasm"
        else:
            text, tool = "TLINK не создал исполняемый файл — подробности в логе сборки", "tlink"
        messages.append(BuildMessage(severity="error", tool=tool, line=None, text=text))

    log = tasm_log
    if tlink_log:
        log = (log.rstrip("\n") + "\n\n" + tlink_log) if log else tlink_log
    result = BuildResult(ok=ok, log=log, messages=messages, listing=listing,
                         segments=segments, symbols=symbols)

    probe = None
    if ok:
        parser = Parser()
        try:
            parser.feed((workdir / "probe.out").read_bytes())
        except OSError:
            pass
        parser.finish()
        probe = parser.blocks[0] if parser.blocks else None
    return _Built(result=result, target=target, probe=probe, timed_out=timed_out,
                  cancelled=was_cancelled)


def build(req: RunRequest, tools: Tools, workdir: Path, *, timeout_s: float) -> BuildResult:
    """Собрать программу. Ошибки программы — в `BuildResult.messages`, не исключением."""
    _check(req)
    return _build(req, tools, Path(workdir), time.monotonic() + timeout_s, None, None).result


# ── адреса и окна ────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class _Window:
    seg: int
    off: int
    length: int

    @property
    def lines(self) -> int:
        return (self.length + 15) // 16 + 1


def _load_seg(target: str, regs: dict[str, int]) -> int:
    """Сегмент, с которого лёг образ: у EXE — PSP+10h, у COM — сам PSP (образ с 0100h)."""
    if target.endswith(".COM"):
        return regs["cs"]
    return (regs["ds"] + 0x10) & 0xFFFF


def _windows(target: str, segments: list[Segment], regs: dict[str, int]) -> tuple[list[_Window], int]:
    """Окна дампа и сегмент данных программы.

    Данные — сегменты `.map`, кроме кода и стека, слитые в сплошные куски и обрезанные до
    `DATA_WINDOW_MAX`. Сегмент окна — параграф начала куска: у `.model small` это ровно
    DGROUP, то есть то, что программа положит в DS. У COM сегментов данных нет, данные живут
    в коде, и окном берётся образ с 0100h.
    """
    load = _load_seg(target, regs)
    base = load * 16
    regions: list[list[int]] = []
    if target.endswith(".COM"):
        image_end = max((int(s.start, 16) + int(s.length, 16) for s in segments), default=0)
        start = base + 0x100
        regions.append([start, base + max(image_end, 0x110)])
    else:
        for s in sorted(segments, key=lambda s: int(s.start, 16)):
            if s.cls in ("CODE", "STACK") or s.name == "STACK" or int(s.length, 16) == 0:
                continue
            a = base + int(s.start, 16)
            b = a + int(s.length, 16)
            if regions and a <= regions[-1][1] + 16:
                regions[-1][1] = max(regions[-1][1], b)
            else:
                regions.append([a, b])

    windows: list[_Window] = []
    budget = DATA_WINDOW_MAX
    for a, b in regions:
        if budget <= 0:
            break
        frame = a >> 4
        off = (a - frame * 16) & 0xFFF0
        length = min(b - frame * 16 - off, budget, 0x10000 - off)
        length = (length + 15) & ~15
        if length > 0:
            windows.append(_Window(frame & 0xFFFF, off, length))
            budget -= length
    data_seg = windows[0].seg if windows else regs["ds"]

    top = regs["sp"] or 0x10000
    start = max(0, top - STACK_WINDOW) & 0xFFF0
    if top - start > 0:
        windows.append(_Window(regs["ss"], start, min(top - start, 0x10000 - start)))
    return windows, data_seg


class _Lines:
    """CS:IP → строка исходника по листингу и карте."""

    def __init__(self, listing: list[ListingLine], segments: list[Segment], load: int) -> None:
        self.base = load * 16
        self.segments = [(s.name, s.cls, int(s.start, 16), int(s.length, 16)) for s in segments]
        self.exact: dict[tuple[str, int], int] = {}
        self.loose: dict[int, int] = {}
        code = {s.name for s in segments if s.cls == "CODE"}
        for ln in listing:
            if not ln.offset or not ln.bytes:
                continue
            off = int(ln.offset, 16)
            if ln.segment:
                self.exact.setdefault((ln.segment.upper(), off), ln.line)
            if ln.segment is None or ln.segment.upper() in code or not code:
                self.loose.setdefault(off, ln.line)
        self.single_code = len(code) <= 1

    def at(self, cs: int, ip: int) -> int | None:
        linear = cs * 16 + ip
        for name, cls, start, length in self.segments:
            a = self.base + start
            if a <= linear < a + max(length, 1):
                line = self.exact.get((name, linear - a))
                if line is None and cls == "CODE" and self.single_code:
                    line = self.loose.get(linear - a)
                return line
        if not self.segments:
            return self.loose.get(ip)
        return None


# ── план ввода ───────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class _Injection:
    data: bytes
    set_cx: int | None = None
    orig_cx: int | None = None


@dataclass
class _Plan:
    key: str
    reads: dict[int, _Injection] = field(default_factory=dict)
    stops: set[int] = field(default_factory=set)

    def to_json(self) -> dict:
        return {"version": 1, "key": self.key,
                "reads": {str(k): {"data": v.data.hex().upper(), "set_cx": v.set_cx,
                                   "orig_cx": v.orig_cx} for k, v in sorted(self.reads.items())},
                "stops": sorted(self.stops)}

    @classmethod
    def load(cls, path: Path, key: str) -> "_Plan":
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if raw.get("version") != 1 or raw.get("key") != key:
                return cls(key)
            reads = {int(k): _Injection(bytes.fromhex(v["data"]), v.get("set_cx"), v.get("orig_cx"))
                     for k, v in raw.get("reads", {}).items()}
            return cls(key, reads, set(int(x) for x in raw.get("stops", [])))
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            return cls(key)


# ── трасса ───────────────────────────────────────────────────────────────────

_REG16 = ("ax", "bx", "cx", "dx", "si", "di", "bp", "sp", "ip", "cs", "ds", "ss", "es", "flags")
_REG32 = ("eax", "ebx", "ecx", "edx", "esi", "edi", "ebp", "esp", "eip", "eflags", "fs", "gs")
_FLAGS = ("of", "df", "if", "sf", "zf", "af", "pf", "cf")


class _Tracer:
    """Попытки снять трассу, пока план ввода и границ пачек не сойдётся с программой."""

    def __init__(self, req: RunRequest, tools: Tools, workdir: Path, built: _Built, *,
                 deadline: float, limit: int, plan: _Plan, dumps: bool,
                 progress: Progress | None, cancelled: Cancelled | None,
                 final_ranges: list[tuple[int, int, int]] | None = None,
                 tag: str | None = None, staged: bool = False) -> None:
        self.req, self.tools, self.workdir, self.built = req, tools, workdir, built
        self.deadline, self.limit, self.plan = deadline, limit, plan
        self.progress, self.cancelled = progress, cancelled
        self.with_dumps = dumps
        self.final_ranges = final_ranges
        self.tag = tag
        # Сколько шагов снимает текущая ступень (см. шапку модуля); без ступеней — сразу все.
        self.reach = min(limit, FIRST_REACH) if staged else limit
        self.cost = 0.0
        self.attempt = 0
        self.status = "crashed"
        self.error: str | None = None
        self.exit_code: int | None = None
        self.steps = 0
        self.truncated: Truncation | None = None
        self.dumps: list[Dump] = []
        self.final_dumps: list[Dump] = []
        self.load_regs = dict(built.probe.regs) if built.probe else {}
        self.load_checked = False
        self._layout()

    def _layout(self) -> None:
        br = self.built.result
        self.windows, self.data_seg = _windows(self.built.target, br.segments, self.load_regs)
        self.lines = _Lines(br.listing, br.segments, _load_seg(self.built.target, self.load_regs))
        if self.with_dumps and self.windows:
            per_step = sum(w.lines for w in self.windows)
            self.dump_steps = min(DUMP_STEPS_MAX, DUMP_LINES_BUDGET // per_step, self.limit)
        else:
            self.dump_steps = 0

    # ── сценарий ──

    def _script(self) -> bytes:
        """Сценарий текущей ступени; попутно — его цена в секундах (`self.cost`)."""
        out = bytearray()
        self.cost = 0.0

        def cmd(text: str) -> None:
            out.extend(text.encode("ascii") + b"\r\n")

        def dumps(ws) -> None:
            for w in ws:
                cmd(dump_command(w.seg, w.off, w.length))
                self.cost += ((w.length + 15) // 16 + 1) * DUMP_LINE_S

        reads = sorted(self.plan.reads)
        stops = sorted(self.plan.stops)
        if self.req.mode32:
            cmd("RX")
        cmd("R")
        if self.with_dumps:
            dumps(self.windows)
        s = 0
        while s < self.reach:
            k = s + 1
            inj = self.plan.reads.get(k)
            if inj is not None:
                if inj.set_cx is not None:
                    cmd(f"R CX {inj.set_cx:X}")
                cmd("T")
                self.cost += STEP_S
                out.extend(inj.data)
                if inj.set_cx is not None and inj.orig_cx is not None:
                    cmd(f"R CX {inj.orig_cx:X}")
                n = 1
            elif k <= self.dump_steps:
                cmd("T")
                self.cost += STEP_S
                n = 1
            else:
                n = min(CHUNK, self.reach - s)
                if self.with_dumps:
                    n = min(n, CHUNK - (s - self.dump_steps) % CHUNK)
                nxt = next((r for r in reads if r > k), None)
                if nxt is not None:
                    n = min(n, nxt - 1 - s)
                stop = next((t for t in stops if t > s), None)
                if stop is not None:
                    n = min(n, stop - s)
                n = max(1, n)
                cmd("T" if n == 1 else f"T {n:X}")
                self.cost += STEP_S if n == 1 else n * CHUNK_STEP_S
            s += n
            if self.with_dumps and (s <= self.dump_steps
                                    or (s - self.dump_steps) % CHUNK == 0 or s == self.reach):
                dumps(self.windows)
        if self.final_ranges and self.reach == self.limit:
            dumps(_Window(seg, off, length) for seg, off, length in self.final_ranges)
        cmd("Q")
        return bytes(out)

    # ── попытки ──

    def run(self) -> None:
        while True:
            self.attempt += 1
            if self.attempt > MAX_RESTARTS + 1:
                self.status = "crashed"
                self.error = "Трасса не сошлась: слишком много перезапусков ради ввода программы"
                return
            verdict = self._attempt()
            if verdict != "restart":
                return

    def _names(self, n: int) -> tuple[str, str, str, str, str]:
        """Сценарий, вывод, пакетный файл (их видит DOS — 8.3), conf и журнал попытки `n`."""
        if self.tag is None:
            return f"script{n}.txt", f"debugx{n}.txt", "trace.bat", "trace.conf", "trace.log"
        return (f"m{self.tag}s{n}.txt", f"m{self.tag}o{n}.txt", f"m{self.tag}.bat",
                f"memory-{self.tag}.conf", f"memory-{self.tag}.log")

    def _attempt(self) -> str:
        script_name, out_name, bat, conf_name, log_name = self._names(self.attempt)
        (self.workdir / script_name).write_bytes(self._script())
        out_path = self.workdir / out_name
        out_path.write_bytes(b"")
        debugx = dosbox.dos_name(self.tools.debugx)
        dosbox.write_bat(self.workdir, bat, [
            "@echo off",
            "cd \\EXEC",
            f"E:\\{debugx} /s C:\\{self.built.target} < C:\\{script_name.upper()} > C:\\{out_name.upper()}",
        ])
        conf = dosbox.write_conf(self.workdir, conf_name,
                                 dosbox.autoexec_prefix(self.tools)
                                 + [f"CALL C:\\{bat.upper()}", "exit"])
        walk = _Walk(self, Parser(), out_name)
        wanted = LAUNCH_S + TIME_MARGIN * self.cost
        # Секунда на выход эмулятора и разбор: вывод дописывается на диск при выходе, и
        # эмулятор должен выйти сам раньше, чем кончится общий таймаут.
        left = self.deadline - time.monotonic() - 1.0
        clipped = wanted > left
        seconds = max(1.0, min(wanted, left))
        last_progress = 0.0
        with dosbox.Process(self.tools, self.workdir, conf, seconds=seconds,
                            log_name=log_name) as proc, \
                open(out_path, "rb") as fh:
            while True:
                exited = proc.poll() is not None
                chunk = fh.read()
                if chunk:
                    walk.parser.feed(chunk)
                if exited:
                    rest = fh.read()
                    if rest:
                        walk.parser.feed(rest)
                    walk.parser.finish()
                verdict = walk.advance(final=exited)
                if verdict is not None:
                    return walk.close(verdict)
                if exited:
                    reached = len(walk.parser.blocks) - 1 >= self.reach
                    if reached and self.reach < self.limit:
                        self.reach = min(self.limit, self.reach * REACH_GROWTH)
                        return walk.close("restart")
                    if not reached and proc.ran_out():
                        return walk.close("timeout" if clipped else "stalled")
                    return walk.close("exited")
                if self.cancelled and self.cancelled():
                    return walk.close("cancelled")
                if proc.overdue():
                    # Не вышел и по `-time-limit`: убит, и вывода, скорее всего, нет.
                    proc.kill()
                    rest = fh.read()
                    if rest:
                        walk.parser.feed(rest)
                    walk.parser.finish()
                    walk.advance(final=True)
                    return walk.close("timeout" if clipped else "stalled")
                now = time.monotonic()
                if self.progress and now - last_progress >= PROGRESS_EVERY_S:
                    last_progress = now
                    self.progress("trace", max(0, len(walk.parser.blocks) - 1), self.limit)
                time.sleep(POLL_S)


class _Walk:
    """Одна попытка: блоки разборщика → шаги, проверки перед каждым шагом."""

    def __init__(self, tracer: _Tracer, parser: Parser, out_name: str) -> None:
        self.t = tracer
        self.parser = parser
        self.out_name = out_name
        self.feed = Feed(tracer.req.stdin)
        self.sink = TraceSink(tracer.workdir, RAW_INDEX) if tracer.with_dumps else None
        self.seen = 0
        self.open: int | None = None
        self.dump_ptr = 0
        self.mem: dict[int, int] = {}
        self.stdin_marks: dict[int, int] = {}
        self.stdin_now = 0
        self.stop_reason: str | None = None
        self.stopped_at: int | None = None

    # ── проверки ──

    def advance(self, final: bool) -> str | None:
        p = self.parser
        blocks = p.blocks
        while self.seen < len(blocks):
            b = self.seen
            block = blocks[b]
            if b > self.t.reach:
                break
            if b == 0 and not self.t.load_checked:
                self.t.load_checked = True
                if self._load_moved(block):
                    return "restart"
            inj = self.t.plan.reads.get(b)
            if inj is not None and inj.set_cx is not None and inj.orig_cx is not None:
                block.regs["cx"] = inj.orig_cx
                if block.reg32 is not None:
                    block.reg32["ecx"] = (block.reg32["ecx"] & ~0xFFFF) | inj.orig_cx
            if self.open is not None:
                self._emit(self.open)
            self.open = b
            self.seen += 1
            for e in p.breaks_early:
                if e not in self.t.plan.stops and e < len(blocks):
                    self.t.plan.stops.add(e)
                    return "restart"
            if block.next is not None and b < self.t.reach:
                verdict = self._before_step(b + 1, block)
                if verdict is not None:
                    return verdict

        if p.errors and self.stop_reason is None:
            after, text = p.errors[0]
            self.t.error = (f"Вывод DebugX разошёлся со сценарием после шага {max(after, 0)}: "
                            f"{text}")
            return "desync"
        if p.terminated is not None and self.seen == len(blocks):
            return "terminated"
        if final and self.open is not None and self.seen == len(blocks):
            self._emit(self.open)
            self.open = None
        return None

    def _load_moved(self, block: Block) -> bool:
        """Сегменты при загрузке разошлись с пробным запуском — окна пересчитываются."""
        keys = ("cs", "ds", "ss", "sp")
        if all(block.regs.get(k) == self.t.load_regs.get(k) for k in keys):
            return False
        self.t.load_regs = dict(block.regs)
        self.t._layout()
        return True

    def _before_step(self, k: int, block: Block) -> str | None:
        nxt = block.next
        assert nxt is not None
        if waits_keyboard(nxt.asm, block.regs):
            self.stop_reason = (f"На шаге {k} программа ждёт клавиатуру через int 16h, а в "
                                f"пакетном прогоне клавиатуры нет — ввод читается через int 21h")
            self.stopped_at = k - 1
            return "stop"
        read = read_at(nxt.asm, block.regs)
        if read is None:
            return None
        data = self.feed.take(read)
        planned = self.t.plan.reads.get(k)
        if data is None:
            self.stop_reason = f"На шаге {k} программа ждёт ввод, а заданный ввод кончился"
            self.stopped_at = k - 1
            return "stop"
        inj = self._injection(read, data)
        self.stdin_marks[k] = self.feed.pos
        if planned == inj:
            return None
        self.t.plan.reads = {s: v for s, v in self.t.plan.reads.items() if s < k}
        self.t.plan.reads[k] = inj
        return "restart"

    @staticmethod
    def _injection(read: Read, data: bytes) -> _Injection:
        if read.kind == "bytes" and len(data) != read.cx:
            return _Injection(data, set_cx=len(data), orig_cx=read.cx)
        return _Injection(data)

    # ── шаги ──

    def _step_dumps(self, b: int) -> list:
        dumps = self.parser.dumps
        out = []
        while self.dump_ptr < len(dumps) and dumps[self.dump_ptr].after_block <= b:
            if dumps[self.dump_ptr].after_block == b:
                out.append(dumps[self.dump_ptr])
            self.dump_ptr += 1
        return out

    def _emit(self, b: int) -> None:
        t = self.t
        blocks = self.parser.blocks
        block = blocks[b]
        chunks = self._step_dumps(b)
        if self.sink is None:
            return
        if b in self.stdin_marks:
            self.stdin_now = self.stdin_marks[b]
        lines = t.lines
        if b == 0:
            ex = block.next
            cs, ip = (ex.cs, ex.ip) if ex else (block.regs["cs"], block.regs["ip"])
            asm, raw, line = "", "", None
            changed: list[str] = []
        else:
            prev = blocks[b - 1]
            ex = prev.next
            cs, ip = (ex.cs, ex.ip) if ex else (prev.regs["cs"], prev.regs["ip"])
            asm, raw = (ex.asm, ex.bytes) if ex else ("", "")
            line = lines.at(cs, ip)
            changed = self._changed(prev, block)

        mem: list[MemWrite] = []
        records: list[Dump] = []
        for c in chunks:
            if b == 0 or b > t.dump_steps:
                records.append(Dump(step=b, seg=_h4(c.seg), off=_h4(c.off), hex=c.data.hex().upper()))
            if b <= t.dump_steps:
                mem.extend(self._mem_diff(c, record=b > 0))
        self.sink.add_dumps(b, records)

        nxt = None
        if block.next is not None:
            nxt = {"cs": _h4(block.next.cs), "ip": _h4(block.next.ip),
                   "line": lines.at(block.next.cs, block.next.ip),
                   "asm": block.next.asm, "bytes": block.next.bytes}
        step = Step(i=b, cs=_h4(cs), ip=_h4(ip), line=line, asm=asm, bytes=raw,
                    reg={k: _h4(block.regs[k]) for k in _REG16},
                    reg32=self._reg32(block), changed=changed, mem=mem,
                    out=_out_text(block.out), stdin_pos=self.stdin_now, next=nxt)
        self.sink.add(step, {"i": b, "file": self.out_name, "offset": block.start,
                             "length": max(0, block.end - block.start)})

    def _emit_termination(self) -> None:
        term = self.parser.terminated
        blocks = self.parser.blocks
        if term is None or not blocks or self.sink is None:
            return
        last = blocks[-1]
        b = len(blocks)
        ex = last.next
        cs, ip = (ex.cs, ex.ip) if ex else (last.regs["cs"], last.regs["ip"])
        step = Step(i=b, cs=_h4(cs), ip=_h4(ip), line=self.t.lines.at(cs, ip),
                    asm=ex.asm if ex else "", bytes=ex.bytes if ex else "",
                    reg={k: _h4(last.regs[k]) for k in _REG16}, reg32=self._reg32(last),
                    changed=[], mem=[], out=_out_text(term.out), stdin_pos=self.stdin_now,
                    next=None)
        self.sink.add(step, {"i": b, "file": self.out_name, "offset": term.start,
                             "length": max(0, term.end - term.start)})

    def _reg32(self, block: Block) -> dict[str, str] | None:
        if not self.t.req.mode32 or block.reg32 is None:
            return None
        return {k: (_h4(v) if k in ("fs", "gs") else _h8(v)) for k, v in block.reg32.items()}

    def _changed(self, prev: Block, cur: Block) -> list[str]:
        out = [k for k in _REG16 if k not in ("ip", "flags") and prev.regs.get(k) != cur.regs.get(k)]
        if self.t.req.mode32 and prev.reg32 and cur.reg32:
            out += [k for k in _REG32 if k not in ("eip", "eflags")
                    and prev.reg32.get(k) != cur.reg32.get(k)]
        out += [f for f in _FLAGS if prev.flags.get(f) != cur.flags.get(f)]
        return out

    def _mem_diff(self, chunk, record: bool) -> list[MemWrite]:
        writes: list[MemWrite] = []
        run_off = None
        old_run = bytearray()
        new_run = bytearray()

        def flush() -> None:
            nonlocal run_off
            if run_off is not None:
                writes.append(MemWrite(seg=_h4(chunk.seg), off=_h4(run_off),
                                       old=old_run.hex().upper(), new=new_run.hex().upper()))
            run_off = None
            old_run.clear()
            new_run.clear()

        base = chunk.seg * 16 + chunk.off
        for k, value in enumerate(chunk.data):
            lin = base + k
            old = self.mem.get(lin)
            self.mem[lin] = value
            if record and old is not None and old != value:
                if run_off is None or chunk.off + k != run_off + len(new_run):
                    flush()
                    run_off = chunk.off + k
                old_run.append(old)
                new_run.append(value)
            elif run_off is not None:
                flush()
        flush()
        return writes

    # ── итог попытки ──

    def _stall_reason(self) -> str:
        """Почему эмулятор пришлось остановить по времени — по команде, которую DebugX начал
        выполнять и не довёл до конца: последний блок вывода — её `next`."""
        t = self.t
        blocks = self.parser.blocks
        if not blocks:
            return "DebugX не напечатал ни одного шага: эмулятор остановлен по времени"
        last = blocks[-1]
        n = len(blocks) - 1
        nxt = last.next
        if nxt is not None:
            words = nxt.asm.upper().split()
            vector = words[1].rstrip("H") if len(words) == 2 and words[0] == "INT" else None
            # Функции выхода 00h и int 20h берут PSP из CS. В COM так и есть, а в EXE код
            # лежит выше PSP, и DOS «возвращается» в мусор — машина больше не отвечает.
            in_exe = (not t.built.target.endswith(".COM")
                      and last.regs["cs"] != t.load_regs.get("ds"))
            if vector == "21" and in_exe and last.regs["ax"] >> 8 == 0x00:
                return ("int 21h с AH = 00h в EXE-программе не завершает её: функция 00h ищет "
                        "PSP по CS. Для выхода в DOS — mov ax, 4C00h и int 21h")
            if vector == "20" and in_exe:
                return ("int 20h в EXE-программе не завершает её: прерывание ищет PSP по CS. "
                        "Для выхода в DOS — mov ax, 4C00h и int 21h")
            if vector == "16":
                return ("Программа ждёт клавиатуру через int 16h, а ввод на сайте подаётся "
                        "только через DOS (01h/0Ah)")
        line = t.lines.at(nxt.cs, nxt.ip) if nxt is not None else None
        if line is None and n > 0 and blocks[n - 1].next is not None:
            # Следующая команда вне листинга (переход в никуда) — тогда полезнее строка
            # последнего выполненного шага.
            ex = blocks[n - 1].next
            line = t.lines.at(ex.cs, ex.ip)
        where = f" (строка {line})" if line is not None else ""
        return f"Программа перестала отвечать после шага {n}{where}"

    def close(self, verdict: str) -> str:
        t = self.t
        p = self.parser
        if verdict == "restart":
            if self.sink:
                self.sink.abandon()
            return "restart"
        blocks = p.blocks
        executed = max(0, min(len(blocks), t.limit + 1) - 1)
        if verdict == "terminated":
            if self.open is not None:
                self._emit(self.open)
                self.open = None
            self._emit_termination()
            t.status, t.exit_code = "done", p.terminated.exit_code if p.terminated else None
            executed += 1
        elif verdict == "stop":
            if self.open is not None:
                self._emit(self.open)
                self.open = None
            t.status, t.error = "done", self.stop_reason
            if self.stopped_at is not None:
                executed = self.stopped_at
        elif verdict == "timeout":
            t.status = "timeout"
            t.error = t.error or "Прогон не уложился в отведённое время"
        elif verdict == "stalled":
            t.status, t.error = "timeout", self._stall_reason()
        elif verdict == "cancelled":
            t.status, t.error = "crashed", "Прогон отменён"
        elif verdict == "desync":
            t.status = "crashed"
        else:  # эмулятор вышел сам
            if self.open is not None:
                self._emit(self.open)
                self.open = None
            if len(blocks) - 1 >= t.limit:
                t.status = "step_limit"
            elif not blocks:
                t.status = "crashed"
                t.error = "DebugX не напечатал ни одного шага — см. сырой вывод"
            else:
                t.status = "crashed"
                t.error = f"DebugX завершился на шаге {len(blocks) - 1}, раньше лимита шагов"
        t.steps = executed

        if t.final_ranges is not None:
            target = t.limit
            t.final_dumps = [Dump(step=target, seg=_h4(c.seg), off=_h4(c.off),
                                  hex=c.data.hex().upper())
                             for c in p.dumps if c.after_block == target]
        if self.sink is not None:
            fold = t.status == "step_limit" and self.sink.count > HEAD + TAIL
            t.truncated, t.dumps = self.sink.finish(fold)
        return verdict


# ── прогон ───────────────────────────────────────────────────────────────────

def _summary(workdir: Path, result: RunResult) -> None:
    try:
        _write_json(workdir / "summary.json", result.to_json())
    except OSError:
        pass


def _version(req: RunRequest) -> str:
    """Версия TASM для итога: её несёт запрос набора (`asm.tasm.TasmRequest`)."""
    return str(getattr(req, "version", "") or DEFAULT_VERSION)


def _crashed(req: RunRequest, error: str, build: BuildResult | None = None,
             ms: int = 0) -> RunResult:
    return RunResult(status="crashed", build=build or BuildResult(ok=False, log=""),
                     load=None, stdin=normalize(req.stdin) if isinstance(req.stdin, str) else "",
                     step_limit=req.step_limit, mode32=req.mode32,
                     totals={"steps": 0, "ms": ms, "exit_code": None}, error=error,
                     toolchain="tasm", version=_version(req))


def run(req: RunRequest, tools: Tools, workdir: Path, *, timeout_s: float,
        progress: Progress | None = None,
        cancelled: Cancelled | None = None) -> RunResult:
    """Собрать и снять трассу. `timeout_s` — на всё сразу: сборку и все перезапуски."""
    workdir = Path(workdir)
    started = time.monotonic()
    deadline = started + timeout_s
    ms = lambda: int((time.monotonic() - started) * 1000)  # noqa: E731
    built: _Built | None = None
    try:
        workdir.mkdir(parents=True, exist_ok=True)
        for stale in ("trace.jsonl", RAW_INDEX, "summary.json", "plan.json"):
            (workdir / stale).unlink(missing_ok=True)
        _check(req)
        built = _build(req, tools, workdir, deadline, progress, cancelled)
        base = dict(build=built.result, stdin=normalize(req.stdin), step_limit=req.step_limit,
                    mode32=req.mode32, toolchain="tasm", version=_version(req))
        if built.cancelled:
            result = RunResult(status="crashed", load=None, error="Прогон отменён",
                               totals={"steps": 0, "ms": ms(), "exit_code": None}, **base)
        elif not built.result.ok:
            result = RunResult(status="timeout" if built.timed_out else "build_error", load=None,
                               totals={"steps": 0, "ms": ms(), "exit_code": None}, **base)
        elif built.probe is None:
            result = RunResult(status="crashed", load=None,
                               error="DebugX не загрузил собранную программу",
                               totals={"steps": 0, "ms": ms(), "exit_code": None}, **base)
        else:
            plan = _Plan(_request_key(req))
            tracer = _Tracer(req, tools, workdir, built, deadline=deadline, limit=req.step_limit,
                             plan=plan, dumps=True, progress=progress, cancelled=cancelled,
                             staged=True)
            tracer.run()
            _write_json(workdir / "plan.json", plan.to_json())
            regs = tracer.load_regs
            psp = regs["cs"] if built.target.endswith(".COM") else regs["ds"]
            load = {"psp": _h4(psp), "cs": _h4(regs["cs"]), "ds": _h4(tracer.data_seg),
                    "ss": _h4(regs["ss"])}
            if progress:
                progress("trace", tracer.steps, req.step_limit)
            result = RunResult(status=tracer.status, load=load, error=tracer.error,
                               totals={"steps": tracer.steps, "ms": ms(),
                                       "exit_code": tracer.exit_code},
                               truncated=tracer.truncated, dumps=tracer.dumps, **base)
    except АсмОшибка as e:
        _summary(workdir, _crashed(req, str(e), built.result if built else None, ms()))
        raise
    except Exception as e:
        _summary(workdir, _crashed(req, f"{type(e).__name__}: {e}",
                                   built.result if built else None, ms()))
        raise
    # Шагов может не быть вовсе (ошибка сборки, трасса не сошлась) — файлы всё равно есть,
    # чтобы служба читала их одинаково при любом итоге.
    if not (workdir / "trace.jsonl").exists():
        (workdir / "trace.jsonl").write_text("", encoding="utf-8")
        _write_json(workdir / RAW_INDEX, [])
    _summary(workdir, result)
    return result


def memory_at(req: RunRequest, tools: Tools, workdir: Path, step: int,
              ranges: list[tuple[str, str, int]], *, timeout_s: float) -> list[Dump]:
    """Дампы диапазонов `(seg, off, len)` на шаге `step`: перезапуск до шага тем же вводом.

    Ввод берётся из `plan.json` прогона, если он снят с того же запроса; иначе подбирается
    заново. Программа, завершившаяся раньше шага, — `АсмОшибка`: памяти на таком шаге нет.
    """
    _check(req)
    workdir = Path(workdir)
    if not isinstance(step, int) or not 0 <= step <= STEP_LIMIT_CEIL:
        raise АсмОшибка("Номер шага вне трассы")
    if not ranges or len(ranges) > 16:
        raise АсмОшибка("Диапазонов памяти — от 1 до 16")
    parsed: list[tuple[int, int, int]] = []
    for seg, off, length in ranges:
        if not (isinstance(seg, str) and _HEX.match(seg) and isinstance(off, str) and _HEX.match(off)):
            raise АсмОшибка("Адрес памяти — hex, до 4 знаков")
        if not isinstance(length, int) or not 1 <= length <= 0x1000:
            raise АсмОшибка("Длина диапазона — от 1 до 4096 байт")
        o = int(off, 16)
        parsed.append((int(seg, 16), o, min(length, 0x10000 - o)))

    deadline = time.monotonic() + timeout_s
    key = _request_key(req)
    plan = _Plan.load(workdir / "plan.json", key)
    target = _target(req)
    built = None
    if plan.reads or plan.stops or (workdir / "plan.json").exists():
        built = _reuse_build(req, workdir, target)
    if built is None or built.probe is None:
        built = _build(req, tools, workdir, deadline, None, None)
        if not built.result.ok or built.probe is None:
            raise АсмОшибка("Программа не собирается — памяти на шаге нет")
    tag = _memory_tag(workdir)
    # Без ступеней: шаг уже есть в трассе, и сценарий до него короткий ровно настолько, насколько
    # мал номер шага, — по нему и считается `-time-limit`.
    tracer = _Tracer(req, tools, workdir, built, deadline=deadline, limit=step, plan=plan,
                     dumps=False, progress=None, cancelled=None, final_ranges=parsed, tag=tag)
    tracer.run()
    if plan.key == key:
        _write_json(workdir / "plan.json", plan.to_json())
    if tracer.status == "timeout":
        raise АсмОшибка("Перезапуск до шага не уложился в отведённое время")
    if tracer.status == "done" or tracer.steps < step:
        raise АсмОшибка(f"Программа остановилась на шаге {tracer.steps}, раньше шага {step}")
    if tracer.status == "crashed":
        raise АсмОшибка(tracer.error or "Перезапуск до шага не удался")
    _drop_memory_files(workdir, tag)
    return tracer.final_dumps


def _memory_tag(workdir: Path) -> str:
    """Метка файлов одного вызова `memory_at`: четыре hex-знака, чтобы `m<метка>s<попытка>`
    влезало в 8 знаков DOS. Занимается созданием пакетного файла — второй вызов ту же не возьмёт."""
    while True:
        tag = secrets.token_hex(2)
        try:
            fd = os.open(workdir / f"m{tag}.bat", os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            continue
        os.close(fd)
        return tag


def _drop_memory_files(workdir: Path, tag: str) -> None:
    """Сценарии и вывод дампа нужны только на время вызова, а метка у каждого вызова новая —
    без уборки каталог прогона рос бы с каждым вопросом окна «Дамп»."""
    for entry in list(workdir.iterdir()):
        name = entry.name.lower()
        if name.startswith((f"m{tag}.", f"m{tag}s", f"m{tag}o", f"memory-{tag}.")):
            entry.unlink(missing_ok=True)


def _reuse_build(req: RunRequest, workdir: Path, target: str) -> _Built | None:
    """Сборка прогона, если её файлы на месте: пересобирать ради дампа незачем."""
    exe = workdir / target.lower()
    probe_out = workdir / "probe.out"
    if not exe.exists() or not probe_out.exists():
        return None
    parser = Parser()
    parser.feed(probe_out.read_bytes())
    parser.finish()
    if not parser.blocks:
        return None
    lst = _read_dos(workdir / "prog.lst")
    segments, _ = parse_map(_read_dos(workdir / "prog.map"))
    result = BuildResult(ok=True, log="", listing=parse_listing(lst) if lst else [],
                         segments=segments, symbols=[])
    return _Built(result=result, target=target, probe=parser.blocks[0])


__all__ = ["build", "run", "memory_at", "АсмОшибка"]
