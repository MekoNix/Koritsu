"""
validate — значения против шаблона и манифеста, до сборки документа.

Ограничения манифеста до сих пор только печатались модели в промпт: попросить «строк
не больше 20» мы умели, а проверить — нет. `limits` и `depends_on` разбирались, ехали
в задание и не читались никем, поэтому таблица на 500 строк при `max_rows: 20` уходила
в собранный отчёт без единого слова, и студент нёс это на кафедру. Единственные потолки
в коде — `report.HARD_LIMITS` (2000 строк) — защита от абсурда, а не от ошибки.

Проверка возвращает список, а не бросает на первой беде: модель должна получить все
замечания за один повтор, а человек — увидеть их разом. Запись — `model.Problem`,
то есть общая на проект форма замечания (`kyotsu.Notice`: module, level, code,
message) плюс тег и машиночитаемые `expected`/`got`: проблему показывают в
интерфейсе и отдают модели, и разбирать прозу ни тому, ни другому нечем. Та же
запись у `check_manifest`, `check_template` и предупреждений `build_report`.

Уровни:
  error   — собирать нельзя: render либо упадёт (пустое значение), либо соберёт не то;
  warning — соберётся, но с изъяном, видимым в документе («?» вместо номера ссылки);
  info    — законное состояние, о котором стоит знать (необязательный тег пуст).

Чужого здесь не проверяется: форма значения — дело `wire`, потолки службы — `build_report`,
манифест против шаблона — `check_manifest`. Пустоту и знаки считают те же функции, что
у render и build_report: две проверки «пустого значения» разошлись бы через полгода.
"""
from __future__ import annotations

import difflib

from . import markdown as md
from .manifest import Manifest, default_spec
from .model import (Blocks, Code, Diagram, Formula, Image, Markdown, PageBreak, Problem,
                    Table, Text, Toc)
from .render import REF_TEXT_RE, _empty_value
from .report import _chars
from .tags import extract_tags, norm_key
from .wire import VALUE_TYPES

# Класс значения → слово, которым его называет манифест. Второй список типов — риск,
# поэтому расхождение с wire роняет импорт (_check_types ниже), а не всплывает на готовом
# отчёте: тип, которого validate не знает, иначе выглядел бы как «тип не тот».
_TYPE_OF = {Text: "text", Markdown: "markdown", Code: "code", Image: "image",
            Diagram: "diagram", Table: "table", Formula: "formula", Toc: "toc",
            Blocks: "blocks", PageBreak: "page_break"}


def _check_types() -> None:
    missing = sorted(set(VALUE_TYPES) - set(_TYPE_OF.values()))
    if missing:
        raise RuntimeError(f"validate: тип значения {missing[0]!r} есть в wire, "
                           "а в _TYPE_OF его нет — допишите класс значения")


_check_types()


def validate(template, values: dict, manifest: Manifest) -> list[Problem]:
    """Значения против тегов шаблона и записей манифеста → список проблем.

    Пустой список означает ровно одно: `build_report` соберёт из этих значений тот отчёт,
    который объявлен манифестом. Без проверки любая из перечисленных бед (не тот тип,
    500 строк при `max_rows: 20`, ссылка в никуда, вывод по незаполненным замерам)
    доезжает до готового DOCX молча — и обнаруживается уже на кафедре.

    `values` — типизированные значения (как у `render`: то, что отдал `values_from_json`);
    `manifest` — записи по тегам; тег без записи проверяется по умолчаниям `default_spec`.
    """
    tags = {t.key: t for t in extract_tags(template)}
    values = {norm_key(str(k)): v for k, v in values.items()}   # ключи в NFC с обеих сторон
    filled = {k for k, v in values.items() if v is not None and not _empty_value(v)}
    out: list[Problem] = []
    for key in values:
        if key not in tags:
            # опечатка в ключе (в том числе у модели) молча теряла целое значение
            out.append(_p("warning", "unknown_key", key,
                          f"значение {key!r} не нашло тега в шаблоне{_hint(key, tags)}"))
    for key, tag in tags.items():
        spec = manifest.tags.get(key)
        out += _tag(key, default_spec(tag) if spec is None else spec, values, filled, tags)
    out += _refs(values, tags)
    return out


