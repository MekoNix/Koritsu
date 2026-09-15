/**
 * CardView — текст карточки: безопасное подмножество Markdown и формулы.
 *
 *     <CardView md={card.q} className="text-lg" />
 *
 * **Что показывается.** Абзацы (перенос строки внутри абзаца сохраняется), **жирный**,
 * *курсив*, `код`, блоки кода, списки, таблицы, цитаты, формулы `$…$` и `$$…$$`.
 * Больше ничего: сырого HTML, картинок и ссылок в формате карточек нет.
 *
 * **Почему свой разбор, а не библиотека Markdown.** Текст карточки — недоверенный:
 * его пишет чужой человек или агент. Разбор здесь строит элементы React и нигде не
 * вставляет текст разметкой, поэтому `<script>`, `<img onerror>` или `[x](javascript:…)`
 * показываются буквами, как написаны. Служба режет то же самое при загрузке; сайт
 * держит правило сам, а не надеется на это.
 *
 * **Формулы — MathLive**, тот же пакет, что у доски: `convertLatexToMarkup` строит
 * вёрстку в стиле KaTeX, шрифты KaTeX приезжают со своего сервера вместе со
 * `mathlive/static.css`. Пакет тяжёлый и грузится по требованию: карточка без формул
 * за него не платит, а пока он в пути, формула видна исходником. Команды, которые
 * дают ссылку, класс, стиль или атрибут (`\href`, `\url`, `\class`, `\htmlData` …),
 * не рисуются — формула остаётся исходником; готовая вёрстка с `<a>`, `on…=` или
 * `javascript:` не вставляется.
 *
 * **Ширина.** Формула или таблица шире карточки прокручивается внутри своего блока, а
 * длинные слова переносятся: страница на телефоне не получает горизонтальной прокрутки.
 */
import 'mathlive/static.css'

import { useEffect, useMemo, useState, type ReactNode } from 'react'

import { cn } from '@/lib/cn'

// ── формулы ──────────────────────────────────────────────────────────────────

type Convert = (latex: string, options?: { defaultMode?: 'math' | 'inline-math' | 'text' }) => string

let загрузка: Promise<Convert> | null = null
let готовый: Convert | null = null

function загрузитьMathLive(): Promise<Convert> {
  загрузка ??= import('mathlive').then((модуль) => {
    готовый = модуль.convertLatexToMarkup as unknown as Convert
    return готовый
  })
  return загрузка
}

/** Команды LaTeX, которые выводят за пределы формулы: ссылки, классы, стили, атрибуты, файлы, макросы. */
const ЗАПРЕТНЫЕ_КОМАНДЫ =
  /\\(href|url|htmlData|htmlClass|htmlId|htmlStyle|cssId|class|style|includegraphics|input|include|def|gdef|edef|let|newcommand|renewcommand|providecommand)(?![A-Za-z])/

const ОПАСНАЯ_ВЁРСТКА = /<(a|script|iframe|img|object|embed|link|style|svg:script|form|input)\b|\son[a-z]+\s*=|javascript:|data:text/i

const КЭШ_ПОТОЛОК = 800
const кэш = new Map<string, string | null>()

function вёрстка(convert: Convert, tex: string, display: boolean): string | null {
  const ключ = `${display ? 'D' : 'I'}${tex}`
  const было = кэш.get(ключ)
  if (было !== undefined) return было
  let html: string | null = null
  if (!ЗАПРЕТНЫЕ_КОМАНДЫ.test(tex)) {
    try {
      const готово = convert(tex, { defaultMode: display ? 'math' : 'inline-math' })
      html = ОПАСНАЯ_ВЁРСТКА.test(готово) ? null : готово
    } catch {
      html = null
    }
  }
  if (кэш.size > КЭШ_ПОТОЛОК) кэш.clear()
  кэш.set(ключ, html)
  return html
}

function useConvert(нужно: boolean): Convert | null {
  const [convert, setConvert] = useState<Convert | null>(() => готовый)
  useEffect(() => {
    if (!нужно || convert) return
    let живо = true
    загрузитьMathLive().then(
      (f) => живо && setConvert(() => f),
      () => {
        // Пакет не загрузился — формулы остаются исходником, текст карточки читается.
      },
    )
    return () => {
      живо = false
    }
  }, [нужно, convert])
  return convert
}

