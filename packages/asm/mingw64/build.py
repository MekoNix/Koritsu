"""build.py — сборка программы MinGW x64: `as` → `ld` → разбор листинга и образа.

Команды — те же, что у лабы под MSYS2, с ключами человека перед ними (`flags.py`):

    x86_64-w64-mingw32-as <as_flags> -a=prog.lst prog.s -o prog.obj
    x86_64-w64-mingw32-ld <ld_flags> -o prog.exe prog.obj -L<lib> -lkernel32

Без `-e` ld ищет `mainCRTStartup`, не находит и берёт начало `.text` — там у лабы `main`.
Это предупреждение ld, а не ошибка сборки.

**Запуск инструментов.** `subprocess` без оболочки, в каталоге прогона, со своей группой
процессов (таймаут и отмена гасят всё дерево), закрытым окружением (`PATH`, `HOME` = каталог
прогона, `LC_ALL=C.UTF-8` — сообщения не переводятся и разбираются одной регуляркой) и
потолками `resource`: адресное пространство, процессорное время, размер файла (`.space` на
гигабайт упрётся в него, а не в диск), без core. Исходник чужой, а `as` и `ld` — большие
программы на C.

**Сообщения.**

    prog.s: Assembler messages:
    prog.s:12: Error: no such instruction: `movk rax,1'
    prog.s:12: Warning: …
    x86_64-w64-mingw32-ld: prog.obj:prog.s:(.text+0x10): undefined reference to `GetStdHandle'
    x86_64-w64-mingw32-ld: warning: cannot find entry symbol mainCRTStartup; defaulting to 0000000140001000

У `ld` строки исходника нет (без `-g`) — она находится через листинг по `.text+0x10`: это
смещение поля перемещения внутри команды, и строка — та, чей кусок секции его накрывает.
Если `-g` дал строку (`prog.s:88:(.text+0xcb)`), берётся она.

**Что получается.** `BuildResult`:

- `listing` — строка на каждую строку листинга; `text` — из исходника; после удачной компоновки
  `offset` — VA (16 hex), `segment` — секция образа, `bytes` — настоящие байты образа (в
  листинге поля перемещений ещё нули); если образа нет — смещение и секция `prog.obj`;
- `segments` — секции PE: `start`/`length` по VA, 16 hex; класс — `pe.Section.cls`;
- `symbols` — символы `prog.obj` из листинга (`DEFINED SYMBOLS`) с VA; `kind` — `text`,
  `data`, `bss` или `abs`; `size` — до следующего символа той же секции или до её конца.

`build.key` — отпечаток запроса удачной сборки: по нему память на шаге берёт уже собранный
`prog.exe`, а не пересобирает.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import resource
import signal
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from ..model import АсмОшибка, BuildMessage, BuildResult, ListingLine, Segment, Symbol
from . import pe as pe_mod
from .flags import check_flags, source_problem
from .gas import GasListing, LineIndex, parse_listing
from .tools import VERSION, Mingw64Tools

Progress = Callable[[str, int, int], None]
Cancelled = Callable[[], bool]

SOURCE_MAX = 512_000            # знаков исходника

SOURCE = "prog.s"
OBJECT = "prog.obj"
EXE = "prog.exe"
LISTING = "prog.lst"
KEY = "build.key"

# `as` и `ld` на программе лабы укладываются в десятки мегабайт; гигабайт — запас на макросы
# и `.rept`, дальше — уже не программа, а попытка съесть машину.
MEMORY_BYTES = 1024 * 1024 * 1024
FILE_BYTES = 64 * 1024 * 1024
LOG_MAX = 256_000               # байт журнала инструмента, которые читаются
LISTING_MAX = 32 * 1024 * 1024
POLL_S = 0.02


def h16(value: int) -> str:
    return f"{value & 0xFFFF_FFFF_FFFF_FFFF:016X}"


@dataclass(frozen=True)
class Mingw64Request:
    source: str
    stdin: str = ""
    step_limit: int = 20_000
    version: str = VERSION
    as_flags: tuple[str, ...] = ()
    ld_flags: tuple[str, ...] = ()


def source_text(source: str) -> str:
    """Концы строк LF и перевод строки в конце: без него `as` предупреждает «end of file not
    at end of a line», а человек его не писал."""
    text = source.replace("\r\n", "\n").replace("\r", "\n")
    if not text.endswith("\n"):
        text += "\n"
    return text


def request_key(req: Mingw64Request) -> str:
    raw = json.dumps([source_text(req.source), str(req.version), list(req.as_flags),
                      list(req.ld_flags)], ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ── запуск инструмента ───────────────────────────────────────────────────────

def _env(workdir: Path) -> dict:
    return {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "HOME": str(workdir),
        "TMPDIR": str(workdir),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
    }


def _limits(cpu_s: int) -> None:
    resource.setrlimit(resource.RLIMIT_AS, (MEMORY_BYTES, MEMORY_BYTES))
    resource.setrlimit(resource.RLIMIT_CPU, (cpu_s, cpu_s + 2))
    resource.setrlimit(resource.RLIMIT_FSIZE, (FILE_BYTES, FILE_BYTES))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


@dataclass
class _Ran:
    code: int | None
    log: str
    timed_out: bool = False
    cancelled: bool = False


def _read_text(path: Path, limit: int) -> str:
    try:
        with open(path, "rb") as fh:
            return fh.read(limit).decode("utf-8", "replace").replace("\r\n", "\n")
    except OSError:
        return ""


def _kill(proc: subprocess.Popen) -> None:
    if proc.poll() is None:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass


def _run_tool(cmd: list[str], workdir: Path, log_name: str, deadline: float,
              cancelled: Cancelled | None) -> _Ran:
    seconds = max(1, int(deadline - time.monotonic()) + 1)
    log_path = workdir / log_name
    with open(log_path, "wb") as log:
        try:
            proc = subprocess.Popen(
                cmd, cwd=str(workdir), env=_env(workdir), stdin=subprocess.DEVNULL,
                stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
                preexec_fn=lambda: _limits(seconds + 2))
        except OSError as e:
            raise АсмОшибка(f"{Path(cmd[0]).name} не запустился: {e}") from None
        timed_out = was_cancelled = False
        try:
            while proc.poll() is None:
                if cancelled and cancelled():
                    was_cancelled = True
                    break
                if time.monotonic() > deadline:
                    timed_out = True
                    break
                time.sleep(POLL_S)
        finally:
            _kill(proc)
    return _Ran(code=proc.returncode, log=_read_text(log_path, LOG_MAX), timed_out=timed_out,
                cancelled=was_cancelled)


# ── сообщения ────────────────────────────────────────────────────────────────

_AS_MESSAGE = re.compile(
    r"^(?P<file>[^:\n]+?):(?:(?P<line>\d+):)?\s*(?P<sev>Error|Warning|Fatal error|Info):\s*(?P<text>.*)$")
_TOOL_PREFIX = re.compile(r"^(?P<tool>\S*?(?:as|ld)(?:\.exe)?): (?P<rest>.*)$")
_LD_WHERE = re.compile(
    r"^(?P<obj>[^:\s()]+?)(?::(?P<src>[^:()]*?))?(?::(?P<line>\d+))?:\((?P<sec>[^()+]+)\+0x(?P<off>[0-9a-fA-F]+)\): (?P<text>.+)$")


def as_messages(log: str) -> list[BuildMessage]:
    out: list[BuildMessage] = []
    for row in log.split("\n"):
        m = _AS_MESSAGE.match(row)
        if m:
            sev = m.group("sev")
            if sev == "Info":
                continue                     # «macro invoked from here» — пояснение к ошибке выше
            line = int(m.group("line")) if m.group("line") else None
            out.append(BuildMessage(severity="warning" if sev == "Warning" else "error", tool="as",
                                    line=line, text=m.group("text").strip()))
            continue
        p = _TOOL_PREFIX.match(row)
        if p and p.group("tool").endswith(("as", "as.exe")):
            # Ключи и файлы: `as: unrecognized option`, `as: can't open prog.s`.
            out.append(BuildMessage(severity="error", tool="as", line=None,
                                    text=p.group("rest").strip()))
    return out


def ld_messages(log: str, lines: LineIndex) -> list[BuildMessage]:
    out: list[BuildMessage] = []
    for row in log.split("\n"):
        row = row.strip()
        if not row:
            continue
        p = _TOOL_PREFIX.match(row)
        rest = p.group("rest") if p and p.group("tool").endswith(("ld", "ld.exe")) else row
        severity = "error"
        if rest.startswith("warning: "):
            severity, rest = "warning", rest[len("warning: "):]
        if "in function" in rest and rest.endswith(("':", "’:")):
            continue                         # заголовок к сообщению следующей строкой
        line = None
        text = rest
        m = _LD_WHERE.match(rest)
        if m:
            text = m.group("text")
            if m.group("line") and m.group("src") and m.group("src") != "fake":
                line = int(m.group("line"))
            else:
                line = lines.at_offset(m.group("sec"), int(m.group("off"), 16))
            if text.startswith("warning: "):
                severity, text = "warning", text[len("warning: "):]
        elif p is None:
            continue                         # не сообщение ld: хвост предыдущей строки
        out.append(BuildMessage(severity=severity, tool="ld", line=line, text=text.strip()))
    return out


# ── итог ─────────────────────────────────────────────────────────────────────

@dataclass
class Built:
    result: BuildResult
    image: pe_mod.PeImage | None = None
    listing: GasListing = field(default_factory=lambda: GasListing([], [], []))
    lines: LineIndex = field(default_factory=lambda: LineIndex([]))
    timed_out: bool = False
    cancelled: bool = False


def section_bases(image: pe_mod.PeImage | None, listing: GasListing) -> dict[str, int]:
    """VA начала каждой секции `prog.obj`: по символам секций в образе, иначе — начало секции
    образа с тем же именем (`.text$x` → `.text`)."""
    if image is None:
        return {}
    bases = image.object_section_bases()
    by_name = {s.name: s for s in image.sections}
    for ln in listing.lines:
        sec = ln.section
        if sec and sec not in bases:
            target = by_name.get(sec.split("$", 1)[0])
            if target is not None:
                bases[sec] = image.va(target)
    return bases


def _listing_lines(listing: GasListing, image: pe_mod.PeImage | None, bases: dict[str, int],
                   source_lines: list[str]) -> list[ListingLine]:
    out: list[ListingLine] = []
    for ln in listing.lines:
        text = source_lines[ln.line - 1] if 0 < ln.line <= len(source_lines) else ln.text
        data = bytes(ln.data)
        if ln.offset is None or ln.section is None:
            out.append(ListingLine(line=ln.line, segment=None, offset=None,
                                   bytes=data.hex().upper(), text=text))
            continue
        segment, offset = ln.section, ln.offset
        base = bases.get(ln.section)
        if image is not None and base is not None:
            va = base + ln.offset
            section = image.section_at(va)
            if section is not None:
                segment = section.name
                if data:
                    try:
                        data = image.read(va, len(data))
                    except АсмОшибка:
                        pass
            offset = va
        out.append(ListingLine(line=ln.line, segment=segment if data else None,
                               offset=h16(offset) if data else None,
                               bytes=data.hex().upper(), text=text))
    return out


def _kind(section: pe_mod.Section | None, obj_section: str) -> str:
    cls = section.cls if section is not None else ""
    if cls == "CODE" or (not cls and obj_section.startswith(".text")):
        return "text"
    if cls == "BSS" or (not cls and (obj_section.startswith(".bss") or obj_section == "COMMON")):
        return "bss"
    return "data"


def _symbols(listing: GasListing, image: pe_mod.PeImage | None, bases: dict[str, int],
             lines: LineIndex) -> list[Symbol]:
    per_section: dict[str, list[int]] = {}
    for s in listing.symbols:
        if s.line is not None and not s.section.startswith("*") and s.section != "COMMON":
            per_section.setdefault(s.section, []).append(s.value)
    for values in per_section.values():
        values.sort()

    out: list[Symbol] = []
    for s in listing.symbols:
        if s.line is None or s.section == "*UND*":
            continue
        if s.section == "*ABS*":
            out.append(Symbol(name=s.name, segment="*ABS*", offset=h16(s.value), kind="abs",
                              size=None))
            continue
        va: int | None = None
        if s.section in bases:
            va = bases[s.section] + s.value
        elif image is not None:
            found = image.find_symbol(s.name)
            va = image.symbol_va(found) if found is not None else None
        section = image.section_at(va) if image is not None and va is not None else None
        if s.section == "COMMON":
            # У `.comm` значение в листинге — размер, а место выбирает ld.
            size: int | None = s.value
        else:
            values = per_section.get(s.section, [])
            nxt = next((v for v in values if v > s.value), None)
            end = nxt if nxt is not None else lines.end(s.section)
            size = end - s.value if end > s.value else None
        out.append(Symbol(name=s.name, segment=section.name if section else s.section,
                          offset=h16(va if va is not None else s.value),
                          kind=_kind(section, s.section), size=size))
    return out


def _segments(image: pe_mod.PeImage | None) -> list[Segment]:
    if image is None:
        return []
    return [Segment(name=s.name, cls=s.cls, start=h16(image.va(s)), length=h16(s.size))
            for s in image.sections]


def _finish(source: str, listing_text: str, image: pe_mod.PeImage | None, *, ok: bool,
            log: str, messages: list[BuildMessage]) -> Built:
    listing = parse_listing(listing_text, source) if listing_text else GasListing([], [], [])
    bases = section_bases(image, listing)
    lines = LineIndex(listing.lines, bases)
    result = BuildResult(ok=ok, log=log, messages=messages,
                         listing=_listing_lines(listing, image, bases, source.split("\n")),
                         segments=_segments(image), symbols=_symbols(listing, image, bases, lines))
    return Built(result=result, image=image, listing=listing, lines=lines)


# ── сборка ───────────────────────────────────────────────────────────────────

def check_request(req: Mingw64Request) -> tuple[list[str], list[str]]:
    """Исходник, версия и ключи; `АсмОшибка` — запрос негоден. Отдаёт чистые ключи as и ld."""
    if not isinstance(req.source, str) or len(req.source) > SOURCE_MAX:
        raise АсмОшибка(f"Исходник длиннее {SOURCE_MAX} знаков")
    if str(req.version) != VERSION:
        raise АсмОшибка(f"Версии MinGW x64 {str(req.version)[:20]!r} нет — есть {VERSION}")
    return check_flags("as", req.as_flags), check_flags("ld", req.ld_flags)


def assemble(req: Mingw64Request, tools: Mingw64Tools, workdir: Path, deadline: float,
             progress: Progress | None = None, cancelled: Cancelled | None = None) -> Built:
    """Собрать программу. Ошибки программы — в `BuildResult.messages`, не исключением."""
    as_flags, ld_flags = check_request(req)
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    for name in (SOURCE, OBJECT, EXE, LISTING, KEY, "as.txt", "ld.txt"):
        (workdir / name).unlink(missing_ok=True)
    source = source_text(req.source)
    (workdir / SOURCE).write_bytes(source.encode("utf-8"))

    problem = source_problem(source)
    if problem is not None:
        line, text = problem
        return _finish(source, "", None, ok=False, log=f"{SOURCE}:{line}: Error: {text}\n",
                       messages=[BuildMessage(severity="error", tool="as", line=line, text=text)])

    as_bin = tools.executable("as")
    ld_bin = tools.executable("ld")
    if as_bin is None or ld_bin is None:
        raise АсмОшибка(f"Нет {tools.prefix}as или {tools.prefix}ld")

    if progress:
        progress("as", 0, 1)
    ran_as = _run_tool([as_bin, *as_flags, f"-a={LISTING}", SOURCE, "-o", OBJECT],
                       workdir, "as.txt", deadline, cancelled)
    messages = as_messages(ran_as.log)
    listing_text = _read_text(workdir / LISTING, LISTING_MAX)
    # Индекс строк без баз: сообщения ld говорят смещением в секции prog.obj.
    obj_lines = LineIndex(parse_listing(listing_text, source).lines) if listing_text else LineIndex([])

    ran_ld: _Ran | None = None
    as_failed = (ran_as.timed_out or ran_as.cancelled or ran_as.code != 0
                 or any(m.severity == "error" for m in messages))
    if not as_failed and (workdir / OBJECT).is_file():
        if progress:
            progress("ld", 0, 1)
        ran_ld = _run_tool([ld_bin, *ld_flags, "-o", EXE, OBJECT, f"-L{tools.lib_dir}",
                            "-lkernel32"], workdir, "ld.txt", deadline, cancelled)
        messages += ld_messages(ran_ld.log, obj_lines)

    timed_out = ran_as.timed_out or bool(ran_ld and ran_ld.timed_out)
    was_cancelled = ran_as.cancelled or bool(ran_ld and ran_ld.cancelled)
    image = None
    if ran_ld is not None and ran_ld.code == 0 and not timed_out and not was_cancelled \
            and (workdir / EXE).is_file():
        try:
            image = pe_mod.parse(workdir / EXE)
        except АсмОшибка as e:
            messages.append(BuildMessage(severity="error", tool="ld", line=None, text=str(e)))

    errors = [m for m in messages if m.severity == "error"]
    ok = image is not None and not errors
    if not ok and not errors:
        if was_cancelled:
            text, tool = "Сборка отменена", "as" if ran_ld is None else "ld"
        elif timed_out:
            text, tool = "Сборка не уложилась в отведённое время", "as" if ran_ld is None else "ld"
        elif ran_ld is None:
            text, tool = "as не создал объектный файл — подробности в логе сборки", "as"
        else:
            text, tool = "ld не создал исполняемый файл — подробности в логе сборки", "ld"
        messages.append(BuildMessage(severity="error", tool=tool, line=None, text=text))

    log = ran_as.log
    if ran_ld is not None and ran_ld.log:
        log = (log.rstrip("\n") + "\n\n" + ran_ld.log) if log else ran_ld.log
    built = _finish(source, listing_text, image if ok else None, ok=ok, log=log,
                    messages=messages)
    built.timed_out, built.cancelled = timed_out, was_cancelled
    if ok:
        (workdir / KEY).write_text(request_key(req), encoding="utf-8")
    return built


def reuse(req: Mingw64Request, workdir: Path) -> Built | None:
    """Удачная сборка этого же запроса, если её файлы на месте: для памяти на шаге
    пересобирать незачем."""
    workdir = Path(workdir)
    try:
        if (workdir / KEY).read_text(encoding="utf-8").strip() != request_key(req):
            return None
    except OSError:
        return None
    if not (workdir / EXE).is_file():
        return None
    try:
        image = pe_mod.parse(workdir / EXE)
    except АсмОшибка:
        return None
    return _finish(source_text(req.source), _read_text(workdir / LISTING, LISTING_MAX), image,
                   ok=True, log="", messages=[])


__all__ = ["Mingw64Request", "Built", "assemble", "reuse", "check_request", "request_key",
           "source_text", "section_bases", "as_messages", "ld_messages", "h16",
           "SOURCE", "OBJECT", "EXE", "LISTING", "KEY", "SOURCE_MAX"]
