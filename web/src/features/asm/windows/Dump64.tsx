/**
 * Dump64 — плоская память Windows x64 по 16 байт в строке: hex (или dec) и ASCII.
 *
 * Адрес — одно число, 16 знаков. Поле понимает `0x140003000`, `140003000h`,
 * имя переменной `message`, `message+8`, `rsp+32`, `[rsp]` (адрес, лежащий в
 * стеке) и имя секции `.data`. Регистры берутся с текущего шага, поэтому `rsp`
 * едет за RSP сам.
 *
 * Листается не всё адресное пространство, а одна секция образа (кнопки
 * `.text .data .bss .rdata .idata` над строками) или окно вокруг адреса вне
 * секций — стек. Между секциями у Windows-программы пусто, и мегабайты `··`
 * были бы шумом.
 *
 * Байты переменных подчёркнуты цветом своего символа; ячейки таблицы импорта
 * подписаны `__imp_WriteFile`. RSP обведён пунктиром, RBP — точками, RIP —
 * рамкой. Перед вызовом API подсвечен его буфер (`lpBuffer … +n`) и ячейка,
 * куда функция запишет счётчик. Неизвестные байты окно дочитывает само, когда
 * человек перестал листать.
 */
import { useEffect, useMemo, useRef, useState, type CSSProperties, type KeyboardEvent, type ReactNode } from 'react'

import { useAsm } from '@/features/asm/store'
import type { AsmWindowProps } from '@/features/asm/types'
import { useT } from '@/i18n'
import { cn } from '@/lib/cn'

import {
  bigToNum,
  callArgs,
  flatImage,
  hex16,
  hexNum,
  parseFlatRef,
  pendingCall,
  regNum,
  resolveFlatAddress,
  sectionAt,
  symbolAt,
} from './flat'
import {
  ROW,
  asciiOf,
  hasTrace,
  hex,
  isMenuKey,
  menuPointOf,
  sameAnchor,
  useAnchorMenu,
  useFlatFetch,
  useMemView,
  useRowWindow,
  veilText,
} from './format'
import './windows64.css'

/** Цвета подчёркивания переменных по кругу — из токенов темы. */
const VAR_COLORS = ['var(--info)', 'var(--ok)', 'var(--code-num)', 'var(--agent)', 'var(--warn)']
/** Окно вокруг адреса вне секций (стек): байт до и после. */
const AROUND_BEFORE = 0x100
const AROUND_AFTER = 0x700
/** Больше строк у одной секции не листается: у огромной `.bss` видно начало. */
const MAX_ROWS = 0x4000
/** Потолок подсветки буфера вызова, байт. */
const MAX_BUFFER = 0x1000

interface Region {
  name: string | null
  start: number
  rows: number
}

