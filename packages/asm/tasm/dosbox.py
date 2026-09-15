"""dosbox.py — запуск DOSBox-X без экрана, с потолками и своей группой процессов.

Как запускается (проверено на DOSBox-X 2025.02.01, `samples/command.txt`):

* `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy` — окна нет, звука нет;
* свой `dosbox.conf` в каталоге прогона и `HOME` = каталог прогона: пользовательский конфиг с
  машины не подхватывается, сеть (ne2000, ipx, последовательные порты) выключена;
* `-silent -exit -fastlaunch -nomenu -nogui` — без заставки, выход после autoexec;
* `-time-limit` — эмулятор гасит себя сам, `timeout -k` снаружи — если не погасил, а убийство
  группы процессов — если не успел и `timeout`. Выход по `-time-limit` штатный: перенаправленный
  вывод DOS, пока эмулятор работает, на диске может не расти вовсе и дописывается при выходе,
  а убийство снаружи его теряет. Поэтому потолок времени запуска ставится самим `-time-limit`,
  а `Process.ran_out()` говорит, что выход был по нему.

Диски: `C:` — каталог прогона, `D:` — TASM/TLINK, `E:` — DebugX; оба последних `-ro`.
Программа человека пишет только в `C:`. Имена файлов, которые видит DOS, — 8.3: пакетный файл
`MEMORY-2-TRACE.BAT` оболочка DOSBox-X не находит, и `CALL` молча ничего не делает.

`C:` монтируется не прямым путём каталога прогона, а короткой символьной ссылкой на него во
временном каталоге. Каталог прогона на томе лежит глубоко (пространство, работа, решение,
номер прогона) — больше двухсот символов, и с таким путём TASM под DOSBox-X не открывает
исходник и молча выходит, не написав ни строки; тот же каталог через ссылку собирается.

Ссылка своя у каждого `conf` — в имени случайная часть. В одном каталоге прогона эмуляторов
бывает несколько сразу (дампы памяти одной трассы), и общая на каталог ссылка,
убранная первым закончившимся запуском, увела бы `C:` из-под соседнего. `Process` берёт путь
ссылки из строки `mount c` своего `conf`, заводит ссылку перед запуском (и заново, если `conf`
запускается не в первый раз) и убирает после — только её.

Окружение дочернего процесса закрытое, как у `api/subproc.py`: `PATH`, `HOME`, язык и
переменные SDL — и ничего больше. Эмулятор исполняет чужой код, и ключам службы рядом с ним
делать нечего.
"""
from __future__ import annotations

import math
import os
import re
import resource
import shutil
import secrets
import signal
import subprocess
import tempfile
import time
from pathlib import Path

from ..model import АсмОшибка
from .tools import Tools

# Адресное пространство DOSBox-X: гостю отдано 16 МБ, остальное — библиотеки SDL. Запуск с
# 256 МБ проверен; потолок взят втрое, чтобы не упереться в резерв библиотек на другой машине.
MEMORY_BYTES = 768 * 1024 * 1024
# Самый большой файл, который процесс может написать: сырой вывод 500 000 шагов — около
# 90 МБ, остальное — запас на дампы. Программа, пишущая файл без конца, упрётся сюда.
FILE_BYTES = 1024 * 1024 * 1024

CONF = """\
[sdl]
autolock=false
[log]
logfile=
[dosbox]
memsize=16
quit warning=false
[cpu]
core=normal
cputype=pentium
cycles=max
[mixer]
nosound=true
[speaker]
pcspeaker=false
[sblaster]
sbtype=none
[gus]
gus=false
[midi]
mididevice=none
[serial]
serial1=disabled
serial2=disabled
serial3=disabled
serial4=disabled
[parallel]
parallel1=disabled
parallel2=disabled
parallel3=disabled
[ne2000]
ne2000=false
[ipx]
ipx=false
[autoexec]
"""


def _quote(path: Path) -> str:
    return '"' + str(path) + '"'


def dos_name(path: Path) -> str:
    return path.name.upper()


# Строка монтирования `C:` в autoexec — по ней `Process` находит ссылку своего запуска.
_MOUNT_C = re.compile(r'^mount c "([^"]+)"', re.MULTILINE)
_LINK_PREFIX = "asm-"


def short_path() -> Path:
    """Новое короткое имя ссылки на каталог прогона (см. шапку модуля). Сама ссылка
    заводится в `Process`: имя попадает в `conf` раньше, чем эмулятор запущен."""
    return Path(tempfile.gettempdir()) / f"{_LINK_PREFIX}{secrets.token_hex(8)}"


def _link_of(conf: Path) -> Path | None:
    try:
        m = _MOUNT_C.search(conf.read_text(encoding="utf-8"))
    except OSError:
        return None
    if m is None:
        return None
    link = Path(m.group(1))
    # Удалять можно только своё: ссылку во временном каталоге с нашим префиксом.
    if link.parent != Path(tempfile.gettempdir()) or not link.name.startswith(_LINK_PREFIX):
        return None
    return link


