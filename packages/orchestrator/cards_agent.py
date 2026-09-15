"""
cards_agent — агент пишет набор карточек тренажёра: вход частями, карточки
структурированным выводом, та же проверка, что у загруженного файла, на каждую
часть, один переспрос, черновик JSON по ходу работы.

Дверь одна — `generate`, её зовёт обработчик задания `cards_generate`:

    generate(params, *, endpoint, project=None, progress=None, emit=None,
             cancelled=None, write_draft=None, draft_path=None,
             effort=None) -> dict

**Модель отвечает объектом по схеме.** Часть — один вызов `llm.generate_object`
со схемой `{"cards": [{id?, topic, q, a, note?}]}` (`cards_prompt.CARDS_SCHEMA`).
Ступень выбирает слой: схема в запросе, строгий инструмент, режим JSON или
текст с извлечением объекта — и на всех ступенях значение проходит один
валидатор схемы. Markdown и LaTeX живут только внутри строк `q`, `a`, `note`;
разбирать разметку ответа модели незачем.

Ответ, который не разобрался целиком (оборвался на потолке вывода, одна
карточка без обязательного поля), не выбрасывается: из текста ответа берутся
дописанные объекты карточек тем же накопителем, что у потока
(`llm.stream_parse`). Обрыв стоит недописанной карточки, а не всей части.

**Вход режется на части, часть — один вызов.**

* Есть список вопросов — разделы списка становятся темами, карточка пишется на
  каждый вопрос. Большой раздел делится на несколько вызовов: длинный ответ
  рвётся на потолке вывода, и обрыв на тридцатом вопросе стоил бы всей темы.
* Есть только описание и материалы — сначала план тем (один вызов по схеме:
  названия и слова для поиска), потом карточки по темам.
* Догенерация (`append_to` + `topic`) — одна тема, `count` новых карточек;
  вопросы этой темы, уже написанные в черновике, едут модели списком.
* Потолок — 200 карточек за задание.

**Материалы режутся по теме.** Тексты файлов делятся на куски по абзацам, и в
вызов части едут куски, в которых больше всего слов темы: названия, слов плана,
вопросов части. Отбор — простой счёт совпадающих основ слов с весом редкости.
Всё, что влезает в бюджет целиком, едет целиком и одинаково во всех вызовах —
тогда у частей общий кэшируемый префикс.

**Сверка своя, а не модели.** Тему, id и число карточек ставит этот модуль:
тему — название темы части (из плана, списка или догенерации), id —
`g-<тема>-<n>` после самого большого занятого в черновике номера, лишние
карточки отрезаются. Что модель написала в `topic` и `id`, не используется.
Собранная часть проверяется как файл набора: `cards.read_json` — тот же разбор
и валидатор, что у загрузки. Отдельного «доверенного» пути для агента нет.

**Переспрос — один.** Проблемы проверки части (и нехватка карточек) уезжают
модели перечнем `путь: текст` (`cards[2].a: у карточки нет ответа`) вместе с
собранной частью. Что пришло на переспрос, то и берётся, даже с проблемами:
проблемы остаются в черновике с путями, и поправить карточку руками дешевле
третьего вызова.

**Черновик — JSON набора, пишется после каждой части.** Обрыв на четвёртой теме
из пяти оставляет три готовые, а сайт перечитывает черновик на каждый кадр
хода. Новые карточки встают в массив после последней карточки своей темы;
темы, которой в черновике нет, — в конец. Остальное в черновике (описание,
настройки, отклонённые карточки) остаётся как было.

**Защита — как у доски и ассемблера.** Описание набора, список вопросов, тексты
файлов, уже написанные вопросы и прошлый ответ модели едут недоверенными
кусками в рамке со случайной меткой прогона. В кусок задания (`request`) чужой
текст не попадает: там только число карточек, длина и язык из закрытого
списка. Проверка набора сама режет HTML, картинки и ссылки.
"""
from __future__ import annotations

import copy
import json
import math
import os
import re
import tempfile
import unicodedata
from collections import Counter
from dataclasses import dataclass, field

import cards
import llm
from llm.model import Part, Result
from llm.stream_parse import ObjectStream

from . import cards_prompt as texts, prompt as prompt_mod
from .errors import OrchestratorError, trouble_words

# ── потолки ──────────────────────────────────────────────────────────────────

# Карточек за одно задание. Больше — это уже не черновик, который человек
# просмотрит глазами, а простыня, которую он сохранит не читая.
MAX_CARDS = 200

LENGTHS = ("short", "full")
DEFAULT_LENGTH = "short"

# Сколько карточек заказано, когда число не названо: всего и при догенерации.
DEFAULT_COUNT = 20
DEFAULT_APPEND = 10

# Тем в плане не больше этого: двенадцать тем по паре карточек — это список
# вопросов, а не набор.
TOPICS_MAX = 12
# Сколько карточек в среднем на тему, когда число тем выбирает агент.
CARDS_PER_TOPIC = 8

# Карточек в одном вызове. Развёрнутый ответ с разбором втрое длиннее краткого.
CARDS_PER_CALL = {"short": 15, "full": 8}
# Сколько токенов вывода закладывается на карточку и на всё остальное в ответе.
# С запасом: на кириллице токенов на знак больше, чем в заявке поставщика.
# Строки JSON дороже текста: кавычки, экраны переводов строк и удвоенные
# обратные слеши LaTeX.
TOKENS_PER_CARD = {"short": 300, "full": 800}
TOKENS_HEAD = 400
PLAN_TOKENS = 2048

# Окно и потолок вывода, когда endpoint о них не сказал.
CONTEXT_TOKENS_DEFAULT = 32_000
OUTPUT_TOKENS_DEFAULT = 4096
# Сколько токенов материалов едет в один вызов: не меньше и не больше этого,
# внутри — по окну модели.
MATERIAL_TOKENS_MIN = 2_000
MATERIAL_TOKENS_MAX = 24_000
# Какая доля свободного окна отдаётся материалам. Оценка токенов по знакам
# ошибается на кириллице в полтора раза, и запас стоит здесь, а не в отказе
# поставщика «не поместилось».
MATERIAL_SHARE = 0.6

# Кусок материала для отбора — примерно абзац-два.
CHUNK_CHARS = 1_200

# Потолки чужого текста, который едет в промпт.
PROMPT_CHARS = 4_000
QUESTION_CHARS = 1_000
TITLE_CHARS = 120
KEYWORDS_MAX = 16
SEEN_CHARS = 8_000
RETRY_TEXT_CHARS = 60_000

# Имена кадров потока, которые пишет этот модуль сам (`progress` пишет служба).
FRAME_PART = "cards_part"

# Коды замечаний агента. Проблемы разбора приходят со своими кодами из
# `cards`; эти начинаются с `agent_`, чтобы их было видно в общем списке.
AGENT_MODEL_FAILED = "agent_model_failed"
AGENT_TRUNCATED = "agent_truncated"
AGENT_SHORT = "agent_short"
AGENT_CAP = "agent_cap"
AGENT_PLAN_FAILED = "agent_plan_failed"
AGENT_CHECK_FAILED = "agent_check_failed"
AGENT_MISSING = "agent_missing_cards"

