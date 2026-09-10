"""
_spec — спецификация графика: словарь от вызывающего → проверенный `ChartSpec`.

Проверка строгая и вся здесь, до matplotlib. Причина не в аккуратности: почти
всё, что модель может прислать не так, matplotlib примет молча и нарисует
правдоподобную неправду. Строка `"12"` вместо числа станет подписью категории —
и на графике окажется ось, которой не было в данных; `x` короче `y` даст отказ с
текстом про размеры массивов, написанным для того, кто пишет скрипт; лишнее поле
пропадёт без следа. Поэтому годное описано перечнем, а на всё остальное
отвечается фразой, по которой видно, **какое поле** и **что с ним не так**:
её читает тот, кто спецификацию прислал, и правит вызов.

Обрезание — не то же самое, что отказ. Серии сверх потолка и точки сверх потолка
не портят картинку, а делают её нечитаемой, и правильный ответ на них —
нарисовать сколько влезает и сказать, что отброшено (`notes`). Отказ остаётся
там, где рисовать нечего или нарисованное будет ложью.

Формы данных ровно три, по видам графика:

  series-виды (line, bar, barh, scatter, step, area) — `series: [{name, x, y}]`;
  pie                                                — `labels` + `values`;
  hist                                               — `values` + `bins`.

Смешивать их нельзя: `series` у pie — не «лишнее поле, которое можно
проигнорировать», а признак того, что данные собраны не для того графика.
"""
from __future__ import annotations

import difflib
import math
from dataclasses import dataclass

# Виды графика. Перечень конечен и постоянен: вызывающий объявляет его модели
# как единственно возможное, и «нарисуй что-нибудь ещё» здесь не бывает.
KINDS = ("line", "bar", "barh", "scatter", "pie", "hist", "step", "area")

# Виды, у которых данные — это `series`. Остальные два (pie, hist) устроены
# иначе, и это не исключение из правила, а разные вопросы: у круговой доли
# целого, у гистограммы — один ряд замеров, который она сама раскладывает.
SERIES_KINDS = ("line", "bar", "barh", "scatter", "step", "area")

# Виды, у которых ось x — это подписи категорий, а не числовая шкала.
# Столбчатый график по числовому x рисовать можно, но незачем: числами по x
# отвечают line и scatter, а столбцы отвечают на «сколько у каждого из».
CATEGORY_KINDS = ("bar", "barh")

# Размеры фигуры в дюймах (ширина, высота). Названы словами, а не числами:
# дюймы модель выбирать не должна — она не знает ни поля страницы, ни того, во
# сколько раз картинку ужмёт вёрстка. Пропорции близки к 16:10 — на такой
# ширине помещается подпись оси, не наезжая на соседнюю.
SIZES = {"small": (5.0, 3.2), "medium": (7.6, 4.6), "large": (10.0, 6.0)}
DEFAULT_SIZE = "medium"

# Темы — те же два слова, что у схем. Умолчание светлое: график едет в документ
# на белый лист, и тёмная плашка посреди страницы там выглядит опечаткой.
# Тёмная нужна тому, кто показывает график на экране рядом с тёмной схемой.
THEMES = ("light", "dark")
DEFAULT_THEME = "light"

# Потолки. Серий больше восьми не различит глаз (столько же и цветов в палитре);
# точек больше пяти тысяч не различит бумага — на ширине графика их меньше, чем
# пикселей. Оба потолка обрезают, а не отказывают.
MAX_SERIES = 8
MAX_POINTS = 5000

# Столбиков гистограммы. Потолок нужен от опечатки в порядке (`bins: 10000`):
# такая гистограмма рисуется долго и читается как сплошная заливка.
MAX_BINS = 200
DEFAULT_BINS = 20

# Длина подписей. Заголовок длиннее строки уезжает за край картинки, и обрезать
# его лучше здесь, где об этом можно сказать вслух, чем в отрисовке молча.
MAX_TITLE_CHARS = 120
MAX_LABEL_CHARS = 60

# Поля спецификации, общие для всех видов. Перечень нужен отказу на незнакомое
# поле: «поля gride нет» с подсказкой чинится следующим ходом, а молча
# проглоченное поле оставляет вызывающего в уверенности, что сетку он включил.
_COMMON_FIELDS = ("kind", "title", "x_label", "y_label", "legend", "grid",
                  "size", "theme")
