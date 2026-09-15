/**
 * Agent — окно «Агент»: переписка о программе и её трассе.
 *
 * ── Вопрос всегда о чём-то ──────────────────────────────────────────────────
 *
 * С каждым сообщением уезжает якорь — то, что выделено в окнах отладчика
 * (строка, регистр, флаг, ячейка, запись справки), — номер шага и номер
 * прогона. Агент отвечает по цифрам трассы на этом шаге, и без якоря «почему
 * тут 0» не о чем было бы спросить. Ничего не выделено — якорь текущая строка
 * трассы (команда, которая выполнится следующей), а без трассы — прогон целиком.
 * Чип над перепиской показывает якорь до отправки, у отправленных сообщений —
 * тот, с которым они ушли.
 *
 * ── Переписка лежит у службы ────────────────────────────────────────────────
 *
 * Сообщения приходят запросом, а не копятся в окне: закрытая и открытая заново
 * вкладка, другой браузер и перезагрузка показывают один разговор. Окно держит
 * у себя только отправленное и ещё не записанное сообщение — оно стоит в конце,
 * пока не приедет запись с ответом.
 *
 * ── Платно — только по нажатию ──────────────────────────────────────────────
 *
 * Сообщение агенту стоит денег, поэтому само оно не уходит никогда: быстрый
 * вопрос и «Отправить» — нажатия человека, `askAgent` с готовым текстом — тоже.
 * `askAgent` без текста только подставляет вопрос по якорю в поле. Пока ответ
 * идёт, на месте «Отправить» — «Остановить»: два одновременных вопроса — это два
 * списания и два ответа, из которых прочтут один.
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'

import { ApiError, errorSaid, errorText } from '@/api'
import { useJobStream } from '@/api/hooks'
import { useCancelJob } from '@/features/agent/data'
import { plural } from '@/features/projects/format'
import { useDefaultEndpoint } from '@/features/reports/data'
import { useT } from '@/i18n'
import { cn } from '@/lib/cn'
import { Icon, Spinner } from '@/ui'

import { asmKeys, useAsmChat, usePostAsmChat, type AsmChatMessage, type AsmChatSend } from '../api'
import { entryById } from '../docs/lookup'
import { useDocEntries } from '../docs/useDocEntries'
import { useAsm } from '../store'
import { regHex, type AsmAnchor, type AsmRunSummary, type AsmStep, type AsmWindowProps } from '../types'
import { apiShortName, winapi } from './winapi'

type T = ReturnType<typeof useT>

/** Что подписи якоря и вопросы берут из режима программы. */
interface AnchorCtx {
  /** Заголовок записи справки по id; набор ещё не загружен — сам id. */
  docName(id: string): string
  /** Имя регистра флагов в шаге: `flags` у TASM, `rflags` у MinGW x64. */
  flagsReg: string
}

/** Кадр потока задания с куском ответа. */
const EV_TEXT = 'text'

/**
 * Последний обработанный `agentRequest.seq` по программам.
 *
 * Снаружи компонента: док перемонтирует окно, когда вкладку перетаскивают в
 * другую группу, и счётчик в состоянии окна забылся бы — старый запрос с
 * текстом ушёл бы агенту второй раз и второй раз был бы оплачен.
 */
const handledSeq = new Map<string, number>()

/* ── якорь ───────────────────────────────────────────────────────────────── */

const FLAG_BIT: Record<string, number> = { of: 11, df: 10, if: 9, tf: 8, sf: 7, zf: 6, af: 4, pf: 2, cf: 0 }

function flagValue(step: AsmStep | undefined, name: string, flagsReg: string): number | null {
  const bit = FLAG_BIT[name.toLowerCase()]
  const hex = regHex(step, flagsReg)
  if (hex === undefined || bit === undefined) return null
  const flags = parseInt(hex, 16)
  return Number.isNaN(flags) ? null : (flags >> bit) & 1
}