# Формат черновика: те же поля, что у файла набора.
FORMAT = "koritsu.cards"
FORMAT_VERSION = 1

# Беды, после которых следующие части заведомо кончатся тем же: ключ не
# принят, модели нет, лимит исчерпан. Дальше звать — только копить замечания.
FATAL_KINDS = ("auth", "not_found", "limit_exceeded", "unsupported")


# ── дверь ────────────────────────────────────────────────────────────────────

def generate(params: dict, *, endpoint: str | None = None, project=None,
             progress=None, emit=None, cancelled=None, write_draft=None,
             draft_path: str | None = None, effort=None) -> dict:
    """Вход человека → набор карточек в черновике. Возвращает итог словарём.

    `params` — словарь задания:

        prompt      str          тема или описание набора
        questions   list[str] | str
                                 список вопросов к экзамену: строки или текст
                                 списка; разделы («# Пределы», «Раздел 2.»,
                                 строка с двоеточием) становятся темами
        materials   list[{name, text}]
                                 извлечённые тексты файлов
        count       int          сколько карточек всего (без списка вопросов)
                                 или сколько дописать в тему при догенерации
        per_topic   int          сколько карточек на тему (без списка вопросов)
        length      short | full краткие ответы или развёрнутые с разбором
        language    str          код языка: ru, en, …; незнакомый — ru
        title       str          название набора; не дано — из плана или prompt
        append_to   str          JSON текущего черновика (формат набора): новые
                                 карточки дописываются в его массив, id не
                                 повторяются; не читается как JSON — отказ
        topic       str          название темы для догенерации (с append_to)

    Остальные аргументы можно передать и ключами `params` — аргументы сильнее:

        endpoint     id endpoint'а с ключом человека (`Прогон.ep`)
        project      `orchestrator.Project` прогона: запись прогона, журнал
                     расхода и лимит; без него вызовы идут мимо учёта проекта
        progress     progress(step, total, note): step — карточек готово,
                     total — заказано, note — «тема 2 из 5 · Первообразная»
        emit         emit(frame): кадр `cards_part` после каждой части —
                     {kind, topic, n, total, cards, ready, problems, retried}
        cancelled    cancelled() -> bool; спрашивается между частями и слоем
                     модели внутри потока (дёшево: `Отмена` службы)
        write_draft  write_draft(text, problems, stats) — запись черновика
        draft_path   путь `.json` черновика, если колбэка нет: рядом ложится
                     `<имя>.problems.json` с {problems, stats, source}
        effort       глубина рассуждения модели, как у доски

    Черновик пишется после плана и после каждой части: JSON набора целиком
    (`format`, `version`, `title`, `language`, `cards` и всё, что было в
    `append_to`), с проблемами проверки всего набора и замечаниями агента.

    Итог:

        {ok, outcome: done | interrupted | cancelled | error | refused,
         title, language, text, problems: [{line, path, code, text, card}],
         stats: {cards, total, topics, parts, calls, retried},
         usage: {input, output, cache_read, cache_write, reasoning, measured,
                 units}, run_id}

    `text` — JSON черновика целиком (отступ 2); в `job.result` его класть не
    нужно, он уже записан черновиком. У проблемы проверки `path` — путь JSON
    (`cards[12].a`), `card` — номер карточки в массиве с нуля; у замечаний
    агента оба пусты.
    """
    params = dict(params or {})

    def pick(name, value):
        return value if value is not None else params.get(name)

    endpoint = str(pick("endpoint", endpoint) or "").strip()
    if not endpoint:
        raise OrchestratorError("не назван endpoint модели")
    job = _Job(_Params.of(params), endpoint=endpoint,
               project=pick("project", project),
               progress=pick("progress", progress), emit=pick("emit", emit),
               cancelled=pick("cancelled", cancelled),
               write_draft=pick("write_draft", write_draft),
               draft_path=pick("draft_path", draft_path),
               effort=pick("effort", effort))
    return job.run()


# ── вход ─────────────────────────────────────────────────────────────────────

@dataclass
class _Params:
    prompt: str = ""
    sections: list = field(default_factory=list)   # [(название, [вопросы])]
    materials: list = field(default_factory=list)  # [(имя, текст)]
    count: int | None = None
    per_topic: int | None = None
    length: str = DEFAULT_LENGTH
    language: str = texts.DEFAULT_LANGUAGE
    title: str = ""
    append_to: str = ""
    topic: str | None = None

    @classmethod
    def of(cls, raw: dict) -> "_Params":
        length = str(raw.get("length") or DEFAULT_LENGTH).strip().lower()
        language = str(raw.get("language") or "").strip().lower()
        topic = raw.get("topic")
        append_to = _text(raw.get("append_to"))
        return cls(
            prompt=_text(raw.get("prompt"))[:PROMPT_CHARS].strip(),
            sections=parse_questions(raw.get("questions")),
            materials=_materials(raw.get("materials")),
            count=_positive(raw.get("count")),
            per_topic=_positive(raw.get("per_topic")),
            length=length if length in LENGTHS else DEFAULT_LENGTH,
            language=language if language in texts.LANGUAGES else texts.DEFAULT_LANGUAGE,
            title=_one_line(_text(raw.get("title")), TITLE_CHARS),
            append_to=append_to,
            topic=(_title(_text(topic)) if append_to and topic is not None
                   and _text(topic).strip() else None))


def _text(value) -> str:
    if value is None:
        return ""
    text = str(value).replace("\r\n", "\n").replace("\r", "\n").lstrip("﻿")
    return unicodedata.normalize("NFC", text)


def _positive(value) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _materials(value) -> list:
    """Тексты файлов парами (имя, текст). Пустые отбрасываются молча.

    `units` принимается рядом с `text`: разобранный материал хранится
    страницами или строками, и склеивать их службе незачем.
    """
    out: list = []
    for item in value or ():
        if not isinstance(item, dict):
            continue
        text = item.get("text")
        if not text and isinstance(item.get("units"), (list, tuple)):
            text = "\n\n".join(str(u) for u in item["units"])
        text = _text(text).strip()
        if text:
            name = _one_line(_text(item.get("name")), TITLE_CHARS) or f"файл {len(out) + 1}"
            out.append((name, text))
    return out


# Строка списка вопросов с меткой пункта: «1.», «1)», «1.2», «(3)», «-», «•», «а)».
_MARKER = re.compile(
    r"^\s*(?:\(?\d{1,3}(?:\.\d{1,3})*[.)]|\d{1,3}(?:\.\d{1,3})+|[-*•–—]|[a-zа-я]\))\s+",
    re.IGNORECASE)
_HEADING_MD = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$")
_HEADING_WORD = re.compile(
    r"^(?:раздел|тема|глава|часть|модуль|блок|section|chapter|part|topic|unit)"
    r"\s*(?:№\s*)?(?:\d{1,3}|[IVXLC]{1,6})\b", re.IGNORECASE)
