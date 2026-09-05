"""
tags — синтаксис тегов и их поиск в документе.

  {{ключ}}               {{ключ:Подсказка для пользователя}}
Ключ: буквы (в т.ч. кириллица), цифры, `_`, `.`, `-`; без пробелов.
Зарезервировано на будущее (1.5): `{{ключ|умолчание}}`, `{{#if …}}`, `{{#each …}}` —
парсер их распознаёт как «служебные» и не считает обычными тегами.

Кроме своих тегов в бланке встречается разметка docxtpl/Jinja — её пишут те, кто
делал бланк до нас:

  {# … #}    комментарий: пояснение к соседнему тегу, написанное для человека.
             Из документа он вырезается (иначе печатается в готовом отчёте как
             обычный текст), а сам текст достаётся модели подсказкой к ближайшему
             следующему тегу: ровно про него его и писали.
  {% … %}    конструкция (`{% for %}`, `{%tr for %}`, `{% endfor %}`).
             Движок её не понимает: `{%tr for k in kpis %}` — это таблица, строки
             которой берутся из списка, а тега там нет вовсе. Такая конструкция
             остаётся в документе текстом и показывается человеком-читаемым
             предупреждением манифеста, но сборку не ломает.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from .model import Tag


def norm_key(key: str) -> str:
    """Ключ тега в NFC: Word и macOS могут писать «й»/«ё» разложенными (NFD)."""
    return unicodedata.normalize("NFC", key.strip())

TAG_RE = re.compile(r"\{\{\s*(?P<key>[^\s{}:|#/]+)\s*(?::(?P<label>[^{}]*))?\}\}")
DIRECTIVE_RE = re.compile(r"\{\{\s*[#/|][^{}]*\}\}")

# Комментарий и конструкция Jinja. Нежадно и через несколько строк: комментарий
# в бланке бывает на абзац, а разрыв строки внутри абзаца Word держит в том же
# тексте.
COMMENT_RE = re.compile(r"\{#(?P<text>.*?)#\}", re.S)
CONSTRUCT_RE = re.compile(r"\{%(?P<text>.*?)%\}", re.S)

# Маркеры для быстрого отбора абзацев: то же множество, что ищут регулярки выше.
EXTRA_MARKERS = ("{{", "{#", "{%")


@dataclass
class Extras:
    """Разметка бланка, которая тегом не является.

    `comments` — пары «текст комментария → ключ ближайшего следующего тега».
    Ключ пустой, если после комментария тегов больше нет: подсказку девать
    некуда, и приписать её предыдущему тегу значило бы соврать про то, к чему
    она относится.

    `constructs` — тексты конструкций `{% … %}` в порядке появления, без
    повторов: список читает человек, и десять одинаковых `{% endfor %}` в нём
    ничего не добавляют.
    """

    comments: list = field(default_factory=list)
    constructs: list = field(default_factory=list)


def parse_tag(text: str) -> tuple[str, str] | None:
    m = TAG_RE.fullmatch(text.strip())
    if not m:
        return None
    return m.group("key"), (m.group("label") or m.group("key")).strip()


def find_tags(text: str) -> list[re.Match]:
    return list(TAG_RE.finditer(text))


def find_comments(text: str) -> list[re.Match]:
    return list(COMMENT_RE.finditer(text))


def extract_tags(template) -> list[Tag]:
    """Все теги документа в порядке появления, без повторов (первое место — в `where`)."""
    from .walker import iter_paragraphs, marked_paragraphs, open_document
    doc = open_document(template)
    seen: dict[str, Tag] = {}
    hot = marked_paragraphs(doc, ("{{",))
    for loc in iter_paragraphs(doc):
        if loc.paragraph._p not in hot:
            continue
        text = loc.text()
        if "{{" not in text:
            continue
        for m in TAG_RE.finditer(text):
            key = norm_key(m.group("key"))
            label = (m.group("label") or "").strip()
            tag = seen.get(key)
            if tag is None:
                tag = seen[key] = Tag(key=key, label=label or key, where=loc.where)
            elif label and tag.label == key:
                tag.label = label                     # подсказка может стоять не в первом месте
            tag.count += 1
            if loc.where not in tag.places:
                tag.places.append(loc.where)
    return list(seen.values())


def extract_extras(template) -> Extras:
    """Комментарии `{# … #}` и конструкции `{% … %}` документа в порядке появления.

    Одним проходом с тегами, а не двумя: «ближайший следующий тег» — это вопрос
    про порядок, и отвечать на него можно только там, где комментарии и теги
    встречаются в одном потоке.

    Комментарий, разорванный между абзацами, не собирается: абзац — граница
    разбора у всего модуля (теги ищутся так же), а комментарий, начатый в одном
    абзаце и закрытый в другом, в бланках не встречается.
    """
    from .walker import iter_paragraphs, marked_paragraphs, open_document
    doc = open_document(template)
    hot = marked_paragraphs(doc, EXTRA_MARKERS)
    ждут: list = []                      # комментарии без своего тега
    out = Extras()
    for loc in iter_paragraphs(doc):
        if loc.paragraph._p not in hot:
            continue
        text = loc.text()
        события = [(m.start(), "tag", norm_key(m.group("key"))) for m in TAG_RE.finditer(text)]
        события += [(m.start(), "comment", m.group("text").strip())
                    for m in COMMENT_RE.finditer(text)]
        события += [(m.start(), "construct", m.group(0).strip())
                    for m in CONSTRUCT_RE.finditer(text)]
        for _, вид, значение in sorted(события, key=lambda e: e[0]):
            if вид == "tag":
                for текст in ждут:
                    out.comments.append((текст, значение))
                ждут = []
            elif вид == "comment":
                if значение:
                    ждут.append(значение)
            elif значение not in out.constructs:
                out.constructs.append(значение)
    for текст in ждут:
        out.comments.append((текст, ""))
    return out
