"""
template — документ без шаблона: пустой DOCX со своими стилями, полями и нумерацией.

Зачем. До сих пор hokoku умел ровно одно: заполнить чужой DOCX. Во всём пакете не было
ни одного `Document()` без аргумента — шаблон приносил студент. `kadai` шаблон сочиняет
сам, приносить нечего, и документ надо построить: `blank_document()` даёт тот самый
пустой документ, который дальше идёт обычным путём `render` / `build_report`.

Механизм один на две беды, а не два похожих. Стили, без которых рендер вписывает
оформление прямо в абзацы (`Heading N`, `Code`, `Caption`, `Quote`), объявлены здесь
таблицей `STYLE_SPECS`:
  `blank_document()` ставит их все сразу;
  `docx_ops.set_style()` на промахе достаёт из той же таблицы ровно тот, что попросили.
Цена прямого форматирования видна не сразу, а в Word: стиль правится одним движением на
весь документ, прямое форматирование — руками по каждому абзацу; «Обновить оглавление»
находит заголовки по стилю и `outlineLvl`, а не по кеглю.

`check_template()` — что стоит спросить у шаблона до сборки. Отсутствие стиля теперь не
беда, а замена: hokoku подставит свой, и вид будет не кафедральный — это `warning`,
а не `error`. Ошибка тут одна и настоящая: поля шире страницы, то есть полосы набора нет
и картинка с таблицей поедут за край.

Умолчания пустого документа — ГОСТ 7.32 (А4, поля 3/1.5/2/2 см, Times New Roman 14,
полуторный интервал, абзацный отступ 1.25 см). Это умолчание, а не закон: у кафедры свой
вкус, и `blank_document(page=…, body=…)` его принимает; `sample.py` вытаскивает то же
самое из чужого готового отчёта.
"""
from __future__ import annotations

import io
from dataclasses import dataclass, replace

from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

from . import docx_ops as ops
from .images import EMU_PER_CM
from .model import Problem
from .styles import get_style

# ── описание оформления ───────────────────────────────────────────────────────


@dataclass(frozen=True)
class PageSetup:
    """Размер листа и поля, в сантиметрах. Порядок полей — как их называет Word."""
    width_cm: float = 21.0
    height_cm: float = 29.7
    left_cm: float = 3.0
    right_cm: float = 1.5
    top_cm: float = 2.0
    bottom_cm: float = 2.0

    def text_width_cm(self) -> float:
        """Полоса набора. Может выйти нулевой или отрицательной — это и ловит check_template."""
        return self.width_cm - self.left_cm - self.right_cm

    def text_height_cm(self) -> float:
        return self.height_cm - self.top_cm - self.bottom_cm


@dataclass(frozen=True)
class BodyText:
    """Основной текст: стиль Normal, от которого наследуются все остальные."""
    font: str = "Times New Roman"
    size_pt: float = 14
    line_spacing: float = 1.5
    first_line_cm: float = 1.25
    align: str = "both"                  # both | left | center | right


A4_GOST = PageSetup()
GOST_BODY = BodyText()

_ALIGN = {"left": "left", "right": "right", "center": "center", "both": "both",
          "justify": "both"}


@dataclass(frozen=True)
class StyleSpec:
    """Запасной стиль: как он выглядит, если в документе своего такого нет.

    `builtin` различает две разные вещи в OOXML. `Heading 1`, `Caption`, `Quote` —
    встроенные имена Word: у них внутреннее имя, локализованное отображение («Заголовок 1»)
    и смысл для оглавления. `Code` — наш собственный стиль, и он обязан быть помечен
    `customStyle`, иначе Word покажет его как испорченный встроенный.
    """
    name: str
    builtin: bool = True
    base: str | None = "Normal"
    next_style: str | None = "Normal"
    font: str | None = None
    size_pt: float | None = None
    bold: bool = False
    italic: bool = False
    color: str | None = None
    align: str | None = None
    space_before: int = 0                # twips
    space_after: int = 0
    line_spacing: float | None = None
    keep_next: bool = False
    keep_lines: bool = False
    outline_level: int | None = None     # 0 = «Уровень 1» в оглавлении
    left_indent_cm: float = 0.0
    first_line_cm: float | None = None   # None — как у базового стиля
    left_border: str | None = None       # цвет вертикальной черты слева (цитата)


