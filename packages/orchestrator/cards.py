"""cards — дверь к тренажёру карточек: ядро разбора, набор на томе, черновики.

Ядро (`cards`) — чистые функции над текстом и неизменяемыми записями: файл JSON
или таблица CSV на входе, `CardSet` и перечень проблем на выходе, план захода по
прогрессу. Оно
не знает ни про том, ни про базу, ни про модель. Служба же не знает ни одного
пути на томе и ядро по имени не импортирует — тем же разрезом, что доска зовёт
`kokuban` через `orchestrator.board`. Эта дверь держит три вещи:

* **проход к ядру.** Разбор, запись, сравнение версий и план захода — ровно по
  договору ядра, без своих решений;
* **набор на томе.** Набор — решение неявной работы «Тренажёр» (запись журнала
  `module: "cards"` и каталог решения). Исходный `.json` каждой версии лежит
  артефактом работы (адресуется содержимым, историю даёт перечень версий), а
  разобранный канонический набор — файлом `cards/v<n>.json` в каталоге
  решения. Файл версии создаётся, а не заменяется: две вкладки, заменившие
  набор разом, получат одна версию, другая — отказ, а не молча затёртую
  замену. Хранятся два последних канонических файла: текущий и предыдущий,
  на случай чтения, начатого до замены;
* **черновики.** Каталог черновиков человека (`cards-drafts/<id>/`) рядом с его
  проектами: текст файла JSON набора и запись о черновике. Черновик всегда JSON:
  таблица CSV переводится в файл JSON при создании черновика, вместе с
  карточками, которые не прошли проверку, — их человек правит в черновике.
  Черновик живёт семь дней с последней записи; уборка идёт при обращении к
  черновикам того же человека.

Канонический набор на томе — не файл набора, а записи ядра как есть: ключи
карточек, id тем, только годные карточки. Читают его на каждом открытии набора и
захода, и разбор файла с проверкой на каждый запрос стоил бы времени, а главное —
давал бы ответ, зависящий от версии разборщика.

Файлы Markdown (прежний формат набора) не читаются: загрузка `.md` — отказ, а
черновик, записанный Markdown, узнаётся по имени файла текста (`outdated`).
"""
from __future__ import annotations

import dataclasses
import datetime
import json
import os
import re
import secrets
import shutil
import uuid

import cards as ядро

from .errors import OrchestratorError

# ── проход к ядру ────────────────────────────────────────────────────────────

ORDERS = tuple(ядро.ORDERS)
INCLUDE = tuple(ядро.INCLUDE)
CardSet = ядро.CardSet
Card = ядро.Card
Topic = ядро.Topic
Defaults = ядро.Defaults
Problem = ядро.Problem


def read_json(data, *, filename: str = ""):
    """Файл JSON → `(CardSet | None, [Problem])`. Проход к ядру."""
    return ядро.read_json(data, filename=filename)


def read_csv(text: str, delimiter: str | None = None):
    """CSV/TSV → `(CardSet | None, [Problem])`. Проход к ядру."""
    return ядро.read_csv(text, delimiter)


def write_json(s) -> str:
    """Набор → канонический файл JSON с id у каждой карточки. Проход к ядру."""
    return ядро.write_json(s)


def validate(s) -> list:
    """Один валидатор на все входы. Проход к ядру."""
    return list(ядро.validate(s))


def diff(old, new) -> dict:
    """`{added, changed, removed}` по ключам карточек. Проход к ядру."""
    return dict(ядро.diff(old, new))


def card_markdown(c) -> str:
    """Карточка → Markdown для «Скопировать». Проход к ядру."""
    return ядро.card_markdown(c)


def plan_session(s, last: dict, *, size, order: str, topics, include: str,
                 seed: int) -> list[str]:
    """Ключи захода по порядку. Проход к ядру."""
    return list(ядро.plan_session(s, last, size=size, order=order,
                                  topics=topics, include=include, seed=seed))


