"""runner_service.py — исполнитель трасс MinGW x64: цикл над томом очереди.

    python -m asm.mingw64.runner_service serve            цикл исполнителя (контейнер asm-runner)
    python -m asm.mingw64.runner_service job <задание> <каталог прогона>   один прогон (зовёт цикл)

**Зачем отдельный контейнер.** Трасса MinGW x64 — это настоящий `prog.exe` под Wine на
процессоре машины: код студента может звать системные вызовы Linux в обход Wine и через
`\\\\?\\unix\\` видит файловую систему. Поэтому он исполняется не в воркере с томом данных, а
здесь: без сети, без прав, без тома данных, с корнем только для чтения и потолками памяти,
процессора и числа процессов. С воркером контейнер делит только том очереди.

**Протокол задания** (том очереди, по умолчанию `/queue`; права — группа 10001, `2770`/`660`):

    runner.json              сердцебиение исполнителя: {ts, ready, slots, busy, pid}, раз в 5 с
    new/<id>/                воркер собирает задание
    jobs/<id>/               готовое задание: воркер переименовывает new/<id> сюда целиком
        request.json         {kind: 'trace'|'memory', timeout_s, step_limit, dump_steps,
                              step, ranges: [[va, len]]}
        prog.exe             собранная программа
        stdin                ввод (байты, переводы строк `\\n`)
        image.json           tracer.Image и команды кода: {image_base, entry, code, imports,
                              data_windows, stack_window, insns: {va hex: [текст, байты hex]}}
        claimed              исполнитель забрал задание (создаётся с O_EXCL — атомарно)
        cancel               воркер просит остановить прогон
        abandoned            воркер больше не ждёт итога: задание удаляет исполнитель
        steps.jsonl          шаги по мере трассы, строка на шаг (`encode_step`)
        raw.txt              сырой вывод трассировщика
        memory.json          память на шаге (kind='memory'): [[va, hex]]
        end.json             итог: {status, exit_code, error, load, steps, ms}
        done                 пишется последним: результат можно забирать

Воркер (`runner_client.py`) читает `steps.jsonl` по ходу, после `done` переносит сырой вывод
в каталог прогона и удаляет задание — в том числе отменённое, если итог успел прийти. Задание с
`abandoned` исполнитель удаляет сам, как только прогон кончился; любое задание старше
`KORITSU_ASM_RUNNER_JOB_TTL_S` и незабранный итог старше `DONE_TTL_S` — по сроку.

**Прогон** идёт отдельным процессом (`job`) в своей группе: цикл остаётся жив при любом
падении трассировщика, а зависший прогон снимается целиком. Каталог прогона на tmpfs
(`KORITSU_ASM_RUNNER_TMP`) — префикс Wine прогона, stdout, stderr — удаляется циклом после
конца процесса всегда; на старте цикл удаляет каталоги, оставшиеся от прошлого запуска.

**Потолки места.** `steps.jsonl` — `STEPS_MAX` байт (дальше прогон останавливается), сырой
вывод — `wine_tracer.RAW_MAX` (дальше не пишется), процесс прогона не пишет файл больше
`JOB_FILE_BYTES` (`RLIMIT_FSIZE`), вывод программы — `wine_tracer.OUT_MAX`.

Переменные окружения:

    KORITSU_ASM_MINGW_QUEUE          том очереди (умолч. /queue)
    KORITSU_ASM_RUNNER_SLOTS         прогонов одновременно (умолч. 2)
    KORITSU_ASM_RUNNER_TIMEOUT_MAX_S потолок времени прогона (умолч. 300)
    KORITSU_ASM_RUNNER_JOB_TTL_S     срок жизни задания в очереди (умолч. 900)
    KORITSU_ASM_RUNNER_PREFIX        общий префикс Wine образа (умолч. /opt/koritsu-wine/prefix)
    KORITSU_ASM_RUNNER_TMP           где заводить каталоги прогонов (умолч. /tmp/koritsu-runs)
"""
from __future__ import annotations

import json
import os
import resource
import secrets
import shutil
import signal
import subprocess
import sys
import time
import traceback
from pathlib import Path
from typing import Mapping