# Ровно тот набор, ради которого рендер сегодня форматирует абзацы напрямую
# (`docx_ops.style_heading` / `style_quote` / `add_code_lines` / `add_caption`).
# Размеры заголовков не дублируются: их даёт `styles.yaml` (раздел `headings`),
# и перегрузка `render(style={"headings": …})` продолжает работать.
STYLE_SPECS: dict[str, StyleSpec] = {
    **{f"Heading {n}": StyleSpec(
        name=f"Heading {n}", bold=True, space_before=240, space_after=120,
        keep_next=True, keep_lines=True, outline_level=n - 1, align="left",
        first_line_cm=0.0, line_spacing=1.15) for n in range(1, 7)},
    "Caption": StyleSpec(name="Caption", space_before=60, space_after=200,
                         align="center", first_line_cm=0.0, line_spacing=1.0),
    "Quote": StyleSpec(name="Quote", italic=True, left_indent_cm=1.25,
                       first_line_cm=0.0, space_before=120, space_after=120,
                       left_border="BBBBBB"),
    "Code": StyleSpec(name="Code", builtin=False, font=ops.CODE_FONT,
                      size_pt=ops.CODE_SIZE_PT, align="left", first_line_cm=0.0,
                      line_spacing=1.0),
}

# Что проверяет check_template: без этих стилей отчёт выходит некрасивым молча —
# заголовки не попадут в оглавление, подписи разъедутся с кафедральными.
CRITICAL_STYLES = ("Heading 1", "Heading 2", "Heading 3", "Caption")


# ── запасные стили ────────────────────────────────────────────────────────────

def heading_sizes(doc=None) -> dict:
    """Кегли заголовков: перегрузка рендера (если она была), иначе styles.yaml.

    Перегрузку `render(style={"headings": …})` рендер кладёт на сам документ: стиль
    создаётся глубоко внутри `docx_ops.set_style`, куда словарь оформления не доходит,
    а молча игнорировать просьбу нельзя — заголовки вышли бы не того размера, о чём
    вызывающий узнал бы только глазами.
    """
    sizes = getattr(doc, "_hokoku_heading_sizes", None) if doc is not None else None
    return dict(sizes or get_style()["headings"])


def ensure_style(doc, name: str, *, overwrite: bool = False) -> str | None:
    """Создать в документе запасной стиль `name`, если его там нет. → style_id или None.

    `overwrite=True` — переписать и существующий: так поступает только `blank_document`
    со своим же документом. Чужой шаблон переписывать нельзя ни при каких условиях:
    его оформление и есть то, ради чего его принесли.

    None значит «не смогли» (имени нет в таблице или в документе нет части стилей) —
    вызывающий обязан остаться на прямом форматировании, иначе абзац уедет без оформления.
    """
    spec = STYLE_SPECS.get(name)
    if spec is None:
        return None
    ids = ops.style_ids(doc)
    if name in ids and not overwrite:
        return ids[name]
    if spec.size_pt is None and name.startswith("Heading "):
        spec = replace(spec, size_pt=heading_sizes(doc).get(int(name[-1])))
    try:
        style = (doc.styles[name] if name in ids else
                 doc.styles.add_style(name, WD_STYLE_TYPE.PARAGRAPH, builtin=spec.builtin))
        _apply_spec(doc, style, spec, reset=name in ids)
    except Exception:                                          # noqa: BLE001
        # экзотический документ без styles.xml или занятое имя другого типа: рендер
        # переживает это прямым форматированием, а падать на оформлении нельзя
        return None
    # кэш style_ids живёт на документе; без этой строки следующий же set_style снова
    # промахнётся и создаст второй такой же стиль
    ids[name] = style.style_id
    return style.style_id


def ensure_styles(doc, names=None, *, overwrite: bool = False) -> list[str]:
    """Все запасные стили разом (для документа, который строим сами). → что тронули."""
    touched = []
    for name in (names if names is not None else STYLE_SPECS):
        if (overwrite or not ops.has_style(doc, name)) and ensure_style(doc, name,
                                                                        overwrite=overwrite):
            touched.append(name)
    return touched


