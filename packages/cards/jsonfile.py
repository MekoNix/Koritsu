"""jsonfile.py — файл набора `.json`: чтение и каноническая запись.

    {
      "format": "koritsu.cards",
      "version": 1,
      "title": "Матанализ: определённый интеграл",
      "defaults": {"session_size": 20, "order": "topic_random"},
      "cards": [
        {"id": "c-0001", "topic": "Первообразная", "q": "Что такое первообразная?",
         "a": "Функция $F$, для которой $F' = f$.", "note": "Частая ошибка — забыть константу."},
        {"topic": "Интеграл Римана", "q": "Вычислить $\\\\int_0^1 x^2\\\\,dx$.", "a": "$\\\\frac13$"}
      ]
    }

Правила разбора:

- **Битый JSON** — одна проблема с номером строки и столбца из `json.JSONDecodeError` и
  подсказкой по-русски; набора нет. Файл, похожий на прежний Markdown, узнаётся отдельно.
- **Проблемы указывают путь JSON** (`cards[12].a`, `defaults.order`) и номер карточки `card`
  с нуля. Проблема с `card` отклоняет карточку, без него — касается файла.
- **Лишние поля** файла и карточки молча пропускаются: файл, в который новая версия формата
  добавила необязательные поля, читается и старым разборщиком. Другое значение `format` —
  проблема файла, `version` больше 1 — отказ: смысл полей мог поменяться.
- **Неизвестные значения настроек** — проблема файла, берётся значение по умолчанию.
- **Тема — название строкой.** Порядок тем — по первому появлению в `cards`, id темы —
  slug названия.
- **Числа в текстовых полях** (`"a": 42`) читаются строкой; списки, объекты и `true`/`false`
  — проблема поля.
- **Неудвоенный обратный слеш LaTeX.** В JSON `\\t`, `\\n`, `\\b`, `\\f`, `\\r` — законные
  escape-последовательности, и `"\\theta"` молча становится табуляцией и словом `heta`. Такие
  места узнаются по имени команды после управляющего символа и отклоняют карточку с
  подсказкой удвоить слеш.
- **Строки** приводятся к NFC, концы строк — к `\\n`.
"""
from __future__ import annotations

import json
import re
from pathlib import PurePath

from .check import Raw, assemble, check_meta, check_topics, raw_from_text, snip
from .model import (DEFAULT_LANGUAGE, DEFAULT_TITLE, DESCRIPTION_LIMIT, FILE_BYTES, FORMAT,
                    FORMAT_VERSION, INCLUDE, MAX_CARDS, MAX_TOPICS, ORDERS, TITLE_LIMIT, Card,
                    CardSet, Defaults, Problem, key_to_id, normalize_input, number,
                    question_key, title_norm)

_MARKDOWN_START = re.compile(r"^(?:---[ \t]*(?:\n|$)|#{1,2}[ \t]+\S)")

# Сообщения `json.JSONDecodeError.msg` → что поправить.
_JSON_HINTS = {
    "Expecting property name enclosed in double quotes":
        "ожидалось имя поля в двойных кавычках — нет ли лишней запятой перед `}` или имени "
        "в одинарных кавычках",
    "Expecting ',' delimiter": "не хватает запятой между элементами",
    "Expecting ':' delimiter": "после имени поля нужно двоеточие",
    "Expecting value": "ожидалось значение — нет ли лишней запятой перед `]` или `}`, "
                       "строки в одинарных кавычках или комментария",
    "Invalid \\escape": "неизвестная escape-последовательность: обратный слеш в строке JSON "
                        "удваивается — `\\\\int`, `\\\\sum`",
    "Invalid \\uXXXX escape": "после `\\u` нужны четыре шестнадцатеричных знака; обратный слеш "
                              "LaTeX удваивается — `\\\\underline`",
    "Invalid control character at": "перевод строки или табуляция внутри строки пишутся как "
                                    "`\\n` и `\\t`",
    "Unterminated string starting at": "строка не закрыта кавычкой `\"`",
    "Extra data": "после закрывающей `}` ещё текст",
}

# Команды LaTeX, первая буква которых — законная escape-последовательность JSON.
_ESCAPED_COMMANDS = {
    "\t": "theta|tau|times|text|textbf|textit|textrm|to|tan|tanh|tilde|top|tfrac|triangle",
    "\n": "nabla|neq|neg|notin|newline|nleq|ngeq|nmid",
    "\r": "rho|right|rangle|rfloor|rceil|rightarrow|Rightarrow|rbrace",
    "\b": "beta|bar|begin|big|bigl|bigr|binom|bmod|boldsymbol|bullet|bot|backslash",
    "\f": "frac|forall|flat",
}
_ESCAPED_RE = re.compile("|".join(
    f"{re.escape(ch)}(?:{'|'.join(re.escape(w[1:]) for w in words.split('|'))})(?![A-Za-z])"
    for ch, words in _ESCAPED_COMMANDS.items()))
