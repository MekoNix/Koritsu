"""
wire — JSON ↔ типизированные значения тегов (model.py).

Шов, через который значения приходят снаружи: от скрипта, от службы, от модели.
Форма одна — помеченное объединение по `type`, поля один в один с датаклассами:
wire остаётся механическим переводом, а не вторым описанием мира. Схема строится из
`dataclasses.fields`, поэтому поле, добавленное в model.py и забытое здесь, роняет
импорт модуля, а не теряется молча внутри значения.

Правила, которые дороже удобства:
  • версия стоит на значении (`"v": 1`), а не на конверте: значения хранятся,
    версионируются и копируются по одному тегу, а не набором;
  • значение из будущей версии — ошибка, а не догадка: незнакомое поле могло менять
    смысл знакомых (`page` без `count_pages` дал бы не тот лист);
  • неизвестное поле — ошибка с именем поля и подсказкой «похоже на»: молча
    проглоченный ключ уже стоил проекту дефекта, на уровне полей это было бы ещё
    незаметнее — {"captionn": "Схема"} собрался бы без подписи, и объяснить нечем;
  • путей на диске в JSON нет ни одного, только идентификатор артефакта; байты достаёт
    колбэк resolve_artifact(id) -> bytes.

Пустое значение ("", Text(""), Table([])) здесь не проверяется: это делает render —
одна проверка на обе точки входа лучше двух, разошедшихся через полгода.
"""
from __future__ import annotations

import difflib
import io
import re
from dataclasses import dataclass, fields

from PIL import Image as PILImage

from .images import count_pages
from .model import (Blocks, Code, Diagram, Formula, HokokuError, Image, Markdown, PageBreak,
                    Table, Text, Toc, Value)
from .tags import norm_key

WIRE_VERSION = 1

# Идентификатор артефакта, а не имя файла: ни «/», ни «\», ни «..», ни «~» — путь
# в JSON запрещён по построению, а не проверкой у каждого вызывающего.
ARTIFACT_RE = re.compile(r"\A[A-Za-z0-9_.-]{1,64}\Z")
_ALIGN = ("left", "center", "right")


class WireError(HokokuError):
    """Значение не соответствует схеме: неизвестный тип, неизвестное поле, битая версия.

    stage — где рвануло: "wire" (значение не по схеме) или "artifact" (байтов нет
    в хранилище); build_report кладёт это прямо в свой список ошибок.
    """

    def __init__(self, message: str, *, key: str | None = None, path: str = "", stage: str = "wire"):
        self.message, self.key, self.path, self.stage = message, key, path, stage
        super().__init__(self._text())

    @property
    def detail(self) -> str:
        """Беда без имени тега: в errors ключ стоит отдельным полем, дублировать его незачем."""
        return f"{self.path}: {self.message}" if self.path else self.message

    def _text(self) -> str:
        where = f'значение "{self.key}"' if self.key else "значение"
        return f"{where} → {self.detail}" if self.path else f"{where}: {self.message}"

    def at_key(self, key: str) -> "WireError":
        """Та же беда с именем тега: value_from_json ключа не знает, values_from_json знает."""
        return WireError(self.message, key=key, path=self.path, stage=self.stage)


# ── разбор отдельных полей ────────────────────────────────────────────────────

_RU_TYPE = {str: "строка", bool: "логическое", int: "целое", float: "число",
            list: "список", dict: "объект", type(None): "null"}


def _ru(v) -> str:
    return _RU_TYPE.get(type(v), type(v).__name__)


def _hint(name: str, known) -> str:
    """«Похоже на» — не украшение: почти все такие ошибки это опечатки, свои или модели."""
    near = difflib.get_close_matches(name, sorted(known), n=1, cutoff=0.6)
    return f' (похоже на "{near[0]}")' if near else ""


def _string(v, name):
    if not isinstance(v, str):
        raise WireError(f'поле "{name}": ожидалась строка, а не {_ru(v)}')
    return v


def _opt_string(v, name):
    return None if v is None else _string(v, name)


def _flag(v, name):
    if not isinstance(v, bool):
        raise WireError(f'поле "{name}": ожидалось true или false, а не {_ru(v)}')
    return v


