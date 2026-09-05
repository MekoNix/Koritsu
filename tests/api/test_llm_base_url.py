"""
Подменённый адрес модели: в `dev` действует, в `prod` мёртв.

Настройка `KORITSU_LLM_BASE_URL_<ПРЕСЕТ>` заведена ради одного — стенда
«настоящая служба, настоящий воркер, поддельная модель» (`web/e2e/`), на котором
сквозные проверки сайта гоняют прогоны без ключей и без сети.

Проверяется ровно то, из-за чего эта настройка вообще может быть опасна: она
переписывает адрес, по которому уезжает ключ человека. Поэтому здесь два теста
на одно поведение — «в dev применяется» и «в prod не применяется», — и второй
важнее первого: он про то, что забытая строка в `.env` боевой машины безвредна
сама по себе, а не «безвредна, пока никто не ошибся».
"""
from __future__ import annotations

import contextlib
import types

import pytest

import llm

from api import Settings
from api.keys import service as keys
from api.runs import model as runs_model
from api.settings import предупредить_о_подмене

ПРЕСЕТ = "deepseek"
АДРЕС = "http://127.0.0.1:8016"
КЛЮЧ = "sk-podmena-0123456789"


@pytest.fixture(autouse=True)
def _чистый_реестр():
    """Реестр endpoint'ов общий на процесс: `endpoint()` его и наполняет."""
    llm.clear()
    yield
    llm.clear()


class Ктx:
    """Столько контекста задания, сколько читает `runs.model.endpoint`.

    Настоящий `JobContext` тянет за собой базу, очередь и подпроцесс, а
    проверяется здесь одна строка — из какого адреса собран пресет. Сессия
    отдаётся пустая: ключ и его источник подменены ниже, и в базу никто не
    ходит.
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self.job_id = "job-проба"
        self.job = types.SimpleNamespace(user_id="u-проба")

    @contextlib.contextmanager
    def session_scope(self):
        yield None


@pytest.fixture
def ключ_есть(monkeypatch):
    """Ключ у человека есть — иначе `endpoint()` откажет `no_key` до пресета."""
    monkeypatch.setattr(keys, "resolve_key", lambda *a, **k: КЛЮЧ)
    monkeypatch.setattr(keys, "source_of", lambda *a, **k: "own")


def настройки(tmp_path, *, env: str, адреса: dict | None = None) -> Settings:
    return Settings.for_tests(tmp_path, env=env,
                              llm_base_urls=dict(адреса or {}))


# ── чтение окружения ─────────────────────────────────────────────────────────

def test_переменная_читается_в_словарь_по_имени_пресета():
    """`KORITSU_LLM_BASE_URL_DEEPSEEK` → `{"deepseek": …}`: имя пресета внизу,
    потому что `payload.endpoint` приходит именно в нижнем регистре."""
    s = Settings.from_env({"KORITSU_DATA_DIR": "/tmp/koritsu-проба",
                           "KORITSU_SECRET": "x" * 32,
                           "KORITSU_LLM_BASE_URL_DEEPSEEK": АДРЕС + "/"})
    # Хвостовая косая срезана: адрес склеивается с `/v1/chat/completions`.
    assert s.llm_base_urls == {"deepseek": АДРЕС}


def test_пустая_переменная_это_не_подмена():
    """`KORITSU_LLM_BASE_URL_DEEPSEEK=` (так compose передаёт незаполненную
    переменную) означает «не задано», а не «ходить в пустоту»."""
    s = Settings.from_env({"KORITSU_DATA_DIR": "/tmp/koritsu-проба",
                           "KORITSU_SECRET": "x" * 32,
                           "KORITSU_LLM_BASE_URL_DEEPSEEK": "  "})
    assert s.llm_base_urls == {}


def test_в_prod_адрес_не_отдаётся_даже_прочитанный(tmp_path):
    """Прочитан — да, применён — нет: `llm_base_url` и есть та единственная
    дверь, через которую подмена попадает в пресет."""
    s = настройки(tmp_path, env="prod", адреса={ПРЕСЕТ: АДРЕС})
    assert s.llm_base_urls == {ПРЕСЕТ: АДРЕС}          # прочитано
    assert s.llm_base_url(ПРЕСЕТ) is None              # не применяется


def test_в_dev_адрес_отдаётся(tmp_path):
    s = настройки(tmp_path, env="dev", адреса={ПРЕСЕТ: АДРЕС})
    assert s.llm_base_url(ПРЕСЕТ) == АДРЕС
    assert s.llm_base_url("anthropic") is None


# ── что достаётся прогону ────────────────────────────────────────────────────

def test_dev_прогон_идёт_на_подменённый_адрес(tmp_path, ключ_есть):
    """Ради этого всё и заведено: пресет собран с чужим адресом, остальное —
    как обычно (протокол, модель, имя переменной с ключом)."""
    ctx = Ктx(настройки(tmp_path, env="dev", адреса={ПРЕСЕТ: АДРЕС}))
    with runs_model.endpoint(ctx, ПРЕСЕТ) as (ep_id, откуда):
        spec = llm.spec_of(ep_id)
        assert spec.base_url == АДРЕС
        assert spec.protocol == "openai"
        assert spec.api_key_env == runs_model.ИМЯ_КЛЮЧА
        assert откуда == "own"


def test_prod_прогон_идёт_к_поставщику(tmp_path, ключ_есть):
    """Та же переменная, тот же прогон — и адрес поставщика, а не стенда."""
    ctx = Ктx(настройки(tmp_path, env="prod", адреса={ПРЕСЕТ: АДРЕС}))
    with runs_model.endpoint(ctx, ПРЕСЕТ) as (ep_id, _):
        assert llm.spec_of(ep_id).base_url == llm.presets.make(ПРЕСЕТ).base_url


def test_без_переменной_адрес_пресета(tmp_path, ключ_есть):
    """Умолчание не трогается ничем: нет переменной — нет и разницы."""
    ctx = Ктx(настройки(tmp_path, env="dev"))
    with runs_model.endpoint(ctx, ПРЕСЕТ) as (ep_id, _):
        assert llm.spec_of(ep_id).base_url == llm.presets.make(ПРЕСЕТ).base_url


# ── след в журнале ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("env, ожидается", [("dev", "dev"), ("prod", "не применяется")])
def test_подмена_всегда_видна_в_журнале(tmp_path, caplog, env, ожидается):
    """Молчать нельзя ни в том, ни в другом случае: в `dev` подменённый адрес
    объясняет странные ответы модели, в `prod` — почему подмена «не работает»."""
    caplog.set_level("WARNING", logger="api.error")
    предупредить_о_подмене(настройки(tmp_path, env=env, адреса={ПРЕСЕТ: АДРЕС}))
    записи = [з.getMessage() for з in caplog.records]
    assert записи and ожидается in " ".join(записи)
    assert АДРЕС in " ".join(записи)


def test_без_подмены_журнал_молчит(tmp_path, caplog):
    caplog.set_level("WARNING", logger="api.error")
    предупредить_о_подмене(настройки(tmp_path, env="dev"))
    assert not caplog.records
