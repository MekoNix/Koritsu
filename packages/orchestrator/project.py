"""
project — состояние одной работы студента на диске.

Это единственное место пакета, которое знает про пути. Правило проверяемо
грепом: `os.path.join` встречается только здесь. Цена нарушения известна заранее
— переезд на SQLite превратится в переписывание службы вместо добавления
второго класса с теми же методами, потому что `fill` и `build` начнут строить
пути сами.

**Версионируем значения тегов, а не документ** (действующее решение проекта).
История версий отчёта из этого получается бесплатно: отчёт — детерминированная
функция набора значений, и «версия отчёта» это просто набор номеров версий на
момент сборки. Обратный порядок (версионировать собранный DOCX) стоил бы
хранения мегабайтов ради правки одного абзаца и не дал бы ответа на вопрос
«кто поставил это значение» — а именно он и нужен, когда часть текста написала
модель, а часть человек.

Отсюда `source` у каждой версии: `agent` (модель), `manual` (человек), `file`
(взято из материала), `template` (умолчание шаблона). Без него значение,
исправленное человеком, неотличимо от сгенерированного, и прогон уровня 2 молча
затрёт правку — беда, которую замечают на кафедре.

Раскладка на диске:

    <path>/project.json            имя, endpoint по умолчанию, шаблон, лимит
    <path>/manifest.json           manifest_to_json (hokoku)
    <path>/materials/              materials.Store(root) — как есть
    <path>/artifacts/<id>          плоский каталог: шаблон, XML схем, картинки
    <path>/artifacts/notices/<id>.json  замечания того, кто артефакт построил
    <path>/values/<slug>/vN.json   {"version": шапка, "value": значение wire}
    <path>/blocks/vN.json          {"version": шапка, "blocks": [блок, …]} — живой режим
    <path>/state/<slug>.json       ход стадий сценария: put_state / state
    <path>/derived.jsonl           журнал производных артефактов (append-only)
    <path>/runs/<id>.json          прогон: уровень, endpoint, метка рамки, шаги
    <path>/journal.jsonl           по записи на вызов модели (форма В.4 слоя llm)
    <path>/out/                    workdir для build_report и готовый архив

Каталог, а не один JSON: версия пишется отдельным файлом, правки разных тегов не
спорят за один файл, и `git diff` каталога показывает правку тега, а не
перезапись простыни. Файл версии при этом **создаётся** и никогда не
заменяется (`_write_new`): занятый номер — это чужая запись, и молчаливое
«успешно» на ней означало бы потерянную правку.

Путь задаётся снаружи, умолчания в коде нет: служба открывает то, что ей дали.
Умолчание здесь означало бы, что лаборатория, CI и рабочая машина расходятся
молча.
"""
from __future__ import annotations

import datetime
import hashlib
import io
import json
import os
import re
import secrets
import zipfile
from dataclasses import asdict, dataclass, field

import hokoku
import llm
import materials
from kyotsu import Notice

from .errors import OrchestratorError, hint

# Кто поставил значение. Список закрытый: `source` разбирают и интерфейс, и
# прогон уровня 2 (чужое не трогать), и опечатка в нём означала бы значение,
# которое никто не считает своим.
SOURCES = ("agent", "manual", "file", "template")

# Идентификатор артефакта — те же 16 hex, что у `materials.material_id`: один и
# тот же файл, положенный и в материалы, и в артефакты, получает один
# идентификатор, и `resolve_artifact` не обязан помнить, откуда он взялся.
ARTIFACT_ID_LEN = 16

_VERSION_FILE_RE = re.compile(r"\Av(\d+)\.json\Z")

# Сколько раз пробуем занять номер версии, прежде чем сдаться вслух. Каждая
# попытка — чужая запись, обогнавшая нашу; сотня подряд означает не гонку, а
# что-то другое (чужой процесс в цикле, сломанный каталог), и молчать про это
# нельзя: тихая сдача — это опять потерянное значение.
_WRITE_ATTEMPTS = 100

# Сколько версий значения тега хранится. Хранится история правок, а не архив:
# человек возвращается на шаг-другой назад, а не на двадцатый прогон трёхнедельной
# давности, — и каталог значений на длинной работе иначе растёт без конца, унося
# место в квоте за то, чего никто не откроет. Старшие версии удаляются при записи
# новой; текущая, разумеется, остаётся всегда.
ВЕРСИЙ_ХРАНИМ = 5


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def _json_bytes(obj) -> bytes:
    return json.dumps(obj, ensure_ascii=False, indent=2).encode("utf-8")


@dataclass
class Version:
    """Шапка одной версии значения — самоописанная и потому переживающая переезд.

    Всё, что нужно, чтобы объяснить значение через полгода, лежит в самой
    записи: кто поставил (`source`), в каком прогоне (`run`), какой моделью
    (`endpoint`, `model`), по какому промпту (`prompt_hash`) и по какому
    манифесту (`manifest_version`). Цена ошибки, если этого не писать сразу:
    первые недели работы окажутся необъяснимыми — дописать поля задним числом
    в уже сохранённые версии нельзя.
    """

    n: int
    key: str
    at: str
    source: str
    run: str | None = None
    flags: list = field(default_factory=list)
    endpoint: str = ""
    model: str = ""
    prompt_hash: str = ""
    manifest_version: int = 1
    stop: str = ""
    usage: dict = field(default_factory=dict)


@dataclass
class BlockVersion:
    """Шапка одной версии списка блоков — живой режим (без шаблона).

    Версионируется **список целиком**, а не блок по отдельности, и это решение,
    а не упрощение. Работа в живом режиме — упорядоченный список, и половина
    правок меняет не значение блока, а сам порядок: убрали, переставили,
    вставили посередине.
    Версия отдельного блока на такие правки не отвечает вовсе — «вернуть как
    было» после перестановки пришлось бы собирать из версий десяти блоков,
    угадывая, какие из них были одновременны. Список целиком отвечает на это
    одним номером.

    Плата названа честно: правка одного абзаца пишет весь список заново. Список
    — десятки блоков по несколько килобайт, то есть цена версии измеряется
    сотнями килобайт на правку, и это дёшево ровно до тех пор, пока в блоках
    лежат тексты, а не картинки. Картинок в них и не лежит: `image` и `diagram`
    хранят идентификатор артефакта, а байты — в `artifacts/`.

    `source` — тот же закрытый список `SOURCES`, что у версий тегов, и второго
    словаря пометок не заводится: интерфейс разбирает `source` одним разбором,
    и «model» рядом с «agent» означало бы, что одно и то же названо дважды.
    Пометка стоит и на версии (кто сделал эту правку), и на самом блоке (кто
    написал то, что в нём лежит): без второй прогон текста затирал бы правку
    человека — ровно та беда, ради которой `source` заводился у тегов.
    """

    n: int
    at: str
    source: str
    note: str = ""
    run: str | None = None
    count: int = 0


# Поля записи блока на диске. Список закрытый: поле, которого здесь нет, — это
# опечатка или чужая модель блока, и молча положить его на диск значит потерять
# его при первом же чтении.
#
#   key    — адрес блока, нормализованный `wire.norm_key`; по нему на блок
#            ссылаются инструменты и `{ref:}`; переименованию не подлежит;
#   kind   — вид блока словом `hokoku.live.KINDS` (виды значений плюс `heading`);
#   value  — значение в форме `wire`, всегда; место под текст выражается
#            черновиком (`hokoku.live.draft`), а не пустотой: пустое значение
#            движок отчётов считает ошибкой, и «пустая заготовка» не собралась
#            бы даже для показа человеку;
#   label  — имя для человека: оглавление и выбор блока щелчком;
#   source — кто написал значение: `SOURCES`; пусто — берётся у версии.
#
# Первые четыре — это ровно `hokoku.live.Block`, разобранный на JSON; пятое
# принадлежит хранилищу и живому режиму не нужно: «кто написал» — вопрос версий,
# а не документа. Отсюда и разрез: список правит `hokoku.live`, помнит его —
# проект, а переводит одно в другое `orchestrator.live`.
BLOCK_FIELDS = ("key", "kind", "value", "label", "source")


