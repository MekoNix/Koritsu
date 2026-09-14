/**
 * Output — что программа вывела к текущему шагу.
 *
 * Вывод склеивается из шагов трассы (`step.out`), поэтому ходьба назад по
 * трассе стирает его обратно: на шаге 12 видно ровно то, что было на экране
 * DOS после двенадцатой команды. То, что программа выведет дальше, показано
 * бледно после курсора — так видно, к чему идёт программа, и не спутать с уже
 * случившимся.
 *
 * Если трасса оборвана по лимиту, середины у неё нет — и вывода середины тоже;
 * на месте дырки стоит отметка, а не склейка начала с концом.
 */
import { useEffect, useRef, type ReactNode } from 'react'

import { useAsm } from '@/features/asm/store'
import type { AsmWindowProps } from '@/features/asm/types'
import { useT } from '@/i18n'
import { cn } from '@/lib/cn'

import { fmtInt, lastStepIndex, traceState, useAnchorMenu, useSelectionAsk, useTraceScan, visibleChar, waitsForInput } from './format'

/** До скольких шагов вывод читается до конца — чтобы показать будущий. */
const FULL_LIMIT = 20_000
/** Сколько последних символов прошлого вывода рисовать; выше — отметка «ещё N». */
const TAIL_CHARS = 20_000
/** Сколько символов будущего вывода рисовать. */
const FUTURE_CHARS = 4_000

function Sys({ tone, children }: { tone?: 'ok' | 'err'; children: ReactNode }) {
  return <span className={cn('sys', tone)}>{children}</span>
}

export default function Output({ active }: AsmWindowProps) {
  const t = useT()
  const asm = useAsm()
  const { run, step, stepIndex } = asm
  const total = lastStepIndex(run)
  const scan = useTraceScan(total <= FULL_LIMIT ? 'end' : 'current', active)
  const caret = useRef<HTMLSpanElement | null>(null)
  const state = traceState(run)
  const box = useRef<HTMLDivElement | null>(null)
  const menu = useAnchorMenu()
  const ask = useSelectionAsk({ window: 'output', active, root: box })

  const known = !!scan && stepIndex < scan.scanned
  const cut = scan ? (known ? (scan.outLen[stepIndex] ?? 0) : scan.out.length) : 0

  useEffect(() => {
    caret.current?.scrollIntoView({ block: 'nearest' })
  }, [cut, stepIndex])

  let body: ReactNode
  let summary: ReactNode = null

  if (state !== 'ready' || !scan || !run) {
    if (state === 'build_error')
      body = (
        <>
          <Sys>{t('asm.output.buildError')}</Sys>{' '}
          <button type="button" className="asm-linkbtn" onClick={() => asm.openWindow('build', { focus: true })}>
            {t('asm.output.openBuild')}
          </button>
        </>
      )
    else if (state === 'queued' || state === 'building' || state === 'running') body = <Sys>{t('asm.output.building')}</Sys>
    else if (state === 'failed') body = <Sys tone="err">{run?.error ?? t('asm.trace.failed')}</Sys>
    else body = <Sys>{t('asm.output.none')}</Sys>
  } else {
    const from = Math.max(0, cut - TAIL_CHARS)
    const gap = scan.outGap && scan.outGap.at <= cut && scan.outGap.at >= from ? scan.outGap : null
    const atEnd = stepIndex >= total
    const future = scan.complete && !atEnd ? scan.out.slice(cut, cut + FUTURE_CHARS) : ''

    let tail: ReactNode = null
    if (!known) tail = <Sys>{t('asm.output.loading')}</Sys>
    else if (!atEnd) tail = null
    else if (waitsForInput(run)) tail = <Sys tone="err">{t('asm.output.waitInput')}</Sys>
    else if (run.status === 'done') tail = <Sys tone="ok">{t('asm.output.exited', { code: run.totals.exit_code ?? '—' })}</Sys>
    else if (run.status === 'step_limit') tail = <Sys tone="err">{t('asm.output.limit', { n: fmtInt(run.step_limit) })}</Sys>
    else if (run.status === 'timeout') tail = <Sys tone="err">{run.error ?? t('asm.output.timeout')}</Sys>
    else tail = <Sys tone="err">{run.error ?? t('asm.output.crashed')}</Sys>

    body = (
      <>
        {from > 0 && (
          <>
            <Sys>{t('asm.output.above', { n: fmtInt(from) })}</Sys>
            {'\n'}
          </>
        )}
        {gap ? (
          <>
            {scan.out.slice(from, gap.at)}
            {'\n'}
            <Sys>{t('asm.output.gap', { n: fmtInt(gap.steps) })}</Sys>
            {'\n'}
            {scan.out.slice(gap.at, cut)}
          </>
        ) : (
          scan.out.slice(from, cut)
        )}
        {!atEnd && <span ref={caret} className="caret" aria-hidden="true" />}
        {future && <span className="fut">{future}</span>}
        {tail && (
          <>
            {'\n'}
            <span ref={atEnd ? caret : undefined}>{tail}</span>
          </>
        )}
      </>
    )

    if (run.status === 'step_limit')
      summary = (
        <div className="summary">
          <b>{t('asm.output.limitHead', { n: fmtInt(run.step_limit) })}</b> {t('asm.output.limitText')}
        </div>
      )
    else if (atEnd && waitsForInput(run))
      summary = (
        <div className="summary" title={run.error ?? undefined}>
          <b>{t('asm.output.waitInputHead')}</b> {t('asm.output.waitInput')}
        </div>
      )
    else if (atEnd && run.status === 'done')
      summary = (
        <div className="summary ok">
          <b>{t('asm.output.doneHead', { code: run.totals.exit_code ?? '—' })}</b>{' '}
          {t('asm.output.doneText', { steps: fmtInt(run.totals.steps), sec: (run.totals.ms / 1000).toFixed(2).replace('.', ',') })}
        </div>
      )
  }

  const stdin = run?.stdin ?? ''
  const meta = run
    ? stdin
      ? t('asm.output.stdinMeta', {
          stdin: [...stdin.slice(0, 24)].map(visibleChar).join('') + (stdin.length > 24 ? '…' : ''),
          read: Math.min(step?.stdin_pos ?? 0, stdin.length),
          total: stdin.length,
        })
      : t('asm.output.stdinEmpty')
    : ''

  return (
    <section className="relative flex h-full min-h-0 flex-col" aria-label={t('asm.tabs.output')}>
      <div className="pt">
        <span className="m truncate">{meta}</span>
      </div>
      <div
        ref={box}
        className="qb"
        tabIndex={0}
        aria-live="polite"
        onContextMenu={(e) => {
          const text = ask.current()
          if (text) menu.open(e, text)
        }}
      >
        {summary}
        <div className="con">{body}</div>
      </div>
      {ask.element}
      {menu.element}
    </section>
  )
}
