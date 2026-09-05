"""
Оснастка прогонов: лимиты, потоки событий, уведомления, версии.

Отдельным модулем, как `c_fixtures.py`, и по той же причине: conftest общий на
весь набор, а эти фикстуры нужны только своим тестам.

**Сети нет и быть не может.** Модель подменяется на уровне провода — реестр
`llm` собирает бэкенд функцией `llm.registry.backends.make`, и подменяется
ровно она. Всё остальное настоящее: лестница, лимит, журнал, склейка текста,
разбор потока. Подмени мы `orchestrator.fill_tag`, тест проверял бы подделку, а
не то, как служба разговаривает со слоем.

**Endpoint регистрирует не тест, а обработчик задания.** Он делает это сам,
внутри подпроцесса (или, в тестах, внутри inline-воркера), из имени пресета и
ключа человека (`api/runs/model.py`). Поэтому подмена ставится **до** прогона и
ловит бэкенд в момент регистрации: держатель `Подделка` отдаёт его тесту после.

Ключ заводится настоящий, через `POST /api/keys`: `resolve_key` — единственное
место, где ключ снова становится текстом, и обойти его в тесте значило бы не
проверить ровно тот путь, ради которого обработчику дан секрет сервера.
"""
from __future__ import annotations

import json

import pytest

import llm
from llm.backends.base import Backend
from llm.model import Chunk, Structured, Usage

from api.jobs.models import Job, JobEvent
from api.jobs.worker import Worker

# Ступень структурированного вывода. Слабая по умолчанию — та же, что у
# оснастки оркестратора: на ней `strictify` не применяется, и ответ модели
# пишется в тесте так же, как его пишет человек.
LOOSE = Structured.JSON_OBJECT
STRICT = Structured.JSON_SCHEMA

# Поставщик, от чьего имени идут прогоны в тестах. Настоящий пресет, а не
# выдуманный: список поставщиков считается из `llm.presets` (`keys.providers`),
# и выдуманное имя отказало бы ещё на проверке `unknown_provider` — то есть
# проверяло бы не то.
ПОСТАВЩИК = "deepseek"

# Ключ латиницей и без пробелов: `keys.add_key` требует печатных ASCII —
# ключ уезжает в заголовок HTTP, а туда нельзя ничего другого. Слово в нём
# осмысленное, чтобы поиск по журналам читался глазами.
КЛЮЧ = "sk-proba-kljucha-dlja-testov-1234567890"


class ПоддельныйБэкенд(Backend):
    """Бэкенд на заготовленных ответах. Провод — единственное, что подделано.

    `cancel` спрашивается **перед каждым куском**, ровно как это делает
    настоящий транспорт (`llm/transport.py`). Без этого отмену посреди потока
    нельзя было бы проверить вовсе: подделка досказала бы ответ до конца, и
    тест доказывал бы только то, что подделка не умеет останавливаться.
    """

    protocol = "fake"

    def __init__(self, spec, scripts, step: str = LOOSE):
        super().__init__(spec, transport=None)
        self.scripts = list(scripts)
        self.step = step
        self.requests: list = []

    def supported_step(self, wanted: str) -> str:
        return self.step

    def headers(self) -> dict:
        """Заголовков у подделки нет, но метод обязан быть: слой собирает
        транспорт из заголовков. Соединения при этом не открывается."""
        return {}

    def stream(self, request, cancel=None):
        self.requests.append(request)
        if not self.scripts:
            raise AssertionError("вызовов больше, чем заготовлено ответов")
        for item in self.scripts.pop(0):
            if callable(item) and not isinstance(item, (Chunk, Exception)):
                # Заготовка может дёрнуть сторонний рычаг посреди потока —
                # например, нажать «отменить» за человека. Кадром это не
                # становится.
                item()
                continue
            if isinstance(item, Exception):
                raise item
            if cancel is not None and cancel():
                yield Chunk(kind="stop", stop=llm.Stop.CANCELLED)
                return
            yield item


class Подделка:
    """Держатель: подмена стоит до прогона, бэкенд появляется во время него."""

    def __init__(self):
        self.backend: ПоддельныйБэкенд | None = None

    @property
    def requests(self) -> list:
        return list(self.backend.requests) if self.backend else []