def _opt_flag(v, name):
    """true / false / null — «взять из styles» (line_numbers, highlight)."""
    return None if v is None else _flag(v, name)


def _number(v, name):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise WireError(f'поле "{name}": ожидалось число, а не {_ru(v)}')
    if v <= 0:
        raise WireError(f'поле "{name}": {v} — размер в сантиметрах, больше нуля')
    return float(v)


def _opt_number(v, name):
    return None if v is None else _number(v, name)


def _caption(v, name):
    """Трёхзначна, и JSON выражает это нативно: строка — подпись с текстом, null — «Рисунок N»
    без текста, false — без подписи и без номера (логотип, врезка). Сентинелов не заводим."""
    if v is None or v is False:
        return v
    if v is True:
        raise WireError(f'поле "{name}": true бессмысленно — строка, null или false')
    return _string(v, name)


def _err_list(v, name):
    raise WireError(f'поле "{name}": ожидался список, а не {_ru(v)}')


def _align(v, name):
    if v not in _ALIGN:
        raise WireError(f'поле "{name}": {v!r} — можно {", ".join(_ALIGN)}')
    return v


def _opt_align_list(v, name):
    if v is None:
        return None
    if not isinstance(v, list):
        _err_list(v, name)
    return [_align(x, name) for x in v]


def _opt_widths(v, name):
    if v is None:
        return None
    if not isinstance(v, list):
        _err_list(v, name)
    return [_number(x, name) for x in v]


def _rows(v, name):
    """Все строки длиной с первую. Сегодня Table рваную таблицу молча расширяет до
    max(len(row)) и оставляет дыры; контракт этого не наследует — тихая дыра в отчёте
    неотличима от задуманной пустой ячейки."""
    if not isinstance(v, list):
        _err_list(v, name)
    out: list[list[str]] = []
    for i, row in enumerate(v, 1):
        if not isinstance(row, list):
            raise WireError(f'поле "{name}": строка {i} — {_ru(row)}, а нужен список ячеек')
        for j, cell in enumerate(row, 1):
            if not isinstance(cell, str):
                raise WireError(f'поле "{name}": ячейка [{i}][{j}] — {_ru(cell)}, а нужна строка')
        if out and len(row) != len(out[0]):
            raise WireError(f'поле "{name}": в строке {i} ячеек {len(row)}, а в первой {len(out[0])}')
        out.append(list(row))
    return out


def _levels(v, name):
    if isinstance(v, bool) or not isinstance(v, int) or not 1 <= v <= 9:
        raise WireError(f'поле "{name}": {v!r} — целое от 1 до 9 (глубже Word не знает)')
    return v


def _page(v, name):
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, int) or v < 1:
        raise WireError(f'поле "{name}": {v!r} — номер листа, считая с 1')
    return v


def _artifact(v, name):
    """Только идентификатор. Байты подставит _build, когда позовёт resolve_artifact."""
    _string(v, name)
    if not ARTIFACT_RE.match(v) or ".." in v:
        raise WireError(f'поле "{name}": {v[:80]!r} — не идентификатор артефакта '
                        "(буквы, цифры, «_.-», до 64 знаков; путей и base64 в JSON нет)")
    return v


def _raw_list(v, name):
    if not isinstance(v, list):
        _err_list(v, name)
    return list(v)


# ── таблица типов ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class _Field:
    schema: dict                    # фрагмент JSON Schema
    parse: object                   # (значение JSON, имя поля) -> значение датакласса
    attr: str = ""                  # поле датакласса, если имя другое (artifact → source)
    required: bool = False
    for_model: bool = True          # показываем ли поле модели (diagram.xml — нет)
    model_schema: dict | None = None    # схема для модели, если она уже (caption без false)
    model_required: bool = False    # обязательно только в схеме для модели
    emit: bool = True               # пишем ли обратно в JSON (diagram.artifact — нет)


@dataclass(frozen=True)
class _Spec:
    name: str
    cls: type
    props: dict                     # имя поля JSON → _Field, в порядке датакласса
    service: frozenset = frozenset()    # поля датакласса, которых в JSON нет: их ставит служба


_CAPTION = _Field({"anyOf": [{"type": "string"}, {"type": "null"}, {"const": False}]}, _caption,
                  model_schema={"type": ["string", "null"]})
