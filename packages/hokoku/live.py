"""
live — живой режим: работа это упорядоченный список именованных блоков.

Второй способ работы, отличающийся от обычного ровно одним: **шаблона нет**.
Человек кидает материалы, агент вставляет блоки словами, документ — сборка списка.
Обычный путь (шаблон с тегами → значения → `render`) остаётся целиком и не правится.

Несущее решение: **список — источник, документ — сборка, а не наоборот.** Мутировать
готовый DOCX нельзя, довод один и решающий: пропадает отмена, а в совместном письме
она нужна каждый ход. Отсюда всё остальное здесь: `Work` неизменяем, каждая операция
возвращает новый список, прежний цел и годится для «верни как было» без единой копии
на стороне вызывающего.

Второго рисовальщика не заводится, и это проверяемо, а не обещано. `assemble` строит
из списка **синтетический шаблон**: `blank_document()` плюс по абзацу `{{ключ}}` на
блок, — и зовёт тот же `render(шаблон, значения)`, что и шаблонный режим. Значит
подписи, счётчики SEQ, закладки, поля REF, оглавление и `{ref:имя}` работают ровно
тем же кодом; `build_report` не дублируется — `work_template()` и `work_values()`
отдают ему шаблон и значения, и живой список едет в него как обычное задание.
Из этого же следует, что имя блока и имя ссылки — одно и то же слово: `{ref:b-07}`
находит блок `b-07` без всяких закладок в документе, потому что ключ блока стал
ключом тега.

Заголовок уровня N отдельным типом значения не заводится: это `Markdown` из одной
строки `## Название`. Довод — `render` уже ставит на него настоящий стиль `Heading N`
(`_emit_markdown` → `docx_ops.style_heading`), а значит его находит и поле TOC, и
«Обновить оглавление» в Word. Новый тип значения пришлось бы завести в `model`, `wire`
и `validate` разом, поднять контракт и переучить всех, кто уже пишет против
`VALUE_TYPES`, — ради того, что и так собирается правильно.

Чего здесь нет намеренно: хранилища, версий, проекта и вызовов модели. Список блоков
с версиями хранит `orchestrator`, модель зовёт он же — `live_tools()` отдаёт
только объявления и `call_tool` над списком. `hokoku` остаётся библиотекой без
состояния, как и был.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, replace as _replace

from . import docx_ops as ops
from .markdown import REF_RE
from .model import (Blocks, Code, Diagram, Formula, HokokuError, Image, Markdown, Problem,
                    RenderResult, Table, Text, Toc)
from .render import _empty_value, render
from .report import HARD_LIMITS, _JobError, _check_value
from .sample import apply_style
from .tags import norm_key, parse_tag
from .template import blank_document, document_bytes
from .validate import _TYPE_OF, _refs
from .wire import VALUE_TYPES, WireError, value_from_json, value_schema

# Виды блоков: имена типов значений `wire` плюс «heading». Второго списка типов не
# заводится — он бы разошёлся с `wire` на первой правке, поэтому `KINDS` собирается
# из `VALUE_TYPES`, а не переписывается руками.
KINDS = ("heading",) + tuple(name for name in VALUE_TYPES if name != "blocks")

# Виды, в которые пишется связный текст одним проходом.
# Заголовка тут нет: заголовок — скелет, его ставит петля, и переписывать его текстовым
# проходом значило бы менять строение работы задним числом.
TEXT_KINDS = ("text", "markdown")

# Сколько знаков блока показывать в `list_blocks`. Модели нужен не текст, а опознание:
# «тот ли это блок». Отдать содержимое целиком — вернуть в окно весь отчёт на каждом ходу.
PREVIEW_CHARS = 120

# Пометка черновика: текстовый блок, начинающийся с неё, считается местом под текст,
# а не написанным текстом. Нужна затем, что пустое значение `render` считает ошибкой
# (`_empty_value`), и оставить дырку в списке буквально пустой нельзя — она не соберётся
# даже для показа человеку.
#
# **Пометка — строка в самом значении, и отдельного поля у блока не будет.** Флаг «это
# ещё не написано» пришлось бы носить через запись на диске, `wire`, сборку и проход
# текста, и в первом же месте, где его забыли переложить, черновик уехал бы в готовый
# документ молчаливым абзацем. Строка едет вместе со значением сама и видна человеку,
# открывшему промежуточный DOCX: он читает «черновик:», а не пустую страницу. Кто
# написал блок — вопрос другой и решается пометкой источника (`source` в записи
# проекта), от которой зависит, можно ли его переписывать.
DRAFT_MARK = "черновик:"

# Заготовка раздела, который заполняет **инструмент**, а не проход текста, несёт
# в самой пометке вид ожидаемого содержимого: «черновик diagram: схема
# алгоритма». Без него заготовка схемы неотличима от места под текст, и проход
# текста заливает её прозой: раздел выглядит написанным, а схемы в работе нет,
# и обнаруживает это человек в готовом отчёте. Вид стоит строкой в значении по
# той же причине, что и сама пометка (см. выше): отдельное поле пришлось бы
# перекладывать через запись, `wire` и сборку, и первый же забытый
# перекладыватель вернул бы прозу вместо схемы.
_DRAFT_RE = re.compile(r"\Aчерновик(?:[ \t]+([a-z_]+))?:[ \t]*", re.I)

_HEADING_RE = re.compile(r"\A(#{1,6})[ \t]+(\S.*)\Z")

# Класс значения → вид. Таблица одна на проект: `validate._TYPE_OF` уже связывает
# классы `model` со словами `wire`, и вторая копия расходится молча.
_KIND_BY_CLASS = dict(_TYPE_OF)


class LiveError(HokokuError):
    """Живой режим позвали неправильно: неизвестный ключ, чужой вид, битое значение.

    `payload` — ответ, который вызывающий отдаёт модели как `is_error`: код и текст,
    в котором сказано, что именно поправить. Своего типа для этого хватает, а звать
    `orchestrator.tools.ToolError` нельзя — `hokoku` соседей не импортирует.
    """

    def __init__(self, code: str, message: str, **extra):
        super().__init__(message)
        self.code = code
        self.payload = {"error": code, "message": message, **extra}


# ── блок и список ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Block:
    """Именованный кусок содержимого: ключ, вид, значение, метка для человека.

    Подписи и `ref` полями блока не сделаны намеренно, хотя просились. Они уже живут
    на самих значениях (`Image.caption`, `Table.ref`, `Formula.ref`), и второе место
    для них означало бы два ответа на вопрос «как подписан рисунок»: разошлись бы они
    молча, а в документ уехал бы один. Здесь они — свойства только на чтение, и берутся
    оттуда же, откуда их берёт `render`.

    `label` — читаемая метка («Постановка задачи»), её показывают человеку и модели.
    Ключ ей не заменишь: ключ это адрес, по нему стоит `{ref:}`, а метку можно менять
    сколько угодно и ничего не порвётся.
    """

    key: str
    kind: str
    value: object
    label: str = ""

    @property
    def caption(self) -> str | None:
        """Подпись значения, если она у него есть и это текст."""
        cap = getattr(self.value, "caption", None)
        return cap if isinstance(cap, str) else None

    @property
    def ref(self) -> str:
        """Имя, которым на блок ссылаются в тексте. По умолчанию — ключ: `render`
        нумерует подпись именем тега, а тегом блока стал его ключ."""
        own = getattr(self.value, "ref", None)
        return own if isinstance(own, str) and own else self.key

    @property
    def level(self) -> int | None:
        """Уровень заголовка (1..6) или None, если блок не заголовок."""
        return heading_level(self.value)

    @property
    def text(self) -> str:
        """Написанный человеком или моделью текст блока — то, что показывают в превью."""
        return _text_of(self.value)


@dataclass(frozen=True)
class Work:
    """Работа: упорядоченный список блоков. Неизменяем — отмена нужна каждый ход.

    Кортеж, а не список, и `frozen=True` не ради строгости: `insert` над изменяемым
    списком когда-нибудь напишут «на месте», и прежнего списка не станет ровно тогда,
    когда он понадобится.
    """

    blocks: tuple[Block, ...] = ()

    def __iter__(self):
        return iter(self.blocks)

    def __len__(self) -> int:
        return len(self.blocks)

    def keys(self) -> list[str]:
        return [b.key for b in self.blocks]

    def get(self, key: str) -> Block | None:
        key = norm_key(str(key))
        for b in self.blocks:
            if b.key == key:
                return b
        return None

    def index(self, key: str) -> int:
        """Место блока в списке. Индексами наружу не пользуются — они сдвигаются молча
        при первой вставке выше; это внутренний счёт операций."""
        key = norm_key(str(key))
        for i, b in enumerate(self.blocks):
            if b.key == key:
                return i
        raise LiveError("unknown_block", f"блока {key!r} в списке нет{_hint(key, self.keys())}",
                        known=self.keys())


# ── ключи и виды ──────────────────────────────────────────────────────────────

def check_key(key) -> str:
    """Ключ блока в NFC, годный тегом. → ключ; иначе LiveError.

    Годность проверяется самим разбором тега, а не копией его регулярки: ключ обязан
    пережить поездку через `{{ключ}}` в синтетическом шаблоне (`work_template`), и
    второе описание того же правила разошлось бы с `tags.TAG_RE` на первой правке.
    """
    key = norm_key(str(key))
    if not key:
        raise LiveError("bad_key", "ключ блока пустой")
    if parse_tag("{{" + key + "}}") != (key, key):
        raise LiveError("bad_key", f"ключ {key!r} нельзя поставить тегом: в нём пробел "
                                   "или один из знаков «{}:|#/». Ключ — короткий адрес "
                                   "латиницей, например b-07 или alg1; название блока "
                                   "живёт отдельно, в метке")
    return key


# Приставка имени закладки блока. Своя, чтобы закладки блоков не путались с закладками
# подписей (`_Ref_…`), которые рендер ставит вокруг номеров рисунков и таблиц.
BOOKMARK_PREFIX = "blk"

# Знак, с которого начинается escape в имени закладки (см. `bookmark_name`). Латинская
# буква, а не подчёркивание или процент: имя обязано состоять из букв и цифр целиком.
BOOKMARK_ESC = "X"


def bookmark_name(key) -> str:
    """Ключ блока → имя закладки Word. Обратимо: ключ возвращает `key_of_bookmark`.

    Форма: `blk`, затем ключ, в котором латинские буквы и цифры стоят как есть, а
    каждый прочий знак (и сама буква `X`) записан как `X` плюс два шестнадцатеричных
    знака заглавными — по паре на каждый байт UTF-8. Одиночной `X` в имени не бывает,
    поэтому разбор однозначен. `b-01` → `blkbX2D01`, `X` → `blkX58`.

    Имя выходит из букв и цифр и начинается с буквы — и это не вкусовщина, а два
    ограничения подряд. Имя закладки Word состоит из букв, цифр и подчёркиваний и
    начинается с буквы, а ключ блока — короткий адрес вида `b-01`, где дефис обычен;
    имя без кодирования Word выбросил бы вместе с закладкой. Дальше закладка едет в
    PDF именованным назначением, а туда имя попадает не буква в букву: всё, кроме букв
    и цифр, заменяется кодом знака, и `_` из имени превратился бы в `5F`. Имя из одних
    букв и цифр переживает обе поездки без изменений, поэтому на превью назначение
    зовут ровно тем именем, которое дала эта функция.

    Длина имени закладки в Word — до 40 знаков; на ключ остаётся 37 знаков после
    кодирования. Более длинный ключ имя всё равно получает: потерять закладку значит
    потерять блок на превью, а документ от длинного имени не портится — обрезать его
    Word стал бы только при собственном сохранении.
    """
    out = [BOOKMARK_PREFIX]
    for ch in norm_key(str(key)):
        if ch.isascii() and ch.isalnum() and ch != BOOKMARK_ESC:
            out.append(ch)
        else:
            out.extend(BOOKMARK_ESC + "%02X" % b for b in ch.encode("utf-8"))
    return "".join(out)


def key_of_bookmark(name) -> str | None:
    """Имя закладки (или именованного назначения PDF) → ключ блока.

    → None, если имя не наше или испорчено: в списке назначений PDF лежат и чужие
    имена — закладки подписей, оглавление, ссылки внутри документа.
    """
    if not isinstance(name, str) or not name.startswith(BOOKMARK_PREFIX):
        return None
    body, raw, i = name[len(BOOKMARK_PREFIX):], bytearray(), 0
    while i < len(body):
        ch = body[i]
        if ch == BOOKMARK_ESC:
            pair = body[i + 1:i + 3]
            if len(pair) != 2 or any(c not in "0123456789abcdefABCDEF" for c in pair):
                return None
            raw.append(int(pair, 16))
            i += 3
        elif ch.isascii() and ch.isalnum():
            raw.append(ord(ch))
            i += 1
        else:
            return None
    try:
        key = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None
    return norm_key(key) or None


def new_key(work: Work, *, prefix: str = "b") -> str:
    """Свободный ключ блока: `b-01`, `b-02`, … Уникальность — **после** нормализации.

    Пункт из `status.md`: два сгенерированных ключа, различающиеся только формой NFC,
    схлопнутся в один — и второй блок затрёт первый молча. Проверка стоит по `norm_key`,
    то есть по тому же признаку, по которому их сравнит `render` и `values_from_json`.

    Ключ непрозрачный, а метка отдельно: читаемый ключ соблазняет переименовать,
    а ключ это адрес — по нему стоят `{ref:}` и история версий.
    """
    taken = {norm_key(b.key) for b in work.blocks}
    n = len(work.blocks) + 1
    while True:
        key = f"{prefix}-{n:02d}"
        if norm_key(key) not in taken:
            return check_key(key)
        n += 1


def heading_level(value) -> int | None:
    """Уровень заголовка значения или None. Заголовок — `Markdown` из одной строки
    `## Название`: отдельного типа значения для него нет (см. докстроку модуля)."""
    if not isinstance(value, Markdown):
        return None
    text = value.text.strip()
    if "\n" in text:
        return None
    m = _HEADING_RE.match(text)
    return len(m.group(1)) if m else None


def heading(level: int, text: str) -> Markdown:
    """Заголовок уровня N значением. Перевод строки в тексте убирается: заголовок из
    двух абзацев — это два заголовка, и второй уехал бы в оглавление отдельной строкой."""
    if not isinstance(level, int) or isinstance(level, bool) or not 1 <= level <= 6:
        raise LiveError("bad_level", f"уровень заголовка — целое от 1 до 6, а не {level!r}")
    text = " ".join(str(text).split())
    if not text:
        raise LiveError("empty_value", "заголовок пустой: подставлять нечего")
    return Markdown("#" * level + " " + text)


def kind_of(value) -> str:
    """Вид значения одним словом из `KINDS`. Не догадка: тип значения известен точно
    (в шаблонном пути тип предлагается по метке и помечается `guessed` — здесь этого
    не бывает). Единственное, что смотрит внутрь, — заголовок против обычного markdown."""
    if isinstance(value, str):
        value = Text(value)
    if heading_level(value) is not None:
        return "heading"
    name = _KIND_BY_CLASS.get(type(value))
    if name is None or name not in KINDS:
        raise LiveError("unknown_kind",
                        f"значение вида {type(value).__name__} в живом списке не бывает; "
                        f"бывают: {', '.join(KINDS)}")
    return name


def block(key, value, *, label: str = "") -> Block:
    """Собрать блок: проверить ключ, определить вид, обернуть голую строку в `Text`."""
    if isinstance(value, str):
        value = Text(value)
    return Block(key=check_key(key), kind=kind_of(value), value=value, label=str(label).strip())


# ── операции над списком: каждая возвращает новый список ──────────────────────

_KEEP = object()


def insert(work: Work, b: Block, *, after: str | None = None,
           before: str | None = None) -> Work:
    """Вставить блок. Место называется **ключом соседа**, никогда индексом.

    Индекс сдвинется при первой вставке выше, и сдвинется молча: агент, назвавший
    место числом, попадёт не туда через ход. `after=None, before=None` — в конец
    (петля растит документ вниз, это обычный случай); `before=ключ` — перед соседом,
    так ставят оглавление и введение.
    """
    if after is not None and before is not None:
        raise LiveError("bad_place", "место задают одним из «after» и «before», а не обоими")
    if work.get(b.key) is not None:
        raise LiveError("duplicate_key",
                        f"блок {b.key!r} в списке уже есть: переписать его — "
                        "replace_block, а новый блок вставляется и без ключа")
    if after is not None:
        at = work.index(after) + 1
    elif before is not None:
        at = work.index(before)
    else:
        at = len(work.blocks)
    return Work(work.blocks[:at] + (b,) + work.blocks[at:])


def replace(work: Work, key: str, value=_KEEP, *, label=_KEEP) -> Work:
    """Новое значение (и метка) блока. Место в списке не меняется.

    Это «переделай этот блок»: соседи не пересчитываются — иначе точечная
    правка превращается в полный прогон. Прежний список цел, и вернуться к нему
    можно тем же движением, что и к любой другой правке.
    """
    i = work.index(key)
    old = work.blocks[i]
    if value is _KEEP and label is _KEEP:
        return work
    if value is _KEEP:
        new = _replace(old, label=str(label).strip())
    else:
        v = Text(value) if isinstance(value, str) else value
        new = Block(key=old.key, kind=kind_of(v), value=v,
                    label=old.label if label is _KEEP else str(label).strip())
    return Work(work.blocks[:i] + (new,) + work.blocks[i + 1:])


def remove(work: Work, key: str) -> Work:
    """Убрать блок. Дешевле перегенерации и модели не стоит вовсе.

    Единственное, за чем следить, — `{ref:}` на убранный блок: они станут «?» прямо
    в тексте отчёта. Ловит это `validate_work` кодом `unresolved_ref` **до** сборки,
    поэтому здесь отказа нет: убирать блок, на который ссылались, законно — сначала
    убрать, потом починить ссылку.
    """
    i = work.index(key)
    return Work(work.blocks[:i] + work.blocks[i + 1:])


def move(work: Work, key: str, *, after: str | None = None,
         before: str | None = None) -> Work:
    """Переставить блок. Место — ключ соседа; `after=None, before=None` — в конец."""
    if after is not None and before is not None:
        raise LiveError("bad_place", "место задают одним из «after» и «before», а не обоими")
    i = work.index(key)
    if after == work.blocks[i].key or before == work.blocks[i].key:
        raise LiveError("bad_place", f"блок {work.blocks[i].key!r} нельзя переставить "
                                     "относительно самого себя")
    b = work.blocks[i]
    rest = work.blocks[:i] + work.blocks[i + 1:]
    tail = Work(rest)
    if after is not None:
        at = tail.index(after) + 1
    elif before is not None:
        at = tail.index(before)
    else:
        at = len(rest)
    return Work(rest[:at] + (b,) + rest[at:])


def rename(work: Work, key: str, new_key: str) -> Work:
    """Переименовать блок вместе со всеми ссылками на него.

    Ключ это адрес, и голое переименование порвало бы `{ref:старый}` во всех соседних
    текстах и подписях — беда, ради которой ключ предлагалось вовсе не менять.
    Здесь она снята работой, а не запретом: ссылки переписываются тем же разбором
    (`markdown.REF_RE`), которым их читает `render`, и `ref=` у самого значения тоже.
    Что переименование **не** чинит — историю версий: она живёт в `orchestrator`,
    и перенести её отсюда нечем.
    """
    i = work.index(key)
    old = work.blocks[i].key
    new = check_key(new_key)
    if new == old:
        return work
    if work.get(new) is not None:
        raise LiveError("duplicate_key", f"блок {new!r} в списке уже есть")
    out = []
    for j, b in enumerate(work.blocks):
        value = _rewrite_refs(b.value, old, new)
        if j == i:
            out.append(Block(key=new, kind=b.kind, value=value, label=b.label))
        elif value is not b.value:
            out.append(_replace(b, value=value))
        else:
            out.append(b)
    return Work(tuple(out))


def outline(work: Work) -> list[dict]:
    """Заголовки списка по порядку: `[{key, level, text}]`.

    Оно же ответ на вопрос «нужно ли оглавление»: `assemble` его не выдумывает, блок
    вида `toc` ставит агент, а видит он для этого вот этот список.
    """
    return [{"key": b.key, "level": b.level, "text": b.text.lstrip("# ").strip()}
            for b in work.blocks if b.kind == "heading"]


# ── сборка: список блоков → DOCX ──────────────────────────────────────────────

def work_values(work: Work) -> dict:
    """Значения блоков как значения тегов: `{ключ: значение}`. То же, что уходит
    в `render` и в `build_report`; второго представления содержимого не заводится."""
    return {b.key: b.value for b in work.blocks}


def work_template(work: Work, *, profile=None, page=None, body=None,
                  page_numbers: bool = True) -> bytes:
    """Синтетический шаблон списка: пустой документ и по абзацу `{{ключ}}` на блок.

    Он и делает живой режим вторым режимом, а не вторым движком: дальше это обычный
    шаблон, и `render` с `build_report` работают с ним, ничего не зная о происхождении.
    Наружу (человеку, модели, в архив) он не показывается — это шов, а не документ.

    `profile` — оформление, снятое с образца человека (`sample.style_from_sample`);
    подписи из него едут отдельно, `render(style=profile.style_overrides())`, и об этом
    заботится `render_work`.
    """
    return document_bytes(_document(work, profile=profile, page=page, body=body,
                                    page_numbers=page_numbers))


def render_work(work: Work, *, style: dict | None = None, profile=None,
                page=None, body=None, page_numbers: bool = True,
                images_dir: str | None = None, on_error: str = "raise",
                drawio_timeout: float | None = None) -> RenderResult:
    """Список блоков → `RenderResult` (байты в `.data`, номера в `.refs`).

    Полный ответ сборки: сколько рисунков, таблиц, листингов и формул пронумеровано,
    какие `{ref:}` повисли, что не собралось при `on_error="skip"`. `assemble` — она же,
    но одними байтами: вызывающему, которому нужен только файл, разбирать результат незачем.
    """
    doc = _document(work, profile=profile, page=page, body=body, page_numbers=page_numbers)
    return render(doc, work_values(work), None, images_dir=images_dir,
                  style=_style(style, profile), on_error=on_error,
                  drawio_timeout=drawio_timeout)


def assemble(work: Work, *, style: dict | None = None, profile=None,
             page=None, body=None, page_numbers: bool = True,
             images_dir: str | None = None, on_error: str = "raise",
             drawio_timeout: float | None = None) -> bytes:
    """Документ из списка блоков. → байты DOCX.

    Она же «как будет в Word»: второго рисовальщика нет, кнопка предпросмотра считает
    ровно этот документ. Превью по ходу письма рисует интерфейс из того же списка —
    быстро и поблочно, но состав и порядок, а не вёрстку: поля, переносы и номера
    страниц считает Word, и обещать совпадение нельзя.
    """
    return render_work(work, style=style, profile=profile, page=page, body=body,
                       page_numbers=page_numbers, images_dir=images_dir,
                       on_error=on_error, drawio_timeout=drawio_timeout).data


def _document(work: Work, *, profile, page, body, page_numbers):
    kw = {}
    if page is not None:
        kw["page"] = page
    if body is not None:
        kw["body"] = body
    if profile is not None:
        kw.setdefault("page", profile.page)
        kw.setdefault("body", profile.body)
    doc = blank_document(page_numbers=page_numbers, **kw)
    if profile is not None:
        apply_style(doc, profile)
    seen = set()
    for n, b in enumerate(work.blocks):
        key = norm_key(b.key)
        if key in seen:
            raise LiveError("duplicate_key", f"ключ {key!r} в списке дважды: собрать такой "
                                             "список нельзя, второй блок затрёт первый")
        seen.add(key)
        para = doc.add_paragraph("{{" + key + "}}")
        # Закладка вокруг блока. Она едет дальше сама: сборка в PDF выгружает закладки
        # именованными назначениями, и превью по ним знает, где на странице начинается
        # каждый блок, — замечание человека адресуется прямо с вёрстки, а не по списку.
        # Читателю документа закладка не мешает: ни Word, ни LibreOffice её не рисуют,
        # поэтому второй сборки «для превью» не нужно — файл один и тот же.
        ops.mark_range(para._p, bookmark_name(key), ops.RANGE_BOOKMARK_ID + n)
    return doc


def _style(style: dict | None, profile) -> dict:
    """Перегрузки оформления: явные поверх снятых с образца. Забыть образец нельзя —
    подписи выйдут нашими, а не из образца, и половина работы пропадёт незаметно."""
    if profile is None:
        return dict(style or {})
    out = {k: dict(v) for k, v in profile.style_overrides().items()}
    for name, val in (style or {}).items():
        if isinstance(val, dict) and isinstance(out.get(name), dict):
            out[name] = {**out[name], **val}
        else:
            out[name] = val
    return out


# ── валидатор на списке ───────────────────────────────────────────────────────

def validate_work(work: Work, *, limits: dict | None = None) -> list[Problem]:
    """Список блоков до сборки → `[Problem]`. Те же сита, что у `validate` для тегов.

    Пустой список означает ровно одно: `assemble` соберёт из этих блоков документ,
    в котором нет ни «?» вместо номера, ни съеденного блока. Не бросает и на первой
    беде не останавливается: модель должна получить все замечания за один повтор,
    а человек — увидеть их разом.

    Сита и почему они здесь:
      `bad_key`, `duplicate_key` — ключ блока становится ключом тега, и два одинаковых
        ключа не спорят, а молча схлопываются (второй затирает первый);
      `unknown_kind`, `type_mismatch` — вид блока обязан отвечать значению: живой режим
        тем и хорош, что тип известен точно, и разойтись ему негде, кроме как здесь;
      `empty_value` — `render` считает пустое значение ошибкой, и знать о ней надо до
        сборки: «модель ничего не вернула» выглядит ровно как «блок написан»;
      `limit_exceeded` — потолки службы (`report.HARD_LIMITS`), счёт знаков и строк тот же;
      `unresolved_ref` — `{ref:}` мимо цели `render` превратит в «?» прямо в тексте
        отчёта, и видно это только глазами и только на готовом документе; в живом
        списке это **ошибка**, а не предупреждение: цель здесь видна точно
        (`ref_targets` знает, кто получит номер), а «?» в готовом документе хуже
        отказа собрать его.
    """
    limits = HARD_LIMITS if limits is None else {**HARD_LIMITS, **limits}
    out: list[Problem] = []
    seen: dict[str, int] = {}
    for i, b in enumerate(work.blocks):
        try:
            key = check_key(b.key)
        except LiveError as e:
            out.append(_p("error", "bad_key", str(b.key), str(e)))
            continue
        if key in seen:
            out.append(_p("error", "duplicate_key", key,
                          f"ключ {key!r} стоит у блоков {seen[key] + 1} и {i + 1} "
                          "(после нормализации NFC): второй затрёт первый",
                          expected=1, got=2))
            continue
        seen[key] = i
        out += _block_problems(b, key, limits)
    if len(work.blocks) > limits["max_values"]:
        out.append(_p("error", "limit_exceeded", None,
                      f"блоков {len(work.blocks)}, потолок {limits['max_values']} (max_values)",
                      expected=limits["max_values"], got=len(work.blocks)))
    out += _refs(work_values(work), ref_targets(work), what="блока", level="error",
                 labels={b.key: b.label for b in work.blocks})
    return out


def _block_problems(b: Block, key: str, limits: dict) -> list[Problem]:
    out: list[Problem] = []
    try:
        kind = kind_of(b.value)
    except LiveError as e:
        return [_p("error", "unknown_kind", key, str(e), got=type(b.value).__name__)]
    if b.kind != kind:
        out.append(_p("error", "type_mismatch", key,
                      f"блок {key!r} объявлен как {b.kind}, а значение — {kind}",
                      expected=b.kind, got=kind))
    if b.kind not in KINDS:
        out.append(_p("error", "unknown_kind", key,
                      f"вида {b.kind!r} не бывает; бывают: {', '.join(KINDS)}",
                      got=b.kind))
    if _empty_value(b.value):
        out.append(_p("error", "empty_value", key,
                      f"значение блока {key!r} пустое: подставлять нечего"))
        return out
    try:
        _check_value(key, b.value, limits)
    except _JobError as e:
        out.append(_p("error", e.code, key, str(e)))
    return out


def ref_targets(work: Work) -> dict:
    """Блоки, на которые ссылка вообще может указать: те, что получат номер. `{ключ: блок}`.

    Номер `render` заводит рисунку и схеме с подписью, таблице с подписью, листингу
    с подписью и нумерованной формуле (`_emit_image`, `_emit_table`, `_emit_code`,
    `_emit_formula`). Ссылка на абзац текста или на заголовок номера не получит — в
    документе на её месте встанет «?», и это отдельная беда от «блока с таким именем нет».

    Шаблонному режиму такой точности взять неоткуда: там тип тега объявлен манифестом,
    а подпись живёт в значении, которого во время проверки может и не быть. В живом
    списке значение есть всегда — потому здесь сито строже, а не слабее.
    """
    out = {}
    for b in work.blocks:
        v = b.value
        if isinstance(v, (Image, Diagram, Table)):
            numbered = v.caption is not False
        elif isinstance(v, Code):
            numbered = v.caption is not None          # у кода нет `false` (см. model.Code)
        elif isinstance(v, Formula):
            numbered = bool(v.numbered)
        else:
            numbered = False
        if numbered:
            out[b.key] = b
    return out


def unresolved_refs(work: Work) -> list[str]:
    """Имена, на которые ссылаются тексты и подписи, а номера за ними не стоит.

    Отдельно от `validate_work` затем, что после `remove` и `rename` это единственный
    вопрос, который интересно задать, — и задавать его вызывающий будет каждый ход.
    Уровень тот же, что у `validate_work`, — `error`: два ответа на вопрос «насколько
    это беда» разошлись бы молча.
    """
    return [str(p.got) for p in _refs(work_values(work), ref_targets(work),
                                      what="блока", level="error")
            if p.code == "unresolved_ref"]


# ── инструменты агента ────────────────────────────────────────────────────────

@dataclass(frozen=True)
class LiveTool:
    """Объявление инструмента: имя, описание для модели, JSON Schema аргументов.

    Свой датакласс, а не `llm.Tool`: `hokoku` соседей не импортирует, и живой режим
    обязан оставаться пригодным без всякого поставщика моделей. Оркестратор
    перекладывает эти три поля в свой `llm.Tool` одной строкой.
    """

    name: str
    description: str
    schema: dict = field(default_factory=dict)


def _obj(props: dict, required=()) -> dict:
    return {"type": "object", "properties": props, "required": list(required),
            "additionalProperties": False}


def any_block_value_schema() -> dict:
    """Схема любого значения блока — помеченное объединение по типам `wire`.

    Ровно то же, что уровень 3 даёт `set_tag`: у каждого варианта дискриминатор
    `type` с `const`, и такое `anyOf` строгий режим поставщика принимает, а
    `strictify` расширяет по веткам. `blocks` из объединения выброшен: список блоков
    внутри блока ничего не выражает сверх плоского списка — он и есть плоский список.
    """
    return {"anyOf": [value_schema(name, for_model=True)
                      for name in VALUE_TYPES if name != "blocks"]}


_AFTER = {"type": ["string", "null"],
          "description": "ключ блока, после которого вставить; null — в конец списка"}
_BEFORE = {"type": ["string", "null"],
           "description": "ключ блока, перед которым вставить; задают одно из after и before"}
_LABEL = {"type": ["string", "null"],
          "description": "короткая метка для человека, например «Постановка задачи»"}
_KEY = {"type": ["string", "null"],
        "description": "ключ нового блока — короткий адрес латиницей без пробелов "
                       "(b-07, alg1); null — служба выдаст сама и назовёт в ответе. "
                       "Название блока сюда не пишут, для него есть label"}


def live_tools() -> list[LiveTool]:
    """Объявления инструментов живого режима, в постоянном порядке.

    Постоянство не украшение: список едет в каждом запросе прогона и стоит в
    кэшируемом префиксе. Собирать его «по обстановке» значило бы платить за префикс
    заново на каждом ходу и менять правила игры посреди прогона.

    Набор выведен из двух правил, а не придуман. **Путей нет ни у одного аргумента**:
    место называется ключом соседнего блока, картинка и схема — идентификатором
    артефакта. **Значение проходит тот же валидатор**, что и правка человека: второго
    пути записи не заводится, иначе появилось бы содержимое, попавшее в отчёт мимо
    проверки.

    Заголовок отдельным инструментом не сделан: это значение `{"type": "markdown",
    "text": "## Название"}`, и `list_blocks` покажет его видом `heading`. Инструмент
    на каждый вид значения (`insert_table`, `insert_picture`, …) обошёлся бы девятью
    почти одинаковыми объявлениями в кэшируемом префиксе — а тип и так известен точно,
    он стоит полем `type` самого значения.
    """
    value = any_block_value_schema()
    return [
        LiveTool(name="insert_block", description=(
            "Вставить блок в работу. Место называется ключом соседнего блока: after — "
            "после него, before — перед ним, ни того ни другого — в конец. Индексы не "
            "принимаются: они сдвигаются при первой же вставке выше. Значение — объект "
            "с полем type (text, markdown, code, image, table, diagram, formula, toc, "
            "page_break); заголовок раздела — это markdown из одной строки «## Название». "
            "Ключ не обязателен: не назовёшь — служба выдаст его сама и напишет в "
            "ответе. Ключ — это короткий адрес латиницей без пробелов (b-07), а "
            "название блока идёт в label; названный ключ, который адресом быть не "
            "может, служба заменит своим и скажет об этом. "
            "Возвращает ключ созданного блока — им и адресуй то, что сделал."),
            schema=_obj({"key": _KEY, "after": _AFTER, "before": _BEFORE, "value": value,
                         "label": _LABEL}, required=["value"])),
        LiveTool(name="replace_block", description=(
            "Заменить значение блока, не трогая его место в работе. Это «переделай этот "
            "блок»: соседи не пересчитываются. Значение проверяется тем же валидатором, "
            "что и правка человека, — отказ приходит с перечнем замечаний, поправь и "
            "повтори."),
            schema=_obj({"key": {"type": "string", "description": "ключ блока из list_blocks"},
                         "value": value, "label": _LABEL}, required=["key", "value"])),
        LiveTool(name="remove_block", description=(
            "Убрать блок из работы. В ответе unresolved_refs — имена, ссылки на которые "
            "остались висеть после удаления: в документе на их месте будет «?». Почини "
            "их, прежде чем идти дальше."),
            schema=_obj({"key": {"type": "string"}}, required=["key"])),
        LiveTool(name="move_block", description=(
            "Переставить блок. Место называется ключом соседа: after — после него, "
            "before — перед ним, ни того ни другого — в конец. Содержимое не меняется, "
            "номера рисунков и таблиц пересчитаются сами при сборке."),
            schema=_obj({"key": {"type": "string"}, "after": _AFTER, "before": _BEFORE},
                        required=["key"])),
        LiveTool(name="list_blocks", description=(
            "Состав работы по порядку: ключ, вид, уровень заголовка, метка, подпись и "
            f"первые {PREVIEW_CHARS} знаков содержимого. Содержимого целиком не отдаёт — "
            "оно тебе не нужно, чтобы опознать блок. Аргументов нет."),
            schema=_obj({})),
    ]


TOOL_NAMES = ("insert_block", "replace_block", "remove_block", "move_block", "list_blocks")


def call_tool(work: Work, name: str, args: dict | None = None, *,
              resolve_artifact=None) -> tuple[Work, dict]:
    """Позвать инструмент по имени. → (новый список, ответ модели).

    Чистая: `work` не меняется, новый список возвращается первым. Хранение, версии и
    журнал — дело вызывающего (`orchestrator`), и знать о них здесь нечего.

    Беда инструмента — `LiveError` с готовым `payload`: вызывающий отдаёт его модели
    как `is_error`, и прогон продолжается. Модель, получившая внятный отказ, чинится
    следующим ходом, а упавший прогон стоит всех уже потраченных денег.

    `resolve_artifact(id) -> bytes` обязателен, если значение содержит `artifact`
    (картинка, схема): путей в аргументах нет ни одного, байты достаёт вызывающий.
    """
    args = {} if args is None else args
    if not isinstance(args, dict):
        raise LiveError("bad_args", f"аргументы инструмента — объект, а не {type(args).__name__}")
    handler = _HANDLERS.get(name)
    if handler is None:
        raise LiveError("unknown_tool", f"инструмента {name!r} нет"
                                        f"{_hint(name, TOOL_NAMES)}", known=list(TOOL_NAMES))
    known = _ARGS[name]
    for arg in args:
        if arg not in known:
            raise LiveError("unknown_argument",
                            f"у {name} нет аргумента {arg!r}{_hint(arg, known)}",
                            known=list(known))
    return handler(work, args, resolve_artifact)


def _place(args: dict) -> dict:
    after, before = args.get("after"), args.get("before")
    if after is not None and before is not None:
        raise LiveError("bad_place", "место задают одним из «after» и «before», а не обоими")
    return {"after": after, "before": before}


def _value_arg(args: dict, resolve_artifact):
    raw = args.get("value")
    if not isinstance(raw, dict):
        raise LiveError("bad_value", 'аргумент "value" — объект с полем "type"')
    try:
        return value_from_json(raw, resolve_artifact=resolve_artifact)
    except WireError as e:
        raise LiveError("bad_value", e.detail) from None


def _t_insert(work: Work, args: dict, resolve_artifact):
    value = _value_arg(args, resolve_artifact)
    key, label, note = _insert_key(work, args.get("key"), args.get("label") or "")
    b = block(key, value, label=label)
    out = insert(work, b, **_place(args))
    answer = {"key": b.key, "kind": b.kind, "blocks": len(out)}
    return out, ({**answer, "note": note} if note else answer)


def _insert_key(work: Work, raw, label: str) -> tuple[str, str, str]:
    """Ключ нового блока: названный, если он годен тегом, иначе свой.

    → `(ключ, метка, что сказать в ответе)`.

    Отказать за форму ключа при вставке нельзя, и это решение, а не послабление.
    Ключ вставляющему не нужен вовсе — он приходит ему в ответе, — а вставка,
    отклонённая из-за пробела в придуманном имени, стоит хода и часто стоит
    самого блока: написанное бросают и идут дальше, а раздел работы остаётся
    пустым. Поэтому негодный ключ заменяется своим, и в ответе прямо сказано,
    под каким адресом блок встал: молча подменённый адрес хуже отказа — по нему
    потом ставят `{ref:}`.

    Негодный ключ — это почти всегда название («Схема 1: сортировка»). Если
    метки не дали, оно ею и становится: выбрасывать единственное, чем человек
    узнаёт блок, ради формы адреса незачем.

    Годный, но уже занятый ключ здесь не разбирается: «блок с таким адресом
    есть» — это или опечатка, или попытка переписать чужой блок вставкой, и
    отвечает на неё `insert` отказом с именем нужного инструмента.
    """
    key = str(raw or "").strip()
    if not key:
        свой = new_key(work)
        return свой, label, f"ключ выдан службой: {свой} — им и адресуй этот блок"
    try:
        return check_key(key), label, ""
    except LiveError as exc:
        свой = new_key(work)
        return свой, (label or key), (f"{exc}. Блок вставлен под ключом {свой} — "
                                      "им и адресуй его")


def _t_replace(work: Work, args: dict, resolve_artifact):
    key = _key_arg(work, args)
    value = _value_arg(args, resolve_artifact)
    label = args.get("label")
    out = replace(work, key, value, **({} if label is None else {"label": label}))
    return out, {"key": key, "kind": out.get(key).kind}


def _t_remove(work: Work, args: dict, resolve_artifact):
    key = _key_arg(work, args)
    out = remove(work, key)
    return out, {"removed": key, "blocks": len(out), "unresolved_refs": unresolved_refs(out)}


def _t_move(work: Work, args: dict, resolve_artifact):
    key = _key_arg(work, args)
    out = move(work, key, **_place(args))
    return out, {"key": key, "order": out.keys()}


def _t_list(work: Work, args: dict, resolve_artifact):
    return work, {"blocks": list_blocks(work)}


_HANDLERS = {"insert_block": _t_insert, "replace_block": _t_replace,
             "remove_block": _t_remove, "move_block": _t_move, "list_blocks": _t_list}
_ARGS = {t.name: tuple(t.schema.get("properties") or ()) for t in live_tools()}


def _key_arg(work: Work, args: dict) -> str:
    key = args.get("key")
    if not isinstance(key, str) or not key.strip():
        raise LiveError("bad_args", 'аргумент "key" — ключ блока из list_blocks')
    work.index(key)                                  # неизвестный ключ — с подсказкой
    return norm_key(key)


def list_blocks(work: Work) -> list[dict]:
    """Описание списка для модели и интерфейса: ключи, виды, метки, подписи, начало текста.

    Содержимого целиком не отдаёт намеренно. Модели документ не нужен — ей нужно
    опознать блок, — а отдать ей документ значит отдать OOXML и весь отчёт в окно
    на каждом ходу.
    """
    out = []
    for b in work.blocks:
        item = {"key": b.key, "kind": b.kind, "label": b.label,
                "preview": _preview(b), "chars": len(b.text)}
        if b.level is not None:
            item["level"] = b.level
        if b.caption is not None:
            item["caption"] = b.caption
        if b.ref != b.key:
            item["ref"] = b.ref
        out.append(item)
    return out


def _preview(b: Block) -> str:
    text = " ".join(b.text.split())
    return text if len(text) <= PREVIEW_CHARS else text[:PREVIEW_CHARS - 1] + "…"


# ── связный текст одним проходом ──────────────────────────────────────────────

def text_slots(work: Work) -> list[dict]:
    """Текстовые блоки, в которые ещё нечего показать. → `[{key, label, before, after}]`.

    Скелет работы, таблицы, код и схемы набираются петлёй по блокам, а **весь связный
    текст пишется одним проходом** по готовому списку, видя соседей. Иначе абзацы,
    написанные по одному, разойдутся между собой.

    Место под текст — блок вида text или markdown, значение которого пусто или начинается
    с пометки «черновик:». Пустым буквально его оставить нельзя: пустое значение `render`
    считает ошибкой, и список не собрался бы даже для показа человеку.

    Заготовка, ждущая инструмента («черновик diagram: …»), местом под текст **не**
    считается: схему прозой не напишешь, а написанная поверх неё проза выглядит
    готовым разделом, и человек узнаёт о пропаже схемы из готового отчёта.
    Такие заготовки отдаёт `tool_slots`.

    `before` и `after` — соседи одной строкой: это и есть «видя соседей», в схеме ответа
    они уезжают в `description` каждого ключа.
    """
    out = []
    for i, b in enumerate(work.blocks):
        if not _is_slot(b):
            continue
        before = work.blocks[i - 1] if i else None
        after = work.blocks[i + 1] if i + 1 < len(work.blocks) else None
        out.append({"key": b.key, "kind": b.kind, "label": b.label,
                    "hint": draft_hint(b.text),
                    "before": _describe(before), "after": _describe(after)})
    return out


def tool_slots(work: Work) -> list[dict]:
    """Заготовки, которых ждёт инструмент. → `[{key, kind, label, hint, section}]`.

    То же место в списке, что и `text_slots`, но с другой стороны черты: здесь
    разделы, где должны стоять схема, код, таблица, картинка или формула, а
    стоит пока черновик с названным видом. Спрашивают об этом после петли: что
    осталось заготовкой, то либо доделывается ещё одним заданием, либо честно
    называется человеку — «схемы в разделе нет».

    `section` — заголовок раздела, в котором заготовка стоит: человеку она
    называется разделом, а не ключом блока.
    """
    out, section = [], ""
    for b in work.blocks:
        if b.kind == "heading":
            section = b.text.lstrip("# ").strip()
            continue
        kind = draft_kind(b.text) if b.kind in TEXT_KINDS else ""
        if kind:
            out.append({"key": b.key, "kind": kind, "label": b.label,
                        "hint": draft_hint(b.text), "section": section})
    return out


def _is_slot(b: Block) -> bool:
    if b.kind not in TEXT_KINDS:
        return False
    text = b.text.strip()
    return (not text or is_draft_text(text)) and not draft_kind(text)


def draft_mark(kind: str = "") -> str:
    """Пометка черновика: «черновик:» под текст, «черновик diagram:» под инструмент."""
    kind = str(kind or "").strip().lower()
    # Заголовок и текст пометки вида не получают: заголовок ставит скелет, а
    # текст пишет проход текста — обоим вид в пометке сказал бы, что раздел ждёт
    # инструмента, которого для них нет.
    return (DRAFT_MARK if not kind or kind in TEXT_KINDS or kind == "heading"
            else f"черновик {kind}:")


def is_draft_text(text) -> bool:
    """Не написан ли ещё блок: пусто или пометка черновика — с видом или без."""
    text = str(text or "").strip()
    return not text or _DRAFT_RE.match(text) is not None


def draft_kind(text) -> str:
    """Вид содержимого, которого ждёт заготовка («diagram»), или пусто для текста.

    Не догадка по словам подсказки, а то, что записал автор скелета
    (`draft(hint, kind=…)`). Слово, которого нет среди видов, видом не
    считается: приняв за вид опечатку, мы вынули бы раздел из прохода текста, и
    он остался бы черновиком в готовой работе.
    """
    m = _DRAFT_RE.match(str(text or "").strip())
    kind = (m.group(1) or "").lower() if m else ""
    return kind if kind in KINDS and kind not in TEXT_KINDS and kind != "heading" else ""


def draft_hint(text) -> str:
    """Что автор скелета написал в черновике: «черновик: сравнить два способа»."""
    text = str(text or "").strip()
    m = _DRAFT_RE.match(text)
    return text[m.end():].strip() if m else ""


def _describe(b: Block | None) -> str:
    if b is None:
        return ""
    what = f"{b.kind} {b.key}"
    if b.label:
        what += f" «{b.label}»"
    preview = _preview(b)[:60]
    return f"{what}: {preview}" if preview else what


def draft(hint: str = "", *, kind: str = "", markdown: bool = True):
    """Заготовка раздела: черновик с пометкой, что в нём должно быть.

    Пометка не украшение — она едет в промпт текстового прохода (`text_slots`→`hint`),
    и без неё модель, пишущая весь текст разом, знает про блок только имя соседей.

    `kind` — вид содержимого, если раздел заполняет инструмент, а не текст
    (`diagram`, `code`, `table`, `image`, `formula`). Он встаёт в саму пометку, и
    по нему такая заготовка выпадает из мест под текст: проза, написанная поверх
    места под схему, выглядит готовым разделом, а схемы в работе нет.
    """
    mark = draft_mark(kind)
    hint = str(hint).strip() or ("написать" if mark == DRAFT_MARK
                                 else f"поставить сюда: {kind}")
    text = f"{mark} {hint}"
    return Markdown(text) if markdown else Text(text)


def texts_schema(work: Work) -> dict:
    """Строгая схема ответа текстового прохода: `{ключ блока: написанный текст}`.

    Ключи — только места под текст (`text_slots`), и все обязательны: схема,
    попросившая то, чего у модели никто не спрашивал, получает выдумку, а токены на
    неё тратятся настоящие. Порядок ключей — порядок документа: модель заполняет
    объект по порядку, значит первые закрывшиеся значения — начало работы, и
    частичный ответ при обрыве осмыслен, а не случаен.

    `description` каждого ключа — метка блока и соседи: это и есть «видя соседей».
    """
    slots = text_slots(work)
    if not slots:
        raise LiveError("nothing_to_write",
                        "нечего писать: пустых текстовых блоков в работе нет")
    props = {}
    for s in slots:
        parts = [p for p in (s["label"], s["hint"]) if p]
        if s["before"]:
            parts.append(f"перед — {s['before']}")
        if s["after"]:
            parts.append(f"после — {s['after']}")
        props[s["key"]] = {"type": "string", "minLength": 1,
                           "description": "; ".join(parts) or "связный текст блока"}
    return _obj(props, required=list(props))


def fill_texts(work: Work, texts: dict) -> Work:
    """Вписать написанный одним проходом текст в свои блоки. → новый список.

    Нетекстовых блоков не трогает — и не молча: ключ, указывающий на таблицу или
    схему, это отказ с именами всех таких ключей сразу. Молча пропущенный ключ здесь
    хуже отказа: текст, который модель написала и за который заплачено, просто исчез
    бы, а обнаружилось бы это на готовом отчёте по пустому разделу.

    Вид блока сохраняется: в `markdown` кладётся `Markdown`, в `text` — `Text`.
    Готовое значение (`Markdown`/`Text`) принимается как есть — тогда вид берётся у него.
    """
    if not isinstance(texts, dict):
        raise LiveError("bad_args", f"тексты — объект «ключ: текст», а не {type(texts).__name__}")
    unknown, wrong, empty = [], [], []
    ready = {}
    for raw_key, val in texts.items():
        key = norm_key(str(raw_key))
        b = work.get(key)
        if b is None:
            unknown.append(key)
            continue
        if b.kind not in TEXT_KINDS:
            wrong.append(f"{key} ({b.kind})")
            continue
        value = val if isinstance(val, (Text, Markdown)) else (
            Markdown(str(val)) if b.kind == "markdown" else Text(str(val)))
        if _empty_value(value):
            empty.append(key)
            continue
        ready[key] = value
    if unknown or wrong or empty:
        parts = []
        if unknown:
            parts.append("нет таких блоков: " + ", ".join(unknown))
        if wrong:
            parts.append("не текстовые блоки: " + ", ".join(wrong))
        if empty:
            parts.append("пустой текст: " + ", ".join(empty))
        raise LiveError("bad_texts", "; ".join(parts), known=[b.key for b in work.blocks
                                                              if b.kind in TEXT_KINDS])
    out = tuple(_replace(b, value=ready[b.key], kind=kind_of(ready[b.key]))
                if b.key in ready else b for b in work.blocks)
    return Work(out)


# ── мелочи ────────────────────────────────────────────────────────────────────

def _text_of(v) -> str:
    """Написанный текст значения — то, что показывают в превью и меряют в знаках."""
    if isinstance(v, str):
        return v
    if isinstance(v, (Text, Markdown, Code)):
        return v.text
    if isinstance(v, Formula):
        return v.latex
    if isinstance(v, Table):
        return " | ".join(str(c) for c in (v.rows[0] if v.rows else []))
    if isinstance(v, (Image, Diagram)):
        return v.caption if isinstance(v.caption, str) else ""
    if isinstance(v, Toc):
        return v.title or ""
    if isinstance(v, Blocks):
        return "\n".join(_text_of(i) for i in v.items)
    return ""


def _map_refs(v, sub, *, own=None):
    """Пройти по всем местам значения, где `render` читает `{ref:}`, и переписать их.

    Мест этих четыре с половиной (текст, подпись, ячейки таблицы, заголовок
    оглавления и `ref=` самого значения), и перечислены они один раз: и
    переименование, и снятие ссылки обязаны знать один и тот же список — иначе
    одно из двух починит не все ссылки, а какие именно, выяснится по «?» в
    готовом документе.

    `own` — что сделать с именем, которое значение назначило себе само (`ref=`).
    Оно не ссылка, а цель, и трогать его вправе только переименование.
    """
    changed = {}
    # текст листинга не трогаем: `{ref:x}` в коде программы — текст программы, и render
    # его не разбирает; подпись листинга — разбирает, и она ниже вместе с прочими
    if isinstance(v, (Text, Markdown)) and sub(v.text) != v.text:
        changed["text"] = sub(v.text)
    if isinstance(v, (Image, Diagram, Table, Code)) and isinstance(v.caption, str):
        if sub(v.caption) != v.caption:
            changed["caption"] = sub(v.caption)
    if isinstance(v, Table):
        rows = [[sub(str(c)) for c in row] for row in v.rows]
        if rows != v.rows:
            changed["rows"] = rows
    if isinstance(v, Toc) and isinstance(v.title, str) and sub(v.title) != v.title:
        changed["title"] = sub(v.title)
    if own is not None:
        имя = getattr(v, "ref", None)
        if isinstance(имя, str) and own(имя) != имя:
            changed["ref"] = own(имя)
    if isinstance(v, Blocks):
        items = [_map_refs(i, sub, own=own) for i in v.items]
        if any(a is not b for a, b in zip(items, v.items)):
            changed["items"] = items
    return _replace(v, **changed) if changed else v


def _rewrite_refs(v, old: str, new: str):
    """`{ref:старый}` → `{ref:новый}` в текстах, подписях и `ref=` значения.

    Разбор тот же (`markdown.REF_RE`), которым ссылку читает `render`: своя регулярка
    разошлась бы с ним, и переименование чинило бы не все ссылки — а какие именно,
    выяснялось бы по «?» в готовом документе.
    """
    return _map_refs(
        v,
        lambda text: REF_RE.sub(
            lambda m: "{ref:" + (new if m.group(1) == old else m.group(1)) + "}", text),
        own=lambda имя: new if имя == old else имя)


# Ссылка вместе с пробелами перед ней: «см. рисунок {ref:x} и таблицу» без них
# оставило бы двойной пробел, а «Замеры {ref:x}» — висящий хвост. Пробелы после
# ссылки не трогаются: за ней обычно стоит знак препинания, и съеденный пробел
# склеил бы слова.
_ССЫЛКА_С_ОТСТУПОМ = re.compile(r"[ \t]*" + REF_RE.pattern)


def strip_refs(work: Work, names) -> Work:
    """Убрать из текстов и подписей ссылки на названные имена. → новый список блоков.

    Нужно это ровно там, где ссылка ведёт в никуда, а документ всё равно обязан
    собраться: блок остаётся с текстом, но без ссылки. Выбор между «не собрать
    работу вовсе» и «оставить абзац без номера рисунка» решён в пользу второго —
    отказ собрать стоит человеку всего прогона, а пропавшая ссылка видна и
    чинится правкой одного блока.

    Убирается только сама ссылка. Ни текст вокруг, ни `ref=` самого значения
    (это цель, а не ссылка) не трогаются: снятие ссылки не должно менять смысл
    соседнего предложения.
    """
    имена = {str(n) for n in names or ()}
    if not имена:
        return work

    def sub(text: str) -> str:
        return _ССЫЛКА_С_ОТСТУПОМ.sub(
            lambda m: "" if m.group(1) in имена else m.group(0), text)

    blocks = []
    for b in work.blocks:
        value = _map_refs(b.value, sub)
        blocks.append(b if value is b.value else _replace(b, value=value))
    return Work(tuple(blocks))


def _p(level: str, code: str, key: str | None, message: str, *, expected=None, got=None) -> Problem:
    return Problem(module="hokoku", level=level, code=code, key=key, message=message,
                   expected=expected, got=got)


def _hint(name, known) -> str:
    import difflib
    near = difflib.get_close_matches(str(name), sorted(str(k) for k in known), n=1, cutoff=0.6)
    return f' (похоже на "{near[0]}")' if near else ""


__all__ = [
    "Block", "Work", "LiveTool", "LiveError", "KINDS", "TEXT_KINDS", "DRAFT_MARK",
    "PREVIEW_CHARS", "TOOL_NAMES",
    "block", "check_key", "new_key", "heading", "heading_level", "kind_of", "draft",
    "draft_mark", "draft_kind", "draft_hint", "is_draft_text",
    "insert", "replace", "remove", "move", "rename", "outline",
    "work_values", "work_template", "render_work", "assemble",
    "validate_work", "unresolved_refs", "strip_refs",
    "live_tools", "call_tool", "list_blocks", "any_block_value_schema",
    "text_slots", "tool_slots", "texts_schema", "fill_texts",
]
