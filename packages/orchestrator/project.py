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
    <path>/runs/<id>.json          прогон: уровень, endpoint, метка рамки, шаги
    <path>/journal.jsonl           по записи на вызов модели (форма В.4 слоя llm)
    <path>/out/                    workdir для build_report

Каталог, а не один JSON: версия пишется отдельным файлом, правки разных тегов не
спорят за один файл, и `git diff` каталога показывает правку тега, а не
перезапись простыни. Файл версии при этом **создаётся** и никогда не
заменяется (`_write_new`): занятый номер — это чужая запись, и молчаливое
«успешно» на ней означало бы потерянную правку.

Путь задаётся снаружи, умолчания в коде нет (решение владельца 2026-08-31):
служба открывает то, что ей дали. Умолчание здесь означало бы, что лаборатория,
CI и рабочая машина расходятся молча.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import re
import secrets
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


class Project:
    """Каталог одной работы студента: материалы, значения с версиями, манифест, журнал.

    Наружу — только методы. Ни `fill`, ни `build`, ни будущий HTTP-маршрут не
    знают, что `values/` это каталог: SQLite придёт вторым классом с теми же
    методами, а не переписыванием службы (Г.2 записки о службе).

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
    def create(cls, path: str, *, template: bytes, name: str = "",
               endpoint: str = "", cap_units: float | None = None) -> "Project":
        """Новый проект: каталог, шаблон артефактом, заготовка манифеста по тегам.

        Манифест строится сразу, а не при первом обращении: без него нельзя ни
        показать список тегов, ни собрать промпт, а `manifest_from_template`
        читает шаблон — единственную вещь, которую при создании уже держат в
        руках. Проект без манифеста был бы состоянием, из которого не выйти,
        не прочитав DOCX второй раз.

        Поверх существующего проекта — отказ. Раньше вызов проходил и строил
        манифест **без `base`**: промпты, `limits`, `depends_on`, поправленные
        типы и снятые пометки `guessed` исчезали разом, а значения оставались и
        ссылались на решения, которых больше нет. «Создать» и «сменить шаблон» —
        разные намерения, и второе делает `update_template`, который решения
        человека переносит.
        """
        if not isinstance(template, (bytes, bytearray)):
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
                return version
            # Номер занял кто-то другой. Берём следующий свободный: и наш
            # счётчик, и каталог — каталог мог уйти вперёд на много номеров.
            n = max(n + 1, (self._head(folder) or 0) + 1)
        raise OrchestratorError(
            f"не удалось записать значение тега {key!r} за {_WRITE_ATTEMPTS} попыток: "
            "номер версии занимают быстрее, чем мы пишем")

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
        path = self._journal_path()
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
                    # Битая строка журнала — не повод не дать работать: расход
                    # по ней потерян, а всё остальное считается по-прежнему.
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


__all__ = ["Project", "Version", "Run", "SOURCES", "artifact_id"]
