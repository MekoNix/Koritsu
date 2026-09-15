/**
 * DocsView — справка: поиск, разделы, список записей и карточка записи.
 *
 * ── Набор записей приходит снаружи ───────────────────────────────────────────
 *
 * Справка у каждого режима своя (TASM — `entries.ts`, MinGW x64 —
 * `entries64.ts`), и окно получает набор пропом. Разделы, поиск, «см. также» и
 * запись по токену считаются по этому набору, а разделы без записей не
 * показываются. Примеры набора GAS подсвечиваются тем же разбором, что и
 * редактор (`gasLanguage.ts`), примеры TASM — прежней построчной подсветкой.
 *
 * ── Широко рядом, узко по очереди ────────────────────────────────────────────
 *
 * Окно справки живёт во вкладке дока, и его ширину задаёт группа, а не экран:
 * одна и та же справка стоит то узкой колонкой рядом с агентом, то на всю
 * нижнюю полосу. Поэтому раскладка решается по ширине самого окна: от 560px
 * список и карточка стоят рядом, уже — по очереди, с «← к списку».
 *
 * ── Клавиатура ──────────────────────────────────────────────────────────────
 *
 * Стрелки ходят по списку прямо из поля поиска, Enter открывает запись, Esc
 * сначала очищает запрос, потом возвращает из карточки к списку: справку
 * открывают по F1 посреди набора кода, и тянуться к мыши ради соседней записи
 * незачем.
 */
