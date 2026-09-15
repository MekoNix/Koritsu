/**
 * Listing — вид трассы по листингу TASM: адрес, байты команды, строка исходника,
 * сколько раз строка выполнялась.
 *
 * Править здесь нельзя — правят в «Исходнике». Листинг отвечает на другой
 * вопрос: где сейчас процессор. Поэтому строки берутся из `.lst` последней
 * сборки, а не из редактора: после правки номера строк в редакторе уже другие,
 * а адреса и байты — те, что реально исполнялись.
 *
 * Отметки в поле слева: стрелка — следующая команда (`step.next`), точка —
 * только что выполненная, красный круг — точка останова (щелчок ставит и
 * снимает). Двойной щелчок — выполнить до строки.
 */
import { useEffect, useMemo, type KeyboardEvent } from 'react'

import { useAsm } from '@/features/asm/store'
import type { AsmWindowProps } from '@/features/asm/types'
import { useT } from '@/i18n'
import { cn } from '@/lib/cn'

import {
  ROW,
  fmtInt,
  firstError,
  hasTrace,
  hex,
  hexFlat,
  isMenuKey,
  lastStepIndex,
  lineOfNode,
  menuPointOf,
  nextOf,
  parseHex,
  sameAnchor,
  segmentBase,
  useAnchorMenu,
  useRowWindow,
  useSelectionAsk,
  useToolchainLanguage,
  useTraceScan,
} from './format'
import { mnemonicOf, tasmSpans } from './tasmLanguage'
import './windows64.css'

/** Строки листинга, которые задевает выделение. Конец в самом начале строки её не задевает. */
function selectionLines(range: Range): readonly [number | null, number | null] {
  const from = lineOfNode(range.startContainer)
  let to = lineOfNode(range.endContainer)
  if (range.endOffset === 0 && to != null && to !== from) {
    const node = range.endContainer
    const el = node instanceof Element ? node : node.parentElement
    to = lineOfNode(el?.closest('[data-line]')?.previousElementSibling ?? null) ?? to
  }
  return [from, to]
}

/**
 * Текст выделения через несколько строк — строками листинга «номер адрес байты
 * текст». Колонки — отдельные ячейки сетки, и сырой текст выделения разложил бы
 * каждую ячейку на свою строку.
 */
function selectionText(range: Range, raw: string): string {
  const common = range.commonAncestorContainer
  const rows = common instanceof Element ? [...common.querySelectorAll('.ln')].filter((el) => range.intersectsNode(el)) : []
  if (rows.length < 2) return raw
  const cell = (el: Element, sel: string) => el.querySelector(sel)?.textContent ?? ''
  return rows
    .map((el) => [cell(el, '.no').padStart(5, ' '), cell(el, '.addr').padEnd(9, ' '), cell(el, '.by').padEnd(20, ' '), cell(el, '.src')].join('  ').trimEnd())
    .join('\n')
}

/** Высота шапки таблицы, px (`.lh`). */
const HEADER = 20
/** До скольких шагов счётчик «раз» считается за весь прогон; дальше — к текущему шагу. */
const HITS_FULL_LIMIT = 20_000

interface Row {
  line: number
  seg: string | null
  addr: string | null
  bytes: string
  text: string
}

