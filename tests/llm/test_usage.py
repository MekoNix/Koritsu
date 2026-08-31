"""Учёт: приведённые единицы, деньги, конвенция «кэш снаружи входа», оценка.

Формула лимита живёт здесь, и главная ошибка, которую эти тесты стерегут, —
двойной счёт кэшированных токенов на endpoint'е, который отчитывается о кэше
внутри входа. Ошибка тихая: числа выглядят правдоподобно и врут примерно вдвое.
"""
from __future__ import annotations

from llm import usage as u
from llm.model import Prices, Usage


def test_формула_приведённых_единиц_на_умолчаниях():
    """input×1 + cache_read×0.1 + cache_write×1.25 + output×5."""
    usage = Usage(input=3000, output=1500, cache_read=9000, cache_write=0)
    assert u.units(usage) == 3000 + 900 + 0 + 7500


def test_веса_берутся_из_цен_endpointа():
    """Вес — отношение к цене входного токена; в этом смысл слова «приведённые»."""
    prices = Prices(input_per_mtok=2.0, output_per_mtok=20.0,
                    cache_read_per_mtok=0.2, cache_write_per_mtok=2.5)
    weights = u.weights(prices)
    assert weights["out"] == 10.0 and weights["read"] == 0.1 and weights["write"] == 1.25
    assert u.units(Usage(input=100, output=10), prices) == 100 + 100


def test_без_цен_работают_умолчания():
    assert u.weights(Prices()) == {"read": 0.1, "write": 1.25, "out": 5.0}


def test_кэш_внутри_входа_вычитается():
    """Иначе кэшированные токены посчитаются дважды: и как вход, и как кэш."""
    clean, read, write = u.normalize_cache(12000, 9000, 0, cache_inside_input=True)
    assert clean == 3000 and read == 9000
    assert u.units(Usage(input=clean, cache_read=read)) == 3000 + 900


def test_кэш_снаружи_входа_не_трогается():
    clean, read, _ = u.normalize_cache(3000, 9000, 0, cache_inside_input=False)
    assert clean == 3000 and read == 9000


def test_несогласованный_отчёт_не_уводит_в_минус():
    """Отрицательный вход сделал бы лимит отрицательным — это хуже недосчёта."""
    clean, _, _ = u.normalize_cache(100, 9000, 0, cache_inside_input=True)
    assert clean == 0


def test_двойной_счёт_виден_в_цифрах():
    """Наглядно, во сколько врёт пропущенное вычитание."""
    без_вычитания = u.units(Usage(input=12000, cache_read=9000))
    с_вычитанием = u.units(Usage(input=3000, cache_read=9000))
    assert без_вычитания / с_вычитанием > 3


# ── деньги ──────────────────────────────────────────────────────────────────
def test_деньги_none_когда_цен_нет():
    """None ≠ 0.0: «не знаем» и «бесплатно» в отчёте о расходах различны."""
    assert u.cost(Usage(input=1000, output=100), Prices()) is None
    assert u.cost(Usage(input=1000), None) is None


def test_деньги_считаются_по_сырым_счётчикам():
    prices = Prices(input_per_mtok=5.0, output_per_mtok=25.0,
                    cache_read_per_mtok=0.5, cache_write_per_mtok=6.25)
    usage = Usage(input=3000, output=1500, cache_read=9000)
    # 3000×5 + 1500×25 + 9000×0.5 всё делить на миллион
    assert u.cost(usage, prices) == round((15000 + 37500 + 4500) / 1e6, 6)


# ── оценка, когда счётчиков нет ─────────────────────────────────────────────
def test_оценка_растёт_с_длиной():
    assert u.estimate_tokens("x" * 350, 3.5) == 100
    assert u.estimate_tokens("") == 0


def test_калибровка_сдвигает_коэффициент_а_не_заменяет():
    """Один нетипичный вызов не должен дёргать коэффициент целиком."""
    new = u.calibrate(chars=2000, measured_tokens=1000, previous=3.5, weight=0.2)
    assert 3.0 < new < 3.5


def test_калибровка_отбрасывает_чушь():
    assert u.calibrate(chars=10, measured_tokens=1000, previous=3.5) == 3.5
    assert u.calibrate(chars=0, measured_tokens=0, previous=3.5) == 3.5


# ── сложение ────────────────────────────────────────────────────────────────
def test_сумма_помечается_оценкой_если_хоть_одно_слагаемое_оценка():
    """measured по И: смесь измеренного и оценённого — это оценка."""
    total = Usage(input=10, measured=True) + Usage(input=5, measured=False)
    assert total.input == 15 and total.measured is False


def test_reasoning_остаётся_none_если_его_нигде_не_было():
    assert (Usage() + Usage()).reasoning is None
    assert (Usage(reasoning=5) + Usage()).reasoning == 5
