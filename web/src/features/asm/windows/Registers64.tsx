/**
 * Registers64 — регистры и флаги Windows x64 после шага.
 *
 * Регистр показан восемью байтами, и подсвечивается ровно изменившийся байт:
 * `mov al, 'A'` меняет младший, `mov eax, …` обнуляет старшие четыре, и это
 * видно. Наведение на регистр показывает его части — `EAX AX AH AL` или
 * `R8D R8W R8B`: в лабе пишут то `rcx`, то `ecx`, и вопрос «это одно и то же
 * место?» снимается сразу.
 *
 * Под регистрами — то, на чём спотыкаются в соглашении Microsoft x64: кратен
 * ли RSP шестнадцати (перед `call` обязан), что лежит в `[RSP]`, куда указывает
 * RIP, и какой вызов API выполнил шаг — с RAX и пометкой, что RCX/RDX/R8–R11
 * вызов вправе испортить.
 *
 * Флаги RFLAGS — битами с подписью `0`/`1` и записью gdb `[ ZF PF ]`: мнемоник
 * DebugX в Windows-отладчиках нет. Сегментные регистры свёрнуты: в плоской
 * модели они ни на что не указывают.
 */
import { useMemo, useState, type KeyboardEvent, type MouseEvent } from 'react'

import { useAsm } from '@/features/asm/store'
import type { AsmAnchor, AsmStep, AsmWindowProps } from '@/features/asm/types'
import { useT } from '@/i18n'
import { cn } from '@/lib/cn'

import {
  bigToNum,
  flatImage,
  fmtBig,
  gdbFlags,
  hex16,
  hexNum,
  hexOf,
  isCallText,
  pendingCall,
  readLE,
  regBig,
  regParts,
  sectionAt,
  signed,
  subRegister,
  symbolize,
} from './flat'
import {
  firstError,
  fmtInt,
  hasTrace,
  isMenuKey,
  menuPointOf,
  sameAnchor,
  traceState,
  useAnchorMenu,
  useMemView,
  veilText,
  type TraceState,
} from './format'
import { VOLATILE } from './winapi'
import './windows64.css'

type NamedAnchor = Extract<AsmAnchor, { kind: 'register' | 'flag' }>

