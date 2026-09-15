"""csvin.py — CSV/TSV в тот же набор: колонки `вопрос, ответ[, тема[, разбор]]`.

Так экспортируют Quizlet и Anki («Notes in Plain Text»). Разделитель — из аргумента, из
строки Anki `#separator:` или по первой строке: табуляция, затем `;`, затем `,`.
Заголовок `вопрос,ответ` (или `question,answer`, `front,back`) пропускается.

У Anki впереди служебные строки `#separator:tab`, `#html:true`, `#tags column:3`. Колонки
тегов, заметки, колоды и guid выбрасываются. При `#html:true` переносы `<br>` и `<div>`
становятся переводами строк, а сущности `&amp;` раскрываются; остальной HTML остаётся и
даёт проблему, как в файле JSON.

`csv_json` переводит таблицу в текст файла JSON со всеми прочитанными карточками, включая
те, что не пройдут проверку: черновик набора хранится JSON, а человек должен увидеть и
поправить отклонённые карточки, а не потерять их при переводе.
"""
from __future__ import annotations

import csv
import html as _html
import io
import json
import re
from pathlib import PurePath

from .check import Raw, assemble, raw_from_text, sort_problems
from .model import (DEFAULT_LANGUAGE, DEFAULT_TITLE, FILE_BYTES, FORMAT, FORMAT_VERSION,
                    MAX_CARDS, MAX_TOPICS, CardSet, Defaults, Problem, normalize_input, number,
                    title_norm)

_DIRECTIVE = re.compile(r"^#([a-z ]+):(.*)$", re.I)
_SEPARATORS = {"tab": "\t", "comma": ",", "semicolon": ";", "pipe": "|", "space": " ",
               "colon": ":"}
_Q_HEADS = {"вопрос", "question", "front", "term", "лицевая сторона"}
_A_HEADS = {"ответ", "answer", "back", "definition", "оборотная сторона"}
_BREAK = re.compile(r"<\s*br\s*/?\s*>|<\s*/?\s*div\s*>|<\s*/?\s*p\s*>", re.I)


def _sniff(lines: list[str]) -> str:
    first = next((ln for ln in lines if ln.strip()), "")
    if "\t" in first:
        return "\t"
    return ";" if first.count(";") > first.count(",") else ","


def _rows(text: str, delimiter: str | None) -> tuple[list[Raw] | None, list[Problem]]:
    """Таблица → сырые карточки строк и проблемы. `None` — файл за потолком размера."""
    size = len(text.encode("utf-8", "surrogatepass"))
    if size > FILE_BYTES:
        return None, [Problem(None, "file_too_big",
                              "файл больше 5 МБ — разделите набор на несколько файлов")]
    lines = normalize_input(text).split("\n")
    problems: list[Problem] = []

    skip, html_fields, drop = 0, False, set()
    for line in lines:
        m = _DIRECTIVE.match(line)
        if not m:
            break
        skip += 1
        key, value = m.group(1).strip().lower(), m.group(2).strip()
        if key == "separator" and delimiter is None:
            delimiter = _SEPARATORS.get(value.lower(), value[:1] or None)
        elif key == "html":
            html_fields = value.lower() == "true"
        elif key.endswith(" column") and value.isdigit():
            drop.add(int(value) - 1)
    body = lines[skip:]
    if not delimiter:
        delimiter = _sniff(body)

    reader = csv.reader(io.StringIO("\n".join(body), newline=""), delimiter=delimiter,
                        quotechar='"')
    raws: list[Raw] = []
    prev_end = 0
    first_row = True
    try:
        for row in reader:
            start = skip + prev_end + 1
            prev_end = reader.line_num
            cells = [c for i, c in enumerate(row) if i not in drop]
            if not any(c.strip() for c in cells):
                continue
            if first_row:
                first_row = False
                if len(cells) >= 2 and cells[0].strip().lower() in _Q_HEADS \
                        and cells[1].strip().lower() in _A_HEADS:
                    continue
            while len(cells) > 4 and not cells[-1].strip():
                cells.pop()
            if len(cells) < 2:
                problems.append(Problem(start, "csv_columns",
                                        "в строке одна колонка, а нужны хотя бы две: вопрос и "
                                        "ответ — проверьте разделитель"))
                continue
            if len(cells) > 4:
                problems.append(Problem(start, "csv_columns",
                                        f"в строке {len(cells)} колонок, а их не больше четырёх: "
                                        "вопрос, ответ, тема, разбор"))
                continue
            if html_fields:
                cells = [_html.unescape(_BREAK.sub("\n", c)) for c in cells]
            cells = [c.strip() for c in cells] + [""] * (4 - len(cells))
            q, a, topic, note = cells
            raws.append(raw_from_text(len(raws), start, q, a, note or None, topic or None))
    except csv.Error as exc:
        problems.append(Problem(skip + prev_end + 1, "csv_syntax",
                                f"строка не разбирается как CSV: {exc}"))
    return raws, problems


def read_csv(text: str, delimiter: str | None = None) -> tuple[CardSet | None, list[Problem]]:
    """Текст CSV/TSV → набор из годных карточек и проблемы по строкам."""
    raws, problems = _rows(text, delimiter)
    if raws is None:
        return None, problems

    if len(raws) > MAX_CARDS:
        return None, sort_problems(problems + [Problem(
            None, "too_many_cards", f"в файле {number(len(raws))} карточек, а потолок "
                                    f"{number(MAX_CARDS)} — разделите набор")])
    if len({title_norm(r.topic) for r in raws if r.topic}) > MAX_TOPICS:
        return None, sort_problems(problems + [Problem(
            None, "too_many_topics", f"тем больше {MAX_TOPICS} — объедините темы")])

    topics, cards, _ = assemble(raws, problems)
    if not cards:
        problems.append(Problem(None, "no_cards", "в файле нет ни одной годной карточки"))
        return None, sort_problems(problems)
    return (CardSet(title=DEFAULT_TITLE, description="", language=DEFAULT_LANGUAGE,
                    topics=topics, cards=cards, defaults=Defaults()),
            sort_problems(problems))


def csv_json(text: str, delimiter: str | None = None, *, filename: str = "") -> str:
    """Текст CSV/TSV → текст файла JSON со всеми карточками строк, годными и нет.

    Строки, которые карточкой не стали (одна колонка, больше четырёх), в файл не попадают:
    о них говорят проблемы `read_csv`. Название — имя файла без расширения, если оно есть.
    """
    raws, _ = _rows(text, delimiter)
    doc: dict[str, object] = {"format": FORMAT, "version": FORMAT_VERSION}
    title = PurePath(filename).stem.strip() if filename else ""
    if title:
        doc["title"] = title
    cards = []
    for r in raws or ():
        item: dict[str, str] = {}
        if r.topic:
            item["topic"] = r.topic
        item["q"] = r.q
        item["a"] = r.a
        if r.note:
            item["note"] = r.note
        cards.append(item)
    doc["cards"] = cards
    return json.dumps(doc, ensure_ascii=False, indent=2) + "\n"


__all__ = ["read_csv", "csv_json"]
