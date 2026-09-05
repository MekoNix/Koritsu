"""
manifest — манифест шаблона: тип и промпт на каждый тег.

Тип тега объявляет манифест, а не имя ключа (имя-префикс вроде `global_` ломает
`{ref:ключ}` и сохранённые значения при смене типа, а промпт девать некуда). По
умолчанию всё `markdown` — он покрывает текст, заголовки, списки, таблицы и картинки;
манифест объявляет исключения (`image`, `diagram`, `code`, `formula`, `table`,
`toc`).

Он же — то, что отдаётся модели вместо DOCX: `manifest_prompt` собирает из него список
заданий, а форму самого значения даёт `wire.value_schema(тип, for_model=True)`. Отсюда
требование к сериализации: она обязана быть устойчивой (тот же манифест — тот же текст,
знак в знак), иначе кэш префикса промахивается на каждом вызове.

Где живёт: манифест — самостоятельный объект, а не часть задания `build_report`.
В задании от него едет только `template.manifest_version` — чтобы в журнале было видно,
по какому манифесту собран отчёт. Хранение — за службой (диск и SQLite, которых ещё нет);
здесь только чистые функции: заготовка из шаблона, разбор и запись JSON, сверка
с реальными тегами и промпт.

Правила те же, что у wire: неизвестное поле — ошибка с именем поля и подсказкой
«похоже на», ключи в NFC, путей на диске в JSON нет.
"""
from __future__ import annotations

import difflib
import hashlib
import unicodedata
from dataclasses import dataclass, field, fields, replace

from .model import HokokuError, Problem
from .tags import extract_extras, extract_tags, norm_key
from .wire import VALUE_TYPES, WIRE_VERSION, value_schema

# Те же слова, что в значении (wire), кроме `page_break`: разрыв страницы — не задание
# на тег, а способ сложить блоки внутри значения.
MANIFEST_TYPES = tuple(t for t in VALUE_TYPES if t != "page_break")
DEFAULT_TYPE = "markdown"
SOURCE_HINTS = ("agent", "manual", "file")

# Ограничения, понятные проверке значения; неизвестное имя — ошибка, а не молчание:
# `limits: {max_char: 600}` с опечаткой не ограничивал бы ничего.
LIMIT_KEYS = {"max_chars": int, "max_rows": int, "max_cols": int, "headings": bool}

# Тип по метке только *предлагается*: молча ставить его нельзя — цена ошибки в том, что
# модель отдаёт картинку туда, где ждали абзац, и видно это лишь глазами на готовом отчёте.
_TYPE_HINTS = (("схем", "diagram"), ("рисун", "image"), ("листинг", "code"),
               ("формул", "formula"), ("таблиц", "table"), ("оглавл", "toc"))

# В колонтитуле подписи и нумерации нет (render там не нумерует), и тег там обычно
# необязателен: логотип и номер группы вписывает человек, а не модель.
_HEADERS = ("header", "footer")


class ManifestError(HokokuError):
    """Манифест не по схеме: неизвестный тип, неизвестное поле, битая версия."""


@dataclass
class TagSpec:
    """Что человек решил про один тег. `where`, `places`, `count` здесь не хранятся —
    их даёт `extract_tags` при сверке, и хранить их значило бы держать вторую копию
    шаблона, которая разойдётся с ним при первой же правке в Word."""
    type: str = DEFAULT_TYPE
    label: str = ""                 # из {{ключ:подсказка}}, дальше правится человеком
    required: bool = True
    inline: bool = False            # тег внутри строки — значение без заголовков и списков
    numbered: bool = True           # false ⇒ служба ставит в значении caption: false
    prompt: str = ""                # задание модели на этот тег
    comment: str = ""               # комментарий `{# … #}` бланка, стоящий перед тегом
    example: str = ""
    limits: dict = field(default_factory=dict)
    depends_on: list = field(default_factory=list)
    source_hint: str = "agent"      # agent | manual | file
    tool: str | None = None         # каким инструментом агент это добывает
    guessed: bool = False           # тип предложен по метке, человек его не подтверждал
    missing: bool = False           # записи нет в шаблоне (тег убрали, промпт бережём)


@dataclass
class Manifest:
    """`manifest_version` — счётчик правок этого манифеста, а не версия формата: версия
    формата — `wire_version`, та же система координат, что у значений (третьего счётчика
    не заводим). Шаблон опознаётся по `template_sha256`: один и тот же файл, загруженный
    дважды, — один шаблон и один манифест."""
    tags: dict = field(default_factory=dict)          # ключ тега (NFC) → TagSpec
    manifest_version: int = 1
    wire_version: int = WIRE_VERSION
    template_sha256: str = ""
    language: str = "ru"
    system_prompt: str = ""
    constructs: list = field(default_factory=list)    # `{% … %}` бланка, которых движок не знает


