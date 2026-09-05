/**
 * Chart — три графика «Обзора» инлайн-SVG, без единой зависимости.
 *
 * **Почему свой SVG.** Цвет здесь — переменная темы (`var(--chart-1)`), а тем
 * четыре и у каждой светлый и тёмный вид: `fill="var(--chart-1)"`
 * перекрашивается сменой атрибута на `<html>` сам, тогда как библиотека графиков
 * берёт цвет строкой в JS и потребовала бы читать `getComputedStyle` и
 * перерисовывать всё на каждое переключение. Плюс вес: три простых графика не
 * стоят зависимости размером с сам сайт, а вся арифметика — сорок строк в
 * `chart.ts`, где она и проверяется тестом.
 *
 * **У графиков свои переменные темы** (`--chart-1…4`, `--chart-bad`,
 * `--chart-grid`), а не `--accent` и `--err`. Смысловые
 * цвета интерфейса выбраны по другому правилу: акцент обязан работать заливкой
 * кнопки и текстом ссылки, то есть держать контраст 4.5:1 к тексту, а заливке
 * графика нужно ровно 3:1 к поверхности и различимость с соседями при
 * дальтонизме. Одна пара переменных на две задачи означала бы, что каждый новый
 * ряд подбирается «на глаз» из того, что осталось. Палитры подобраны по
 * правилам skill `dataviz` и проверяются `palette.test.ts` во всех восьми
 * сочетаниях тема × режим.
 *
 * **Читаемость в обе стороны.** Столбцы одного ряда — один цвет (ряд
 * единственный, и цвет здесь не обозначает ничего, кроме «это данные»); там,
 * где рядов два (задания: всего и упавшие), к цвету добавлены и подпись в
 * легенде, и число у столбца — цвет не остаётся единственным различием.
 *
 * **Размер.** `viewBox` с растяжением по ширине, а не измерение контейнера:
 * подсказка ставится в процентах от той же системы координат, поэтому масштаб
 * ей не мешает и `ResizeObserver` не нужен.
 *
 * Ниже каждого графика — та же таблица для скринридера (`sr-only`): график,
 * который нельзя прочитать голосом, — это картинка, а не данные.
 */
import { useId, useState } from 'react'

import { cn } from '@/lib/cn'

import { columns, labelIndexes, scaleOf, shortDay, type DayPoint } from './chart'
import type { StatsKind } from './types'

// Система координат графика по дням. Числа в единицах `viewBox`.
const Ш = 720
const В = 180
const ПОЛЯ = { left: 48, right: 8, top: 12, bottom: 24 }
const ОБЛАСТЬ_Ш = Ш - ПОЛЯ.left - ПОЛЯ.right
const ОБЛАСТЬ_В = В - ПОЛЯ.top - ПОЛЯ.bottom

/**
 * Столбцы по дням: один ряд, ось слева, подписи дат снизу, подсказка по
 * наведению.
 */