def _make_link(link: Path, workdir: Path) -> None:
    target = str(workdir.resolve())
    if os.path.islink(link) and os.readlink(link) == target:
        return
    tmp = link.with_name(link.name + f".{os.getpid()}")
    try:
        os.unlink(tmp)
    except FileNotFoundError:
        pass
    os.symlink(target, tmp)
    os.replace(tmp, link)


def _drop_link(link: Path, workdir: Path) -> None:
    try:
        if os.path.islink(link) and os.readlink(link) == str(workdir.resolve()):
            os.unlink(link)
    except OSError:
        pass


def autoexec_prefix(tools: Tools) -> list[str]:
    """Одинаковое начало autoexec у сборки и трассы.

    Одинаковое не для красоты: PSP программы зависит от окружения DOS (`set PATH` сдвигает
    его на несколько параграфов), а сегменты окон дампа считаются по пробному запуску при
    сборке. Разойдись начало — разошлись бы и адреса.
    """
    return [
        f"mount c {_quote(short_path())}",
        f"mount d {_quote(tools.tools_dir)} -ro",
        f"mount e {_quote(tools.debugx.parent)} -ro",
        "c:",
        "set PATH=D:\\;E:\\",
    ]


def write_conf(workdir: Path, name: str, autoexec: list[str]) -> Path:
    path = workdir / name
    path.write_text(CONF + "\n".join(autoexec) + "\n", encoding="utf-8")
    return path


def write_bat(workdir: Path, name: str, lines: list[str]) -> Path:
    """Пакетный файл DOS. Концы строк CRLF: оболочка DOSBox читает и LF, но DOS — нет."""
    path = workdir / name
    path.write_bytes(("\r\n".join(lines) + "\r\n").encode("ascii"))
    return path


def _env(workdir: Path) -> dict:
    env = {
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "HOME": str(workdir),
        "LANG": "C.UTF-8",
        "SDL_VIDEODRIVER": "dummy",
        "SDL_AUDIODRIVER": "dummy",
    }
    return env


def _limits(cpu_s: int) -> None:
    resource.setrlimit(resource.RLIMIT_AS, (MEMORY_BYTES, MEMORY_BYTES))
    resource.setrlimit(resource.RLIMIT_CPU, (cpu_s, cpu_s + 2))
    resource.setrlimit(resource.RLIMIT_FSIZE, (FILE_BYTES, FILE_BYTES))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


class Process:
    """Один запуск DOSBox-X. Всегда в своей группе процессов: `kill()` гасит дерево целиком."""

    def __init__(self, tools: Tools, workdir: Path, conf: Path, *, seconds: float,
                 log_name: str) -> None:
        self.time_limit = max(1, int(math.ceil(seconds)))
        cmd = [str(tools.dosbox), "-conf", str(conf), "-silent", "-exit", "-fastlaunch",
               "-nomenu", "-nogui", "-time-limit", str(self.time_limit)]
        timeout_bin = shutil.which("timeout")
        if timeout_bin:
            cmd = [timeout_bin, "-k", "2", str(self.time_limit + 2)] + cmd
        self._workdir = workdir
        self._link = _link_of(conf)
        if self._link is not None:
            _make_link(self._link, workdir)
        self._log = open(workdir / log_name, "wb")
        self.started = time.monotonic()
        try:
            self.proc = subprocess.Popen(
                cmd, cwd=str(workdir), env=_env(workdir), stdin=subprocess.DEVNULL,
                stdout=self._log, stderr=subprocess.STDOUT, start_new_session=True,
                preexec_fn=lambda: _limits(self.time_limit + 5))
        except OSError as e:
            self.close()
            raise АсмОшибка(f"DOSBox-X не запустился: {e}") from None

    def poll(self) -> int | None:
        return self.proc.poll()

    def ran_out(self) -> bool:
        """Эмулятор вышел, проработав свой `-time-limit`, — то есть по нему, а не сам."""
        return (self.proc.poll() is not None
                and time.monotonic() - self.started >= self.time_limit - 0.5)

    def overdue(self) -> bool:
        """Работает дольше, чем его погасили бы `-time-limit` и `timeout -k`: пора убивать."""
        return self.proc.poll() is None and time.monotonic() - self.started > self.time_limit + 5

    def kill(self) -> None:
        if self.proc.poll() is None:
            try:
                os.killpg(self.proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        self.close()

    def close(self) -> None:
        if not self._log.closed:
            self._log.close()
        if self._link is not None:
            _drop_link(self._link, self._workdir)

    def __enter__(self) -> "Process":
        return self

    def __exit__(self, *exc) -> None:
        self.kill()


__all__ = ["Process", "autoexec_prefix", "write_conf", "write_bat", "dos_name", "CONF",
           "MEMORY_BYTES", "FILE_BYTES"]
