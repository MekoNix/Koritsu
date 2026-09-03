"""
_docx — разбор Word: текст по абзацам, встроенные картинки, таблицы, формулы.

До этого модуля `.docx` уходил в «неизвестный тип»: файл сохранялся, карточка
показывала принятый материал, а содержимого не было ни строки. Цена такой
ошибки выше, чем у падения: человек уверен, что условие задачи загружено, и
спрашивает модель по методичке, которой модель не видела.

Единица нумерации — АБЗАЦ, точнее блок тела документа: абзац или таблица.
Почему не страница, как у PDF: в `.docx` страниц нет. Разбиение на страницы
считает тот, кто открывает файл (Word и LibreOffice расходятся на том же
документе из-за шрифтов), в самом файле лежит только последовательность
`<w:p>` и `<w:tbl>`. Номер страницы был бы выдуманным числом в якоре, по
которому человек не смог бы проверить ссылку. Номер блока — свойство файла:
блок N — это N-й блок тела, всегда тот же самый.

Из этого следуют два решения:

  * пустые абзацы сохраняются как пустые единицы. Иначе номер блока перестал
    бы быть свойством файла и зависел бы от того, что мы посчитали пустым;
  * таблица занимает ОДНУ единицу целиком, на своём месте в документе. Так её
    не разрежет пополам запрос куска, и текст вокруг не теряет порядок.

Отдельно, как и у PDF:
  * встроенные картинки — самостоятельные материалы с пометкой источника
    (имя документа и номер блока), чтобы рисунок из методички можно было
    вставить в отчёт, а не пересказывать;
  * таблицы — ещё и списком в `extra["tables"]`, строками и ячейками.

Формулы Word (OMML) читаются в линейную запись: `python-docx` их не видит
(`Paragraph.text` собирает только `w:t`), поэтому без этого куска формула из
абзаца исчезала бы молча, а с ней и половина смысла лабораторной.

Чего этот разбор НЕ читает намеренно: колонтитулы, сноски и примечания —
это обрамление страницы, а не условие задачи; при надобности они добавляются
тем же обходом.
"""
from __future__ import annotations

import io
import os

import docx

from ._docx_safe import DocxUnsafe, OLE2_MAGIC, ZIP_MAGIC, check_zip
from ._image import size_px
from ._text import detect_lang
from .model import KIND_DOCX, UNIT_PARAGRAPH, Derived, Parsed

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
M = "http://schemas.openxmlformats.org/officeDocument/2006/math"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
V = "urn:schemas-microsoft-com:vml"
MC = "http://schemas.openxmlformats.org/markup-compatibility/2006"

# Меньше этого картинку считаем украшением (линейка, логотип, маркер списка).
# Тот же порог, что у PDF: смысл один — не сорить в опись.
MIN_IMAGE_SIDE = 48

# Та же сигнатура OLE2 бывает и у .docx под паролем: снаружи их не различить,
# поэтому пометка называет оба случая — иначе человек с зашифрованным файлом
# получит совет, который ему не поможет.
OLD_WORD_NOTE = ("не читается: это либо старый формат Word (.doc, до 2007 года), "
                 "либо документ под паролем. Откройте файл в Word, снимите пароль "
                 "и сохраните как .docx — иначе содержимое до модели не доедет")


def _split(tag) -> tuple[str, str]:
    """(пространство имён, локальное имя). У комментариев lxml tag не строка."""
    if not isinstance(tag, str):
        return ("", "")
    if tag.startswith("{"):
        ns, _, local = tag[1:].partition("}")
        return (ns, local)
    return ("", tag)


# ── формулы OMML ──────────────────────────────────────────────────────────────
# hokoku умеет писать формулы в OMML; здесь обратное действие, но не обратное
# преобразование: назад в LaTeX идти незачем, модели нужен читаемый текст.
# Структуру передаём скобками — «(a+b)/2» понятно и человеку, и модели, а голая
# склейка знаков дала бы «a+b2», то есть неверную формулу вместо потерянной.