export function ColumnChart({
  points,
  label,
  color = 'var(--chart-1)',
  valueLabel,
  dayLabel,
  format = (n: number) => String(n),
  formatAxis = (n: number) => String(n),
}: {
  points: readonly DayPoint[]
  /** Что это за график — уходит в `aria-label` и в заголовок таблицы. */
  label: string
  color?: string
  /** Как называется величина: «единиц», «регистраций». Из переводов. */
  valueLabel: string
  /** Заголовок столбца дат в таблице для скринридера. Из переводов. */
  dayLabel: string
  /** Точное число для подсказки. */
  format?: (value: number) => string
  /** Короткое число для оси — там, где длинное не поместится. */
  formatAxis?: (value: number) => string
}) {
  const обрезка = useId().replace(/:/g, '')
  const [под, навести] = useState<number | null>(null)
  const { max, ticks } = scaleOf(points.map((т) => т.value))
  const столбцы = columns(points, ОБЛАСТЬ_Ш, ОБЛАСТЬ_В, max)
  const подписи = new Set(labelIndexes(points.length))
  const выбран = под !== null ? столбцы[под] : undefined

  return (
    <div className="relative">
      <svg
        viewBox={`0 0 ${Ш} ${В}`}
        className="block h-auto w-full"
        role="img"
        aria-label={label}
        onMouseLeave={() => навести(null)}
      >
        <defs>
          <clipPath id={обрезка}>
            <rect x={0} y={0} width={ОБЛАСТЬ_Ш} height={ОБЛАСТЬ_В} />
          </clipPath>
        </defs>

        {/* Сетка и подписи оси — приглушённые: это опора, а не данные. */}
        <g transform={`translate(${ПОЛЯ.left} ${ПОЛЯ.top})`}>
          {ticks.map((деление) => {
            const y = ОБЛАСТЬ_В - (деление / (max || 1)) * ОБЛАСТЬ_В
            return (
              <g key={деление}>
                <line
                  x1={0}
                  x2={ОБЛАСТЬ_Ш}
                  y1={y}
                  y2={y}
                  stroke="var(--chart-grid)"
                  strokeWidth={1}
                />
                <text
                  x={-8}
                  y={y + 4}
                  textAnchor="end"
                  fontSize={11}
                  fill="var(--muted)"
                  className="font-mono"
                >
                  {formatAxis(деление)}
                </text>
              </g>
            )
          })}

          <g clipPath={`url(#${обрезка})`}>
            {столбцы.map((столбец, i) => (
              <rect
                key={столбец.day}
                x={столбец.x}
                y={столбец.y}
                width={столбец.width}
                height={столбец.height + 4}
                rx={Math.min(3, столбец.width / 2)}
                fill={color}
                opacity={под === null || под === i ? 1 : 0.55}
              />
            ))}
          </g>

          {/* Мишени наведения шире столбцов: попасть в полосу в четыре пикселя
              мышью нельзя, а в полосу шириной с день — можно. */}
          {столбцы.map((столбец, i) => (
            <rect
              key={`hit-${столбец.day}`}
              x={(i * ОБЛАСТЬ_Ш) / столбцы.length}
              y={0}
              width={ОБЛАСТЬ_Ш / столбцы.length}
              height={ОБЛАСТЬ_В}
              fill="transparent"
              onMouseEnter={() => навести(i)}
            />
          ))}

          {столбцы.map((столбец, i) =>
            подписи.has(i) ? (
              <text
                key={`x-${столбец.day}`}
                x={столбец.x + столбец.width / 2}
                y={ОБЛАСТЬ_В + 16}
                textAnchor="middle"
                fontSize={11}
                fill="var(--muted)"
              >
                {shortDay(столбец.day)}
              </text>
            ) : null,
          )}
        </g>
      </svg>

      {выбран && (
        <div
          className="pointer-events-none absolute z-[1] -translate-x-1/2 -translate-y-full whitespace-nowrap rounded-sm border border-line bg-elevated px-2 py-1 text-xs shadow-2"
          style={{
            left: `${((ПОЛЯ.left + выбран.x + выбран.width / 2) / Ш) * 100}%`,
            top: `${((ПОЛЯ.top + выбран.y - 6) / В) * 100}%`,
          }}
        >
          <span className="text-muted">{shortDay(выбран.day)}</span>{' '}
          <span className="font-mono font-semibold text-ink-strong">{format(выбран.value)}</span>{' '}
          <span className="text-muted">{valueLabel}</span>
        </div>
      )}

      <ScreenReaderTable
        caption={label}
        headers={[dayLabel, valueLabel]}
        rows={points.map((т) => [shortDay(т.day), format(т.value)])}
      />
    </div>
  )
}

/**
 * Горизонтальные столбцы по видам заданий: длина — всего за период, красная
 * часть — упавшие. Горизонтальные, потому что подпись здесь — слово
 * (`kadai_rework`), а не дата: под вертикальным столбцом оно легло бы боком.
 */