function Формула({ tex, display, convert }: { tex: string; display: boolean; convert: Convert | null }) {
  const исходник = display ? `$$${tex}$$` : `$${tex}$`
  if (!convert) {
    return (
      <span className={cn('font-mono text-[0.9em] text-muted', display && 'block overflow-x-auto whitespace-pre py-1')}>
        {исходник}
      </span>
    )
  }
  const html = вёрстка(convert, tex, display)
  if (html === null) {
    return (
      <code className={cn('rounded-sm bg-surface-2 px-1 font-mono text-[0.9em] text-ink', display && 'block overflow-x-auto whitespace-pre py-1')}>
        {исходник}
      </code>
    )
  }
  return display ? (
    <span
      role="math"
      aria-label={tex}
      className="my-1 block max-w-full overflow-x-auto overflow-y-hidden py-1 text-center"
      dangerouslySetInnerHTML={{ __html: html }}
    />
  ) : (
    <span
      role="math"
      aria-label={tex}
      className="inline-block max-w-full overflow-x-auto overflow-y-hidden align-middle"
      dangerouslySetInnerHTML={{ __html: html }}
    />
  )
}

// ── разбор блоков ────────────────────────────────────────────────────────────

type Выравнивание = 'left' | 'center' | 'right' | null

type Блок =
  | { k: 'p'; text: string }
  | { k: 'h'; text: string }
  | { k: 'code'; text: string }
  | { k: 'math'; tex: string }
  | { k: 'hr' }
  | { k: 'quote'; blocks: Блок[] }
  | { k: 'list'; ordered: boolean; start: number; items: Блок[][] }
  | { k: 'table'; head: string[]; align: Выравнивание[]; rows: string[][] }

const ОГРАДА = /^\s{0,3}(`{3,}|~{3,})/
const ПУНКТ = /^(\s*)([-*+]|\d{1,9}[.)])\s+(.*)$/
const ЧЕРТА = /^\s{0,3}([-*_])(\s*\1){2,}\s*$/
const ЗАГОЛОВОК = /^\s{0,3}#{1,6}\s+(.*?)\s*#*\s*$/
const РАЗДЕЛИТЕЛЬ_ТАБЛИЦЫ = /^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$/
const ГЛУБИНА = 8

function отступ(line: string): number {
  return line.length - line.trimStart().length
}

function началоТаблицы(line: string, next: string | undefined): boolean {
  return line.includes('|') && next !== undefined && next.includes('-') && РАЗДЕЛИТЕЛЬ_ТАБЛИЦЫ.test(next)
}

function началоБлока(line: string, next: string | undefined): boolean {
  const t = line.trim()
  return (
    ОГРАДА.test(line) ||
    t.startsWith('$$') ||
    t.startsWith('>') ||
    ПУНКТ.test(line) ||
    ЗАГОЛОВОК.test(line) ||
    ЧЕРТА.test(line) ||
    началоТаблицы(line, next)
  )
}

/** Ячейки строки таблицы: `|` внутри `кода` и `$формулы$` ячейку не делит, `\|` вне формулы — буква. */
function ячейки(line: string): string[] {
  let s = line.trim()
  if (s.startsWith('|')) s = s.slice(1)
  if (s.endsWith('|') && !s.endsWith('\\|')) s = s.slice(0, -1)
  const out: string[] = []
  let buf = ''
  let код = false
  let формула = false
  for (let i = 0; i < s.length; i++) {
    const ch = s[i] ?? ''
    if (ch === '\\' && s[i + 1] === '|') {
      buf += формула ? '\\|' : '|'
      i++
      continue
    }
    if (ch === '`' && !формула) код = !код
    else if (ch === '$' && !код) формула = !формула
    if (ch === '|' && !код && !формула) {
      out.push(buf.trim())
      buf = ''
      continue
    }
    buf += ch
  }
  out.push(buf.trim())
  return out
}

function выравнивание(sep: string): Выравнивание[] {
  return ячейки(sep).map((c) => {
    const л = c.startsWith(':')
    const п = c.endsWith(':')
    return л && п ? 'center' : п ? 'right' : л ? 'left' : null
  })
}