_HEADING_ROMAN = re.compile(r"^([IVXLC]{1,6})[.)]\s+(\S.*)$")


def parse_questions(value) -> list:
    """Список вопросов → разделы `[(название, [вопросы])]`. Пустых разделов нет.

    Принимает список строк (строка — вопрос, строка-заголовок — раздел) или
    текст списка. В тексте заголовок раздела — строка Markdown «# …», строка
    «Раздел 2. …» / «Тема 3», пункт римской цифрой, строка с двоеточием на конце
    или написанная целиком заглавными. Если в списке есть номера или маркеры
    пунктов, строка без метки продолжает предыдущий вопрос — кроме строки,
    за которой сразу идут пункты: это раздел без двоеточия.

    Вопросы до первого раздела — раздел без названия, то есть карточки без темы.
    """
    if not value:
        return []
    sections: list = [("", [])]
    if isinstance(value, (list, tuple)):
        for item in value:
            line = " ".join(_text(item).split())
            if not line:
                continue
            title = _section_title(line)
            if title is not None:
                sections.append((title, []))
            else:
                sections[-1][1].append(_question(line))
        return _nonempty(sections)

    lines = _text(value).split("\n")
    marked = any(_MARKER.match(line) for line in lines if line.strip())
    current: list | None = None
    gap = False
    for i, raw_line in enumerate(lines):
        line = raw_line.strip()
        if not line:
            gap = True
            continue
        if _MARKER.match(line):
            sections[-1][1].append(_question(line))
            current = sections[-1][1]
            gap = False
            continue
        title = _section_title(line)
        if title is None and marked:
            following = next((x for x in lines[i + 1:] if x.strip()), "")
            starts_list = bool(_MARKER.match(following))
            if current is None or not current or (gap and starts_list):
                title = " ".join(line.rstrip(":").split())
            else:
                joined = f"{current[-1]} {line}"
                current[-1] = _question(joined)
                gap = False
                continue
        if title is not None:
            sections.append((_one_line(title, TITLE_CHARS), []))
            current = None
        else:
            sections[-1][1].append(_question(line))
            current = sections[-1][1]
        gap = False
    return _nonempty(sections)


def _section_title(line: str) -> str | None:
    """Название раздела, если строка — заголовок раздела, иначе None."""
    if _MARKER.match(line):
        return None
    heading = _HEADING_MD.match(line)
    if heading:
        return _one_line(heading.group(1), TITLE_CHARS)
    if _HEADING_WORD.match(line):
        return _one_line(line.rstrip(":"), TITLE_CHARS)
    roman = _HEADING_ROMAN.match(line)
    if roman:
        return _one_line(roman.group(2).rstrip(":"), TITLE_CHARS)
    if line.endswith(":") and len(line) <= TITLE_CHARS:
        return _one_line(line[:-1], TITLE_CHARS)
    letters = [c for c in line if c.isalpha()]
    if len(letters) >= 3 and all(c.isupper() for c in letters) and len(line) <= TITLE_CHARS:
        return _one_line(line, TITLE_CHARS)
    return None


def _question(line: str) -> str:
    text = " ".join(_MARKER.sub("", line, count=1).split())
    return text[:QUESTION_CHARS]


def _nonempty(sections) -> list:
    return [(title, questions) for title, questions in sections if questions]


# ── состояние задания ────────────────────────────────────────────────────────

@dataclass
class _Topic:
    """Тема прогона: что писать и что уже написано."""

    title: str
    slug: str
    count: int = 0
    keywords: list = field(default_factory=list)
    questions: list = field(default_factory=list)
    seen: list = field(default_factory=list)       # вопросы темы в черновике и прогоне
    next_n: int = 1
    cards: list = field(default_factory=list)      # новые карточки словарями формата


@dataclass
class _Reply:
    cards: list = field(default_factory=list)      # объекты карточек как написала модель
    text: str = ""
    stop: str = ""
    error: object = None


@dataclass
class _Chunk:
    material: int
    order: int
    text: str
    terms: Counter