/** Адрес ячейки якоря: `сегмент:смещение` у TASM, одно смещение в плоской памяти. */
function cellAddr(a: { seg: string | null; off: string }): string {
  return a.seg ? `${a.seg}:${a.off}` : a.off
}

function anchorLabel(t: T, ctx: AnchorCtx, a: AsmAnchor | null, step: number | null, runNo: number | null): string {
  if (!a) return t('asm.agent.anchor.none')
  switch (a.kind) {
    case 'line':
      return step !== null
        ? t('asm.agent.anchor.lineStep', { line: a.line, step })
        : t('asm.agent.anchor.line', { line: a.line })
    case 'register':
      return t('asm.agent.anchor.register', { name: a.name.toUpperCase() })
    case 'flag':
      return t('asm.agent.anchor.flag', { name: a.name.toUpperCase() })
    case 'cell':
      return t('asm.agent.anchor.cell', { addr: cellAddr(a) })
    case 'doc':
      return t('asm.agent.anchor.doc', { name: ctx.docName(a.id) })
    case 'run':
      return runNo !== null ? t('asm.agent.anchor.runNo', { n: runNo }) : t('asm.agent.anchor.run')
    case 'text': {
      if (a.line_from !== null && a.line_to !== null)
        return a.line_from === a.line_to
          ? t('asm.agent.anchor.textLine', { line: a.line_from })
          : t('asm.agent.anchor.textLines', { from: a.line_from, to: a.line_to })
      const n = a.text.length
      return t('asm.agent.anchor.textFrom', {
        where: t(`asm.agent.anchor.where.${a.window}`),
        n: n.toLocaleString('ru-RU'),
        chars: plural(n, [t('asm.agent.anchor.chars.one'), t('asm.agent.anchor.chars.few'), t('asm.agent.anchor.chars.many')]),
      })
    }
  }
}

/** Подсказка чипа: у выделения — сам выделенный текст. */
function anchorTitle(a: AsmAnchor | null): string | undefined {
  return a?.kind === 'text' ? a.text : undefined
}

/** Вопрос по якорю словами — для поля ввода и быстрых вопросов. */
function questionFor(t: T, ctx: AnchorCtx, a: AsmAnchor | null, step: AsmStep | undefined): string {
  if (!a) return ''
  switch (a.kind) {
    case 'line':
      return t('asm.agent.ask.line', { line: a.line })
    case 'register':
      return t('asm.agent.ask.register', { name: a.name.toUpperCase() })
    case 'flag': {
      const v = flagValue(step, a.name, ctx.flagsReg)
      return v === null
        ? t('asm.agent.ask.flagAny', { name: a.name.toUpperCase() })
        : t('asm.agent.ask.flag', { name: a.name.toUpperCase(), value: v })
    }
    case 'cell':
      return t('asm.agent.ask.cell', { addr: cellAddr(a) })
    case 'doc':
      return t('asm.agent.ask.doc', { name: ctx.docName(a.id) })
    case 'run':
      return t('asm.agent.ask.run')
    case 'text':
      return t('asm.agent.ask.text')
  }
}

type Quick = { key: string; label: string; text: string }

/**
 * Функция kernel32, о которой уместно спросить на этом шаге: та, что вызовется
 * следующей командой (строка исходника `call WriteFile`), а если нет — та, что
 * вызвал сам шаг (`step.call`). Строка берётся из исходника прогона: адрес
 * переходника в дизассемблере имени функции не несёт.
 */