_FIELDS = {
    **{k: (*_COMMON_FIELDS, "series") for k in SERIES_KINDS},
    "pie": (*_COMMON_FIELDS, "labels", "values"),
    "hist": (*_COMMON_FIELDS, "values", "bins"),
}
_SERIES_FIELDS = ("name", "x", "y")


class ChartError(Exception):
    """Спецификация не годится, и починить это может тот, кто её прислал.

    Не наследник чего-либо общего намеренно: пакет чистый, про службу и про
    модель не знает. `field` — имя поля, на котором всё кончилось; вызывающий
    кладёт его в свой ответ рядом с текстом, чтобы чинить не пришлось наугад.
    """

    def __init__(self, message: str, *, field: str = ""):   # noqa: A002
        super().__init__(message)
        self.message = message
        self.field = field


@dataclass(frozen=True)
class Series:
    """Одна кривая (или группа столбцов): имя для легенды и точки.

    `x` — всегда числа: подписи категорий, если они были, вынесены в
    `ChartSpec.x_labels`, а сюда встали их места (0, 1, 2 …). Так сделано
    потому, что категории у графика одни на всех: две серии с разными наборами
    подписей — это два графика, а не один, и нарисованные вместе они дали бы
    столбцы, стоящие не над своими делениями.
    """

    name: str
    x: tuple[float, ...]
    y: tuple[float, ...]


@dataclass(frozen=True)
class ChartSpec:
    """Проверенная спецификация: дальше рисование, никаких решений о данных.

    Одно поле `values` на pie и hist, а не два с разными именами: значения там
    и там — просто числа, а разница в том, что с ними делают (доли целого против
    раскладки по столбикам), и она уже названа полем `kind`.
    """

    kind: str
    title: str = ""
    x_label: str = ""
    y_label: str = ""
    series: tuple[Series, ...] = ()
    x_labels: tuple[str, ...] = ()      # подписи делений, когда x — не числа
    labels: tuple[str, ...] = ()        # доли круговой
    values: tuple[float, ...] = ()      # значения круговой и замеры гистограммы
    bins: int = DEFAULT_BINS
    legend: bool = False
    grid: bool = True
    size: str = DEFAULT_SIZE
    theme: str = DEFAULT_THEME

    @property
    def inches(self) -> tuple[float, float]:
        return SIZES[self.size]

    def to_dict(self) -> dict:
        """Спецификация словарём — для журнала производных.

        Пишется то, что нарисовано, а не то, что прислали: обрезанное обрезано,
        умолчания проставлены. Запись отвечает на вопрос «что на этой картинке»,
        и присланное до обрезания отвечало бы на него неправдой.
        """
        out: dict = {"kind": self.kind, "size": self.size, "theme": self.theme,
                     "legend": self.legend, "grid": self.grid}
        for name in ("title", "x_label", "y_label"):
            if getattr(self, name):
                out[name] = getattr(self, name)
        if self.series:
            out["series"] = [{"name": s.name, "x": list(s.x), "y": list(s.y)}
                             for s in self.series]
        if self.x_labels:
            out["x_labels"] = list(self.x_labels)
        if self.labels:
            out["labels"] = list(self.labels)
        if self.values:
            out["values"] = list(self.values)
        if self.kind == "hist":
            out["bins"] = self.bins
        return out