def _hint(name: str, known) -> str:
    near = difflib.get_close_matches(str(name), sorted(known), n=1, cutoff=0.6)
    return f' (похоже на "{near[0]}")' if near else ""


# ── заготовка из шаблона и сверка ─────────────────────────────────────────────

def suggest_type(label: str) -> str | None:
    """Тип по метке — догадка, и она отмечается как догадка (`TagSpec.guessed`)."""
    low = unicodedata.normalize("NFC", label or "").casefold()
    for needle, type_name in _TYPE_HINTS:
        if needle in low:
            return type_name
    return None


def default_spec(tag, comment: str = "") -> TagSpec:
    """Что тег получает, когда записи о нём в манифесте нет.

    Одно правило на два вопроса — заготовку манифеста и проверку значений (`validate`).
    Две копии разошлись бы на первой правке, и логотип в колонтитуле стал бы для проверки
    «обязательным тегом без значения».
    """
    header = tag.where in _HEADERS
    guess = suggest_type(tag.label)
    return TagSpec(type=guess or DEFAULT_TYPE, label=tag.label or tag.key,
                   required=not header, numbered=not header, guessed=guess is not None,
                   prompt=comment, comment=comment)


def manifest_from_template(template, *, base: Manifest | None = None,
                           language: str = "ru", system_prompt: str = "") -> Manifest:
    """Заготовка манифеста по тегам шаблона; с `base` — обновление старого манифеста
    под новый DOCX.

    Обновление устроено так: тег добавили — заводим запись с `markdown` и без промпта;
    тег убрали — ставим `missing: true`, но **не удаляем**: промпт и значения переживут
    случайную правку шаблона; изменилась только метка — обновляем метку, промпт не
    трогаем. Переименование мы не видим (оно выглядит как «убрали и добавили») и молча
    переносить промпт не имеем права: два тега, поменянных местами в Word, дали бы
    перепутанные значения, и никто бы этого не заметил. Подсказку об этом даёт
    `check_manifest`.

    **Комментарий бланка становится заданием тега.** `{# 4–6 предложений: итог
    квартала #}`, написанный автором бланка перед тегом, — это ровно то, что
    человек написал бы в поле «задание модели», и переписывать его руками во
    второй раз незачем. Комментарий кладётся и в `prompt` (уезжает модели), и в
    `comment` (что именно взято из бланка). Второе поле нужно при обновлении:
    задание, правленное человеком, комментарий бланка не переписывает, а
    нетронутое — обновляется вместе с бланком. Без такой памяти пришлось бы
    выбирать между «правка человека теряется» и «поправленный бланк ни на что
    не влияет».
    """
    extras = extract_extras(template)
    подсказки: dict = {}
    for текст, ключ in extras.comments:
        if not ключ:
            continue                     # после комментария тегов нет — приписать некуда
        подсказки[ключ] = (подсказки[ключ] + "\n" + текст) if ключ in подсказки else текст
    tags: dict = {}
    for tag in extract_tags(template):
        комментарий = подсказки.get(tag.key, "")
        old = (base.tags.get(tag.key) if base else None)
        if old is not None:
            свой = old.prompt.strip() not in ("", old.comment.strip())
            tags[tag.key] = replace(old, label=tag.label or old.label, missing=False,
                                    comment=комментарий,
                                    prompt=old.prompt if свой else комментарий)
            continue
        tags[tag.key] = default_spec(tag, комментарий)
    if base is not None:
        for key, old in base.tags.items():
            if key not in tags:
                tags[key] = replace(old, missing=True)
    return Manifest(tags=tags,
                    manifest_version=(base.manifest_version + 1) if base else 1,
                    template_sha256=_sha256(template),
                    language=base.language if base else language,
                    system_prompt=base.system_prompt if base else system_prompt,
                    constructs=list(extras.constructs))


