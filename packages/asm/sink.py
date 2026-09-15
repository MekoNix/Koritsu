"""sink.py — запись шагов трассы в `trace.jsonl` со свёрткой середины.

Общая для всех наборов инструментов: форма шага (`model.Step`) и договор со службой о файлах
прогона одни и те же — `trace.jsonl` построчно, индекс сырого вывода отладчика рядом. Разное у
наборов только имя индекса (`debugx.idx.json` у TASM, `raw.idx.json` у MinGW x64): служба
находит его по `Toolchain.raw_index`.

Свёртка. Шаги пишутся потоком: первые `HEAD` — сразу на диск, дальше хвост держится в памяти
строками JSON (не больше `TRACE_KEEP_MAX - HEAD`). Если в конце выясняется, что середину надо
свернуть (лимит шагов, или хвост вытеснил шаги), на диск уходит только последние `TAIL`, а в
итоге прогона — `Truncation`. Дампы окон остаются только у шагов, которые в трассе есть.
"""
from __future__ import annotations

import collections
import json
import os
from pathlib import Path

from .model import Dump, Step, Truncation

HEAD = 1000
TAIL = 1000
# Сколько шагов держать в `trace.jsonl` целиком, если программа завершилась сама. Больше —
# середина сворачивается так же, как на лимите: 20 000 шагов — около 9 МБ JSON.
TRACE_KEEP_MAX = 20_000


def _write_json(path: Path, data) -> None:
    # Временное имя своё у процесса: соседние файлы прогона пишут и дампы памяти, идущие
    # параллельно.
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


class TraceSink:
    """Шаги в `trace.jsonl` потоком: начало пишется сразу, хвост держится в памяти строками
    JSON, пока не ясно, сворачивать ли середину.

    `index_name` — имя файла индекса сырого вывода: `[{i, file, offset, length}]` по шагам,
    оставшимся в трассе.
    """

    def __init__(self, workdir: Path, index_name: str) -> None:
        self.workdir = workdir
        self.index_name = index_name
        self.fh = open(workdir / "trace.jsonl.tmp", "w", encoding="utf-8")
        self.count = 0
        self.head_idx: list[dict] = []
        self.tail: collections.deque = collections.deque(maxlen=TRACE_KEEP_MAX - HEAD)
        self.dumps: dict[int, list[Dump]] = {}

    def add(self, step: Step, idx: dict) -> None:
        line = json.dumps(step.to_json(), ensure_ascii=False)
        if self.count < HEAD:
            self.fh.write(line + "\n")
            self.head_idx.append(idx)
        else:
            self.tail.append((step.i, line, idx))
        self.count += 1

    def add_dumps(self, step: int, dumps: list[Dump]) -> None:
        if dumps:
            self.dumps[step] = dumps

    def finish(self, fold: bool) -> tuple[Truncation | None, list[Dump]]:
        rest = list(self.tail)
        truncated = None
        spilled = self.count - HEAD - len(rest)       # вытеснено из хвоста
        if (fold and len(rest) > TAIL) or spilled > 0:
            keep = rest[-TAIL:]
            truncated = Truncation(head=min(self.count, HEAD),
                                   skipped=self.count - HEAD - len(keep), tail=len(keep))
            rest = keep
        for _, line, _ in rest:
            self.fh.write(line + "\n")
        self.fh.close()
        (self.workdir / "trace.jsonl.tmp").replace(self.workdir / "trace.jsonl")
        index = self.head_idx + [idx for _, _, idx in rest]
        _write_json(self.workdir / self.index_name, index)
        kept = set(range(min(self.count, HEAD))) | {i for i, _, _ in rest}
        dumps = [d for step in sorted(self.dumps) if step in kept for d in self.dumps[step]]
        return truncated, dumps

    def abandon(self) -> None:
        if not self.fh.closed:
            self.fh.close()


__all__ = ["TraceSink", "HEAD", "TAIL", "TRACE_KEEP_MAX"]