function apiOf(step: AsmStep, source: string | null | undefined): string | null {
  const line = step.next?.line
  const text = line != null && source ? source.split('\n')[line - 1] : step.next?.asm
  const m = /^\s*(?:[\w.$]+:\s*)?call\s+(?:qword\s+ptr\s+\[rip\+)?([A-Za-z_][\w@]*)/i.exec(text ?? '')
  const next = m ? winapi(m[1]) : null
  if (next) return next.name
  return step.call ? apiShortName(step.call) : null
}

/**
 * Быстрые вопросы режима MinGW x64 — о стеке и вызовах, где у лабораторных
 * ошибаются чаще всего. Каждый показывается только тогда, когда он о текущем
 * месте трассы: «выровнен ли RSP» — перед `call`, «почему съехал стек» — после
 * `ret`, `pop` или `leave`, «почему упала на ret» — у упавшего прогона.
 */
function quick64(t: T, run: AsmRunSummary | undefined, step: AsmStep | undefined): Quick[] {
  const q: Quick[] = []
  const done = (step?.asm ?? '').trim().toLowerCase()
  const next = (step?.next?.asm ?? '').trim().toLowerCase()
  if (run?.status === 'crashed' && (!step || !step.next || /^ret/.test(done) || /^ret/.test(next)))
    q.push({ key: 'retCrash', label: t('asm.agent.quick.retCrash'), text: t('asm.agent.ask.retCrash') })
  if (!step) return q
  const beforeCall = /^call/.test(next)
  const api = apiOf(step, run?.source)
  if (/^(ret|pop|leave)/.test(done) || run?.status === 'crashed')
    q.push({ key: 'stack', label: t('asm.agent.quick.stack'), text: t('asm.agent.ask.stack') })
  if (beforeCall) q.push({ key: 'align', label: t('asm.agent.quick.align'), text: t('asm.agent.ask.align') })
  if (api) q.push({ key: 'apiArgs', label: t('asm.agent.quick.apiArgs', { name: api }), text: t('asm.agent.ask.apiArgs', { name: api }) })
  if (beforeCall || api) q.push({ key: 'shadow', label: t('asm.agent.quick.shadow'), text: t('asm.agent.ask.shadow') })
  return q
}

function quickFor(
  t: T,
  ctx: AnchorCtx,
  mingw64: boolean,
  a: AsmAnchor | null,
  run: AsmRunSummary | undefined,
  step: AsmStep | undefined,
): Quick[] {
  const q: Quick[] = []
  if (run?.status === 'build_error') q.push({ key: 'fix', label: t('asm.agent.quick.fix'), text: t('asm.agent.ask.fix') })
  if (run?.status === 'step_limit') q.push({ key: 'limit', label: t('asm.agent.quick.limit'), text: t('asm.agent.ask.limit') })
  if (run?.status === 'timeout' || run?.status === 'crashed')
    q.push({ key: 'stuck', label: t('asm.agent.quick.stuck'), text: t('asm.agent.ask.stuck') })
  if (mingw64) q.push(...quick64(t, run, step))
  if (!a) return q
  q.push({ key: a.kind, label: t(`asm.agent.quick.${a.kind}`), text: questionFor(t, ctx, a, step) })
  if (a.kind === 'text') {
    q.push({ key: 'textBug', label: t('asm.agent.quick.textBug'), text: t('asm.agent.ask.textBug') })
    q.push({ key: 'textRegs', label: t('asm.agent.quick.textRegs'), text: t('asm.agent.ask.textRegs') })
  }
  if ((a.kind === 'line' || a.kind === 'register' || a.kind === 'flag') && step)
    q.push({ key: 'next', label: t('asm.agent.quick.next'), text: t('asm.agent.ask.next') })
  return q
}

/* ── окно ────────────────────────────────────────────────────────────────── */

export default function Agent({ active }: AsmWindowProps) {
  const t = useT()
  const qc = useQueryClient()
  const { projectId, programId, selection, select, stepIndex, step, run, markUnread, agentRequest, toolchain } = useAsm()
  const docs = useDocEntries().entries
  const mingw64 = toolchain.id === 'mingw64'
  const ctx = useMemo<AnchorCtx>(
    () => ({
      docName: (id) => (docs ? entryById(id, docs)?.name : undefined) ?? id,
      flagsReg: mingw64 ? 'rflags' : 'flags',
    }),
    [docs, mingw64],
  )

  const chat = useAsmChat()
  const send = usePostAsmChat()
  const cancel = useCancelJob()
  // Выбора модели в окне нет, как и в чате доски: пресет — умолчание
  // пользователя из настроек, а без него спрашивать не с кем.
  const endpoint = useDefaultEndpoint()

  const [pending, setPending] = useState<AsmChatSend | null>(null)
  const [jobId, setJobId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [stopped, setStopped] = useState(false)
  const [draft, setDraft] = useState('')
  const stream = useJobStream(jobId)
  // Конец задания виден не один раз: поток закрывается, карточка перечитывается.
  const closed = useRef<string | null>(null)
  const inputRef = useRef<HTMLTextAreaElement | null>(null)
  const endRef = useRef<HTMLDivElement | null>(null)

  const hasTrace = !!run && !!step
  const currentLine = step?.next?.line ?? null
  const anchor = useMemo<AsmAnchor | null>(
    () => selection ?? (currentLine !== null ? { kind: 'line', line: currentLine } : run ? { kind: 'run' } : null),
    [selection, currentLine, run],
  )

  const answer = useMemo(() => {
    const parts: string[] = []
    for (const ev of stream.events) {
      if (ev.kind !== EV_TEXT) continue
      const piece = ev.data?.text
      if (typeof piece === 'string' && piece) parts.push(piece)
    }
    return parts.join('')
  }, [stream.events])

  const running = !!jobId && !stream.done
  const busy = running || send.isPending
  const messages = chat.data?.messages ?? []

  function doSend(text: string, a: AsmAnchor | null) {
    const body = text.trim()
    if (!body || busy || !endpoint) return
    const msg: AsmChatSend = {
      text: body,
      anchor: a,
      step: hasTrace ? stepIndex : null,
      run_no: run?.run_no ?? null,
      endpoint,
    }
    setError(null)
    setStopped(false)
    setPending(msg)
    setDraft('')
    send.mutate(msg, {
      onSuccess: (r) => {
        closed.current = null
        setJobId(r.job_id)
      },
      onError: (e) => setError(errorText(e)),
    })
  }

  // Свежие значения для обработчика запроса: сам запрос приходит редко, и
  // перезапускать его эффект на каждом шаге трассы незачем.
  const latest = useRef({ doSend, anchor, step, active, ctx })
  useEffect(() => {
    latest.current = { doSend, anchor, step, active, ctx }
  })

  useEffect(() => {
    if (!agentRequest || handledSeq.get(programId) === agentRequest.seq) return
    handledSeq.set(programId, agentRequest.seq)
    const { doSend: go, anchor: here, step: now, ctx: names } = latest.current
    const a = agentRequest.anchor ?? here
    if (agentRequest.text) {
      go(agentRequest.text, a)
    } else {
      setDraft(questionFor(t, names, a, now))
      inputRef.current?.focus()
    }
  }, [agentRequest, programId, t])

  useEffect(() => {
    if (!jobId || !stream.done || closed.current === jobId) return
    closed.current = jobId
    const status = stream.job?.status
    if (status === 'cancelled') {
      // Остановил сам человек — не беда и не повод звать его точкой на вкладке.
      setStopped(true)
      setJobId(null)
      return
    }
    // Ответ (или отказ) пришёл, а вкладка не на виду — точка на ярлыке.
    if (!latest.current.active) markUnread('agent')
    if (status !== 'done') {
      const e = (stream.job?.error ?? {}) as { code?: string; message?: string }
      setError(errorSaid(new ApiError(e.code || 'unknown', e.message || '')).text)
      setJobId(null)
      return
    }
    // Переписка перечитывается до того, как снимается «ждём ответа»: снятое
    // раньше на миг оставило бы разговор без последней пары.
    void qc.invalidateQueries({ queryKey: asmKeys.chat(projectId, programId) }).finally(() => {
      setPending(null)
      setJobId(null)
    })
  }, [jobId, stream.done, stream.job, projectId, programId, qc, markUnread])

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: 'end' })
  }, [messages.length, pending, answer, error, stopped])

  function stop() {
    if (jobId) cancel.mutate(jobId, { onError: (e) => setError(errorText(e)) })
  }

  const quick = quickFor(t, ctx, mingw64, anchor, run, step)
  const empty = !chat.isLoading && messages.length === 0 && !pending

  return (
    <div className="flex h-full min-h-0 flex-col bg-surface text-sm text-ink">
      <div className="flex min-w-0 items-center gap-s2 border-b border-line px-s3 py-1.5 text-xs text-muted">
        <span className="shrink-0">{t('asm.agent.about')}</span>
        <span
          className="min-w-0 truncate rounded-full bg-agent-bg px-2 py-px font-mono text-[11px] text-agent"
          data-testid="asm-agent-anchor"
          title={anchorTitle(anchor)}
        >
          {anchorLabel(t, ctx, anchor, hasTrace ? stepIndex : null, run?.run_no ?? null)}
        </span>
        {selection && (
          <button
            type="button"
            className="grid h-5 w-5 shrink-0 place-items-center rounded-sm text-muted hover:bg-surface-2 hover:text-ink"
            aria-label={t('asm.agent.unanchor')}
            title={t('asm.agent.unanchor')}
            onClick={() => select(null)}
          >
            <Icon name="close" size={12} />
          </button>
        )}
      </div>

      <div
        role="log"
        aria-live="polite"
        className="flex min-h-0 flex-1 flex-col gap-s2 overflow-y-auto px-s3 py-s2"
        data-testid="asm-agent-chat"
      >
        {chat.isLoading && <Spinner size={16} className="self-center" />}
        {chat.isError && <p className="text-xs text-err">{t('asm.agent.loadError')}</p>}
        {empty && <p className="text-muted">{t('asm.agent.empty')}</p>}
        {messages.map((m) => (
          <Bubble
            key={m.id}
            role={m.role}
            text={m.text}
            chip={m.role === 'user' && m.anchor ? anchorLabel(t, ctx, m.anchor, m.step, m.run_no) : null}
            chipTitle={m.role === 'user' ? anchorTitle(m.anchor) : undefined}
          />
        ))}
        {pending && (
          <>
            <Bubble
              role="user"
              text={pending.text}
              chip={pending.anchor ? anchorLabel(t, ctx, pending.anchor, pending.step, pending.run_no) : null}
              chipTitle={anchorTitle(pending.anchor)}
            />
            {busy && <Bubble role="assistant" text={answer} waiting />}
            {stopped && <p className="text-xs text-muted">{t('asm.agent.stopped')}</p>}
          </>
        )}
        {error && !busy && (
          <p className="rounded-sm border border-err bg-err-bg px-s2 py-1.5 text-xs text-err">{error}</p>
        )}
        <div ref={endRef} />
      </div>

      {quick.length > 0 && (
        <div className="flex flex-none flex-wrap gap-1 px-s3 pb-1.5">
          {quick.map((q) => (
            <button
              key={q.key}
              type="button"
              disabled={busy || !endpoint}
              className="rounded-full border border-[color-mix(in_srgb,var(--agent)_45%,var(--line))] px-2 py-px text-xs text-agent hover:bg-agent-bg disabled:cursor-not-allowed disabled:opacity-45"
              title={q.text}
              onClick={() => doSend(q.text, anchor)}
            >
              {q.label}
            </button>
          ))}
        </div>
      )}

      {!endpoint && (
        <p className="flex flex-none flex-wrap items-center gap-s2 px-s3 pb-1.5 text-xs text-warn">
          {t('asm.agent.noEndpoint')}
          <Link to="/settings/agent" className="underline">
            {t('asm.agent.toSettings')}
          </Link>
        </p>
      )}

      <form
        className="flex flex-none items-end gap-1.5 px-s3 pb-s2"
        onSubmit={(e) => {
          e.preventDefault()
          doSend(draft, anchor)
        }}
      >
        <textarea
          ref={inputRef}
          rows={1}
          value={draft}
          placeholder={t('asm.agent.placeholder')}
          aria-label={t('asm.agent.placeholder')}
          data-testid="asm-agent-input"
          className="max-h-32 min-h-8 flex-1 resize-y rounded-sm border border-line-strong bg-surface px-2 py-1.5 text-sm text-ink placeholder:text-muted focus:border-agent focus:outline-none"
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            // ⏎ отправляет, ⇧⏎ переносит строку: вопрос агенту — фраза, а не сочинение.
            if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault()
              doSend(draft, anchor)
            }
          }}
        />
        {running ? (
          <button
            type="button"
            className="grid h-8 w-8 flex-none place-items-center rounded-sm border border-err text-err hover:bg-err-bg disabled:opacity-45"
            aria-label={t('asm.agent.stop')}
            title={t('asm.agent.stop')}
            disabled={cancel.isPending}
            onClick={stop}
          >
            <Icon name="close" size={14} />
          </button>
        ) : (
          <button
            type="submit"
            className="grid h-8 w-8 flex-none place-items-center rounded-sm bg-agent text-agent-ink disabled:cursor-not-allowed disabled:opacity-45"
            aria-label={t('asm.agent.send')}
            title={t('asm.agent.send')}
            disabled={busy || !endpoint || !draft.trim()}
          >
            <Icon name="upload" size={14} />
          </button>
        )}
      </form>
    </div>
  )
}