def check_manifest(manifest: Manifest, template) -> list[Problem]:
    """Манифест против настоящих тегов шаблона → предупреждения.

    Запись — `model.Problem`, общий канал предупреждений проекта (`kyotsu.Notice`
    плюс тег), тот же, что у `validate` и `build_report`. Ошибок здесь нет: манифест
    шире шаблона это законное состояние (тег убрали, промпт бережём), а тег без записи
    просто соберётся с умолчаниями.
    """
    tags = {t.key: t for t in extract_tags(template)}
    out: list[Problem] = []
    for текст in extract_extras(template).constructs:
        out.append(_w("warning", "unknown_construct", "",
                      f"конструкция {текст!r} движку не знакома: она останется в "
                      "документе текстом, а тега в ней нет"))
    for key, tag in tags.items():
        spec = manifest.tags.get(key)
        if spec is None:
            out.append(_w("warning", "tag_without_entry", key,
                          f"тег {key!r} есть в шаблоне, но записи в манифесте нет: "
                          f"тип {DEFAULT_TYPE}, промпта нет"))
            continue
        if spec.missing:
            out.append(_w("info", "tag_returned", key,
                          f"тег {key!r} снова есть в шаблоне — снимите пометку «нет в шаблоне»"))
        if spec.guessed:
            out.append(_w("warning", "type_guessed", key,
                          f"тип тега {key!r} ({spec.type}) предложен по метке и не подтверждён"))
        if spec.label and tag.label and _same(spec.label) != _same(tag.label):
            out.append(_w("info", "label_changed", key,
                          f"подсказка в шаблоне теперь {tag.label!r}, в манифесте {spec.label!r}"))
        if tag.where in _HEADERS and spec.numbered:
            out.append(_w("warning", "numbered_in_header", key,
                          f"тег {key!r} стоит в колонтитуле: там нет нумерации и подписи, "
                          "numbered: false"))
        if not spec.prompt and spec.required and spec.source_hint == "agent":
            out.append(_w("info", "no_prompt", key,
                          f"тег {key!r} обязателен, заполняет его модель, а промпта нет"))
    for key, spec in manifest.tags.items():
        if key in tags:
            continue
        near = difflib.get_close_matches(key, [k for k in tags if k not in manifest.tags],
                                         n=1, cutoff=0.6)
        hint = (f"; похоже на {near[0]!r} — возможно, переименовали (перенести промпт "
                "и значение может только человек)") if near else ""
        # уже помеченное «нет в шаблоне» — известное состояние, а не новость
        seen = " (помечено «нет в шаблоне»)" if spec.missing else ""
        out.append(_w("info" if spec.missing else "warning", "entry_without_tag", key,
                      f"в манифесте есть {key!r}, а тега в шаблоне нет{seen}{hint}"))
    return out


def _same(label: str) -> str:
    """Метки сравниваем в NFC: Word и macOS пишут «й» разложенным, и без этого метка
    «изменилась» на каждой перезагрузке одного и того же шаблона."""
    return unicodedata.normalize("NFC", label.strip())


def _w(level: str, code: str, key: str, message: str) -> Problem:
    return Problem(module="hokoku", level=level, code=code, key=key, message=message)


def _sha256(template) -> str:
    """Шаблон опознаётся по sha256 своих байтов. Готовый Document байтов не имеет —
    у такого манифеста шаблон не опознан, и это честнее выдуманной суммы."""
    if isinstance(template, (bytes, bytearray)):
        return hashlib.sha256(bytes(template)).hexdigest()
    if isinstance(template, str):
        try:
            with open(template, "rb") as f:
                return hashlib.sha256(f.read()).hexdigest()
        except OSError:
            return ""
    return ""


# ── JSON ──────────────────────────────────────────────────────────────────────

_MANIFEST_KEYS = ("manifest_version", "wire_version", "template_sha256", "language",
                  "system_prompt", "constructs", "tags")


def manifest_from_json(d: dict) -> Manifest:
    """JSON → Manifest. Неизвестное поле — отказ: молча проглоченный `promt` это тег,
    который модель заполняет наугад, а объяснить потом нечем."""
    if not isinstance(d, dict):
        raise ManifestError(f"манифест должен быть объектом JSON, а не {type(d).__name__}")
    _known(d, _MANIFEST_KEYS, "манифесте")
    version = d.get("wire_version", WIRE_VERSION)
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise ManifestError("wire_version — целое число от 1")
    if version > WIRE_VERSION:
        raise ManifestError(f"манифест версии {version}, hokoku знает до {WIRE_VERSION}")
    edit = d.get("manifest_version", 1)
    if isinstance(edit, bool) or not isinstance(edit, int) or edit < 1:
        raise ManifestError("manifest_version — целое число от 1 (счётчик правок)")
    raw_tags = d.get("tags") or {}
    if not isinstance(raw_tags, dict):
        raise ManifestError(f"tags — объект «ключ тега → запись», а не {type(raw_tags).__name__}")
    tags: dict = {}
    for raw_key, item in raw_tags.items():
        key = norm_key(str(raw_key))
        if key in tags:
            raise ManifestError(f"ключ {raw_key!r} повторяется после нормализации NFC")
        tags[key] = _tag_from_json(key, item)
    constructs = d.get("constructs") or []
    if not isinstance(constructs, list) or any(not isinstance(x, str) for x in constructs):
        raise ManifestError("constructs — список строк: тексты конструкций бланка")
    return Manifest(tags=tags, manifest_version=edit, wire_version=version,
                    template_sha256=_str(d.get("template_sha256", ""), "template_sha256"),
                    language=_str(d.get("language", "ru"), "language"),
                    system_prompt=_str(d.get("system_prompt", ""), "system_prompt"),
                    constructs=list(constructs))