from ..model import АсмОшибка
from .tracer import Image, RawStep, TraceLimits

QUEUE_DEFAULT = "/queue"
PREFIX_DEFAULT = "/opt/koritsu-wine/prefix"
RUN_ROOT_DEFAULT = "/tmp/koritsu-runs"

HEARTBEAT = "runner.json"
NEW = "new"
JOBS = "jobs"
REQUEST = "request.json"
EXE = "prog.exe"
STDIN = "stdin"
IMAGE = "image.json"
CLAIMED = "claimed"
CANCEL = "cancel"
ABANDONED = "abandoned"
STEPS = "steps.jsonl"
RAW = "raw.txt"
MEMORY = "memory.json"
END = "end.json"
DONE = "done"

HEARTBEAT_EVERY_S = 5.0
HEARTBEAT_FRESH_S = 30.0
POLL_S = 0.1
SWEEP_EVERY_S = 30.0
DONE_TTL_S = 300.0              # результат, который воркер так и не забрал
GRACE_S = 20.0                  # сверх времени прогона: холодный старт Wine и уборка

SLOTS_DEFAULT = 2
TIMEOUT_MAX_DEFAULT = 300.0
JOB_TTL_DEFAULT = 900.0

STEP_LIMIT_MAX = 1_000_000
DUMP_STEPS_MAX = 5000
STDIN_MAX_BYTES = 256_000
RANGES_MAX = 16
RANGE_LEN_MAX = 0x1000
IMAGE_JSON_MAX = 32 * 1024 * 1024
STEPS_MAX = 256 * 1024 * 1024
JOB_FILE_BYTES = 512 * 1024 * 1024

DIR_MODE = 0o2770
FILE_MODE = 0o660


# ── протокол: общее с воркером ───────────────────────────────────────────────

def write_file(path: Path, data: bytes) -> None:
    """Файл целиком, атомарно (временное имя и переименование), с правами группы."""
    tmp = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, FILE_MODE)
    try:
        os.fchmod(fd, FILE_MODE)
        view = memoryview(data)
        while view:
            n = os.write(fd, view)
            view = view[n:]
    finally:
        os.close(fd)
    os.replace(tmp, path)


def write_json(path: Path, data) -> None:
    write_file(path, json.dumps(data, ensure_ascii=False).encode("utf-8"))


def make_dir(path: Path) -> None:
    path.mkdir(mode=DIR_MODE, exist_ok=True)
    try:
        os.chmod(path, DIR_MODE)
    except PermissionError:
        pass


def image_to_json(image: Image, insns: Mapping[int, tuple[str, bytes]]) -> dict:
    return {
        "image_base": image.image_base,
        "entry": image.entry,
        "code": [[lo, hi] for lo, hi in image.code],
        "imports": {f"{va:x}": name for va, name in image.imports.items()},
        "data_windows": [[lo, hi] for lo, hi in image.data_windows],
        "stack_window": image.stack_window,
        "insns": {f"{va:x}": [asm, code.hex()] for va, (asm, code) in insns.items()},
    }


def image_from_json(data: dict, exe: Path) -> tuple[Image, dict[int, tuple[str, bytes]]]:
    """Обратно в `Image`. Данные пришли с тома, проверяются формы, а не доверие."""
    def pairs(value) -> list[tuple[int, int]]:
        out = []
        for item in value or ():
            lo, hi = int(item[0]), int(item[1])
            if not 0 <= lo < hi < 2 ** 64:
                raise АсмОшибка("Образ задания негоден: диапазон адресов")
            out.append((lo, hi))
        return out

    try:
        image = Image(exe=exe, image_base=int(data["image_base"]), entry=int(data["entry"]),
                      sections=[], code=pairs(data.get("code")),
                      imports={int(k, 16): str(v)[:128] for k, v in (data.get("imports") or {}).items()},
                      data_windows=pairs(data.get("data_windows")),
                      stack_window=max(0, min(int(data.get("stack_window") or 0x100), 0x1000)))
        insns = {int(k, 16): (str(v[0])[:200], bytes.fromhex(v[1])[:15])
                 for k, v in (data.get("insns") or {}).items()}
    except (KeyError, TypeError, ValueError, IndexError) as e:
        raise АсмОшибка(f"Образ задания негоден: {e}") from None
    if not image.code:
        raise АсмОшибка("Образ задания негоден: нет исполняемых секций")
    return image, insns