def _apply_spec(doc, style, spec: StyleSpec, *, reset: bool = False) -> None:
    """Свойства стиля через API python-docx; XML — только там, где API нет.

    `reset` стирает прежние pPr/rPr стиля. Без него встроенный «Heading 1» из шаблона
    python-docx остаётся синим Cambria: кегль мы переставим, а тему шрифта и цвет — нет,
    и в отчёте по ГОСТу заголовки вышли бы синими."""
    if reset:
        el = style.element
        for tag in ("w:pPr", "w:rPr"):
            for old in el.findall(qn(tag)):
                el.remove(old)
    if spec.base and ops.has_style(doc, spec.base):
        style.base_style = doc.styles[spec.base]
    if spec.next_style and ops.has_style(doc, spec.next_style):
        style.next_paragraph_style = doc.styles[spec.next_style]
    style.quick_style = True                        # иначе стиля нет в галерее Word
    _apply_font(style, font=spec.font, size_pt=spec.size_pt, bold=spec.bold or None,
                italic=spec.italic or None, color=spec.color)
    pf = style.paragraph_format
    pf.space_before = Pt(spec.space_before / 20)
    pf.space_after = Pt(spec.space_after / 20)
    if spec.line_spacing is not None:
        pf.line_spacing = spec.line_spacing
    pf.keep_with_next = spec.keep_next or None
    pf.keep_together = spec.keep_lines or None
    pf.left_indent = Cm(spec.left_indent_cm)
    if spec.first_line_cm is not None:
        pf.first_line_indent = Cm(spec.first_line_cm)
    ppr = style.element.get_or_add_pPr()
    if spec.align:
        ops.set_child(ppr, "w:jc", val=_ALIGN[spec.align])
    if spec.outline_level is not None:
        ops.set_child(ppr, "w:outlineLvl", val=spec.outline_level)
    if spec.left_border:
        for old in ppr.findall(qn("w:pBdr")):
            ppr.remove(old)
        ops.insert_ordered(ppr, _left_border(spec.left_border))


def _apply_font(style, *, font=None, size_pt=None, bold=None, italic=None, color=None):
    """Шрифт стиля; None у любого свойства — «не трогать, наследовать от базового».
    Различие не косметическое: `bold=False` пишет в стиль явное «не жирный», а None
    оставляет жирность базового стиля, и заголовок из примера вышел бы жирным вопреки
    примеру. Имя шрифта пишем во все четыре слота rFonts: кириллица у Word идёт по
    `ascii`/`hAnsi`, но документ, побывавший в LibreOffice, читает `cs`, и без него
    половина текста внезапно набрана другой гарнитурой."""
    if font:
        rpr = style.element.get_or_add_rPr()
        for old in rpr.findall(qn("w:rFonts")):
            rpr.remove(old)
        rf = OxmlElement("w:rFonts")
        for attr in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
            rf.set(qn(attr), font)
        ops.insert_ordered(rpr, rf)
    if size_pt is not None:
        style.font.size = Pt(size_pt)
    if bold is not None:
        style.font.bold = bold
    if italic is not None:
        style.font.italic = italic
    if color:
        style.font.color.rgb = RGBColor.from_string(color)


def _left_border(color: str):
    bdr = OxmlElement("w:pBdr")
    left = OxmlElement("w:left")
    for k, v in (("val", "single"), ("sz", "12"), ("space", "8"), ("color", color)):
        left.set(qn(f"w:{k}"), v)
    bdr.append(left)
    return bdr


# ── документ с нуля ───────────────────────────────────────────────────────────

def blank_document(*, page: PageSetup = A4_GOST, body: BodyText = GOST_BODY,
                   page_numbers: bool = True):
    """Пустой документ со стилями, полями и нумерацией страниц. → docx.Document.

    Пустой — значит без единого абзаца в теле: любой оставленный абзац станет лишней
    строкой на первой странице готового отчёта, а убрать его вызывающий не догадается.
    Наполняет документ вызывающий (`kadai` — тегами `{{…}}`), после чего это обычный
    шаблон: `render` и `build_report` работают с ним, ничего не зная о его происхождении.
    """
    doc = Document()
    for p in list(doc.paragraphs):                 # штатный шаблон python-docx не пуст
        p._p.getparent().remove(p._p)
    apply_page_setup(doc, page)
    apply_body_text(doc, body)
    # переписываем и те стили, что пришли из штатного шаблона python-docx: их вид
    # (синий Cambria у заголовков) не имеет отношения ни к ГОСТу, ни к styles.yaml
    ensure_styles(doc, overwrite=True)
    if page_numbers:
        add_page_numbers(doc)
    return doc


def apply_page_setup(doc, page: PageSetup) -> None:
    """Размер и поля — всем секциям: секции у документа обычно одна, но у отчёта
    с альбомным приложением их две, и поля надо ставить в обеих."""
    for s in doc.sections:
        s.page_width, s.page_height = Cm(page.width_cm), Cm(page.height_cm)
        s.left_margin, s.right_margin = Cm(page.left_cm), Cm(page.right_cm)
        s.top_margin, s.bottom_margin = Cm(page.top_cm), Cm(page.bottom_cm)


