"""
_render — проверенная спецификация → PNG. Здесь и только здесь живёт matplotlib.

**Импорт ленивый, внутри функции.** matplotlib тянет за собой numpy, разбор
шрифтов и свой кэш; `import zuhyo` делает и служба, которой рисовать не нужно
никогда, и разбор спецификации, которому хватает списков чисел. Платить за это
секундой запуска и десятками мегабайт памяти на каждом процессе службы незачем.

**Бэкенд — Agg, и ставится он до `pyplot`.** Иначе matplotlib выбирает бэкенд
сам, по окружению: на машине с DISPLAY он возьмёт оконный, и рисование PNG на
сервере кончится попыткой открыть окно. Порядок здесь обязателен — после
импорта `pyplot` смена бэкенда уже ничего не решает.

**Фигура закрывается всегда** (`finally: plt.close`). `pyplot` держит созданные
фигуры в своём реестре, и не закрытая фигура не собирается сборщиком мусора: на
сотом графике прогона это сотня фигур в памяти. Отказ посреди рисования —
такой же случай, поэтому закрытие стоит в `finally`, а не после `savefig`.

**Глобальные настройки не трогаются** (`plt.rc_context`). Пакет — не хозяин
процесса: рядом может рисовать кто угодно, и оставленный после себя `rcParams`
менял бы чужие картинки.

**Шрифт назван прямо — DejaVu Sans.** Он встроен в matplotlib и покрывает
кириллицу; умолчание же берётся из `rcParams`, которое зависит от системы, и
подписи на чужой машине превратились бы в прямоугольники.

Палитры — те же два слова, что у схем (`light`/`dark`), и родня им по цветам:
графики ложатся в один документ со схемами, и третья гамма посреди отчёта видна
сразу. Цветов ряда ровно восемь — столько же, сколько потолок серий: девятая
серия иначе повторила бы цвет первой, а две кривые одного цвета на одном
графике неразличимы.
"""
from __future__ import annotations

import io

# Плотность точек. 150 dpi — вдвое против экранных 75: картинка не мылится при
# печати и не весит как фотография. Меньшая плотность — запасной ход для
# графика, не влезшего в потолок веса.
DPI = 150
SMALL_DPI = 100

# Потолок веса PNG. Картинка едет в DOCX, а оттуда в PDF, и десяток тяжёлых
# графиков превращает отчёт в файл, который не открывается на телефоне.
MAX_PNG_BYTES = 2 * 1024 * 1024


class _Palette:
    """Цвета одной темы. Роли те же, что у схем: фон, текст, линии, ряд."""

    def __init__(self, *, figure, axes, text, muted, grid, spine, cycle):
        self.figure = figure        # поле картинки целиком
        self.axes = axes            # поле внутри осей
        self.text = text            # заголовок и подписи осей
        self.muted = muted          # цифры делений и легенда
        self.grid = grid            # сетка
        self.spine = spine          # линии осей
        self.cycle = cycle          # цвета серий, по одному на серию


_PALETTES = {
    "light": _Palette(
        figure="#ffffff", axes="#ffffff", text="#0f172a", muted="#334155",
        grid="#e2e8f0", spine="#94a3b8",
        cycle=("#4f46e5", "#0284c7", "#16a34a", "#d97706",
               "#dc2626", "#7c3aed", "#0d9488", "#db2777")),
    "dark": _Palette(
        figure="#0f172a", axes="#1e293b", text="#f1f5f9", muted="#94a3b8",
        grid="#334155", spine="#475569",
        cycle=("#818cf8", "#38bdf8", "#4ade80", "#fbbf24",
               "#f87171", "#c4b5fd", "#2dd4bf", "#f472b6")),
}

# Толщина линий и размер точки. Числа собраны здесь, а не разбросаны по видам
# графика: у соседних видов они обязаны совпадать, иначе линейный и ступенчатый
# графики одних данных выглядят нарисованными разными инструментами.
_LINE_WIDTH = 1.8
_MARKER_LIMIT = 40          # до скольких точек кривая рисуется с кружками
_DOT_SIZE = 26
_BAR_TOTAL = 0.8            # какую долю деления занимает группа столбцов
_AREA_ALPHA = 0.30