function разобрать(lines: string[], глубина = 0): Блок[] {
  const out: Блок[] = []
  let i = 0
  while (i < lines.length) {
    const line = lines[i] ?? ''
    const t = line.trim()
    if (!t) {
      i++
      continue
    }

    // Блок кода: до закрывающей ограды того же вида или до конца текста.
    const ограда = ОГРАДА.exec(line)
    if (ограда) {
      const знак = ограда[1] ?? '```'
      const тело: string[] = []
      i++
      while (i < lines.length && !(lines[i] ?? '').trimStart().startsWith(знак)) {
        тело.push(lines[i] ?? '')
        i++
      }
      i++
      out.push({ k: 'code', text: тело.join('\n') })
      continue
    }

    // Формула отдельным блоком: `$$…$$` в одну строку или на нескольких.
    if (t.startsWith('$$')) {
      const хвост = t.slice(2)
      if (хвост.length > 2 && хвост.endsWith('$$')) {
        out.push({ k: 'math', tex: хвост.slice(0, -2).trim() })
        i++
        continue
      }
      const исходные = [line]
      const тело = [хвост]
      let закрыта = false
      let j = i + 1
      while (j < lines.length) {
        const l = lines[j] ?? ''
        исходные.push(l)
        if (l.trimEnd().endsWith('$$')) {
          тело.push(l.trimEnd().slice(0, -2))
          закрыта = true
          j++
          break
        }
        тело.push(l)
        j++
      }
      if (закрыта) {
        out.push({ k: 'math', tex: тело.join('\n').trim() })
        i = j
        continue
      }
      // Незакрытая формула — абзацем, как написана.
      out.push({ k: 'p', text: line })
      i++
      continue
    }

    if (ЧЕРТА.test(line)) {
      out.push({ k: 'hr' })
      i++
      continue
    }

    const заголовок = ЗАГОЛОВОК.exec(line)
    if (заголовок) {
      out.push({ k: 'h', text: заголовок[1] ?? '' })
      i++
      continue
    }

    if (t.startsWith('>')) {
      const тело: string[] = []
      while (i < lines.length && (lines[i] ?? '').trim().startsWith('>')) {
        тело.push((lines[i] ?? '').replace(/^\s*>\s?/, ''))
        i++
      }
      out.push(глубина < ГЛУБИНА ? { k: 'quote', blocks: разобрать(тело, глубина + 1) } : { k: 'p', text: тело.join('\n') })
      continue
    }

    if (началоТаблицы(line, lines[i + 1])) {
      const head = ячейки(line)
      const align = выравнивание(lines[i + 1] ?? '')
      const rows: string[][] = []
      i += 2
      while (i < lines.length && (lines[i] ?? '').trim() && (lines[i] ?? '').includes('|')) {
        rows.push(ячейки(lines[i] ?? ''))
        i++
      }
      out.push({ k: 'table', head, align, rows })
      continue
    }

    const пункт = ПУНКТ.exec(line)
    if (пункт && глубина < ГЛУБИНА) {
      const уровень = (пункт[1] ?? '').length
      const ordered = /\d/.test(пункт[2] ?? '')
      const start = ordered ? parseInt(пункт[2] ?? '1', 10) || 1 : 1
      const items: string[][] = []
      while (i < lines.length) {
        const l = lines[i] ?? ''
        const m = ПУНКТ.exec(l)
        if (m && (m[1] ?? '').length <= уровень + 1) {
          if (/\d/.test(m[2] ?? '') !== ordered) break
          items.push([m[3] ?? ''])
          i++
          continue
        }
        const текущий = items[items.length - 1]
        if (!текущий) break
        if (!l.trim()) {
          // Пустая строка внутри списка: продолжаем, только если дальше вложенное содержимое.
          let k = i + 1
          while (k < lines.length && !(lines[k] ?? '').trim()) k++
          const дальше = lines[k]
          if (дальше !== undefined && отступ(дальше) > уровень) {
            текущий.push('')
            i++
            continue
          }
          break
        }
        if (отступ(l) > уровень) {
          текущий.push(l.slice(Math.min(отступ(l), уровень + 2)))
          i++
          continue
        }
        if (началоБлока(l, lines[i + 1])) break
        текущий.push(l.trim())
        i++
      }
      out.push({ k: 'list', ordered, start, items: items.map((item) => разобрать(item, глубина + 1)) })
      continue
    }

    // Абзац: до пустой строки или начала другого блока.
    const абзац = [line]
    i++
    while (i < lines.length && (lines[i] ?? '').trim() && !началоБлока(lines[i] ?? '', lines[i + 1])) {
      абзац.push(lines[i] ?? '')
      i++
    }
    out.push({ k: 'p', text: абзац.map((l) => l.trim()).join('\n') })
  }
  return out
}