def _tag_from_json(key: str, d) -> TagSpec:
    if not isinstance(d, dict):
        raise ManifestError(f"запись тега {key!r} — объект JSON, а не {type(d).__name__}")
    known = {f.name for f in fields(TagSpec)}
    for name in d:
        if name not in known:
            raise ManifestError(f"тег {key!r}: неизвестное поле {name!r}{_hint(name, known)}")
    spec = TagSpec()
    type_name = d.get("type", DEFAULT_TYPE)
    if type_name not in MANIFEST_TYPES:
        raise ManifestError(f"тег {key!r}: неизвестный тип {type_name!r}"
                            f"{_hint(type_name, MANIFEST_TYPES)}")
    spec.type = type_name
    for name in ("label", "prompt", "comment", "example"):
        setattr(spec, name, _str(d.get(name, ""), f"{key}.{name}"))
    for name in ("required", "inline", "numbered", "guessed", "missing"):
        val = d.get(name, getattr(spec, name))
        if not isinstance(val, bool):
            raise ManifestError(f"тег {key!r}: поле {name!r} — true или false")
        setattr(spec, name, val)
    hint = d.get("source_hint", "agent")
    if hint not in SOURCE_HINTS:
        raise ManifestError(f"тег {key!r}: source_hint — {', '.join(SOURCE_HINTS)}, "
                            f"а не {hint!r}")
    spec.source_hint = hint
    tool = d.get("tool")
    spec.tool = None if tool is None else _str(tool, f"{key}.tool")
    spec.limits = _limits(key, d.get("limits") or {})
    depends = d.get("depends_on") or []
    if not isinstance(depends, list) or any(not isinstance(x, str) for x in depends):
        raise ManifestError(f"тег {key!r}: depends_on — список ключей других тегов")
    spec.depends_on = [norm_key(x) for x in depends]
    return spec


def _limits(key: str, d) -> dict:
    if not isinstance(d, dict):
        raise ManifestError(f"тег {key!r}: limits — объект JSON")
    out: dict = {}
    for name, val in d.items():
        want = LIMIT_KEYS.get(name)
        if want is None:
            raise ManifestError(f"тег {key!r}: неизвестное ограничение {name!r}"
                                f"{_hint(name, LIMIT_KEYS)}")
        if want is bool:
            if not isinstance(val, bool):
                raise ManifestError(f"тег {key!r}: limits.{name} — true или false")
        elif isinstance(val, bool) or not isinstance(val, int) or val <= 0:
            raise ManifestError(f"тег {key!r}: limits.{name} — целое число больше нуля")
        out[name] = val
    return out


def _str(v, name: str) -> str:
    if not isinstance(v, str):
        raise ManifestError(f"поле {name!r} — строка, а не {type(v).__name__}")
    return v


def _known(d: dict, allowed, what: str) -> None:
    for key in d:
        if key not in allowed:
            raise ManifestError(f"неизвестный ключ {key!r} в {what}{_hint(key, allowed)}")


def manifest_to_json(m: Manifest) -> dict:
    """Manifest → JSON. Умолчания не выписываются: манифест объявляет исключения,
    и диф правки должен показывать правку, а не двенадцать строк умолчаний."""
    plain = TagSpec()
    tags: dict = {}
    for key, spec in m.tags.items():
        d = {"type": spec.type}
        for f in fields(TagSpec):
            if f.name == "type":
                continue
            val = getattr(spec, f.name)
            if val != getattr(plain, f.name):
                d[f.name] = dict(val) if isinstance(val, dict) else \
                    list(val) if isinstance(val, list) else val
        tags[key] = d
    return {"manifest_version": m.manifest_version, "wire_version": m.wire_version,
            "template_sha256": m.template_sha256, "language": m.language,
            "system_prompt": m.system_prompt, "constructs": list(m.constructs),
            "tags": tags}