class _Job:
    """Одно задание генерации: разбиение, части, черновик, итог."""

    def __init__(self, p: _Params, *, endpoint, project, progress, emit, cancelled,
                 write_draft, draft_path, effort):
        # Черновик разбирается до записи прогона: нечитаемый `append_to` —
        # отказ задания, а не прогон, который затёр бы черновик пустым набором.
        self.base = _base_doc(p.append_to)
        self.base_seen, self.base_titles, self.taken_ids = _outline(self.base)

        self.p = p
        self.endpoint = endpoint
        self.project = project
        self.effort = effort
        self._progress_hook = progress
        self._emit_hook = emit
        self._cancelled_hook = cancelled
        self._write_draft = write_draft
        self._draft_path = draft_path

        self.cpt, self.context_tokens, self.max_out, self.prices = _endpoint_limits(endpoint)
        per_card = TOKENS_PER_CARD[p.length]
        self.per_call = max(1, min(CARDS_PER_CALL[p.length],
                                   (self.max_out - TOKENS_HEAD) // per_card))

        self.run_rec = project.start_run(level=1, endpoint=endpoint) if project else None
        self.limit = project.limit() if project else None
        self.journal = project.journal() if project else None
        self.mark: str | None = None

        self.notices: list = []
        self.usage = None
        self.calls = 0
        self.parts_done = 0
        self.retried = 0
        self.failed_parts = 0
        self.refused_parts = 0
        self.fatal = False
        self.cancel_seen = False
        self.ready = 0
        self.total = 0
        self.title = p.title
        self.topics: list = []

        self.chunks = _chunks_of(p.materials)
        self.idf = _idf(self.chunks)
        self.material_chars = self._material_budget()
        self.whole_materials = (sum(len(c.text) for c in self.chunks)
                                <= self.material_chars)

    # ── хуки ────────────────────────────────────────────────────────────────

    def cancelled(self) -> bool:
        if self.cancel_seen:
            return True
        if self._cancelled_hook is not None and self._cancelled_hook():
            self.cancel_seen = True
        return self.cancel_seen

    def progress(self, note: str) -> None:
        if self._progress_hook is not None:
            self._progress_hook(self.ready, max(self.total, self.ready), note)

    def emit(self, frame: dict) -> None:
        if self._emit_hook is not None:
            self._emit_hook(frame)

    # ── ход ─────────────────────────────────────────────────────────────────

    def run(self) -> dict:
        outcome = "error"
        try:
            self._build_topics()
            self._save()
            for index, topic in enumerate(self.topics):
                for questions, count in self._pieces(topic):
                    if self.cancelled() or self.fatal:
                        break
                    self.progress(self._note(index, topic))
                    self._piece(index, topic, questions, count)
                    self._save()
                    self.progress(self._note(index, topic))
                if self.cancelled() or self.fatal:
                    break
            outcome = self._outcome()
        finally:
            if self.run_rec is not None:
                self.project.finish_run(
                    self.run_rec, outcome if outcome in ("done", "error", "refused")
                    else "interrupted")
        text = self._document()
        return {
            "ok": outcome == "done", "outcome": outcome,
            "title": self.title, "language": self.p.language,
            "text": text, "problems": self._problems(text),
            "stats": self._stats(),
            "usage": self._usage_dict(),
            "run_id": self.run_rec.id if self.run_rec is not None else "",
        }

    def _note(self, index: int, topic: _Topic) -> str:
        return (f"тема {index + 1} из {len(self.topics)} · "
                f"{topic.title or 'без темы'}")

    def _outcome(self) -> str:
        if self.cancel_seen:
            return "cancelled"
        if self.ready == 0:
            if self.refused_parts and self.refused_parts == self.failed_parts:
                return "refused"
            return "error"
        if self.fatal or self.failed_parts:
            return "interrupted"
        return "done"

    # ── разбиение ───────────────────────────────────────────────────────────

    def _build_topics(self) -> None:
        p = self.p
        if p.topic is not None:
            # Догенерация: одна тема, вопросы (если даны) — все в неё.
            questions = [q for _, qs in p.sections for q in qs]
            count = len(questions) or min(p.count or p.per_topic or DEFAULT_APPEND,
                                          MAX_CARDS)
            self._cap_note(len(questions) or (p.count or 0))
            self.topics = [self._topic(p.topic, questions=questions[:MAX_CARDS],
                                       count=min(count, MAX_CARDS))]
            if not self.title:
                self.title = p.topic
        elif p.sections:
            left = MAX_CARDS
            self._cap_note(sum(len(qs) for _, qs in p.sections))
            for title, questions in p.sections:
                if left <= 0:
                    break
                taken = questions[:left]
                left -= len(taken)
                self.topics.append(self._topic(title, questions=taken, count=len(taken)))
            if not self.title:
                self.title = (_first_line(p.prompt)
                              or next((t.title for t in self.topics if t.title), "")
                              or "Карточки")
        elif p.prompt or p.materials:
            self._plan()
        else:
            raise OrchestratorError(
                "нечего генерировать: нет ни темы, ни списка вопросов, ни материалов")
        self.total = sum(t.count for t in self.topics)

    def _cap_note(self, asked: int) -> None:
        if asked > MAX_CARDS:
            self._notice(AGENT_CAP, f"за одно задание пишется не больше {MAX_CARDS} "
                                    f"карточек: заказано {asked}, взяты первые {MAX_CARDS}")

    def _topic(self, title: str, *, questions=(), count: int = 0, keywords=()) -> _Topic:
        slug = _slug(title) if title else "q"
        taken = {t.slug for t in self.topics}
        base, n = slug, 2
        while slug in taken:
            slug = f"{base}-{n}"
            n += 1
        return _Topic(title=title, slug=slug, count=count,
                      questions=list(questions), keywords=list(keywords),
                      seen=list(self.base_seen.get(_norm_title(title), ())),
                      next_n=_next_number(self.taken_ids, slug))

    def _plan(self) -> None:
        """План тем одним вызовом по схеме, затем раздача числа карточек."""
        p = self.p
        if p.per_topic:
            wanted = math.ceil(p.count / p.per_topic) if p.count else None
        else:
            wanted = math.ceil(min(p.count or DEFAULT_COUNT, MAX_CARDS) / CARDS_PER_TOPIC)
        if wanted is not None:
            wanted = max(1, min(TOPICS_MAX, wanted))
        self._cap_note(p.count or 0)

        self.progress("план тем")
        planned, plan_title = self._plan_call(wanted)
        if not planned:
            fallback = self.title or _first_line(p.prompt) or "Карточки"
            planned = [(fallback, _keywords_of(p.prompt))]
        planned = planned[:wanted or TOPICS_MAX]
        if not self.title:
            # Короткая тема одной строкой и есть название; длинное описание
            # названием не годится — тогда берётся название из плана.
            short = p.prompt.strip()
            if short and "\n" not in short and len(short) <= TITLE_CHARS:
                self.title = _title(short)
            else:
                self.title = plan_title or _first_line(p.prompt) or "Карточки"

        if p.per_topic:
            total = min(p.count or p.per_topic * len(planned), MAX_CARDS)
            counts = []
            for _ in planned:
                take = min(p.per_topic, total - sum(counts))
                counts.append(max(0, take))
        else:
            total = min(p.count or DEFAULT_COUNT, MAX_CARDS)
            share, extra = divmod(total, len(planned))
            counts = [share + (1 if i < extra else 0) for i in range(len(planned))]
        for (title, keywords), count in zip(planned, counts):
            if count > 0:
                self.topics.append(self._topic(title, count=count, keywords=keywords))

    def _plan_call(self, wanted: int | None) -> tuple[list, str]:
        p = self.p
        parts = [Part(role="rules", text=texts.PLAN_RULES, stable=True)]
        parts += self._description_parts()
        parts += self._material_parts(_query(p.prompt, weight=1), overview=True)
        parts += prompt_mod.data_parts([("темы, которые уже есть в наборе",
                                         "\n".join(self.base_titles))])
        parts.append(Part(role="request", stable=False,
                          text=texts.plan_request(topics=wanted, language=p.language)))
        result = self._object(copy.deepcopy(texts.PLAN_SCHEMA), parts,
                              min(PLAN_TOKENS, self.max_out), self._meta("plan"))
        value = result.value if result.ok and isinstance(result.value, dict) else {}
        planned: list = []
        seen: set = set()
        for item in value.get("topics") or ():
            if not isinstance(item, dict):
                continue
            title = _title(str(item.get("title") or ""))
            key = _norm_title(title)
            if not title or key in seen:
                continue
            seen.add(key)
            keywords = [_one_line(str(k), 60) for k in (item.get("keywords") or ())
                        if isinstance(k, str) and k.strip()][:KEYWORDS_MAX]
            planned.append((title, keywords))
        if self.run_rec is not None:
            self.run_rec.steps.append({"cards": "plan", "ok": bool(planned),
                                       "stop": result.stop, "topics": len(planned)})
        if not planned:
            if result.stop == llm.Stop.CANCELLED or self.cancel_seen:
                return [], ""
            why = (trouble_words(result.error) if getattr(result, "error", None)
                   is not None else "модель не вернула ни одной темы")
            self._notice(AGENT_PLAN_FAILED, f"план тем не получился ({why}): "
                                            "карточки пишутся одной темой")
            if _fatal(getattr(result, "error", None)):
                self.fatal = True
        return planned, _title(str(value.get("title") or ""))

    def _pieces(self, topic: _Topic):
        """Части темы: (вопросы части, сколько карточек)."""
        if topic.questions:
            for start in range(0, len(topic.questions), self.per_call):
                chunk = topic.questions[start:start + self.per_call]
                yield chunk, len(chunk)
            return
        left = topic.count
        while left > 0:
            take = min(self.per_call, left)
            yield [], take
            left -= take

    # ── часть ───────────────────────────────────────────────────────────────

    def _piece(self, index: int, topic: _Topic, questions: list, count: int) -> None:
        ids = self._ids(topic, count)
        parts = self._parts(topic, questions, count)
        max_tokens = min(self.max_out, TOKENS_HEAD + count * TOKENS_PER_CARD[self.p.length])

        reply = self._call(parts, max_tokens, "part", index)
        made = self._settle(reply.cards, topic, ids, count)
        problems, checked = self._check(self._part_text(made))
        problems += _shortfall(len(made), count, bool(questions))

        retried = False
        if (problems and checked and not _fatal(reply.error)
                and reply.stop not in (llm.Stop.REFUSED, llm.Stop.CANCELLED)
                and not self.cancelled()):
            retried = True
            self.retried += 1
            # Прошлый ответ едет собранной частью, а не текстом модели: пути
            # проблем (`cards[2].a`) считаются по ней.
            shown = _dumps({"cards": made}) if made else reply.text
            again = list(parts) + prompt_mod.data_parts([
                ("прошлый ответ", shown[:RETRY_TEXT_CHARS]),
                ("проблемы проверки", _problems_text(problems)),
            ]) + [Part(role="request", stable=False, text=texts.retry_request())]
            second = self._call(again, max_tokens, "retry", index)
            second_made = self._settle(second.cards, topic, ids, count)
            if second_made:
                reply, made = second, second_made
            elif second.error is not None and not made:
                reply = second

        final_problems, _ = self._check(self._part_text(made))

        where = f"«{topic.title}»" if topic.title else "без темы"
        if not made:
            self.failed_parts += 1
            if reply.stop == llm.Stop.REFUSED:
                self.refused_parts += 1
            if reply.stop != llm.Stop.CANCELLED:
                if reply.error is not None or reply.stop in _WORDED_STOPS:
                    why = trouble_words(reply.error, reply.stop)
                else:
                    why = "в ответе нет ни одной карточки"
                self._notice(AGENT_MODEL_FAILED, f"тема {where}: часть не написана — {why}")
            if _fatal(reply.error):
                self.fatal = True
        else:
            if reply.stop == llm.Stop.MAX_TOKENS:
                self._notice(AGENT_TRUNCATED, f"тема {where}: ответ оборвался на потолке "
                                              "длины, недописанная карточка отброшена")
            if len(made) < count and reply.stop != llm.Stop.CANCELLED:
                self._notice(AGENT_SHORT, f"тема {where}: написано {len(made)} "
                                          f"карточек из {count}")

        used = [card["id"] for card in made]
        self.taken_ids.update(used)
        if used:
            topic.next_n = _number_of(used[-1], topic.slug) + 1
        topic.cards.extend(made)
        topic.seen.extend(_one_line(card["q"], QUESTION_CHARS) for card in made)
        self.ready += len(made)
        self.parts_done += 1
        if self.run_rec is not None:
            self.run_rec.steps.append({"cards": "part", "topic": index + 1,
                                       "cards_written": len(made), "asked": count,
                                       "retried": retried, "stop": reply.stop,
                                       "problems": len(final_problems)})
            self.project.save_run(self.run_rec)
        self.emit({"kind": FRAME_PART, "topic": topic.title, "n": index + 1,
                   "total": len(self.topics), "cards": len(made), "ready": self.ready,
                   "problems": len(final_problems), "retried": retried})

    def _settle(self, raw: list, topic: _Topic, ids: list, count: int) -> list:
        """Объекты карточек модели → карточки формата с нашими темой и id.

        Берутся только `q`, `a` и `note`; `topic` и `id` модели не читаются.
        Сверх `count` — отрезается. Карточка с пустым вопросом или ответом не
        выбрасывается: её отклонит проверка, и проблема уедет в переспрос.
        """
        out: list = []
        for item in raw or ():
            if len(out) >= count:
                break
            if not isinstance(item, dict):
                continue
            q = _question_clean(_field(item.get("q")))
            a = _field(item.get("a"))
            if not q and not a:
                continue
            card = {"id": ids[len(out)]}
            if topic.title:
                card["topic"] = topic.title
            card["q"] = q
            card["a"] = a
            note = _field(item.get("note"))
            if note:
                card["note"] = note
            out.append(card)
        return out

    def _part_text(self, made: list) -> str:
        """Часть отдельным набором — ровно то, что проверяется."""
        return _dumps({"format": FORMAT, "version": FORMAT_VERSION,
                       "title": self.title or "Карточки", "language": self.p.language,
                       "cards": made})

    def _ids(self, topic: _Topic, count: int) -> list:
        ids: list = []
        n = topic.next_n
        while len(ids) < count:
            candidate = f"g-{topic.slug}-{n}"
            if candidate not in self.taken_ids:
                ids.append(candidate)
            n += 1
        return ids

    def _parts(self, topic: _Topic, questions: list, count: int) -> list:
        p = self.p
        parts = [Part(role="rules", text=texts.RULES, stable=True)]
        parts += self._description_parts()
        query = _query(topic.title, weight=3) + _query(" ".join(topic.keywords), weight=2) \
            + _query(" ".join(questions), weight=2) + _query(p.prompt, weight=1)
        parts += self._material_parts(query)
        data = [("тема", topic.title)]
        if questions:
            data.append(("вопросы темы",
                         "\n".join(f"{i}. {q}" for i, q in enumerate(questions, 1))))
        seen = _tail_lines(topic.seen, SEEN_CHARS) if not questions else ""
        data.append(("уже написанные вопросы", seen))
        parts += prompt_mod.data_parts(data)
        has_materials = bool(self.chunks)
        if questions:
            request = texts.questions_request(count=count, length=p.length,
                                              language=p.language,
                                              has_materials=has_materials,
                                              has_topic=bool(topic.title))
        else:
            request = texts.topic_request(count=count, length=p.length,
                                          language=p.language,
                                          has_materials=has_materials,
                                          has_seen=bool(seen),
                                          has_topic=bool(topic.title))
        parts.append(Part(role="request", stable=False, text=request))
        return parts

    def _description_parts(self) -> list:
        """Описание набора — одинаковое во всех вызовах, поэтому стабильное."""
        if not self.p.prompt:
            return []
        return [Part(role="files", stable=True, untrusted=True,
                     name="описание набора", text=self.p.prompt)]

    # ── материалы ───────────────────────────────────────────────────────────

    def _material_budget(self) -> int:
        out = min(self.max_out, TOKENS_HEAD + self.per_call * TOKENS_PER_CARD[self.p.length])
        free = self.context_tokens - out - 3_000
        tokens = int(free * MATERIAL_SHARE)
        tokens = max(MATERIAL_TOKENS_MIN, min(MATERIAL_TOKENS_MAX, tokens))
        return int(tokens * self.cpt)

    def _material_parts(self, query: Counter, *, overview: bool = False) -> list:
        """Куски материалов для вызова: всё, если влезает, иначе отбор по теме.

        Всё целиком — стабильные куски: одинаковые во всех вызовах прогона, они
        кэшируются. Отобранное меняется от части к части и помечено волатильным.
        Для плана берётся половина бюджета и первый кусок каждого файла:
        оглавление и введение говорят о темах больше, чем случайный абзац.
        """
        if not self.chunks:
            return []
        if self.whole_materials:
            chosen = list(range(len(self.chunks)))
            stable = True
        else:
            budget = self.material_chars // 2 if overview else self.material_chars
            chosen = _select(self.chunks, self.idf, query, budget, firsts=overview)
            stable = False
        by_material: dict = {}
        for i in chosen:
            by_material.setdefault(self.chunks[i].material, []).append(i)
        parts: list = []
        for material, indices in sorted(by_material.items()):
            pieces: list = []
            previous = None
            for i in sorted(indices):
                if previous is not None and i != previous + 1:
                    pieces.append("[…]")
                pieces.append(self.chunks[i].text)
                previous = i
            name = self.p.materials[material][0]
            parts.append(Part(role="files", stable=stable, untrusted=True, name=name,
                              text="\n\n".join(pieces)))
        return parts

    # ── вызов модели ────────────────────────────────────────────────────────

    def _object(self, schema: dict, parts: list, max_tokens: int, meta: dict) -> Result:
        """Один вызов по схеме через лестницу слоя. Не бросает: беда — в Result."""
        self._seal(parts)
        try:
            result = llm.generate_object(
                self.endpoint, schema, parts, max_tokens=max_tokens,
                effort=self.effort, cancel=self.cancelled, limit=self.limit,
                journal=self.journal, frame_mark=self.mark, meta=meta)
        except llm.Cancelled:
            result = Result(ok=False, stop=llm.Stop.CANCELLED)
        except llm.LlmError as exc:
            result = Result(ok=False, stop=llm.Stop.ERROR, error=exc)
        # Повторы нижних ступеней лестницы — настоящие вызовы.
        self.calls += max(1, int(getattr(result, "attempts", 1) or 1))
        self._add_usage(getattr(result, "usage", None))
        if result.stop == llm.Stop.CANCELLED:
            self.cancel_seen = True
        return result

    def _call(self, parts: list, max_tokens: int, kind: str, index: int) -> _Reply:
        """Вызов части: объекты карточек, текст ответа, причина остановки, беда."""
        result = self._object(copy.deepcopy(texts.CARDS_SCHEMA), parts, max_tokens,
                              self._meta(kind, index))
        reply = _Reply(text=str(result.text or ""), stop=result.stop or "",
                       error=result.error)
        value = result.value if result.ok else None
        if isinstance(value, dict) and isinstance(value.get("cards"), list):
            reply.cards = list(value["cards"])
        elif result.stop not in (llm.Stop.REFUSED, llm.Stop.CANCELLED):
            reply.cards = _salvage(result)
        return reply

    def _seal(self, parts: list) -> None:
        """Метка рамки прогона: одна на все вызовы, пока чужой текст её не задел."""
        mark = prompt_mod.seal_mark(parts, self.mark)
        if mark != self.mark:
            self.mark = mark
            if self.run_rec is not None:
                self.run_rec.mark = mark
                self.project.save_run(self.run_rec)

    def _meta(self, kind: str, index: int | None = None) -> dict:
        meta = {"run": self.run_rec.id if self.run_rec is not None else "",
                "level": 1, "cards": kind}
        if index is not None:
            meta["topic"] = index + 1
        return meta

    def _add_usage(self, usage) -> None:
        if isinstance(usage, llm.Usage):
            self.usage = usage if self.usage is None else self.usage + usage

    def _usage_dict(self) -> dict:
        usage = self.usage or llm.Usage(measured=False)
        return {**usage.as_dict(), "units": llm.usage.units(usage, self.prices)}

    # ── проверка и черновик ─────────────────────────────────────────────────

    def _check(self, text: str) -> tuple[list, bool]:
        """Разбор и валидатор набора — те же, что у загруженного файла.

        Второе значение — удалась ли проверка. Упавшая проверка — не повод
        переспрашивать модель: чинить нечего, кроме самой проверки.
        """
        # `read_json`, а не `validate` над собранным `CardSet`: у разбора номер
        # карточки и путь — по массиву источника вместе с отклонёнными, и
        # проблемы указывают на те карточки, что лежат в черновике.
        try:
            _, found = cards.read_json(text, filename="cards.json")
            found = [_problem_of(p) for p in (found or ())]
        except Exception as exc:                          # noqa: BLE001
            return [_problem(None, AGENT_CHECK_FAILED,
                             f"проверка карточек не удалась: {type(exc).__name__}")], False
        out: list = []
        seen: set = set()
        for problem in found:
            key = (problem["path"], problem["line"], problem["code"], problem["text"],
                   problem["card"])
            if key not in seen:
                seen.add(key)
                out.append(problem)
        return out, True

    def _notice(self, code: str, text: str) -> None:
        self.notices.append(_problem(None, code, text))

    def _problems(self, text: str) -> list:
        problems, _ = self._check(text)
        return problems + list(self.notices)

    def _stats(self) -> dict:
        return {"cards": self.ready, "total": max(self.total, self.ready),
                "topics": sum(1 for t in self.topics if t.cards),
                "parts": self.parts_done, "calls": self.calls, "retried": self.retried}

    def _document(self) -> str:
        """JSON черновика: набор из `append_to` (или новый) и новые карточки.

        Пишется своим `json.dumps`, а не `cards.write_json`: запись ядра берёт
        `CardSet` из годных карточек, а черновик хранит и отклонённые — их
        человек правит на странице черновика.
        """
        base = self.base or {}
        doc = {"format": base.get("format") or FORMAT,
               "version": base.get("version") or FORMAT_VERSION}
        for key, value in base.items():
            doc.setdefault(key, value)
        if not isinstance(doc.get("title"), str) or not doc["title"].strip():
            doc["title"] = _title(self.title) or "Карточки"
        if not isinstance(doc.get("language"), str) or not doc["language"].strip():
            doc["language"] = self.p.language
        doc["cards"] = list(doc["cards"]) if isinstance(doc.get("cards"), list) else []
        # Ключ `cards` — последним, как в формате: заголовок набора читается
        # первым и в файле, и в черновике.
        doc["cards"] = doc.pop("cards")
        _merge(doc["cards"], [(t.title, t.cards) for t in self.topics if t.cards])
        return _dumps(doc)

    def _save(self) -> None:
        text = self._document()
        problems = self._problems(text)
        stats = self._stats()
        if self._write_draft is not None:
            self._write_draft(text, problems, stats)
        elif self._draft_path:
            _write_atomic(self._draft_path, text)
            side = os.path.splitext(self._draft_path)[0] + ".problems.json"
            _write_atomic(side, json.dumps({"problems": problems, "stats": stats,
                                            "source": "agent"},
                                           ensure_ascii=False, indent=1))


# ── ответ модели → карточки ──────────────────────────────────────────────────

# Начало массива карточек в тексте ответа: объекты после него — карточки.
_CARDS_OPEN = re.compile(r'"cards"\s*:\s*\[')
_NUMBER_PREFIX = re.compile(r"^(?:вопрос\s*|question\s*)?\d{1,3}\s*[.):]\s+", re.IGNORECASE)


def _salvage(result) -> list:
    """Дописанные объекты карточек из ответа, который не разобрался целиком.

    Ответ оборвался на потолке вывода или одна карточка нарушила схему — и
    слой отдал `value=None`. Объекты, закрывшиеся в тексте (или в аргументах
    вызова инструмента), берутся накопителем потока: скобки внутри строк он
    считает правильно, а недописанный хвост не отдаёт.
    """
    sources = [str(getattr(result, "text", "") or "")]
    for call in getattr(result, "tool_calls", None) or ():
        arguments = getattr(call, "arguments", None)
        if isinstance(arguments, dict) and isinstance(arguments.get("cards"), list):
            return list(arguments["cards"])
        sources.append(str(getattr(call, "raw_arguments", "") or ""))
    for text in sources:
        found = _card_objects(text)
        if found:
            return found
    return []


def _card_objects(text: str) -> list:
    if not text.strip():
        return []
    # Без ключа `cards` — голый массив или объекты подряд: верхний уровень и
    # есть карточки.
    match = _CARDS_OPEN.search(text)
    objects = ObjectStream().feed(text[match.end():] if match else text)
    return [o for o in objects if isinstance(o, dict) and ("q" in o or "a" in o)]


def _field(value) -> str:
    """Строковое поле карточки: текст без крайних пробелов; не строка — пусто."""
    if isinstance(value, bool) or value is None:
        return ""
    if isinstance(value, (int, float)):
        value = str(value)
    if not isinstance(value, str):
        return ""
    return _text(value).strip()


def _question_clean(text: str) -> str:
    """Вопрос в одну строку — без номера пункта и жирного по всей строке.

    Номер модель переносит из списка вопросов; в карточке он лишний и ломает
    опознание вопроса при следующей версии списка.
    """
    if "\n" in text:
        return text
    plain = _NUMBER_PREFIX.sub("", text)
    if len(plain) > 4 and plain.startswith("**") and plain.endswith("**") \
            and "**" not in plain[2:-2]:
        plain = plain[2:-2].strip()
    return plain


# Причины остановки, у которых есть слова для человека (`errors.STOP_WORDS`).
_WORDED_STOPS = (llm.Stop.MAX_TOKENS, llm.Stop.REFUSED, llm.Stop.CANCELLED)


def _shortfall(written: int, asked: int, by_questions: bool) -> list:
    if written >= asked:
        return []
    if by_questions:
        text = (f"в ответе {written} карточек, а вопросов {asked}: нужна карточка "
                "на каждый вопрос, в том же порядке")
    else:
        text = f"в ответе {written} карточек, а нужно {asked}"
    return [_problem(None, AGENT_MISSING, text)]


def _fatal(error) -> bool:
    return error is not None and str(getattr(error, "kind", "")) in FATAL_KINDS


# ── черновик ─────────────────────────────────────────────────────────────────

def _dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def _base_doc(text: str) -> dict | None:
    """`append_to` → объект набора или None, если черновик пуст.

    Разбирается простым `json.loads`, а не `cards.read_json`: черновик
    переписывается целиком, и всё, что в нём было — описание, настройки,
    отклонённые карточки, незнакомые поля, — должно пережить дописывание.
    """
    if not (text or "").strip():
        return None
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as exc:
        raise OrchestratorError(f"черновик не читается как JSON: строка {exc.lineno}, "
                                f"столбец {exc.colno}") from None
    if not isinstance(doc, dict):
        raise OrchestratorError("черновик — не объект набора JSON")
    if "cards" in doc and not isinstance(doc["cards"], list):
        raise OrchestratorError("в черновике `cards` — не массив")
    return doc


def _card_topic(card) -> str:
    topic = card.get("topic") if isinstance(card, dict) else None
    return _norm_title(topic) if isinstance(topic, str) else ""


def _merge(cards_list: list, additions: list) -> None:
    """Новые карточки в массив черновика: после последней карточки своей темы.

    Темы, которой в черновике нет, — в конец массива. Порядок тем набора — по
    первому появлению, поэтому карточка, вставленная рядом со своими, тему не
    передвигает.
    """
    for title, new in additions:
        if not new:
            continue
        key = _norm_title(title)
        at = None
        for i, card in enumerate(cards_list):
            if _card_topic(card) == key:
                at = i + 1
        if at is None:
            cards_list.extend(new)
        else:
            cards_list[at:at] = new


def _outline(doc: dict | None) -> tuple[dict, list, set]:
    """Черновик: вопросы по темам, названия тем, занятые id."""
    seen: dict = {"": []}
    titles: list = []
    ids: set = set()
    for card in (doc or {}).get("cards") or ():
        if not isinstance(card, dict):
            continue
        topic = card.get("topic")
        title = _title(topic) if isinstance(topic, str) else ""
        if title and title not in titles:
            titles.append(title)
        questions = seen.setdefault(_norm_title(title), [])
        q = card.get("q")
        if isinstance(q, str) and q.strip():
            questions.append(_one_line(q, QUESTION_CHARS))
        card_id = card.get("id")
        if isinstance(card_id, str) and card_id.strip():
            ids.add(card_id.strip())
    return seen, titles, ids


def _next_number(taken: set, slug: str) -> int:
    """Номер после самого большого занятого `g-<тема>-<n>`.

    После самого большого, а не первый свободный: карточку удалили из
    черновика, а её id мог уже жить в сохранённом наборе с прогрессом, и новая
    карточка под старым id унаследовала бы чужие ответы.
    """
    top = 0
    for card_id in taken:
        top = max(top, _number_of(card_id, slug))
    return top + 1


def _number_of(card_id: str, slug: str) -> int:
    match = re.fullmatch(rf"g-{re.escape(slug)}-(\d+)", card_id)
    return int(match.group(1)) if match else 0


def _write_atomic(path: str, data: str) -> None:
    folder = os.path.dirname(path) or "."
    os.makedirs(folder, exist_ok=True)
    handle, temp = tempfile.mkstemp(dir=folder, prefix=".cards-", suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as f:
            f.write(data)
        os.replace(temp, path)
    except BaseException:
        try:
            os.unlink(temp)
        except OSError:
            pass
        raise


# ── материалы: куски и отбор ─────────────────────────────────────────────────

_WORD = re.compile(r"[^\W_]{3,}")
_STOP = frozenset("""
это как что для или при так его она они все был была были быть который которая
которые также если чем где когда между после перед только можно нужно этот эта
эти того тем том той чтобы более менее очень the and for with that this are from
was were which what when where into than then also have has not but can may
""".split())
# Длина основы слова. Грубо, но без словаря: «интеграл», «интеграла» и
# «интегралом» сходятся в одну основу, а редкие склейки разных слов отбор
# переживает — он выбирает куски, а не отвечает на вопрос.
STEM = 6


def _terms(text: str) -> list:
    out: list = []
    for word in _WORD.findall(text.lower()):
        if word in _STOP:
            continue
        out.append(word[:STEM])
    return out


def _query(text: str, *, weight: int) -> Counter:
    return Counter({term: weight for term in set(_terms(text or ""))})


def _chunks_of(materials: list) -> list:
    chunks: list = []
    for index, (_, text) in enumerate(materials):
        for piece in _split_text(text):
            chunks.append(_Chunk(material=index, order=len(chunks), text=piece,
                                 terms=Counter(_terms(piece))))
    return chunks


def _split_text(text: str) -> list:
    """Текст → куски около `CHUNK_CHARS` по границам абзацев."""
    pieces: list = []
    current = ""
    for paragraph in re.split(r"\n\s*\n", text):
        paragraph = paragraph.strip()
        while len(paragraph) > CHUNK_CHARS:
            cut = paragraph.rfind(" ", CHUNK_CHARS // 2, CHUNK_CHARS)
            cut = cut if cut > 0 else CHUNK_CHARS
            if current:
                pieces.append(current)
                current = ""
            pieces.append(paragraph[:cut].strip())
            paragraph = paragraph[cut:].strip()
        if not paragraph:
            continue
        if current and len(current) + len(paragraph) + 2 > CHUNK_CHARS:
            pieces.append(current)
            current = paragraph
        else:
            current = f"{current}\n\n{paragraph}" if current else paragraph
    if current:
        pieces.append(current)
    return pieces


def _idf(chunks: list) -> dict:
    df: Counter = Counter()
    for chunk in chunks:
        df.update(set(chunk.terms))
    total = len(chunks) or 1
    return {term: math.log(1 + total / count) for term, count in df.items()}


def _select(chunks: list, idf: dict, query: Counter, budget: int, *,
            firsts: bool = False) -> list:
    """Номера кусков под бюджет: самые совпадающие с темой, затем их соседи.

    Ни один кусок не совпал — первые куски файлов по порядку: введение лучше
    пустого контекста. Соседи добираются, пока бюджет не кончился: определение
    часто стоит абзацем раньше того, где встретилось слово.
    """
    chosen: set = set()
    used = 0

    def take(i: int) -> bool:
        nonlocal used
        if i in chosen or not 0 <= i < len(chunks):
            return False
        size = len(chunks[i].text) + 8
        if used + size > budget:
            return False
        chosen.add(i)
        used += size
        return True

    if firsts:
        firsts_seen: set = set()
        for i, chunk in enumerate(chunks):
            if chunk.material not in firsts_seen:
                firsts_seen.add(chunk.material)
                take(i)
    scored = []
    for i, chunk in enumerate(chunks):
        score = 0.0
        for term, weight in query.items():
            tf = chunk.terms.get(term)
            if tf:
                score += weight * (1 + math.log(tf)) * idf.get(term, 0.0)
        if score > 0:
            scored.append((-score, i))
    for _, i in sorted(scored):
        take(i)
    if not scored:
        for i in range(len(chunks)):
            take(i)
    else:
        for i in sorted(chosen):
            for j in (i - 1, i + 1):
                if 0 <= j < len(chunks) and chunks[j].material == chunks[i].material:
                    take(j)
    return sorted(chosen)


# ── мелочи ───────────────────────────────────────────────────────────────────

def _endpoint_limits(endpoint: str) -> tuple:
    """Знаков на токен, окно, потолок вывода и цены endpoint'а — или умолчания."""
    try:
        spec = llm.spec_of(endpoint)
        caps = llm.capabilities(endpoint)
    except llm.LlmError:
        return 3.5, CONTEXT_TOKENS_DEFAULT, OUTPUT_TOKENS_DEFAULT, None
    context = caps.context_tokens or spec.context_tokens or CONTEXT_TOKENS_DEFAULT
    output = caps.max_output_tokens or spec.max_output_tokens or OUTPUT_TOKENS_DEFAULT
    return (float(spec.chars_per_token or 3.5), int(context), int(output), spec.prices)


def _problem(line, code: str, text: str, card=None, path=None) -> dict:
    """Проблема в общей форме: строка, путь JSON, код, текст и номер карточки (с 0)."""
    return {"line": line, "path": path, "code": code, "text": text, "card": card}


def _problem_of(item) -> dict:
    """Проблема разбора (`cards.Problem` или словарь) → общая форма словаря."""
    if isinstance(item, dict):
        line, code, text = item.get("line"), item.get("code"), item.get("text")
        card, path = item.get("card"), item.get("path")
    else:
        line = getattr(item, "line", None)
        code = getattr(item, "code", "")
        text = getattr(item, "text", "")
        card = getattr(item, "card", None)
        path = getattr(item, "path", None)
    return _problem(line if isinstance(line, int) else None, str(code or ""),
                    str(text or ""), card if isinstance(card, int) else None,
                    str(path) if path else None)


def _problems_text(problems: list) -> str:
    out: list = []
    for p in problems:
        if p.get("path"):
            out.append(f"{p['path']}: {p['text']}")
        elif p.get("line"):
            out.append(f"строка {p['line']}: {p['text']}")
        else:
            out.append(p["text"])
    return "\n".join(out)


def _tail_lines(lines: list, limit: int) -> str:
    """Последние строки списка, сколько влезает в `limit` знаков, по порядку."""
    out: list = []
    used = 0
    for line in reversed(lines):
        if used + len(line) + 1 > limit:
            break
        out.append(line)
        used += len(line) + 1
    return "\n".join(reversed(out))


def _one_line(text: str, limit: int) -> str:
    plain = " ".join((text or "").split())
    plain = "".join(c if c.isprintable() else " " for c in plain)
    return plain[:limit - 1].rstrip() + "…" if len(plain) > limit else plain


def _title(text: str) -> str:
    """Название темы или набора: одна строка не длиннее `TITLE_CHARS`."""
    return _one_line(text or "", TITLE_CHARS).strip()


def _norm_title(text: str) -> str:
    return " ".join(_title(text or "").casefold().split())


def _first_line(text: str) -> str:
    first = next((line for line in (text or "").split("\n") if line.strip()), "")
    return _title(first)


def _keywords_of(text: str) -> list:
    words = [w for w in _WORD.findall((text or "").lower()) if w not in _STOP]
    return list(dict.fromkeys(words))[:KEYWORDS_MAX]


_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh",
    "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o",
    "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "h", "ц": "ts",
    "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu",
    "я": "ya", "і": "i", "ї": "yi", "є": "ye", "ў": "u", "ә": "a", "ғ": "g", "қ": "k",
    "ң": "n", "ө": "o", "ұ": "u", "ү": "u", "һ": "h",
}
SLUG_CHARS = 24


def _slug(title: str) -> str:
    """Название темы → часть id латиницей: `[a-z0-9-]`, не длиннее `SLUG_CHARS`."""
    lowered = "".join(_TRANSLIT.get(c, c) for c in title.lower())
    ascii_text = unicodedata.normalize("NFKD", lowered).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text).strip("-")
    if len(slug) > SLUG_CHARS:
        slug = slug[:SLUG_CHARS].rsplit("-", 1)[0] or slug[:SLUG_CHARS]
    return slug.strip("-") or "t"


__all__ = ["generate", "parse_questions", "MAX_CARDS", "LENGTHS", "FRAME_PART"]