@dataclass
class Run:
    """Прогон: одна граница, внутри которой метка рамки постоянна.

    `mark` хранится в записи прогона не для отчётности: по ней потом
    проверяется, той ли меткой были обёрнуты файлы студента. Метка одна на
    прогон и разная между прогонами (развилка И.1) — метка, которую модель
    видела, может утечь в значение тега, а значение тега человек копирует к себе
    в файл.

    Заполняет поле `fill._seal` (выпуск по всем недоверенным текстам сразу) и он
    же передаёт ту же метку в вызов через `frame_mark`. Записать её, но не
    передать, — худший из вариантов: в `runs/<id>.json` лежала бы метка, которой
    модель никогда не видела, а выглядело бы это как ответ на вопрос «чем были
    обёрнуты файлы».
    """

    id: str
    level: int
    endpoint: str
    started: str
    mark: str = ""
    steps: list = field(default_factory=list)
    finished: str | None = None
    outcome: str = ""


def artifact_id(data: bytes) -> str:
    """Идентификатор артефакта по содержимому: тот же файл — тот же идентификатор."""
    return hashlib.sha256(data).hexdigest()[:ARTIFACT_ID_LEN]


def template_tags(template: bytes) -> list[str]:
    """Ключи тегов шаблона DOCX, в порядке документа. Не читается ни один путь.

    Дверь для службы: та хранит шаблоны человека отдельно от проектов
    (`api.templates`) и обязана показать в списке, сколько в шаблоне тегов, — до
    того, как по нему заведут работу. Считать их вторым разбором DOCX было бы
    вторым описанием того, что такое тег, и разошлось бы с манифестом на первой
    же правке `hokoku.extract_tags`. Поэтому здесь ровно то же самое, чем
    манифест строится при создании проекта (`Project.create`), и ни строкой
    больше.

    Байты, а не путь, — по тому же правилу, что у `Project.create(template=)`:
    путей в проекте не хранится, и знание о томе принадлежит службе.

    Не-DOCX и битый архив поднимают `HokokuError`; служба переводит её в свой
    отказ (`bad_template`), потому что в тексте беды бывает путь.
    """
    if not isinstance(template, (bytes, bytearray)):
        raise OrchestratorError("template — байты DOCX: путей в проекте не хранится")
    return list(hokoku.manifest_from_template(bytes(template)).tags)


# Имена типов значений наружу: те же слова, что стоят в поле `type` значения и
# в манифесте. Служба перечисляет их человеку («тип — одно из…»), а своего
# списка завести не может — `hokoku` ей не виден.
VALUE_TYPES: tuple[str, ...] = tuple(hokoku.wire.VALUE_TYPES)

# Имя поля из беды `wire`: она называет его по-русски и в кавычках («поле
# "rows"», «нет обязательного поля "latex"»). Разбирается здесь, а не в службе:
# как `hokoku` называет свои поля — знание этой стороны разреза.
_ПОЛЕ_БЕДЫ = re.compile(r'по(?:ле|ля) "([^"]+)"')


def _slug(key: str) -> str:
    """Имя каталога для ключа тега: читаемое начало плюс хвост от sha256.

    Ключ тега — произвольный текст в NFC (кириллица, точки, дефисы), и класть
    его в имя каталога как есть нельзя: разделитель пути, `..`, длина за предел
    файловой системы и разная нормализация имён в macOS дали бы либо запись мимо
    проекта, либо два ключа в одном каталоге. Хвост от sha256 делает имя
    однозначным, читаемое начало оставляет `git diff` осмысленным.

    Обратно ключ из имени каталога НЕ разбирается никогда: он лежит в шапке
    версии (`Version.key`), и это единственный источник правды.
    """
    safe = "".join(c if (c.isalnum() or c in "-_.") else "_" for c in key)[:40]
    safe = safe.strip("._") or "tag"
    return f"{safe}-{hashlib.sha256(key.encode('utf-8')).hexdigest()[:8]}"


def _safe_leaf(name, what: str) -> str:
    """Одно звено имени файла — или отказ. Разделителей не пропускает вовсе.

    Отказ, а не тихая подчистка: подрезав `../`, мы положили бы файл под именем,
    которого человек не называл, и не сказали бы ему об этом. Проверка стоит
    здесь, потому что имя приходит из данных сценария, а путь складывается тут.
    """
    leaf = str(name or "")
    if not leaf or leaf in (".", "..") or leaf != leaf.strip():
        raise OrchestratorError(f"{what}: {name!r} — пустое, служебное или с пробелами по краям")
    bad = [c for c in leaf if c in "/\\:" or ord(c) < 32]
    if bad:
        raise OrchestratorError(
            f"{what}: {leaf!r} — не имя, а путь (запрещённые знаки: "
            + ", ".join(repr(c) for c in dict.fromkeys(bad)) + ")")
    return leaf


def _entry_bytes(project, entry, number: int) -> tuple[str, bytes]:
    """Одна запись описи → (имя в архиве, байты). Источник ровно один из трёх."""
    if not isinstance(entry, dict):
        raise OrchestratorError(
            f"запись {number} описи — объект, а не {type(entry).__name__}")
    inner = str(entry.get("name") or "")
    if not inner or inner.startswith("/") or "\\" in inner or ".." in inner.split("/"):
        raise OrchestratorError(
            f"запись {number} описи: имя в архиве {inner!r} — пустое или уводит из архива")
    sources = [k for k in ("artifact", "output", "text") if k in entry]
    if len(sources) != 1:
        raise OrchestratorError(
            f"запись {number} описи ({inner!r}): источник ровно один из "
            "artifact, output, text, а дано "
            + (", ".join(sources) if sources else "ни одного"))
    kind = sources[0]
    if kind == "artifact":
        return inner, project.resolve_artifact(entry["artifact"])
    if kind == "output":
        with open(project._output_path(entry["output"]), "rb") as f:
            return inner, f.read()
    text = entry["text"]
    if not isinstance(text, str):
        raise OrchestratorError(
            f"запись {number} описи ({inner!r}): text — строка, а не {type(text).__name__}")
    return inner, text.encode("utf-8")


def _blocks_json(blocks, *, source: str) -> list:
    """Список блоков в форму, которая ложится на диск, — или внятный отказ.

    Принимаются и словари, и объекты с теми же полями (модель блока `hokoku`):
    служба обязана быть полезной обеим сторонам, а различать их по типу значит
    завести здесь знание о чужом классе. Утиная проверка — по именам полей.
    """
    if not isinstance(blocks, (list, tuple)):
        raise OrchestratorError(
            f"список блоков — список, а не {type(blocks).__name__}")
    out: list = []
    seen: dict = {}
    for number, item in enumerate(blocks, start=1):
        block = _block_json(item, number, source)
        key = block["key"]
        if key in seen:
            # Два блока с одним ключом — это потерянный блок: ссылка `{ref:}` и
            # инструмент агента адресуют ключом, и второй адресат молча исчез бы.
            raise OrchestratorError(
                f"блоки {seen[key]} и {number} с одним ключом {key!r}: "
                "ключ — адрес блока, и двух одинаковых адресов не бывает")
        seen[key] = number
        out.append(block)
    return out