@pytest.fixture
def модель(monkeypatch):
    """Подменить провод модели: `модель(сценарий, …)` → `Подделка`.

    Сценарий — список кусков (`куски`, `обрыв`) или заготовленных объектов; их
    столько же, сколько будет вызовов модели.
    """
    def подставить(*scripts, step: str = LOOSE) -> Подделка:
        держатель = Подделка()

        def собрать(spec, transport=None):
            держатель.backend = ПоддельныйБэкенд(spec, scripts, step=step)
            return держатель.backend

        monkeypatch.setattr(llm.registry.backends, "make", собрать)
        return держатель
    return подставить


@pytest.fixture(autouse=True)
def _чистый_реестр():
    """Реестр endpoint'ов общий на процесс — чистим до и после каждого теста.

    Иначе endpoint, зарегистрированный обработчиком одного задания, дожил бы до
    следующего теста, и подмена провода в нём не сработала бы: бэкенд-то уже
    собран.
    """
    llm.clear()
    yield
    llm.clear()


# ── заготовки ответов модели ─────────────────────────────────────────────────

def куски(текст: str, *, частей: int = 1) -> list:
    """Текст ответа кусками — так же рвано, как приходит настоящий поток."""
    if частей <= 1:
        return [Chunk(kind="text", text=текст)]
    размер = max(1, len(текст) // частей)
    return [Chunk(kind="text", text=текст[i:i + размер])
            for i in range(0, len(текст), размер)]


def сценарий(текст: str, *, частей: int = 1, stop: str = llm.Stop.END_TURN,
             usage: Usage | None = None, хвост=()) -> list:
    """Один ответ модели: текст кусками, счётчики, причина остановки."""
    out = list(куски(текст, частей=частей))
    out.extend(хвост)
    out.append(Chunk(kind="usage", usage=usage or Usage(input=1000, output=500),
                     raw={"prompt_tokens": 1000, "completion_tokens": 500}))
    out.append(Chunk(kind="stop", stop=stop))
    return out


def значение(текст: str) -> dict:
    return {"type": "markdown", "text": текст}


def отчёт(**значения) -> str:
    """Ответ уровня 2: {ключ тега: значение} — как его пишет модель."""
    return json.dumps(значения, ensure_ascii=False)


# ── очередь ──────────────────────────────────────────────────────────────────

def воркер(app) -> Worker:
    """Воркер на базе приложения: ту же базу видят и тест, и обработчик."""
    return Worker(app.state.settings, db=app.state.db)


def прогнать(app) -> str | None:
    """Один шаг воркера в этом же процессе. → идентификатор сделанного задания.

    `inline=True` — обработчик здесь же, без подпроцесса: подделка провода
    живёт в памяти процесса теста и в настоящий подпроцесс не попала бы вовсе.
    """
    return воркер(app).run_once(inline=True)


def задание(app, job_id: str) -> Job:
    """Свежая строка задания, отвязанная от сессии."""
    with app.state.db.session_scope() as s:
        строка = s.get(Job, job_id)
        s.expunge(строка)
        return строка


def события(app, job_id: str) -> list[JobEvent]:
    """Все события задания по порядку."""
    from sqlalchemy import select                             # noqa: PLC0415

    with app.state.db.session_scope() as s:
        строки = list(s.scalars(select(JobEvent)
                                .where(JobEvent.job_id == job_id)
                                .order_by(JobEvent.seq)))
        for е in строки:
            s.expunge(е)
        return строки


def виды_событий(app, job_id: str) -> list[str]:
    return [е.kind for е in события(app, job_id)]


# ── ключ и задание с моделью ─────────────────────────────────────────────────

def завести_ключ(клиент, provider: str = ПОСТАВЩИК, ключ: str = КЛЮЧ) -> dict:
    """Настоящий ключ через настоящий маршрут: `resolve_key` найдёт его сам."""
    ответ = клиент.post("/api/keys", json={"provider": provider, "key": ключ})
    assert ответ.status_code == 201, ответ.text
    return ответ.json()


def поставить(клиент, вид: str, project_id: str | None = None, **payload):
    """`POST /api/jobs` с пресетом по умолчанию. → ответ как есть."""
    payload.setdefault("endpoint", ПОСТАВЩИК)
    тело: dict = {"kind": вид, "payload": payload}
    if project_id:
        тело["project_id"] = project_id
    return клиент.post("/api/jobs", json=тело)


__all__ = ["ПоддельныйБэкенд", "Подделка", "модель", "куски", "сценарий",
           "значение", "отчёт", "воркер", "прогнать", "задание", "события",
           "виды_событий", "завести_ключ", "поставить", "ПОСТАВЩИК", "КЛЮЧ",
           "LOOSE", "STRICT"]