// ── разбор строки ────────────────────────────────────────────────────────────

const ЭКРАНИРУЕМЫЕ = /[\\`*_{}[\]()#+\-.!|$>~]/
const БУКВА = /[\p{L}\p{N}]/u

/** Закрывающий `$` строчной формулы: не экранирован, без пробела у краёв, за ним не цифра. */
function конецФормулы(text: string, from: number): number {
  if (text[from] === ' ' || from >= text.length) return -1
  for (let j = from; j < text.length; j++) {
    if (text[j] !== '$' || text[j - 1] === '\\') continue
    if (j === from || text[j - 1] === ' ') continue
    if (/\d/.test(text[j + 1] ?? '')) continue
    return j
  }
  return -1
}

/** Закрывающий одиночный `*` или `_` курсива. */
function конецКурсива(text: string, from: number, знак: string): number {
  if (text[from] === ' ' || text[from] === знак) return -1
  for (let j = from + 1; j < text.length; j++) {
    if (text[j] !== знак || text[j - 1] === '\\' || text[j - 1] === ' ') continue
    if (text[j + 1] === знак) {
      j++
      continue
    }
    if (знак === '_' && БУКВА.test(text[j + 1] ?? '')) continue
    return j
  }
  return -1
}

function строка(text: string, convert: Convert | null, глубина = 0): ReactNode[] {
  if (глубина > ГЛУБИНА) return [text]
  const out: ReactNode[] = []
  let buf = ''
  const сбросить = () => {
    if (buf) out.push(buf)
    buf = ''
  }
  let i = 0
  while (i < text.length) {
    const ch = text[i] ?? ''

    if (ch === '\\' && ЭКРАНИРУЕМЫЕ.test(text[i + 1] ?? '')) {
      buf += text[i + 1]
      i += 2
      continue
    }

    if (ch === '\n') {
      сбросить()
      out.push(<br key={`b${out.length}`} />)
      i++
      continue
    }

    if (ch === '`') {
      let n = 1
      while (text[i + n] === '`') n++
      const знак = '`'.repeat(n)
      const конец = text.indexOf(знак, i + n)
      if (конец > i + n - 1 && конец !== -1) {
        сбросить()
        out.push(
          <code key={`c${out.length}`} className="rounded-sm bg-surface-2 px-1 py-px font-mono text-[0.9em] text-ink-strong">
            {text.slice(i + n, конец)}
          </code>,
        )
        i = конец + n
        continue
      }
      buf += знак
      i += n
      continue
    }

    if (ch === '$') {
      if (text[i + 1] === '$') {
        const конец = text.indexOf('$$', i + 2)
        if (конец > i + 2) {
          сбросить()
          out.push(<Формула key={`m${out.length}`} tex={text.slice(i + 2, конец).trim()} display convert={convert} />)
          i = конец + 2
          continue
        }
        buf += '$$'
        i += 2
        continue
      }
      const конец = конецФормулы(text, i + 1)
      if (конец > i + 1) {
        сбросить()
        out.push(<Формула key={`m${out.length}`} tex={text.slice(i + 1, конец)} display={false} convert={convert} />)
        i = конец + 1
        continue
      }
      buf += ch
      i++
      continue
    }

    if (ch === '*' || ch === '_') {
      const слева = text[i - 1] ?? ''
      const внутриСлова = ch === '_' && БУКВА.test(слева)
      if (!внутриСлова && text[i + 1] === ch) {
        const конец = text.indexOf(ch + ch, i + 2)
        if (конец > i + 2 && text[i + 2] !== ' ') {
          сбросить()
          out.push(
            <strong key={`s${out.length}`} className="font-semibold text-ink-strong">
              {строка(text.slice(i + 2, конец), convert, глубина + 1)}
            </strong>,
          )
          i = конец + 2
          continue
        }
      } else if (!внутриСлова) {
        const конец = конецКурсива(text, i + 1, ch)
        if (конец > i + 1) {
          сбросить()
          out.push(<em key={`e${out.length}`}>{строка(text.slice(i + 1, конец), convert, глубина + 1)}</em>)
          i = конец + 1
          continue
        }
      }
    }

    buf += ch
    i++
  }
  сбросить()
  return out
}

