"""
Настройки: обязательное — обязательно, умолчания — те, что решил владелец.

Проверяется здесь не чтение переменных, а то, ради чего настройки собраны в
одном месте: служба, настроенная неправильно, обязана **не подняться**. Каждая
из этих бед иначе обнаруживается на живом томе — пустой базой, чужим секретом
или корзиной, которая убирается не тогда.
"""
from __future__ import annotations

import os

import pytest

from api import Settings
from api.errors import ConfigError
from api.settings import MB, SECRET_MIN_BYTES

СЕКРЕТ = "x" * SECRET_MIN_BYTES


def окружение(**правки) -> dict:
    """Полное годное окружение с правками — чтобы тест называл только беду."""
    env = {"KORITSU_DATA_DIR": "/tmp/koritsu-проба", "KORITSU_SECRET": СЕКРЕТ}
    env.update({k: v for k, v in правки.items() if v is not None})
    for k, v in правки.items():
        if v is None:
            env.pop(k, None)
    return env


# ── обязательные ─────────────────────────────────────────────────────────────

def test_том_обязателен_умолчания_нет():
    """Путь задаётся снаружи. Умолчание вроде `./data`
    значило бы, что CI и контейнер расходятся молча."""
    with pytest.raises(ConfigError) as беда:
        Settings.from_env(окружение(KORITSU_DATA_DIR=None))
    assert "KORITSU_DATA_DIR" in str(беда.value)


def test_секрет_обязателен():
    with pytest.raises(ConfigError) as беда:
        Settings.from_env(окружение(KORITSU_SECRET=None))
    assert "KORITSU_SECRET" in str(беда.value)


def test_короткий_секрет_не_проходит():
    """`KORITSU_SECRET=test` переживает выкат и обнаруживается кражей ключей."""
    with pytest.raises(ConfigError):
        Settings.from_env(окружение(KORITSU_SECRET="x" * (SECRET_MIN_BYTES - 1)))


def test_сам_секрет_в_сообщение_не_попадает():
    """Текст беды уедет в журнал — секрету там не место."""
    почти = "тайна" * 3
    with pytest.raises(ConfigError) as беда:
        Settings.from_env(окружение(KORITSU_SECRET=почти))
    assert почти not in str(беда.value)


def test_режим_только_из_двух():
    with pytest.raises(ConfigError) as беда:
        Settings.from_env(окружение(KORITSU_ENV="stage"))
    assert "KORITSU_ENV" in str(беда.value)


# ── умолчания ────────────────────────────────────────────────────────────────

def test_умолчания_те_что_решил_владелец():
    s = Settings.from_env(окружение())
    assert s.env == "dev"
    assert s.user_quota_bytes == 250 * MB          # квота на владельца
    assert s.file_max_bytes == 10 * MB             # на один файл
    assert s.session_days == 30                    # сессия с продлением
    assert s.trash_days == 10                      # уборка корзины
    assert s.registrations_per_ip_per_day > 0      # заслон от массовой регистрации


def test_база_по_умолчанию_лежит_в_томе():
    """Снимок тома должен забирать базу вместе с файлами: снимок из одного без
    другого бесполезен."""
    s = Settings.from_env(окружение(KORITSU_DATA_DIR="/tmp/koritsu-том"))
    assert s.db_url == "sqlite:////tmp/koritsu-том/koritsu.db"
    assert s.is_sqlite


def test_база_переопределяется():
    s = Settings.from_env(окружение(KORITSU_DB_URL="sqlite:///:memory:"))
    assert s.db_url == "sqlite:///:memory:"


def test_числа_читаются_и_проверяются():
    s = Settings.from_env(окружение(KORITSU_FILE_MAX_BYTES="64",
                                    KORITSU_TRASH_DAYS="3"))
    assert (s.file_max_bytes, s.trash_days) == (64, 3)


def test_мусор_в_числе_это_беда_а_не_умолчание():
    """Тихое умолчание на опечатке означало бы, что корзина убирается не тогда,
    и заметили бы это по пропавшим файлам."""
    with pytest.raises(ConfigError) as беда:
        Settings.from_env(окружение(KORITSU_TRASH_DAYS="десять"))
    assert "KORITSU_TRASH_DAYS" in str(беда.value)


