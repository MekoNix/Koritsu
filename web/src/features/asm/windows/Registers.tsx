/**
 * Registers — регистры и флаги после шага.
 *
 * Регистр общего назначения показан двумя байтами: `mov al, …` меняет только
 * младший, и подсветка всего слова говорила бы «AX поменялся целиком» — а это
 * неправда, и на ней как раз путаются. Подсвечивается ровно изменившийся байт
 * (в режиме 32 бит — и старшее слово отдельно).
 *
 * Флаги — с мнемониками DebugX (NV/OV, UP/DN, …): те же буквы человек видит в
 * окне сырого вывода и в любой книге по DEBUG, и «0/1» рядом не заменяет их, а
 * объясняет.
 */
import type { KeyboardEvent, MouseEvent } from 'react'

import { useAsm } from '@/features/asm/store'
import type { AsmAnchor, AsmStep, AsmWindowProps } from '@/features/asm/types'
import { useT } from '@/i18n'
import { cn } from '@/lib/cn'

import {
  FLAG_MNEMONIC,
  FLAG_ORDER,
  REG_GENERAL,
  REG_INDEX,
  REG_SEGMENT,
  firstError,
  flagBit,
  fmtInt,
  hasTrace,
  hex,
  isMenuKey,
  linear,
  menuPointOf,
  nextOf,
  reg,
  regValue,
  sameAnchor,
  segmentRole,
  stepFlags,
  traceState,
  useAnchorMenu,
  useMemView,
  veilText,
  type TraceState,
} from './format'

type NamedAnchor = Extract<AsmAnchor, { kind: 'register' | 'flag' }>

