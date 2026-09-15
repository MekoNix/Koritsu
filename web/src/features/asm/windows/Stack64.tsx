/**
 * Stack64 — стек Windows x64 словами по 8 байт вокруг RSP.
 *
 * Разметка — по трассе, а не по догадке: трасса знает каждый `call` и `push`,
 * поэтому у слова в стеке есть происхождение — «адрес возврата → стр. 32 ·
 * call hextochar», «сохранённый RBP · шаг 1». Если слот с тех пор перезаписан,
 * так и сказано.
 *
 * Кадры RBP разделены чертой с заголовком «кадр hextochar · RBP = …»: цепочка
 * идёт от RBP по сохранённым значениям. Кадра нет — просто слова.
 *
 * Перед `call` в API окно показывает параметры по соглашению Microsoft x64:
 * RCX, RDX, R8, R9 и `[RSP+32]…` с именами из сигнатуры (`WriteFile`: hFile,
 * lpBuffer, …), а 32 байта над RSP подписаны как shadow space. Это проверка «так
 * ли положил» до того, как нажал F8.
 *
 * Строки выровнены по 8 байт. Когда RSP встаёт посреди слова — `pop bp` вместо
 * `pop rbp` снимает два байта, — метка RSP стоит внутри слова, а сверху
 * горит предупреждение: стек съехал, и `ret` возьмёт мусор.
 */
import { useEffect, useMemo, useState, type KeyboardEvent, type ReactNode } from 'react'

import { useAsm } from '@/features/asm/store'
import type { AsmStep, AsmWindowProps } from '@/features/asm/types'
import { useT } from '@/i18n'
import { cn } from '@/lib/cn'

import {
  bigToNum,
  callArgs,
  flatImage,
  flatLoad,
  hex16,
  hexOf,
  isCallText,
  isRetText,
  pendingCall,
  readLE,
  readText,
  regNum,
  signed,
  stackOriginsFor,
  symbolAt,
  symbolize,
  type CallArg,
  type FlatImage,
  type StackOrigin,
} from './flat'
import {
  fmtInt,
  hasTrace,
  isMenuKey,
  menuPointOf,
  sameAnchor,
  skippedRange,
  useAnchorMenu,
  useFlatFetch,
  useMemView,
  veilText,
} from './format'
import { SHADOW_SPACE } from './winapi'
import './windows64.css'

/** Сколько слов показывать ниже RSP (след) и выше (стек). */
const BELOW = 6
const ABOVE = 24
/** Дальше этого окно не растягивается, даже если кадр RBP выше. */
const MAX_ABOVE = 0x200