# Расширения, которые читаются как таблица, а не как файл JSON.
# Разделитель таблицы по расширению. У `.csv` его нет: разделитель берётся из
# строки Anki `#separator:` или по первой строке (табуляция, `;`, `,`) — Excel в
# русской локали и Quizlet пишут `.csv` через точку с запятой.
ТАБЛИЧНЫЕ = {".csv": None, ".tsv": "\t"}

# Расширения прежнего формата набора: такие файлы не читаются.
MARKDOWN = (".md", ".markdown")


def _расширение(filename: str) -> str:
    return os.path.splitext(str(filename or ""))[1].lower()


def markdown_name(filename: str) -> bool:
    """Имя файла прежнего формата Markdown."""
    return _расширение(filename) in MARKDOWN


def parse(text: str, filename: str = "") -> tuple:
    """Загруженный файл → `(CardSet | None, [Problem])` по расширению имени.

    `.csv`/`.tsv` — таблица, `.md` — одна проблема «формат больше не
    поддерживается», остальное — файл JSON. Разборщики ядра сами проверяют
    карточки теми же правилами, что валидатор, и отклонённые в набор не кладут;
    `card` у их проблем — номер карточки в источнике. Валидатор здесь не
    зовётся: его номера — номера в готовом наборе, и сведённые в один перечень
    они посчитали бы отклонённым то, что в набор вошло. Валидатор нужен набору,
    собранному не из текста (`merge`).
    """
    расширение = _расширение(filename)
    if расширение in ТАБЛИЧНЫЕ:
        набор, проблемы = read_csv(text, ТАБЛИЧНЫЕ[расширение])
    elif расширение in MARKDOWN:
        return None, [Problem(None, "markdown_unsupported",
                              "формат Markdown больше не поддерживается: набор "
                              "карточек — файл JSON (docs/cards-format.md)")]
    else:
        набор, проблемы = read_json(text, filename=filename)
    return набор, _без_повторов(list(проблемы or ()))


def parse_draft(text: str, filename: str = "") -> tuple:
    """Текст черновика → `(CardSet | None, [Problem])`. Черновик всегда JSON;
    `filename` — только запасное название набора."""
    набор, проблемы = read_json(text, filename=filename)
    return набор, _без_повторов(list(проблемы or ()))


def draft_text(text: str, filename: str = "") -> str:
    """Загруженный файл → текст черновика: таблица — файлом JSON со всеми
    карточками строк, файл JSON — как пришёл."""
    расширение = _расширение(filename)
    if расширение in ТАБЛИЧНЫЕ:
        return ядро.csv_json(text, ТАБЛИЧНЫЕ[расширение], filename=filename)
    return text


def _без_повторов(проблемы) -> list:
    виденные, out = set(), []
    for п in проблемы:
        ключ = (getattr(п, "line", None), getattr(п, "code", ""),
                getattr(п, "text", ""), getattr(п, "card", None))
        if ключ not in виденные:
            виденные.add(ключ)
            out.append(п)
    return out


def problem_json(п) -> dict:
    """Проблема разбора наружу: `{line, column, code, text, card, path}`.

    `card` — номер карточки в источнике с нуля: такая карточка отклонена и в
    набор не вошла. `None` — проблема файла целиком. `path` — путь поля в файле
    JSON (`cards[12].a`), `line` — строка битого JSON или таблицы CSV, `column` —
    столбец в этой строке у битого JSON.
    """
    строка = getattr(п, "line", None)
    столбец = getattr(п, "column", None)
    карточка = getattr(п, "card", None)
    путь = getattr(п, "path", None)
    return {"line": int(строка) if isinstance(строка, int) else None,
            "column": int(столбец) if isinstance(столбец, int) else None,
            "code": str(getattr(п, "code", "") or ""),
            "text": str(getattr(п, "text", "") or ""),
            "card": int(карточка) if isinstance(карточка, int) else None,
            "path": str(путь) if путь else None}


def rejected(проблемы) -> int:
    """Сколько карточек источника отклонено: разных `card` у проблем."""
    return len({п.card for п in проблемы or ()
                if isinstance(getattr(п, "card", None), int)})