export default function Registers({ active }: AsmWindowProps) {
  const t = useT()
  const asm = useAsm()
  const { run, step, prevStep, stepIndex, view, selection } = asm
  const menu = useAnchorMenu()
  const { mem } = useMemView(active)
  const trace = hasTrace(run)
  const st = trace ? step : undefined
  const prev = trace && stepIndex > 0 ? prevStep : undefined
  const wide = view.bits === 32
  const dec = view.radix === 'dec'

  // Предыдущий шаг ещё не загружен — изменённое берём из списка самого шага.
  const changedByStep = (name: string) => !!st && !prev && st.changed.some((c) => c.toLowerCase() === name.toLowerCase())

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (!isMenuKey(e) || !selection || (selection.kind !== 'register' && selection.kind !== 'flag')) return
    const el = e.currentTarget.querySelector(`[data-anchor="${selection.kind}:${selection.name.toUpperCase()}"]`)
    if (!el) return
    e.preventDefault()
    e.stopPropagation()
    menu.open(menuPointOf(el), selection, selection.name.toUpperCase())
  }

  const rowProps = (anchor: NamedAnchor) => ({
    'data-anchor': `${anchor.kind}:${anchor.name}`,
    onClick: () => asm.select(anchor),
    onContextMenu: (e: MouseEvent) => menu.open(e, anchor, anchor.name),
  })
  const isCtx = (anchor: NamedAnchor) => sameAnchor(selection, anchor) && 'is-ctx'

  /* общие регистры: два байта, в 32 битах — ещё старшее слово */
  const general = REG_GENERAL.map((n) => {
    const N = n.toUpperCase()
    const v = regValue(st, n)?.value ?? null
    const pv = regValue(prev, n)?.value ?? null
    const hiChg = pv != null && v != null ? v >> 8 !== pv >> 8 : changedByStep(n)
    const loChg = pv != null && v != null ? (v & 0xff) !== (pv & 0xff) : changedByStep(n)
    const e32 = regValue(st, `e${n}`)?.value ?? null
    const pe32 = regValue(prev, `e${n}`)?.value ?? null
    const upper = e32 == null ? null : e32 >>> 16
    const upperChg = e32 != null && pe32 != null && e32 >>> 16 !== pe32 >>> 16
    const full = wide && e32 != null ? e32 : v
    const anchor: NamedAnchor = { kind: 'register', name: N }
    return (
      <div
        key={n}
        {...rowProps(anchor)}
        title={t('asm.registers.byteHint', { hi: `${N[0]}H`, lo: `${N[0]}L` })}
        className={cn('reg', (hiChg || loChg || upperChg) && 'is-chg', isCtx(anchor))}
      >
        <span className="rn">{wide ? `E${N}` : N}</span>
        <span className="rv">
          {v == null ? (
            <i className="z">{wide ? '········' : '····'}</i>
          ) : dec ? (
            <b className={cn((hiChg || loChg || upperChg) && 'chg')}>{String(full ?? 0).padStart(wide ? 10 : 5, ' ')}</b>
          ) : (
            <>
              {wide &&
                (upper == null || (upper === 0 && !upperChg) ? (
                  <i className="z">{upper == null ? '····' : '0000'}</i>
                ) : (
                  <b className={cn(upperChg && 'chg')}>{hex(upper)}</b>
                ))}
              <b className={cn(hiChg && 'chg')}>{hex(v >> 8, 2)}</b>
              <b className={cn(loChg && 'chg')}>{hex(v & 0xff, 2)}</b>
            </>
          )}
        </span>
        <span className="rd">{v == null ? '' : dec ? `${hex(full ?? 0, wide ? 8 : 4)}h` : fmtInt(full ?? 0)}</span>
      </div>
    )
  })

  /* индексные и указатели */
  const index = REG_INDEX.map((n) => {
    const N = n.toUpperCase()
    const v = reg(st, n)
    const pv = reg(prev, n)
    const chg = pv != null && v != null ? v !== pv : changedByStep(n)
    const e32 = n === 'ip' ? null : (regValue(st, `e${n}`)?.value ?? null)
    const full = wide && e32 != null ? e32 : v
    let note = ''
    if (v != null) {
      if (n === 'ip') {
        const line = nextOf(st)?.line
        note = line != null ? t('asm.registers.ipLine', { line }) : '—'
      } else note = dec ? `${hex(full ?? 0, wide ? 8 : 4)}h` : fmtInt(full ?? 0)
    }
    const anchor: NamedAnchor = { kind: 'register', name: N }
    return (
      <div key={n} {...rowProps(anchor)} className={cn('reg', chg && 'is-chg', isCtx(anchor))}>
        <span className="rn">{wide && n !== 'ip' ? `E${N}` : N}</span>
        <span className="rv">
          {v == null ? (
            <i className="z">····</i>
          ) : dec && n !== 'ip' ? (
            <b className={cn(chg && 'chg')}>{String(full ?? 0).padStart(wide ? 10 : 5, ' ')}</b>
          ) : (
            <>
              {wide && n !== 'ip' && (e32 == null || e32 >>> 16 === 0) && <i className="z">{e32 == null ? '····' : '0000'}</i>}
              <b className={cn(chg && 'chg')}>{wide && e32 != null && e32 >>> 16 !== 0 ? hex(e32, 8) : hex(v)}</b>
            </>
          )}
        </span>
        <span className="rd">{note}</span>
      </div>
    )
  })

  /* сегментные */
  const segments = REG_SEGMENT.map((n, i) => {
    const N = n.toUpperCase()
    const v = reg(st, n)
    const pv = reg(prev, n)
    const chg = pv != null && v != null ? v !== pv : changedByStep(n)
    const role = v == null ? null : segmentRole(run, v)
    const anchor: NamedAnchor = { kind: 'register', name: N }
    return (
      <div key={n} {...rowProps(anchor)} className={cn('reg', i === 0 && 'sep', chg && 'is-chg', isCtx(anchor))}>
        <span className="rn">{N}</span>
        <span className="rv">{v == null ? <i className="z">····</i> : <b className={cn(chg && 'chg')}>{hex(v)}</b>}</span>
        <span className="rd">{role ? t(`asm.registers.seg.${role}`) : ''}</span>
      </div>
    )
  })

  const flags = stepFlags(st)
  const prevFlags = stepFlags(prev)
  const flagRows = FLAG_ORDER.map((f) => {
    const b = flags == null ? null : flagBit(flags, f)
    const pb = prevFlags == null ? null : flagBit(prevFlags, f)
    const chg = b != null && pb != null ? b !== pb : changedByStep(f)
    const anchor: NamedAnchor = { kind: 'flag', name: f }
    const name = t(`asm.registers.flagName.${f}`)
    return (
      <div key={f} {...rowProps(anchor)} title={name} className={cn('flg', b === 1 && 'on', chg && 'is-chg', isCtx(anchor))}>
        <span>{f}</span>
        <b>{b ?? '·'}</b>
        <em>{b == null ? '··' : FLAG_MNEMONIC[f][b]}</em>
        <small>{name}</small>
      </div>
    )
  })

  const state = traceState(run)

  return (
    <section className="relative flex h-full min-h-0 flex-col" aria-label={t('asm.tabs.registers')}>
      <div className="pt">
        <span className="m">{st ? t('asm.registers.afterStep', { step: fmtInt(stepIndex) }) : ''}</span>
        <span className="grow" />
        <div className="seg" role="group" aria-label={t('asm.registers.bits')}>
          {([16, 32] as const).map((b) => (
            <button key={b} type="button" aria-pressed={view.bits === b} onClick={() => asm.setView({ bits: b })}>
              {b === 16 ? '16' : t('asm.registers.bits32')}
            </button>
          ))}
        </div>
      </div>
      <div className="qb regbox" tabIndex={0} onKeyDown={onKeyDown}>
        {wide && st && !st.reg32 && <div className="empty">{t('asm.registers.no32')}</div>}
        <div className="rq">
          <div>
            {general}
            {index}
            {segments}
            {st && <Pairs step={st} memByte={(a) => mem.get(a)} />}
          </div>
          <div>
            <div className="fh">{t('asm.registers.flagsHead')}</div>
            {flagRows}
          </div>
        </div>
      </div>
      {state !== 'ready' && <Veil run={run} state={state} />}
      {menu.element}
    </section>
  )
}