// ── показ ────────────────────────────────────────────────────────────────────

const ВЫРАВНИВАНИЕ_КЛАСС: Record<Exclude<Выравнивание, null>, string> = {
  left: 'text-left',
  center: 'text-center',
  right: 'text-right',
}

function Блоки({ blocks, convert, tight = false }: { blocks: Блок[]; convert: Convert | null; tight?: boolean }) {
  return (
    <>
      {blocks.map((b, n) => {
        switch (b.k) {
          case 'p':
            return tight && blocks.length === 1 ? (
              <span key={n}>{строка(b.text, convert)}</span>
            ) : (
              <p key={n} className="m-0">
                {строка(b.text, convert)}
              </p>
            )
          case 'h':
            return (
              <p key={n} className="m-0 font-semibold text-ink-strong">
                {строка(b.text, convert)}
              </p>
            )
          case 'code':
            return (
              <pre
                key={n}
                className="m-0 max-w-full overflow-x-auto rounded-sm border border-line bg-surface-2 px-s3 py-s2 font-mono text-[0.85em] leading-snug text-ink"
              >
                <code>{b.text}</code>
              </pre>
            )
          case 'math':
            return <Формула key={n} tex={b.tex} display convert={convert} />
          case 'hr':
            return <hr key={n} className="my-1 border-0 border-t border-line" />
          case 'quote':
            return (
              <blockquote key={n} className="m-0 flex flex-col gap-s2 border-l-2 border-line-strong pl-s3 text-muted">
                <Блоки blocks={b.blocks} convert={convert} />
              </blockquote>
            )
          case 'list': {
            const Список = b.ordered ? 'ol' : 'ul'
            return (
              <Список
                key={n}
                start={b.ordered && b.start !== 1 ? b.start : undefined}
                className={cn('m-0 flex flex-col gap-1 pl-s5', b.ordered ? 'list-decimal' : 'list-disc')}
              >
                {b.items.map((item, m) => (
                  <li key={m} className="pl-1">
                    <div className="flex min-w-0 flex-col gap-1">
                      <Блоки blocks={item} convert={convert} tight />
                    </div>
                  </li>
                ))}
              </Список>
            )
          }
          case 'table':
            return (
              <div key={n} className="max-w-full overflow-x-auto">
                <table className="border-collapse text-[0.92em]">
                  <thead>
                    <tr>
                      {b.head.map((c, m) => (
                        <th
                          key={m}
                          className={cn(
                            'border border-line bg-surface-2 px-s2 py-1 font-semibold text-ink-strong',
                            ВЫРАВНИВАНИЕ_КЛАСС[b.align[m] ?? 'left'],
                          )}
                        >
                          {строка(c, convert)}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {b.rows.map((row, r) => (
                      <tr key={r}>
                        {b.head.map((_, m) => (
                          <td key={m} className={cn('border border-line px-s2 py-1 align-top', ВЫРАВНИВАНИЕ_КЛАСС[b.align[m] ?? 'left'])}>
                            {строка(row[m] ?? '', convert)}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )
        }
      })}
    </>
  )
}

export type CardViewProps = {
  /** Текст карточки: вопрос, ответ или разбор. */
  md: string
  className?: string
}

export function CardView({ md, className }: CardViewProps) {
  const blocks = useMemo(() => разобрать((md ?? '').normalize('NFC').replace(/\r\n?/g, '\n').split('\n')), [md])
  const естьФормулы = useMemo(() => (md ?? '').includes('$'), [md])
  const convert = useConvert(естьФормулы)
  return (
    <div className={cn('flex min-w-0 max-w-full flex-col gap-s2 break-words leading-normal [overflow-wrap:anywhere]', className)}>
      <Блоки blocks={blocks} convert={convert} />
    </div>
  )
}
