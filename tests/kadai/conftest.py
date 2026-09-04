"""
Оснастка тестов kadai.

Два правила обеспечиваются структурно, а не договорённостью.

1. **Службы здесь нет вовсе.** `kadai` не импортирует ни `orchestrator`, ни
   `llm`, ни `materials` (правило разреза, см. `kadai/__init__.py`), поэтому и
   тесты обходятся стандартной библиотекой и подделками. Выгода не только
   идейная: соседние пакеты переписываются, и тесты сценария не должны краснеть
   от чужой правки. Движок отчётов (`hokoku`) при этом настоящий — он приходит
   в пакет чистыми функциями, и подделывать сборку документа значило бы
   проверять свою подделку вместо сборки.
2. **Сети нет, потому что её неоткуда взять.** Ни одна функция пакета не зовёт
   модель: вызовы модели живут за дверями, а двери здесь подделаны. Отдельный
   запрет транспорта поэтому не нужен — нужен тест, что двери, которых не дали,
   отказывают (`test_seams.py`).

Подделка проекта повторяет ровно те методы, которыми `kadai` пользуется, и
позволяет убрать любой из них: «метода нет» — рабочий случай, а не крайний, и
именно по нему проверяется, что отказ называет шов, а не падает
`AttributeError`.

Подделки дверей ведут себя как настоящие в том, что для сценария важно:
`make_template` кладёт по два блока на раздел (заголовок и место под
содержимое), `solve` заменяет черновики нетекстовых блоков и пишет версию,
`write_texts` пишет весь текст одним вызовом и **не трогает** блоки с пометкой
`manual`/`file`. Последнее подделано намеренно: правило «написанное человеком
не переписывается» держит настоящая дверь, и тест обязан ловить сценарий,
который попросил бы её об обратном.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pytest

import kadai

# Значение блока в том виде, в каком оно лежит на диске. Записано здесь
# буквально, а не собрано через `hokoku`: подделка обязана проверять, что
# сценарий читает **запись**, а не то, что она сама же и построила движком.
def markdown(text: str) -> dict:
    return {"v": 2, "type": "markdown", "text": text}


def code(text: str, lang: str = "python") -> dict:
    # Поле языка у значения `code` называется `lang` — так у движка отчётов, и
    # подделка обязана называть его так же: разойдись имя, сценарий читал бы
    # пустой язык и молча клал бы в архив `.txt`.
    return {"v": 2, "type": "code", "text": text, "lang": lang}


def table(rows) -> dict:
    return {"v": 2, "type": "table", "rows": [list(r) for r in rows]}


@dataclass
class FakeSpec:
    """Запись манифеста в том объёме, в каком её читает `kadai` (утиная типизация).

    Ровно четыре поля входа плюс `missing`: если `kadai` начнёт читать пятое,
    тест это заметит — подделка его не отдаст.
    """

    type: str = "markdown"
    prompt: str = ""
    limits: dict = field(default_factory=dict)
    depends_on: list = field(default_factory=list)
    missing: bool = False


@dataclass
class FakeMaterial:
    """Материал в объёме карточки: имя, вид, единица, пометки разбора."""

    id: str
    name: str
    kind: str = "текст"
    unit: str = "строка"
    count: int = 1
    notes: list = field(default_factory=list)


@dataclass
class FakeChunk:
    text: str
    name: str = ""
    unit: str = "строка"


class FakeStore:
    """Хранилище материалов в объёме `materials.Store`, который читает сценарий."""

    def __init__(self):
        self._items: dict = {}

    def add(self, mid: str, name: str, text: str, *, kind: str = "текст", notes=()):
        self._items[mid] = (FakeMaterial(id=mid, name=name, kind=kind,
                                         notes=list(notes)), text)
        return self._items[mid][0]

    def list(self):
        return [m for m, _ in self._items.values()]

    def get(self, mid: str):
        return self._items[str(mid)][0]

    def read(self, mid: str, start=None, end=None):
        material, text = self._items[str(mid)]
        return FakeChunk(text=text, name=material.name, unit=material.unit)


@dataclass
class FakeVersion:
    n: int
    source: str = "agent"
    note: str = ""


class FakeProject:
    """Проект в объёме, нужном сценарию. Любой метод можно убрать через `without`."""

    def __init__(self, *, without=(), spent=None, cap=None):
        self._state: dict = {}
        self._blocks: list = []
        self._block_versions: list = []
        self._artifacts: dict = {}
        self._packed: list | None = None
        self._pack_name: str = ""
        self._derived: dict = {}
        self._store = FakeStore()
        self._condition: str | None = None
        self._spent = spent or {"calls": 2, "units": 41200.0, "cost": 1.83,
                                "estimated_share": 0.04}
        self._cap = cap
        for name in without:
            setattr(self, name, None)

    # ── материалы и условие ──────────────────────────────────────────────
    def store(self) -> FakeStore:
        return self._store

    def add_material(self, data: bytes, name: str, *, do_ocr: bool = True,
                     condition: bool = False):
        mid = f"m{len(self._store.list()) + 1:02d}"
        kind = "изображение" if str(name).lower().endswith((".png", ".jpg")) else "текст"
        material = self._store.add(mid, name, data.decode("utf-8", "replace"), kind=kind)
        if condition:
            self._condition = mid
        return material

    def condition(self):
        return self._condition

    # ── блоки ────────────────────────────────────────────────────────────
    def blocks(self) -> list:
        return [dict(b) for b in self._blocks]

    def set_blocks(self, blocks, *, source: str, note: str = "", run=None):
        prepared = []
        for b in blocks:
            item = dict(b) if isinstance(b, dict) else {
                name: getattr(b, name) for name in ("key", "kind", "value", "label")}
            item.setdefault("source", source)
            item["source"] = item.get("source") or source
            prepared.append(item)
        keys = [b["key"] for b in prepared]
        assert len(keys) == len(set(keys)), "два блока с одним ключом: ключ — адрес"
        self._blocks = prepared
        version = FakeVersion(n=len(self._block_versions) + 1, source=source, note=note)
        self._block_versions.append(version)
        return version

    def block_versions(self) -> list:
        return list(self._block_versions)

    def rollback_blocks(self, n: int):
        raise AssertionError("в тестах откат не используется")

    # ── артефакты и производные ──────────────────────────────────────────
    def put_artifact(self, data: bytes, *, name: str = "", notices=()) -> str:
        art = f"a{len(self._artifacts) + 1:02d}"
        self._artifacts[art] = bytes(data)
        return art

    def resolve_artifact(self, art: str) -> bytes:
        return self._artifacts[str(art)]

    def note_derived(self, art: str, *, tool: str, inputs=(), params=None, run=None):
        self._derived[str(art)] = {"art": str(art), "tool": tool,
                                   "inputs": [str(i) for i in inputs],
                                   "params": dict(params or {}), "run": run}

    def derived_of(self, art: str):
        return self._derived.get(str(art))

    # ── состояние, архив, учёт ───────────────────────────────────────────
    def put_state(self, name: str, d: dict) -> None:
        self._state[name] = d

    def state(self, name: str) -> dict:
        return self._state.get(name, {})

    def pack(self, entries, *, name: str = "работа.zip") -> str:
        self._packed = entries
        self._pack_name = name
        return name

    def spent(self) -> dict:
        return dict(self._spent)

    def limit(self):
        return None if self._cap is None else FakeLimit(self._cap)


@dataclass
class FakeLimit:
    """Лимит в объёме `llm.Limit`: потолок и доля. Больше `kadai` от него не берёт."""

    cap_units: float
    spent_units: float = 41200.0

    def share(self) -> float:
        return self.spent_units / self.cap_units


# ── подделки дверей ──────────────────────────────────────────────────────────

@dataclass
class FakeAnswer:
    """Ответ двери `ask` в объёме, который читает сценарий."""

    ok: bool = True
    value: dict | None = None
    text: str = ""
    problems: list = field(default_factory=list)
    usage: dict = field(default_factory=dict)


@dataclass
class FakeResult:
    """Итог `solve` / `write_texts`: то же, что у настоящих LiveResult и TextsResult."""

    ok: bool = True
    changed: list = field(default_factory=list)
    filled: list = field(default_factory=list)
    problems: list = field(default_factory=list)
    steps: int = 0
    calls: int = 0
    outcome: str = "done"


ТРЕБОВАНИЕ = {"kind": "курсовая", "topic": "Сортировка массива",
              "to_do": ["написать программу", "нарисовать схему"],
              "given": ["язык Python"], "missing": ["объём выборки"]}

СТРОЕНИЕ = {
    "work_kind": "курсовая",
    "expects": {"code": True, "tables": True, "diagrams": False},
    "required_kinds": ["введение", "реализация", "заключение"],
    "sections": [
        {"key": "введение", "title": "Введение", "kind": "введение",
         "prompt": "зачем эта работа"},
        {"key": "постановка", "title": "Постановка задачи", "kind": "постановка",
         "prompt": "что дано и что требуется"},
        {"key": "реализация", "title": "Реализация", "kind": "реализация",
         "prompt": "как устроено решение"},
        {"key": "листинг", "title": "Листинг", "kind": "листинг",
         "prompt": "код сортировки"},
        {"key": "таблица", "title": "Замеры", "kind": "таблица",
         "prompt": "время на разных размерах"},
        {"key": "заключение", "title": "Заключение", "kind": "заключение",
         "prompt": "что вышло"},
    ],
}


class FakeDoors:
    """Все двери сценария подделкой. Каждый вызов записан — по ним и проверяем.

    Записывать вызовы приходится потому, что половина решений сценария видна
    только в аргументах: `overwrite=False` у прохода текста, задание петле по
    замечанию, состав `data` (условие и пожелания едут данными, а не вопросом).
    """

    def __init__(self, project: FakeProject, *, требование=None, строение=None,
                 code_problems=(), pdf: bytes | None = b"%PDF-1.4 fake"):
        self.project = project
        self.требование = dict(требование or ТРЕБОВАНИЕ)
        self.строение = dict(строение or СТРОЕНИЕ)
        self.code_problems = list(code_problems)
        self.pdf = pdf
        self.asked: list = []
        self.templates: list = []
        self.solved: list = []
        self.texts: list = []
        self.checked: list = []

    def services(self, **extra) -> kadai.Services:
        двери = {"write_texts": self.write_texts, "check_code": self.check_code,
                 "to_pdf": self.to_pdf}
        двери.update(extra)
        двери = {k: v for k, v in двери.items() if v is not None}
        return kadai.Services(project=self.project, ask=self.ask,
                              make_template=self.make_template, solve=self.solve,
                              extra=двери)

    # ── модель ───────────────────────────────────────────────────────────
    def ask(self, question, *, schema=None, data=(), **kw):
        self.asked.append({"question": question, "schema": schema, "data": list(data)})
        поля = set((schema or {}).get("properties") or ())
        if "sections" in поля:
            return FakeAnswer(value=dict(self.строение))
        return FakeAnswer(value=dict(self.требование))

    def make_template(self, structure=None, *, task="", default=(), data=(), **kw):
        """Два блока на раздел: заголовок и место под содержимое (как у службы)."""
        self.templates.append({"structure": structure, "task": task, "data": list(data)})
        записи, n = [], 0
        for section in structure or ():
            заголовок = getattr(section, "title", None) or section["title"]
            подсказка = getattr(section, "prompt", "") or заголовок
            вид = getattr(section, "type", None) or section.get("type") or "markdown"
            n += 1
            записи.append({"key": f"b-{n:02d}", "kind": "heading", "label": заголовок,
                           "value": markdown(f"# {заголовок}"), "source": "agent"})
            n += 1
            подпись = подсказка if вид in ("markdown", "text") else f"{подсказка} (здесь будет {вид})"
            записи.append({"key": f"b-{n:02d}", "kind": "markdown", "label": подсказка,
                           "value": markdown(f"черновик: {подпись}"), "source": "agent"})
        self.project.set_blocks(записи, source="agent", note="строение работы")
        return self.project.blocks()

    def solve(self, task, *, data=(), max_steps=None, tools=None, **kw):
        """Петля: черновики нетекстовых мест становятся кодом и таблицей.

        Связного текста не пишет ни строки — это и есть решение владельца
        2026-09-04, и подделка обязана вести себя так же, иначе тест на «текст
        одним проходом» проверял бы не то.
        """
        self.solved.append({"task": task, "data": list(data), "max_steps": max_steps})
        записи, changed = self.project.blocks(), []
        for record in записи:
            текст = str((record.get("value") or {}).get("text") or "")
            if "здесь будет code" in текст:
                record["kind"], record["value"] = "code", code("def sort(a):\n    return sorted(a)")
                changed.append(record["key"])
            elif "здесь будет table" in текст:
                record["kind"] = "table"
                record["value"] = table([["n", "мс"], ["10", "1"], ["100", "12"]])
                changed.append(record["key"])
        self.project.set_blocks(записи, source="agent", note="петля: нетекстовое")
        return FakeResult(ok=True, changed=changed, steps=len(changed) + 1,
                          calls=len(changed))

    def write_texts(self, *, overwrite=False, data=(), **kw):
        """Весь текст одним проходом. Блоки человека не трогает даже при просьбе."""
        self.texts.append({"overwrite": overwrite})
        записи, filled = self.project.blocks(), []
        for record in записи:
            if record.get("kind") not in ("markdown", "text"):
                continue
            текст = str((record.get("value") or {}).get("text") or "")
            if not текст.lower().startswith("черновик:"):
                continue
            if not overwrite and record.get("source") in ("manual", "file"):
                continue
            record["value"] = markdown(f"Написано моделью: {record.get('label') or record['key']}.")
            record["source"] = "agent"
            filled.append(record["key"])
        if filled:
            self.project.set_blocks(записи, source="agent",
                                    note=f"текст одним проходом: {len(filled)} блоков")
        return FakeResult(ok=bool(filled), filled=filled)

    # ── не модель ────────────────────────────────────────────────────────
    def check_code(self, text, language):
        self.checked.append({"text": text, "language": language})
        return list(self.code_problems)

    def to_pdf(self, docx: bytes):
        if self.pdf is None:
            raise RuntimeError("LibreOffice не отозвался")
        return self.pdf


@pytest.fixture
def profile():
    return kadai.load("kursovaya")


@pytest.fixture
def plan(profile):
    return kadai.plan_of(profile)


@pytest.fixture
def structure():
    """Годная структура курсовой: все обязательные виды, код и схема на месте."""
    return {"sections": [
        {"key": "титул", "title": "Титульный лист", "kind": "титульник"},
        {"key": "оглавление", "title": "Содержание", "kind": "оглавление"},
        {"key": "введение", "title": "Введение", "kind": "введение"},
        {"key": "постановка", "title": "Постановка задачи", "kind": "постановка"},
        {"key": "реализация", "title": "Реализация", "kind": "реализация"},
        {"key": "листинг_сортировки", "title": "Листинг", "kind": "листинг"},
        {"key": "схема_алгоритма", "title": "Схема алгоритма", "kind": "схема"},
        {"key": "результаты", "title": "Результаты", "kind": "результаты"},
        {"key": "заключение", "title": "Заключение", "kind": "заключение"},
    ]}


@pytest.fixture
def project():
    return FakeProject()


@pytest.fixture
def условие(project):
    """Проект с приложенным условием текстом. Работа без него не заводится."""
    project.add_material("Написать программу сортировки и отчёт.".encode("utf-8"),
                         "условие.txt", condition=True)
    return project


@pytest.fixture
def doors(условие):
    return FakeDoors(условие)