def _tag(key: str, spec, values: dict, filled: set, tags: dict) -> list[Problem]:
    out: list[Problem] = []
    for dep in spec.depends_on:
        if dep not in tags:
            out.append(_p("error", "depends_on_missing", key,
                          f"тег {key!r} опирается на {dep!r}, а такого тега в шаблоне нет"
                          f"{_hint(dep, tags)}", got=dep))
        elif dep not in filled and (spec.required or key in filled):
            # вывод по замерам, которых нет, модель сочинит — и это худший из исходов
            out.append(_p("error", "depends_on_unfilled", key,
                          f"тег {key!r} опирается на {dep!r}, а тот не заполнен", got=dep))
    value = values.get(key)
    if value is None:
        if spec.required:
            out.append(_p("error", "missing_required", key,
                          f"тег {key!r} обязателен, а значения нет", expected=spec.type))
        else:
            out.append(_p("info", "tag_unfilled", key,
                          f"тег {key!r} необязателен и остался пустым: render уберёт его "
                          "из документа"))
        return out
    if _empty_value(value):
        # решение владельца 2026-08-29: «модель ничего не вернула» выглядело ровно как
        # «тег заполнен»; render считает это ошибкой, и знать о ней надо до сборки
        out.append(_p("error", "empty_value", key,
                      f"значение тега {key!r} пустое: подставлять нечего"))
        return out
    got = _type_name(value)
    if got != spec.type:
        out.append(_p("error", "type_mismatch", key,
                      f"тег {key!r}: манифест объявил {spec.type}, а значение — {got}",
                      expected=spec.type, got=got))
    return out + _limits(key, spec.limits, value)


def _type_name(v) -> str:
    """Голые скаляры render вставляет как простой текст — значит и тип у них `text`
    (те же правила, что в `wire.value_to_json`)."""
    if isinstance(v, (str, bool, int, float)):
        return "text"
    return _TYPE_OF.get(type(v), type(v).__name__)


# ── ограничения манифеста ─────────────────────────────────────────────────────

def _limits(key: str, limits: dict, v) -> list[dict]:
    out: list[dict] = []
    if "max_chars" in limits:
        chars = _chars(v)                      # знаки считает build_report, счёт один на всех
        if chars > limits["max_chars"]:
            out.append(_p("error", "limit_max_chars", key,
                          f"тег {key!r}: {chars} знаков при потолке {limits['max_chars']}",
                          expected=limits["max_chars"], got=chars))
    # знаки считаем по значению, как его написали, а строки и заголовки — по тому, что
    # из него выйдет в документе: render успевает поменять тип значения до сборки
    v = _rendered(v)
    if "max_rows" in limits or "max_cols" in limits:
        tables = _tables(v)
        rows = max((r for r, _ in tables), default=0)
        cols = max((c for _, c in tables), default=0)
        if "max_rows" in limits and rows > limits["max_rows"]:
            out.append(_p("error", "limit_max_rows", key,
                          f"тег {key!r}: строк {rows} при потолке {limits['max_rows']}",
                          expected=limits["max_rows"], got=rows))
        if "max_cols" in limits and cols > limits["max_cols"]:
            out.append(_p("error", "limit_max_cols", key,
                          f"тег {key!r}: колонок {cols} при потолке {limits['max_cols']}",
                          expected=limits["max_cols"], got=cols))
    if limits.get("headings") is False:
        heads = _headings(v)
        if heads:
            out.append(_p("error", "limit_headings", key,
                          f"тег {key!r}: заголовков не ставить, а их {len(heads)} "
                          f"(первый — {heads[0]!r})", expected=0, got=len(heads)))
    return out


def _tables(v) -> list[tuple[int, int]]:
    """Таблицы значения как (строк, колонок). Таблица, набранная разметкой внутри
    markdown, — такая же таблица: иначе `max_rows` обходится сменой типа значения,
    а лимит снова становится украшением. Простой текст со ссылкой — тоже markdown,
    но это уже забота `_rendered`, которую делает вызывающий."""
    if isinstance(v, Table):
        return [(len(v.rows), max((len(r) for r in v.rows), default=0))]
    if isinstance(v, Markdown):
        return [(len(b.rows), max((len(r) for r in b.rows), default=0))
                for b in md.parse(v.text) if isinstance(b, md.TableBlock)]
    if isinstance(v, Blocks):
        return [t for item in v.items for t in _tables(item)]
    return []