# ── набор ↔ JSON ─────────────────────────────────────────────────────────────

def _поля(класс, данные: dict) -> dict:
    """Только те поля записи, которые у класса ядра есть."""
    имена = {f.name for f in dataclasses.fields(класс)}
    return {k: v for k, v in (данные or {}).items() if k in имена}


def set_json(s) -> dict:
    """`CardSet` → JSON. Поля берутся у записей ядра, какие есть."""
    return {
        "title": s.title, "description": s.description, "language": s.language,
        "topics": [dataclasses.asdict(t) for t in s.topics],
        "cards": [dataclasses.asdict(c) for c in s.cards],
        "defaults": dataclasses.asdict(s.defaults),
    }


def set_from_json(данные: dict):
    """JSON → `CardSet`. Лишние поля пропускаются, недостающие берут умолчание."""
    d = dict(данные or {})
    умолчания = _поля(Defaults, d.get("defaults") or {})
    if isinstance(умолчания.get("topics"), list):
        умолчания["topics"] = list(умолчания["topics"])
    return CardSet(
        title=str(d.get("title") or ""),
        description=str(d.get("description") or ""),
        language=str(d.get("language") or ""),
        topics=[Topic(**_поля(Topic, t)) for t in d.get("topics") or ()
                if isinstance(t, dict)],
        cards=[Card(**_поля(Card, c)) for c in d.get("cards") or ()
               if isinstance(c, dict)],
        defaults=Defaults(**умолчания))


def with_identity(s, *, title: str | None = None,
                  description: str | None = None, defaults: dict | None = None):
    """Тот же набор с другим названием, описанием или рекомендуемыми настройками."""
    правки: dict = {}
    if title is not None:
        правки["title"] = title
    if description is not None:
        правки["description"] = description
    if defaults is not None:
        правки["defaults"] = dataclasses.replace(
            s.defaults, **_поля(Defaults, defaults))
    return dataclasses.replace(s, **правки) if правки else s


def merge(old, new) -> tuple:
    """Дополнить набор карточками другого. → `(набор, добавлено, пропущено)`.

    Карточка с ключом, который в наборе уже есть, пропускается: дополнение не
    переписывает карточки, для этого есть замена файлом. Темы сводятся по
    идентификатору — сперва темы набора в их порядке, потом новые.
    """
    ключи = {c.key for c in old.cards}
    добавлено, пропущено = [], []
    for c in new.cards:
        if c.key in ключи:
            пропущено.append(c.key)
            continue
        ключи.add(c.key)
        добавлено.append(c)
    темы = list(old.topics)
    есть = {t.id for t in темы}
    нужные = {c.topic for c in добавлено if c.topic}
    for t in new.topics:
        if t.id not in есть and t.id in нужные:
            есть.add(t.id)
            темы.append(t)
    итог = dataclasses.replace(old, topics=темы, cards=list(old.cards) + добавлено)
    return итог, [c.key for c in добавлено], пропущено


# ── набор на томе ────────────────────────────────────────────────────────────

ПАПКА_НАБОРА = "cards"
_ВЕРСИЯ_RE = re.compile(r"^v(\d+)\.json$")
ХРАНИТЬ_ВЕРСИЙ = 2


def _папка(project) -> str:
    if not project.solution:
        raise OrchestratorError("набор карточек живёт в решении, а решение не открыто")
    return os.path.join(project.doc_path(), ПАПКА_НАБОРА)


def versions(project) -> list[int]:
    """Номера канонических файлов набора по возрастанию. Пусто — набора нет."""
    папка = _папка(project)
    if not os.path.isdir(папка):
        return []
    return sorted(int(m.group(1)) for m in map(_ВЕРСИЯ_RE.match, os.listdir(папка))
                  if m)