_ESCAPE_NAMES = {"\t": "t", "\n": "n", "\r": "r", "\b": "b", "\f": "f"}

_FIELDS = ("id", "topic", "q", "a", "note")
_TEXT_FIELDS = ("q", "a", "note")


def _kind(v: object) -> str:
    if isinstance(v, bool):
        return "`true`/`false`"
    if isinstance(v, list):
        return "массив"
    if isinstance(v, dict):
        return "объект"
    return "число"


def _norm(s: str) -> str:
    return normalize_input(s)


def _too_big(size: int) -> Problem:
    return Problem(None, "file_too_big",
                   f"файл {size / 1024 / 1024:.1f} МБ, а потолок 5 МБ — разделите набор на "
                   "несколько файлов".replace(".", ",", 1))


def _broken(text: str, exc: json.JSONDecodeError) -> Problem:
    if _MARKDOWN_START.match(text.lstrip()):
        return Problem(None, "markdown_format",
                       "файл похож на Markdown, а набор карточек — файл JSON: "
                       "`{\"cards\": [{\"q\": …, \"a\": …}]}` (описание — docs/cards-format.md)")
    hint = next((v for k, v in _JSON_HINTS.items() if exc.msg.startswith(k)), exc.msg)
    return Problem(exc.lineno, "bad_json",
                   f"файл не читается как JSON — строка {exc.lineno}, столбец {exc.colno}: "
                   f"{hint}", column=exc.colno)


def _escaped_latex(value: str) -> str | None:
    m = _ESCAPED_RE.search(value)
    if not m:
        return None
    ch, rest = m.group(0)[0], m.group(0)[1:]
    name = _ESCAPE_NAMES[ch]
    return (f"похоже, обратный слеш LaTeX не удвоен: `\\{name}{rest}` в JSON превратился в "
            f"управляющий символ и `{rest}` — пишите `\\\\{name}{rest}`")


def _text(doc: dict, name: str, problems: list[Problem], path: str) -> str | None:
    """Строковое поле файла: нет или `null` — None, число — строкой, иное — проблема."""
    v = doc.get(name)
    if v is None:
        return None
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        v = str(v)
    if not isinstance(v, str):
        problems.append(Problem(None, "bad_field", f"`{name}` — строка, а не {_kind(v)}",
                                path=path))
        return None
    return _norm(v)


def _card(i: int, item: object, problems: list[Problem], bad: set[str]) -> Raw | None:
    base = f"cards[{i}]"
    if not isinstance(item, dict):
        problems.append(Problem(None, "bad_card",
                                f"карточка — объект `{{\"q\": …, \"a\": …}}`, а не {_kind(item)}",
                                i, base))
        return None
    own: list[Problem] = []
    values: dict[str, str | None] = {}
    for name in _FIELDS:
        v = item.get(name)
        path = f"{base}.{name}"
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            v = str(v)
        if v is not None and not isinstance(v, str):
            own.append(Problem(None, "bad_field", f"`{name}` — строка, а не {_kind(v)}", i, path))
            bad.add(path)
            v = None
        if isinstance(v, str) and name in _TEXT_FIELDS:
            msg = _escaped_latex(v)
            if msg:
                own.append(Problem(None, "latex_escape", msg, i, path))
        values[name] = _norm(v) if isinstance(v, str) else None

    card_id = (values["id"] or "").strip() or None
    topic = " ".join((values["topic"] or "").split()) or None
    r = raw_from_text(i, None, values["q"] or "", values["a"] or "", values["note"], topic,
                      card_id=card_id, path=base)
    r.problems[:0] = own
    return r


