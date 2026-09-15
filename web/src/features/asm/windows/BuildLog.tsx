/**
 * BuildLog — лог TASM и TLINK как есть, с сообщениями-ссылками.
 *
 * Лог не пересказывается: человеку, который потом соберёт то же самое дома, в
 * аудитории или на экзамене, нужно узнать ровно эти строки. Строка
 * `**Error** prog.asm(24) …` — кнопка: щелчок ставит курсор на строку 24 и
 * открывает «Исходник», где её и править.
 */
import { useRef, type ReactNode } from 'react'

import { useAsm } from '@/features/asm/store'
import type { AsmWindowProps } from '@/features/asm/types'
import { useT } from '@/i18n'
import { cn } from '@/lib/cn'

import { firstError, traceState, useAnchorMenu, useSelectionAsk } from './format'

/** Сообщение TASM в логе: `**Error** file.asm(24) текст`, `*Warning* file.asm(7) текст`. */
const MESSAGE_LINE = /^\s*\*+\s*(error|warning|fatal)\s*\*+\s+.*?\((\d+)\)/i
/** Сообщение GNU as: `prog.s:12: Error: …`, `prog.s:7: Warning: …`. */
const GAS_LINE = /^\s*[^\s:]+\.(?:s|S|asm):(\d+):\s*(?:(error|warning|fatal error|note)\s*:)?/i

/** Строка лога — сообщение со строкой исходника? Разбор по режиму: у TASM — `**Error** file.asm(24)`, у GNU as — `file.s:24:`. */
function messageOf(line: string, tasm: boolean): { line: number; warn: boolean } | null {
  if (tasm) {
    const m = MESSAGE_LINE.exec(line)
    return m ? { line: parseInt(m[2]!, 10), warn: m[1]!.toLowerCase() === 'warning' } : null
  }
  const m = GAS_LINE.exec(line)
  return m ? { line: parseInt(m[1]!, 10), warn: /warning/i.test(m[2] ?? '') } : null
}

/** Предупреждение — кнопка того же вида, что ошибка, но цвета `--warn`. */
const WARN_STYLE = { color: 'var(--warn)' }
/** Пометка сообщения, чей номер строки — от текста до правки. */
const STALE_STYLE = { color: 'var(--muted)', fontStyle: 'italic' }

function Sys({ tone, children }: { tone?: 'ok' | 'err'; children: ReactNode }) {
  return <span className={cn('sys', tone)}>{children}</span>
}