export default function Stack64({ active }: AsmWindowProps) {
  const t = useT()
  const asm = useAsm()
  const { run, step, prevStep, stepIndex, view, selection, programId, getStep } = asm
  const menu = useAnchorMenu()
  const { mem, scan } = useMemView(active)
  const trace = hasTrace(run)
  const st = trace ? step : undefined
  const img = useMemo(() => flatImage(run), [run])
  const load = flatLoad(run)
  const dec = view.radix === 'dec'
  const get = (a: number) => mem.get(a)

  const rsp = regNum(st, 'rsp')
  const rbp = regNum(st, 'rbp')
  const prevRsp = trace && stepIndex > 0 ? regNum(prevStep, 'rsp') : null

  // Происхождение слов: разбор трассы до текущего шага, по кадру за раз.
  const origins = run && trace ? stackOriginsFor(programId, run, skippedRange(run)) : null
  const [, setTick] = useState(0)
  useEffect(() => {
    if (!origins || !active) return
    if (origins.advance(getStep, stepIndex)) {
      const id = requestAnimationFrame(() => setTick((n) => n + 1))
      return () => cancelAnimationFrame(id)
    }
    return undefined
  })
  const originsReady = !!origins && origins.scanned > stepIndex

  const grid = rsp == null ? null : Math.floor(rsp / 8) * 8
  const odd = rsp == null || grid == null ? 0 : rsp - grid
  const start = grid == null ? 0 : Math.max(0, grid - BELOW * 8)
  let end = grid == null ? 0 : grid + ABOVE * 8
  if (grid != null && rbp != null && rbp >= grid && rbp + 16 <= grid + MAX_ABOVE) end = Math.max(end, Math.ceil((rbp + 16) / 8) * 8)

  // Неизвестные байты выше RSP — дочитать.
  let unknownAt: number | null = null
  if (trace && grid != null) {
    for (let a = grid; a < end; a++) {
      if (mem.get(a) == null) {
        unknownAt = Math.floor(a / 8) * 8
        break
      }
    }
  }
  const fetchState = useFlatFetch({ active: active && trace, scan, from: unknownAt, len: unknownAt == null ? 0 : end - unknownAt })

  const next = getStep(stepIndex + 1)
  const pc = st ? pendingCall(st, next, img) : null
  const args = pc?.fn && st ? callArgs(pc.fn, st, get) : []
  const beforeCall = isCallText(st?.next?.asm)

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (!isMenuKey(e) || selection?.kind !== 'cell' || selection.seg != null) return
    const el = e.currentTarget.querySelector(`[data-cell="${selection.off}"]`)
    if (!el) return
    e.preventDefault()
    e.stopPropagation()
    menu.open(menuPointOf(el), selection)
  }

  /* кадры по цепочке RBP */
  const originMap = origins && grid != null ? origins.inRange(start, end, stepIndex) : new Map<number, StackOrigin>()
  const frames = new Map<number, string | null>()
  if (grid != null && rbp != null) {
    let fp: number | null = rbp
    let level = 0
    while (fp != null && fp >= grid && fp < end && level < 8 && !frames.has(fp)) {
      const retOrigin = originMap.get(fp + 8)
      let name: string | null = null
      if (retOrigin?.kind === 'ret' && retOrigin.target != null) name = symbolize(img, retOrigin.target)
      else if (level === 0) {
        const rip = regNum(st, 'rip')
        name = rip == null ? null : symbolize(img, rip)
      }
      frames.set(fp, name ? name.replace(/\+.*$/, '') : null)
      const saved = bigToNum(readLE(get, fp, 8))
      fp = saved != null && saved > fp ? saved : null
      level++
    }
  }

  /* предупреждения */
  const warnings: string[] = []
  if (st && rsp != null && odd !== 0) warnings.push(t('asm64.stack.misaligned', { rsp: hex16(rsp), n: odd, asm: st.asm.trim() || '—' }))
  if (st && rsp != null && beforeCall && rsp % 16 !== 0 && odd === 0) warnings.push(t('asm64.stack.alignCall', { n: rsp % 16 }))
  if (st && rsp != null && isRetText(st.next?.asm) && originsReady && rsp !== load?.rsp) {
    const top = originMap.get(rsp) ?? origins?.at(rsp, stepIndex) ?? null
    const value = readLE(get, rsp, 8)
    if (value != null && !(top?.kind === 'ret' && top.value === value)) warnings.push(t('asm64.stack.retWrong', { value: hexOf(value, 16) }))
  }

  const rows: ReactNode[] = []
  if (st && grid != null && rsp != null) {
    const rspRow = (
      <div key="rsp" className="st st64 sprow">
        <span className="sa">{hex16(rsp)}</span>
        <span className="sv">{t('asm64.stack.rspMark')}</span>
        <span className="sn">{odd ? t('asm64.stack.rspMarkOdd', { rsp: hex16(rsp) }) : ''}</span>
      </div>
    )
    let rspShown = false
    for (let a = start; a < end; a += 8) {
      if (!rspShown && a + 8 > rsp) {
        rows.push(rspRow)
        rspShown = true
      }
      if (frames.has(a)) {
        const name = frames.get(a)
        rows.push(
          <div key={`f${a}`} className="st st64 sthead">
            <span>{name ? t('asm64.stack.frame', { name, rbp: hex16(a) }) : t('asm64.stack.frameNoName', { rbp: hex16(a) })}</span>
          </div>,
        )
      }
      const value = readLE(get, a, 8)
      const dead = a + 8 <= rsp
      const partial = a < rsp && a + 8 > rsp
      const written = [0, 1, 2, 3, 4, 5, 6, 7].some((j) => mem.written.has(a + j))
      const changed = [0, 1, 2, 3, 4, 5, 6, 7].some((j) => mem.changed.has(a + j))
      const rel = a - rsp
      const shadow = !!pc?.api && beforeCall && odd === 0 && rel >= 0 && rel < SHADOW_SPACE
      const arg = pc?.api && beforeCall && odd === 0 ? args.find((x) => x.slot === a) : undefined
      const origin = originMap.get(a)
      const notes: ReactNode[] = []
      if (a === rbp) notes.push(<span key="rbp" className="is-rbp">{t('asm64.stack.rbpMark')}</span>)
      if (shadow)
        notes.push(
          <span key="sh" className="is-shadow" title={t('asm64.stack.shadowHint')}>
            {t('asm64.stack.shadow', { off: rel })}
          </span>,
        )
      if (arg) notes.push(<span key="arg" className="is-arg">{`${t('asm64.stack.arg', { name: arg.param.name, n: arg.index + 1 })} ${argText(arg, img, get, t)}`}</span>)
      if (origin) notes.push(originNote(origin, value, t, img))
      else if (!dead && load?.rsp != null && a === load.rsp) notes.push(<span key="entry">{t('asm64.stack.entryRet')}</span>)
      if (dead && notes.length === 0) notes.push(<span key="dead">{written ? t('asm64.stack.trace') : t('asm64.stack.free')}</span>)
      const h = hex16(a)
      const anchor = { kind: 'cell', seg: null, off: h } as const
      rows.push(
        <div
          key={a}
          data-cell={h}
          className={cn(
            'st st64',
            dec && 'dec',
            dead && 'dead',
            partial && 'odd',
            written && 'res',
            changed && 'chg',
            shadow && 'shadow',
            sameAnchor(selection, anchor) && 'is-ctx',
          )}
          onClick={() => asm.select(anchor)}
          onContextMenu={(e) => menu.open(e, anchor)}
        >
          <span className="sa">
            <span className="hi">{h.slice(0, 8)}</span>
            {h.slice(8)}
          </span>
          <span className="sv">{value == null ? '·'.repeat(16) : dec ? value.toString() : hexOf(value, 16)}</span>
          <span className="sn">
            {notes.map((n, i) => (
              <span key={i}>
                {i > 0 && ' · '}
                {n}
              </span>
            ))}
          </span>
        </div>,
      )
    }
    if (!rspShown) rows.push(rspRow)
  }

  const delta = rsp != null && prevRsp != null ? rsp - prevRsp : 0
  const veil = veilText(run)

  return (
    <section className="relative flex h-full min-h-0 flex-col" aria-label={t('asm.tabs.stack')}>
      <div className="pt">
        {st && rsp != null && (
          <>
            <span className="m">{t('asm64.stack.meta', { rsp: hex16(rsp), rbp: rbp == null ? '—' : hex16(rbp) })}</span>
            {load?.rsp != null && load.rsp >= rsp && <span className="m">{t('asm64.stack.depth', { n: fmtInt(load.rsp - rsp) })}</span>}
            {delta !== 0 && <span className="m text-warn">{t(delta < 0 ? 'asm64.stack.pushed' : 'asm64.stack.popped', { n: Math.abs(delta) })}</span>}
          </>
        )}
        {fetchState === 'loading' && <span className="m">{t('asm64.dump.fetching', { step: stepIndex })}</span>}
        {fetchState === 'error' && <span className="m bad">{t('asm64.dump.fetchError')}</span>}
      </div>
      {warnings.map((w) => (
        <div key={w} className="s64-warn" role="status">
          {w}
        </div>
      ))}
      {pc?.api && pc.fn && st && <CallArgs name={pc.fn.name} args={args} step={st} img={img} get={get} />}
      <div className="qb" tabIndex={0} onKeyDown={onKeyDown}>
        {rows}
        {rows.length > 0 && <div className="snote">{t('asm64.stack.note')}</div>}
      </div>
      {veil && <div className="veil">{veil}</div>}
      {menu.element}
    </section>
  )
}

