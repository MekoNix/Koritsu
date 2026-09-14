/**
 * TraceSlider — полоса хода по трассе: кнопки, счётчик шагов, дорожка и то,
 * что программа делает на этом шаге.
 *
 * Прогон уже записан целиком, поэтому дорожка — не перемотка процесса, а
 * выбор места в записи: тянуть можно в обе стороны. Под ней две колонки.
 * «Сейчас выполнится» — команда `step.next` с адресом CS:IP, ролью сегмента и
 * байтами; «Выполнено» — команда самого шага (`step.line`/`asm`) и что она
 * поменяла. Шаг `k` — состояние после `k`-й команды, поэтому на шаге 0
 * выполненной команды нет, а после выхода программы нет следующей.
 *
 * Метки на дорожке берутся только из загруженных страниц: ради засечек трасса
 * не догружается, они появляются по мере того, как по ней ходят.
 */
import { useMemo, type ReactNode } from 'react'

import { useAsm } from '@/features/asm/store'
import { useT } from '@/i18n'
import { cn } from '@/lib/cn'

import {
  fmtInt,
  hasTrace,
  hex,
  isDosCall,
  lastStepIndex,
  linear,
  nextOf,
  parseHex,
  segmentRole,
  skippedRange,
  spacedBytes,
  traceState,
  waitsForInput,
} from './format'
import TraceTrack from './TraceTrack'

/** Команда в одну строку: DebugX разделяет мнемонику и операнды несколькими пробелами. */
const oneLine = (s: string) => s.replace(/\s+/g, ' ').trim()