def _defaults(raw: object, problems: list[Problem], by_norm: dict[str, str],
              topic_ids: set[str]) -> Defaults:
    base = Defaults()
    if raw is None:
        return base
    if not isinstance(raw, dict):
        problems.append(Problem(None, "bad_setting",
                                f"`defaults` — объект с настройками, а не {_kind(raw)}",
                                path="defaults"))
        return base
    kw: dict[str, object] = {}

    def bad(name: str, text: str) -> None:
        problems.append(Problem(None, "bad_setting", text, path=f"defaults.{name}"))

    def shown(v: object) -> str:
        return snip(json.dumps(v, ensure_ascii=False))

    v = raw.get("session_size")
    if v is not None:
        if isinstance(v, str) and v.strip().lower() in ("all", "все"):
            kw["session_size"] = 0
        elif isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= MAX_CARDS:
            kw["session_size"] = v
        else:
            bad("session_size", f"`session_size` — число карточек от 0 до {number(MAX_CARDS)} "
                                f"или `\"all\"`, а не `{shown(v)}`; взято {base.session_size}")

    for name, allowed in (("order", ORDERS), ("include", INCLUDE)):
        v = raw.get(name)
        if v is None:
            continue
        if isinstance(v, str) and v in allowed:
            kw[name] = v
        else:
            bad(name, f"`{name}`: `{shown(v)}` — такого значения нет; допустимы: "
                      f"{', '.join(allowed)}; взято {getattr(base, name)}")

    v = raw.get("repeat_wrong")
    if v is not None:
        if isinstance(v, bool):
            kw["repeat_wrong"] = v
        else:
            bad("repeat_wrong", f"`repeat_wrong` — true или false, а не `{shown(v)}`")

    v = raw.get("topics")
    if v is not None:
        if not isinstance(v, list):
            bad("topics", "`topics` — массив названий тем или `null` (все темы)")
        else:
            ids: list[str | None] = []
            for j, name in enumerate(v):
                path = f"defaults.topics[{j}]"
                if not isinstance(name, str):
                    problems.append(Problem(None, "bad_setting",
                                            "тема в `topics` — строка с названием", path=path))
                    continue
                name = _norm(name)
                if not name.strip():
                    tid = None
                else:
                    tid = by_norm.get(title_norm(name)) or (name if name in topic_ids else None)
                    if tid is None:
                        problems.append(Problem(None, "unknown_topic",
                                                f"темы «{snip(name)}» из `topics` нет у карточек "
                                                "— пишите название, как в поле `topic`",
                                                path=path))
                        continue
                    if tid not in topic_ids:
                        # Все карточки темы отклонены — о них уже сказано проблемами.
                        continue
                if tid not in ids:
                    ids.append(tid)
            if ids:
                kw["topics"] = ids
    return Defaults(**kw)


def _decode(data: bytes | str) -> tuple[str | None, Problem | None]:
    if isinstance(data, (bytes, bytearray, memoryview)):
        raw = bytes(data)
        if len(raw) > FILE_BYTES:
            return None, _too_big(len(raw))
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            return None, Problem(None, "not_utf8", "файл не в кодировке UTF-8 — сохраните его "
                                                   "как UTF-8")
    else:
        text = str(data)
        size = len(text.encode("utf-8", "surrogatepass"))
        if size > FILE_BYTES:
            return None, _too_big(size)
    return (text[1:] if text.startswith("\ufeff") else text), None


def _order(problems: list[Problem]) -> list[Problem]:
    """Сперва проблемы файла, потом карточек по порядку; внутри — как найдены."""
    return sorted(problems, key=lambda p: (p.card is not None, p.card or 0))


