"""
model — типизированные значения тегов и результаты.

Вместо строк с sentinel'ами (1.x: `__code__:`, `__ctx__:`, data-URL) — классы.
Что можно подставить *внутрь строки* (inline): Text. Всё остальное — блоки:
они заменяют абзац с тегом (и текст вокруг тега в нём остаётся: тег
вырезается, блоки вставляются после абзаца).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from kyotsu import Notice


class HokokuError(Exception):
    """Ошибка рендера: битое значение, недоступный файл, неверный шаблон."""


@dataclass(frozen=True)
class Problem(Notice):
    """Замечание о теге: общая форма (`kyotsu.Notice`) плюс то, что есть у тега.

    Тремя записями `{module, level, code, key, message}` пакет отвечал и раньше
    (`validate`, `check_manifest`, `check_template`, предупреждения
    `build_report`), но собирались они тремя почти одинаковыми функциями, и
    ключи у них расходились по одному: `suggest` был только у `build_report`,
    `expected`/`got` — только у `validate`. Здесь форма одна, а `to_dict()`
    достаётся от `Notice` и сам кладёт в JSON поля подкласса — старые ключи
    остались теми же.

    `key` — ключ тега, а у `check_template` ещё и «section 2»: беда там не про
    тег, а про секцию шаблона, и называть её нечем другим. Пустой `key`
    (`None`) в JSON не попадает: беды бывают и не про тег.

    `expected`/`got` — машиночитаемое «ждали / получили»: их показывают в
    интерфейсе и отдают модели, и разбирать ради этого прозу нечем.
    `suggest` — похожие имена («не `цел`, а `цель`»): предупреждение без «а как
    надо» заставляет идти за списком тегов руками.
    """

    key: str | None = None
    expected: str | None = None
    got: str | None = None
    suggest: list | None = None


@dataclass
class Text:
    """Обычный текст. `\\n` → разрыв строки внутри абзаца (w:br)."""
    text: str


@dataclass
class Markdown:
    """Markdown: заголовки, списки, **жирный**, `код`, ```блоки```, > цитаты, ---,
    таблицы `| a | b |`, картинки `![подпись](файл)`, ссылки [текст](url)."""
    text: str
    images_dir: str | None = None     # откуда брать файлы из ![..](name)


@dataclass
class Code:
    """Листинг: моноширинный, переносы строк сохранены, без разбора разметки.
    lang — язык для подсветки (pygments); line_numbers — нумерация строк (None → из styles)."""
    text: str
    lang: str = ""
    line_numbers: bool | None = None
    highlight: bool | None = None


@dataclass
class Image:
    """Картинка: путь или bytes. Ширина в см (по умолчанию — вписать в поле страницы).
    caption — подпись под рисунком ({n} — номер по документу); None — подпись «Рисунок N»
    без текста; False — без подписи и без номера (логотип, врезка). В колонтитулах
    не нумеруется никогда. Слишком высокая картинка вписывается в страницу целиком:
    резать её на листы hokoku больше не умеет — листы даёт генератор схемы (см. Diagram)."""
    source: str | bytes
    caption: str | bool | None = None
    width_cm: float | None = None
    align: str = "center"            # left | center | right
    ref: str | None = None           # имя для ссылок {ref:имя} в тексте (по умолчанию — ключ тега)

    def read(self) -> bytes:
        if isinstance(self.source, bytes):
            return self.source
        if not os.path.isfile(self.source):
            raise HokokuError(f"картинка не найдена: {self.source}")
        with open(self.source, "rb") as f:
            return f.read()


@dataclass
class Table:
    """Таблица: rows — строки ячеек (строки с inline-markdown). header — первая строка жирная."""
    rows: list[list[str]]
    header: bool = True
    caption: str | bool | None = None  # «Таблица {n} — …» над таблицей; False — без номера
    col_widths_cm: list[float] | None = None
    align: list[str] | None = None   # по колонкам: left | center | right
    ref: str | None = None


@dataclass
class Diagram:
    """Схема draw.io (XML) → PNG через drawio CLI (нужен `drawio` и `xvfb-run`).
    Многостраничный mxfile — это листы одного рисунка: «Рисунок N (лист k из m)»,
    номер и закладка общие. Где рвать длинный алгоритм и куда ставить соединители,
    решает генератор схемы, а не hokoku."""
    xml: str
    caption: str | bool | None = None
    width_cm: float | None = None
    align: str = "center"
    ref: str | None = None
    page: int | None = None          # один лист, считая с 1 (None — все листы схемы)


@dataclass
class Formula:
    """Формула в LaTeX-записи → нативная формула Word (OMML). numbered — «(n)» справа
    (поле SEQ Формула, закладка для {ref:имя})."""
    latex: str
    numbered: bool = True
    ref: str | None = None


@dataclass
class Toc:
    """Оглавление — поле TOC по стилям Heading 1..levels; Word заполнит при открытии."""
    levels: int = 3
    title: str | None = None       # заголовок над оглавлением (None — без)


@dataclass
class PageBreak:
    """Разрыв страницы (внутри Blocks или отдельным значением)."""


@dataclass
class Blocks:
    """Последовательность блоков: Text/Markdown/Code/Image/Table/PageBreak."""
    items: list


Value = Text | Markdown | Code | Image | Diagram | Table | Formula | Toc | Blocks | PageBreak | str


@dataclass
class Tag:
    key:    str
    label:  str
    where:  str = "body"                                  # первое место: body | header | footer | textbox | table
    places: list[str] = field(default_factory=list)       # все места
    count:  int = 0                                       # число вхождений


@dataclass
class RenderResult:
    output:   str | None                                 # путь; None — результат в .data
    data:     bytes | None = None
    unfilled: list[str] = field(default_factory=list)   # ключи без значений (убраны из документа)
    figures:  int = 0                                    # сколько рисунков пронумеровано
    tables:   int = 0
    formulas: int = 0
    refs:     dict = field(default_factory=dict)         # имя → номер (рисунки и таблицы)
    unresolved_refs: list[str] = field(default_factory=list)
    errors:   list[dict] = field(default_factory=list)   # on_error="skip": [{key, message}]
    unknown_keys: list[str] = field(default_factory=list)  # значения, для которых нет тега