export function KindBars({
  rows,
  label,
  labels,
}: {
  rows: readonly StatsKind[]
  label: string
  /** Подписи легенды, подсказки и таблицы — тексты живут в переводах, не здесь. */
  labels: { ok: string; failed: string; total: string; kind: string }
}) {
  const [под, навести] = useState<number | null>(null)
  const ШАГ = 26
  const ИМЯ = 132
  const ЧИСЛО = 52
  const высота = Math.max(1, rows.length) * ШАГ + 6
  const дорожка = Ш - ИМЯ - ЧИСЛО
  const потолок = rows.reduce((б, с) => Math.max(б, с.count), 0) || 1

  return (
    <div className="flex flex-col gap-s2">
      <Legend
        items={[
          { color: 'var(--chart-1)', text: labels.ok },
          { color: 'var(--chart-bad)', text: labels.failed },
        ]}
      />
      <div className="relative">
        <svg
          viewBox={`0 0 ${Ш} ${высота}`}
          className="block h-auto w-full"
          role="img"
          aria-label={label}
          onMouseLeave={() => навести(null)}
        >
          {rows.map((строка, i) => {
            const y = i * ШАГ + 6
            const всего = Math.round((строка.count / потолок) * дорожка)
            const упало =
              строка.failed > 0 ? Math.max(4, Math.round((строка.failed / потолок) * дорожка)) : 0
            const целых = Math.max(0, всего - упало - (упало > 0 ? 2 : 0))
            return (
              <g key={строка.kind} opacity={под === null || под === i ? 1 : 0.55}>
                <text x={0} y={y + 11} fontSize={12} fill="var(--ink)" className="font-mono">
                  {строка.kind}
                </text>
                <rect x={ИМЯ} y={y} width={целых} height={14} rx={3} fill="var(--chart-1)" />
                {упало > 0 && (
                  <rect
                    x={ИМЯ + целых + 2}
                    y={y}
                    width={упало}
                    height={14}
                    rx={3}
                    fill="var(--chart-bad)"
                  />
                )}
                <text
                  x={Ш}
                  y={y + 11}
                  textAnchor="end"
                  fontSize={12}
                  fill="var(--ink-strong)"
                  className="font-mono"
                >
                  {строка.count}
                </text>
                <rect
                  x={0}
                  y={y - 3}
                  width={Ш}
                  height={ШАГ - 4}
                  fill="transparent"
                  onMouseEnter={() => навести(i)}
                />
              </g>
            )
          })}
        </svg>

        {под !== null && rows[под] && (
          <div
            className="pointer-events-none absolute right-0 z-[1] -translate-y-full whitespace-nowrap rounded-sm border border-line bg-elevated px-2 py-1 text-xs shadow-2"
            style={{ top: `${((под * ШАГ + 4) / высота) * 100}%` }}
          >
            <span className="font-mono text-ink-strong">{rows[под].kind}</span>{' '}
            <span className="text-muted">
              {labels.total}: {rows[под].count} · {labels.failed}: {rows[под].failed}
            </span>
          </div>
        )}

        <ScreenReaderTable
          caption={label}
          headers={[labels.kind, labels.total, labels.failed]}
          rows={rows.map((с) => [с.kind, String(с.count), String(с.failed)])}
        />
      </div>
    </div>
  )
}

/** Легенда: цветная метка плюс слово. Цвет никогда не единственное различие. */
export function Legend({ items }: { items: readonly { color: string; text: string }[] }) {
  return (
    <ul className="flex flex-wrap items-center gap-s3 text-xs text-muted">
      {items.map((пункт) => (
        <li key={пункт.text} className="flex items-center gap-1.5">
          <span
            aria-hidden="true"
            className="inline-block h-2.5 w-2.5 rounded-[2px]"
            style={{ background: пункт.color }}
          />
          {пункт.text}
        </li>
      ))}
    </ul>
  )
}

/** Те же данные таблицей — только для скринридера. */
function ScreenReaderTable({
  caption,
  headers,
  rows,
}: {
  caption: string
  headers: readonly string[]
  rows: readonly string[][]
}) {
  return (
    <table className="sr-only">
      <caption>{caption}</caption>
      <thead>
        <tr>
          {headers.map((имя) => (
            <th key={имя} scope="col">
              {имя}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((строка) => (
          <tr key={строка[0]}>
            {строка.map((клетка, i) => (
              <td key={`${строка[0]}-${i}`}>{клетка}</td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  )
}

/** Плитка: одно число крупно, подпись под ним, пояснение мелким. */
export function StatTile({
  value,
  label,
  hint,
  className,
}: {
  value: string
  label: string
  hint?: string
  className?: string
}) {
  return (
    <div className={cn('rounded-md border border-line bg-surface p-s3 shadow-1', className)}>
      <div className="font-display text-2xl font-bold leading-none text-ink-strong">{value}</div>
      <div className="mt-1.5 text-xs uppercase tracking-wide text-muted">{label}</div>
      {hint && <div className="mt-0.5 text-xs text-muted">{hint}</div>}
    </div>
  )
}