type T = ReturnType<typeof useT>

/** Подпись слова по тому, кто его положил. */
function originNote(o: StackOrigin, value: bigint | null, t: T, img: FlatImage): ReactNode {
  if (o.kind === 'ret') {
    if (o.value != null && value != null && o.value !== value) return <span key="o" className="is-warn">{t('asm64.stack.retStale', { step: o.step })}</span>
    const target = (o.target != null ? symbolize(img, o.target) : null) ?? (o.target != null ? hex16(o.target) : '?')
    return (
      <span key="o" className="is-ret">
        {o.line != null ? t('asm64.stack.ret', { line: o.line, target }) : t('asm64.stack.retNoLine', { target })}
      </span>
    )
  }
  if (o.kind === 'rbp') return <span key="o">{t('asm64.stack.savedRbp', { step: o.step })}</span>
  return <span key="o">{t('asm64.stack.push', { asm: o.asm, step: o.step })}</span>
}

/** Значение параметра по его роли: строка буфера, число, символ под адресом. */
function argText(a: CallArg, img: FlatImage, get: (addr: number) => number | null, t: T): string {
  const v = a.value
  if (v == null) return '?'
  const num = bigToNum(v)
  switch (a.param.role) {
    case 'buffer': {
      const s = num == null ? null : readText(get, num, 24)
      const sym = num == null ? null : symbolAt(img, num)?.sym.name
      return [sym ? t('asm64.stack.symbol', { name: sym }) : null, s?.text ? t('asm64.stack.text', { text: s.text }) : null].filter(Boolean).join(' ')
    }
    case 'outCount': {
      const sym = num == null ? null : symbolAt(img, num)?.sym.name
      return sym ? t('asm64.stack.symbol', { name: sym }) : ''
    }
    case 'count':
    case 'reserved':
      return t('asm64.stack.dec', { n: v.toString() })
    default:
      return t('asm64.stack.dec', { n: signed(v, a.param.size * 8).toString() })
  }
}

/** Параметры вызова API перед `call`: регистры и слоты стека с именами из сигнатуры. */
function CallArgs({
  name,
  args,
  step,
  img,
  get,
}: {
  name: string
  args: CallArg[]
  step: AsmStep
  img: FlatImage
  get: (addr: number) => number | null
}) {
  const t = useT()
  const rsp = regNum(step, 'rsp')
  if (args.length === 0) return <div className="s64-args"><div className="ah">{t('asm64.stack.argsNone', { name })}</div></div>
  return (
    <div className="s64-args">
      <div className="ah">{t('asm64.stack.argsHead', { name })}</div>
      {args.map((a) => (
        <div key={a.index} className="ar">
          <span>{a.reg ? a.reg.toUpperCase() : `[RSP+${a.slot != null && rsp != null ? a.slot - rsp : '?'}]`}</span>
          <span>{a.value == null ? '·'.repeat(a.param.size * 2) : hexOf(a.value, a.param.size * 2)}</span>
          <span title={a.param.note}>{`${a.param.name} ${argText(a, img, get, t)}`}</span>
        </div>
      ))}
    </div>
  )
}