# ── промпт ────────────────────────────────────────────────────────────────────

_TYPE_WORD = {"markdown": "markdown (абзацы, списки, заголовки, таблицы)",
              "blocks": "несколько блоков подряд (текст, картинка, таблица)",
              "text": "простой текст без разметки",
              "image": "картинка из материалов проекта (идентификатор артефакта)",
              "diagram": "схема draw.io (её строит инструмент, XML не сочинять)",
              "code": "листинг (код берётся из файлов проекта, не сочиняется)",
              "formula": "формула в записи LaTeX",
              "table": "таблица (строки ячеек)",
              "toc": "оглавление (собирается само, содержимого не нужно)"}


def manifest_prompt(m: Manifest, *, keys: list | None = None) -> str:
    """Манифест → текст задания для модели: то, что уходит вместо DOCX.

    Порядок тегов — порядок документа (его даёт `extract_tags` и хранит `dict`), формат
    устойчивый: одинаковый манифест даёт знак в знак одинаковый текст, иначе кэш префикса
    промахивается на каждом вызове. Служебного (суммы шаблона, версий, `source_hint`,
    `tool`) в промпте нет: модель по ним ничего не решает.

    `keys` — сузить до перечисленных тегов (уровень 1: один тег за вызов).
    """
    picked = [(k, s) for k, s in m.tags.items()
              if not s.missing and (keys is None or k in keys)]
    lines: list[str] = []
    if m.system_prompt.strip():
        lines += [m.system_prompt.strip(), ""]
    lines.append(f"Теги шаблона — {len(picked)}. Значение каждого тега отдаётся отдельно, "
                 "по схеме своего типа.")
    for key, spec in picked:
        head = [_TYPE_WORD.get(spec.type, spec.type)]
        head.append("обязательный" if spec.required else "необязательный")
        if spec.inline:
            head.append("стоит внутри строки: без заголовков и списков")
        lines.append("")
        lines.append(f"[{key}] {spec.label or key} — " + "; ".join(head))
        if spec.prompt.strip():
            lines.append(f"  задание: {spec.prompt.strip()}")
        if spec.example.strip():
            lines.append(f"  пример: {spec.example.strip()}")
        limits = _limits_words(spec.limits)
        if limits:
            lines.append("  ограничения: " + ", ".join(limits))
        if spec.depends_on:
            lines.append("  опирается на: " + ", ".join(spec.depends_on))
    return "\n".join(lines)


def _limits_words(limits: dict) -> list[str]:
    words = []
    if "max_chars" in limits:
        words.append(f"не длиннее {limits['max_chars']} знаков")
    if "max_rows" in limits:
        words.append(f"строк не больше {limits['max_rows']}")
    if "max_cols" in limits:
        words.append(f"колонок не больше {limits['max_cols']}")
    if limits.get("headings") is False:
        words.append("заголовков не ставить")
    return words


# ── схема всего отчёта ────────────────────────────────────────────────────────

def manifest_schema(m: Manifest, *, keys: list | None = None) -> dict:
    """Манифест → JSON Schema всего ответа: {ключ тега: схема его типа}.

    Уровень «весь отчёт одним вызовом»: модель отдаёт значения всех тегов разом, и без
    общей схемы проверять их можно было бы только по одному — а лишний ключ (опечатка
    в имени тега) не проверялся бы вовсе и терялся молча. `additionalProperties: false`
    закрывает именно это.

    Схема склеена из `wire.value_schema(тип, for_model=True)`: второго описания формы
    значения здесь нет и быть не должно. `$schema` в корне нет намеренно — строгий режим
    поставщика ждёт в корне объект, а `llm.jsonschema.check_schema` незнакомое ключевое
    слово отвергает. В `required` — только обязательные теги; довести схему до требования
    «все ключи в required» умеет `llm.jsonschema.strictify`, и решать это ему, а не нам.

    `keys` — сузить до перечисленных тегов, как в `manifest_prompt`.
    """
    picked = [(k, s) for k, s in m.tags.items()
              if not s.missing and (keys is None or k in keys)]
    return {"type": "object",
            "properties": {k: value_schema(s.type, for_model=True) for k, s in picked},
            "required": [k for k, s in picked if s.required],
            "additionalProperties": False}