def apply_body_text(doc, body: BodyText) -> None:
    """Стиль Normal: от него наследуется всё остальное, поэтому шрифт ставится один раз."""
    if not ops.has_style(doc, "Normal"):
        return
    style = doc.styles["Normal"]
    _apply_font(style, font=body.font, size_pt=body.size_pt)
    pf = style.paragraph_format
    pf.line_spacing = body.line_spacing
    pf.first_line_indent = Cm(body.first_line_cm)
    pf.space_before, pf.space_after = Pt(0), Pt(0)
    ops.set_child(style.element.get_or_add_pPr(), "w:jc", val=_ALIGN[body.align])


def add_page_numbers(doc, *, align: str = "center") -> None:
    """Номер страницы в нижнем колонтитуле — полем PAGE, а не текстом: текст не
    пересчитается, и весь отчёт уйдёт на кафедру со страницей «1» на каждом листе."""
    for section in doc.sections:
        footer = section.footer
        footer.is_linked_to_previous = False
        p = footer.paragraphs[0] if footer.paragraphs else footer.add_paragraph()
        for r in list(p._p.findall(qn("w:r"))):
            p._p.remove(r)
        ops.set_alignment(p._p, _ALIGN[align])
        p._p.append(ops.page_number_field())


def document_bytes(doc) -> bytes:
    """Документ → байты: `build_report` берёт шаблон артефактом, а не объектом."""
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# ── проверка шаблона ──────────────────────────────────────────────────────────

def _problem(level: str, code: str, message: str, key: str | None = None) -> Problem:
    """Запись той же формы, что у `validate` и `check_manifest` (`model.Problem`,
    он же общий `kyotsu.Notice`): её показывают в интерфейсе и отдают модели, и
    разбирать прозу ни тому, ни другому нечем.

    `module` здесь — `template`, а не `hokoku`, и так было с самого начала:
    проверка шаблона отвечает на отдельный вопрос («годен ли документ, по
    которому собирают»), и в интерфейсе её замечания стоят не рядом с
    замечаниями о значениях. Переименовать — сломать разбор у того, кто их
    сегодня показывает, ничего не выиграв.

    `key` бывает не тегом: у секции с полями шире листа это «section 2».
    Пустым он в JSON не попадает — `Notice.to_dict` выбрасывает незаданное.
    """
    return Problem(module="template", level=level, code=code, message=message, key=key)


def check_template(template) -> list[Problem]:
    """Чего не хватает документу, чтобы собранный отчёт выглядел прилично. → [проблема].

    Не бросает: список пуст — всё в порядке. `error` значит «соберётся не то»
    (поля шире страницы — картинки и таблицы поедут за край, стиля Normal нет —
    у документа нет основного текста). `warning` — «соберётся, но не по-кафедральному»:
    стиль отсутствует, hokoku подставит свой из `STYLE_SPECS`.

    Цена пропуска: без этой проверки сочинённый или чужой шаблон портится молча —
    заголовки не попадают в оглавление, подписи набраны не тем кеглем, и видно это
    только на распечатке.
    """
    from .walker import open_document
    doc = open_document(template)
    out: list[Problem] = []
    if not ops.has_style(doc, "Normal"):
        out.append(_problem("error", "no_normal_style",
                            "в документе нет стиля Normal — основного текста у него нет, "
                            "и остальным стилям не от чего наследоваться"))
    for name in CRITICAL_STYLES:
        if not ops.has_style(doc, name):
            out.append(_problem("warning", "style_missing", key=name, message=(
                f"в шаблоне нет стиля {name!r} — hokoku подставит свой; "
                "вид заголовков и подписей будет не тот, что в кафедральном образце")))
    for name in STYLE_SPECS:
        if name not in CRITICAL_STYLES and not ops.has_style(doc, name):
            out.append(_problem("info", "style_missing", key=name, message=(
                f"в шаблоне нет стиля {name!r} — hokoku подставит свой")))
    for i, s in enumerate(doc.sections):
        width = (s.page_width - s.left_margin - s.right_margin) / EMU_PER_CM
        height = (s.page_height - s.top_margin - s.bottom_margin) / EMU_PER_CM
        if width <= 0 or height <= 0:
            out.append(_problem("error", "no_text_area", key=f"section {i + 1}", message=(
                f"поля секции {i + 1} шире листа: полоса набора {width:.1f}×{height:.1f} см — "
                "текст, картинки и таблицы уедут за край страницы")))
        elif width < 8:
            out.append(_problem("warning", "narrow_text_area", key=f"section {i + 1}", message=(
                f"полоса набора секции {i + 1} — {width:.1f} см: картинка во всю ширину "
                "выйдет размером с марку, а таблица на пять колонок не читается")))
    return out