_WIDTH = _Field({"type": ["number", "null"], "exclusiveMinimum": 0}, _opt_number)
# «enum» без «type» — схема без типа: наш валидатор её понимает, а строгий режим
# поставщика на такое поле отвечает 400. Тип пишем явно, как у _WIDTH и _REF; null
# сюда не входит намеренно — выравнивание по умолчанию задаёт стиль, а не значение,
# и «промолчать» модели даёт strictify, дописывая null необязательному полю сам.
_ALIGN_SCHEMA = {"type": "string", "enum": list(_ALIGN)}
_ALIGN_ONE = _Field(dict(_ALIGN_SCHEMA), _align)
_REF = _Field({"type": ["string", "null"]}, _opt_string)
_TEXT = _Field({"type": "string"}, _string, required=True)
_ART_SCHEMA = {"type": "string", "pattern": "^[A-Za-z0-9_.-]{1,64}$"}


def _spec(name, cls, props, service=()):
    return _Spec(name, cls, props, frozenset(service))


_TYPES: dict[str, _Spec] = {s.name: s for s in (
    _spec("text", Text, {"text": _TEXT}),
    # images_dir ставит служба: это каталог на диске, а в JSON путей нет
    _spec("markdown", Markdown, {"text": _TEXT}, service={"images_dir"}),
    _spec("code", Code, {
        "text": _TEXT,
        "lang": _Field({"type": "string"}, _string),
        "line_numbers": _Field({"type": ["boolean", "null"]}, _opt_flag),
        "highlight": _Field({"type": ["boolean", "null"]}, _opt_flag)}),
    _spec("image", Image, {
        "artifact": _Field(_ART_SCHEMA, _artifact, attr="source", required=True),
        "caption": _CAPTION, "width_cm": _WIDTH, "align": _ALIGN_ONE, "ref": _REF}),
    _spec("diagram", Diagram, {
        # ровно одно из двух; xml — для своих (fragmos и uml отдают схему строкой, заводить
        # артефакт ради одноразовой схемы незачем), модели его не показываем: рисовать
        # draw.io XML она не должна
        "artifact": _Field(_ART_SCHEMA, _artifact, attr="xml", emit=False, model_required=True),
        "xml": _Field({"type": "string"}, _string, attr="xml", for_model=False),
        "caption": _CAPTION, "width_cm": _WIDTH, "align": _ALIGN_ONE, "ref": _REF,
        "page": _Field({"type": ["integer", "null"], "minimum": 1}, _page)}),
    _spec("table", Table, {
        "rows": _Field({"type": "array", "items": {"type": "array", "items": {"type": "string"}}},
                       _rows, required=True),
        "header": _Field({"type": "boolean"}, _flag),
        "caption": _CAPTION,
        "col_widths_cm": _Field({"type": ["array", "null"], "items": {"type": "number"}}, _opt_widths),
        "align": _Field({"type": ["array", "null"], "items": dict(_ALIGN_SCHEMA)},
                        _opt_align_list),
        "ref": _REF}),
    _spec("formula", Formula, {
        "latex": _Field({"type": "string"}, _string, required=True),
        "numbered": _Field({"type": "boolean"}, _flag),
        "ref": _REF}),
    _spec("toc", Toc, {
        "levels": _Field({"type": "integer", "minimum": 1, "maximum": 9}, _levels),
        "title": _Field({"type": ["string", "null"]}, _opt_string)}),
    _spec("page_break", PageBreak, {}),
    _spec("blocks", Blocks, {
        "items": _Field({"type": "array"}, _raw_list, required=True)}),
)}

_SPEC_BY_CLASS = {s.cls: s for s in _TYPES.values()}

# Имена типов наружу: манифест шаблона объявляет тип тега теми же словами, что стоят
# в значении, и брать их обязан отсюда — иначе два списка разойдутся на первой правке.
VALUE_TYPES = tuple(_TYPES)