def _block_json(item, number: int, source: str) -> dict:
    """Один блок: известные поля, нормализованный ключ, согласованный вид."""
    if isinstance(item, dict):
        raw = dict(item)
    else:
        raw = {name: getattr(item, name) for name in BLOCK_FIELDS if hasattr(item, name)}
        if not raw:
            raise OrchestratorError(
                f"блок {number} — {type(item).__name__}: ни одного известного поля "
                f"({', '.join(BLOCK_FIELDS)})")
    unknown = [name for name in raw if name not in BLOCK_FIELDS]
    if unknown:
        raise OrchestratorError(
            f"блок {number}: поля {unknown[0]!r} у блока нет"
            f"{hint(unknown[0], BLOCK_FIELDS)}; известные: {', '.join(BLOCK_FIELDS)}")
    key = hokoku.wire.norm_key(str(raw.get("key") or ""))
    if not key:
        raise OrchestratorError(f"блок {number} без ключа: ключ — адрес блока")
    kind = str(raw.get("kind") or "")
    if kind not in hokoku.live.KINDS:
        raise OrchestratorError(
            f"блок {key!r}: вида {kind!r} не бывает ({', '.join(hokoku.live.KINDS)})"
            f"{hint(kind, hokoku.live.KINDS)}")
    value = raw.get("value")
    if value is None:
        raise OrchestratorError(
            f"блок {key!r} без значения: место под содержимое — это черновик "
            "(hokoku.live.draft), а не пустота")
    if not isinstance(value, dict):
        # Типизированное значение `hokoku` переводим сами: вызывающему не должно
        # быть важно, в каком виде он держит значение в руках.
        value = hokoku.value_to_json(value)
    внутри = str(value.get("type") or "")
    # Заголовок — не отдельный тип значения, а `markdown` из одной строки
    # «## Название» (решение живого режима: `render` уже ставит на него стиль
    # Heading N, и поле TOC его находит). Значит вид блока и тип значения
    # совпадают у всех, кроме заголовка, — и проверка знает ровно это.
    ждём = hokoku.live.TEXT_KINDS if kind == "heading" else (kind,)
    if внутри not in ждём:
        raise OrchestratorError(
            f"блок {key!r} объявлен видом {kind!r}, а значение в нём {внутри!r}: "
            "вид блока и тип значения — одно и то же утверждение")
    own = str(raw.get("source") or "") or source
    if own not in SOURCES:
        raise OrchestratorError(
            f"блок {key!r}: source — {', '.join(SOURCES)}, а не {own!r}"
            f"{hint(own, SOURCES)}")
    return {"key": key, "kind": kind, "value": value,
            "label": str(raw.get("label") or ""), "source": own}


