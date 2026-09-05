/**
 * chart — арифметика графиков админки: ряд, масштаб, координаты столбцов.
 *
 * Без React и без единого элемента разметки, и это не аккуратность ради
 * аккуратности: масштаб и заполнение пустых дней — единственное место, где
 * график может соврать, и проверяются они тестом, которому не нужен ни
 * отрисованный компонент, ни браузер (`chart.test.ts`).
 *
 * **Почему свой SVG, а не библиотека.** Цвета здесь — переменные темы
 * (`var(--accent)`), потому что тем четыре и у каждой светлый и тёмный вид;
 * готовые библиотеки берут цвет строкой в JS, то есть требуют читать
 * `getComputedStyle` и перерисовывать график на каждую смену темы. Плюс вес:
 * три простых графика не стоят четверти мегабайта зависимости, а всё, что от
 * библиотеки было бы нужно, — вот эти сорок строк арифметики.
 */

/** Точка ряда по дням: день в виде `ГГГГ-ММ-ДД` и число. */
export type DayPoint = { day: string; value: number }

/** Столбец, готовый к отрисовке: координаты в единицах области построения. */
export type Column = DayPoint & {
  x: number
  y: number
  width: number
  height: number
}

/** Разметка вертикальной оси: сколько единиц наверху и где рисовать линии. */
export type Scale = { max: number; ticks: number[] }

/**
 * Круглый потолок оси. Ось до 137 — это ось, у которой подписи читаются как
 * случайные числа; до 150 — та же картинка с понятными делениями.
 *
 * Нулевой и отрицательный максимум дают потолок 1, а не 0: деление на ноль
 * превратило бы все высоты в `NaN`, и график исчез бы вместо того, чтобы стать
 * плоским.
 */
export function niceMax(value: number): number {
  if (!Number.isFinite(value) || value <= 0) return 1
  const порядок = 10 ** Math.floor(Math.log10(value))
  // Только целые доли: потолок 2,5 дал бы середину оси 1,25, а её подпись —
  // округлённую единицу, то есть неправду прямо на делении.
  const шаг = [1, 2, 5, 10].find((k) => value <= k * порядок) ?? 10
  return шаг * порядок
}

/**
 * Потолок оси и деления к нему: низ, середина, верх.
 *
 * Середина пропускается, когда она не целая: ось от 0 до 1 с делением 0,5
 * подписывалась бы как «0, 1, 1» — три деления, из которых два врут.
 */
export function scaleOf(values: readonly number[]): Scale {
  const max = niceMax(values.reduce((большее, v) => Math.max(большее, v), 0))
  return { max, ticks: Number.isInteger(max / 2) ? [0, max / 2, max] : [0, max] }
}

/**
 * Ряд подряд идущих дней: то, что пришло, разложенное по оси от `since` на
 * `days` дней вперёд, а пропущенные дни — нулями.
 *
 * Пропуск в ряду — это не «нет данных», это неправда: график соединит пятницу
 * с понедельником и покажет ровную линию там, где были выходные. Служба уже
 * отдаёт ряд плотным, но проверять это на сайте всё равно надо: сайт переживёт
 * службу, у которой ряд однажды станет разреженным, а молчаливо кривой график
 * — нет.
 */
export function fillDays(since: string, days: number, points: readonly DayPoint[]): DayPoint[] {
  const было = new Map(points.map((т) => [т.day, т.value]))
  const начало = new Date(`${since.slice(0, 10)}T00:00:00Z`)
  if (Number.isNaN(начало.getTime()) || days <= 0) return []
  return Array.from({ length: days }, (_, i) => {
    const день = new Date(начало)
    день.setUTCDate(начало.getUTCDate() + i)
    const ключ = день.toISOString().slice(0, 10)
    return { day: ключ, value: было.get(ключ) ?? 0 }
  })
}

/**
 * Столбцы в координатах области построения (начало отсчёта — левый верхний
 * угол, как в SVG). Ширина столбца — доля полосы за вычетом зазора: соседние
 * заливки без просвета читаются как одна.
 *
 * Ненулевое значение никогда не даёт высоту меньше `МИНИМУМ`: столбец в
 * полпикселя визуально равен нулю, а «сегодня ноль» и «сегодня чуть-чуть» —
 * разные новости.
 */
export const ЗАЗОР = 2
export const МИНИМУМ = 2

export function columns(
  points: readonly DayPoint[],
  width: number,
  height: number,
  max: number,
): Column[] {
  if (points.length === 0 || width <= 0 || height <= 0) return []
  const полоса = width / points.length
  const ширина = Math.max(1, полоса - ЗАЗОР)
  const потолок = max > 0 ? max : 1
  return points.map((точка, i) => {
    const доля = Math.max(0, точка.value) / потолок
    const высота = точка.value > 0 ? Math.max(МИНИМУМ, доля * height) : 0
    return {
      ...точка,
      x: i * полоса + (полоса - ширина) / 2,
      y: height - высота,
      width: ширина,
      height: высота,
    }
  })
}

/**
 * Какие столбцы подписать датой. Все подряд не помещаются уже на тридцати днях,
 * поэтому берётся первый, последний и несколько между ними — ровным шагом,
 * чтобы подписи не толпились.
 */
export function labelIndexes(count: number, сколько = 6): number[] {
  if (count <= 0) return []
  if (count <= сколько) return Array.from({ length: count }, (_, i) => i)
  const шаг = (count - 1) / (сколько - 1)
  const набор = new Set<number>()
  for (let i = 0; i < сколько; i += 1) набор.add(Math.round(i * шаг))
  return [...набор].sort((а, б) => а - б)
}

/** День оси коротко: «4 сен». Год не пишется — ось короче трёх месяцев. */
export function shortDay(day: string): string {
  const момент = new Date(`${day}T00:00:00Z`)
  if (Number.isNaN(момент.getTime())) return day
  return момент.toLocaleDateString('ru-RU', {
    day: 'numeric',
    month: 'short',
    timeZone: 'UTC',
  })
}

/** Сумма ряда — число для плитки над графиком. */
export function sumOf(points: readonly DayPoint[]): number {
  return points.reduce((сумма, т) => сумма + (Number.isFinite(т.value) ? т.value : 0), 0)
}