/* ── сообщение ───────────────────────────────────────────────────────────── */

function Bubble({
  role,
  text,
  waiting = false,
  chip = null,
  chipTitle,
}: {
  role: AsmChatMessage['role']
  text: string
  /** Ответа ещё нет целиком: пустой текст — «думает». */
  waiting?: boolean
  /** Якорь, с которым ушло сообщение. */
  chip?: string | null
  /** Подсказка чипа — выделенный текст, если якорь им был. */
  chipTitle?: string
}) {
  const t = useT()
  const mine = role === 'user'
  return (
    <article
      data-role={role}
      className={cn(
        'flex flex-col gap-0.5',
        mine ? 'max-w-[85%] self-end rounded-md bg-surface-2 px-2 py-1' : 'max-w-[72ch] self-start',
      )}
    >
      {!mine && (
        <span className="text-[10px] font-semibold uppercase tracking-wide text-agent">{t('asm.agent.agent')}</span>
      )}
      {chip && (
        <span className="self-end font-mono text-[10px] text-agent" title={chipTitle}>
          {chip}
        </span>
      )}
      {text ? (
        <AnswerText text={text} />
      ) : waiting ? (
        <p className="animate-pulse text-muted">{t('asm.agent.thinking')}</p>
      ) : null}
    </article>
  )
}

