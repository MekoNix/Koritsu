"""
usage — приведённые единицы, деньги и оценка токенов, когда счётчиков нет.

Решение владельца (2026-08-29): лимит считаем в токенах. Записка (В.1) уточняет,
почему сложить четыре числа из usage в одно нельзя: токен входа, токен из кэша и
токен выхода отличаются в цене до 50 раз. Поэтому лимит считается в
**приведённых единицах** — «сколько это стоило бы, будь всё входными токенами
этого endpoint'а»:

    единицы = input×1 + cache_read×w_read + cache_write×w_write + output×w_out
    умолчания: w_read = 0.1, w_write = 1.25, w_out = 5

Умолчания не выдуманы: у Anthropic чтение кэша — 0.1× входа, запись — 1.25×, а
отношение выход/вход равно 5 у всего семейства (Opus 5 $5/$25, Sonnet 5 $2/$10,
Fable 5 $10/$50). Если у endpoint'а отношение другое, оно берётся из его цен.

Сырые счётчики хранятся все и всегда — приведённые единицы их не заменяют.
"""
from __future__ import annotations

from .model import Prices, Usage

# Веса по умолчанию, когда цены endpoint'а не заполнены.
W_READ_DEFAULT = 0.1
W_WRITE_DEFAULT = 1.25
W_OUT_DEFAULT = 5.0


def weights(prices: Prices | None) -> dict:
    """Веса приведённых единиц: из цен endpoint'а, иначе умолчания.

    Вес считается как отношение к цене входного токена — в этом и есть смысл
    слова «приведённые». Нулевая или отсутствующая цена входа делает отношение
    неопределённым, поэтому тогда работают умолчания целиком.
    """
    if prices is None or not prices.input_per_mtok:
        return {"read": W_READ_DEFAULT, "write": W_WRITE_DEFAULT, "out": W_OUT_DEFAULT}
    base = float(prices.input_per_mtok)
    out = (prices.output_per_mtok / base) if prices.output_per_mtok else W_OUT_DEFAULT
    read = (prices.cache_read_per_mtok / base) if prices.cache_read_per_mtok is not None \
        else W_READ_DEFAULT
    write = (prices.cache_write_per_mtok / base) if prices.cache_write_per_mtok is not None \
        else W_WRITE_DEFAULT
    return {"read": read, "write": write, "out": out}


def units(usage: Usage, prices: Prices | None = None) -> float:
    """Приведённые единицы одного вызова. Лимит пользователя считается здесь."""
    w = weights(prices)
    return round(
        usage.input * 1.0
        + usage.cache_read * w["read"]
        + usage.cache_write * w["write"]
        + usage.output * w["out"],
        3,
    )


def cost(usage: Usage, prices: Prices | None) -> float | None:
    """Деньги. None означает «по этому endpoint'у деньги не считаем».

    Отличать None от 0.0 обязательно: незаполненная цена — это «не знаем»,
    а не «бесплатно». Ноль в отчёте о расходах не отличим от бесплатного
    endpoint'а, и первый же вопрос «сколько мы потратили» получит неверный ответ.

    Считается по сырым счётчикам, а не по единицам: единицы — приближение для
    лимита, а деньги должны сходиться с счётом поставщика.
    """
    if prices is None or not prices.filled():
        return None
    million = 1_000_000.0
    total = (usage.input * (prices.input_per_mtok or 0.0)
             + usage.output * (prices.output_per_mtok or 0.0)
             + usage.cache_read * (prices.cache_read_per_mtok or 0.0)
             + usage.cache_write * (prices.cache_write_per_mtok or 0.0)) / million
    return round(total, 6)


# ── оценка, когда usage не пришёл (В.3) ─────────────────────────────────────
def estimate_tokens(text: str, chars_per_token: float = 3.5) -> int:
    """Грубая оценка числа токенов по длине текста.

    Метод сознательно примитивный: символы на калиброванный коэффициент.
    Точность здесь недостижима — токенизаторы у поставщиков разные и закрытые,
    а расхождение между ними и так больше погрешности этой формулы (В.1).
    Важнее другое: результат такой оценки обязан быть помечен `measured=False`,
    иначе через месяц никто не объяснит, откуда взялась цифра расхода.

    Коэффициент 3.5 — среднее по смешанному русско-английскому тексту с кодом.
    На чистой кириллице токенов больше (коэффициент ближе к 2), поэтому проба
    (Б.4) уточняет его через calibrate() по тем своим шагам, где usage всё-таки
    пришёл, и кладёт уточнённое в описание endpoint'а (EndpointSpec.apply_probe).
    Вызывающий обычно передаёт сюда именно `spec.chars_per_token`.
    """
    if not text:
        return 0
    return max(1, int(round(len(text) / max(0.5, chars_per_token))))


def calibrate(chars: int, measured_tokens: int, previous: float = 3.5,
              weight: float = 0.2) -> float:
    """Уточняет «символов на токен» по вызову, где usage пришёл.

    Скользящее среднее, а не замена: один вызов может быть нетипичным (сплошной
    код, сплошная кириллица), и дёргать коэффициент на каждом — хуже, чем
    держать его слегка устаревшим. `weight` — доля нового наблюдения.

    Кормить сюда можно ТОЛЬКО измеренный usage. Оценка сама посчитана по
    `previous`, и калибровка по ней уточняла бы коэффициент по нему самому —
    цифра выглядела бы подтверждённой, ничего не подтверждая.
    """
    if measured_tokens <= 0 or chars <= 0:
        return previous
    observed = chars / measured_tokens
    if not (0.5 <= observed <= 20):
        return previous          # заведомая чушь: не портим коэффициент
    return round(previous * (1 - weight) + observed * weight, 3)


def normalize_cache(input_tokens: int, cache_read: int, cache_write: int,
                    cache_inside_input: bool) -> tuple:
    """Приводит счётчики к нашей конвенции: `input` — только НЕкэшированный вход.

    Ради этой функции в `declared` заведено поле `cache_inside_input`. У
    Anthropic кэш приходит снаружи входа и вычитать нечего; endpoint, который
    считает кэш внутри prompt_tokens, без вычитания даст двойной счёт
    кэшированных токенов — и приведённые единицы соврут примерно вдвое.

    Вычитание защищено от отрицательного результата: если endpoint отчитался
    несогласованно (кэша больше, чем входа), верить входу нельзя, но и уходить
    в минус нельзя — лимит станет отрицательным.
    """
    if not cache_inside_input:
        return input_tokens, cache_read, cache_write
    clean = input_tokens - cache_read - cache_write
    return max(0, clean), cache_read, cache_write


__all__ = ["units", "cost", "weights", "estimate_tokens", "calibrate",
           "normalize_cache",
           "W_READ_DEFAULT", "W_WRITE_DEFAULT", "W_OUT_DEFAULT"]
