"""scan.py — какие строки текста лежат в блоке кода или формуле.

Разметка карточки (`#`, `##`, `---`, `>`) узнаётся только в обычных строках: `# комментарий`
в блоке кода или `---` в YAML внутри ```` ``` ```` не начинают тему и не делят карточку.
Поэтому любой разбор сначала размечает строки: `text`, `code` (ограда ```` ``` ```` / `~~~`
и всё внутри), `math` (блок `$$ … $$` на отдельных строках).

**Незакрытый блок не проглатывает файл.** По CommonMark блок кода без закрывающей ограды
тянется до конца файла — и одна забытая ограда молча превратила бы все карточки ниже в
код одного ответа. Здесь открывающая строка без пары считается обычной строкой, а сама
незакрытость возвращается проблемой: карточка с ней отклоняется, остальные разбираются.

Пара ищется по заранее собранным спискам закрывающих строк, так что разметка линейна и на
враждебном файле из тысяч незакрытых оград.
"""
from __future__ import annotations

import bisect
import re

_FENCE_OPEN = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
_FENCE_CLOSE = re.compile(r"^ {0,3}(`{3,}|~{3,})[ \t]*$")


def _dollars(line: str) -> int:
    return len(re.findall(r"(?<!\\)\$\$", line))


def _opens_math(line: str) -> bool:
    return line.lstrip().startswith("$$") and _dollars(line) % 2 == 1


def scan(lines: list[str]) -> tuple[list[str], list[tuple[int, str]]]:
    """Строки → вид каждой (`text` | `code` | `math`) и незакрытые блоки `(индекс, вид)`."""
    closes: dict[str, list[int]] = {"`": [], "~": []}
    close_len: dict[str, list[int]] = {"`": [], "~": []}
    odd: list[int] = []
    for i, line in enumerate(lines):
        m = _FENCE_CLOSE.match(line)
        if m:
            closes[m.group(1)[0]].append(i)
            close_len[m.group(1)[0]].append(len(m.group(1)))
        if _dollars(line) % 2 == 1:
            odd.append(i)

    kinds = ["text"] * len(lines)
    unclosed: list[tuple[int, str]] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        m = _FENCE_OPEN.match(line)
        if m and not (m.group(1)[0] == "`" and "`" in m.group(2)):
            ch, n = m.group(1)[0], len(m.group(1))
            pos = bisect.bisect_right(closes[ch], i)
            end = None
            while pos < len(closes[ch]):
                if close_len[ch][pos] >= n:
                    end = closes[ch][pos]
                    break
                pos += 1
            if end is None:
                unclosed.append((i, "code"))
                i += 1
                continue
            for j in range(i, end + 1):
                kinds[j] = "code"
            i = end + 1
            continue
        if _opens_math(line):
            pos = bisect.bisect_right(odd, i)
            if pos >= len(odd):
                unclosed.append((i, "math"))
                i += 1
                continue
            end = odd[pos]
            for j in range(i, end + 1):
                kinds[j] = "math"
            i = end + 1
            continue
        i += 1
    return kinds, unclosed


__all__ = ["scan"]