def test_пустая_строка_это_не_задано():
    """docker compose так передаёт незаполненную переменную."""
    assert Settings.from_env(окружение(KORITSU_TRASH_DAYS="")).trash_days == 10


def test_ноль_и_минус_не_проходят():
    with pytest.raises(ConfigError):
        Settings.from_env(окружение(KORITSU_FILE_MAX_BYTES="0"))


# ── прокси и адрес сайта ─────────────────────────────────────────────────────

def test_доверие_прокси_умалчивается_из_режима():
    """За Caddy (prod) `X-Forwarded-For` — единственный источник настоящего
    адреса; на открытом порту (dev) он — подделка, и лимит регистраций по IP
    обходится одной строкой заголовка."""
    assert Settings.from_env(окружение()).trust_proxy is False
    assert Settings.from_env(окружение(KORITSU_ENV="prod")).trust_proxy is True


def test_доверие_прокси_задаётся_явно():
    assert Settings.from_env(окружение(KORITSU_TRUST_PROXY="yes")).trust_proxy
    assert not Settings.from_env(
        окружение(KORITSU_ENV="prod", KORITSU_TRUST_PROXY="no")).trust_proxy


def test_мусор_в_да_нет_это_беда_а_не_нет():
    """Понятый как «нет», `maybe` превратил бы лимит «5 на адрес» в «5 на весь
    сайт»: за прокси адрес у всех один."""
    with pytest.raises(ConfigError) as беда:
        Settings.from_env(окружение(KORITSU_TRUST_PROXY="maybe"))
    assert "KORITSU_TRUST_PROXY" in str(беда.value)


def test_адрес_сайта_умолчание_и_правка():
    """Умолчание — localhost, а не рабочий домен: забытая настройка на
    dev-машине иначе шлёт людям ссылки на живой сайт с токеном, которого там
    нет."""
    assert Settings.from_env(окружение()).base_url == "http://localhost:8000"
    свой = Settings.from_env(окружение(KORITSU_BASE_URL="https://koritsu.ru/"))
    assert свой.base_url == "https://koritsu.ru"     # хвостовая косая срезана


# ── прочее ───────────────────────────────────────────────────────────────────