# Когда подписи делений разворачиваются наискось: длинных подписей поперёк оси
# помещается три-четыре, и наехавшие друг на друга слова хуже наклонных.
_TILT_COUNT = 8
_TILT_CHARS = 6


def draw(spec, *, dpi: int = DPI) -> bytes:
    """`ChartSpec` → байты PNG. Решений о данных здесь нет — только рисование."""
    import matplotlib
    matplotlib.use("Agg")               # до pyplot: иначе бэкенд уже выбран
    import matplotlib.pyplot as plt

    palette = _PALETTES[spec.theme]
    with plt.rc_context({"font.family": "DejaVu Sans", "font.size": 10,
                         "axes.unicode_minus": False}):
        fig = None
        try:
            fig, ax = plt.subplots(figsize=spec.inches, dpi=dpi)
            fig.patch.set_facecolor(palette.figure)
            ax.set_facecolor(palette.axes)
            _plot(ax, spec, palette)
            _dress(ax, spec, palette)
            buf = io.BytesIO()
            fig.savefig(buf, format="png", dpi=dpi, facecolor=palette.figure,
                        bbox_inches="tight", pad_inches=0.18)
            return buf.getvalue()
        finally:
            # Реестр pyplot держит фигуру и после отказа: без закрытия прогон,
            # рисующий график каждым ходом, растёт в памяти до конца.
            if fig is not None:
                plt.close(fig)


# ── по видам ─────────────────────────────────────────────────────────────────

def _plot(ax, spec, palette) -> None:
    """Ветка на вид графика. Всё, что общее (оси, сетка, легенда), — в `_dress`."""
    if spec.kind == "pie":
        _pie(ax, spec, palette)
    elif spec.kind == "hist":
        ax.hist(list(spec.values), bins=spec.bins, color=palette.cycle[0],
                edgecolor=palette.axes, linewidth=0.6)
    elif spec.kind in ("bar", "barh"):
        _bars(ax, spec, palette)
    else:
        _lines(ax, spec, palette)


def _lines(ax, spec, palette) -> None:
    """Кривые: line, step, area, scatter. Точки рисуются в порядке присланного."""
    for n, series in enumerate(spec.series):
        цвет = palette.cycle[n % len(palette.cycle)]
        x, y = list(series.x), list(series.y)
        if spec.kind == "scatter":
            ax.scatter(x, y, s=_DOT_SIZE, color=цвет, label=series.name,
                       edgecolors="none")
        elif spec.kind == "step":
            # `where="mid"` — ступень посередине между точками: так рисуют
            # значение, которое держалось до следующего замера.
            ax.step(x, y, where="mid", color=цвет, linewidth=_LINE_WIDTH,
                    label=series.name)
        elif spec.kind == "area":
            # Заливка полупрозрачная и не складывается в стопку: сложенные
            # площади отвечают на другой вопрос («сколько всего»), а спрошено
            # было про каждую серию отдельно.
            ax.plot(x, y, color=цвет, linewidth=_LINE_WIDTH, label=series.name)
            ax.fill_between(x, y, color=цвет, alpha=_AREA_ALPHA)
        else:
            маркер = "o" if len(x) <= _MARKER_LIMIT else None
            ax.plot(x, y, color=цвет, linewidth=_LINE_WIDTH, marker=маркер,
                    markersize=4, label=series.name)


def _bars(ax, spec, palette) -> None:
    """Столбцы. Несколько серий — группами у одного деления, а не стопкой.

    Стопка складывает значения, то есть отвечает на вопрос «сколько всего», —
    а спрошено «сколько у каждого». Выбирать между ними полем спецификации не
    даём: два вида столбчатого графика назывались бы одним словом, и половина
    читателей отчёта поняла бы картинку неправильно.
    """
    n_series = len(spec.series)
    ширина = _BAR_TOTAL / n_series
    for n, series in enumerate(spec.series):
        цвет = palette.cycle[n % len(palette.cycle)]
        сдвиг = (n - (n_series - 1) / 2) * ширина
        места = [x + сдвиг for x in series.x]
        if spec.kind == "barh":
            ax.barh(места, list(series.y), height=ширина, color=цвет,
                    label=series.name)
        else:
            ax.bar(места, list(series.y), width=ширина, color=цвет,
                   label=series.name)