def read_json(data: bytes | str, *, filename: str = "") -> tuple[CardSet | None, list[Problem]]:
    """Файл набора `.json` → набор из годных карточек и все проблемы.

    Набора нет (`None`), если файл больше 5 МБ, не читается как JSON, новее формата, в нём
    больше 10 000 карточек или 500 тем, или ни одна карточка не годится. Иначе в наборе
    годные карточки, а отклонённые видны по проблемам с `card`.
    """
    text, fatal = _decode(data)
    if fatal is not None:
        return None, [fatal]
    if not text.strip():
        return None, [Problem(None, "no_cards", "файл пуст — набор карточек начинается с `{` "
                                                "и содержит массив `cards`", path="cards")]
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as exc:
        return None, [_broken(text, exc)]
    except RecursionError:
        return None, [Problem(None, "bad_json", "в файле слишком глубокая вложенность")]

    if not isinstance(doc, dict):
        extra = (" — оберните массив карточек: `{\"cards\": […]}`" if isinstance(doc, list)
                 else "")
        return None, [Problem(None, "not_object",
                              f"набор карточек — объект JSON `{{…}}` с полем `cards`{extra}")]

    problems: list[Problem] = []
    if "format" in doc and doc["format"] != FORMAT:
        problems.append(Problem(None, "bad_format",
                                f"`format` — `{FORMAT}`, а не "
                                f"`{snip(json.dumps(doc['format'], ensure_ascii=False))}`",
                                path="format"))
    if "version" in doc:
        v = doc["version"]
        whole = isinstance(v, int) and not isinstance(v, bool)
        if whole and v > FORMAT_VERSION:
            return None, problems + [Problem(
                None, "newer_version", f"файл новее тренажёра: версия формата {v}, а читается "
                                       f"{FORMAT_VERSION} — обновите страницу или сохраните набор "
                                       f"в версии {FORMAT_VERSION}", path="version")]
        if not whole or v < 1:
            problems.append(Problem(None, "bad_version",
                                    f"`version` — целое число {FORMAT_VERSION}", path="version"))

    items = doc.get("cards")
    if not isinstance(items, list):
        problems.append(Problem(None, "no_cards",
                                "в наборе нет массива `cards`" if items is None
                                else f"`cards` — массив карточек, а не {_kind(items)}",
                                path="cards"))
        return None, _order(problems)
    if len(items) > MAX_CARDS:
        return None, _order(problems + [Problem(
            None, "too_many_cards", f"в файле {number(len(items))} карточек, а потолок "
                                    f"{number(MAX_CARDS)} — разделите набор на несколько файлов",
                                    path="cards")])

    bad: set[str] = set()
    raws = [r for r in (_card(i, item, problems, bad) for i, item in enumerate(items)) if r]
    if len({title_norm(r.topic) for r in raws if r.topic}) > MAX_TOPICS:
        return None, _order(problems + [Problem(
            None, "too_many_topics", f"тем больше {MAX_TOPICS} — объедините темы")])

    topics, cards, by_norm = assemble(raws, problems)
    # Поле не той формы уже названо проблемой; «нет вопроса» поверх неё — повтор.
    problems = [p for p in problems
                if not (p.code in ("empty_question", "empty_answer") and p.path in bad)]
    topic_ids = {t.id for t in topics}
    defaults = _defaults(doc.get("defaults"), problems, by_norm, topic_ids)

    title = (_text(doc, "title", problems, "title") or "").strip()
    if not title:
        title = (PurePath(filename).stem.strip() if filename else "") or DEFAULT_TITLE
    description = (_text(doc, "description", problems, "description") or "").strip()
    language = (_text(doc, "language", problems, "language") or "").strip() or DEFAULT_LANGUAGE
    paths = {k: k for k in ("title", "description", "language") if doc.get(k) is not None}
    for p in check_meta(title, description, language, paths=paths):
        problems.append(p)
        if p.code == "bad_title":
            title = " ".join(title.split())[:TITLE_LIMIT] or DEFAULT_TITLE
        elif p.code == "bad_description":
            description = description[:DESCRIPTION_LIMIT]
        elif p.code == "bad_language":
            language = DEFAULT_LANGUAGE
    first: dict[str, str] = {}
    for r in raws:
        if r.topic and title_norm(r.topic) in by_norm:
            first.setdefault(by_norm[title_norm(r.topic)], f"{r.path}.topic")
    problems += check_topics(topics, paths=first)

    if not cards:
        problems.append(Problem(None, "no_cards",
                                "в `cards` нет ни одной карточки" if not items
                                else "ни одна карточка не прошла проверку", path="cards"))
        return None, _order(problems)
    return (CardSet(title=title, description=description, language=language, topics=topics,
                    cards=cards, defaults=defaults), _order(problems))


# ── запись ───────────────────────────────────────────────────────────────────

def card_id(c: Card) -> str:
    """id карточки в файле: свой — как есть, у карточки без id — `q-<16 hex>` по ключу."""
    if c.explicit_id or c.key.startswith("q:"):
        return key_to_id(c.key)
    return key_to_id(question_key(c.q))


def write_json(s: CardSet) -> str:
    """Набор → канонический `.json`: `format` и `version`, все настройки, id у каждой
    карточки, темы названиями, карточки в порядке набора. Отступ 2, текст не экранируется."""
    titles = {t.id: t.title for t in s.topics}
    d = s.defaults
    defaults: dict[str, object] = {"session_size": d.session_size, "order": d.order}
    if d.topics is not None:
        defaults["topics"] = ["" if tid is None else titles.get(tid, tid) for tid in d.topics]
    defaults["include"] = d.include
    defaults["repeat_wrong"] = d.repeat_wrong

    doc: dict[str, object] = {"format": FORMAT, "version": FORMAT_VERSION, "title": s.title}
    if s.description:
        doc["description"] = s.description
    doc["language"] = s.language or DEFAULT_LANGUAGE
    doc["defaults"] = defaults
    cards = []
    for c in s.cards:
        item: dict[str, str] = {"id": card_id(c)}
        if c.topic is not None and c.topic in titles:
            item["topic"] = titles[c.topic]
        item["q"] = c.q
        item["a"] = c.a
        if c.note:
            item["note"] = c.note
        cards.append(item)
    doc["cards"] = cards
    return json.dumps(doc, ensure_ascii=False, indent=2) + "\n"


__all__ = ["read_json", "write_json"]
