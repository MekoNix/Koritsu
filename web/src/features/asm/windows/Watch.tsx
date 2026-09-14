/**
 * Watch — наблюдение: регистры, флаги и ячейки, значение которых видно на
 * каждом шаге.
 *
 * Выражение — то же, что понимает «Дамп»: `CX`, `AL`, `EAX`, `ZF`, `DS:SI`,
 * `0780:0002`, `arr`, `arr[2]`. Арифметики нет намеренно: это не калькулятор, а
 * «куда смотреть», и выражение, которое окно посчитало не так, как человек
 * ожидал, хуже, чем честное «не разобрать».
 *
 * Список хранится в параметрах программы (`settings.watches`), а не в окне:
 * он переживает перезагрузку и его видит агент.
 */
import { useMemo, useState, type FormEvent } from 'react'

import { useAsm } from '@/features/asm/store'
import type { AsmAnchor, AsmRunSummary, AsmStep, AsmWindowProps } from '@/features/asm/types'
import { t as tr, useT } from '@/i18n'
import { cn } from '@/lib/cn'

import {
  FLAG_MNEMONIC,
  asciiOf,
  cellAnchor,
  dataSymbols,
  flagBit,
  fmtAddr,
  fmtInt,
  hasTrace,
  hex,
  isFlagName,
  linear,
  parseAddress,
  regValue,
  sameAnchor,
  stepFlags,
  useAnchorMenu,
  useMemView,
  type DataSymbol,
  type FlagName,
  type MemView,
  type Radix,
} from './format'

/** Больше выражений окно не держит: длинный список уже не «наблюдение», а дамп. */
const MAX_WATCHES = 32

interface Evaluated {
  text: string
  note: string
  anchor: AsmAnchor
  changed: boolean
}

function evaluate(
  expr: string,
  step: AsmStep,
  prev: AsmStep | undefined,
  run: AsmRunSummary | undefined,
  symbols: readonly DataSymbol[],
  mem: MemView,
  radix: Radix,
): Evaluated | null {
  const e = expr.trim()
  if (isFlagName(e)) {
    const f = e.toUpperCase() as FlagName
    const flags = stepFlags(step)
    const pf = stepFlags(prev)
    if (flags == null) return null
    const b = flagBit(flags, f)
    return {
      text: String(b),
      note: `${FLAG_MNEMONIC[f][b]} · ${tr(`asm.registers.flagName.${f}`)}`,
      anchor: { kind: 'flag', name: f },
      changed: pf != null && flagBit(pf, f) !== b,
    }
  }
  const r = regValue(step, e)
  if (r) {
    const pr = regValue(prev, e)
    const v = r.value
    const alt = radix === 'hex' ? fmtInt(v) : `${hex(v, r.bytes * 2)}h`
    return {
      text: radix === 'hex' ? hex(v, r.bytes * 2) : String(v),
      note: r.bytes === 1 && v >= 32 && v < 127 ? `${alt} «${asciiOf(v)}»` : alt,
      anchor: { kind: 'register', name: e.toUpperCase() },
      changed: pr != null && pr.value !== v,
    }
  }
  const a = parseAddress(e, step, run, symbols)
  if (!a) return null
  const lin = linear(a)
  const b = mem.get(lin)
  const hi = mem.get(lin + 1)
  return {
    text: b == null ? '··' : radix === 'hex' ? hex(b, 2) : String(b),
    note: `${fmtAddr(a)}${b != null && hi != null ? ` · ${tr('asm.watch.word')} ${hex(b | (hi << 8))}` : ''}`,
    anchor: cellAnchor(a),
    changed: mem.changed.has(lin),
  }
}

export default function Watch({ active }: AsmWindowProps) {
  const t = useT()
  const asm = useAsm()
  const { run, step, prevStep, stepIndex, settings, view, selection } = asm
  const menu = useAnchorMenu()
  const { mem } = useMemView(active)
  const symbols = useMemo(() => dataSymbols(run), [run])
  const trace = hasTrace(run)
  const st = trace ? step : undefined
  const prev = trace && stepIndex > 0 ? prevStep : undefined
  const [draft, setDraft] = useState('')

  const add = (e: FormEvent) => {
    e.preventDefault()
    const v = draft.trim()
    if (!v) return
    setDraft('')
    const list = settings.watches
    if (list.some((x) => x.toUpperCase() === v.toUpperCase())) return
    asm.updateSettings({ watches: [...list, v].slice(-MAX_WATCHES) })
  }

  return (
    <section className="relative flex h-full min-h-0 flex-col" aria-label={t('asm.tabs.watch')}>
      <form className="pt wform" onSubmit={add}>
        <label htmlFor="asm-watch-input" className="m">
          +
        </label>
        <input
          id="asm-watch-input"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder={t('asm.watch.placeholder')}
          autoComplete="off"
          spellCheck={false}
        />
        <button type="submit" className="tb">
          {t('asm.watch.add')}
        </button>
      </form>
      <div className="qb">
        {settings.watches.length === 0 ? (
          <div className="empty">{t('asm.watch.empty')}</div>
        ) : (
          settings.watches.map((expr, i) => {
            const v = st ? evaluate(expr, st, prev, run, symbols, mem, view.radix) : null
            return (
              <div
                key={`${expr}:${i}`}
                className={cn('wr', v?.changed && 'is-chg', v && sameAnchor(selection, v.anchor) && 'is-ctx')}
                onClick={() => v && asm.select(v.anchor)}
                onContextMenu={(e) => {
                  if (!v) return
                  menu.open(e, v.anchor, v.anchor.kind === 'register' || v.anchor.kind === 'flag' ? v.anchor.name : null)
                }}
              >
                <span className="we">{expr}</span>
                <span className="wv">{v ? v.text : st ? <span className="bad">?</span> : '—'}</span>
                <span className="wd">{v ? v.note : st ? t('asm.watch.bad') : t('asm.watch.noTrace')}</span>
                <button
                  type="button"
                  className="x"
                  aria-label={t('asm.watch.remove', { expr })}
                  onClick={(e) => {
                    e.stopPropagation()
                    asm.updateSettings({ watches: settings.watches.filter((_, j) => j !== i) })
                  }}
                >
                  ×
                </button>
              </div>
            )
          })
        )}
      </div>
      {menu.element}
    </section>
  )
}