def read_set(project) -> tuple[int, object | None]:
    """Текущая версия и канонический набор. `(0, None)` — набора ещё нет."""
    номера = versions(project)
    if not номера:
        return 0, None
    путь = os.path.join(_папка(project), f"v{номера[-1]}.json")
    try:
        with open(путь, encoding="utf-8") as f:
            return номера[-1], set_from_json(json.load(f))
    except (OSError, ValueError, TypeError) as беда:
        raise OrchestratorError(f"набор не читается: {беда}") from None


def write_set(project, version: int, s) -> bool:
    """Положить канонический набор версии `version`. `False` — номер уже занят.

    Файл создаётся жёсткой ссылкой на временный: имя появляется сразу с
    содержимым, и занятое имя — отказ, а не замена.
    """
    папка = _папка(project)
    os.makedirs(папка, exist_ok=True)
    путь = os.path.join(папка, f"v{int(version)}.json")
    временный = f"{путь}.tmp{secrets.token_hex(4)}"
    with open(временный, "w", encoding="utf-8") as f:
        json.dump(set_json(s), f, ensure_ascii=False)
    try:
        os.link(временный, путь)
    except FileExistsError:
        return False
    finally:
        os.unlink(временный)
    for номер in versions(project)[:-ХРАНИТЬ_ВЕРСИЙ]:
        try:
            os.unlink(os.path.join(папка, f"v{номер}.json"))
        except OSError:
            pass
    return True


def rewrite_set(project, s) -> int:
    """Переписать текущую версию на месте (название, описание, настройки)."""
    номер, _ = read_set(project)
    if not номер:
        raise OrchestratorError("набора ещё нет")
    путь = os.path.join(_папка(project), f"v{номер}.json")
    временный = f"{путь}.tmp{secrets.token_hex(4)}"
    with open(временный, "w", encoding="utf-8") as f:
        json.dump(set_json(s), f, ensure_ascii=False)
    os.replace(временный, путь)
    return номер


# ── черновики ────────────────────────────────────────────────────────────────

ПАПКА_ЧЕРНОВИКОВ = "cards-drafts"
ЗАПИСЬ = "draft.json"
ТЕКСТ = "set.json"
# Текст черновика прежнего формата Markdown.
ТЕКСТ_MARKDOWN = "draft.md"
_ИД_RE = re.compile(r"^[0-9a-f]{32}$")


def _сейчас() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _iso(момент: datetime.datetime) -> str:
    return момент.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _момент(значение) -> datetime.datetime | None:
    try:
        return datetime.datetime.fromisoformat(str(значение).replace("Z", "+00:00"))
    except ValueError:
        return None