def _check_model_coverage() -> None:
    """Поле, добавленное в model.py и забытое здесь, обязано ронять импорт: иначе значение
    молча теряет настройку, а обнаруживается это глазами на готовом отчёте."""
    for spec in _TYPES.values():
        covered = {f.attr or n for n, f in spec.props.items()} | set(spec.service)
        missing = [f.name for f in fields(spec.cls) if f.name not in covered]
        if missing:
            raise RuntimeError(
                f"wire: поля {spec.cls.__name__}.{missing[0]} нет в схеме значения — "
                f"допишите его в _TYPES (и поднимите WIRE_VERSION) либо в service, "
                f"если его ставит служба")


_check_model_coverage()

# Миграции словарь → словарь: ключ — версия «откуда». Чистые, без ввода-вывода и без
# resolve_artifact; применяются до постройки датакласса, иначе каждая правка model.py
# требовала бы держать копию старого датакласса.
_MIGRATIONS: dict[int, object] = {}


# ── JSON → значение ───────────────────────────────────────────────────────────

def _as_object(d, path):
    if not isinstance(d, dict):
        raise WireError(f"значение должно быть объектом JSON, а не {_ru(d)}", path=path)
    return d


def _upgrade(d: dict) -> dict:
    # версию можно не писать — тогда значение считается текущей версии. Так же ведёт себя
    # `wire_version` у задания, и требовать её на каждом значении значило бы заставлять
    # каждого производителя (интерфейс, скрипт, модель) штамповать «v» в каждом объекте.
    # Написанная версия проверяется строго: чужая или из будущего — отказ.
    v = d.get("v", WIRE_VERSION)
    if isinstance(v, bool) or not isinstance(v, int) or v < 1:
        raise WireError('поле "v" (версия схемы значения) должно быть целым числом от 1')
    if v > WIRE_VERSION:
        raise WireError(f"значение версии {v}, читатель знает до {WIRE_VERSION}")
    d = dict(d)
    while v < WIRE_VERSION:
        d = _MIGRATIONS[v](d)
        v += 1
    d.pop("v", None)
    return d


def value_from_json(d: dict, *, resolve_artifact=None) -> Value:
    """Один JSON-объект → типизированное значение.

    resolve_artifact(artifact_id: str) -> bytes — обязателен, если в значении есть `artifact`.
    """
    return _value(_upgrade(_as_object(d, "")), resolve_artifact, "", nested=False)


def _value(d: dict, resolve, path: str, nested: bool):
    spec = _spec_of(d, path)
    if nested and spec.name == "blocks":
        raise WireError("внутри blocks нельзя вкладывать blocks: вложенность ничего не выражает "
                        "сверх плоского списка", path=path)
    kwargs = {}
    for name, raw in d.items():
        if name == "type":
            continue
        if name == "v":
            raise WireError('поле "v" стоит только на значении верхнего уровня: элементы blocks '
                            "наследуют версию своего значения", path=path)
        f = spec.props.get(name)
        if f is None:
            raise WireError(f'неизвестное поле "{name}"{_hint(name, spec.props)}', path=path)
        try:
            kwargs[f.attr or name] = f.parse(raw, name)
        except WireError as e:
            raise WireError(e.message, path=path, stage=e.stage) from None
    missing = [n for n, f in spec.props.items() if f.required and n not in d]
    if missing:
        raise WireError(f'нет обязательного поля "{missing[0]}"', path=path)
    return _build(spec, kwargs, d, resolve, path)


def _spec_of(d: dict, path: str) -> _Spec:
    t = d.get("type")
    if t is None:
        raise WireError('нет поля "type": значение — всегда объект с типом', path=path)
    if not isinstance(t, str) or t not in _TYPES:
        raise WireError(f"неизвестный тип {t!r}{_hint(str(t), _TYPES)}", path=path)
    return _TYPES[t]


def _resolve(resolve_artifact, art_id: str, name: str) -> bytes:
    if resolve_artifact is None:
        raise WireError(f'поле "{name}": байты артефакта {art_id!r} достать некому '
                        "(не передан resolve_artifact)")
    try:
        data = resolve_artifact(art_id)
    except Exception as e:                                   # noqa: BLE001 — хранилище чужое
        raise WireError(f"артефакт {art_id!r} не достался: {type(e).__name__}: {e}",
                        stage="artifact") from None
    if not isinstance(data, (bytes, bytearray)):
        raise WireError(f"артефакт {art_id!r}: resolve_artifact вернул {_ru(data)}, а нужны байты",
                        stage="artifact")
    return bytes(data)