def _val(el, name: str) -> str:
    child = el.find(f"{{{M}}}{name}")
    return "" if child is None else (child.get(f"{{{M}}}val") or "")


def _sub(el, name: str) -> str:
    child = el.find(f"{{{M}}}{name}")
    return "" if child is None else _omml(child)


def _wrap(s: str) -> str:
    """Скобки вокруг составного куска; одиночный знак в них не нуждается."""
    return s if len(s) <= 1 else f"({s})"


def _omml_kids(el) -> str:
    return "".join(_omml(c) for c in el if isinstance(c.tag, str))


_OMML_NODE = {
    "t": lambda el: el.text or "",
    "f": lambda el: f"{_wrap(_sub(el, 'num'))}/{_wrap(_sub(el, 'den'))}",
    "sSup": lambda el: f"{_wrap(_sub(el, 'e'))}^{_wrap(_sub(el, 'sup'))}",
    "sSub": lambda el: f"{_wrap(_sub(el, 'e'))}_{_wrap(_sub(el, 'sub'))}",
    "sSubSup": lambda el: (f"{_wrap(_sub(el, 'e'))}_{_wrap(_sub(el, 'sub'))}"
                           f"^{_wrap(_sub(el, 'sup'))}"),
    "bar": lambda el: f"‾{_wrap(_sub(el, 'e'))}",
    "func": lambda el: f"{_sub(el, 'fName')}({_sub(el, 'e')})",
    "limLow": lambda el: f"{_sub(el, 'e')}_{_wrap(_sub(el, 'lim'))}",
    "limUpp": lambda el: f"{_sub(el, 'e')}^{_wrap(_sub(el, 'lim'))}",
}


def _omml_accent(el) -> str:
    """Знак над буквой: вектор, среднее, точка. Сам знак — в свойствах узла."""
    pr = el.find(f"{{{M}}}accPr")
    return _wrap(_sub(el, "e")) + (_val(pr, "chr") if pr is not None else "")


def _omml_rad(el) -> str:
    """Корень. Степень скрыта (`degHide`) — значит квадратный."""
    deg = _sub(el, "deg")
    body = _wrap(_sub(el, "e"))
    return f"{body}^(1/{deg})" if deg else f"√{body}"


def _omml_nary(el) -> str:
    """Большой оператор: ∑, ∫, ∏. Знак лежит в свойствах; по умолчанию — интеграл."""
    pr = el.find(f"{{{M}}}naryPr")
    sign = (_val(pr, "chr") if pr is not None else "") or "∫"
    lo, hi = _sub(el, "sub"), _sub(el, "sup")
    out = sign
    if lo:
        out += f"_{_wrap(lo)}"
    if hi:
        out += f"^{_wrap(hi)}"
    return f"{out} {_sub(el, 'e')}".rstrip()


def _omml_delim(el) -> str:
    """Скобки, выставленные Word'ом: какие именно — в свойствах, по умолчанию круглые."""
    pr = el.find(f"{{{M}}}dPr")
    beg = (_val(pr, "begChr") if pr is not None else "") or "("
    end = (_val(pr, "endChr") if pr is not None else "") or ")"
    inner = "|".join(_omml(e) for e in el.findall(f"{{{M}}}e"))
    return f"{beg}{inner}{end}"


_OMML_NODE["acc"] = _omml_accent
_OMML_NODE["rad"] = _omml_rad
_OMML_NODE["nary"] = _omml_nary
_OMML_NODE["d"] = _omml_delim
# Свойства узлов текста не несут, но внутри лежит w:rPr — в него ходить незачем.
_OMML_SKIP = {"rPr", "ctrlPr", "naryPr", "dPr", "radPr", "accPr", "barPr", "argPr", "mPr"}


def _omml(el) -> str:
    ns, tag = _split(el.tag)
    if ns == M:
        if tag in _OMML_SKIP:
            return ""
        fn = _OMML_NODE.get(tag)
        if fn is not None:
            return fn(el)
    return _omml_kids(el)


# ── текст блока ───────────────────────────────────────────────────────────────