export default function Listing({ active }: AsmWindowProps) {
  const t = useT()
  const asm = useAsm()
  const { run, step, program, settings, cursorLine, selection, stepIndex, toolchain } = asm
  const tasm = toolchain.id === 'tasm'
  // Плоская память: смещение строки — уже адрес после связывания, 16 знаков, без сегмента.
  const flat = toolchain.memory === 'flat'
  const lang = useToolchainLanguage()
  const mnemonic = (text: string) => (tasm ? mnemonicOf(text) : (lang?.mnemonicOf(text) ?? null))
  const menu = useAnchorMenu()
  const total = lastStepIndex(run)
  const fullHits = total <= HITS_FULL_LIMIT
  const scan = useTraceScan(fullHits ? 'end' : 'current', active)

  const rows = useMemo<Row[]>(() => {
    const listing = run?.build?.listing
    if (listing && listing.length > 0) {
      return listing.map((l) => {
        const base = flat ? null : segmentBase(run, l.segment)
        const off = parseHex(l.offset)
        return {
          line: l.line,
          seg: base == null ? null : hex(base),
          addr: off == null ? null : flat ? hexFlat(off) : hex(off),
          bytes: l.bytes.trim(),
          text: l.text,
        }
      })
    }
    // Сборки ещё не было — показываем исходник как есть, без адресов.
    return (program?.source ?? '').split('\n').map((text, i) => ({ line: i + 1, seg: null, addr: null, bytes: '', text: text.replace(/\r$/, '') }))
  }, [run, program?.source, flat])

  const indexByLine = useMemo(() => {
    const m = new Map<number, number>()
    rows.forEach((r, i) => {
      if (!m.has(r.line)) m.set(r.line, i)
    })
    return m
  }, [rows])

  const errors = useMemo(() => {
    const m = new Map<number, string>()
    for (const msg of run?.build?.messages ?? []) if (msg.line != null && msg.severity === 'error' && !m.has(msg.line)) m.set(msg.line, msg.text)
    return m
  }, [run])

  const bps = useMemo(() => new Set(settings.breakpoints), [settings.breakpoints])
  const trace = hasTrace(run)
  const next = trace ? nextOf(step) : null
  const curLine = next?.line ?? null
  const wasLine = trace && stepIndex > 0 ? (step?.line ?? null) : null
  const ended = trace && stepIndex >= total && run?.status === 'done' && !next
  const err = firstError(run)
  // Строки листинга — текст сборки, а переход ведёт в нынешний исходник: после
  // правки — к сдвинутой строке, к переписанной — никуда.
  const stale = asm.buildStale
  const errNow = err ? asm.sourceLineOf(err.line) : null

  const win = useRowWindow(rows.length, { header: HEADER })
  const { reveal } = win
  const ask = useSelectionAsk({ window: 'listing', active, root: win.ref, lines: selectionLines, textOf: selectionText })

  // Шаг сменился — следующая команда должна быть на экране.
  useEffect(() => {
    if (curLine != null) reveal(indexByLine.get(curLine) ?? -1)
  }, [curLine, stepIndex, indexByLine, reveal])

  // Курсор поставили снаружи («Перейти к строке», точка в списке) — показать.
  useEffect(() => {
    if (cursorLine != null) reveal(indexByLine.get(cursorLine) ?? -1)
  }, [cursorLine, indexByLine, reveal])

  const toggleBp = (line: number) => {
    const list = settings.breakpoints
    asm.updateSettings({ breakpoints: list.includes(line) ? list.filter((l) => l !== line) : [...list, line].sort((a, b) => a - b) })
  }

  const putCursor = (line: number) => {
    asm.setCursorLine(line)
    asm.select({ kind: 'line', line })
  }

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (isMenuKey(e) && cursorLine != null) {
      e.preventDefault()
      e.stopPropagation()
      const el = win.ref.current?.querySelector('[data-cursor="true"]')
      const row = rows[indexByLine.get(cursorLine) ?? -1]
      if (el && row) menu.open(menuPointOf(el), { kind: 'line', line: cursorLine }, mnemonic(row.text), ask.current())
      return
    }
    const page = Math.max(1, Math.floor(win.height / ROW) - 1)
    const delta = e.key === 'ArrowUp' ? -1 : e.key === 'ArrowDown' ? 1 : e.key === 'PageUp' ? -page : e.key === 'PageDown' ? page : 0
    if (!delta || e.altKey || e.ctrlKey || rows.length === 0) return
    e.preventDefault()
    const from = cursorLine != null ? (indexByLine.get(cursorLine) ?? 0) : 0
    const i = Math.max(0, Math.min(rows.length - 1, from + delta))
    const row = rows[i]
    if (row) {
      putCursor(row.line)
      reveal(i, false)
    }
  }

  return (
    <section className="relative flex h-full min-h-0 flex-col" aria-label={t('asm.tabs.listing')}>
      {err && run?.status === 'build_error' && (
        <div className="errbar">
          <span className="grow truncate">{t('asm.listing.errorBar', { line: err.line, text: err.text })}</span>
          {stale && (
            <span className="truncate" style={{ color: 'var(--warn)' }}>
              {t('asm.listing.stale')}
            </span>
          )}
          {errNow != null && (
            <button type="button" onClick={() => putCursor(errNow)}>
              {t('asm.listing.toLine', { line: errNow })}
            </button>
          )}
        </div>
      )}
      <div ref={win.ref} tabIndex={0} role="grid" aria-label={t('asm.tabs.listing')} onKeyDown={onKeyDown} className="qb">
        <div className={cn('lst', flat && 'lst64')}>
          <div role="row" className="lh">
            <span />
            <span>{t('asm.listing.colLine')}</span>
            <span>{t(flat ? 'asm64.listing.colAddr' : 'asm.listing.colAddr')}</span>
            <span>{t('asm.listing.colBytes')}</span>
            <span>{t(tasm ? 'asm.listing.colSource' : 'asm64.listing.colSource')}</span>
            <span title={fullHits ? t('asm.listing.hitsAll') : t('asm.listing.hitsToStep')}>{t('asm.listing.colHits')}</span>
          </div>
          {rows.length === 0 && <div className="empty">{t('asm.listing.empty')}</div>}
          <div style={{ height: win.padTop }} />
          {rows.slice(win.first, win.last).map((r, j) => {
            const i = win.first + j
            const first = indexByLine.get(r.line) === i
            const isCur = r.line === curLine && first
            const isWas = r.line === wasLine && !isCur && first
            const isExit = ended && r.line === step?.line && first
            const isCursor = r.line === cursorLine && first
            const hits = first ? scan?.hits.get(r.line) : undefined
            return (
              <div
                key={i}
                role="row"
                data-line={r.line}
                data-cursor={isCursor || undefined}
                aria-selected={isCursor || undefined}
                title={stale && errors.has(r.line) ? `${errors.get(r.line)} · ${t('asm.listing.stale')}` : errors.get(r.line)}
                className={cn(
                  'ln',
                  isCur && 'is-cur',
                  isWas && 'is-was',
                  isCursor && 'is-cursor',
                  bps.has(r.line) && 'is-bp',
                  errors.has(r.line) && 'is-err',
                  isExit && 'is-exit',
                  first && sameAnchor(selection, { kind: 'line', line: r.line }) && 'is-ctx',
                )}
                onClick={() => putCursor(r.line)}
                onDoubleClick={(e) => {
                  if ((e.target as HTMLElement).closest('.gut')) return
                  asm.setCursorLine(r.line)
                  asm.runToCursor()
                }}
                onContextMenu={(e) => menu.open(e, { kind: 'line', line: r.line }, mnemonic(r.text), ask.current())}
              >
                <span
                  className="gut"
                  role="button"
                  aria-pressed={bps.has(r.line)}
                  aria-label={t('asm.listing.bpToggle', { line: r.line })}
                  title={t('asm.listing.bpHint')}
                  onClick={(e) => {
                    e.stopPropagation()
                    toggleBp(r.line)
                  }}
                />
                <span className="no">{first ? r.line : ''}</span>
                <span className="addr">
                  {r.addr != null &&
                    (flat ? (
                      <>
                        <span className="hi">{r.addr.slice(0, 8)}</span>
                        {r.addr.slice(8)}
                      </>
                    ) : (
                      <>
                        {r.seg != null && <span className="sg">{r.seg}:</span>}
                        {r.addr}
                      </>
                    ))}
                </span>
                <span className="by">{r.bytes}</span>
                <span className="src">{tasm ? tasmSpans(r.text) : lang ? lang.spans(r.text) : r.text}</span>
                <span className="hits">
                  {isExit && <span className="text-ok">{t('asm.listing.exit')} </span>}
                  {hits ? `×${fmtInt(hits)}` : ''}
                </span>
              </div>
            )
          })}
          <div style={{ height: win.padBottom }} />
        </div>
      </div>
      {ask.element}
      {menu.element}
    </section>
  )
}