export default function Registers64({ active }: AsmWindowProps) {
  const t = useT()
  const asm = useAsm()
  const { run, step, prevStep, stepIndex, view, selection, toolchain, getStep } = asm
  const menu = useAnchorMenu()
  const { mem } = useMemView(active)
  const trace = hasTrace(run)
  const st = trace ? step : undefined
  const prev = trace && stepIndex > 0 ? prevStep : undefined
  const dec = view.radix === 'dec'
  const img = useMemo(() => flatImage(run), [run])
  const [hover, setHover] = useState<string | null>(null)
  const [segOpen, setSegOpen] = useState(false)

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

  /* строка регистра: восемь байт, изменённые подсвечены по одному */
  const regRow = (n: string, sep: boolean) => {
    const N = n.toUpperCase()
    const v = regBig(st, n)
    const pv = regBig(prev, n)
    const byStep = changedByStep(n)
    const byteChg = (i: number) => (v != null && pv != null ? ((v >> BigInt(i * 8)) & 0xffn) !== ((pv >> BigInt(i * 8)) & 0xffn) : byStep)
    const chg = v != null && pv != null ? v !== pv : byStep
    const anchor: NamedAnchor = { kind: 'register', name: N }
    const parts = regParts(n)
    let note = ''
    if (v != null) {
      if (n === 'rip') {
        const addr = bigToNum(v)
        const line = st?.next?.line
        const sym = addr == null ? null : symbolize(img, addr)
        note = [line != null ? t('asm64.registers.ripLine', { line }) : null, sym].filter(Boolean).join(' · ') || '—'
      } else if (n === 'rflags') note = gdbFlags(v)
      else if (dec) note = `${hexOf(v, 16)}h`
      else {
        const s = signed(v, 64)
        note = s < 0n ? `${fmtBig(v)} / ${fmtBig(s)}` : fmtBig(v)
      }
    }
    const volatile = !!st?.call && chg && (VOLATILE as readonly string[]).includes(n) && n !== 'rax'
    const high = v == null ? null : v >> 32n
    const highChg = [4, 5, 6, 7].some(byteChg)
    return (
      <div
        key={n}
        {...rowProps(anchor)}
        onMouseEnter={() => setHover(n)}
        title={parts.length ? t('asm64.registers.parts', { parts: parts.map((p) => p.toUpperCase()).join(' ') }) : undefined}
        className={cn('reg', sep && 'sep', chg && 'is-chg', isCtx(anchor))}
      >
        <span className="rn">{N}</span>
        <span className="rv">
          {v == null ? (
            <i className="z">{'·'.repeat(16)}</i>
          ) : dec && n !== 'rip' && n !== 'rflags' ? (
            <b className={cn(chg && 'chg')}>{v.toString().padStart(20, ' ')}</b>
          ) : (
            <>
              {high === 0n && !highChg ? (
                <i className="z">00000000</i>
              ) : (
                [7, 6, 5, 4].map((i) => (
                  <b key={i} className={cn(byteChg(i) && 'chg')}>
                    {hexOf(v >> BigInt(i * 8), 2)}
                  </b>
                ))
              )}
              {[3, 2, 1, 0].map((i) => (
                <b key={i} className={cn(byteChg(i) && 'chg')}>
                  {hexOf(v >> BigInt(i * 8), 2)}
                </b>
              ))}
            </>
          )}
        </span>
        <span className="rd">
          {note}
          {volatile && <span className="vol">{` · ${t('asm64.registers.volatileMark')}`}</span>}
        </span>
      </div>
    )
  }

  const groups = toolchain.registers.filter((g) => g.id !== 'segment')
  const segNames = toolchain.registers.find((g) => g.id === 'segment')?.names ?? []
  const regRows = groups.flatMap((g, gi) => g.names.map((n, i) => regRow(n, gi > 0 && i === 0)))

  const segRows = segOpen
    ? segNames.map((n) => {
        const N = n.toUpperCase()
        const v = regBig(st, n)
        const pv = regBig(prev, n)
        const chg = v != null && pv != null ? v !== pv : changedByStep(n)
        const anchor: NamedAnchor = { kind: 'register', name: N }
        return (
          <div key={n} {...rowProps(anchor)} className={cn('reg', chg && 'is-chg', isCtx(anchor))}>
            <span className="rn">{N}</span>
            <span className="rv">{v == null ? <i className="z">····</i> : <b className={cn(chg && 'chg')}>{hexOf(v, 4)}</b>}</span>
            <span className="rd">{n === 'gs' ? t('asm64.registers.gsNote') : ''}</span>
          </div>
        )
      })
    : null

  /* части регистра под курсором или выбранного */
  const partsOf = (() => {
    const pick = hover ?? (selection?.kind === 'register' ? selection.name.toLowerCase() : null)
    const sub = pick ? subRegister(pick) : null
    if (!sub || !st) return null
    const base = sub.base
    const names = [base, ...regParts(base)]
    return names.map((p) => {
      const v = regBig(st, p)
      const width = (subRegister(p)?.bits ?? 64) / 4
      return (
        <span key={p}>
          {p.toUpperCase()} = <b>{v == null ? '·' : hexOf(v, width)}</b>
        </span>
      )
    })
  })()

  /* флаги */
  const rflags = regBig(st, 'rflags')
  const prevFlags = regBig(prev, 'rflags')
  const flagRows = toolchain.flags.map((f) => {
    const b = rflags == null ? null : Number((rflags >> BigInt(f.bit)) & 1n)
    const pb = prevFlags == null ? null : Number((prevFlags >> BigInt(f.bit)) & 1n)
    const chg = b != null && pb != null ? b !== pb : changedByStep(f.name)
    const anchor: NamedAnchor = { kind: 'flag', name: f.name }
    const name = t(`asm64.flagName.${f.name}`)
    return (
      <div key={f.name} {...rowProps(anchor)} title={name} className={cn('flg', b === 1 && 'on', chg && 'is-chg', isCtx(anchor))}>
        <span>{f.name}</span>
        <b>{b == null ? '·' : f.label[b]}</b>
        <em>{t('asm64.registers.bit', { n: f.bit })}</em>
        <small>{name}</small>
      </div>
    )
  })

  const state = traceState(run)

  return (
    <section className="r64 relative flex h-full min-h-0 flex-col" aria-label={t('asm.tabs.registers')}>
      <div className="pt">
        <span className="m">{st ? t('asm64.registers.afterStep', { step: fmtInt(stepIndex) }) : ''}</span>
      </div>
      <div className="qb regbox" tabIndex={0} onKeyDown={onKeyDown} onMouseLeave={() => setHover(null)}>
        <div className="rq">
          <div>
            {regRows}
            <button type="button" className="r64-segbtn" aria-expanded={segOpen} title={t('asm64.registers.segmentsHint')} onClick={() => setSegOpen((o) => !o)}>
              <span aria-hidden="true">{segOpen ? '▾' : '▸'}</span>
              {t('asm64.registers.segments')}
            </button>
            {segRows}
            <div className="r64-parts" title={t('asm64.registers.partsHint')}>
              {partsOf}
            </div>
            {st && <Pointers step={st} next={getStep(stepIndex + 1)} get={(a) => mem.get(a)} img={img} />}
          </div>
          <div>
            <div className="fh">{t('asm64.registers.flagsHead')}</div>
            <div className="r64-fv">
              <b>{rflags == null ? '·'.repeat(16) : hex16(bigToNum(rflags) ?? 0)}</b>
              <span>{rflags == null ? '' : gdbFlags(rflags)}</span>
            </div>
            {flagRows}
          </div>
        </div>
      </div>
      {state !== 'ready' && <Veil run={run} state={state} stages={toolchain.stages} />}
      {menu.element}
    </section>
  )
}

