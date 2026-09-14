/**
 * Stack — окно стека вокруг SS:SP, словами.
 *
 * Выше SP — то, что лежит в стеке. Ниже SP — не стек, а след: `push` и вызовы
 * прерываний кладут туда слова, а `pop` и `iret` только двигают SP и ничего не
 * стирают. Такие слова показаны бледно, но показаны: «откуда здесь FLAGS»
 * спрашивают как раз про них.
 */
import { useMemo, type KeyboardEvent, type ReactNode } from 'react'

import { useAsm } from '@/features/asm/store'
import type { AsmWindowProps } from '@/features/asm/types'
import { useT } from '@/i18n'
import { cn } from '@/lib/cn'

import {
  cellAnchor,
  fmtInt,
  hasTrace,
  hex,
  isMenuKey,
  linear,
  menuPointOf,
  parseHex,
  reg,
  sameAnchor,
  stackTop,
  useAnchorMenu,
  useMemView,
  veilText,
} from './format'

/** Сколько слов показывать ниже SP (след) и выше (стек). */
const BELOW = 8
const ABOVE = 20

export default function Stack({ active }: AsmWindowProps) {
  const t = useT()
  const asm = useAsm()
  const { run, step, prevStep, stepIndex, view, selection } = asm
  const menu = useAnchorMenu()
  const { mem } = useMemView(active)
  const trace = hasTrace(run)
  const st = trace ? step : undefined
  const ss = reg(st, 'ss') ?? parseHex(run?.load?.ss)
  const sp = reg(st, 'sp')
  const prevSp = stepIndex > 0 ? reg(trace ? prevStep : undefined, 'sp') : null
  const top = useMemo(() => stackTop(run), [run])
  const dec = view.radix === 'dec'

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (!isMenuKey(e) || selection?.kind !== 'cell') return
    const el = e.currentTarget.querySelector(`[data-cell="${selection.seg}:${selection.off}"]`)
    if (!el) return
    e.preventDefault()
    e.stopPropagation()
    menu.open(menuPointOf(el), selection)
  }

  const rows: ReactNode[] = []
  if (st && ss != null && sp != null) {
    const start = Math.max(0, (sp - BELOW * 2) & 0xfffe)
    const end = Math.min(top, sp + ABOVE * 2)
    const spRow = (
      <div key="sp" className="st sprow">
        <span className="sa">{`${hex(ss)}:${hex(sp)}`}</span>
        <span className="sv">{t('asm.stack.spMark')}</span>
        <span className="sn">{sp >= top ? t('asm.stack.empty') : t('asm.stack.top')}</span>
      </div>
    )
    for (let off = start; off < end; off += 2) {
      if (off === sp) rows.push(spRow)
      const a = linear({ seg: ss, off })
      const lo = mem.get(a)
      const hi = mem.get(a + 1)
      const v = lo == null || hi == null ? null : lo | (hi << 8)
      const written = mem.written.has(a) || mem.written.has(a + 1)
      const dead = off < sp
      const anchor = cellAnchor({ seg: ss, off })
      rows.push(
        <div
          key={off}
          data-cell={`${hex(ss)}:${hex(off)}`}
          className={cn(
            'st',
            dead && 'dead',
            written && 'res',
            (mem.changed.has(a) || mem.changed.has(a + 1)) && 'chg',
            sameAnchor(selection, anchor) && 'is-ctx',
          )}
          onClick={() => asm.select(anchor)}
          onContextMenu={(e) => menu.open(e, anchor)}
        >
          <span className="sa">{`${hex(ss)}:${hex(off)}`}</span>
          <span className="sv">{v == null ? '····' : dec ? String(v) : hex(v)}</span>
          <span className="sn">{dead ? (written ? t('asm.stack.trace') : t('asm.stack.free')) : ''}</span>
        </div>,
      )
    }
    if (sp >= end) rows.push(spRow)
  }

  const delta = sp != null && prevSp != null ? sp - prevSp : 0
  const veil = veilText(run)

  return (
    <section className="relative flex h-full min-h-0 flex-col" aria-label={t('asm.tabs.stack')}>
      <div className="pt">
        {st && ss != null && sp != null && (
          <>
            <span className="m">{t('asm.stack.meta', { ss: hex(ss), sp: hex(sp), used: fmtInt(Math.max(0, top - sp)) })}</span>
            {delta !== 0 && <span className="m text-warn">{t(delta < 0 ? 'asm.stack.pushed' : 'asm.stack.popped', { n: Math.abs(delta) })}</span>}
          </>
        )}
      </div>
      <div className="qb" tabIndex={0} onKeyDown={onKeyDown}>
        {rows}
        {rows.length > 0 && <div className="snote">{t('asm.stack.note')}</div>}
      </div>
      {veil && <div className="veil">{veil}</div>}
      {menu.element}
    </section>
  )
}