def _walk(el, out: list[str]) -> None:
    for child in el:
        ns, tag = _split(child.tag)
        if not tag:
            continue
        if ns == MC and tag == "AlternateContent":
            # Word кладёт один и тот же кусок дважды (Choice и Fallback).
            # Берём первый: иначе текст надписи попал бы в абзац двумя копиями.
            first = next((c for c in child if isinstance(c.tag, str)), None)
            if first is not None:
                _walk(first, out)
            continue
        if ns == M and tag in ("oMath", "oMathPara"):
            out.append(_omml(child))
            continue
        if ns == W:
            if tag == "t":
                out.append(child.text or "")
                continue
            if tag == "tab":
                out.append("\t")
                continue
            if tag in ("br", "cr"):
                out.append("\n")
                continue
            if tag == "del":
                continue                    # вычеркнутое при правках — этого в тексте уже нет
            if tag == "p":
                # Вложенный абзац (ячейка таблицы, надпись): свой перевод строки,
                # иначе два абзаца ячейки слипаются в одно слово.
                _walk(child, out)
                out.append("\n")
                continue
        _walk(child, out)


def _blocks(el):
    """
    Блоки тела документа по порядку. Обход свой, а не `doc.iter_inner_content()`:
    тот отдаёт только `w:p` и `w:tbl` и молча теряет содержимое элементов
    управления (`w:sdt`) — а в кафедральных шаблонах полями для ФИО, темы и
    группы сделаны именно они, то есть терялась бы ровно шапка задания.
    """
    for child in el:
        ns, tag = _split(child.tag)
        if ns != W:
            continue
        if tag in ("p", "tbl"):
            yield child
        elif tag in ("sdt", "customXml"):
            inner = child.find(f"{{{W}}}sdtContent") if tag == "sdt" else child
            if inner is not None:
                yield from _blocks(inner)


def _text_of(el) -> str:
    """Текст поддерева: `w:t`, табуляции, переводы строк и формулы по порядку."""
    out: list[str] = []
    _walk(el, out)
    return "".join(out).strip()


def _table_rows(tbl_el) -> list[list[str]]:
    """Строки таблицы по XML, а не по `table.rows`: объединённые ячейки и кривая
    разметка роняют высокоуровневый обход, а таблицу терять нельзя."""
    rows = []
    for tr in tbl_el.findall(f"{{{W}}}tr"):
        rows.append([_text_of(tc) for tc in tr.findall(f"{{{W}}}tc")])
    return rows


# ── картинки ──────────────────────────────────────────────────────────────────

def _rel_ids(el) -> list[str]:
    """Идентификаторы связей на картинки в поддереве: DrawingML и старый VML."""
    ids = []
    for node in el.iter():
        ns, tag = _split(node.tag)
        if ns == A and tag == "blip":
            rid = node.get(f"{{{R}}}embed") or node.get(f"{{{R}}}link")
            if rid:
                ids.append(rid)
        elif ns == V and tag == "imagedata":
            rid = node.get(f"{{{R}}}id")
            if rid:
                ids.append(rid)
    return ids


# ── разбор ────────────────────────────────────────────────────────────────────