/** Под регистрами: выравнивание RSP, `[RSP]`, куда указывает RIP, вызов API шага. */
function Pointers({
  step,
  next,
  get,
  img,
}: {
  step: AsmStep
  next: AsmStep | undefined
  get: (addr: number) => number | null
  img: ReturnType<typeof flatImage>
}) {
  const t = useT()
  const rsp = bigToNum(regBig(step, 'rsp'))
  const rip = bigToNum(regBig(step, 'rip')) ?? hexNum(step.next?.ip)
  const rbp = bigToNum(regBig(step, 'rbp'))
  const beforeCall = isCallText(step.next?.asm)
  const rem = rsp == null ? null : rsp % 16
  const atRsp = rsp == null ? null : readLE(get, rsp, 8)
  const atRbp8 = rbp == null ? null : readLE(get, rbp + 8, 8)
  const sec = rip == null ? null : sectionAt(img.sections, rip)
  const ripSym = rip == null ? null : symbolize(img, rip)
  const pc = pendingCall(step, next, img)
  const rax = regBig(step, 'rax')
  const q = (v: bigint | null) => (v == null ? t('asm64.registers.unknown') : hexOf(v, 16))
  const aligned = rem === 0
  return (
    <div className="pairs">
      {rem != null && (
        <div title={t('asm64.registers.rspAlignHint')} className={cn(beforeCall && !aligned && 'is-warn', aligned && 'is-ok')}>
          <span>{t('asm64.registers.rspAlign')}</span>
          <b>
            {aligned ? t('asm64.registers.yes') : t('asm64.registers.no')}
            {!aligned && ` · ${beforeCall ? t('asm64.registers.rspAlignBad', { n: rem }) : t('asm64.registers.rspAlignEntry', { n: rem })}`}
          </b>
        </div>
      )}
      <div>
        <span>{t('asm64.registers.atRsp')}</span>
        <b>{q(atRsp)}</b>
      </div>
      {rbp != null && rsp != null && rbp >= rsp && (
        <div>
          <span>{t('asm64.registers.atRbp')}</span>
          <b>{q(atRbp8)}</b>
        </div>
      )}
      {rip != null && (
        <div>
          <span>{t('asm64.registers.ripAt')}</span>
          <b>{[sec?.name, ripSym].filter(Boolean).join(' · ') || hex16(rip)}</b>
        </div>
      )}
      {step.call && (
        <span className="r64-call">
          {t('asm64.registers.call', { name: step.call, rax: rax == null ? '?' : hexOf(rax, 16) })}
          <small>{t('asm64.registers.callVolatile')}</small>
        </span>
      )}
      {pc?.api && pc.name && <span className="r64-call">{t('asm64.registers.nextCall', { name: pc.name })}</span>}
    </div>
  )
}

/** Заглушка поверх окна: этапы идущей сборки (`as`, `ld`, трасса) или почему трассы нет. */
function Veil({ run, state, stages }: { run: Parameters<typeof veilText>[0]; state: TraceState; stages: readonly [string, string, string] }) {
  const t = useT()
  if (state !== 'queued' && state !== 'building' && state !== 'running') {
    const e = firstError(run)
    return <div className="veil">{e && state === 'build_error' ? t('asm.trace.buildErrorLine', { line: e.line }) : veilText(run)}</div>
  }
  // Статус службы не различает as и ld: пока идёт сборка, «сейчас» горят оба.
  const [as, ld, tr] = stages
  const list = [
    { key: as, done: state === 'running', now: state === 'building' },
    { key: ld, done: state === 'running', now: state === 'building' },
    { key: tr, done: false, now: state === 'running' },
  ]
  return (
    <div className="veil">
      <div className="stages">
        {list.map((s) => (
          <div key={s.key} className={cn(s.done && 'done', s.now && 'now')}>
            <i />
            {t(`asm64.stage.${s.key}`)}
          </div>
        ))}
      </div>
    </div>
  )
}