def encode_step(step: RawStep, prev: Mapping[str, int] | None) -> str:
    """Шаг — строкой JSON. Регистры — только изменившиеся с прошлого шага; команду и её байты
    воркер берёт из своего разбора образа, поэтому они не пишутся."""
    record: dict = {"i": step.i}
    if step.pc is not None:
        record["pc"] = step.pc
    if step.next_pc is not None:
        record["n"] = step.next_pc
    record["r"] = {k: v for k, v in step.regs.items() if prev is None or prev.get(k) != v}
    if step.writes is not None:
        record["w"] = [[va, old.hex(), new.hex()] for va, old, new in step.writes]
    if step.dumps:
        record["d"] = [[va, data.hex()] for va, data in step.dumps]
    if step.out:
        record["o"] = step.out.hex()
    if step.stdin_pos:
        record["s"] = step.stdin_pos
    if step.call:
        record["c"] = step.call
    if step.raw is not None:
        record["x"] = [step.raw[1], step.raw[2]]
    return json.dumps(record, separators=(",", ":"))


def decode_step(line: str, prev: Mapping[str, int] | None,
                insns: Mapping[int, tuple[str, bytes]], raw_name: str = RAW) -> RawStep:
    record = json.loads(line)
    regs = dict(prev or {})
    regs.update(record.get("r") or {})
    pc = record.get("pc")
    next_pc = record.get("n")
    asm, code = insns.get(pc, ("", b"")) if pc is not None else ("", b"")
    next_asm, next_code = insns.get(next_pc, ("", b"")) if next_pc is not None else ("", b"")
    writes = record.get("w")
    raw = record.get("x")
    return RawStep(
        i=int(record["i"]), pc=pc, asm=asm, bytes=code, regs=regs, next_pc=next_pc,
        next_asm=next_asm, next_bytes=next_code,
        writes=None if writes is None else [(int(va), bytes.fromhex(o), bytes.fromhex(n))
                                            for va, o, n in writes],
        dumps=[(int(va), bytes.fromhex(h)) for va, h in record.get("d") or ()],
        out=bytes.fromhex(record.get("o") or ""), stdin_pos=int(record.get("s") or 0),
        call=record.get("c"), raw=(raw_name, int(raw[0]), int(raw[1])) if raw else None)


def read_heartbeat(queue: Path) -> dict | None:
    try:
        data = json.loads((queue / HEARTBEAT).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def heartbeat_fresh(data: dict | None, now: float | None = None) -> bool:
    if not data:
        return False
    try:
        age = (now if now is not None else time.time()) - float(data.get("ts") or 0)
    except (TypeError, ValueError):
        return False
    return -HEARTBEAT_FRESH_S < age < HEARTBEAT_FRESH_S


# ── один прогон ──────────────────────────────────────────────────────────────

class _StepWriter:
    """Шаги в `steps.jsonl` потоком, с потолком размера."""

    def __init__(self, path: Path) -> None:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, FILE_MODE)
        os.fchmod(fd, FILE_MODE)
        self.fh = os.fdopen(fd, "w", encoding="utf-8", buffering=256 * 1024)
        self.prev: Mapping[str, int] | None = None
        self.count = 0
        self.size = 0
        self.overflow = False
        self.last_flush = time.monotonic()

    def __call__(self, step: RawStep) -> None:
        if self.overflow:
            return
        line = encode_step(step, self.prev) + "\n"
        self.size += len(line)
        if self.size > STEPS_MAX:
            self.overflow = True
            return
        self.fh.write(line)
        self.prev = step.regs
        self.count = step.i
        now = time.monotonic()
        if now - self.last_flush > 0.2:
            self.fh.flush()
            self.last_flush = now

    def close(self) -> None:
        self.fh.close()