def _check_image(data: bytes, art_id: str) -> None:
    """Дешёвая проверка при разборе: заголовок читает PIL, целиком картинка не декодируется.
    Иначе «это не картинка» всплывает посреди сборки, когда номер рисунка уже потрачен."""
    head = data[:512].lstrip()
    if head.startswith(b"<") and b"<svg" in head.lower():
        return                          # SVG растрирует to_raster (cairosvg), PIL его не откроет
    try:
        with PILImage.open(io.BytesIO(data)) as im:
            im.size
    except Exception as e:                                   # noqa: BLE001 — PIL кидает своё
        raise WireError(f"артефакт {art_id!r} не картинка: {e}") from None


def _build(spec: _Spec, kwargs: dict, raw: dict, resolve, path: str):
    if spec.name == "image":
        art = kwargs["source"]                   # пока идентификатор, дальше — байты
        data = _resolve(resolve, art, "artifact")
        _check_image(data, art)
        kwargs["source"] = data
    elif spec.name == "diagram":
        art, xml = "artifact" in raw, "xml" in raw
        if art == xml:
            raise WireError('у diagram ровно одно из "artifact" и "xml"'
                            + (" — заданы оба" if art else " — не задано ни одного"), path=path)
        if art:
            data = _resolve(resolve, raw["artifact"], "artifact")
            try:
                kwargs["xml"] = data.decode("utf-8")
            except UnicodeDecodeError:
                raise WireError(f"артефакт {raw['artifact']!r}: схема draw.io должна быть текстом "
                                "UTF-8", stage="artifact") from None
        page = kwargs.get("page")
        if page is not None:
            total = count_pages(kwargs["xml"])
            if page > total:
                raise WireError(f'поле "page": лист {page}, а в схеме листов {total}', path=path)
    elif spec.name == "table":
        rows = kwargs.get("rows") or []
        ncols = len(rows[0]) if rows else 0
        for name in ("align", "col_widths_cm"):
            val = kwargs.get(name)
            if val is not None and rows and len(val) != ncols:
                raise WireError(f'поле "{name}": {len(val)} значений на {ncols} колонок', path=path)
    elif spec.name == "blocks":
        at = f"{path}." if path else ""
        kwargs["items"] = [_value(_as_object(item, f"{at}items[{i}]"), resolve,
                                  f"{at}items[{i}]", nested=True)
                           for i, item in enumerate(kwargs["items"])]
    return spec.cls(**kwargs)


def values_from_json(d: dict, *, resolve_artifact=None) -> tuple[dict, list[dict]]:
    """Набор значений «ключ тега → значение» → ({ключ: значение}, ошибки).

    Ошибки — [{key, stage, message}], как RenderResult.errors: build_report дописывает их
    в свой список, а тег остаётся незаполненным и уезжает в unfilled. Одна битая запись
    не отменяет остальные — отчёт с пометками полезнее отказа целиком.
    """
    if not isinstance(d, dict):
        raise WireError(f"набор значений должен быть объектом JSON, а не {_ru(d)}")
    values: dict = {}
    errors: list[dict] = []
    for raw_key, item in d.items():
        key = norm_key(str(raw_key))            # ключи в NFC с обеих сторон, третий раз на входе
        if key in values:
            errors.append({"key": key, "stage": "wire",
                           "message": f"ключ {raw_key!r} повторяется после нормализации NFC"})
            continue
        try:
            values[key] = value_from_json(item, resolve_artifact=resolve_artifact)
        except WireError as e:
            errors.append({"key": key, "stage": e.stage, "message": e.detail})
    return values, errors


# ── значение → JSON ───────────────────────────────────────────────────────────

def value_to_json(v: Value, *, artifact_of=None) -> dict:
    """Типизированное значение → JSON. artifact_of(data: bytes) -> str кладёт байты
    Image(source=bytes) в хранилище и возвращает идентификатор: выдумать его wire не может,
    а путь наружу протащить не имеет права."""
    return _to_json(v, artifact_of, nested=False)


