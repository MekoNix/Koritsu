"""check.py — один валидатор на все входы: файл JSON, CSV, набор от агента или службы.

Разбор источника (JSON или CSV) собирает сырые карточки — текст вопроса, ответа и разбора,
тему названием, id как написан и место карточки в источнике: номер строки у CSV, путь JSON
(`cards[3]`) у файла набора — и отдаёт их сюда. Проверки те же, что у `validate` для готового
набора.

**Проблема с `card` отклоняет карточку.** В набор из разбора попадают только годные
карточки; отклонённые видны по проблемам. Проблема без `card` — про файл целиком
(название, настройки, темы): карточек она не отклоняет, но и «весь файл без замечаний»
уже неправда. Что делать с частично годным файлом, решает вызывающий: «только годные» — это
`len(s.cards)` из `len(s.cards) + len({p.card for p in problems if p.card is not None})`.

**Разметка внутри полей — только безопасное подмножество** (`sanitize.py`). Строение набора
задаёт JSON, поэтому заголовки, цитаты и черта `---` внутри вопроса или ответа — обычная
разметка, а не граница карточки.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .model import (DESCRIPTION_LIMIT, ID_RE, INCLUDE, LANGUAGE_RE, MAX_CARDS, MAX_TOPICS,
                    ORDERS, TEXT_LIMIT, TITLE_LIMIT, Card, CardSet, Defaults, Problem, Topic,
                    generated_id, id_to_key, key_to_id, number, question_key, title_norm)
from .sanitize import check_line, unclosed_text
from .scan import scan

_HASH_KEY = re.compile(r"q:[0-9a-f]{16}")

Row = tuple  # (номер строки | None, текст строки, вид строки)


@dataclass
class Raw:
    """Карточка до проверки: как её прочитал разбор источника."""
    index: int
    line: int | None
    q: str
    a: str
    note: str | None
    topic: str | None               # название темы, не id
    card_id: str | None = None      # id, как написан
    key: str | None = None          # готовый ключ, если карточка пришла из набора
    path: str | None = None         # путь JSON карточки `cards[3]`; None — у источника путей нет
    spans: list[tuple[str, list[Row]]] = field(default_factory=list)
    problems: list[Problem] = field(default_factory=list)


def snip(s: str, limit: int = 40) -> str:
    s = " ".join(s.split())
    return s if len(s) <= limit else s[: limit - 1] + "…"


def field_path(base: str | None, name: str) -> str | None:
    return f"{base}.{name}" if base else None


def text_rows(text: str, line: int | None, index: int, problems: list[Problem],
              path: str | None = None) -> list[Row]:
    """Текст поля → строки для проверок; незакрытые блоки — в `problems`."""
    lines = text.split("\n")
    kinds, unclosed = scan(lines)
    for _, kind in unclosed:
        code, msg = unclosed_text(kind)
        problems.append(Problem(line, code, msg, index, path))
    return [(line, t, k) for t, k in zip(lines, kinds)]


def raw_from_text(index: int, line: int | None, q: str, a: str, note: str | None,
                  topic: str | None, *, key: str | None = None,
                  card_id: str | None = None, path: str | None = None) -> Raw:
    r = Raw(index=index, line=line, q=q.strip("\n"), a=a.strip("\n"),
            note=(note.strip("\n") or None) if note else None, topic=topic,
            card_id=card_id, key=key, path=path)
    r.spans = [("q", text_rows(r.q, line, index, r.problems, field_path(path, "q"))),
               ("a", text_rows(r.a, line, index, r.problems, field_path(path, "a")))]
    if r.note:
        r.spans.append(("note", text_rows(r.note, line, index, r.problems,
                                          field_path(path, "note"))))
    return r


def _card_checks(r: Raw) -> list[Problem]:
    ps: list[Problem] = []

    def add(name: str, code: str, text: str) -> None:
        ps.append(Problem(r.line, code, text, r.index, field_path(r.path, name)))

    if r.card_id is not None and not ID_RE.fullmatch(r.card_id):
        add("id", "bad_id", f"id `{snip(r.card_id)}` не подходит: только латинские буквы, "
                            "цифры, точка, дефис и подчёркивание, от 1 до 64 знаков")
    if r.key is not None and r.card_id is None and not _HASH_KEY.fullmatch(r.key):
        add("id", "bad_id", f"ключ `{snip(r.key)}` у карточки без id должен быть вида "
                            "`q:` и 16 шестнадцатеричных знаков")
    if not r.q.strip():
        add("q", "empty_question", "у карточки нет вопроса")
    if not r.a.strip():
        add("a", "empty_answer", "у карточки нет ответа")
    for name, word, value in (("q", "вопрос", r.q), ("a", "ответ", r.a),
                              ("note", "разбор", r.note or "")):
        if len(value) > TEXT_LIMIT:
            add(name, "too_long", f"{word} длиннее {number(TEXT_LIMIT)} символов "
                                  f"({number(len(value))}) — разделите карточку")

    for part, rows in r.spans:
        for _, text, kind in rows:
            for code, msg in check_line(text, kind):
                add(part, code, msg)
    return ps


def _where(r: Raw) -> str:
    if r.path:
        return f"`{r.path}`"
    return f"на строке {r.line}" if r.line else f"№{r.index + 1}"


def accept(raws: list[Raw], problems: list[Problem]) -> list[tuple[Raw, str]]:
    """Проверить карточки; годные — с ключами, все проблемы — в `problems`."""
    seen: dict[str, Raw] = {}
    out: list[tuple[Raw, str]] = []
    for r in raws:
        ps = list(r.problems) + _card_checks(r)
        key = r.key
        if key is None:
            if r.card_id is not None:
                key = id_to_key(r.card_id) if ID_RE.fullmatch(r.card_id) else None
            elif r.q.strip():
                key = question_key(r.q)
        if key is not None:
            first = seen.get(key)
            if first is None:
                seen[key] = r
            elif r.card_id is not None:
                ps.append(Problem(r.line, "duplicate_id",
                                  f"id `{r.card_id}` уже есть у карточки {_where(first)} — id в "
                                  "наборе уникальны", r.index, field_path(r.path, "id")))
            else:
                ps.append(Problem(r.line, "duplicate_question",
                                  f"такой же вопрос уже есть у карточки {_where(first)} — "
                                  "переформулируйте его или дайте обеим карточкам разные `id`",
                                  r.index, field_path(r.path, "q")))
        problems.extend(ps)
        if not ps and key is not None:
            out.append((r, key))
    return out


def check_meta(title: str, description: str, language: str,
               lines: dict[str, int] | None = None,
               paths: dict[str, str] | None = None) -> list[Problem]:
    lines, paths = lines or {}, paths or {}
    ps: list[Problem] = []

    def add(name: str, code: str, text: str) -> None:
        ps.append(Problem(lines.get(name), code, text, path=paths.get(name)))

    if not title.strip():
        add("title", "bad_title", "у набора нет названия")
    elif "\n" in title or len(title) > TITLE_LIMIT:
        add("title", "bad_title", f"название набора — одна строка до {TITLE_LIMIT} символов")
    if len(description) > DESCRIPTION_LIMIT:
        add("description", "bad_description",
            f"описание длиннее {number(DESCRIPTION_LIMIT)} символов ({number(len(description))})")
    if not LANGUAGE_RE.fullmatch(language):
        add("language", "bad_language",
            f"язык `{snip(language)}` не похож на код языка вроде `ru` или `en`")
    return ps


def check_topics(topics: list[Topic], lines: dict[str, int] | None = None,
                 paths: dict[str, str] | None = None) -> list[Problem]:
    """Темы набора. `lines`/`paths` — где тема встретилась первой, по id темы."""
    lines, paths = lines or {}, paths or {}
    ps: list[Problem] = []
    ids: set[str] = set()
    titles: set[str] = set()
    if len(topics) > MAX_TOPICS:
        ps.append(Problem(None, "too_many_topics",
                          f"тем {number(len(topics))}, а потолок {MAX_TOPICS} — объедините темы"))
    for t in topics:
        line, path = lines.get(t.id), paths.get(t.id)
        if not ID_RE.fullmatch(t.id) or t.id in ids:
            ps.append(Problem(line, "bad_topic", f"id темы `{snip(t.id)}` пуст, занят или "
                                                 "содержит недопустимые знаки", path=path))
        ids.add(t.id)
        if not t.title.strip() or "\n" in t.title or len(t.title) > TITLE_LIMIT:
            ps.append(Problem(line, "bad_topic",
                              f"название темы — одна непустая строка до {TITLE_LIMIT} символов",
                              path=path))
        elif title_norm(t.title) in titles:
            ps.append(Problem(line, "bad_topic", f"тема «{snip(t.title)}» повторяется",
                              path=path))
        titles.add(title_norm(t.title))
        for code, msg in check_line(t.title, "text"):
            ps.append(Problem(line, code, f"в названии темы: {msg}", path=path))
    return ps


def check_defaults(d: Defaults, topic_ids: set[str]) -> list[Problem]:
    """Рекомендуемые настройки. `None` в `topics` — карточки без темы."""
    ps: list[Problem] = []

    def add(name: str, code: str, text: str) -> None:
        ps.append(Problem(None, code, text, path=f"defaults.{name}"))

    if isinstance(d.session_size, bool) or not isinstance(d.session_size, int) \
            or not 0 <= d.session_size <= MAX_CARDS:
        add("session_size", "bad_setting",
            f"`session_size` — целое число карточек от 0 до {number(MAX_CARDS)} (0 — все)")
    if d.order not in ORDERS:
        add("order", "bad_setting",
            f"порядок `{snip(str(d.order))}` неизвестен — допустимы: {', '.join(ORDERS)}")
    if d.include not in INCLUDE:
        add("include", "bad_setting",
            f"`include` `{snip(str(d.include))}` неизвестен — допустимы: {', '.join(INCLUDE)}")
    if not isinstance(d.repeat_wrong, bool):
        add("repeat_wrong", "bad_setting", "`repeat_wrong` — true или false")
    for tid in d.topics or []:
        if tid is not None and tid not in topic_ids:
            add("topics", "unknown_topic", f"темы `{snip(str(tid))}` из `topics` нет в наборе")
    return ps


def validate(s: CardSet) -> list[Problem]:
    """Готовый набор → проблемы. Строк у набора нет: `line` — None, `card` — номер карточки
    в `s.cards`, `path` — путь поля в файле, который из набора пишет `write_json`."""
    problems: list[Problem] = []
    if len(s.cards) > MAX_CARDS:
        problems.append(Problem(None, "too_many_cards",
                                f"карточек {number(len(s.cards))}, а потолок "
                                f"{number(MAX_CARDS)} — разделите набор", path="cards"))
    raws = [raw_from_text(i, None, c.q, c.a, c.note, c.topic, key=c.key,
                          card_id=key_to_id(c.key) if c.explicit_id else None,
                          path=f"cards[{i}]")
            for i, c in enumerate(s.cards)]
    accept(raws, problems)
    topic_ids = {t.id for t in s.topics}
    for i, c in enumerate(s.cards):
        if c.topic is not None and c.topic not in topic_ids:
            problems.append(Problem(None, "unknown_topic",
                                    f"у карточки тема `{snip(c.topic)}`, которой нет в наборе", i,
                                    f"cards[{i}].topic"))
    problems += check_meta(s.title, s.description, s.language,
                           paths={"title": "title", "description": "description",
                                  "language": "language"})
    problems += check_topics(s.topics)
    problems += check_defaults(s.defaults, topic_ids)
    return problems


def build_topics(raws: list[Raw]) -> tuple[list[Topic], dict[str, str]]:
    """Названия тем в порядке появления → темы с уникальными slug и карта «норма → id»."""
    from .model import slug
    topics: list[Topic] = []
    by_norm: dict[str, str] = {}
    used: set[str] = set()
    for r in raws:
        if not r.topic:
            continue
        norm = title_norm(r.topic)
        if norm in by_norm:
            continue
        base = slug(r.topic)
        tid, n = base, 2
        while tid in used:
            tid = f"{base}-{n}"
            n += 1
        used.add(tid)
        by_norm[norm] = tid
        topics.append(Topic(id=tid, title=" ".join(r.topic.split())))
    return topics, by_norm


def assemble(raws: list[Raw], problems: list[Problem]) -> tuple[list[Topic], list[Card],
                                                                  dict[str, str]]:
    """Сырые карточки → годные карточки и темы, у которых есть хоть одна годная карточка.

    id вида `q-<16 hex>` выдан тренажёром при записи файла, поэтому такая карточка — без
    авторского id (`explicit_id=False`), как и до записи.
    """
    topics, by_norm = build_topics(raws)
    cards: list[Card] = []
    for r, key in accept(raws, problems):
        tid = by_norm.get(title_norm(r.topic)) if r.topic else None
        cards.append(Card(key=key, q=r.q, a=r.a, topic=tid, note=r.note or None,
                          explicit_id=r.card_id is not None and not generated_id(r.card_id)))
    used = {c.topic for c in cards}
    return [t for t in topics if t.id in used], cards, by_norm


def sort_problems(problems: list[Problem]) -> list[Problem]:
    return sorted(problems, key=lambda p: p.line if p.line is not None else 0)


__all__ = ["validate"]