def _int(value, lo: int, hi: int, what: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not lo <= value <= hi:
        raise АсмОшибка(f"Задание негодно: {what} вне [{lo}, {hi}]")
    return value


def run_job(jobdir: Path, rundir: Path, env: Mapping[str, str]) -> None:
    """Прогон одного задания в этом процессе. Итог — всегда `end.json` и `done`."""
    from .wine_tracer import WineTracer                      # ptrace нужен только здесь

    started = time.monotonic()
    resource.setrlimit(resource.RLIMIT_FSIZE, (JOB_FILE_BYTES, JOB_FILE_BYTES))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    end: dict = {"status": "crashed", "exit_code": None, "error": None, "load": None,
                 "steps": 0, "ms": 0}
    try:
        try:
            req = json.loads((jobdir / REQUEST).read_text(encoding="utf-8"))
            if (jobdir / IMAGE).stat().st_size > IMAGE_JSON_MAX:
                raise АсмОшибка("Задание негодно: image.json слишком велик")
            raw_image = json.loads((jobdir / IMAGE).read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            raise АсмОшибка(f"Задание не прочитано: {e}") from None
        image, insns = image_from_json(raw_image, jobdir / EXE)
        with open(jobdir / STDIN, "rb") as fh:
            stdin = fh.read(STDIN_MAX_BYTES + 1)
        if len(stdin) > STDIN_MAX_BYTES:
            raise АсмОшибка("Ввод программы слишком длинный")
        timeout_max = float(env.get("KORITSU_ASM_RUNNER_TIMEOUT_MAX_S") or TIMEOUT_MAX_DEFAULT)
        timeout_s = min(float(req.get("timeout_s") or 60), timeout_max)
        deadline = started + max(1.0, timeout_s)
        base = Path(env.get("KORITSU_ASM_RUNNER_PREFIX") or PREFIX_DEFAULT)
        tracer = WineTracer(base, rundir, insns=insns, raw_name=RAW)
        writer: _StepWriter | None = None

        def cancelled() -> bool:
            return (writer is not None and writer.overflow) or (jobdir / CANCEL).exists() \
                or not jobdir.is_dir()

        kind = req.get("kind")
        if kind == "trace":
            step_limit = _int(req.get("step_limit"), 1, STEP_LIMIT_MAX, "step_limit")
            dump_steps = _int(req.get("dump_steps", 0), 0, DUMP_STEPS_MAX, "dump_steps")
            writer = _StepWriter(jobdir / STEPS)
            try:
                result = tracer.trace(image, stdin, jobdir,
                                      limits=TraceLimits(step_limit=step_limit,
                                                         dump_steps=dump_steps, deadline=deadline),
                                      sink=writer, cancelled=cancelled)
            finally:
                writer.close()
            end.update(status=result.status, exit_code=result.exit_code, error=result.error,
                       load=result.load, steps=writer.count)
            if writer.overflow:
                end.update(status="crashed", exit_code=None,
                           error=f"Трасса больше {STEPS_MAX // 2**20} МБ — прогон остановлен")
        elif kind == "memory":
            step = _int(req.get("step"), 0, STEP_LIMIT_MAX, "step")
            ranges = []
            for item in (req.get("ranges") or [])[:RANGES_MAX + 1]:
                ranges.append((_int(item[0], 0, 2 ** 64 - 1, "адрес"),
                               _int(item[1], 1, RANGE_LEN_MAX, "длина")))
            if not 1 <= len(ranges) <= RANGES_MAX:
                raise АсмОшибка(f"Диапазонов памяти — от 1 до {RANGES_MAX}")
            chunks = tracer.memory_at(image, stdin, jobdir, step, ranges, deadline=deadline,
                                      cancelled=cancelled)
            write_json(jobdir / MEMORY, [[va, data.hex()] for va, data in chunks])
            end.update(status="exited", steps=step)
        else:
            raise АсмОшибка("Задание негодно: kind — trace или memory")
    except АсмОшибка as e:
        end.update(status="error", error=str(e))
    except Exception as e:                                               # noqa: BLE001
        traceback.print_exc()
        end.update(status="crashed", error=f"Трассировщик упал: {type(e).__name__}: {e}")
    end["ms"] = int((time.monotonic() - started) * 1000)
    try:
        write_json(jobdir / END, end)
        write_file(jobdir / DONE, b"")
    except OSError:
        pass                                                  # задание уже убрали


# ── цикл ─────────────────────────────────────────────────────────────────────

def _log(message: str) -> None:
    print(f"asm-runner: {message}", file=sys.stderr, flush=True)


def _mtime(path: Path) -> float | None:
    try:
        return path.stat().st_mtime
    except OSError:
        return None


class _Running:
    def __init__(self, job_id: str, proc: subprocess.Popen, jobdir: Path, rundir: Path,
                 kill_at: float) -> None:
        self.job_id = job_id
        self.proc = proc
        self.jobdir = jobdir
        self.rundir = rundir
        self.kill_at = kill_at


def _drop_rundir(rundir: Path) -> None:
    """Погасить Wine прогона и удалить каталог прогона — при любом итоге."""
    from .wine_prefix import kill_server
    if rundir.is_dir():
        for sub in rundir.glob("wine-*"):
            if (sub / "prefix").is_dir():
                kill_server(sub / "prefix", sub / "home")
    shutil.rmtree(rundir, ignore_errors=True)


class Service:
    def __init__(self, env: Mapping[str, str]) -> None:
        self.env = dict(env)
        self.queue = Path(env.get("KORITSU_ASM_MINGW_QUEUE") or QUEUE_DEFAULT)
        self.slots = max(1, int(env.get("KORITSU_ASM_RUNNER_SLOTS") or SLOTS_DEFAULT))
        self.ttl = float(env.get("KORITSU_ASM_RUNNER_JOB_TTL_S") or JOB_TTL_DEFAULT)
        self.timeout_max = float(env.get("KORITSU_ASM_RUNNER_TIMEOUT_MAX_S") or TIMEOUT_MAX_DEFAULT)
        self.run_root = Path(env.get("KORITSU_ASM_RUNNER_TMP") or RUN_ROOT_DEFAULT)
        self.prefix = Path(env.get("KORITSU_ASM_RUNNER_PREFIX") or PREFIX_DEFAULT)
        self.running: dict[str, _Running] = {}
        self.stopping = False
        self.last_beat = 0.0
        self.last_sweep = 0.0

    def ready(self) -> bool:
        return os.access("/usr/lib/wine/wine64", os.X_OK) and (self.prefix / "system.reg").is_file()

    def serve(self) -> int:
        os.umask(0o007)
        signal.signal(signal.SIGTERM, self._on_term)
        signal.signal(signal.SIGINT, self._on_term)
        make_dir(self.queue / NEW)
        make_dir(self.queue / JOBS)
        self.run_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        for stale in self.run_root.iterdir():
            _drop_rundir(stale)
        _log(f"очередь {self.queue}, прогонов одновременно {self.slots}, "
             f"готов {self.ready()}")
        while True:
            now = time.time()
            if now - self.last_beat >= HEARTBEAT_EVERY_S:
                self._beat(now)
            self._reap()
            if self.stopping:
                if not self.running:
                    break
            else:
                self._take()
            if now - self.last_sweep >= SWEEP_EVERY_S:
                self._sweep(now)
                self.last_sweep = now
            time.sleep(POLL_S)
        try:
            (self.queue / HEARTBEAT).unlink()
        except OSError:
            pass
        _log("остановлен")
        return 0

    def _on_term(self, signum, frame) -> None:
        if self.stopping:
            for r in self.running.values():
                self._kill(r)
        self.stopping = True

    def _beat(self, now: float) -> None:
        self.last_beat = now
        try:
            write_json(self.queue / HEARTBEAT, {"ts": now, "ready": self.ready(),
                                                "slots": self.slots, "busy": len(self.running),
                                                "pid": os.getpid()})
        except OSError as e:
            _log(f"сердцебиение не записано: {e}")

    def _take(self) -> None:
        if len(self.running) >= self.slots:
            return
        try:
            entries = sorted(os.scandir(self.queue / JOBS), key=lambda e: _mtime(Path(e.path)) or 0)
        except OSError:
            return
        for entry in entries:
            if len(self.running) >= self.slots:
                return
            jobdir = Path(entry.path)
            if entry.name in self.running or not entry.is_dir(follow_symlinks=False):
                continue
            if (jobdir / CLAIMED).exists() or (jobdir / DONE).exists():
                continue
            if (jobdir / CANCEL).exists():
                shutil.rmtree(jobdir, ignore_errors=True)
                continue
            try:
                fd = os.open(jobdir / CLAIMED, os.O_WRONLY | os.O_CREAT | os.O_EXCL, FILE_MODE)
                os.close(fd)
            except OSError:
                continue
            self._start(entry.name, jobdir)

    def _start(self, job_id: str, jobdir: Path) -> None:
        rundir = self.run_root / f"{job_id}-{secrets.token_hex(3)}"
        rundir.mkdir(mode=0o700)
        try:
            req = json.loads((jobdir / REQUEST).read_text(encoding="utf-8"))
            timeout_s = min(float(req.get("timeout_s") or 60), self.timeout_max)
        except (OSError, ValueError, TypeError):
            timeout_s = self.timeout_max
        env = {k: v for k, v in self.env.items()
               if k in ("PATH", "PYTHONPATH", "LANG") or k.startswith("KORITSU_ASM_")}
        proc = subprocess.Popen([sys.executable, "-m", "asm.mingw64.runner_service", "job",
                                 str(jobdir), str(rundir)],
                                env=env, stdin=subprocess.DEVNULL, start_new_session=True)
        self.running[job_id] = _Running(job_id, proc, jobdir, rundir,
                                        time.monotonic() + timeout_s + GRACE_S)

    @staticmethod
    def _kill(r: _Running) -> None:
        try:
            os.killpg(r.proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass

    def _reap(self) -> None:
        for job_id, r in list(self.running.items()):
            code = r.proc.poll()
            if code is None and time.monotonic() > r.kill_at:
                _log(f"задание {job_id}: процесс прогона не уложился в срок — снят")
                self._kill(r)
                try:
                    code = r.proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    continue
            if code is None:
                continue
            del self.running[job_id]
            # Группа процесса прогона — тоже: Wine мог оставить потомков.
            self._kill(r)
            _drop_rundir(r.rundir)
            if r.jobdir.is_dir() and not (r.jobdir / DONE).exists():
                try:
                    write_json(r.jobdir / END, {"status": "crashed", "exit_code": None,
                                                "error": f"Исполнитель не закончил прогон (код {code})",
                                                "load": None, "steps": 0, "ms": 0})
                    write_file(r.jobdir / DONE, b"")
                except OSError:
                    pass
            if (r.jobdir / ABANDONED).exists():
                shutil.rmtree(r.jobdir, ignore_errors=True)

    def _sweep(self, now: float) -> None:
        """Очередь по сроку: брошенные сборки заданий, незабранные результаты, старые задания."""
        for part in (NEW, JOBS):
            try:
                entries = list(os.scandir(self.queue / part))
            except OSError:
                continue
            for entry in entries:
                if entry.name in self.running:
                    continue
                path = Path(entry.path)
                done = _mtime(path / DONE)
                born = _mtime(path / REQUEST) or _mtime(path) or now
                abandoned = done is not None and (path / ABANDONED).exists()
                if abandoned or (done is not None and now - done > DONE_TTL_S) or now - born > self.ttl:
                    _log(f"задание {entry.name} удалено по сроку")
                    shutil.rmtree(path, ignore_errors=True)
                    try:
                        path.unlink()
                    except OSError:
                        pass


def main(argv: list[str]) -> int:
    if argv[:1] == ["serve"]:
        return Service(os.environ).serve()
    if argv[:1] == ["job"] and len(argv) == 3:
        run_job(Path(argv[1]), Path(argv[2]), os.environ)
        return 0
    if argv[:1] == ["health"]:
        queue = Path(os.environ.get("KORITSU_ASM_MINGW_QUEUE") or QUEUE_DEFAULT)
        data = read_heartbeat(queue)
        return 0 if heartbeat_fresh(data) and data.get("ready") else 1
    print(__doc__.split("\n\n")[1], file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