/** Пары «сегмент:смещение» под регистрами — то, куда они сейчас указывают. */
function Pairs({ step, memByte }: { step: AsmStep; memByte: (addr: number) => number | null }) {
  const t = useT()
  const v = (n: Parameters<typeof reg>[1]) => reg(step, n) ?? 0
  const at = memByte(linear({ seg: v('ds'), off: v('si') }))
  return (
    <div className="pairs">
      <div>
        <span>CS:IP</span>
        <b>{`${hex(v('cs'))}:${hex(v('ip'))}`}</b>
      </div>
      <div>
        <span>SS:SP</span>
        <b>{`${hex(v('ss'))}:${hex(v('sp'))}`}</b>
      </div>
      <div title={t('asm.registers.dsSiHint')}>
        <span>DS:SI</span>
        <b>{`${hex(v('ds'))}:${hex(v('si'))} → ${at == null ? '??' : hex(at, 2)}`}</b>
      </div>
    </div>
  )
}

/** Заглушка поверх окна: этапы идущей сборки или почему трассы нет. */
function Veil({ run, state }: { run: Parameters<typeof veilText>[0]; state: TraceState }) {
  const t = useT()
  if (state !== 'queued' && state !== 'building' && state !== 'running') {
    const e = firstError(run)
    return <div className="veil">{e && state === 'build_error' ? t('asm.trace.buildErrorLine', { line: e.line }) : veilText(run)}</div>
  }
  // Статус службы не различает TASM и TLINK: пока идёт сборка, «сейчас» горят оба.
  const stages = [
    { key: 'tasm', done: state === 'running', now: state === 'building' },
    { key: 'tlink', done: state === 'running', now: state === 'building' },
    { key: 'trace', done: false, now: state === 'running' },
  ]
  return (
    <div className="veil">
      <div className="stages">
        {stages.map((s) => (
          <div key={s.key} className={cn(s.done && 'done', s.now && 'now')}>
            <i />
            {t(`asm.trace.stage.${s.key}`)}
          </div>
        ))}
      </div>
    </div>
  )
}