class Project:
    """Каталог одной работы студента: материалы, значения с версиями, манифест, журнал.

    Наружу — только методы. Ни `fill`, ни `build`, ни будущий HTTP-маршрут не
    знают, что `values/` это каталог: SQLite придёт вторым классом с теми же
    методами, а не переписыванием службы.

    **Мутирует только `set_value`.** Через неё идут уровень 1, уровень 2,
    будущий инструмент агента `set_tag` и будущий `PUT /values`: второй путь
    записи — это второй набор правил про версии, флаги и `source`, и они
    разойдутся.

    Одна точка записи — не то же самое, что защита от одновременной записи, и
    раньше здесь стояло обещание «рассогласоваться нечему по построению», которое
    было неправдой: два писателя читали один и тот же номер версии и второй
    молча затирал первого. Сегодня это держит механика — версия создаётся, а не
    заменяется (`_write_new`), — и обещание звучит точнее: **ни одна запись не
    пропадёт**. Порядок одновременных записей при этом не наш: кто занял номер
    вторым, тот и стал текущим.
    """

    def __init__(self, path: str):
        self.path = os.path.abspath(path)
        if not os.path.isdir(self.path):
            raise OrchestratorError(f"каталога проекта нет: {self.path}")
        self._journal: llm.Journal | None = None

    # ── создание ────────────────────────────────────────────────────────────
    @classmethod
    def create(cls, path: str, *, template: bytes | None = None, name: str = "",
               endpoint: str = "", cap_units: float | None = None) -> "Project":
        """Новый проект: каталог, шаблон артефактом, заготовка манифеста по тегам.

        Манифест строится сразу, а не при первом обращении: без него нельзя ни
        показать список тегов, ни собрать промпт, а `manifest_from_template`
        читает шаблон — единственную вещь, которую при создании уже держат в
        руках. Проект без манифеста был бы состоянием, из которого не выйти,
        не прочитав DOCX второй раз.

        `template=None` — «проект без шаблона»: документ строит
        `hokoku.blank_document()`, то есть пустой DOCX со стилями, полями и
        нумерацией. Знание о том, как выглядит документ с нуля, лежит здесь, а
        не у службы: `api` про `hokoku` не знает и знать не должен
        (правило разреза), а без этой ветки ему пришлось бы либо требовать файл
        на каждом создании, либо нарушить границу.

        В `project.json` при этом пишется `template_source`: `"blank"` —
        документ построен нами, `"given"` — принесён человеком. Различать их
        надо: пустой документ можно молча заменить первым же принесённым
        шаблоном, а чужой — нельзя, там решения человека.

        Поверх существующего проекта — отказ. Раньше вызов проходил и строил
        манифест **без `base`**: промпты, `limits`, `depends_on`, поправленные
        типы и снятые пометки `guessed` исчезали разом, а значения оставались и
        ссылались на решения, которых больше нет. «Создать» и «сменить шаблон» —
        разные намерения, и второе делает `update_template`, который решения
        человека переносит.
        """
        свой = template is None
        if свой:
            template = hokoku.document_bytes(hokoku.blank_document())
        elif not isinstance(template, (bytes, bytearray)):
            raise OrchestratorError("template — байты DOCX: путей в проекте не хранится")
        os.makedirs(path, exist_ok=True)
        project = cls(path)
        if os.path.isfile(project._settings_path()):
            raise OrchestratorError(
                f"в {project.path} уже есть проект: создание стёрло бы его манифест. "
                "Сменить шаблон — update_template")
        art = project.put_artifact(bytes(template), name="шаблон")
        project._write_json(project._settings_path(), {
            "name": name, "endpoint": endpoint, "template": art,
            "template_source": "blank" if свой else "given",
            "cap_units": cap_units, "created": _now()})
        project.save_manifest(hokoku.manifest_from_template(bytes(template)))
        return project

    def update_template(self, template: bytes) -> hokoku.Manifest:
        """Новый DOCX вместо прежнего; решения человека переезжают в новый манифест.

        Смысл целиком в `base=`: `manifest_from_template` умеет обновлять
        манифест правильно — тег добавили, заводим запись; тег убрали, ставим
        `missing`, но не удаляем; изменилась метка, обновляем метку, а промпт не
        трогаем. Без `base` та же функция строит манифест с нуля, и цена этого
        измеряется не удобством: значения тегов остаются на месте и начинают
        ссылаться на промпты и лимиты, которых больше нет.

        Переименование тега мы не видим (оно выглядит как «убрали и добавили»);
        перенести промпт может только человек, а подсказку об этом даёт
        `hokoku.check_manifest`.
        """
        if not isinstance(template, (bytes, bytearray)):
            raise OrchestratorError("template — байты DOCX: путей в проекте не хранится")
        settings = self.settings()
        settings["template"] = self.put_artifact(bytes(template), name="шаблон")
        # Пустой документ, построенный нами при создании, перестал быть нашим:
        # дальше это шаблон человека, и молча заменять его больше нельзя.
        settings["template_source"] = "given"
        self.save_settings(settings)
        m = hokoku.manifest_from_template(bytes(template), base=self.manifest())
        self.save_manifest(m)
        return self.manifest()

    # ── настройки, шаблон, манифест ─────────────────────────────────────────
    def settings(self) -> dict:
        """project.json целиком. Читается, а не кэшируется: имя и endpoint правит человек."""
        return self._read_json(self._settings_path(), {})

    def save_settings(self, d: dict) -> None:
        self._write_json(self._settings_path(), d)

    def template(self) -> bytes:
        """Байты шаблона. Шаблон — обычный артефакт, поэтому особого пути к нему нет."""
        art = self.settings().get("template")
        if not art:
            raise OrchestratorError("в проекте не назван шаблон (project.json → template)")
        return self.resolve_artifact(art)

    def template_artifact(self) -> str:
        art = self.settings().get("template")
        if not art:
            raise OrchestratorError("в проекте не назван шаблон (project.json → template)")
        return art

    def manifest(self) -> hokoku.Manifest:
        d = self._read_json(self._manifest_path(), None)
        if d is None:
            raise OrchestratorError("в проекте нет манифеста (manifest.json)")
        return hokoku.manifest_from_json(d)

    def set_tag_prompt(self, key: str, prompt: str) -> str:
        """Задание модели на один тег — то, что человек пишет рядом с полем.

        Отдельным методом, а не правкой манифеста снаружи: манифест умеет
        считать свои правки только через `save_manifest`, и служба, которой
        движок отчётов не виден вовсе (правило разреза), иначе не смогла бы
        поменять единственное поле, которое человек и правит руками.

        Тега нет в манифесте — отказ: писать задание тегу, которого нет в
        бланке, значит копить промпты, которые никуда не уедут.
        """
        key = hokoku.wire.norm_key(str(key))
        m = self.manifest()
        spec = m.tags.get(key)
        if spec is None:
            raise OrchestratorError(f"тега {key!r} в манифесте нет")
        spec.prompt = str(prompt)
        self.save_manifest(m)
        return spec.prompt

    def save_manifest(self, m: hokoku.Manifest) -> None:
        """Манифест на диск; `manifest_version` ставится здесь и только здесь.

        Счётчик правок обязан подниматься при записи, иначе он врёт молча: поле
        есть, в шапке каждой версии значения и в задании сборки стоит одно и то
        же число, и «по какому манифесту получено это значение» получает
        постоянный неверный ответ, выглядящий как ответ. Счётчик считает
        **правки**, а не сохранения: запись без изменений его не двигает, иначе
        по номеру нельзя понять, менялось ли что-нибудь.

        Число ставится, а не увеличивается на месте: `manifest_from_template`
        с `base=` тоже прибавляет единицу, и складывать оба прибавления значило
        бы считать одну правку за две.
        """
        d = hokoku.manifest_to_json(m)
        stored = self._read_json(self._manifest_path(), None)
        if stored is not None:
            прежний = int(stored.get("manifest_version", 1))
            same = {k: v for k, v in stored.items() if k != "manifest_version"} \
                == {k: v for k, v in d.items() if k != "manifest_version"}
            d["manifest_version"] = прежний if same else прежний + 1
        else:
            d["manifest_version"] = 1
        # Тот же номер — и в объект вызывающего: он держит его в руках и кладёт
        # в шапку версии значения, и разойтись с диском это число не должно.
        m.manifest_version = d["manifest_version"]
        self._write_json(self._manifest_path(), d)

    # ── материалы и артефакты ───────────────────────────────────────────────
    def store(self) -> materials.Store:
        """Хранилище материалов проекта — `materials.Store` как есть, без надстроек."""
        return materials.Store(self._materials_dir())

    def add_material(self, data: bytes, name: str, *, do_ocr: bool = True,
                     condition: bool = False) -> materials.Material:
        """Чужой файл в проект: проверка недоверенного DOCX, потом `Store.add`.

        Единственная дверь для файла, пришедшего от человека, и она здесь, а не
        в `materials`, по одной причине: защита от zip-slip, zip-bomb и XXE
        живёт в `hokoku.validate_docx`, а `materials` импортировать `hokoku` не
        имеет права (правило разреза). Через `Project.store().add` тот же файл
        доедет без проверки — это известный остаточный риск, и закрывается он
        тем, что чужой файл кладут этим методом.

        Скан читается OCR (`do_ocr=True`): фото методички — обычный вход, и
        отказывать на нём нельзя. Молча доверять распознанному тоже нельзя —
        ошибка в формуле даёт безупречно решённую **чужую** задачу, — поэтому
        распознанное обязательно показывается человеку до работы. Показывать
        есть что: текст лежит в `store().read(id)`, а на картинке без текстового
        слоя он весь и есть распознанный.

        `condition=True` — это условие задачи. Пишется в настройки
        идентификатором (`condition`), а не отдельной копией файла: копия
        разошлась бы с материалом, и «то ли это условие, по которому считали»
        осталось бы без ответа.
        """
        if not isinstance(data, (bytes, bytearray)):
            raise OrchestratorError(
                f"материал — байты, а не {type(data).__name__}: путей в проекте не хранится")
        if not str(name or "").strip():
            raise OrchestratorError("у материала должно быть имя: по нему его узнаёт человек")
        data = bytes(data)
        if data[:4] == b"PK\x03\x04" and str(name).lower().endswith((".docx", ".docm")):
            # Недоверенный ZIP. `validate_docx` бросает своё — переводим в нашу
            # ошибку: человек кладёт файл через службу и про `hokoku` не знает.
            try:
                hokoku.validate_docx(data)
            except hokoku.DocxValidationError as exc:
                raise OrchestratorError(f"файл {name!r} не принят: {exc}") from None
        material = self.store().add(data, name=str(name), do_ocr=do_ocr)
        if condition:
            self.set_condition(material.id)
        return material

    def set_condition(self, material_id: str) -> None:
        """Назвать материал условием задачи. Материал обязан существовать.

        Отдельно от `add_material`, потому что человек подтверждает распознанное
        **после** приёма файла: до подтверждения условие есть материал, а не
        условие, и порядок этот менять нельзя.
        """
        self.store().get(str(material_id))                 # нет такого — ошибка materials
        settings = self.settings()
        settings["condition"] = str(material_id)
        self.save_settings(settings)

    def condition(self) -> str | None:
        """Идентификатор материала-условия или None, если его не называли."""
        return self.settings().get("condition") or None

    def put_artifact(self, data: bytes, *, name: str = "", notices=()) -> str:
        """Байты в хранилище артефактов → идентификатор.

        Адресация по содержимому, а не по имени: `name` нигде не участвует и
        принимается только для читаемости вызова. Одинаковые байты дважды —
        один артефакт, поэтому повторная сборка схемы не плодит мусор.

        `notices` — замечания того, кто артефакт построил (`kyotsu.Notice`;
        сегодня это `fragmos`: «в схему не вошло: goto case»). Они кладутся
        рядом с артефактом, а не в значение тега, по двум причинам: замечание
        описывает **схему**, а не тег (одну и ту же схему могут поставить в два
        тега, и правда о ней одна), и живёт оно ровно столько, сколько живёт
        артефакт. Без записи на диск замечание умирало бы вместе с прогоном, а
        человек смотрит на отчёт позже и другим глазом.
        """
        art = artifact_id(bytes(data))
        path = os.path.join(self._artifacts_dir(), art)
        if not os.path.isfile(path):
            os.makedirs(self._artifacts_dir(), exist_ok=True)
            self._write_bytes(path, bytes(data))
        if notices:
            folder = os.path.join(self._artifacts_dir(), "notices")
            os.makedirs(folder, exist_ok=True)
            self._write_json(os.path.join(folder, f"{art}.json"),
                             [n.to_dict() for n in notices])
        return art

    def artifacts(self) -> list[str]:
        """Идентификаторы всего, что лежит в хранилище артефактов. По порядку.

        Нужно выгрузке файлов пользователя (`api/export` — архив материалов и
        артефактов): собрать её без описи хранилища
        невозможно, а складывать путь к `artifacts/` снаружи значило бы завести
        второе знание о раскладке проекта — то самое, которое разойдётся с этим
        при первом переименовании.

        Материалов здесь нет: они лежат в своём хранилище и перечисляются
        `store().list()`. `resolve_artifact` ищет и там, и тут, но это его дело —
        отдать байты по идентификатору, а не наше — смешать две описи в одну.

        Замечания (`artifacts/notices/`) не считаются: это каталог, а не
        артефакт, и его имя формы идентификатора не имеет.
        """
        folder = self._artifacts_dir()
        if not os.path.isdir(folder):
            return []
        return sorted(name for name in os.listdir(folder)
                      if len(name) == ARTIFACT_ID_LEN
                      and os.path.isfile(os.path.join(folder, name)))

    def artifact_notices(self, art_id: str) -> list:
        """Замечания, с которыми артефакт был построен. Пусто — их не было.

        Возвращается общая форма (`kyotsu.Notice`), а не словарь: список
        замечаний проекта один, и разбирать половину его словарями, а половину
        полями значило бы завести второй разбор в интерфейсе.
        """
        path = os.path.join(self._artifacts_dir(), "notices", f"{str(art_id)}.json")
        out = []
        for raw in self._read_json(path, []) or []:
            if not isinstance(raw, dict):
                continue
            out.append(Notice(module=raw.get("module", ""), level=raw.get("level", "warning"),
                              code=raw.get("code", ""), message=raw.get("message", ""),
                              file=raw.get("file"), line=raw.get("line")))
        return out

    def resolve_artifact(self, art_id: str) -> bytes:
        """Байты по идентификатору: сначала материалы, потом артефакты.

        Одна функция на всё, и её же получает `hokoku.build_report`: иначе
        картинка, загруженная студентом, и схема, построенная генератором,
        доставались бы разными путями, и вызывающему пришлось бы знать, какая
        где — то есть знать про хранилище то, что он знать не должен.

        Ловим только `MaterialsError` — «в материалах такого нет», законный ход
        поиска. Глушить всё подряд нельзя: ошибка чтения с диска выглядела бы
        как опечатка в идентификаторе, и человек искал бы пропавший файл вместо
        того, чтобы чинить ввод-вывод.
        """
        if not hokoku.wire.ARTIFACT_RE.match(str(art_id)) or ".." in str(art_id):
            raise OrchestratorError(f"{art_id!r} — не идентификатор артефакта")
        try:
            return self.store().blob(art_id)
        except materials.MaterialsError:
            pass                                # нет в материалах — ищем дальше
        path = os.path.join(self._artifacts_dir(), art_id)
        if not os.path.isfile(path):
            raise OrchestratorError(f"артефакта {art_id!r} нет ни в материалах, ни в artifacts/")
        with open(path, "rb") as f:
            return f.read()

    # ── значения ────────────────────────────────────────────────────────────
    def keys(self) -> list[str]:
        """Ключи, у которых есть хоть одна версия, в порядке ключа тега."""
        out = []
        root = self._values_dir()
        if not os.path.isdir(root):
            return out
        for slug in sorted(os.listdir(root)):
            head = self._head(os.path.join(root, slug))
            if head is None:
                continue
            record = self._read_json(os.path.join(root, slug, f"v{head}.json"), None)
            if record:
                out.append(record["version"]["key"])
        return sorted(out)

    def value(self, key: str) -> dict | None:
        """JSON текущей версии значения или None. Форма — та же, что у `wire`."""
        record = self._head_record(hokoku.wire.norm_key(str(key)))
        return None if record is None else record["value"]

    def values(self, *, keys=None) -> dict:
        """Текущие значения: {ключ тега: JSON}. Готовый вход `values_from_json`."""
        wanted = None if keys is None else {hokoku.wire.norm_key(str(k)) for k in keys}
        out: dict = {}
        for key in self.keys():
            if wanted is not None and key not in wanted:
                continue
            value = self.value(key)
            if value is not None:
                out[key] = value
        return out

    def versions(self, key: str) -> list[Version]:
        """Все версии значения по возрастанию номера. Пусто — значения не было."""
        key = hokoku.wire.norm_key(str(key))
        folder = os.path.join(self._values_dir(), _slug(key))
        out = []
        for n in self._numbers(folder):
            record = self._read_json(os.path.join(folder, f"v{n}.json"), None)
            if record:
                out.append(Version(**record["version"]))
        return out

    def head_version(self, key: str) -> Version | None:
        """Шапка текущей версии или None, если значения нет.

        Отдельно от `versions()`, потому что вопрос «кто написал то, что лежит
        сейчас» задаётся на каждом теге перед каждым прогоном, а история тега —
        это десятки файлов, и читать их все ради последнего значит платить
        диском за ответ, который лежит в одном файле.
        """
        record = self._head_record(hokoku.wire.norm_key(str(key)))
        return None if record is None else Version(**record["version"])

    def version(self, key: str, n: int) -> tuple[Version, dict]:
        """Конкретная версия: (шапка, значение). Прошлое читается, а не только текущее."""
        key = hokoku.wire.norm_key(str(key))
        folder = os.path.join(self._values_dir(), _slug(key))
        record = self._read_json(os.path.join(folder, f"v{int(n)}.json"), None)
        if record is None:
            known = self._numbers(folder)
            raise OrchestratorError(
                f"у тега {key!r} нет версии {n}"
                + (f" (есть {', '.join(str(x) for x in known)})" if known else ": значений нет"))
        return Version(**record["version"]), record["value"]

    def check_value(self, value_json: dict) -> dict | None:
        """Годится ли значение тега по форме своего типа. `None` — годится.

        **Дверь для службы, и заведена она ровно поэтому.** `api` не имеет
        права импортировать `hokoku` ни одной строкой (правило разреза,
        `tests/api/test_e2e.py::test_служба_не_тянет_hokoku`): служба,
        потянувшая движок отчётов, перестала бы собираться без python-docx.
        Проверять же форму значения служба обязана — иначе таблица без `rows`
        ложится на том и всплывает сборкой отчёта, то есть заданием, деньгами и
        пятью минутами ожидания. Значит проверку зовёт тот, кому `hokoku`
        знать положено.

        **Возвращается запись, а не исключение**, и это не небрежность: службе
        нужно не «что-то не так», а имя поля — она подписывает им место в
        редакторе значения (`where` отказа `invalid_value`). Разбирать русский
        текст беды на той стороне значило бы завести второе описание того, как
        `hokoku` называет свои поля.

        Запись: `stage` («wire» — форма, «artifact» — байтов нет в хранилище),
        `path` (место внутри `blocks`, обычно пусто) и `field` — имя поля,
        которое не так; пустое, если беда не про одно поле.

        `resolve_artifact` берётся свой: у картинки и схемы значение несёт
        идентификатор артефакта, и проверить его можно только сходив за
        байтами (заодно `wire` убедится, что картинка — картинка).
        """
        if not isinstance(value_json, dict):
            return {"stage": "wire", "path": "", "field": ""}
        # Тип разбирается отдельной строкой раньше `wire` не ради проверки, а
        # ради имени поля: о незнакомом типе `wire` говорит без него, а это
        # самая частая ошибка в правке значения руками.
        if value_json.get("type") not in VALUE_TYPES:
            return {"stage": "wire", "path": "", "field": "type"}
        try:
            hokoku.wire.value_from_json(value_json,
                                        resolve_artifact=self.resolve_artifact)
        except hokoku.WireError as беда:
            поле = _ПОЛЕ_БЕДЫ.search(беда.message)
            return {"stage": беда.stage, "path": беда.path,
                    "field": поле.group(1) if поле else ""}
        return None

    def set_value(self, key: str, value_json: dict, *, source: str,
                  run: str | None = None, flags=(), meta: dict | None = None) -> Version:
        """Единственная точка записи значения. Новая версия, старая остаётся.

        Перезаписи не бывает вовсе, и держится это не договорённостью, а
        механикой: файл версии **создаётся**, а не заменяется (`_write_new`), и
        занятый номер отдаёт `FileExistsError`. Наивная запись здесь была бы
        молчаливой потерей — номер читается по каталогу, а между чтением и
        записью успевает второй писатель, и `os.replace`, атомарный и потому
        бесшумный, стирает чужую версию целиком (замер: 120 записей двумя
        процессами → 76 файлов, ни одной ошибки).

        Что при столкновении происходит: опоздавший берёт следующий свободный
        номер, а не чужой файл. Значит обе правки уцелели, а текущей становится
        та, что записалась второй. Порядок двух одновременных правок мы не
        обещаем — обещаем, что ни одна не исчезнет; для «кто был последним»
        есть `at` и `run` в шапке.

        `value_json` не проверяется здесь на выразимость: это делает
        `wire.value_from_json` в `fill`, и делать это дважды значило бы завести
        второе описание того, что такое годное значение.

        История тега обрезается до `ВЕРСИЙ_ХРАНИМ` последних версий сразу после
        записи (`_обрезать_версии`). Обещание «ни одна одновременная запись не
        пропадёт» это не отменяет: обгонявшие друг друга писатели по-прежнему
        получают каждый свой номер, и обрезается только хвост истории.
        """
        if source not in SOURCES:
            raise OrchestratorError(
                f"source — {', '.join(SOURCES)}, а не {source!r}{hint(source, SOURCES)}")
        if not isinstance(value_json, dict):
            raise OrchestratorError(
                f"значение тега — объект JSON, а не {type(value_json).__name__}")
        key = hokoku.wire.norm_key(str(key))
        folder = os.path.join(self._values_dir(), _slug(key))
        os.makedirs(folder, exist_ok=True)
        info = meta or {}
        n = (self._head(folder) or 0) + 1
        for _ in range(_WRITE_ATTEMPTS):
            version = Version(n=n, key=key, at=_now(), source=source, run=run,
                              flags=list(flags),
                              endpoint=info.get("endpoint", ""),
                              model=info.get("model", ""),
                              prompt_hash=info.get("prompt_hash", ""),
                              manifest_version=int(info.get("manifest_version", 1)),
                              stop=info.get("stop", ""),
                              usage=dict(info.get("usage") or {}))
            if self._write_new(os.path.join(folder, f"v{n}.json"),
                               _json_bytes({"version": asdict(version),
                                            "value": value_json})):
                self._обрезать_версии(folder)
                return version
            # Номер занял кто-то другой. Берём следующий свободный: и наш
            # счётчик, и каталог — каталог мог уйти вперёд на много номеров.
            n = max(n + 1, (self._head(folder) or 0) + 1)
        raise OrchestratorError(
            f"не удалось записать значение тега {key!r} за {_WRITE_ATTEMPTS} попыток: "
            "номер версии занимают быстрее, чем мы пишем")

    def _обрезать_версии(self, folder: str) -> None:
        """Оставить в каталоге тега последние `ВЕРСИЙ_ХРАНИМ` версий.

        Сразу после записи, а не уборкой по расписанию: правило «версий не
        больше пяти» человек видит в истории тега, и список, который сначала
        показывает восемь, а через час пять, читается как пропажа.

        Номер версии при этом не переиспользуется — он растёт всегда (`_head`
        считает по максимуму имён в каталоге, а имена удалённых версий не
        возвращаются: следующий номер берётся от текущей, самой старшей).
        Неудача удаления молчит: файл мог унести другой писатель, и падать на
        уборке после успешно записанного значения нельзя.
        """
        лишние = self._numbers(folder)[:-ВЕРСИЙ_ХРАНИМ]
        for n in лишние:
            try:
                os.remove(os.path.join(folder, f"v{n}.json"))
            except OSError:
                pass

    def rollback(self, key: str, n: int) -> Version:
        """Вернуть значение версии `n` — новой версией, а не откатом номера.

        Так «Вернуть» видно в истории: иначе номер версии молча уменьшился бы, и
        два человека, глядя на «версию 3», видели бы разные значения. `source`
        сохраняется от той версии, которую вернули: значение по-прежнему
        написано ею, а не переписано заново.
        """
        old, value = self.version(key, n)
        return self.set_value(key, value, source=old.source, run=old.run,
                              flags=[*old.flags, f"вернули версию {n}"],
                              meta={"endpoint": old.endpoint, "model": old.model,
                                    "prompt_hash": old.prompt_hash,
                                    "manifest_version": old.manifest_version,
                                    "stop": old.stop, "usage": old.usage})

    # ── живой список блоков ─────────────────────────────────────────────────
    # Второй способ работы: шаблона нет вовсе, работа — упорядоченный список
    # именованных блоков, документ — его сборка. Механика
    # версий та же, что у значений тегов: файл версии создаётся и никогда не
    # заменяется, номер занят — берём следующий, «вернуть» пишется новой
    # версией. Точка записи одна — `set_blocks`, как `set_value` у тегов.

    def blocks(self) -> list:
        """Текущий список блоков. Пусто — списка ещё не заводили.

        Отдаётся копия с диска, а не хранимый объект: список правят инструменты
        агента по одному блоку, и общий изменяемый объект означал бы правку,
        которая уже видна всем, но ещё не записана.
        """
        record = self._read_json(self._blocks_path(self._head(self._blocks_dir()) or 0), None)
        return list(record["blocks"]) if record else []

    def set_blocks(self, blocks, *, source: str, note: str = "",
                   run: str | None = None) -> BlockVersion:
        """Единственная точка записи списка блоков. Новая версия, прежняя остаётся.

        Проверяется здесь только строение записи — ключи есть, они разные, поля
        известные, значение это объект JSON или `None`. Выразимость значения
        (`wire.value_from_json`) проверяет тот, кто значение принёс, — ровно как
        у `set_value`: две проверки в двух местах разошлись бы, и правил о том,
        что такое годное значение, стало бы два.

        `note` — зачем эта правка: «вставлен раздел», «текст одним проходом».
        Без него история списка это столбик номеров, по которому нельзя выбрать,
        куда возвращаться, а выбор возврата — единственное, ради чего живой
        режим держит список, а не правит документ на месте.
        """
        if source not in SOURCES:
            raise OrchestratorError(
                f"source — {', '.join(SOURCES)}, а не {source!r}{hint(source, SOURCES)}")
        prepared = _blocks_json(blocks, source=source)
        folder = self._blocks_dir()
        os.makedirs(folder, exist_ok=True)
        n = (self._head(folder) or 0) + 1
        for _ in range(_WRITE_ATTEMPTS):
            version = BlockVersion(n=n, at=_now(), source=source, note=note, run=run,
                                   count=len(prepared))
            if self._write_new(self._blocks_path(n),
                               _json_bytes({"version": asdict(version),
                                            "blocks": prepared})):
                return version
            n = max(n + 1, (self._head(folder) or 0) + 1)
        raise OrchestratorError(
            f"не удалось записать список блоков за {_WRITE_ATTEMPTS} попыток: "
            "номер версии занимают быстрее, чем мы пишем")

    def block_versions(self) -> list[BlockVersion]:
        """Все версии списка по возрастанию номера. Пусто — списка не заводили."""
        folder = self._blocks_dir()
        out = []
        for n in self._numbers(folder):
            record = self._read_json(self._blocks_path(n), None)
            if record:
                out.append(BlockVersion(**record["version"]))
        return out

    def block_version(self, n: int) -> tuple[BlockVersion, list]:
        """Конкретная версия списка: (шапка, блоки). Прошлое читается, а не только текущее."""
        record = self._read_json(self._blocks_path(int(n)), None)
        if record is None:
            known = self._numbers(self._blocks_dir())
            raise OrchestratorError(
                f"версии {n} у списка блоков нет"
                + (f" (есть {', '.join(str(x) for x in known)})" if known else
                   ": списка ещё не заводили"))
        return BlockVersion(**record["version"]), list(record["blocks"])

    def rollback_blocks(self, n: int) -> BlockVersion:
        """Вернуть список версии `n` — новой версией, а не откатом номера.

        То же решение, что у `rollback` для тега, и по той же причине: иначе
        номер версии молча уменьшается, и двое, глядя на «версию 3», видят
        разные списки. `source` сохраняется от возвращаемой версии — список
        по-прежнему написан ею, а не переписан заново.
        """
        old, blocks = self.block_version(n)
        return self.set_blocks(blocks, source=old.source, run=old.run,
                               note=f"вернули версию {n}"
                                    + (f" ({old.note})" if old.note else ""))

    # ── прогоны ─────────────────────────────────────────────────────────────
    def start_run(self, *, level: int, endpoint: str) -> Run:
        """Начало прогона: запись в `runs/` с пустой пока меткой рамки.

        Метку здесь не выпускаем и `llm.layout` про границу прогона больше не
        уведомляем: состояния прогона у слоя нет — метка принадлежит запросу
        (`Request.frame_mark`), а не процессу. Выпускает её `fill._seal` по
        собранным кускам и он же передаёт её в вызов; сюда она возвращается уже
        готовой. Прежний порядок (слой хранил метку в модульной переменной)
        означал, что два прогона в одном процессе делят одну метку: та, которую
        модель уже видела в первом прогоне, переезжала во второй.
        """
        run = Run(id=f"r{datetime.datetime.now(datetime.timezone.utc):%Y%m%dT%H%M%S}"
                     f"-{secrets.token_hex(3)}",
                  level=int(level), endpoint=endpoint, started=_now())
        self.save_run(run)
        return run

    def save_run(self, run: Run) -> None:
        os.makedirs(self._runs_dir(), exist_ok=True)
        self._write_json(os.path.join(self._runs_dir(), f"{run.id}.json"), asdict(run))

    def finish_run(self, run: Run, outcome: str) -> None:
        """Итог прогона на диск. `outcome`: done | interrupted | error | refused."""
        run.finished = _now()
        run.outcome = outcome
        self.save_run(run)

    def run(self, run_id: str) -> Run:
        d = self._read_json(os.path.join(self._runs_dir(), f"{run_id}.json"), None)
        if d is None:
            raise OrchestratorError(f"прогона {run_id!r} в проекте нет")
        return Run(**d)

    # ── ход работы сценария и журнал производных ────────────────────────────
    # Обе записи заведены ради одного: сценарий (`kadai`) не должен узнать ни
    # одного пути. Своё хранилище там означало бы второе место, знающее про
    # диск, и переезд на SQLite перестал бы быть заменой одного класса.

    def put_state(self, name: str, data: dict) -> None:
        """Записать состояние сценария под именем. Заменяется целиком.

        Целиком, а не по полям: состояние — снимок хода работы, и слияние двух
        снимков дало бы стадию, которой не было ни в одном из них. Версий здесь
        нет намеренно — «вернуть работу на стадию назад» это не откат записи, а
        решение сценария, и делать вид, что он бесплатен, нельзя.

        Пишется на диск, а не в память процесса: считает работу один процесс, а
        показывает её человеку другой (действующее решение «всё через очередь»).
        """
        if not isinstance(data, dict):
            raise OrchestratorError(
                f"состояние — объект JSON, а не {type(data).__name__}")
        self._write_json(self._state_path(name), data)

    def state(self, name: str) -> dict:
        """Состояние сценария по имени. Пустой словарь — записи не было.

        Пусто, а не ошибка: «работы ещё не заводили» — обычный ход, и отличать
        его от беды вызывающий умеет сам (`kadai.status.load` так и делает).
        """
        return self._read_json(self._state_path(name), {}) or {}

    def note_derived(self, art: str, *, tool: str, inputs=(), params=None,
                     run: str | None = None) -> None:
        """Запись в журнал производных: чем и из чего построен артефакт.

        Без неё по замечанию «схему переделай» неизвестно ни из какого исходника
        она построена, ни не сменился ли исходник под ней. Журнал
        append-only и пишется в момент производства: петля историю не сохраняет,
        и всё ценное обязано лечь на диск сразу, а не в конце прогона.

        Одному артефакту записей может быть много (тот же XML построили дважды
        разными параметрами) — все они уцелевают, а `derived_of` отдаёт
        последнюю: она про то, как артефакт получили в этот раз.
        """
        entry = {"art": str(art), "tool": str(tool), "inputs": [str(i) for i in inputs],
                 "params": dict(params or {}), "run": run, "at": _now()}
        with open(self._derived_path(), "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")

    def derived_of(self, art: str) -> dict | None:
        """Последняя запись о том, как построен артефакт, или None."""
        art = str(art)
        found = None
        for entry in self._read_lines(self._derived_path()):
            if entry.get("art") == art:
                found = entry
        return found

    # ── архив ───────────────────────────────────────────────────────────────
    def pack(self, entries, *, name: str = "работа.zip") -> str:
        """Опись → ZIP в `out/`. Возвращает **имя** архива, а не путь.

        Опись — список записей `{"name": имя в архиве, источник}`, где источник
        ровно один из трёх: `artifact` (идентификатор по содержимому), `output`
        (готовый файл в каталоге сборки) или `text` (то, что сочинил сценарий).
        Четвёртого вида нет намеренно: любой другой источник — это путь, а путь
        сюда приходить не должен, иначе складывать архив начнёт вызывающий.

        Наружу — имя: путь знает только проект, и утечка его в сценарий значит
        путь на экране у человека и в логах сайта (`kadai.stages._names_only`
        это же и проверяет с другой стороны).
        """
        leaf = _safe_leaf(name, "имя архива")
        prepared = [_entry_bytes(self, e, number)
                    for number, e in enumerate(entries or (), start=1)]
        if not prepared:
            # Пустой ZIP выглядит как готовый архив и открывается без ошибки:
            # человек узнает, что работы в нём нет, распаковав его.
            raise OrchestratorError("опись архива пуста: складывать нечего")
        path = os.path.join(self.outdir(), leaf)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for inner, data in prepared:
                zf.writestr(inner, data)
        self._write_bytes(path, buf.getvalue())
        return leaf

    def output_bytes(self, name: str) -> bytes:
        """Готовый файл каталога сборки по **имени**. Пути сюда не приходят.

        Заведено ради архива `kadai`: стадия «архив» складывает ZIP в `out/` и
        наружу отдаёт имя (пути в снимке работы не бывает — `kadai.stages` это
        и проверяет), а скачать его с сайта можно только артефактом. Чтобы
        положить его артефактом, кто-то обязан прочитать байты, и делает это
        проект: он единственный, кто знает, где лежит `out/`.

        Отказ, а не пустые байты, если файла нет: «архив собран» и «архив
        пропал» — разные состояния, и второе обязано быть слышно.
        """
        with open(self._output_path(name), "rb") as f:
            return f.read()

    # ── учёт ────────────────────────────────────────────────────────────────
    def journal(self) -> llm.Journal:
        """Журнал расхода проекта: один объект на проект, приёмник — journal.jsonl.

        Один, а не новый на вызов: `Limit.spent()` считает по записям своего
        журнала, и второй экземпляр не увидел бы того, что записал первый —
        лимит перестал бы работать ровно тогда, когда он нужен.

        Прошлые записи поднимаются с диска при первом обращении: иначе после
        перезапуска процесса лимит считает расход с нуля, и месячный потолок
        сбрасывается каждым запуском.
        """
        if self._journal is None:
            self._journal = llm.Journal(sink=self._append_journal)
            self._journal.entries.extend(self._read_journal())
        return self._journal

    def limit(self) -> llm.Limit | None:
        """Лимит проекта в приведённых единицах или None, если потолка нет.

        None, а не бесконечность: «потолка нет» и «потолок огромный» — разные
        утверждения, и первое не должно печатать пользователю проценты расхода
        от выдуманного числа.
        """
        cap = self.settings().get("cap_units")
        if cap is None:
            return None
        return llm.Limit(float(cap), journal=self.journal())

    def spent(self) -> dict:
        """Сводка расхода: единицы, деньги, доля оценённого. Для команды «сколько потрачено»."""
        j = self.journal()
        return {"calls": len(j.entries), "units": j.total_units(),
                "cost": j.total_cost(), "estimated_share": j.estimated_share()}

    # ── диск ────────────────────────────────────────────────────────────────
    # Ниже — всё, что знает про пути. При переезде на SQLite исчезает целиком
    # этот раздел, а публичные методы выше остаются как есть.

    def _settings_path(self) -> str:
        return os.path.join(self.path, "project.json")

    def _manifest_path(self) -> str:
        return os.path.join(self.path, "manifest.json")

    def _materials_dir(self) -> str:
        return os.path.join(self.path, "materials")

    def _artifacts_dir(self) -> str:
        return os.path.join(self.path, "artifacts")

    def _values_dir(self) -> str:
        return os.path.join(self.path, "values")

    def _runs_dir(self) -> str:
        return os.path.join(self.path, "runs")

    def _blocks_dir(self) -> str:
        return os.path.join(self.path, "blocks")

    def _blocks_path(self, n: int) -> str:
        return os.path.join(self._blocks_dir(), f"v{int(n)}.json")

    def _state_path(self, name: str) -> str:
        """Имя записи состояния — из данных сценария, значит через `_slug`."""
        return os.path.join(self.path, "state", f"{_slug(hokoku.wire.norm_key(str(name)))}.json")

    def _derived_path(self) -> str:
        return os.path.join(self.path, "derived.jsonl")

    def _output_path(self, name: str) -> str:
        """Готовый файл в каталоге сборки по имени. Путь вместо имени — отказ."""
        leaf = _safe_leaf(name, "имя готового файла")
        path = os.path.join(self.outdir(), leaf)
        if not os.path.isfile(path):
            raise OrchestratorError(f"готового файла {leaf!r} в каталоге сборки нет")
        return path

    def _journal_path(self) -> str:
        return os.path.join(self.path, "journal.jsonl")

    def outdir(self) -> str:
        """Каталог готовых файлов — `workdir` для `build_report`: у проекта есть каталог,
        а хранилища артефактов с записью (режим `store_artifact`) ещё нет."""
        path = os.path.join(self.path, "out")
        os.makedirs(path, exist_ok=True)
        return path

    @staticmethod
    def _numbers(folder: str) -> list[int]:
        """Номера версий в каталоге тега по возрастанию."""
        if not os.path.isdir(folder):
            return []
        out = []
        for name in os.listdir(folder):
            m = _VERSION_FILE_RE.match(name)
            if m:
                out.append(int(m.group(1)))
        return sorted(out)

    def _head(self, folder: str) -> int | None:
        """Номер текущей версии — максимальный, а не записанный отдельным файлом.

        Отдельный `head`-файл был бы вторым источником правды для того, что и
        так выводится из содержимого каталога, и первый же оборванный `os.replace`
        оставил бы проект с текущей версией, которой нет. «Вернуть» при этом не
        теряется: `rollback` пишет новую версию (см. выше).
        """
        numbers = self._numbers(folder)
        return numbers[-1] if numbers else None

    def _head_record(self, key: str) -> dict | None:
        folder = os.path.join(self._values_dir(), _slug(key))
        head = self._head(folder)
        if head is None:
            return None
        return self._read_json(os.path.join(folder, f"v{head}.json"), None)

    def _read_journal(self) -> list:
        return self._read_lines(self._journal_path())

    @staticmethod
    def _read_lines(path: str) -> list:
        """Записи из файла по строке на запись. Битая строка пропускается.

        Пропускается, а не роняет: журнал дописывается на каждом вызове модели,
        и оборванная последняя строка — обычный конец убитого процесса. Ронять
        на ней означало бы, что после одного такого обрыва проект не открыть
        вовсе, а расход по остальным строкам посчитан.
        """
        if not os.path.isfile(path):
            return []
        out = []
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue
        return out

    def _append_journal(self, entry: dict) -> None:
        with open(self._journal_path(), "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")

    @staticmethod
    def _read_json(path: str, default):
        if not os.path.isfile(path):
            return default
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    @staticmethod
    def _write_json(path: str, obj) -> None:
        Project._write_bytes(path, _json_bytes(obj))

    @staticmethod
    def _write_new(path: str, data: bytes) -> bool:
        """Создать файл, которого ещё нет. `False` — имя уже занято другим.

        Разница с `_write_bytes` ровно в одном слове: `os.link` создаёт имя и
        отказывает, если оно занято, а `os.replace` — заменяет молча. Для версий
        нужно первое: занятый номер это чужая запись, и «успешно» на ней означает
        потерянную правку без единой ошибки в логе.

        Через временный файл и `os.link`, а не через `open(O_EXCL)`: имя обязано
        появиться уже с содержимым. Иначе читатель, попавший между созданием и
        записью, получит пустой файл — `json.load` на нём падает, и тег выглядит
        не «ещё не записанным», а битым.

        Жёсткой ссылки может не быть на чужой файловой системе — тогда падаем с
        `OSError`, и это лучше молчаливого отката к перезаписи: отсутствие
        механики защиты обязано быть видно сразу, а не проявиться потерей версий.
        """
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        tmp = f"{path}.tmp{secrets.token_hex(4)}"
        with open(tmp, "wb") as f:
            f.write(data)
        try:
            os.link(tmp, path)
        except FileExistsError:
            return False
        finally:
            os.unlink(tmp)
        return True

    @staticmethod
    def _write_bytes(path: str, data: bytes) -> None:
        """Запись целым файлом через `os.replace` — для того, что заменяется:
        настроек, манифеста, записи прогона.

        Оборванная на середине запись — это файл, который читается наполовину, а
        `json.load` на нём падает: состояние выглядит потерянным, хотя прежнее
        было цело. `os.replace` атомарен на одной файловой системе, поэтому файл
        либо есть целиком, либо остаётся прежний.

        Версии значений идут не сюда, а в `_write_new`: им замена запрещена.
        """
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        tmp = f"{path}.tmp{secrets.token_hex(4)}"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, path)


__all__ = ["Project", "Version", "BlockVersion", "Run", "SOURCES", "BLOCK_FIELDS",
           "artifact_id", "template_tags"]