class Drafts:
    """Черновики одного человека. `root` — его каталог на томе.

    Каталог человека даёт служба (`projects.service.user_dir`), имя папки
    черновиков внутри — эта дверь.
    """

    def __init__(self, user_root: str, *, days: int = 7, keep: int = 50):
        self.root = os.path.join(os.path.abspath(user_root), ПАПКА_ЧЕРНОВИКОВ)
        self.days = max(1, int(days))
        self.keep = max(1, int(keep))

    # ── адреса ──────────────────────────────────────────────────────────────

    def path(self, draft_id: str) -> str:
        """Каталог черновика. Идентификатор не той формы — отказ."""
        ид = str(draft_id or "")
        if not _ИД_RE.match(ид):
            raise OrchestratorError(f"{draft_id!r} — не идентификатор черновика")
        return os.path.join(self.root, ид)

    def exists(self, draft_id: str) -> bool:
        try:
            return os.path.isfile(os.path.join(self.path(draft_id), ЗАПИСЬ))
        except OrchestratorError:
            return False

    # ── запись и чтение ─────────────────────────────────────────────────────

    def create(self, meta: dict, text: str = "") -> str:
        """Новый черновик с записью и текстом. → идентификатор."""
        self.prune()
        ид = uuid.uuid4().hex
        каталог = self.path(ид)
        os.makedirs(каталог, exist_ok=False)
        момент = _iso(_сейчас())
        self._write_text(ид, text)
        self._write_meta(ид, {**dict(meta or {}), "id": ид, "created_at": момент,
                              "updated_at": момент})
        return ид

    def read(self, draft_id: str) -> dict | None:
        """Запись черновика или `None`: нет такого или срок вышел."""
        if not self.exists(draft_id):
            return None
        meta = self._read_json(os.path.join(self.path(draft_id), ЗАПИСЬ))
        if not isinstance(meta, dict):
            return None
        if self._просрочен(meta):
            self.drop(draft_id)
            return None
        return meta

    def outdated(self, draft_id: str) -> bool:
        """Черновик записан прежним форматом Markdown: текста JSON у него нет."""
        каталог = self.path(draft_id)
        return (not os.path.isfile(os.path.join(каталог, ТЕКСТ))
                and os.path.isfile(os.path.join(каталог, ТЕКСТ_MARKDOWN)))

    def text(self, draft_id: str) -> str:
        """Текст файла JSON черновика; пусто — текста ещё нет."""
        try:
            with open(os.path.join(self.path(draft_id), ТЕКСТ), encoding="utf-8") as f:
                return f.read()
        except OSError:
            return ""

    def update(self, draft_id: str, *, text: str | None = None, **meta) -> dict:
        """Переписать текст и/или поля записи. → запись после правки."""
        было = self.read(draft_id)
        if было is None:
            raise OrchestratorError("черновика нет")
        if text is not None:
            self._write_text(draft_id, text)
        стало = {**было, **meta, "updated_at": _iso(_сейчас())}
        self._write_meta(draft_id, стало)
        return стало

    def drop(self, draft_id: str) -> None:
        shutil.rmtree(self.path(draft_id), ignore_errors=True)

    def prune(self) -> list[str]:
        """Убрать черновики, чей срок вышел, и самые старые сверх потолка."""
        if not os.path.isdir(self.root):
            return []
        живые, убрано = [], []
        for имя in os.listdir(self.root):
            if not _ИД_RE.match(имя):
                continue
            meta = self._read_json(os.path.join(self.root, имя, ЗАПИСЬ))
            if not isinstance(meta, dict) or self._просрочен(meta):
                shutil.rmtree(os.path.join(self.root, имя), ignore_errors=True)
                убрано.append(имя)
                continue
            живые.append((str(meta.get("updated_at") or ""), имя))
        живые.sort()
        # Место под новый черновик: потолок считается вместе с ним.
        for _, имя in живые[:max(0, len(живые) - self.keep + 1)]:
            shutil.rmtree(os.path.join(self.root, имя), ignore_errors=True)
            убрано.append(имя)
        return убрано

    # ── внутреннее ──────────────────────────────────────────────────────────

    def _просрочен(self, meta: dict) -> bool:
        момент = _момент(meta.get("updated_at") or meta.get("created_at"))
        if момент is None:
            return True
        return _сейчас() - момент > datetime.timedelta(days=self.days)

    def _write_text(self, draft_id: str, text: str) -> None:
        путь = os.path.join(self.path(draft_id), ТЕКСТ)
        временный = f"{путь}.tmp{secrets.token_hex(4)}"
        with open(временный, "w", encoding="utf-8") as f:
            f.write(str(text or ""))
        os.replace(временный, путь)

    def _write_meta(self, draft_id: str, meta: dict) -> None:
        путь = os.path.join(self.path(draft_id), ЗАПИСЬ)
        временный = f"{путь}.tmp{secrets.token_hex(4)}"
        with open(временный, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False)
        os.replace(временный, путь)

    @staticmethod
    def _read_json(путь: str):
        try:
            with open(путь, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return None


__all__ = ["ORDERS", "INCLUDE", "CardSet", "Card", "Topic", "Defaults", "Problem",
           "read_json", "read_csv", "write_json", "validate", "diff",
           "card_markdown", "plan_session", "parse", "parse_draft", "draft_text",
           "markdown_name", "MARKDOWN", "problem_json", "set_json",
           "set_from_json", "with_identity", "merge", "versions", "read_set",
           "write_set", "rewrite_set", "Drafts", "ПАПКА_НАБОРА",
           "ПАПКА_ЧЕРНОВИКОВ"]
