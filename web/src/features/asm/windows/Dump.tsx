/**
 * Dump — память сегмента по 16 байт в строке: hex (или dec) и ASCII.
 *
 * Адрес пишется так же, как в отладчике: `DS:0000`, `DS:SI`, `0780:0005`, имя
 * переменной или `arr[2]`. Регистры в адресе берутся с текущего шага, поэтому
 * `DS:SI` едет за SI сам.
 *
 * Прокручивается весь сегмент (64 КБ), рисуется только видимое. Байты данных
 * подчёркнуты цветом своей переменной из `.map`; SI и DI обведены, SP — пунктиром,
 * DX (адрес строки для `int 21h / 09h`) — точками; записанное этим шагом
 * подсвечено.
 *
 * Байт, которого нет ни в одном дампе прогона и который трасса не записывала,
 * неизвестен — и показывается как `··`, а не нулём. Если на экране такие есть,
 * окно само дочитывает память на этом шаге (`memory()`), когда человек
 * перестал листать.
 */
import { useEffect, useMemo, useRef, useState, type CSSProperties, type KeyboardEvent, type ReactNode } from 'react'

import { useAsm } from '@/features/asm/store'
import { isSegmentedLoad, type AsmWindowProps } from '@/features/asm/types'
import { useT } from '@/i18n'
import { cn } from '@/lib/cn'

import {
  ROW,
  asciiOf,
  cellAnchor,
  dataSymbols,
  fmtAddr,
  hasTrace,
  hex,
  isMenuKey,
  linear,
  menuPointOf,
  parseAddress,
  parseHex,
  reg,
  sameAnchor,
  symbolAt,
  useAnchorMenu,
  useMemView,
  useRowWindow,
  veilText,
  type Addr,
} from './format'

/** Строк в сегменте: 64 КБ по 16 байт. */
const ROWS = 0x1000
/** Цвета подчёркивания переменных по кругу — из токенов темы. Переменные свои у каждой программы, поэтому цвет задаётся на месте, а не классом. */
const VAR_COLORS = ['var(--info)', 'var(--ok)', 'var(--code-num)', 'var(--agent)', 'var(--warn)']
/** Сколько ждать после прокрутки или шага, прежде чем дочитывать память. */
const FETCH_DELAY_MS = 600