def parse_word(data: bytes, name: str = "документ.docx", ext: str = ".docx",
               extract_images: bool = True) -> Parsed:
    """
    Разобрать документ Word из байтов. Расширению не верим: `.doc`, в котором
    лежит zip, разбираем как docx, а `.docx` с сигнатурой OLE2 — это старый
    `.doc` под чужим именем, и сказать об этом надо словами про `.doc`.

    Ни один путь отсюда не возвращает «пусто и молча»: не открылось — материал
    сохраняется с пометкой, по которой видно, что делать человеку.
    """
    if data.startswith(OLE2_MAGIC) or (not data.startswith(ZIP_MAGIC) and ext in (".doc", ".dot")):
        return Parsed(kind=KIND_DOCX, unit=UNIT_PARAGRAPH, notes=[OLD_WORD_NOTE])
    if not data.startswith(ZIP_MAGIC):
        return Parsed(kind=KIND_DOCX, unit=UNIT_PARAGRAPH,
                      notes=["файл не открывается как DOCX (это не zip); "
                             "возможно, он повреждён или скачан не до конца"])

    try:
        found = check_zip(data)
    except DocxUnsafe as exc:
        return Parsed(kind=KIND_DOCX, unit=UNIT_PARAGRAPH, notes=[f"документ не разобран: {exc}"])

    notes: list[str] = []
    extra: dict = {}
    if found["macros"]:
        # Содержимое читать безопасно — мы разбираем XML и ничего не выполняем.
        # Но файл целиком уедет дальше как есть, поэтому пометка обязана быть
        # видимой: решение отдавать такой документ принимает тот, кто отдаёт.
        extra["macros"] = True
        notes.append("документ с макросами (.docm): текст прочитан, макросы не выполнялись; "
                     "сам файл вставлять в отчёт нельзя — сохраните его как .docx")

    try:
        doc = docx.Document(io.BytesIO(data))
    except Exception as exc:                # чужой файл вправе быть каким угодно
        return Parsed(kind=KIND_DOCX, unit=UNIT_PARAGRAPH, notes=notes +
                      [f"документ не разобран: {exc}"])

    stem = os.path.splitext(os.path.basename(name))[0] or "документ"
    units: list[str] = []
    tables: list[dict] = []
    derived: list[Derived] = []
    seen_parts: set[str] = set()
    external: list[str] = []
    rels = doc.part.rels

    title = (doc.core_properties.title or "").strip()
    if title:
        extra["title"] = title

    for el in _blocks(doc.element.body):
        _, tag = _split(el.tag)
        if tag == "tbl":
            rows = _table_rows(el)
            units.append("\n".join(" | ".join(row) for row in rows))
            # «Осмысленно» — как у PDF: хотя бы две строки и хоть что-то в ячейках.
            if len(rows) >= 2 and any(any(c for c in row) for row in rows):
                tables.append({"paragraph": len(units), "rows": rows})
        else:
            units.append(_text_of(el))

        if not extract_images:
            continue
        for rid in _rel_ids(el):
            rel = rels.get(rid)
            if rel is None:
                continue
            if rel.is_external:
                # Картинка лежит не в файле, а по ссылке: её у нас нет и не будет.
                if rel.target_ref not in external:
                    external.append(rel.target_ref)
                continue
            part = rel.target_part
            key = str(part.partname)
            if key in seen_parts:           # одна картинка в нескольких местах — материал один
                continue
            seen_parts.add(key)
            blob = part.blob
            w, h = size_px(blob)
            # Отсеиваем только то, про что ТОЧНО знаем, что оно мелкое. Векторную
            # картинку (EMF/WMF из Word) PIL не читает и вернёт (0, 0) — такую
            # оставляем: это чаще всего и есть рисунок из методички.
            if w and h and (w < MIN_IMAGE_SIDE or h < MIN_IMAGE_SIDE):
                continue
            img_ext = os.path.splitext(key)[1].lower() or ".png"
            derived.append(Derived(
                name=f"{stem}-абз{len(units)}-{len(derived) + 1}{img_ext}",
                data=blob, ext=img_ext,
                origin={"paragraph": len(units)}))

    if external:
        # Картинка по ссылке лежит не в файле: у нас её нет и не будет.
        # Промолчать здесь — значит потерять рисунок и не сказать об этом.
        notes.append(f"картинок по внешним ссылкам: {len(external)}; самих файлов в "
                     f"документе нет, вставить их в отчёт нечем — "
                     + ", ".join(external[:3]))
    if not any(u.strip() for u in units):
        notes.append("в документе нет текста: он либо пуст, либо всё содержимое — картинки")

    if tables:
        extra["tables"] = tables
    if derived:
        extra["images"] = len(derived)

    return Parsed(kind=KIND_DOCX, unit=UNIT_PARAGRAPH, units=units,
                  lang=detect_lang("\n".join(units)), notes=notes,
                  extra=extra, derived=derived)
