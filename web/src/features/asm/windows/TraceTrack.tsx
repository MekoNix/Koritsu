/**
 * TraceTrack — дорожка ползунка трассы: заливка пройденного, круглый бегунок
 * с номером шага и метки.
 *
 * Своя, а не `<input type=range>`: на дорожке стоят метки — точки останова,
 * вызовы DOS или API, выход, свёрнутая середина, — и у нативного ползунка их некуда
 * положить так, чтобы они совпадали с бегунком во всех браузерах.
 *
 * Метки прореживаются до пикселя: на трассе в сто тысяч шагов вызовов `int 21h`
 * бывают тысячи, а различимых мест на дорожке — сотни.
 *
 * Клавиатура — как у `role=slider`: стрелки на шаг, PageUp/PageDown на десять,
 * Home/End к краям. Мышь и палец в свёрнутую середину не ставят — бегунок
 * соскакивает к ближнему краю; клавиши её перескакивают (это делает `goto`).
 */
import { useLayoutEffect, useMemo, useRef, useState, type KeyboardEvent, type PointerEvent } from 'react'

import { cn } from '@/lib/cn'

import { fmtInt } from './format'

/** Шагов за PageUp/PageDown. */
const PAGE = 10

interface TraceTrackProps {
  value: number
  /** Последний номер шага. */
  total: number
  disabled: boolean
  /** Свёрнутая середина `[from, to)`. */
  gap: readonly [number, number] | null
  /** Шаги, стоящие перед строкой с точкой останова. */
  breakpoints: readonly number[]
  /** Шаги с вызовом DOS. */
  dosCalls: readonly number[]
  /** Шаги, выполнившие вызов API (MinGW x64), с направлением данных — цвет засечки. */
  apiCalls?: readonly { i: number; io: 'in' | 'out' | 'exit' | 'other' }[]
  /** Шаг выхода программы. */
  exit: number | null
  label: string
  valueText: string
  gapText: string | null
  onChange(step: number): void
}

/** Позиции меток в пикселях дорожки, не больше одной на пиксель. */
function thin(steps: readonly number[], span: number, width: number): number[] {
  if (width <= 0) return []
  const seen = new Set<number>()
  for (const i of steps) seen.add(Math.round((i / span) * width))
  return [...seen]
}

export default function TraceTrack({ value, total, disabled, gap, breakpoints, dosCalls, apiCalls, exit, label, valueText, gapText, onChange }: TraceTrackProps) {
  const rail = useRef<HTMLDivElement>(null)
  const [width, setWidth] = useState(0)
  const [drag, setDrag] = useState(false)
  /** Последний шаг, отправленный перетаскиванием: одно и то же место не шлётся дважды. */
  const sent = useRef<number | null>(null)

  useLayoutEffect(() => {
    const el = rail.current
    if (!el) return
    const update = () => setWidth(el.clientWidth)
    update()
    const ro = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(update) : null
    ro?.observe(el)
    return () => ro?.disconnect()
  }, [])

  const span = Math.max(1, total)
  const pct = (Math.max(0, Math.min(total, value)) / span) * 100
  const bpPx = useMemo(() => thin(breakpoints, span, width), [breakpoints, span, width])
  const dosPx = useMemo(() => thin(dosCalls, span, width), [dosCalls, span, width])
  // Засечки API прореживаются так же; на одном пикселе ввод, вывод и выход важнее прочих вызовов.
  const apiPx = useMemo(() => {
    if (!apiCalls?.length || width <= 0) return []
    const seen = new Map<number, string>()
    for (const c of apiCalls) {
      const px = Math.round((c.i / span) * width)
      const had = seen.get(px)
      if (!had || had === 'other') seen.set(px, c.io)
    }
    return [...seen.entries()]
  }, [apiCalls, span, width])
  const exitPx = exit != null && width > 0 ? Math.round((exit / span) * width) : null

  const fromPointer = (clientX: number) => {
    const el = rail.current
    if (!el) return
    const r = el.getBoundingClientRect()
    let v = Math.round(((clientX - r.left) / Math.max(1, r.width)) * total)
    v = Math.max(0, Math.min(total, v))
    if (gap && v >= gap[0] && v < gap[1]) v = v - gap[0] < gap[1] - v ? gap[0] - 1 : gap[1]
    if (v === sent.current) return
    sent.current = v
    onChange(v)
  }

  const onPointerDown = (e: PointerEvent<HTMLDivElement>) => {
    if (disabled || e.button !== 0) return
    e.preventDefault()
    e.currentTarget.focus({ preventScroll: true })
    e.currentTarget.setPointerCapture(e.pointerId)
    sent.current = value
    setDrag(true)
    fromPointer(e.clientX)
  }

  const onPointerMove = (e: PointerEvent<HTMLDivElement>) => {
    if (drag) fromPointer(e.clientX)
  }

  const endDrag = () => {
    if (!drag) return
    setDrag(false)
    sent.current = null
  }

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (disabled || e.altKey || e.ctrlKey || e.metaKey) return
    let v: number
    switch (e.key) {
      case 'ArrowRight':
      case 'ArrowUp':
        v = value + 1
        break
      case 'ArrowLeft':
      case 'ArrowDown':
        v = value - 1
        break
      case 'PageUp':
        v = value + PAGE
        break
      case 'PageDown':
        v = value - PAGE
        break
      case 'Home':
        v = 0
        break
      case 'End':
        v = total
        break
      default:
        return
    }
    e.preventDefault()
    onChange(Math.max(0, Math.min(total, v)))
  }

  return (
    <div
      className={cn('trk', drag && 'is-drag', disabled && 'is-off')}
      role="slider"
      tabIndex={disabled ? -1 : 0}
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={total}
      aria-valuenow={value}
      aria-valuetext={valueText}
      aria-disabled={disabled || undefined}
      title={gapText ?? undefined}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={endDrag}
      onPointerCancel={endDrag}
      onLostPointerCapture={endDrag}
      onKeyDown={onKeyDown}
    >
      <div className="trk-rail" ref={rail}>
        <span className="trk-bar" aria-hidden="true" />
        <span className="trk-fill" aria-hidden="true" style={{ width: `${pct}%` }} />
        {gap && total > 0 && (
          <span
            className="trk-gap"
            aria-hidden="true"
            style={{
              left: `${(gap[0] / span) * 100}%`,
              width: `${Math.max(0.5, ((gap[1] - gap[0]) / span) * 100)}%`,
            }}
          />
        )}
        {dosPx.map((px) => (
          <span key={`d${px}`} className="trk-mk is-dos" aria-hidden="true" style={{ left: px }} />
        ))}
        {apiPx.map(([px, io]) => (
          <span key={`a${px}`} className={`trk-mk is-api io-${io}`} aria-hidden="true" style={{ left: px }} />
        ))}
        {exitPx != null && <span className="trk-mk is-exit" aria-hidden="true" style={{ left: exitPx }} />}
        {bpPx.map((px) => (
          <span key={`b${px}`} className="trk-mk is-bp" aria-hidden="true" style={{ left: px }} />
        ))}
        <span className="trk-thumb" aria-hidden="true" style={{ left: `${pct}%` }}>
          <span className="trk-bubble">{fmtInt(value)}</span>
        </span>
      </div>
    </div>
  )
}