def test_том_приводится_к_абсолютному(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    s = Settings.from_env(окружение(KORITSU_DATA_DIR="данные"))
    assert os.path.isabs(s.data_dir)
    assert s.data_dir.endswith("данные")


def test_настройки_неизменяемы(tmp_path):
    s = Settings.for_tests(tmp_path)
    with pytest.raises(Exception):
        s.env = "prod"          # type: ignore[misc]


def test_for_tests_даёт_годные_настройки_и_пускает_правки(tmp_path):
    s = Settings.for_tests(tmp_path, file_max_bytes=64)
    assert s.data_dir == str(tmp_path)
    assert len(s.secret.encode("utf-8")) >= SECRET_MIN_BYTES
    assert s.file_max_bytes == 64


# ── разборщик чужих файлов ───────────────────────────────────────────────────
#
# Таймаут и потолок памяти подпроцесса разбора. Числа были константами в
# `materials/parsing.py`, а теперь живут здесь — и проверяется тут ровно то,
# ради чего их сюда перенесли: машина,
# на которой тяжёлый скан не укладывается в минуту, чинится строкой в `.env`, а
# не правкой кода и выкатом.

def test_разбор_умолчания():
    """Шестьдесят секунд и гигабайт — те же числа, что стояли константами."""
    s = Settings.from_env(окружение())
    assert s.parse_timeout_s == 60
    assert s.parse_memory_mb == 1024
    assert s.parse_memory_bytes == 1024 * MB


def test_разбор_читается_из_окружения():
    s = Settings.from_env(окружение(KORITSU_PARSE_TIMEOUT_S="5",
                                    KORITSU_PARSE_MEMORY_MB="256"))
    assert s.parse_timeout_s == 5
    assert s.parse_memory_mb == 256
    assert s.parse_memory_bytes == 256 * MB


@pytest.mark.parametrize("имя", ["KORITSU_PARSE_TIMEOUT_S",
                                 "KORITSU_PARSE_MEMORY_MB"])
def test_разбор_мусор_это_беда(имя):
    """`KORITSU_PARSE_TIMEOUT_S=60s` — опечатка, а не шестьдесят и не умолчание.

    Молчаливое умолчание здесь означало бы, что машина, поднятая с опечаткой,
    режет разбор по чужому числу, и ни одной строки о том, почему.
    """
    with pytest.raises(ConfigError) as беда:
        Settings.from_env(окружение(**{имя: "60s"}))
    assert имя in str(беда.value)


@pytest.mark.parametrize("имя", ["KORITSU_PARSE_TIMEOUT_S",
                                 "KORITSU_PARSE_MEMORY_MB"])
def test_разбор_ноль_это_беда(имя):
    """Нулевой таймаут — разбор, который не начинается; нулевая память —
    подпроцесс, который не успевает импортировать `materials`. И то, и другое
    выглядело бы как «файлы перестали загружаться», без единой подсказки."""
    with pytest.raises(ConfigError) as беда:
        Settings.from_env(окружение(**{имя: "0"}))
    assert имя in str(беда.value)


# ── очередь заданий и воркер ─────────────────────────────────────────────────
#
# Те же три проверки, что у разбора, и по той же причине: числа очереди решают,
# сколько работы идёт разом и когда она признаётся потерянной, а машина,
# поднятая с опечаткой в них, ведёт себя иначе и молча.

ОЧЕРЕДЬ = ["KORITSU_JOB_SLOTS", "KORITSU_JOBS_PER_USER",
           "KORITSU_WORKER_POLL_S", "KORITSU_JOB_TIMEOUT_S",
           "KORITSU_JOB_MEMORY_MB", "KORITSU_JOBS_RETENTION_DAYS"]


def test_очередь_умолчания():
    """Слоты: 2 тяжёлых задания на машину, 1 на пользователя, остальные ждут
    в очереди."""
    s = Settings.from_env(окружение())
    assert s.job_slots == 2
    assert s.jobs_per_user == 1
    assert s.worker_poll_s == 1.0
    assert s.job_timeout_s == 1800
    assert s.job_memory_mb == 2048
    assert s.job_memory_bytes == 2048 * MB
    assert s.jobs_retention_days == 90


def test_очередь_читается_из_окружения():
    """Машина вдвое мощнее чинится строкой в `.env`, а не правкой кода."""
    s = Settings.from_env(окружение(KORITSU_JOB_SLOTS="4",
                                    KORITSU_JOBS_PER_USER="2",
                                    KORITSU_WORKER_POLL_S="0.25",
                                    KORITSU_JOB_TIMEOUT_S="600",
                                    KORITSU_JOB_MEMORY_MB="512",
                                    KORITSU_JOBS_RETENTION_DAYS="30"))
    assert (s.job_slots, s.jobs_per_user) == (4, 2)
    assert s.worker_poll_s == 0.25
    assert (s.job_timeout_s, s.job_memory_mb) == (600, 512)
    assert s.jobs_retention_days == 30


def test_опрос_очереди_бывает_дробным():
    """Секунда — потолок задержки перед началом работы, и на живом сайте её
    захотят уменьшить, а не увеличить; целое число этого не позволило бы."""
    assert Settings.from_env(
        окружение(KORITSU_WORKER_POLL_S="0.05")).worker_poll_s == 0.05


@pytest.mark.parametrize("имя", ОЧЕРЕДЬ)
def test_очередь_мусор_это_беда(имя):
    """`KORITSU_JOB_SLOTS=два` — опечатка, а не два и не умолчание."""
    with pytest.raises(ConfigError) as беда:
        Settings.from_env(окружение(**{имя: "два"}))
    assert имя in str(беда.value)


@pytest.mark.parametrize("имя", ОЧЕРЕДЬ)
def test_очередь_ноль_это_беда(имя):
    """Ноль слотов — воркер, который никогда ничего не берёт, и очередь,
    растущая молча. Отказ на старте дешевле."""
    with pytest.raises(ConfigError) as беда:
        Settings.from_env(окружение(**{имя: "0"}))
    assert имя in str(беда.value)