def _rendered(v):
    """Значение таким, каким его увидит документ, а не таким, каким его назвал манифест.

    `{ref:` внутри простого текста render разбирает как markdown целиком
    (`render._process_paragraph`: `Text`/`str` со ссылкой становятся `Markdown`) — вместе
    с заголовками, таблицами и листингами. Пока лимиты мерились по типу значения, любой
    из них снимался одной ссылкой в тексте, а ставить ссылки модель обязана: заголовок
    ехал в отчёт при `headings: false` и ломал нумерацию оглавления, ради которой лимит
    и заводился. Условие и склейка строк повторены за render дословно; разойдутся —
    обход вернётся, поэтому править это надо парой.

    Внутрь `Blocks` подмена не заходит: render меняет только само значение тега,
    а элементы последовательности идут в `_emit_value` как есть — там `Text`/`str`
    остаётся простым текстом, в котором разбирается одна лишь ссылка
    (`markdown.split_refs`), и заголовков из него не выйдет.
    """
    if isinstance(v, Text) and "{ref:" in v.text:
        return Markdown(v.text.replace("\n", "  \n"))
    if isinstance(v, str) and "{ref:" in v:
        return Markdown(v)
    return v


def _headings(v) -> list[str]:
    """Заголовки значения; звать после `_rendered` — простой текст со ссылкой к этому
    месту уже markdown и заголовки даёт настоящие. Листинга здесь нет по делу:
    `Code` уходит в `_emit_code` без разбора разметки, и `## ` там — знаки решётки."""
    if isinstance(v, Markdown):
        return ["".join(s.text for s in b.spans) for b in md.parse(v.text)
                if isinstance(b, md.Para) and b.kind.startswith("h")]
    if isinstance(v, Blocks):
        return [h for item in v.items for h in _headings(item)]
    return []


# ── ссылки {ref:имя} ──────────────────────────────────────────────────────────

def _refs(values: dict, tags: dict) -> list[Problem]:
    """`{ref:имя}` мимо цели render превращает в «?» прямо в тексте отчёта — беда видна
    только глазами и только на готовом документе.

    Имя ссылки — либо ключ тега (так подписи нумеруются по умолчанию), либо `ref=`,
    назначенное самим значением; больше взяться номеру неоткуда.
    """
    known = set(tags)
    for v in values.values():
        known |= _own_refs(v)
    out: list[Problem] = []
    for key, v in values.items():
        for name in dict.fromkeys(REF_TEXT_RE.findall(_ref_text(v))):
            if name not in known:
                out.append(_p("warning", "unresolved_ref", key,
                              f"ссылка {{ref:{name}}} в значении тега {key!r} никуда "
                              f"не ведёт: в документе останется «?»{_hint(name, known)}",
                              got=name))
    return out


def _own_refs(v) -> set:
    name = getattr(v, "ref", None)
    out = {name} if isinstance(name, str) and name else set()
    if isinstance(v, Blocks):
        for item in v.items:
            out |= _own_refs(item)
    return out


def _ref_text(v) -> str:
    """Текст значения, в котором render превращает `{ref:имя}` в поле REF — и значит,
    где мимо цели останется «?».

    Подпись — такое же место: `docx_ops._plain_with_refs` разбирает в ней ссылки, и «?»
    в «Рисунок 1 — см. ?» стоит на самом виду. Пока подписи здесь не было, заявка модуля
    выполнялась наполовину: та же ссылка в тексте давала предупреждение, а в подписи —
    ни одного.

    Заголовок оглавления (`Toc.title`) — тоже: он отдельный абзац перед полем TOC,
    и поле REF в нём законно (`docx_ops.add_toc`).

    Листинга нет намеренно: `{ref:x}` в коде программы — текст программы, render его
    не трогает.
    """
    if isinstance(v, str):
        return v
    if isinstance(v, (Text, Markdown)):
        return v.text
    if isinstance(v, Table):
        return "\n".join([_caption(v)] + [str(c) for row in v.rows for c in row])
    if isinstance(v, (Image, Diagram)):
        return _caption(v)
    if isinstance(v, Toc):
        return v.title or ""
    if isinstance(v, Blocks):
        return "\n".join(_ref_text(item) for item in v.items)
    return ""


def _caption(v) -> str:
    """Текст подписи. `caption` бывает не строкой: None — номер без текста, False — вовсе
    без подписи; разбирать в них нечего."""
    return v.caption if isinstance(v.caption, str) else ""


# ── запись о проблеме ─────────────────────────────────────────────────────────

def _p(level: str, code: str, key: str, message: str, *, expected=None, got=None) -> Problem:
    return Problem(module="hokoku", level=level, code=code, key=key, message=message,
                   expected=expected, got=got)


def _hint(name: str, known) -> str:
    near = difflib.get_close_matches(str(name), sorted(known), n=1, cutoff=0.6)
    return f' (похоже на "{near[0]}")' if near else ""
