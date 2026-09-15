"""
cards — ядро «Тренажёра»: формат набора карточек, проверка и план захода.

**Что делает пакет.** Набор карточек живёт в файле JSON (`docs/cards-format.md`): объект с
названием, рекомендуемыми настройками и массивом `cards`, у карточки — вопрос `q`, ответ `a`,
необязательные тема названием, разбор и устойчивый id. Текст полей — безопасное подмножество
Markdown с формулами. Пакет читает такой файл и CSV в один и тот же `CardSet`, проверяет его
одним валидатором, пишет обратно канонический `.json`, сравнивает версии и строит порядок
карточек для захода.

    read_json(data, filename=)       .json → набор из годных карточек + проблемы с путями JSON
    write_json(set)                  набор → канонический .json, id у каждой карточки
    read_csv(text, delimiter=)       CSV/TSV → набор + проблемы по строкам
    csv_json(text, delimiter=, …)    CSV/TSV → текст .json со всеми карточками, годными и нет
    validate(set)                    готовый набор (от агента, службы) → проблемы
    sanitize_md(text)                текст карточки → нарушения безопасного подмножества
    card_markdown(card)              одна карточка Markdown для «Скопировать»
    diff(old, new)                   {added, changed, removed} по ключам
    plan_session(set, last, …)       ключи карточек захода по порядку

**Чистый пакет.** Только стандартная библиотека: ни диска, ни базы, ни модели. Файл
приходит строкой или байтами, результат — объекты и строки. Хранение, прогресс и задание
агента — в службе и оркестраторе.

**Проблема — не исключение.** Разбор не падает на кривом файле: он возвращает всё, что
понял, и список `Problem(line, code, text, card, path)` с понятным текстом по-русски.
`path` — путь JSON (`cards[12].a`), `line` — строка битого JSON или CSV. Проблема с `card`
отклоняет карточку, без `card` — касается файла. Набор `None` — только когда разбирать
нечего, файл не читается или за потолками.

Состав пакета:

    model.py      модели, потолки, ключи карточек, slug тем
    scan.py       строки блоков кода и формул — где разметка не действует
    sanitize.py   безопасное подмножество Markdown
    check.py      валидатор карточек и набора
    jsonfile.py   чтение и запись .json
    csvin.py      чтение CSV/TSV
    clip.py       карточка для «Скопировать»
    session.py    план захода и сравнение версий
"""
from __future__ import annotations

from .check import validate
from .clip import card_markdown
from .csvin import csv_json, read_csv
from .jsonfile import read_json, write_json
from .model import (DESCRIPTION_LIMIT, FILE_BYTES, FORMAT, FORMAT_VERSION, INCLUDE, MAX_CARDS,
                    MAX_TOPICS, ORDERS, TEXT_LIMIT, TITLE_LIMIT, Card, CardSet, Defaults,
                    Problem, Topic, question_key)
from .sanitize import sanitize_md
from .session import diff, plan_session

__all__ = [
    "Topic", "Card", "Defaults", "CardSet", "Problem",
    "read_json", "write_json", "read_csv", "csv_json", "validate", "sanitize_md", "diff",
    "card_markdown", "plan_session",
    "ORDERS", "INCLUDE", "FORMAT", "FORMAT_VERSION",
    "FILE_BYTES", "MAX_CARDS", "MAX_TOPICS", "TEXT_LIMIT", "TITLE_LIMIT", "DESCRIPTION_LIMIT",
    "question_key",
]