def check(raw) -> tuple[ChartSpec, list[str]]:
    """Словарь → `ChartSpec` и список предупреждений. Отказ — `ChartError`."""
    if not isinstance(raw, dict):
        raise ChartError(f"спецификация графика — объект, а не {_ru(raw)}")
    kind = _one_of(raw.get("kind"), KINDS, "kind")
    _known_fields(raw, kind)
    notes: list[str] = []
    common = {
        "kind": kind,
        "title": _text(raw.get("title"), "title", MAX_TITLE_CHARS, notes),
        "x_label": _text(raw.get("x_label"), "x_label", MAX_LABEL_CHARS, notes),
        "y_label": _text(raw.get("y_label"), "y_label", MAX_LABEL_CHARS, notes),
        "grid": _flag(raw.get("grid"), "grid", default=True),
        "size": _one_of(raw.get("size") or DEFAULT_SIZE, tuple(SIZES), "size"),
        "theme": _one_of(raw.get("theme") or DEFAULT_THEME, THEMES, "theme"),
    }
    if kind == "pie":
        labels, values = _pie(raw, notes)
        # Легенда круговой по умолчанию не нужна: доли подписаны у самих
        # секторов, и второй список тех же слов рядом только съедает место.
        return ChartSpec(labels=labels, values=values,
                         legend=_flag(raw.get("legend"), "legend", default=False),
                         **common), notes
    if kind == "hist":
        values, bins = _hist(raw, notes)
        return ChartSpec(values=values, bins=bins,
                         legend=_flag(raw.get("legend"), "legend", default=False),
                         **common), notes
    series, x_labels = _series(raw, kind, notes)
    # Легенда по умолчанию — там, где серий больше одной: у единственной кривой
    # она называет то, что и так написано в заголовке.
    legend = _flag(raw.get("legend"), "legend", default=len(series) > 1)
    return ChartSpec(series=series, x_labels=x_labels, legend=legend, **common), notes


# ── данные по видам ──────────────────────────────────────────────────────────

def _series(raw: dict, kind: str,
            notes: list[str]) -> tuple[tuple[Series, ...], tuple[str, ...]]:
    """`series` → кривые и подписи делений.

    Категории (нечисловой `x`, а у столбчатых — любой) сводятся к одному набору
    на весь график: серии с разными подписями по x рисовать вместе нельзя, а
    подогнать их друг под друга можно только выдумав недостающие значения.
    """
    items = raw.get("series")
    if not isinstance(items, list) or not items:
        raise ChartError(
            f"series: у {kind} данные задаются непустым списком серий "
            f"[{{name, x, y}}]", field="series")
    if len(items) > MAX_SERIES:
        notes.append(f"серий было {len(items)} — нарисованы первые {MAX_SERIES}")
        items = items[:MAX_SERIES]

    разобранные = [_one_series(item, n, notes) for n, item in enumerate(items, 1)]
    урезано = sum(1 for *_, обрезана in разобранные if обрезана)
    if урезано:
        notes.append(f"точек в серии было больше {MAX_POINTS} — нарисованы "
                     f"первые {MAX_POINTS}" + (f" (серий с обрезкой: {урезано})"
                                               if урезано > 1 else ""))
    сырые = [(name, x, y) for name, x, y, _ in разобранные]
    подписи = _x_labels(сырые, kind)
    out = []
    for n, (name, x, y) in enumerate(сырые, 1):
        if подписи:
            x = tuple(float(i) for i in range(len(y)))
        elif x is None:
            # x не дали — точки нумеруются с единицы: «замер номер такой-то».
            x = tuple(float(i) for i in range(1, len(y) + 1))
        out.append(Series(name=name or f"ряд {n}", x=x, y=y))
    return tuple(out), подписи


def _one_series(item, n: int, notes: list[str]):
    """Одна запись `series` → имя, x (числа, подписи или None), y и признак обрезки."""
    where = f"series[{n}]"
    if not isinstance(item, dict):
        raise ChartError(f"{where}: серия — объект {{name, x, y}}, а не {_ru(item)}",
                         field=where)
    _unknown(item, _SERIES_FIELDS, where)
    name = _text(item.get("name"), f"{where}.name", MAX_LABEL_CHARS, notes)
    y = item.get("y")
    if not isinstance(y, list) or not y:
        raise ChartError(f"{where}.y: непустой список чисел", field=f"{where}.y")
    x = item.get("x")
    if x is not None and not isinstance(x, list):
        raise ChartError(f"{where}.x: список той же длины, что y, или не задан вовсе",
                         field=f"{where}.x")
    if x is not None and len(x) != len(y):
        raise ChartError(
            f"{where}: x и y разной длины — {len(x)} и {len(y)}; на каждое "
            f"значение по одному месту на оси", field=f"{where}.x")
    # Сообщение про обрезанные точки собирает вызывающий: обрезаются они
    # обычно во всех сериях разом, и восемь одинаковых строк в ответе вытесняют
    # из него то, ради чего его читают.
    обрезана = len(y) > MAX_POINTS
    if обрезана:
        y, x = y[:MAX_POINTS], (x[:MAX_POINTS] if x is not None else None)
    y = tuple(_number(v, f"{where}.y[{i}]") for i, v in enumerate(y, 1))
    return name, _x_values(x, where), y, обрезана


