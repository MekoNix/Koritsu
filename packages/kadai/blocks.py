"""
blocks — единственное место в `kadai`, где зовётся `hokoku`, и только чистыми функциями.

Правило разреза 2.0.0a4.3 разрешает `kadai` звать `hokoku` **как чистый
инструмент**: байты и значения, без диска и без проекта. Разрешение узкое, и
держать его узким проще всего одним файлом: всё, что пакет знает о движке
отчётов, лежит здесь, и проверить это можно чтением одного модуля, а не восьми
(`tests/kadai/test_border.py`).

Что отсюда зовётся и почему именно оно:

* `value_from_json` / `value_to_json` — перевод записи блока с диска в значение
  и обратно. Второй разборщик значения завести нельзя: форма значения —
  знание `hokoku`, и разойдясь, две реализации соврали бы молча.
* `validate_work` — то же сито, что стоит перед сборкой документа. Своя
  проверка списка блоков была бы вторым мнением о том, что такое годная работа.
* `assemble`, `work_template` — сборка DOCX и синтетический шаблон с `{{ключ}}`
  для архива. Обе чистые: список блоков на входе, байты на выходе.
* `text_slots`, `draft`, `list_blocks`, `outline` — знание о том, что такое
  «место под текст» и как выглядит скелет. Оно уже записано в движке, и
  повторить его здесь значило бы разойтись с проходом текста в тот день, когда
  движок поменяет пометку черновика.

Чего здесь нет и быть не может: `open_document`, `build_report`, `docx_to_pdf`
с путями, `Project` — всё, что ходит на диск или знает проект. Диск знает
`orchestrator`, и второго знающего в проекте не заводится.
"""
from __future__ import annotations

import hokoku
from hokoku import live as _live

from .errors import KadaiError

# Виды блоков, значение которых производит инструмент, а не текстовый проход.
# Разрез тот же, что в `rework.TOOL_TYPES`, и берётся он из движка: вид блока и
# тип значения у `hokoku` — одно утверждение.
TOOL_KINDS = ("code", "diagram", "image", "table", "formula")
TEXT_KINDS = _live.TEXT_KINDS

# Чем бывает заполнен раздел: типы значений движка, кроме служебных. `heading`
# ставит скелет, а не раздел; `page_break` — не содержимое; `text` покрыт
# `markdown`. Своего списка типов в пакете не заводится: разойдясь с движком, он
# соврал бы молча — раздел, объявленный схемой, стал бы обычным текстом.
SECTION_TYPES = tuple(k for k in _live.KINDS
                      if k not in ("heading", "page_break", "text"))

# Пометка черновика — **строкой** в самом значении, отдельного поля «это ещё не
# написано» нет и не будет; почему именно так, написано у движка
# (`hokoku.live.DRAFT_MARK`), и второго объяснения здесь не заводится. Сценарию
# она нужна затем, что по ней он отличает написанное от места под текст
# (`is_draft`, `_solution`).
DRAFT_MARK = _live.DRAFT_MARK


def work_of(records, *, resolve_artifact=None):
    """Записи блоков проекта → список блоков с типизированными значениями.

    `resolve_artifact` — метод проекта: схема и картинка лежат в значении
    идентификатором, и без него значение не собрать. Битая запись — отказ с
    именем блока, а не пропуск: пропущенный блок сдвинул бы список, и ссылки
    `{ref:}` уехали бы молча.
    """
    out = []
    for record in records or ():
        key = str(record.get("key") or "")
        try:
            value = hokoku.value_from_json(record.get("value") or {},
                                           resolve_artifact=resolve_artifact)
        except hokoku.HokokuError as exc:
            raise KadaiError(f"блок {key!r} не читается: {exc}") from None
        out.append(_live.block(key, value, label=record.get("label") or ""))
    return hokoku.Work(tuple(out))


def records_of(work, *, source: str = "agent", before=()) -> list:
    """Список блоков → записи для `Project.set_blocks`, с сохранением пометки источника.

    Пометка прежних блоков переносится по ключу. Без этого правка одного блока
    объявила бы моделью весь список, и следующий проход текста затёр бы
    написанное человеком — та самая беда, ради которой `source` и заведён.
    """
    прежние = {r.get("key"): r.get("source") for r in (before or ())}
    return [{"key": b.key, "kind": b.kind, "label": b.label,
             "value": hokoku.value_to_json(b.value),
             "source": прежние.get(b.key) or source}
            for b in work.blocks]


