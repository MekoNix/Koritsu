"""
journal — журнал расхода и поведение на границе лимита (В.4, В.5).

Одна запись на **один вызов модели**, не на прогон и не на тег: прогон агента —
это десятки вызовов, и без разбивки нельзя понять, что именно съело бюджет.

Слой не знает ни про теги, ни про прогоны, ни про пользователей — эти поля
приходят от вызывающей службы одним словарём `meta` и кладутся в запись как
есть. Если завести их полями здесь, в слой протечёт бизнес-логика, и первый же
второй потребитель (не hokoku) обнаружит, что журнал требует «тег».

Три поля обязательны и все три неочевидны:
  * `price_snapshot` — цена на момент вызова. Цена в настройках меняется, и без
    снимка прошлые месяцы пересчитаются задним числом по новому прайсу.
  * `degraded` — объяснение, почему вызов стоил столько. Без него «этот тег
    обошёлся вчетверо дороже вчерашнего» необъяснимо.
  * `own_key` — расход по своему ключу пользователя считаем и показываем, но
    против тарифа не засчитываем. Без флага это не разделить.

Хранилища здесь нет намеренно: журнал складывает записи в подключаемый приёмник
(`sink`). Куда их писать — SQLite, файл, ничего — решает вызывающая служба.

Здесь же собирается `meta` записи — `with_retries` и `step_meta`. Раньше они
лежали в `api` и `loop`, и правда о том, чего вызов стоил, оказывалась
размазанной по двум модулям: `loop` ходил за забором записок в `api`, то есть
знал про журнальную сторону соседа. Имена в прежних модулях оставлены
переэкспортом — вызывающие снаружи пакета их могли взять оттуда.
"""
from __future__ import annotations

import datetime

from .errors import ErrorKind, LlmError
from .model import EndpointSpec, Result


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def with_retries(meta, backend) -> dict:
    """meta вызывающего плюс записки о повторах транспорта на ЭТОМ вызове.

    Живёт здесь, а не у вызывающего: правда о том, чего вызов стоил, должна
    собираться в одном месте. Раньше забор записок стоял в `api`, а `loop`
    ходил за ним туда же — то есть один модуль знал про журнальную сторону
    другого, и второй забор рано или поздно завёлся бы отдельно.

    Забирает записки тот, кто сделал вызов, и никто другой. Записка,
    оставленная в транспорте, дождётся следующего забирающего и припишется
    чужому вызову: повтор, случившийся при генерации значения, всплывал в
    записи хода петли, прошедшего с первой попытки. Тогда «почему этот ход шёл
    вчетверо дольше» получает ложный ответ, а настоящая задержка так и остаётся
    необъяснимой.

    Забираем и когда журнала нет: записка принадлежит этому вызову, и оставить
    её значит подложить её следующему.
    """
    take = getattr(backend.transport(), "take_retries", None)
    notes = take() if callable(take) else []
    if not notes:
        return meta
    return {**(meta or {}), "retries": notes}


def step_meta(meta, step: int, backend) -> dict:
    """meta вызывающей службы + номер хода + повторы транспорта на этом ходу.

    Ход петли инструментов — такой же вызов модели, как одиночный, и запись о
    нём отличается ровно одним полем. Поэтому и живёт рядом с `with_retries`:
    два места забора записок означали бы, что одно из них рано или поздно
    забудут, а забытая записка достанется чужому вызову.

    Повторы кладутся в запись, потому что иначе они невидимы: ход, который
    из-за трёх пауз занял вчетверо дольше соседнего, в журнале ничем от него не
    отличается, и «почему прогон шёл двадцать минут» не расследуется.
    """
    return with_retries({**(meta or {}), "step": step}, backend)


def record(result: Result, spec: EndpointSpec, meta: dict | None = None) -> dict:
    """Result + описание endpoint'а → запись журнала.

    Сырые счётчики попадают в запись все до одного, приведённые единицы — рядом,
    а не вместо: из одного числа «токены» не получить ни денег, ни осмысленного
    лимита, а из записи считается всё — месячный расход, разбивка по
    endpoint'ам, средняя цена тега, доля попаданий в кэш.
    """
    usage = result.usage
    entry: dict = {
        "at": _now(),
        "endpoint": spec.id,
        "protocol": spec.protocol,
        "model": spec.model,
        "input": usage.input,
        "output": usage.output,
        "cache_read": usage.cache_read,
        "cache_write": usage.cache_write,
        "reasoning": usage.reasoning,
        "measured": usage.measured,
        "units": result.units,
        "cost": result.cost,
        "price_snapshot": spec.prices.as_snapshot(),
        "degraded": list(result.degraded),
        "attempts": result.attempts,
        "stop": result.stop,
        "structured_step": result.structured_step,
        "latency_ms": result.latency_ms,
        "request_id": result.request_id,
        "own_key": bool(spec.own_key),
        "ok": result.ok,
        "raw_usage": dict(result.raw_usage or {}),
    }
    if result.error is not None:
        entry["error_kind"] = getattr(result.error, "kind", ErrorKind.TRANSPORT)
    # meta от вызывающей службы: run, tag, project, user — слой их не толкует.
    for key, value in (meta or {}).items():
        entry.setdefault(key, value)
    return entry