def _x_values(x, where):
    """`x` серии → числа, подписи (кортеж строк) или None, если его не задали."""
    if x is None:
        return None
    if all(_is_number(v) for v in x):
        return tuple(_number(v, f"{where}.x[{i}]") for i, v in enumerate(x, 1))
    return tuple(_category(v, f"{where}.x[{i}]") for i, v in enumerate(x, 1))


def _x_labels(сырые, kind: str) -> tuple[str, ...]:
    """Подписи делений на весь график — или пусто, если ось числовая.

    У столбчатых ось всегда подписями: столбец отвечает на «сколько у этого», а
    не «сколько при таком-то значении», и числовой x у них — те же подписи,
    только записанные цифрами.
    """
    категории = kind in CATEGORY_KINDS or any(
        x and isinstance(x[0], str) for _, x, _ in сырые if x is not None)
    if not категории:
        return ()
    наборы = [tuple(_as_label(v) for v in x) for _, x, _ in сырые if x is not None]
    if not наборы:
        # Подписей не дали вовсе: деления нумеруются, столбцы стоят по порядку.
        длина = max(len(y) for _, _, y in сырые)
        return tuple(str(i) for i in range(1, длина + 1))
    if len(наборы) != len(сырые) or any(n != наборы[0] for n in наборы[1:]):
        raise ChartError(
            "series: подписи по оси x у серий разные — на одном графике ось "
            "одна, задай всем сериям одинаковый x", field="series")
    подписи = наборы[0]
    for _, _, y in сырые:
        if len(y) != len(подписи):
            raise ChartError(
                f"series: подписей по x {len(подписи)}, а в одной из серий "
                f"{len(y)} значений", field="series")
    return подписи


def _as_label(v) -> str:
    """Значение x подписью деления. Целое число — без хвоста «.0»."""
    return v if isinstance(v, str) else f"{v:g}"


def _pie(raw: dict, notes: list[str]) -> tuple[tuple[str, ...], tuple[float, ...]]:
    """`labels` + `values` круговой: доли целого, поэтому только неотрицательные."""
    values = raw.get("values")
    labels = raw.get("labels")
    if not isinstance(values, list) or not values:
        raise ChartError("values: у pie доли задаются непустым списком чисел",
                         field="values")
    if not isinstance(labels, list) or len(labels) != len(values):
        сколько = len(labels) if isinstance(labels, list) else 0
        raise ChartError(
            f"labels: у pie на каждое значение своя подпись — значений "
            f"{len(values)}, подписей {сколько}", field="labels")
    if len(values) > MAX_SERIES:
        notes.append(f"долей было {len(values)} — нарисованы первые {MAX_SERIES}")
        values, labels = values[:MAX_SERIES], labels[:MAX_SERIES]
    числа = tuple(_number(v, f"values[{i}]") for i, v in enumerate(values, 1))
    if any(v < 0 for v in числа):
        raise ChartError(
            "values: у круговой доли не бывают отрицательными — для чисел со "
            "знаком возьми bar", field="values")
    if sum(числа) <= 0:
        raise ChartError("values: все доли нулевые — круг делить не на что",
                         field="values")
    имена = tuple(_category(v, f"labels[{i}]") for i, v in enumerate(labels, 1))
    return имена, числа


def _hist(raw: dict, notes: list[str]) -> tuple[tuple[float, ...], int]:
    """`values` + `bins` гистограммы: ряд замеров, который раскладывают сами."""
    values = raw.get("values")
    if not isinstance(values, list) or not values:
        raise ChartError(
            "values: у hist замеры задаются непустым списком чисел — "
            "раскладку по столбикам гистограмма считает сама", field="values")
    if len(values) > MAX_POINTS:
        notes.append(f"замеров было {len(values)} — взяты первые {MAX_POINTS}")
        values = values[:MAX_POINTS]
    числа = tuple(_number(v, f"values[{i}]") for i, v in enumerate(values, 1))
    bins = raw.get("bins")
    if bins is None:
        return числа, DEFAULT_BINS
    if isinstance(bins, bool) or not isinstance(bins, int):
        raise ChartError(f"bins: целое число столбиков, а не {bins!r}", field="bins")
    if not 1 <= bins <= MAX_BINS:
        raise ChartError(f"bins: {bins} — вне 1..{MAX_BINS}", field="bins")
    return числа, bins


