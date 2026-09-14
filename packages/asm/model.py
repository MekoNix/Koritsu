"""model.py — формы, которыми ядро отвечает службе.

Каждая форма — dataclass с `to_json()`. JSON — snake_case; шестнадцатеричные числа — строки
ВЕРХНИМ регистром без `0x`: 4 знака для слов, 8 для 32-битных значений, 5 для линейных адресов
образа из `.map` (они 20-битные). Байты (`bytes`, `hex`, `old`, `new`) — hex без `0x`.

Что описывает шаг. Шаг `i` — состояние ПОСЛЕ `i`-й выполненной команды: `reg`, `reg32`,
`changed`, `mem`, `out`, `stdin_pos`. Поля `cs`, `ip`, `line`, `asm`, `bytes` — сама эта
команда; `next` — команда, которая выполнится следующей (DebugX печатает её строкой после
регистров), после выхода программы `next` — `None`. Шаг `0` — состояние до первой команды:
`asm=''`, `bytes=''`, `line=None`, `cs:ip` и `next` — точка входа.

Шаг, на котором программа завершилась (`int 21h`/4Ch, `int 20h`), в трассе есть, но регистров
после него нет — процесса уже нет. У такого шага `reg` повторяет предыдущий, `changed` пуст,
`next` — `None`, а код выхода лежит в `RunResult.totals.exit_code`.

`out` — байты вывода программы в кодировке CP866, переводы строк `\\r\\n` сведены к `\\n`,
одиночный `\\r` оставлен как есть.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal


class АсмОшибка(Exception):
    """Прогон нельзя начать: инструментов нет, запрос негоден, DOSBox-X не запустился.

    Всё, что случилось с программой человека (ошибка сборки, зависание, падение), ошибкой
    ядра не считается и приезжает в `RunResult.status` — это результат прогона, а не беда.
    """


def _json(obj) -> dict:
    return asdict(obj)


@dataclass(frozen=True)
class RunRequest:
    source: str
    stdin: str = ""
    step_limit: int = 100_000
    mode32: bool = False
    tasm_flags: tuple[str, ...] = ("/zi", "/l")
    tlink_flags: tuple[str, ...] = ("/v",)

    to_json = _json


@dataclass
class BuildMessage:
    severity: Literal["error", "warning"]
    tool: Literal["tasm", "tlink"]
    line: int | None
    text: str

    to_json = _json


@dataclass
class ListingLine:
    line: int
    segment: str | None
    offset: str | None
    bytes: str
    text: str

    to_json = _json


@dataclass
class Segment:
    name: str
    cls: str
    start: str
    length: str

    to_json = _json


@dataclass
class Symbol:
    name: str
    segment: str
    offset: str
    kind: str
    size: int | None

    to_json = _json


@dataclass
class BuildResult:
    ok: bool
    log: str
    messages: list[BuildMessage] = field(default_factory=list)
    listing: list[ListingLine] = field(default_factory=list)
    segments: list[Segment] = field(default_factory=list)
    symbols: list[Symbol] = field(default_factory=list)

    to_json = _json


@dataclass
class MemWrite:
    seg: str
    off: str
    old: str
    new: str

    to_json = _json


@dataclass
class Step:
    i: int
    cs: str
    ip: str
    line: int | None
    asm: str
    bytes: str
    reg: dict[str, str]
    reg32: dict[str, str] | None
    changed: list[str]
    mem: list[MemWrite]
    out: str
    stdin_pos: int
    next: dict | None = None   # {cs, ip, line, asm, bytes}

    to_json = _json


@dataclass
class Truncation:
    head: int
    skipped: int
    tail: int

    to_json = _json


@dataclass
class Dump:
    step: int
    seg: str
    off: str
    hex: str

    to_json = _json


RunStatus = Literal["done", "build_error", "step_limit", "timeout", "crashed"]


@dataclass
class RunResult:
    """Итог прогона без шагов (шаги — построчно в `trace.jsonl`).

    `status`:
      done         программа завершилась сама — или трасса честно остановлена там, где её
                   нельзя продолжить без человека (ввод кончился, чтение клавиатуры через
                   int 16h); тогда `totals.exit_code` — `None`, а причина — в `error`
      build_error  TASM или TLINK не собрали программу; шагов нет
      step_limit   программа не завершилась за `step_limit` шагов
      timeout      прогон не уложился в отведённое время; шаги до обрыва сохранены
      crashed      сломалось ядро или DOSBox-X, прогон отменён; причина в `error`

    `load` — `{psp, cs, ds, ss}` при загрузке: `ds` — сегмент данных программы по `.map` (тот,
    что окажется в DS после `mov ds, @data`), а не DS в момент загрузки (он равен PSP).
    `totals` — `{steps, ms, exit_code}`: `steps` — сколько команд реально выполнено.
    `dumps` — дампы окон данных и стека на шаге 0 и на границах пачек за пределами пошаговых
    дампов; внутри них изменения памяти лежат в `Step.mem`.
    """
    status: RunStatus
    build: BuildResult
    load: dict | None
    stdin: str
    step_limit: int
    mode32: bool
    totals: dict
    truncated: Truncation | None = None
    dumps: list[Dump] = field(default_factory=list)
    error: str | None = None

    to_json = _json


__all__ = ["АсмОшибка", "RunRequest", "BuildMessage", "ListingLine", "Segment", "Symbol",
           "BuildResult", "MemWrite", "Step", "Truncation", "Dump", "RunResult", "RunStatus"]
