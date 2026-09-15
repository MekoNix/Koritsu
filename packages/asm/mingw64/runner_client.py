"""runner_client.py — трассировщик MinGW x64 на стороне воркера: задание в очередь исполнителя.

Реализация `tracer.Tracer`, которая сама ничего не исполняет: кладёт `prog.exe`, ввод и
образ в том очереди (`KORITSU_ASM_MINGW_QUEUE`), ждёт `done` с дедлайном и отменой и отдаёт
шаги в `sink` по мере того, как исполнитель пишет их в `steps.jsonl`. Протокол — в шапке
`runner_service.py`.

Команды кода (`RawStep.asm`, `bytes`) — из `objdump -d -M intel` той же сборки: `objdump`
приезжает в образ воркера с `as` и `ld` одним пакетом, а исполнителю разборщик команд не
нужен. Нет `objdump` — шаги приходят без текста команд.

После `done` сырой вывод переносится в каталог прогона, задание удаляется. Прогон, не
кончившийся к дедлайну, получает `cancel` и остаётся исполнителю: он доснимет процесс и
удалит задание сам.

`status()` — жив ли исполнитель: файл сердцебиения в очереди свежий и исполнитель готов.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import subprocess
import time
from pathlib import Path
from typing import Callable, Mapping

from ..model import АсмОшибка
from . import runner_service as proto
from .tracer import Image, RawStep, TraceEnd, TraceLimits

WAIT_POLL_S = 0.05
GRACE_S = 20.0                  # сверх дедлайна: холодный старт Wine в исполнителе и уборка
CANCEL_GRACE_S = 5.0            # сколько ждать `done` после `cancel`
OBJDUMP_TIMEOUT_S = 15.0
OBJDUMP_MAX = 32 * 1024 * 1024
RAW_COPY_MAX = 128 * 1024 * 1024

_INSN = re.compile(r"^\s*([0-9a-f]+):\t([0-9a-f ]+?)\s*\t(.+?)\s*$")


def disassemble(objdump: str | None, exe: Path) -> dict[int, tuple[str, bytes]]:
    """Команды кода по VA: `(текст Intel, байты)`. Ошибка разбора — пустой словарь."""
    if not objdump:
        return {}
    try:
        done = subprocess.run([objdump, "-d", "-w", "-M", "intel", str(exe)],
                              capture_output=True, timeout=OBJDUMP_TIMEOUT_S,
                              stdin=subprocess.DEVNULL, check=False,
                              env={"PATH": "/usr/local/bin:/usr/bin:/bin", "LC_ALL": "C.UTF-8"})
    except (OSError, subprocess.SubprocessError):
        return {}
    out: dict[int, tuple[str, bytes]] = {}
    for line in done.stdout[:OBJDUMP_MAX].decode("utf-8", "replace").split("\n"):
        m = _INSN.match(line)
        if not m:
            continue
        text = re.sub(r"\s+", " ", m.group(3))
        try:
            out[int(m.group(1), 16)] = (text, bytes.fromhex(m.group(2).replace(" ", "")))
        except ValueError:
            continue
    return out


class QueueTracer:
    name = "wine-ptrace"

    def __init__(self, queue: Path, objdump: str | None = None) -> None:
        self.queue = Path(queue)
        self.objdump = objdump
        self._insns_key: tuple | None = None
        self._insns: dict[int, tuple[str, bytes]] = {}

    # ── состояние ────────────────────────────────────────────────────────────

    def status(self, env: Mapping[str, str]) -> dict[str, bool]:
        beat = proto.read_heartbeat(self.queue)
        alive = proto.heartbeat_fresh(beat)
        return {"ready": bool(alive and beat and beat.get("ready")), "queue": self.queue.is_dir(),
                "runner": alive}

    # ── трасса ───────────────────────────────────────────────────────────────

    def trace(self, image: Image, stdin: bytes, workdir: Path, *, limits: TraceLimits,
              sink: Callable[[RawStep], None],
              progress: Callable[[int], None] | None = None,
              cancelled: Callable[[], bool] | None = None) -> TraceEnd:
        insns = self._disassemble(image.exe)
        jobdir = self._submit(image, insns, stdin, {
            "kind": "trace", "step_limit": limits.step_limit, "dump_steps": limits.dump_steps,
        }, limits.deadline)
        prev: dict[str, int] | None = None
        state = {"prev": prev}

        def on_line(line: str) -> None:
            step = proto.decode_step(line, state["prev"], insns)
            state["prev"] = step.regs
            sink(step)
            if progress is not None:
                progress(step.i)

        finished, end = self._wait(jobdir, limits.deadline, cancelled, on_line)
        load = {"image_base": image.image_base, "entry": image.entry, "rsp": None}
        if finished and end.get("status") == "cancelled":
            shutil.rmtree(jobdir, ignore_errors=True)
            return TraceEnd(status="cancelled", exit_code=None, error=end.get("error"),
                            load=end.get("load") or load)
        if not finished:
            status = "cancelled" if cancelled is not None and cancelled() else "timeout"
            return TraceEnd(status=status, exit_code=None,
                            error=None if status == "cancelled" else
                            "Прогон не уложился в отведённое время", load=load)
        try:
            if end.get("status") == "error":
                raise АсмОшибка(str(end.get("error") or "Исполнитель отказал в прогоне"))
            self._take_raw(jobdir, Path(workdir))
        finally:
            shutil.rmtree(jobdir, ignore_errors=True)
        status = end.get("status")
        if status not in ("exited", "step_limit", "timeout", "crashed", "waits_input", "cancelled"):
            status = "crashed"
        return TraceEnd(status=status, exit_code=end.get("exit_code"), error=end.get("error"),
                        load=end.get("load") or load)

    def memory_at(self, image: Image, stdin: bytes, workdir: Path, step: int,
                  ranges: list[tuple[int, int]], *, deadline: float) -> list[tuple[int, bytes]]:
        insns = self._disassemble(image.exe)
        jobdir = self._submit(image, insns, stdin, {
            "kind": "memory", "step": step, "ranges": [[va, n] for va, n in ranges],
        }, deadline)
        finished, end = self._wait(jobdir, deadline, None, None)
        if not finished:
            raise АсмОшибка("Память на шаге не снята: исполнитель не уложился в отведённое время")
        try:
            if end.get("status") != "exited":
                raise АсмОшибка(str(end.get("error") or "Память на шаге не снята"))
            data = json.loads((jobdir / proto.MEMORY).read_text(encoding="utf-8"))
            return [(int(va), bytes.fromhex(h)) for va, h in data]
        except (OSError, ValueError, TypeError) as e:
            raise АсмОшибка(f"Память на шаге не прочитана: {e}") from None
        finally:
            shutil.rmtree(jobdir, ignore_errors=True)

    # ── очередь ──────────────────────────────────────────────────────────────

    def _disassemble(self, exe: Path) -> dict[int, tuple[str, bytes]]:
        try:
            st = os.stat(exe)
            key = (str(exe), st.st_mtime_ns, st.st_size)
        except OSError:
            return {}
        if key != self._insns_key:
            self._insns = disassemble(self.objdump, exe)
            self._insns_key = key
        return self._insns

    def _submit(self, image: Image, insns: Mapping[int, tuple[str, bytes]], stdin: bytes,
                request: dict, deadline: float) -> Path:
        beat = proto.read_heartbeat(self.queue)
        if not proto.heartbeat_fresh(beat):
            raise АсмОшибка("Исполнитель трасс MinGW x64 не отвечает")
        new_root = self.queue / proto.NEW
        jobs_root = self.queue / proto.JOBS
        job_id = secrets.token_hex(8)
        tmp = new_root / job_id
        try:
            proto.make_dir(new_root)
            proto.make_dir(jobs_root)
            proto.make_dir(tmp)
            proto.write_file(tmp / proto.EXE, Path(image.exe).read_bytes())
            proto.write_file(tmp / proto.STDIN, bytes(stdin))
            proto.write_json(tmp / proto.IMAGE, proto.image_to_json(image, insns))
            request = dict(request, timeout_s=max(1.0, round(deadline - time.monotonic(), 1)))
            proto.write_json(tmp / proto.REQUEST, request)
            os.rename(tmp, jobs_root / job_id)
        except OSError as e:
            shutil.rmtree(tmp, ignore_errors=True)
            raise АсмОшибка(f"Задание в очередь исполнителя не положено: {e}") from None
        return jobs_root / job_id

    def _wait(self, jobdir: Path, deadline: float, cancelled: Callable[[], bool] | None,
              on_line: Callable[[str], None] | None) -> tuple[bool, dict]:
        """Ждать `done`, отдавая строки шагов. (закончено ли, end.json)."""
        steps_path = jobdir / proto.STEPS
        fh = None
        buf = b""
        cancel_at: float | None = None
        last_beat_check = 0.0

        def pump(final: bool) -> None:
            nonlocal fh, buf
            if on_line is None:
                return
            if fh is None:
                try:
                    fh = open(steps_path, "rb")                         # noqa: SIM115
                except OSError:
                    return
            while True:
                chunk = fh.read(1024 * 1024)
                if not chunk:
                    break
                buf += chunk
                *lines, buf = buf.split(b"\n")
                for line in lines:
                    if line:
                        on_line(line.decode("utf-8"))
            if final and buf.strip():
                on_line(buf.decode("utf-8"))
                buf = b""

        try:
            while True:
                if (jobdir / proto.DONE).exists():
                    pump(True)
                    try:
                        end = json.loads((jobdir / proto.END).read_text(encoding="utf-8"))
                    except (OSError, ValueError):
                        end = {"status": "crashed", "error": "Итог прогона не прочитан"}
                    return True, end if isinstance(end, dict) else {}
                pump(False)
                now = time.monotonic()
                if cancel_at is None:
                    wants_cancel = cancelled is not None and cancelled()
                    if wants_cancel or now > deadline + GRACE_S:
                        self._cancel(jobdir)
                        cancel_at = now
                elif now > cancel_at + CANCEL_GRACE_S:
                    # Итога не дождались: задание остаётся исполнителю, он удалит его сам.
                    try:
                        proto.write_file(jobdir / proto.ABANDONED, b"")
                    except OSError:
                        pass
                    return False, {}
                if now - last_beat_check > 5.0:
                    last_beat_check = now
                    if not (jobdir / proto.CLAIMED).exists() and \
                            not proto.heartbeat_fresh(proto.read_heartbeat(self.queue)):
                        shutil.rmtree(jobdir, ignore_errors=True)
                        raise АсмОшибка("Исполнитель трасс MinGW x64 не отвечает")
                time.sleep(WAIT_POLL_S)
        finally:
            if fh is not None:
                fh.close()

    @staticmethod
    def _cancel(jobdir: Path) -> None:
        try:
            proto.write_file(jobdir / proto.CANCEL, b"")
        except OSError:
            pass

    @staticmethod
    def _take_raw(jobdir: Path, workdir: Path) -> None:
        src = jobdir / proto.RAW
        try:
            if src.stat().st_size > RAW_COPY_MAX:
                return
            shutil.copyfile(src, workdir / proto.RAW)
        except OSError:
            pass


__all__ = ["QueueTracer", "disassemble"]