class Journal:
    """Журнал вызовов с подключаемым приёмником.

    По умолчанию копит в памяти: пакету этого достаточно, а долговременное
    хранение — дело службы, которая его подключает.
    """

    def __init__(self, sink=None):
        self.entries: list = []
        self._sink = sink

    def add(self, result: Result, spec: EndpointSpec, meta: dict | None = None) -> dict:
        entry = record(result, spec, meta)
        self.entries.append(entry)
        if self._sink is not None:
            self._sink(entry)
        return entry

    def total_units(self, own_key: bool = False, since: str | None = None) -> float:
        """Сумма приведённых единиц.

        `own_key=False` (по умолчанию) — только то, что идёт против тарифа:
        расход по ключу пользователя считаем и показываем, но в лимит не берём.
        """
        total = 0.0
        for entry in self.entries:
            if not own_key and entry.get("own_key"):
                continue
            if since and entry.get("at", "") < since:
                continue
            total += entry.get("units") or 0.0
        return round(total, 3)

    def estimated_share(self, own_key: bool = False, since: str | None = None) -> float:
        """Доля суммы, которая не измерена, а оценена (В.3).

        Оценки в сумму лимита входят, но пользователю показывается, какая часть
        оценена. Иначе через месяц никто не объяснит, откуда взялась цифра.

        Отбор записей тот же, что у `total_units`, и это не формальность: доля
        считается ОТ той суммы, которую доля объясняет. Считай её по всем
        записям, а сумму — по тарифным, и «сколько из этих денег оценка»
        отвечало бы про другие деньги.
        """
        total = 0.0
        estimated = 0.0
        for entry in self.entries:
            if not own_key and entry.get("own_key"):
                continue
            if since and entry.get("at", "") < since:
                continue
            units = entry.get("units") or 0.0
            total += units
            if not entry.get("measured", True):
                estimated += units
        return round(estimated / total, 4) if total else 0.0

    def total_cost(self, since: str | None = None) -> float | None:
        """Деньги. None — если ни по одному вызову цена не была известна."""
        known = [e.get("cost") for e in self.entries
                 if e.get("cost") is not None and (not since or e.get("at", "") >= since)]
        return round(sum(known), 6) if known else None


class Limit:
    """Лимит в приведённых единицах и поведение на его границе (В.5).

    Правила, которые не зависят от поставщика:
      * отказ **до** вызова, а не посреди: посреди — это потраченные деньги
        без результата;
      * начавшийся прогон дорабатывает: обрывать на середине хуже, чем немного
        превысить;
      * пороги предупреждения 70 / 85 / 95 %;
      * отказ приходит **с цифрой**, а не «попробуйте позже»: пользователь
        должен видеть, сколько не хватило.
    """

    THRESHOLDS = (0.70, 0.85, 0.95)

    def __init__(self, cap_units: float, journal: Journal | None = None,
                 period_start: str | None = None):
        self.cap_units = float(cap_units)
        self.journal = journal or Journal()
        self.period_start = period_start

    def spent(self) -> float:
        return self.journal.total_units(since=self.period_start)

    def remaining(self) -> float:
        return round(max(0.0, self.cap_units - self.spent()), 3)

    def share(self) -> float:
        return round(self.spent() / self.cap_units, 4) if self.cap_units else 0.0

    def warning(self) -> float | None:
        """Достигнутый порог предупреждения (0.70 / 0.85 / 0.95) или None."""
        share = self.share()
        reached = [t for t in self.THRESHOLDS if share >= t]
        return reached[-1] if reached else None

    def check(self, estimate_units: float) -> None:
        """Пускать ли вызов. Бросает LlmError(LIMIT_EXCEEDED) с цифрами.

        Проверяется оценка, а не факт: смысл в том, чтобы отказать до вызова.
        Оценка может ошибиться, и тогда лимит слегка переберётся — это дешевле,
        чем обрывать прогон на середине.
        """
        need = float(estimate_units or 0.0)
        left = self.remaining()
        if need > left:
            raise LlmError(
                ErrorKind.LIMIT_EXCEEDED,
                f"не хватает лимита: нужно ≈{need:.0f} единиц, осталось {left:.0f} "
                f"из {self.cap_units:.0f}")


__all__ = ["Journal", "Limit", "record", "with_retries", "step_meta"]