import { useCallback, useEffect, useId, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from 'react'

import { useT } from '@/i18n'
import { cn } from '@/lib/cn'
import { Icon } from '@/ui'

import { tokenize as gasTokenize, type GasTokenKind } from '../windows/gasLanguage'
import { DOC_ENTRIES, FLAG_NAMES, SECTION_TITLE, type DocEntry, type DocIoRow, type DocSection } from './entries'
import { entryById, findEntry, lookup, searchEntries, sectionsOf, seeAlso } from './lookup'

export interface DocsRequest {
  /** Токен из кода или id записи; `null` — просто показать справку. */
  token: string | null
  /** Растёт с каждым запросом: повторный запрос той же записи тоже открывает её. */
  seq: number
}

export interface DocsViewProps {
  /** Набор записей режима программы. */
  entries: readonly DocEntry[]
  request?: DocsRequest | null
  onAsk?: (entry: DocEntry) => void
  /** Нет — кнопки «Вставить пример» нет. */
  onInsert?: (entry: DocEntry) => void
}

/** С какой ширины окна список и карточка стоят рядом. */
const WIDE_PX = 560

export function DocsView({ entries, request, onAsk, onInsert }: DocsViewProps) {
  const t = useT()
  const uid = useId()
  const rootRef = useRef<HTMLDivElement | null>(null)
  const listRef = useRef<HTMLDivElement | null>(null)
  const cardRef = useRef<HTMLElement | null>(null)
  const inputRef = useRef<HTMLInputElement | null>(null)

  /** Набор GAS: у него свои подсказка поиска и подсветка примеров. */
  const gas = useMemo(() => entries.some((e) => e.sec === 'gas'), [entries])
  const sections = useMemo(() => sectionsOf(entries), [entries])
  /** Запись, открытая до первого запроса: первая команда набора (`mov`). */
  const firstId = entries[0]?.id ?? ''

  const [wide, setWide] = useState(false)
  const [sec, setSec] = useState<DocSection | 'all'>('all')
  const [query, setQuery] = useState('')
  const [active, setActive] = useState(0)
  const [openId, setOpenId] = useState(firstId)
  /** Узкое окно: показана карточка, а не список. На широком не читается. */
  const [cardMode, setCardMode] = useState(false)

  useEffect(() => {
    const el = rootRef.current
    if (!el || typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver((boxes) => {
      const box = boxes[0]
      if (box) setWide(box.contentRect.width >= WIDE_PX)
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  // Раздел, которого в наборе нет, — это «все».
  const secShown: DocSection | 'all' = sec !== 'all' && !sections.some((s) => s.id === sec) ? 'all' : sec
  const shown = useMemo(() => searchEntries(query, secShown, entries), [query, secShown, entries])
  const activeIdx = Math.max(0, Math.min(active, shown.length - 1))
  const entry = entryById(openId, entries) ?? entryById(firstId, entries)

  /**
   * Открыть запись. Запрос извне (`fromUser = false`) сбрасывает поиск и раздел,
   * если запись в текущий список не попадает: человек нажал F1 на `loop` и
   * должен увидеть `loop`, а не пустой фильтр «DOS».
   */
  const open = useCallback(
    (token: string, fromUser: boolean) => {
      const e = findEntry(token, entries)
      if (!e) return false
      let pool = shown
      if (!pool.includes(e) && !fromUser) {
        setQuery('')
        setSec('all')
        pool = searchEntries('', 'all', entries)
      }
      const idx = pool.indexOf(e)
      if (idx >= 0) setActive(idx)
      setOpenId(e.id)
      setCardMode(true)
      return true
    },
    [shown, entries],
  )

  const handled = useRef<number | null>(null)
  useEffect(() => {
    if (!request || handled.current === request.seq) return
    handled.current = request.seq
    const token = request.token?.trim()
    if (!token) {
      inputRef.current?.focus()
      return
    }
    if (lookup(token, entries)) {
      open(token, false)
      cardRef.current?.focus({ preventScroll: true })
    } else {
      // Незнакомое слово — не тупик: оно становится строкой поиска.
      setQuery(token)
      setActive(0)
      setCardMode(false)
    }
  }, [request, open, entries])

  useEffect(() => {
    cardRef.current?.scrollTo({ top: 0 })
  }, [openId])

  useEffect(() => {
    const el = listRef.current?.querySelector<HTMLElement>(`[data-i="${activeIdx}"]`)
    el?.scrollIntoView({ block: 'nearest' })
  }, [activeIdx, shown])

  function onKey(ev: KeyboardEvent) {
    if (ev.key === 'ArrowDown') {
      ev.preventDefault()
      setActive(Math.min(shown.length - 1, activeIdx + 1))
    } else if (ev.key === 'ArrowUp') {
      ev.preventDefault()
      setActive(Math.max(0, activeIdx - 1))
    } else if (ev.key === 'Enter') {
      const e = shown[activeIdx]
      if (e) {
        ev.preventDefault()
        open(e.id, true)
      }
    } else if (ev.key === 'Escape') {
      if (query) {
        ev.preventDefault()
        setQuery('')
        setActive(0)
      } else if (cardMode && !wide) {
        setCardMode(false)
      }
    }
  }

  const grouped = !query.trim() && secShown === 'all'
  const listVisible = wide || !cardMode
  const cardVisible = wide || cardMode
  const listId = `${uid}-list`

  return (
    <div ref={rootRef} className="flex h-full min-h-0 flex-col bg-surface text-sm text-ink">
      <div className="flex flex-col gap-s2 border-b border-line px-s3 py-s2">
        <label className="flex h-8 items-center gap-s2 rounded-sm border border-line-strong bg-surface-3 px-2.5 focus-within:border-accent">
          <Icon name="search" size={14} className="shrink-0 text-muted" />
          <input
            ref={inputRef}
            type="search"
            autoComplete="off"
            spellCheck={false}
            value={query}
            placeholder={t(gas ? 'asm.docs.placeholder64' : 'asm.docs.placeholder')}
            aria-label={t('asm.docs.search')}
            aria-controls={listId}
            className="min-w-0 flex-1 border-0 bg-transparent text-sm text-ink outline-none placeholder:text-muted"
            onChange={(e) => {
              setQuery(e.target.value)
              setActive(0)
              setCardMode(false)
            }}
            onKeyDown={onKey}
          />
          {query && (
            <span className="whitespace-nowrap font-mono text-xs text-muted" aria-live="polite">
              {t('asm.docs.count', { n: shown.length, total: entries.length })}
            </span>
          )}
        </label>
        <div className="flex flex-wrap gap-1" role="group" aria-label={t('asm.docs.sections')}>
          {[{ id: 'all' as const, title: t('asm.docs.all') }, ...sections].map((s) => (
            <button
              key={s.id}
              type="button"
              aria-pressed={secShown === s.id}
              className={cn(
                'rounded-full border px-2 py-px text-xs focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent',
                secShown === s.id
                  ? 'border-accent bg-accent-bg text-accent'
                  : 'border-line text-muted hover:border-line-strong hover:text-ink',
              )}
              onClick={() => {
                setSec(s.id)
                setActive(0)
                setCardMode(false)
              }}
            >
              {s.title}
            </button>
          ))}
        </div>
      </div>

      <div
        className={cn(
          'grid min-h-0 flex-1',
          wide ? 'grid-cols-[220px_minmax(0,1fr)]' : 'grid-cols-[minmax(0,1fr)]',
        )}
      >
        {listVisible && (
          <div
            ref={listRef}
            id={listId}
            role="listbox"
            tabIndex={0}
            aria-label={t('asm.docs.list')}
            aria-activedescendant={shown.length ? `${uid}-o-${activeIdx}` : undefined}
            className={cn(
              'min-h-0 overflow-auto py-1 outline-none focus-visible:shadow-[inset_0_0_0_2px_var(--accent)]',
              wide && 'border-r border-line',
            )}
            onKeyDown={onKey}
          >
            {shown.length === 0 && (
              <p className="px-s3 py-s4 text-muted">{t(gas ? 'asm.docs.empty64' : 'asm.docs.empty')}</p>
            )}
            {shown.map((e, i) => {
              const head = grouped && (i === 0 || shown[i - 1]?.sec !== e.sec)
              return (
                <div key={e.id}>
                  {head && (
                    <div
                      role="presentation"
                      className="px-s3 pb-1 pt-2.5 text-[11px] font-semibold uppercase tracking-wider text-muted"
                    >
                      {SECTION_TITLE[e.sec]}
                    </div>
                  )}
                  <div
                    id={`${uid}-o-${i}`}
                    role="option"
                    data-i={i}
                    aria-selected={e.id === openId}
                    className={cn(
                      'flex cursor-pointer items-baseline gap-s2 border-l-2 px-s3 py-1',
                      e.id === openId
                        ? 'border-accent bg-accent-bg'
                        : i === activeIdx
                          ? 'border-line-strong bg-surface-2'
                          : 'border-transparent hover:bg-surface-2',
                    )}
                    onClick={() => open(e.id, true)}
                  >
                    <b className="whitespace-nowrap font-mono text-xs font-medium text-ink-strong">{e.name}</b>
                    <span className="min-w-0 truncate text-xs text-muted">{e.short}</span>
                  </div>
                </div>
              )
            })}
          </div>
        )}

        {cardVisible && entry && (
          <article
            ref={cardRef}
            tabIndex={-1}
            aria-live="polite"
            className="min-h-0 overflow-auto px-s4 pb-s5 pt-s3 outline-none"
          >
            <EntryCard
              entry={entry}
              entries={entries}
              gas={gas}
              showBack={!wide}
              onBack={() => {
                setCardMode(false)
                listRef.current?.focus()
              }}
              onOpen={(id) => open(id, false)}
              onAsk={onAsk}
              onInsert={onInsert}
            />
          </article>
        )}
      </div>
    </div>
  )
}

/* ── карточка ────────────────────────────────────────────────────────────── */

function EntryCard({
  entry,
  entries,
  gas,
  showBack,
  onBack,
  onOpen,
  onAsk,
  onInsert,
}: {
  entry: DocEntry
  entries: readonly DocEntry[]
  gas: boolean
  showBack: boolean
  onBack: () => void
  onOpen: (id: string) => void
  onAsk?: (entry: DocEntry) => void
  onInsert?: (entry: DocEntry) => void
}) {
  const t = useT()
  const see = seeAlso(entry, entries)
  const h = 'mb-1.5 mt-s4 text-[11px] font-semibold uppercase tracking-wider text-muted'
  const CodeView = gas ? GasCode : Code

  return (
    <>
      {showBack && (
        <button type="button" className="mb-2.5 text-xs text-accent" onClick={onBack}>
          {t('asm.docs.back')}
        </button>
      )}
      <div className="flex flex-wrap items-baseline gap-x-2.5 gap-y-1.5">
        <h3 className="m-0 font-mono text-lg font-semibold text-ink-strong">{entry.name}</h3>
        <span className="rounded-full border border-line px-2 text-[11px] text-muted">{SECTION_TITLE[entry.sec]}</span>
      </div>
      <p className="mt-0.5 text-muted">{entry.short}</p>

      {entry.syntax && (
        <pre className="mt-s3 overflow-x-auto whitespace-pre rounded-sm border border-line bg-surface-3 px-2.5 py-2 font-mono text-xs text-ink-strong">
          <CodeView code={entry.syntax} />
        </pre>
      )}
      <p className="mt-2.5 max-w-[68ch]">
        <Inline text={entry.desc} />
      </p>

      {entry.flags && (
        <>
          <div className={h}>{t('asm.docs.flags')}</div>
          <div className="overflow-x-auto">
            <table className="border-collapse font-mono text-xs">
              <thead>
                <tr>
                  {FLAG_NAMES.map((f) => (
                    <th key={f} className="w-8 border border-line bg-surface-2 py-0.5 text-center font-medium text-muted">
                      {f}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                <tr>
                  {entry.flags.split('').map((ch, i) => (
                    <FlagCell key={i} ch={ch} />
                  ))}
                </tr>
              </tbody>
            </table>
          </div>
          <div className="mt-1 text-[11px] text-muted">{t('asm.docs.legend')}</div>
        </>
      )}

      {entry.io && (
        <div className="grid grid-cols-[repeat(auto-fit,minmax(180px,1fr))] gap-x-s4 gap-y-s2">
          <div>
            <div className={h}>{t('asm.docs.in')}</div>
            <IoList rows={entry.io.in} />
          </div>
          <div>
            <div className={h}>{t('asm.docs.out')}</div>
            <IoList rows={entry.io.out} />
          </div>
        </div>
      )}

      {entry.ex && (
        <>
          <div className={h}>{t('asm.docs.example')}</div>
          <pre className="m-0 overflow-x-auto whitespace-pre rounded-sm border border-line bg-surface-3 px-2.5 py-2 font-mono text-xs leading-relaxed text-ink">
            <CodeView code={entry.ex} />
          </pre>
        </>
      )}

      {entry.errs.length > 0 && (
        <>
          <div className={h}>{t('asm.docs.errors')}</div>
          <ul className="m-0 grid max-w-[68ch] list-disc gap-1 pl-4 marker:text-warn">
            {entry.errs.map((x, i) => (
              <li key={i}>
                <Inline text={x} />
              </li>
            ))}
          </ul>
        </>
      )}

      {see.length > 0 && (
        <>
          <div className={h}>{t('asm.docs.see')}</div>
          <div className="flex flex-wrap gap-1">
            {see.map((e) => (
              <button
                key={e.id}
                type="button"
                className="rounded-sm border border-line px-1.5 py-px font-mono text-xs text-accent hover:border-accent hover:bg-accent-bg"
                onClick={() => onOpen(e.id)}
              >
                {e.name}
              </button>
            ))}
          </div>
        </>
      )}

      {(onAsk || (onInsert && entry.ex)) && (
        <div className="mt-s4 flex flex-wrap gap-1.5">
          {onAsk && (
            <button
              type="button"
              className="inline-flex h-7 items-center gap-1.5 rounded-sm border border-agent bg-agent-bg px-2.5 text-xs font-medium text-agent"
              onClick={() => onAsk(entry)}
            >
              <Icon name="agent" size={14} />
              {t('asm.docs.ask')}
            </button>
          )}
          {onInsert && entry.ex && (
            <button
              type="button"
              className="inline-flex h-7 items-center gap-1.5 rounded-sm border border-line-strong bg-surface px-2.5 text-xs font-medium text-ink hover:bg-surface-2"
              onClick={() => onInsert(entry)}
            >
              <Icon name="plus" size={14} />
              {t('asm.docs.insert')}
            </button>
          )}
        </div>
      )}
    </>
  )
}

function FlagCell({ ch }: { ch: string }) {
  const t = useT()
  const base = 'w-8 border border-line py-0.5 text-center'
  if (ch === '-')
    return (
      <td className={cn(base, 'text-muted')} title={t('asm.docs.flagKept')}>
        –
      </td>
    )
  if (ch === '*')
    return (
      <td className={cn(base, 'font-semibold text-accent')} title={t('asm.docs.flagResult')}>
        *
      </td>
    )
  if (ch === '?')
    return (
      <td className={cn(base, 'text-warn')} title={t('asm.docs.flagUndefined')}>
        ?
      </td>
    )
  return (
    <td className={cn(base, 'font-semibold text-ink-strong')} title={t('asm.docs.flagAlways', { v: ch })}>
      {ch}
    </td>
  )
}

function IoList({ rows }: { rows: DocIoRow[] }) {
  const t = useT()
  const list: DocIoRow[] = rows.length ? rows : [['—', t('asm.docs.returnsNothing')]]
  return (
    <dl className="m-0 grid grid-cols-[auto_1fr] gap-x-2.5 gap-y-0.5">
      {list.map(([where, what], i) => (
        <div key={i} className="contents">
          <dt className="font-mono text-xs text-ink-strong">{where}</dt>
          <dd className="m-0 text-xs">{what}</dd>
        </div>
      ))}
    </dl>
  )
}

/* ── текст и код ─────────────────────────────────────────────────────────── */

/** `код` в обратных кавычках — моноширинным. */
function Inline({ text }: { text: string }) {
  const parts = text.split(/`([^`]+)`/g)
  return (
    <>
      {parts.map((p, i) =>
        i % 2 ? (
          <code key={i} className="rounded-sm bg-surface-2 px-1 font-mono text-xs text-ink-strong">
            {p}
          </code>
        ) : (
          p
        ),
      )}
    </>
  )
}

const MNEMONICS = new Set<string>([
  ...DOC_ENTRIES.filter((e) => e.sec === 'cmd').flatMap((e) => e.alias),
  'retf', 'cmpsw', 'scasw', 'jo', 'jno', 'js', 'jns', 'jp', 'jnp',
])
const DIRECTIVES = new Set(
  '.model .stack .data .code .startup .exit segment ends assume proc endp db dw dd dup equ offset seg ptr byte word dword near far end include macro endm org stack ideal masm model dataseg codeseg @data'.split(' '),
)
const REGISTERS = new Set(
  'ax bx cx dx ah al bh bl ch cl dh dl si di bp sp ip cs ds ss es eax ebx ecx edx esi edi ebp esp'.split(' '),
)
const TOKEN = /(;.*$)|('[^']*'|"[^"]*")|(\b[0-9][0-9a-f]*h\b|\b\d+\b)|([.@]?[a-z_?][\w@?]*)/gi

/**
 * Подсветка TASM для примеров: комментарии, строки, числа, мнемоники,
 * директивы, регистры. Разбор построчный и без состояния — в примерах нет
 * многострочных конструкций, а цвета берутся из токенов темы `--code-*`.
 */
function Code({ code }: { code: string }) {
  const out: ReactNode[] = []
  let key = 0
  code.split('\n').forEach((line, li) => {
    if (li) out.push('\n')
    let last = 0
    for (const m of line.matchAll(TOKEN)) {
      const at = m.index ?? 0
      if (at > last) out.push(line.slice(last, at))
      const tok = m[0]
      let cls = ''
      if (m[1]) cls = 'italic text-[color:var(--code-comment)]'
      else if (m[2]) cls = 'text-[color:var(--code-str)]'
      else if (m[3]) cls = 'text-[color:var(--code-num)]'
      else {
        const l = tok.toLowerCase()
        cls = MNEMONICS.has(l)
          ? 'text-[color:var(--code-fn)]'
          : DIRECTIVES.has(l)
            ? 'text-[color:var(--code-kw)]'
            : REGISTERS.has(l)
              ? 'text-ink-strong'
              : ''
      }
      out.push(
        cls ? (
          <span key={key++} className={cls}>
            {tok}
          </span>
        ) : (
          tok
        ),
      )
      last = at + tok.length
    }
    if (last < line.length) out.push(line.slice(last))
  })
  return <>{out}</>
}

const GAS_CLASS: Partial<Record<GasTokenKind, string>> = {
  comment: 'italic text-[color:var(--code-comment)]',
  string: 'text-[color:var(--code-str)]',
  number: 'text-[color:var(--code-num)]',
  mnemonic: 'text-[color:var(--code-fn)]',
  directive: 'text-[color:var(--code-kw)]',
  register: 'text-ink-strong',
}

/**
 * Подсветка GAS для примеров — разбором редактора (`gasLanguage.ts`): `#` —
 * комментарий, `;` — разделитель команд, как у самого `as`. Цвета — те же
 * токены темы `--code-*`, что у примеров TASM.
 */
function GasCode({ code }: { code: string }) {
  const out: ReactNode[] = []
  let key = 0
  code.split('\n').forEach((line, li) => {
    if (li) out.push('\n')
    for (const tok of gasTokenize(line)) {
      const cls = GAS_CLASS[tok.kind]
      out.push(
        cls ? (
          <span key={key++} className={cls}>
            {tok.text}
          </span>
        ) : (
          tok.text
        ),
      )
    }
  })
  return <>{out}</>
}