export default function BuildLog({ active }: AsmWindowProps) {
  const t = useT()
  const asm = useAsm()
  const { run } = asm
  const tasm = asm.toolchain.id === 'tasm'
  const box = useRef<HTMLDivElement | null>(null)
  const menu = useAnchorMenu()
  const ask = useSelectionAsk({ window: 'build', active, root: box })
  const state = traceState(run)
  const build = run?.build ?? null
  const err = firstError(run)
  const errors = build?.messages.filter((m) => m.severity === 'error').length ?? 0
  const warnings = build?.messages.filter((m) => m.severity === 'warning').length ?? 0

  // Номера в логе — от текста, из которого собрано. После правки переход идёт
  // к той же строке на её новом месте, а к переписанной не идёт вовсе: курсор
  // на чужой строке хуже, чем никакой.
  const stale = asm.buildStale
  const goLine = (line: number) => {
    const now = asm.sourceLineOf(line)
    if (now == null) return
    asm.setCursorLine(now)
    asm.select({ kind: 'line', line: now })
    asm.openWindow('source', { focus: true })
  }
  const errNow = err ? asm.sourceLineOf(err.line) : null

  let meta = ''
  if (!build && (state === 'queued' || state === 'building')) meta = t('asm.build.metaBuilding')
  else if (build) {
    meta = errors ? t('asm.build.metaErrors', { n: errors }) : t('asm.build.metaOk', { sec: ((run?.totals.ms ?? 0) / 1000).toFixed(2).replace('.', ',') })
    if (warnings) meta += ' · ' + t('asm.build.metaWarnings', { n: warnings })
  }

  const link = (key: string | number, text: string, line: number, warn: boolean) => {
    const now = asm.sourceLineOf(line)
    const title =
      now == null
        ? t('asm.build.lineGone', { line })
        : stale && now !== line
          ? t('asm.build.goHintMoved', { line, now })
          : t('asm.build.goHint', { line: now })
    return (
      <span key={key}>
        <button type="button" className="bad" style={warn ? WARN_STYLE : undefined} title={title} disabled={now == null} onClick={() => goLine(line)}>
          {text}
        </button>
        {stale && (
          <span style={STALE_STYLE}>
            {'  ← '}
            {now == null ? t('asm.build.goneMark') : now !== line ? t('asm.build.movedMark', { now }) : t('asm.build.staleMark')}
          </span>
        )}
      </span>
    )
  }

  let body: ReactNode
  if (!run) body = <Sys>{t('asm.build.none')}</Sys>
  else if (!build) {
    body =
      state === 'failed' ? (
        <Sys tone="err">{run.error ?? t('asm.trace.failed')}</Sys>
      ) : (
        <>
          <Sys>{t('asm.build.building')}</Sys>
          <span className="caret" aria-hidden="true" />
        </>
      )
  } else {
    const logged = new Set<number>()
    const lines = build.log
      .replace(/\r\n?/g, '\n')
      .split('\n')
      .map((line, i) => {
        const m = messageOf(line, tasm)
        const msg = m ? null : build.messages.find((x) => x.line != null && x.text && line.includes(x.text))
        const lineNo = m ? m.line : (msg?.line ?? null)
        if (lineNo != null) {
          logged.add(lineNo)
          const warn = m ? m.warn : msg?.severity === 'warning'
          return (
            <span key={i}>
              {link(i, line, lineNo, warn)}
              {'\n'}
            </span>
          )
        }
        return (
          <span key={i} className={/^[A-Z]:\\.*>/.test(line) ? 'cmd' : undefined}>
            {line}
            {'\n'}
          </span>
        )
      })
    // Сообщения, которых в логе не нашлось текстом (например, у TLINK), — списком под логом.
    const extra = build.messages.filter((m) => m.line == null || !logged.has(m.line))
    body = (
      <>
        {lines}
        {extra.map((m, i) => (
          <span key={`m${i}`}>
            {m.line != null ? (
              link(`b${i}`, `${m.tool.toUpperCase()} (${m.line}): ${m.text}`, m.line, m.severity === 'warning')
            ) : (
              <span className={m.severity === 'warning' ? undefined : 'bad'} style={m.severity === 'warning' ? WARN_STYLE : undefined}>
                {`${m.tool.toUpperCase()}: ${m.text}`}
              </span>
            )}
            {'\n'}
          </span>
        ))}
        {build.ok ? (
          <Sys tone="ok">{state === 'running' || state === 'queued' ? t(tasm ? 'asm.build.okTracing' : 'asm64.build.okTracing') : t('asm.build.ok')}</Sys>
        ) : (
          <Sys tone="err">{t(tasm ? 'asm.build.stopped' : 'asm64.build.stopped')}</Sys>
        )}
        {run.error && (
          <>
            {'\n'}
            <Sys tone="err">{run.error}</Sys>
          </>
        )}
      </>
    )
  }

  return (
    <section className="relative flex h-full min-h-0 flex-col" aria-label={t('asm.tabs.build')}>
      <div className="pt">
        <span className="m">{meta}</span>
        {stale && (
          <span className="m truncate" style={WARN_STYLE}>
            {t('asm.build.stale')}
          </span>
        )}
        <span className="grow" />
        {err && errNow != null && (
          <button type="button" className="tb" onClick={() => goLine(err.line)}>
            {t('asm.build.toLine', { line: errNow })}
          </button>
        )}
      </div>
      <div
        ref={box}
        className="qb"
        tabIndex={0}
        onContextMenu={(e) => {
          const text = ask.current()
          if (text) menu.open(e, text)
        }}
      >
        <div className="con">{body}</div>
      </div>
      {ask.element}
      {menu.element}
    </section>
  )
}