/**
 * Текст ответа: блоки ``` — кодом, `так` — моноширинным в строке, остальное как
 * есть с переносами. Больше разметки не нужно: агент объясняет команды и цифры
 * трассы, а заголовки и таблицы в узкой вкладке только мешают. Недописанный
 * блок кода, пока ответ идёт потоком, остаётся текстом до закрывающих кавычек.
 */
function AnswerText({ text }: { text: string }) {
  const blocks = text.split(/```[^\n]*\n?([\s\S]*?)```/g)
  return (
    <div className="whitespace-pre-wrap break-words text-sm leading-normal text-ink">
      {blocks.map((b, i) =>
        i % 2 ? (
          <pre
            key={i}
            className="my-1 overflow-x-auto whitespace-pre rounded-sm border border-line bg-surface-3 px-2 py-1 font-mono text-xs"
          >
            {b.replace(/\n$/, '')}
          </pre>
        ) : (
          <InlineCode key={i} text={b} />
        ),
      )}
    </div>
  )
}

function InlineCode({ text }: { text: string }) {
  const parts = text.split(/`([^`\n]+)`/g)
  return (
    <>
      {parts.map((p, i) =>
        i % 2 ? (
          <code key={i} className="rounded-sm bg-agent-bg px-1 font-mono text-xs text-ink-strong">
            {p}
          </code>
        ) : (
          p
        ),
      )}
    </>
  )
}
