"""runner.py — сборка, трасса и память на шаге MinGW x64.

    build(req, tools, workdir, timeout_s)            as → ld, листинг, секции, символы
    run(req, tools, workdir, timeout_s, …)           сборка → трасса целиком
    memory_at(req, tools, workdir, step, ranges, …)  память на шаге через трассировщик

**Трасса.** Сборка даёт `prog.exe` и листинг; из них — `tracer.Image` (база, точка входа,
секции, код, ячейки IAT, окна данных). Трассировщик (`tools.tracer`) проходит программу и
отдаёт сырые шаги `RawStep`; здесь каждый превращается в `model.Step` и уходит в `TraceSink`:

- `ip` — RIP команды (16 hex), `cs` — `None`: память плоская;
- `line` — строка исходника по VA через листинг и базы секций (`gas.LineIndex`); у шага 0 и
  у команд вне листинга (заглушки импорта) — `None`;
- `reg` — 64-битные регистры по 16 hex, сегментные по 4; `reg32` — `None`;
- `changed` — регистры, у которых значение разошлось с прошлым шагом, и флаги RFLAGS по битам
  (`of df if sf zf af pf cf`, как у TASM);
- `mem` — из `RawStep.writes`, если трассировщик их знает, иначе разница дампов окон на шагах
  до `dump_steps`;
- `out` — байты вывода как UTF-8 (исходник на сайте в UTF-8), не декодируются — cp866;
  `\\r\\n` → `\\n`;
- `stdin_pos` — в знаках ввода, а не в байтах: сайт отмечает прочитанное в тексте поля;
- `call` — вызов API, выполненный шагом целиком.

**Итог.** `summary.json` с `toolchain='mingw64'`. Статус — из `TraceEnd`: `exited` → `done`
с кодом выхода; `waits_input` → `done` без кода с причиной в `error`, как у TASM, когда
ввод кончился; `cancelled` → `crashed` «Прогон отменён».

**Что пишется в каталог прогона.** `prog.s/.obj/.exe/.lst`, `as.txt`, `ld.txt`, `build.key`,
файлы трассировщика (`raw*.txt`), `raw.idx.json`, `trace.jsonl`, `summary.json`.
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

from ..model import АсмОшибка, BuildResult, Dump, MemWrite, RunResult, Step
from ..sink import TraceSink
from ..toolchain import Cancelled, Progress
from .build import (EXE, Built, Mingw64Request, assemble, h16, reuse)
from .gas import LineIndex
from .tools import Mingw64Tools
from .tracer import REGISTERS, SEGMENT_REGISTERS, Image, RawStep, TraceEnd, TraceLimits

TOOLCHAIN_ID = "mingw64"
RAW_INDEX = "raw.idx.json"

STDIN_MAX = 64_000              # знаков ввода
STEP_LIMIT_CEIL = 1_000_000     # потолок ядра; потолок продукта ставит служба
DUMP_STEPS_MAX = 5000           # до этого шага — дампы окон на каждом шаге
DATA_WINDOW_MAX = 0x1000        # байт секций данных в окнах дампа
STACK_WINDOW = 0x100            # байт выше RSP
RANGES_MAX = 16
RANGE_LEN_MAX = 0x1000
PROGRESS_EVERY_S = 0.25

_HEX = re.compile(r"^[0-9A-Fa-f]{1,16}$")
_FLAG_BITS = (("of", 11), ("df", 10), ("if", 9), ("sf", 7), ("zf", 6), ("af", 4), ("pf", 2),
              ("cf", 0))


# ── общее ────────────────────────────────────────────────────────────────────

def normalize(stdin: str) -> str:
    """CR LF → LF; непустой ввод без перевода строки в конце получает его: человек, набравший
    «42» в поле ввода, имел в виду «42 и Enter»."""
    text = stdin.replace("\r\n", "\n").replace("\r", "\n")
    if text and not text.endswith("\n"):
        text += "\n"
    return text


def _check(req: Mingw64Request) -> None:
    if not isinstance(req.stdin, str) or len(req.stdin) > STDIN_MAX:
        raise АсмОшибка(f"Ввод программы длиннее {STDIN_MAX} знаков")
    if (not isinstance(req.step_limit, int) or isinstance(req.step_limit, bool)
            or not 1 <= req.step_limit <= STEP_LIMIT_CEIL):
        raise АсмОшибка(f"Лимит шагов — от 1 до {STEP_LIMIT_CEIL}")


def _stdin_bytes(req: Mingw64Request) -> bytes:
    return normalize(req.stdin).encode("utf-8")


def _write_json(path: Path, data) -> None:
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _out_text(raw: bytes) -> str:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("cp866", "replace")
    return text.replace("\r\n", "\n")


def _reg_hex(name: str, value: int) -> str:
    if name in SEGMENT_REGISTERS:
        return f"{value & 0xFFFF:04X}"
    return h16(value)


# ── образ ────────────────────────────────────────────────────────────────────

def make_image(built: Built, workdir: Path) -> Image:
    img = built.image
    if img is None:
        raise АсмОшибка("Программа не собрана — образа нет")
    code = sorted((img.va(s), img.va(s) + s.size) for s in img.sections if s.executable and s.size)
    windows: list[tuple[int, int]] = []
    budget = DATA_WINDOW_MAX
    for s in sorted(img.sections, key=lambda s: s.rva):
        if budget <= 0:
            break
        if s.cls not in ("DATA", "BSS", "RDATA") or not s.size:
            continue
        length = min(s.size, budget)
        windows.append((img.va(s), img.va(s) + length))
        budget -= length
    return Image(exe=Path(workdir) / EXE, image_base=img.image_base, entry=img.entry,
                 sections=list(built.result.segments), code=code, imports=dict(img.imports),
                 data_windows=windows, stack_window=STACK_WINDOW)


# ── шаги ─────────────────────────────────────────────────────────────────────

class _Steps:
    """`RawStep` → `Step` в `TraceSink`, по порядку шагов."""

    def __init__(self, sink: TraceSink, lines: LineIndex, image: Image, stdin: bytes,
                 dump_steps: int) -> None:
        self.sink = sink
        self.lines = lines
        self.image = image
        self.stdin = stdin
        self.dump_steps = dump_steps
        self.prev: dict[str, int] | None = None
        self.mem: dict[int, int] = {}
        self.executed = 0
        self.stdin_bytes = 0
        self.stdin_chars = 0

    def _stdin_pos(self, pos: int) -> int:
        pos = max(0, min(pos, len(self.stdin)))
        if pos != self.stdin_bytes:
            self.stdin_bytes = pos
            self.stdin_chars = len(self.stdin[:pos].decode("utf-8", "ignore"))
        return self.stdin_chars

    def _changed(self, cur: dict[str, int]) -> list[str]:
        prev = self.prev
        if prev is None:
            return []
        out = [k for k in REGISTERS if k not in ("rip", "rflags") and prev.get(k) != cur.get(k)]
        a, b = prev.get("rflags", 0), cur.get("rflags", 0)
        out += [name for name, bit in _FLAG_BITS if (a >> bit) & 1 != (b >> bit) & 1]
        return out

    def _mem_diff(self, va: int, data: bytes, record: bool) -> list[MemWrite]:
        writes: list[MemWrite] = []
        run_va: int | None = None
        old_run = bytearray()
        new_run = bytearray()

        def flush() -> None:
            nonlocal run_va
            if run_va is not None:
                writes.append(MemWrite(seg=None, off=h16(run_va), old=old_run.hex().upper(),
                                       new=new_run.hex().upper()))
            run_va = None
            old_run.clear()
            new_run.clear()

        for k, value in enumerate(data):
            addr = va + k
            old = self.mem.get(addr)
            self.mem[addr] = value
            if record and old is not None and old != value:
                if run_va is None or addr != run_va + len(new_run):
                    flush()
                    run_va = addr
                old_run.append(old)
                new_run.append(value)
            elif run_va is not None:
                flush()
        flush()
        return writes

    def __call__(self, raw: RawStep) -> None:
        i = raw.i
        regs = dict(raw.regs)
        records: list[Dump] = []
        mem: list[MemWrite] = []
        for va, data in raw.dumps or ():
            if i == 0 or i > self.dump_steps:
                records.append(Dump(step=i, seg=None, off=h16(va), hex=bytes(data).hex().upper()))
            diff = self._mem_diff(va, bytes(data), record=i > 0 and raw.writes is None
                                  and i <= self.dump_steps)
            mem.extend(diff)
        if raw.writes is not None and i > 0:
            mem = [MemWrite(seg=None, off=h16(va), old=bytes(old).hex().upper(),
                            new=bytes(new).hex().upper()) for va, old, new in raw.writes]
        self.sink.add_dumps(i, records)

        pc = raw.pc if raw.pc is not None else (raw.next_pc if raw.next_pc is not None
                                                 else self.image.entry)
        nxt = None
        if raw.next_pc is not None:
            nxt = {"cs": None, "ip": h16(raw.next_pc), "line": self.lines.at(raw.next_pc),
                   "asm": raw.next_asm, "bytes": bytes(raw.next_bytes).hex().upper()}
        step = Step(i=i, cs=None, ip=h16(pc),
                    line=self.lines.at(raw.pc) if i > 0 else None,
                    asm=raw.asm if i > 0 else "",
                    bytes=bytes(raw.bytes).hex().upper() if i > 0 else "",
                    reg={k: _reg_hex(k, regs[k]) for k in REGISTERS if k in regs},
                    reg32=None, changed=self._changed(regs) if i > 0 else [], mem=mem,
                    out=_out_text(bytes(raw.out)), stdin_pos=self._stdin_pos(raw.stdin_pos),
                    next=nxt, call=raw.call)
        if raw.raw is not None:
            idx = {"i": i, "file": raw.raw[0], "offset": raw.raw[1], "length": raw.raw[2]}
        else:
            idx = {"i": i, "file": None, "offset": 0, "length": 0}
        self.sink.add(step, idx)
        self.prev = regs
        self.executed = max(self.executed, i)


# ── прогон ───────────────────────────────────────────────────────────────────

def _summary(workdir: Path, result: RunResult) -> None:
    try:
        _write_json(workdir / "summary.json", result.to_json())
    except OSError:
        pass


def _base(req: Mingw64Request, build: BuildResult) -> dict:
    return dict(build=build, stdin=normalize(req.stdin) if isinstance(req.stdin, str) else "",
                step_limit=req.step_limit, mode32=True, toolchain=TOOLCHAIN_ID,
                version=str(req.version))


def _crashed(req: Mingw64Request, error: str, build: BuildResult | None = None,
             ms: int = 0) -> RunResult:
    return RunResult(status="crashed", load=None, error=error,
                     totals={"steps": 0, "ms": ms, "exit_code": None},
                     **_base(req, build or BuildResult(ok=False, log="")))


def _outcome(end: TraceEnd) -> tuple[str, str | None, int | None]:
    """Статус прогона, причина и код выхода по концу трассы."""
    if end.status == "exited":
        return "done", end.error, end.exit_code
    if end.status == "waits_input":
        return "done", end.error or "Программа ждёт ввод, а заданный ввод кончился", None
    if end.status == "step_limit":
        return "step_limit", end.error, None
    if end.status == "timeout":
        return "timeout", end.error or "Прогон не уложился в отведённое время", None
    if end.status == "cancelled":
        return "crashed", "Прогон отменён", None
    return "crashed", end.error or "Трасса оборвалась без объяснения трассировщика", None


def _load(end: TraceEnd, image: Image) -> dict:
    raw = end.load or {}
    out = {}
    for key, fallback in (("image_base", image.image_base), ("entry", image.entry), ("rsp", None)):
        value = raw.get(key, fallback)
        out[key] = h16(value) if isinstance(value, int) else value
    return out


def build(req: Mingw64Request, tools: Mingw64Tools, workdir: Path, *,
          timeout_s: float) -> BuildResult:
    """Собрать программу. Ошибки программы — в `BuildResult.messages`, не исключением."""
    _check(req)
    return assemble(req, tools, Path(workdir), time.monotonic() + timeout_s).result


def run(req: Mingw64Request, tools: Mingw64Tools, workdir: Path, *, timeout_s: float,
        progress: Progress | None = None, cancelled: Cancelled | None = None) -> RunResult:
    """Собрать и снять трассу. `timeout_s` — на всё сразу: сборку и трассу."""
    workdir = Path(workdir)
    started = time.monotonic()
    deadline = started + timeout_s
    ms = lambda: int((time.monotonic() - started) * 1000)  # noqa: E731
    built: Built | None = None
    sink: TraceSink | None = None
    try:
        workdir.mkdir(parents=True, exist_ok=True)
        for stale in ("trace.jsonl", RAW_INDEX, "summary.json"):
            (workdir / stale).unlink(missing_ok=True)
        _check(req)
        built = assemble(req, tools, workdir, deadline, progress, cancelled)
        base = _base(req, built.result)
        totals = {"steps": 0, "ms": 0, "exit_code": None}
        if built.cancelled:
            result = RunResult(status="crashed", load=None, error="Прогон отменён",
                               totals={**totals, "ms": ms()}, **base)
        elif not built.result.ok:
            result = RunResult(status="timeout" if built.timed_out else "build_error", load=None,
                               totals={**totals, "ms": ms()}, **base)
        else:
            image = make_image(built, workdir)
            stdin = _stdin_bytes(req)
            limits = TraceLimits(step_limit=req.step_limit,
                                 dump_steps=min(DUMP_STEPS_MAX, req.step_limit), deadline=deadline)
            sink = TraceSink(workdir, RAW_INDEX)
            steps = _Steps(sink, built.lines, image, stdin, limits.dump_steps)
            last_tick = 0.0

            def tick(n: int) -> None:
                nonlocal last_tick
                now = time.monotonic()
                if progress and now - last_tick >= PROGRESS_EVERY_S:
                    last_tick = now
                    progress("trace", int(n), req.step_limit)

            if progress:
                progress("trace", 0, req.step_limit)
            end = tools.tracer.trace(image, stdin, workdir, limits=limits, sink=steps,
                                     progress=tick, cancelled=cancelled)
            status, error, exit_code = _outcome(end)
            truncated, dumps = sink.finish(fold=status == "step_limit")
            sink = None
            if progress:
                progress("trace", steps.executed, req.step_limit)
            result = RunResult(status=status, load=_load(end, image), error=error,
                               totals={"steps": steps.executed, "ms": ms(), "exit_code": exit_code},
                               truncated=truncated, dumps=dumps, **base)
    except АсмОшибка as e:
        _abandon(sink, workdir)
        _summary(workdir, _crashed(req, str(e), built.result if built else None, ms()))
        raise
    except Exception as e:
        _abandon(sink, workdir)
        _summary(workdir, _crashed(req, f"{type(e).__name__}: {e}",
                                   built.result if built else None, ms()))
        raise
    # Шагов может не быть вовсе (ошибка сборки) — файлы всё равно есть, чтобы служба читала их
    # одинаково при любом итоге.
    if not (workdir / "trace.jsonl").exists():
        (workdir / "trace.jsonl").write_text("", encoding="utf-8")
        _write_json(workdir / RAW_INDEX, [])
    _summary(workdir, result)
    return result


def _abandon(sink: TraceSink | None, workdir: Path) -> None:
    if sink is None:
        return
    sink.abandon()
    (workdir / "trace.jsonl.tmp").unlink(missing_ok=True)


def memory_at(req: Mingw64Request, tools: Mingw64Tools, workdir: Path, step: int,
              ranges: list[tuple[str | None, str, int]], *, timeout_s: float) -> list[Dump]:
    """Дампы диапазонов `(None, off, len)` на шаге `step`. Сегмента у адреса нет: память
    плоская, `off` — VA до 16 hex. Собранная сборка того же запроса берётся как есть."""
    _check(req)
    workdir = Path(workdir)
    if not isinstance(step, int) or isinstance(step, bool) or not 0 <= step <= STEP_LIMIT_CEIL:
        raise АсмОшибка("Номер шага вне трассы")
    if not ranges or len(ranges) > RANGES_MAX:
        raise АсмОшибка(f"Диапазонов памяти — от 1 до {RANGES_MAX}")
    parsed: list[tuple[int, int]] = []
    for r in ranges:
        if not isinstance(r, (tuple, list)) or len(r) != 3:
            raise АсмОшибка("Диапазон памяти — (seg, off, len)")
        seg, off, length = r
        if seg is not None:
            raise АсмОшибка("Память MinGW x64 плоская: адрес пишется без сегмента")
        if not isinstance(off, str) or not _HEX.match(off):
            raise АсмОшибка("Адрес памяти — hex, до 16 знаков")
        if not isinstance(length, int) or isinstance(length, bool) or not 1 <= length <= RANGE_LEN_MAX:
            raise АсмОшибка(f"Длина диапазона — от 1 до {RANGE_LEN_MAX} байт")
        parsed.append((int(off, 16), length))

    deadline = time.monotonic() + timeout_s
    built = reuse(req, workdir)
    if built is None:
        built = assemble(req, tools, workdir, deadline)
        if not built.result.ok or built.image is None:
            raise АсмОшибка("Программа не собирается — памяти на шаге нет")
    image = make_image(built, workdir)
    chunks = tools.tracer.memory_at(image, _stdin_bytes(req), workdir, step, parsed,
                                    deadline=deadline)
    return [Dump(step=step, seg=None, off=h16(va), hex=bytes(data).hex().upper())
            for va, data in chunks]


__all__ = ["build", "run", "memory_at", "make_image", "normalize", "TOOLCHAIN_ID", "RAW_INDEX",
           "STEP_LIMIT_CEIL", "STDIN_MAX"]