export default function TraceSlider() {
  const t = useT()
  const asm = useAsm()
  const { run, step, stepIndex, settings, loadedSteps } = asm

  const trace = hasTrace(run)
  const total = lastStepIndex(run)
  const gap = trace ? skippedRange(run) : null
  const next = trace ? nextOf(step) : null
  const atEnd = trace && stepIndex >= total
  const exited = run?.status === 'done' && run.totals.exit_code != null
  const code = run?.totals.exit_code ?? '—'
  const waiting = waitsForInput(run)

  const marks = useMemo(() => {
    const breakpoints: number[] = []
    const dosCalls: number[] = []
    if (!trace) return { breakpoints, dosCalls }
    // Точка останова — там, где остановится F9: шаг, у которого следующей стоит строка с точкой.
    const bps = new Set(settings.breakpoints)
    for (const s of loadedSteps()) {
      if (s.next?.line != null && bps.has(s.next.line)) breakpoints.push(s.i)
      if (s.i > 0 && isDosCall(s.asm)) dosCalls.push(s.i)
    }
    return { breakpoints, dosCalls }
  }, [trace, loadedSteps, settings.breakpoints])

  // ── счётчик ──
  let note: string | null = null
  let noteTone: 'ok' | 'warn' | null = null
  if (trace && stepIndex === 0) note = t('asm.slider.beforeFirst')
  else if (atEnd) {
    noteTone = 'warn'
    if (waiting) note = run?.error ?? t('asm.slider.waitInput')
    else if (exited) {
      note = t('asm.slider.exited', { code })
      noteTone = 'ok'
    } else if (run?.status === 'step_limit') note = t('asm.slider.cut')
    else note = run?.error ?? t('asm.slider.stopped')
  }

  // ── сейчас выполнится ──
  let now: ReactNode
  if (!trace) {
    const state = traceState(run)
    const text =
      state === 'build_error'
        ? t('asm.slider.buildError')
        : state === 'queued' || state === 'building' || state === 'running'
          ? t('asm.slider.writing')
          : state === 'failed'
            ? (asm.run?.error ?? t('asm.trace.failed'))
            : t('asm.slider.none')
    now = (
      <div className="cmd">
        <span className="cmd-main is-quiet" title={text}>
          {text}
        </span>
      </div>
    )
  } else if (!step) {
    now = (
      <div className="cmd">
        <span className="cmd-main is-quiet">{t('asm.slider.loading')}</span>
      </div>
    )
  } else if (next) {
    const cs = parseHex(next.cs)
    const ip = parseHex(next.ip)
    const addr = cs != null && ip != null ? `${hex(cs)}:${hex(ip)}` : `${next.cs}:${next.ip}`
    const role = cs != null ? segmentRole(run, cs) : null
    const roleText = role ? t(`asm.slider.seg.${role}`) : null
    const phys = cs != null && ip != null ? `${hex(linear({ seg: cs, off: ip }), 5)}h` : null
    const mnem = oneLine(next.asm)
    const lineText = next.line != null ? t('asm.slider.line', { line: next.line }) : t('asm.slider.noLine')
    const bytes = next.bytes ? t('asm.slider.bytes', { bytes: spacedBytes(next.bytes) }) : null
    const addrText = `${t('asm.slider.addrLabel')} ${addr}${roleText ? ` — ${roleText}` : ''}`
    now = (
      <div className="cmd is-now">
        <CmdMain line={next.line} title={`${t('asm.slider.now')} ${lineText} · ${mnem}`}>
          <span className="lbl">{t('asm.slider.now')}</span> <b>{lineText}</b> · <code>{mnem}</code>
        </CmdMain>
        <div className="cmd-sub" title={[addrText, bytes].filter(Boolean).join(' · ')}>
          <span className="addr" title={phys ? t('asm.slider.addrHint', { phys }) : undefined}>
            {t('asm.slider.addrLabel')} <span className="m">{addr}</span>
            {roleText && ` — ${roleText}`}
          </span>
          {bytes && (
            <>
              {' · '}
              <span className="m">{bytes}</span>
            </>
          )}
        </div>
      </div>
    )
  } else {
    const head = exited ? t('asm.slider.exitedNow') : waiting ? t('asm.slider.waitInputNow') : t('asm.slider.stoppedNow')
    const tail = exited ? t('asm.slider.exitCode', { code }) : null
    now = (
      <div className="cmd is-now">
        <span className="cmd-main" title={tail ? `${head} · ${tail}` : head}>
          <b>{head}</b>
          {tail && (
            <>
              {' · '}
              <code>{tail}</code>
            </>
          )}
        </span>
      </div>
    )
  }

  // ── выполнено ──
  let done: ReactNode = null
  if (trace && step && stepIndex > 0 && step.asm.trim()) {
    const mnem = oneLine(step.asm)
    const lineText = step.line != null ? t('asm.slider.line', { line: step.line }) : t('asm.slider.noLine')
    const list = [...step.changed.map((x) => x.toUpperCase()), ...(step.mem.length ? [t('asm.slider.memory')] : [])]
    const change =
      list.length === 0
        ? null
        : step.changed.length === 0
          ? t('asm.slider.memOnly')
          : t(list.length === 1 ? 'asm.slider.changedOne' : 'asm.slider.changed', { list: list.join(', ') })
    done = (
      <div className="cmd is-done">
        <CmdMain line={step.line} title={[`${t('asm.slider.done')} ${lineText}`, mnem, change].filter(Boolean).join(' · ')}>
          <span className="lbl">{t('asm.slider.done')}</span> {lineText} · <code>{mnem}</code>
          {change && <span className="chg"> · {change}</span>}
        </CmdMain>
      </div>
    )
  }

  const valueText =
    t('asm.slider.valueText', { k: fmtInt(stepIndex), n: fmtInt(total) }) +
    (next?.line != null ? `, ${t('asm.slider.line', { line: next.line })}` : '')

  return (
    <div className="scrub">
      <div className="scrub-row">
        <div className="nav" role="group" aria-label={t('asm.slider.nav')}>
          <NavButton tip={t('asm.slider.toStart')} align="start" disabled={!trace} onClick={asm.toStart}>
            <rect x="2" y="3" width="2" height="10" />
            <path d="M14 3v10L5 8z" />
          </NavButton>
          <NavButton tip={t('asm.slider.back')} disabled={!trace} onClick={asm.stepBack}>
            <path d="M12 3v10L4 8z" />
          </NavButton>
          <NavButton tip={t('asm.slider.step')} disabled={!trace} onClick={asm.stepOver}>
            <path d="M4 3v10l8-5z" />
          </NavButton>
          <NavButton tip={t('asm.slider.run')} disabled={!trace} onClick={asm.runToBreakpoint}>
            <path d="M1.5 3v10l8-5z" />
            <circle cx="12.5" cy="8" r="2.5" />
          </NavButton>
        </div>
        <span className="stepno">
          <span>{t('asm.slider.stepWord')}</span>
          <b className="k">{trace ? fmtInt(stepIndex) : '—'}</b>
          {trace && (
            <>
              <span>{t('asm.slider.of')}</span>
              <b className="k">{fmtInt(total)}</b>
            </>
          )}
          {note && (
            <span className={cn('note', noteTone && `is-${noteTone}`)} title={note}>
              {note}
            </span>
          )}
        </span>
        <TraceTrack
          value={trace ? stepIndex : 0}
          total={total}
          disabled={!trace}
          gap={gap}
          breakpoints={marks.breakpoints}
          dosCalls={marks.dosCalls}
          exit={trace && exited ? total : null}
          label={t('asm.slider.aria')}
          valueText={valueText}
          gapText={gap ? t('asm.slider.gap', { n: fmtInt(gap[1] - gap[0]) }) : null}
          onChange={asm.goto}
        />
        <div className="nav">
          <NavButton tip={t('asm.slider.toEnd')} align="end" disabled={!trace} onClick={asm.toEnd}>
            <path d="M2 3v10l9-5z" />
            <rect x="12" y="3" width="2" height="10" />
          </NavButton>
        </div>
      </div>
      <div className="scrub-info">
        {now}
        {done}
      </div>
    </div>
  )
}

/** Кнопка хода с подсказкой: подпись и клавиша — во всплывающей подсказке и в `aria-label`. */
function NavButton({
  tip,
  align,
  disabled,
  onClick,
  children,
}: {
  tip: string
  /** К какому краю кнопки прижать подсказку: у краёв полосы по центру она бы обрезалась. */
  align?: 'start' | 'end'
  disabled: boolean
  onClick(): void
  children: ReactNode
}) {
  return (
    <button type="button" disabled={disabled} onClick={onClick} aria-label={tip} data-tip={tip} data-tip-align={align}>
      <svg viewBox="0 0 16 16" aria-hidden="true">
        {children}
      </svg>
    </button>
  )
}

/**
 * Первая строка команды. Номер строки — от текста сборки: если в нынешнем
 * исходнике она нашлась, строка — кнопка, ведущая к ней в «Исходник».
 */
function CmdMain({ line, title, children }: { line: number | null; title: string; children: ReactNode }) {
  const t = useT()
  const asm = useAsm()
  const target = line == null ? null : asm.sourceLineOf(line)
  if (target == null) {
    return (
      <span className="cmd-main" title={title}>
        {children}
      </span>
    )
  }
  const go = () => {
    asm.setCursorLine(target)
    asm.select({ kind: 'line', line: target })
    asm.openWindow('source', { focus: true })
  }
  return (
    <button type="button" className="cmd-main" title={`${title}\n${t('asm.slider.toSource', { line: target })}`} onClick={go}>
      {children}
    </button>
  )
}