def _pie(ax, spec, palette) -> None:
    """Круговая: доли подписаны процентами у секторов, ось выключена."""
    цвета = [palette.cycle[i % len(palette.cycle)] for i in range(len(spec.values))]
    подписи = None if spec.legend else list(spec.labels)
    куски, тексты, проценты = ax.pie(
        list(spec.values), labels=подписи, colors=цвета, startangle=90,
        autopct="%1.1f%%", pctdistance=0.72,
        wedgeprops={"edgecolor": palette.figure, "linewidth": 1.0},
        textprops={"color": palette.text})
    for текст in проценты:
        # Процент лежит на заливке сектора, а не на фоне картинки: цвет фона
        # ему не годится ни в светлой теме, ни в тёмной.
        текст.set_color("#ffffff")
        текст.set_fontsize(9)
    if spec.legend:
        for кусок, имя in zip(куски, spec.labels):
            кусок.set_label(имя)
    ax.set_aspect("equal")


# ── общее оформление ─────────────────────────────────────────────────────────

def _dress(ax, spec, palette) -> None:
    """Заголовок, подписи осей, деления, сетка, легенда — одинаково для всех."""
    if spec.title:
        ax.set_title(spec.title, color=palette.text, fontsize=12, pad=10)
    if spec.kind == "pie":
        ax.set_axis_off()
        _legend(ax, spec, palette)
        return

    ax.set_xlabel(spec.x_label, color=palette.text)
    ax.set_ylabel(spec.y_label, color=palette.text)
    ax.tick_params(colors=palette.muted, labelsize=9)
    for место, видно in (("top", False), ("right", False),
                         ("left", True), ("bottom", True)):
        ax.spines[место].set_visible(видно)
        if видно:
            ax.spines[место].set_color(palette.spine)

    if spec.x_labels:
        _ticks(ax, spec, palette)
    if spec.grid:
        # Сетка вдоль той оси, по которой читают значение: у столбцов это
        # высота, у лежачих — длина, у кривых обе. Лишняя сетка поперёк
        # столбцов только рябит.
        ось = {"bar": "y", "barh": "x", "hist": "y"}.get(spec.kind, "both")
        ax.grid(True, axis=ось, color=palette.grid, linewidth=0.7)
        ax.set_axisbelow(True)          # сетка под данными, а не поверх них
    _legend(ax, spec, palette)


def _ticks(ax, spec, palette) -> None:
    """Подписи делений вместо чисел — там, где ось категорийная."""
    места = list(range(len(spec.x_labels)))
    подписи = list(spec.x_labels)
    if spec.kind == "barh":
        ax.set_yticks(места)
        ax.set_yticklabels(подписи, color=palette.muted)
        # Сверху вниз, а не снизу вверх: лежачие столбцы читают списком, и
        # порядок на картинке обязан совпасть с порядком в данных.
        ax.invert_yaxis()
        return
    ax.set_xticks(места)
    длинные = max((len(t) for t in подписи), default=0) > _TILT_CHARS
    наискось = len(подписи) > _TILT_COUNT or длинные
    ax.set_xticklabels(подписи, color=palette.muted,
                       rotation=30 if наискось else 0,
                       ha="right" if наискось else "center")


def _legend(ax, spec, palette) -> None:
    # Пустая легенда не рисуется вовсе: у гистограммы называть нечего (ряд
    # один), и matplotlib на просьбу построить её отвечает предупреждением в
    # поток ошибок — там, где его никто не читает.
    подписанное, _ = ax.get_legend_handles_labels()
    if not spec.legend or not подписанное:
        return
    # У круговой легенда выносится вбок: круг занимает поле целиком, и
    # положенная поверх него легенда закрывает сектор, о котором и рассказывает.
    сбоку = ({"loc": "center left", "bbox_to_anchor": (0.98, 0.5)}
             if spec.kind == "pie" else {})
    легенда = ax.legend(facecolor=palette.axes, edgecolor=palette.spine,
                        labelcolor=palette.muted, fontsize=9, framealpha=1.0,
                        **сбоку)
    легенда.get_frame().set_linewidth(0.6)


__all__ = ["draw", "DPI", "SMALL_DPI", "MAX_PNG_BYTES"]