# ── мелкие проверки ──────────────────────────────────────────────────────────

def _is_number(v) -> bool:
    # `bool` — не число: `True` в данных означает, что серию собрали не из тех
    # значений, а нарисованная единица выглядела бы законным замером.
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _number(v, where: str) -> float:
    if not _is_number(v):
        raise ChartError(f"{where}: {_ru(v)} — не число", field=where)
    число = float(v)
    if not math.isfinite(число):
        raise ChartError(f"{where}: {v!r} — не конечное число", field=where)
    return число


def _category(v, where: str) -> str:
    """Подпись деления. Числа принимаются — их приводит к строке ось, не мы."""
    if isinstance(v, bool) or not isinstance(v, (str, int, float)):
        raise ChartError(f"{where}: подпись — строка или число, а не {_ru(v)}",
                         field=where)
    текст = " ".join(str(v).split())
    return текст[:MAX_LABEL_CHARS] if len(текст) > MAX_LABEL_CHARS else текст


def _text(v, name: str, limit: int, notes: list[str]) -> str:
    if v is None:
        return ""
    if not isinstance(v, str):
        raise ChartError(f"{name}: строка или ничего, а не {_ru(v)}", field=name)
    текст = " ".join(v.split())
    if len(текст) > limit:
        notes.append(f"{name}: подпись длиннее {limit} знаков — обрезана")
        текст = текст[:limit].rstrip()
    return текст


def _flag(v, name: str, *, default: bool) -> bool:
    if v is None:
        return default
    if not isinstance(v, bool):
        raise ChartError(f"{name}: true или false, а не {_ru(v)}", field=name)
    return v


def _one_of(value, allowed, name: str) -> str:
    текст = str(value or "")
    if текст not in allowed:
        raise ChartError(
            f"{name}: {текст!r} — не из списка {', '.join(allowed)}"
            f"{_hint(текст, allowed)}", field=name)
    return текст


def _known_fields(raw: dict, kind: str) -> None:
    """Поля не своего вида — отказ, а не молчание.

    `series` у круговой значит, что данные собраны для другого графика:
    проглотить их и нарисовать пустой круг — худшее из возможного.
    """
    свои = _FIELDS[kind]
    for name, значение in raw.items():
        if name in свои or значение is None:
            # null — это «поля я не задаю»: строгий режим поставщика заставляет
            # называть все поля разом, и отсутствие выражается там только им.
            continue
        чужой = next((k for k, fields in _FIELDS.items() if name in fields), "")
        # Подсказка «похоже на» — только когда поле незнакомо вовсе: у поля,
        # которое мы узнали, но не у того вида, ближайшее по написанию соседнее
        # имя лишь уводит в сторону.
        откуда = f" — это поле у {чужой}" if чужой else _hint(name, свои)
        raise ChartError(
            f"{name}: у {kind} такого поля нет{откуда}. Поля {kind}: "
            f"{', '.join(свои)}", field=name)


def _unknown(raw: dict, allowed, where: str) -> None:
    for name in raw:
        if name not in allowed:
            raise ChartError(
                f"{where}: поля {name!r} у серии нет, есть "
                f"{', '.join(allowed)}{_hint(name, allowed)}", field=where)


def _hint(name, known) -> str:
    """Хвост «(похоже на "…")» или пустая строка."""
    near = difflib.get_close_matches(str(name), sorted(str(k) for k in known),
                                     n=1, cutoff=0.6)
    return f' (похоже на "{near[0]}")' if near else ""


def _ru(v) -> str:
    """Тип значения по-русски: текст читает не тот, кто пишет на Python."""
    слова = {bool: "true/false", int: "число", float: "число", str: "строка",
             list: "список", dict: "объект", type(None): "ничего"}
    return слова.get(type(v), type(v).__name__)


__all__ = ["check", "ChartSpec", "ChartError", "Series", "KINDS", "THEMES",
           "SIZES", "SERIES_KINDS", "CATEGORY_KINDS", "MAX_SERIES",
           "MAX_POINTS", "MAX_BINS", "DEFAULT_BINS", "DEFAULT_SIZE",
           "DEFAULT_THEME"]
