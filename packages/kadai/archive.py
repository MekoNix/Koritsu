"""
archive — опись ZIP: что кладём, под каким именем и почему один файл обязателен всегда.

`kadai` называет содержимое, складывает `orchestrator` (шов «архив»). Разрез
именно тут: опись — это список пар «имя в архиве → откуда взять»
(`{"artifact": id}`, `{"output": имя}`, `{"text": …}`), и в ней нет ни одного
пути. Стоило бы `kadai` пойти по `out/` руками — и правило «`os.path.join`
встречается только в `project.py`», на котором держится переезд на SQLite,
ломается первой же строкой.

**`как-это-собрано.txt` обязателен, и в нём обязательна строка про незапущенный
код.** Исполнять код мы не будем никогда (песочницы не будет), а врать о
непроверенном нельзя. Компилируемый исходник без этой строки читается как
проверенный — человек узнает правду на защите, а не от нас. Поэтому опись
отказывается собираться, если строки в тексте нет: это не оформление, а
условие честности архива.

**Имена приходят из данных.** Ключ тега сочинила модель, имя исходника —
тоже. Значит `../`, абсолютный путь, `C:`, обратная косая, управляющий символ и
пустое имя обязаны быть невозможны, а не «маловероятны»: распаковщик у человека
чужой, и имя вида `../../.bashrc` пишет файл мимо каталога. Имя внутри архива
собирается только так: наша папка-константа плюс проверенный лист.

**Столкновение имён — ошибка, а не «последний победил».** Windows и macOS
распаковывают без учёта регистра, и `Схема.drawio` рядом со `схема.drawio`
молча станет одним файлом. Молча пропавший из архива раздел — то же, что
неверный отчёт: увидят его на проверке.

`решение.md` — производная от значений тегов, а не отдельный авторский путь:
иначе появляется второй источник правды, человек правит `решение.md`, отчёт
остаётся прежним, и объяснить расхождение нечем. Сюда он приходит уже текстом:
превращать значение `wire` в markdown — знание `hokoku`, и импортировать его
ради этого `kadai` не имеет права.
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field

from .errors import KadaiError
from .seams import method

# Имена и папки — константы, а не данные: единственная часть имени, пришедшая
# из данных, это лист, и он проходит `safe_leaf`.
REPORT_DOCX = "отчёт.docx"
REPORT_PDF = "отчёт.pdf"
TEMPLATE = "шаблон.docx"
SOLUTION = "решение.md"
NOTICE = "как-это-собрано.txt"
DIR_SOURCES = "исходники"
DIR_DIAGRAMS = "схемы"

# Строка, без которой опись не собирается. Дословная: её ищут в тексте, и
# переформулировка «где-то там то же самое» проверку бы прошла, а смысл потеряла.
NOT_RUN = ("Код в этом архиве не запускался и не проверялся исполнением: система "
           "пользовательский код не выполняет. Разбор был только статический "
           "(tree-sitter): он ловит синтаксический мусор и обрывки, но не отвечает "
           "на вопрос, верно ли работает решение. Проверьте код перед сдачей.")

_MAX_LEAF = 120
_BAD_LEAF = {"", ".", ".."}
# Имена, которые Windows не даёт создать вовсе; файл молча не распакуется.
_RESERVED = ({"CON", "PRN", "AUX", "NUL"}
             | {f"COM{i}" for i in range(1, 10)} | {f"LPT{i}" for i in range(1, 10)})


@dataclass(frozen=True)
class Entry:
    """Один элемент архива: имя внутри ZIP и откуда взять байты.

    Источник — только `artifact` (идентификатор по содержимому), `output` (имя
    готового файла в каталоге сборки) или `text` (то, что сочинили мы сами).
    Четвёртого вида нет намеренно: любой другой источник — это путь, а путь
    здесь и есть та вещь, которой в описи быть не должно.
    """

    name: str
    source: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {"name": self.name, **self.source}


# Расширение файла по языку блока — только для имени внутри архива. Знания о
# языках здесь нет и заводить его нельзя: разбирает код tree-sitter за
# дверью `check_code`, а это таблица имён, по которой человек узнаёт файл в
# распакованной папке. Незнакомый язык — `.txt`, а не догадка: `.py` на
# чужом коде обманул бы и редактор, и человека.
SOURCE_EXT = {"python": "py", "cpp": "cpp", "c": "c", "c_sharp": "cs", "csharp": "cs",
              "java": "java", "javascript": "js", "typescript": "ts", "go": "go",
              "rust": "rs", "sql": "sql", "bash": "sh", "shell": "sh"}


def source_name(key, language) -> str:
    """Имя файла исходника в архиве: ключ блока плюс расширение по языку."""
    ext = SOURCE_EXT.get(str(language or "").strip().lower(), "txt")
    return f"{safe_leaf(key)}.{ext}"


def safe_leaf(name) -> str:
    """Одно звено имени внутри архива или отказ. Разделителей не пропускает вовсе.

    Проверка, а не тихая замена запрещённых знаков: подчистив `../` до `..`,
    можно получить другое имя, чем ждал человек, и не сказать ему об этом.
    Отказ виден, подмена — нет.
    """
    leaf = unicodedata.normalize("NFC", str(name))
    if leaf != leaf.strip():
        # Края не срезаем молча: срезав их, мы положили бы в архив имя, которого
        # человек не называл, и не сказали бы ему об этом.
        raise KadaiError(f"имя в архиве {name!r} обрамлено пробелами")
    if leaf in _BAD_LEAF:
        raise KadaiError(f"имя в архиве пустое или служебное: {name!r}")
    bad = [c for c in leaf if c in "/\\:" or ord(c) < 32 or ord(c) == 127]
    if bad:
        raise KadaiError(f"имя в архиве {name!r} содержит запрещённые знаки: "
                         + ", ".join(repr(c) for c in dict.fromkeys(bad)))
    if leaf.endswith((".", " ")):
        raise KadaiError(f"имя в архиве {name!r} кончается точкой или пробелом: "
                         "Windows распакует его иначе или не распакует вовсе")
    if leaf.split(".")[0].upper() in _RESERVED:
        raise KadaiError(f"имя в архиве {name!r} зарезервировано Windows")
    if len(leaf) > _MAX_LEAF:
        raise KadaiError(f"имя в архиве длиннее {_MAX_LEAF} знаков: {leaf[:40]}…")
    return leaf


def in_dir(folder: str, leaf) -> str:
    """Имя внутри нашей папки. Папка — константа этого модуля, лист — из данных."""
    return f"{folder}/{safe_leaf(leaf)}"


def check_names(entries) -> None:
    """Столкновения имён без учёта регистра и нормализации. Ошибка, а не перезапись."""
    seen: dict = {}
    for e in entries:
        key = unicodedata.normalize("NFC", e.name).casefold()
        if key in seen:
            raise KadaiError(f'в архиве два файла с именем "{e.name}" '
                             f'(уже есть "{seen[key]}"): распаковщик оставит один')
        seen[key] = e.name


def plan_archive(*, notice: str, report: str | None = None,
                 report_artifact: str | None = None, pdf: str | None = None,
                 pdf_artifact: str | None = None, template_artifact: str | None = None,
                 sources=(), source_texts=(), diagrams=(), diagram_texts=(),
                 solution: str = "") -> list[Entry]:
    """Опись архива. `notice` обязателен и обязан содержать строку про незапущенный код.

    Отчёт приходит одним из двух путей, и оба законны. `report` — имя готового
    файла в каталоге сборки (шаблонный путь: `build_report` пишет DOCX в `out/`).
    `report_artifact` — идентификатор артефакта (живой режим: документ собран из
    списка блоков в памяти и положен `put_artifact`). Второго знания о том, где
    лежат байты, `kadai` не заводит: и то и другое — не путь.

    `sources` — пары `(имя файла, идентификатор артефакта)`, `source_texts` —
    пары `(имя файла, текст)`: код, сочинённый моделью, живёт блоком работы, а
    не материалом, и нести его в архив приходится текстом. `diagrams` — пары
    `(ключ блока, идентификатор)`: схема называется тем блоком, который на неё
    ссылается, иначе по архиву не понять, какая схема к какому разделу.

    `diagram_texts` — те же пары, но со схемой строкой. Два пути здесь не
    прихоть: значение блока `diagram` держит схему **либо** идентификатором
    артефакта, либо XML'ем, и обратно в запись пишется всегда XML (движок
    отчётов идентификатор схемы наружу не эмитит — `hokoku.wire`). Значит схема,
    построенная петлёй, доезжает сюда текстом, и знать про это надо здесь:
    иначе `схемы/` в архиве молча пусты, а человек узнаёт об этом, распаковав.
    """
    if NOT_RUN not in (notice or ""):
        raise KadaiError("в «как-это-собрано.txt» нет строки о том, что код не "
                         "запускался. Без неё архив обещает проверенный код: "
                         "соберите текст через notice_text()")
    if report and report_artifact:
        raise KadaiError("отчёт назван и файлом сборки, и артефактом: источник байтов "
                         "ровно один, иначе в архив уедет неизвестно который")
    entries: list[Entry] = []
    if report_artifact:
        entries.append(Entry(REPORT_DOCX, {"artifact": report_artifact}))
    elif report:
        entries.append(Entry(safe_leaf(report), {"output": report}))
    if pdf_artifact:
        entries.append(Entry(REPORT_PDF, {"artifact": pdf_artifact}))
    elif pdf:
        entries.append(Entry(safe_leaf(pdf), {"output": pdf}))
    if template_artifact:
        entries.append(Entry(TEMPLATE, {"artifact": template_artifact}))
    for name, art in sources:
        entries.append(Entry(in_dir(DIR_SOURCES, name), {"artifact": art}))
    for name, text in source_texts:
        entries.append(Entry(in_dir(DIR_SOURCES, name), {"text": str(text)}))
    for key, art in diagrams:
        entries.append(Entry(in_dir(DIR_DIAGRAMS, f"{key}.drawio"), {"artifact": art}))
    for key, xml in diagram_texts:
        entries.append(Entry(in_dir(DIR_DIAGRAMS, f"{key}.drawio"), {"text": str(xml)}))
    if solution:
        entries.append(Entry(SOLUTION, {"text": solution}))
    entries.append(Entry(NOTICE, {"text": notice}))
    check_names(entries)
    return entries


def notice_text(*, work_id: str, profile: str, wishes: str = "", requirement: str = "",
                stages=(), spent: dict | None = None, versions: dict | None = None,
                problems=()) -> str:
    """Текст «как-это-собрано.txt»: чем работа была, как собиралась и чего мы не проверяли.

    Собирается всегда и целиком: файл отвечает на вопрос «откуда это взялось»
    через полгода, когда прогона уже нет ни в чьей памяти. Номера версий
    значений на момент сборки кладутся сюда же — без них по архиву не понять,
    какой именно вариант отчёта в нём лежит.
    """
    lines = ["Как собрана эта работа", "",
             f"Работа: {work_id}", f"Вид работы: {profile}"]
    if wishes:
        lines += ["", "Пожелания (дословно):", _quote(wishes)]
    if requirement:
        lines += ["", "Как мы поняли задание:", _quote(requirement)]
    if stages:
        lines += ["", "Стадии:"]
        lines += [f"  {s.get('name')}: {s.get('state')}"
                  + (f" — {s['note']}" if s.get("note") else "") for s in stages]
    if spent:
        share = spent.get("share")
        cap = spent.get("cap")
        lines += ["", "Расход: "
                  + f"{spent.get('units', 0):.0f} приведённых единиц"
                  + (f", потолок {cap:.0f}" if cap else ", потолка нет")
                  + (f" ({share:.0%})" if share is not None else "")
                  + f"; оценено, а не измерено: {spent.get('estimated_share', 0):.0%}"]
    if versions:
        lines += ["", "Версии значений на момент сборки:"]
        lines += [f"  {key}: v{n}" for key, n in sorted(versions.items())]
    if problems:
        lines += ["", "Замечания сборки:"]
        lines += [f"  [{p.get('level')}] {p.get('module')}/{p.get('code')}"
                  + (f" ({p['key']})" if p.get("key") else "")
                  + f": {p.get('message')}" for p in problems]
    lines += ["", NOT_RUN, ""]
    return "\n".join(lines)


def solution_md(sections=()) -> str:
    """`решение.md` из готовых пар «заголовок → текст».

    Текст приходит готовым, а не добывается из значений тегов здесь: значение —
    это `wire`, то есть знание `hokoku`, и разбирать его в `kadai` значило бы
    завести второе место, которое понимает форму значения.
    """
    out = []
    for title, text in sections:
        out += [f"## {title}", "", str(text).strip(), ""]
    return "\n".join(out)


def _quote(text: str) -> str:
    """Чужой текст в нашем файле — с отступом, чтобы его нельзя было спутать с нашим."""
    return "\n".join("  | " + line for line in str(text).splitlines())


def pack(project, entries, *, name: str = "") -> str:
    """Сложить архив. Складывает проект: он единственный знает пути.

    Возвращается **имя** архива, а не путь: путь на экране у человека и в логах
    сайта — это то, ради чего вся опись собирается идентификаторами.
    """
    check_names(entries)
    door = method(project, "pack", "архив")
    entries = [e.as_dict() for e in entries]
    return door(entries, name=safe_leaf(name)) if name else door(entries)


__all__ = ["Entry", "NOT_RUN", "NOTICE", "SOLUTION", "TEMPLATE", "REPORT_DOCX", "REPORT_PDF",
           "DIR_SOURCES", "DIR_DIAGRAMS", "SOURCE_EXT", "source_name",
           "safe_leaf", "in_dir", "check_names", "plan_archive", "notice_text",
           "solution_md", "pack"]
