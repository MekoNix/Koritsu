"""
model — что такое материал, карточка и кусок текста.

Материал — это файл пользователя плюс результат его разбора. Разбор не зависит
от модели: текст, число страниц/строк, распознанный с картинки текст. Модель
получает сначала только карточки (дёшево), а полный текст запрашивает кусками
по идентификатору.

Единица разбора (`unit`) — то, чем нумеруется содержимое: у текста «строка»,
у PDF «страница», у Word «абзац» (страниц в файле нет — их считает Word при
открытии), у картинки «строка» распознанного текста. Она же попадает в якорь,
чтобы модель могла сослаться на источник словами человека.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Виды материалов. Строки русские: они уходят в карточки, а карточки читает модель.
KIND_TEXT = "текст"
KIND_PDF = "pdf"
KIND_DOCX = "word"
KIND_IMAGE = "изображение"
KIND_UNKNOWN = "неизвестный тип"

UNIT_LINE = "строка"
UNIT_PAGE = "страница"
# В DOCX страниц нет: разбиение на страницы считает тот, кто открывает файл.
# Единица там — блок тела документа (абзац или таблица), см. _docx.
UNIT_PARAGRAPH = "абзац"


class MaterialsError(Exception):
    """Ошибка хранилища: нет такого материала, нечитаемый файл, битый разбор."""


@dataclass
class Material:
    """
    Один материал в хранилище.

    id      — устойчивый идентификатор: первые 16 знаков sha256 от содержимого.
              Из-за этого один и тот же файл, добавленный дважды, — один материал.
    unit/count — чем и сколько нумеруется содержимое (строк или страниц).
    origin  — откуда взялся производный материал: {"parent": id, "page": 4}.
              У картинки, вынутой из PDF, здесь ссылка на PDF и номер страницы.
    children — идентификаторы материалов, порождённых этим (картинки со страниц).
    notes   — честные пометки для карточки: «текст не распознан», «тип не поддержан».
    extra   — что нашлось при разборе: заголовок PDF, размеры картинки, таблицы.
    seq     — порядковый номер добавления, чтобы опись была стабильной.
    """
    id: str
    name: str
    kind: str
    ext: str
    size: int
    added: str
    unit: str = ""
    count: int = 0
    lang: str = ""
    origin: dict | None = None
    children: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    extra: dict = field(default_factory=dict)
    seq: int = 0

    def to_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "kind": self.kind, "ext": self.ext,
            "size": self.size, "added": self.added, "unit": self.unit, "count": self.count,
            "lang": self.lang, "origin": self.origin, "children": list(self.children),
            "notes": list(self.notes), "extra": self.extra, "seq": self.seq,
        }

    @staticmethod
    def from_dict(d: dict) -> "Material":
        return Material(
            id=d["id"], name=d["name"], kind=d["kind"], ext=d.get("ext", ""),
            size=int(d.get("size", 0)), added=d.get("added", ""), unit=d.get("unit", ""),
            count=int(d.get("count", 0)), lang=d.get("lang", ""), origin=d.get("origin"),
            children=list(d.get("children", ())), notes=list(d.get("notes", ())),
            extra=dict(d.get("extra", {})), seq=int(d.get("seq", 0)))


@dataclass
class Card:
    """
    Короткая карточка материала: несколько строк, считается без модели.
    Первая строка всегда начинается с идентификатора — иначе модель не сможет
    попросить кусок именно этого материала.
    """
    id: str
    lines: list[str]

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


@dataclass
class Chunk:
    """
    Кусок содержимого с якорем. Якорь — человеческая ссылка на источник
    (««методичка.pdf», страница 4»), её же модель потом вставит в отчёт.
    Границы start/end включительные, нумерация с единицы.
    """
    id: str
    name: str
    unit: str
    start: int
    end: int
    text: str
    anchor: str


def anchor(name: str, unit: str, start: int, end: int) -> str:
    """
    Якорь одной строкой. Формат задан здесь единожды: и хранилище, и сборка
    контекста берут его отсюда, чтобы ссылки везде выглядели одинаково.
    """
    if not unit or end < start:
        return f"«{name}»"
    if start == end:
        return f"«{name}», {unit} {start}"
    # Множественное число единицы задано здесь же: якорь читает человек, и
    # «страницы 3–7» вместо «страница 3–7» — разница между ссылкой и опиской.
    plural = {UNIT_LINE: "строки", UNIT_PAGE: "страницы", UNIT_PARAGRAPH: "абзацы"}.get(unit, unit)
    return f"«{name}», {plural} {start}–{end}"


@dataclass
class Derived:
    """
    Материал, порождённый разбором другого: картинка, вынутая со страницы PDF.
    Байты вместе с тем, откуда они взялись, — хранилище положит их отдельным
    материалом со своим идентификатором.
    """
    name: str
    data: bytes
    ext: str
    origin: dict


@dataclass
class Parsed:
    """
    Результат разбора файла — то, что хранилище сохранит рядом с исходником.
    units — содержимое, разбитое на нумеруемые куски (строки или страницы):
    именно по ним потом нарезаются якоря.
    """
    kind: str
    unit: str = ""
    units: list[str] = field(default_factory=list)
    lang: str = ""
    notes: list[str] = field(default_factory=list)
    extra: dict = field(default_factory=dict)
    derived: list[Derived] = field(default_factory=list)