def validate(work) -> list:
    """Замечания к списку блоков в общей форме проекта. Пусто — соберётся."""
    return [problem_dict(p) for p in _live.validate_work(work)]


def assemble(work) -> bytes:
    """Список блоков → байты DOCX. Второго рисовальщика в проекте нет.

    Беда движка переводится в свою: сборка спотыкается о вещи, которых в
    значениях не видно (`drawio` не нарисовал схему, картинка не читается), и
    прилететь она должна стадии как беда стадии — иначе прогон падает чужим
    исключением, а работа остаётся в состоянии «идёт» навсегда.
    """
    try:
        return _live.assemble(work)
    except hokoku.HokokuError as exc:
        raise KadaiError(f"документ не собрался: {exc}") from None


def template_bytes(work) -> bytes:
    """Синтетический шаблон работы: пустой документ и по абзацу `{{ключ}}` на блок.

    В архив он кладётся затем, чтобы работу можно было пересобрать чужими
    руками: без шаблона значения блоков — это данные без формы.
    """
    return _live.work_template(work)


def to_pdf(data: bytes) -> bytes:
    """DOCX байтами → PDF байтами. Запасной путь, когда двери `to_pdf` не дали.

    Внутри `hokoku` зовёт LibreOffice подпроцессом, и его может не быть — тогда
    беда прилетает исключением, а PDF в архив просто не кладётся: он туда
    попадает, только если просили и LibreOffice есть. Врать о наличии PDF
    нельзя, а отказываться собирать архив из-за него — тем более.
    """
    return hokoku.docx_bytes_to_pdf(data)


def slots(work) -> list:
    """Места под связный текст: пустые и черновые текстовые блоки."""
    return _live.text_slots(work)


def outline(work) -> list:
    """Заголовки работы по порядку — скелет, каким его видит человек."""
    return _live.outline(work)


def listing(work) -> list:
    """Состав работы для человека и снимка: ключ, вид, метка, начало текста."""
    return _live.list_blocks(work)


def draft_json(hint: str) -> dict:
    """Место под текст с подсказкой — записью для `set_blocks`.

    Пустым значением место под текст не выразить: пустое значение движок
    считает ошибкой сборки. Поэтому черновик с пометкой, и пометка не
    украшение — её читает проход текста (`text_slots` → `hint`).
    """
    return hokoku.value_to_json(_live.draft(str(hint or "")))


def is_text(record) -> bool:
    """Текстовый ли это блок. Вид блока и тип значения у `hokoku` — одно и то же."""
    return str(record.get("kind") or "") in TEXT_KINDS


def is_draft(record) -> bool:
    """Не написан ли блок ещё: пусто или пометка черновика."""
    text = str((record.get("value") or {}).get("text") or "").strip()
    return not text or text.lower().startswith(DRAFT_MARK)


def text_of(record) -> str:
    """Написанный текст блока из записи на диске, без разбора значения целиком."""
    return str((record.get("value") or {}).get("text") or "")


def problem_dict(p) -> dict:
    """Замечание любого из пакетов → общая форма `{module, level, code, key, message}`.

    Четвёртого канала предупреждений не заводится, но приходят они и
    объектами (`kyotsu.Notice`), и словарями — от того, кто их отдал.
    Разбирать это в трёх местах значило бы разойтись в двух из них.
    """
    if isinstance(p, dict):
        out = dict(p)
    elif hasattr(p, "to_dict"):
        out = p.to_dict()
    else:
        out = {"module": getattr(p, "module", "?"), "level": getattr(p, "level", "error"),
               "code": getattr(p, "code", "?"), "key": getattr(p, "key", None),
               "message": str(getattr(p, "message", p))}
    out.setdefault("module", "?")
    out.setdefault("level", "error")
    out.setdefault("code", "?")
    out.setdefault("key", None)
    out.setdefault("message", "")
    return out


def errors_of(problems) -> list:
    """Только то, из-за чего нельзя идти дальше. `warning` и `info` не останавливают."""
    return [p for p in (problem_dict(x) for x in problems or ()) if p["level"] == "error"]


__all__ = ["TOOL_KINDS", "TEXT_KINDS", "SECTION_TYPES", "DRAFT_MARK", "work_of", "records_of", "validate", "to_pdf",
           "assemble", "template_bytes", "slots", "outline", "listing", "draft_json",
           "is_text", "is_draft", "text_of", "problem_dict", "errors_of"]