def _to_json(v, artifact_of, nested: bool) -> dict:
    # Голых скаляров в JSON нет (true стало бы словом «да»), но перевести питоновское
    # значение в текстовое — теми же правилами, что render, — можно и нужно: иначе набор
    # значений «как из руки» в JSON не выражается вовсе.
    if isinstance(v, bool):
        v = Text("да" if v else "нет")
    elif isinstance(v, (int, float)):
        v = Text(str(v))
    elif isinstance(v, str):
        v = Text(v)
    spec = _SPEC_BY_CLASS.get(type(v))
    if spec is None:
        raise WireError(f"значение типа {type(v).__name__} в JSON не выражается")
    out: dict = {} if nested else {"v": WIRE_VERSION}
    out["type"] = spec.name
    for name, f in spec.props.items():
        if f.emit:
            out[name] = _dump(spec, name, getattr(v, f.attr or name), artifact_of)
    return out


def _dump(spec: _Spec, name: str, val, artifact_of):
    if spec.name == "image" and name == "artifact":
        if isinstance(val, str):
            raise WireError("Image(source=путь) в JSON не выражается: путей там нет — положите "
                            "файл в хранилище и передайте идентификатор")
        if artifact_of is None:
            raise WireError("Image(source=bytes): нужен artifact_of, чтобы положить байты "
                            "в хранилище и получить идентификатор")
        return _artifact(artifact_of(bytes(val)), "artifact")
    if name == "items":
        return [_to_json(item, artifact_of, nested=True) for item in val]
    if name == "rows":
        return [list(row) for row in val]
    if name in ("align", "col_widths_cm") and isinstance(val, list):
        return list(val)
    return val


def values_to_json(values: dict, *, artifact_of=None) -> dict:
    return {norm_key(str(k)): value_to_json(v, artifact_of=artifact_of) for k, v in values.items()}


# ── схема ─────────────────────────────────────────────────────────────────────

def value_schema(type_name: str | None = None, *, for_model: bool = False) -> dict:
    """JSON Schema контракта — одна на всех: валидатор, документация, structured output модели.

    for_model=True убирает то, чего модель не решает: diagram.xml (схемы она не рисует),
    caption=false (это свойство шаблона, его ставит манифест) и «v» из required (версию
    ставит служба, а при чтении она необязательна).

    Схема без имени типа (`value_schema()`) — документация и валидатор, а не схема для
    модели: у неё в корне `anyOf` и `$schema`, а строгий режим поставщика ждёт в корне
    объект. Модели схему дают по одному тегу — тип тега известен из манифеста.
    """
    if type_name is None:
        return {"$schema": "https://json-schema.org/draft/2020-12/schema",
                "title": "Значение тега hokoku",
                "anyOf": [_type_schema(s, for_model, False) for s in _TYPES.values()]}
    if type_name not in _TYPES:
        raise WireError(f"неизвестный тип {type_name!r}{_hint(str(type_name), _TYPES)}")
    return _type_schema(_TYPES[type_name], for_model, False)


def _type_schema(spec: _Spec, for_model: bool, nested: bool) -> dict:
    props: dict = {"type": {"const": spec.name}}
    required = ["type"]
    if not nested:
        props["v"] = {"type": "integer", "minimum": 1, "maximum": WIRE_VERSION}
        # Модели версия не обязательна: при чтении она и так необязательна (её ставит
        # _upgrade), а в схеме это лишние токены на каждом значении и лишний повод
        # валидатору отказать из-за поля, которое модель не решает.
        if not for_model:
            required.append("v")
    for name, f in spec.props.items():
        if for_model and not f.for_model:
            continue
        props[name] = dict(f.model_schema if for_model and f.model_schema else f.schema)
        if f.required or (for_model and f.model_required):
            required.append(name)
    if spec.name == "blocks":
        # внутрь blocks проходит всё, что принимает _emit_value, кроме самого blocks;
        # элементы наследуют версию своего значения, поэтому «v» у них нет
        props["items"] = {"type": "array",
                          "items": {"anyOf": [_type_schema(s, for_model, True)
                                              for s in _TYPES.values() if s.name != "blocks"]}}
    return {"type": "object", "properties": props, "required": required,
            "additionalProperties": False}