export default function Dump({ active }: AsmWindowProps) {
  const t = useT()
  const asm = useAsm()
  const { run, step, stepIndex, view, selection, memory } = asm
  const menu = useAnchorMenu()
  const { mem, scan } = useMemView(active)
  const trace = hasTrace(run)
  const st = trace ? step : undefined
  const symbols = useMemo(() => dataSymbols(run), [run])
  const dec = view.radix === 'dec'

  const [text, setText] = useState('DS:0000')
  const parsed = parseAddress(text, st, run, symbols)
  const lastGood = useRef<Addr>({ seg: 0, off: 0 })
  if (parsed) lastGood.current = parsed
  const seg = (parsed ?? lastGood.current).seg

  const win = useRowWindow(ROWS, { overscan: 4 })
  const { reveal } = win
  const targetRow = parsed ? parsed.off >> 4 : -1
  const targetSeg = parsed ? parsed.seg : -1
  useEffect(() => {
    if (targetRow >= 0) reveal(targetRow, false)
  }, [targetRow, targetSeg, reveal])

  // Ячейку выбрали снаружи («Показать в дампе», «Перейти к адресу») — перейти к ней.
  // Свой же щелчок по ячейке адрес не переписывает: иначе `DS:SI` превращался бы
  // в число и переставал следить за SI.
  const ownPick = useRef(false)
  useEffect(() => {
    if (selection?.kind !== 'cell') return
    if (ownPick.current) {
      ownPick.current = false
      return
    }
    setText(`${selection.seg}:${selection.off}`)
  }, [selection])

  const load = run?.load
  const ds = reg(st, 'ds') ?? parseHex(isSegmentedLoad(load) ? load.ds : undefined)
  const ptr = (s: 'ds' | 'es' | 'ss', o: 'si' | 'di' | 'sp' | 'dx') => {
    const sv = reg(st, s)
    const ov = reg(st, o)
    return sv == null || ov == null ? -1 : linear({ seg: sv, off: ov })
  }
  const dsSi = ptr('ds', 'si')
  const esDi = ptr('es', 'di')
  const ssSp = ptr('ss', 'sp')
  const dsDx = ptr('ds', 'dx')

  // Первая строка на экране с неизвестным байтом — её и дочитываем.
  const visibleRows = Math.ceil(win.height / ROW)
  let unknownRow = -1
  if (trace) {
    outer: for (let r = win.visibleFirst; r < Math.min(ROWS, win.visibleFirst + visibleRows + 1); r++) {
      for (let i = 0; i < 16; i++) {
        if (mem.get(linear({ seg, off: r * 16 + i })) == null) {
          unknownRow = r
          break outer
        }
      }
    }
  }

  const [fetchState, setFetchState] = useState<'idle' | 'loading' | 'error'>('idle')
  const requested = useRef(new Set<string>())
  const runNo = run?.run_no ?? -1
  useEffect(() => {
    if (!active || !trace || !scan || unknownRow < 0) return
    const key = `${runNo}:${stepIndex}:${seg}:${unknownRow}`
    if (requested.current.has(key)) return
    const timer = window.setTimeout(() => {
      requested.current.add(key)
      setFetchState('loading')
      const len = Math.min(0x10000 - unknownRow * 16, Math.max(256, (visibleRows + 2) * 16))
      memory(stepIndex, [{ seg: hex(seg), off: hex(unknownRow * 16), len }]).then(
        (dumps) => {
          scan.extraDumps.push(...dumps)
          setFetchState('idle')
        },
        () => setFetchState('error'),
      )
    }, FETCH_DELAY_MS)
    return () => window.clearTimeout(timer)
  }, [active, trace, scan, unknownRow, runNo, stepIndex, seg, visibleRows, memory])

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (!isMenuKey(e) || selection?.kind !== 'cell') return
    const el = e.currentTarget.querySelector(`[data-cell="${selection.seg}:${selection.off}"]`)
    if (!el) return
    e.preventDefault()
    e.stopPropagation()
    menu.open(menuPointOf(el), selection)
  }

  // Подписи переменных, попавших на экран, — для легенды.
  const legend = new Map<string, string>()
  const rows: ReactNode[] = []
  for (let r = win.first; r < win.last; r++) {
    const off = r * 16
    const cells: ReactNode[] = []
    let ascii = ''
    for (let i = 0; i < 16; i++) {
      const a: Addr = { seg, off: off + i }
      const lin = linear(a)
      const b = mem.get(lin)
      const hit = ds != null && seg === ds ? symbolAt(symbols, off + i) : null
      const color = hit ? VAR_COLORS[hit.index % VAR_COLORS.length] : undefined
      if (hit && color) legend.set(hit.sym.name, color)
      const anchor = cellAnchor(a)
      const style: CSSProperties = {}
      if (color) style.boxShadow = `inset 0 -2px 0 ${color}`
      if (lin === dsDx && lin !== dsSi && lin !== esDi) {
        style.outline = '1px dotted var(--mem-pointer)'
        style.outlineOffset = '-1px'
      }
      cells.push(
        <span
          key={i}
          role="gridcell"
          data-cell={`${hex(a.seg)}:${hex(a.off & 0xffff)}`}
          title={`${fmtAddr(a)}${hit ? ` · ${hit.sym.name}${hit.rel ? `[${hit.rel}]` : ''}` : ''}${b == null ? ` · ${t('asm.dump.unknown')}` : ` · ${hex(b, 2)}h (${b})`}`}
          style={style}
          className={cn(
            'dc',
            (b == null || b === 0) && lin !== dsSi && lin !== esDi && 'zero',
            (lin === dsSi || lin === esDi) && 'ptr',
            lin === ssSp && 'spp',
            mem.changed.has(lin) && 'chg',
            sameAnchor(selection, anchor) && 'is-ctx',
          )}
          onClick={() => {
            ownPick.current = true
            asm.select(anchor)
          }}
          onContextMenu={(e) => {
            ownPick.current = true
            menu.open(e, anchor)
          }}
        >
          {b == null ? (dec ? '···' : '··') : dec ? String(b).padStart(3, '0') : hex(b, 2)}
        </span>,
      )
      ascii += b == null ? ' ' : asciiOf(b)
    }
    rows.push(
      <div key={r} role="row" className="dr">
        <span className="da">{`${hex(seg)}:${hex(off)}`}</span>
        {cells}
        <span />
        <span className="asc">{ascii}</span>
      </div>,
    )
  }

  const veil = veilText(run)

  return (
    <section className="relative flex h-full min-h-0 flex-col" aria-label={t('asm.tabs.dump')}>
      <div className="pt">
        <label className={cn('dh-in', !parsed && 'bad')}>
          <span>{t('asm.dump.address')}</span>
          <input
            value={text}
            onChange={(e) => setText(e.target.value)}
            spellCheck={false}
            autoComplete="off"
            aria-invalid={!parsed}
            title={t('asm.dump.addressHint')}
          />
        </label>
        <span className="m">{parsed ? `= ${fmtAddr({ seg: parsed.seg, off: parsed.off & 0xfff0 })}` : t('asm.dump.bad')}</span>
        {['DS:0000', 'DS:SI', 'ES:DI', 'SS:SP'].map((label) => (
          <button key={label} type="button" className="chipbtn" onClick={() => setText(label)}>
            {label}
          </button>
        ))}
        {fetchState === 'loading' && <span className="m">{t('asm.dump.fetching', { step: stepIndex })}</span>}
        {fetchState === 'error' && <span className="m bad">{t('asm.dump.fetchError')}</span>}
        <span className="legend">
          {[...legend.entries()].slice(0, 5).map(([name, color]) => (
            <span key={name}>
              <i style={{ borderColor: color }} />
              {name}
            </span>
          ))}
        </span>
      </div>
      <div ref={win.ref} role="grid" aria-label={t('asm.tabs.dump')} tabIndex={0} onKeyDown={onKeyDown} className="qb">
        <div className={cn('dq', dec && 'is-dec')}>
          <div style={{ height: win.padTop }} />
          {rows}
          <div style={{ height: win.padBottom }} />
        </div>
      </div>
      {veil && <div className="veil">{veil}</div>}
      {menu.element}
    </section>
  )
}