export default function Dump64({ active }: AsmWindowProps) {
  const t = useT()
  const asm = useAsm()
  const { run, step, stepIndex, view, selection, getStep } = asm
  const menu = useAnchorMenu()
  const { mem, scan } = useMemView(active)
  const trace = hasTrace(run)
  const st = trace ? step : undefined
  const img = useMemo(() => flatImage(run), [run])
  const dec = view.radix === 'dec'
  const get = (a: number) => mem.get(a)

  const [text, setText] = useState('.data')
  const ref = parseFlatRef(text, st, run)
  const addr = resolveFlatAddress(ref, get)
  const lastGood = useRef<number | null>(null)
  if (addr != null) lastGood.current = addr
  const fallback = (img.sections.find((s) => s.name === '.data') ?? img.sections[0])?.start ?? null
  const target = addr ?? lastGood.current ?? fallback

  const region = useMemo<Region | null>(() => {
    if (target == null) return null
    const sec = sectionAt(img.sections, target)
    if (sec) {
      const start = Math.floor(sec.start / 16) * 16
      const end = Math.ceil(Math.max(sec.end, sec.start + 16) / 16) * 16
      return { name: sec.name, start, rows: Math.min(MAX_ROWS, (end - start) / 16) }
    }
    const start = Math.max(0, Math.floor((target - AROUND_BEFORE) / 16) * 16)
    return { name: null, start, rows: (AROUND_BEFORE + AROUND_AFTER) / 16 }
    // Окно вне секций пересчитывается, только когда адрес ушёл из него: иначе
    // каждый push сдвигал бы строки под курсором.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [img, target == null ? null : sectionAt(img.sections, target)?.name ?? Math.floor(target / 0x400)])

  const rows = region?.rows ?? 0
  const win = useRowWindow(rows, { overscan: 4 })
  const { reveal } = win
  const targetRow = region && target != null ? Math.floor((target - region.start) / 16) : -1
  useEffect(() => {
    if (targetRow >= 0 && targetRow < rows) reveal(targetRow, false)
  }, [targetRow, rows, region?.start, reveal])

  // Ячейку выбрали снаружи — перейти к ней; свой щелчок адрес не переписывает,
  // иначе `rsp+32` превращался бы в число и переставал следить за RSP.
  const ownPick = useRef(false)
  useEffect(() => {
    if (selection?.kind !== 'cell' || selection.seg != null) return
    if (ownPick.current) {
      ownPick.current = false
      return
    }
    setText(`0x${selection.off}`)
  }, [selection])

  const rsp = regNum(st, 'rsp')
  const rbp = regNum(st, 'rbp')
  const rip = regNum(st, 'rip') ?? hexNum(st?.next?.ip)

  // Вызов API следующей командой: его буфер и ячейка счётчика.
  const pc = st ? pendingCall(st, getStep(stepIndex + 1), img) : null
  let buf: { from: number; to: number; title: string } | null = null
  let out: { from: number; title: string } | null = null
  if (pc?.fn) {
    const args = callArgs(pc.fn, st, get)
    for (const a of args) {
      const v = bigToNum(a.value)
      if (v == null || v === 0) continue
      if (a.param.role === 'buffer') {
        const lenArg = args.find((x) => x.param.name === a.param.lenParam)
        const len = Math.min(MAX_BUFFER, bigToNum(lenArg?.value ?? null) ?? 1)
        buf = { from: v, to: v + Math.max(1, len), title: t('asm64.dump.callBuffer', { name: pc.fn.name, param: a.param.name }) }
      } else if (a.param.role === 'outCount') out = { from: v, title: t('asm64.dump.outCount', { name: pc.fn.name, param: a.param.name }) }
    }
  }

  // Первая строка на экране с неизвестным байтом — её и дочитываем.
  const visibleRows = Math.ceil(win.height / ROW)
  let unknownAt: number | null = null
  if (trace && region) {
    outer: for (let r = win.visibleFirst; r < Math.min(rows, win.visibleFirst + visibleRows + 1); r++) {
      for (let i = 0; i < 16; i++) {
        if (mem.get(region.start + r * 16 + i) == null) {
          unknownAt = region.start + r * 16
          break outer
        }
      }
    }
  }
  const fetchLen = region && unknownAt != null ? Math.min(region.start + rows * 16 - unknownAt, Math.max(256, (visibleRows + 2) * 16)) : 0
  const fetchState = useFlatFetch({ active: active && trace, scan, from: unknownAt, len: fetchLen })

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (!isMenuKey(e) || selection?.kind !== 'cell' || selection.seg != null) return
    const el = e.currentTarget.querySelector(`[data-cell="${selection.off}"]`)
    if (!el) return
    e.preventDefault()
    e.stopPropagation()
    menu.open(menuPointOf(el), selection)
  }

  const legend = new Map<string, string>()
  const lines: ReactNode[] = []
  if (region) {
    for (let r = win.first; r < win.last; r++) {
      const base = region.start + r * 16
      const cells: ReactNode[] = []
      let ascii = ''
      for (let i = 0; i < 16; i++) {
        const a = base + i
        const b = mem.get(a)
        const hit = symbolAt(img, a)
        const color = hit ? VAR_COLORS[hit.index % VAR_COLORS.length] : undefined
        if (hit && color) legend.set(hit.sym.name, color)
        const h = hex16(a)
        const anchor = { kind: 'cell', seg: null, off: h } as const
        const style: CSSProperties = {}
        if (color) style.boxShadow = `inset 0 -2px 0 ${color}`
        const inBuf = !!buf && a >= buf.from && a < buf.to
        const inOut = !!out && a >= out.from && a < out.from + 4
        const titleParts = [
          h,
          hit ? `${hit.sym.name}${hit.rel ? `+${hit.rel}` : ''}` : null,
          inBuf ? buf!.title : null,
          inOut ? out!.title : null,
          b == null ? t('asm64.dump.unknown') : `${hex(b, 2)}h (${b})`,
        ]
        cells.push(
          <span
            key={i}
            role="gridcell"
            data-cell={h}
            title={titleParts.filter(Boolean).join(' · ')}
            style={style}
            className={cn(
              'dc',
              (b == null || b === 0) && 'zero',
              a === rsp && 'spp',
              a === rbp && a !== rsp && 'bpp',
              a === rip && 'ripp',
              inBuf && 'argbuf',
              inOut && 'argout',
              mem.changed.has(a) && 'chg',
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
      const h = hex16(base)
      lines.push(
        <div key={r} role="row" className="dr">
          <span className="da">
            <span className="hi">{h.slice(0, 8)}</span>
            {h.slice(8)}
          </span>
          {cells}
          <span />
          <span className="asc">{ascii}</span>
        </div>,
      )
    }
  }

  const veil = veilText(run)

  return (
    <section className="relative flex h-full min-h-0 flex-col" aria-label={t('asm.tabs.dump')}>
      <div className="pt">
        <label className={cn('dh-in wide', addr == null && 'bad')}>
          <span>{t('asm64.dump.address')}</span>
          <input
            value={text}
            onChange={(e) => setText(e.target.value)}
            spellCheck={false}
            autoComplete="off"
            aria-invalid={addr == null}
            title={t('asm64.dump.addressHint')}
          />
        </label>
        {addr == null ? (
          <span className="m bad" title={t('asm64.dump.bad')}>
            {t('asm64.dump.bad')}
          </span>
        ) : (
          <span className="m">{`= ${hex16(addr)}${region?.name ? '' : ` · ${t('asm64.dump.outside')}`}`}</span>
        )}
        {img.sections.map((s) => (
          <button
            key={s.name}
            type="button"
            className="chipbtn"
            aria-pressed={region?.name === s.name}
            title={t('asm64.dump.sectionHint', { name: s.name, start: hex16(s.start), size: s.length })}
            onClick={() => setText(s.name)}
          >
            {s.name}
          </button>
        ))}
        <button type="button" className="chipbtn" aria-pressed={text.trim().toLowerCase() === 'rsp'} onClick={() => setText('rsp')}>
          {t('asm64.dump.stack')}
        </button>
        {fetchState === 'loading' && <span className="m">{t('asm64.dump.fetching', { step: stepIndex })}</span>}
        {fetchState === 'error' && <span className="m bad">{t('asm64.dump.fetchError')}</span>}
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
        <div className={cn('dq dq64', dec && 'is-dec')}>
          <div style={{ height: win.padTop }} />
          {lines}
          <div style={{ height: win.padBottom }} />
        </div>
      </div>
      {veil && <div className="veil">{veil}</div>}
      {menu.element}
    </section>
  )
}
