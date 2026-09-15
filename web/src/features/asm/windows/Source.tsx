/**
 * Source — редактор исходника TASM на CodeMirror 6.
 *
 * Здесь программу пишут; «Листинг» рядом показывает, как её выполнил процессор.
 * Поэтому в редакторе, кроме подсветки и номеров строк, есть ровно то, что
 * связывает текст с трассой: точки останова в поле слева (щелчок), ошибки
 * сборки волнистой чертой с текстом в подсказке, следующая команда трассы —
 * стрелкой и подсветкой строки, только что выполненная — точкой.
 *
 * Поиск, переход к строке и прочие диалоги — у каркаса модуля: он ставит
 * курсор через store (`setCursorLine`), а редактор к нему прокручивается.
 * Поэтому собственный поиск CodeMirror сюда не подключён — две разные панели
 * поиска на одно Ctrl+F путали бы.
 *
 * Точки останова — номера строк; когда над ними вставляют или удаляют строки,
 * точки едут вместе с текстом, а не остаются на прежних номерах.
 *
 * Цвета — переменные темы, как у соседних редакторов сайта.
 */
import { defaultKeymap, history, historyKeymap, indentWithTab, redo, undo } from '@codemirror/commands'
import { HighlightStyle, indentUnit, syntaxHighlighting } from '@codemirror/language'
import { Annotation, Compartment, EditorState, MapMode, RangeSetBuilder, StateEffect, StateField } from '@codemirror/state'
import {
  Decoration,
  EditorView,
  GutterMarker,
  drawSelection,
  gutter,
  highlightActiveLine,
  highlightActiveLineGutter,
  keymap,
  lineNumbers,
} from '@codemirror/view'
import { tags } from '@lezer/highlight'
import { useEffect, useMemo, useRef } from 'react'

import { useAsm } from '@/features/asm/store'
import type { AsmWindowProps } from '@/features/asm/types'
import { t as translate, useT } from '@/i18n'

import { hasTrace, hexFlat, nextOf, parseHex, textAnchor, useAnchorMenu, useSelectionAsk, useToolchainLanguage, type TextAnchor } from './format'
import { mnemonicOf, tasmLanguage } from './tasmLanguage'

/** Выделение редактора якорем `text`: главный диапазон и строки, которые он задевает. */
function selectedInView(view: EditorView): TextAnchor | null {
  const r = view.state.selection.main
  if (r.empty) return null
  const doc = view.state.doc
  const from = doc.lineAt(r.from).number
  const end = doc.lineAt(r.to)
  // Выделение, кончившееся в самом начале строки (Shift+↓, тройной щелчок), эту строку не задевает.
  const to = end.number > from && r.to === end.from ? end.number - 1 : end.number
  return textAnchor('source', view.state.sliceDoc(r.from, r.to), from, to)
}

/** Что отмечено в редакторе поверх текста, кроме сообщений сборки. */
interface Marks {
  bps: ReadonlySet<number>
  cur: number | null
  was: number | null
  /** Исходник изменён после сборки: подсказка сообщения говорит об этом. */
  stale: boolean
}

const NO_MARKS: Marks = { bps: new Set(), cur: null, was: null, stale: false }

const setMarks = StateEffect.define<Marks>()

const marksField = StateField.define<Marks>({
  create: () => NO_MARKS,
  update(value, tr) {
    for (const e of tr.effects) if (e.is(setMarks)) value = e.value
    return value
  },
})

/** Сообщение сборки в тексте: начало строки, на которую оно указывает. */
interface PlacedMessage {
  pos: number
  severity: 'error' | 'warning'
  text: string
}

const setMessages = StateEffect.define<readonly PlacedMessage[]>()

/**
 * Сообщения сборки держатся позициями в тексте, а не номерами строк, и каждая
 * правка их сдвигает (`mapPos`): вставили строки выше — подчёркивание уезжает
 * вместе с ошибочной строкой, Enter в начале строки уводит его вниз вместе с
 * текстом. Удалили начало строки — сообщение снимается: указывать ему больше
 * не на что.
 */
const messagesField = StateField.define<readonly PlacedMessage[]>({
  create: () => [],
  update(value, tr) {
    for (const e of tr.effects) if (e.is(setMessages)) return e.value
    if (!tr.docChanged || value.length === 0) return value
    const out: PlacedMessage[] = []
    for (const m of value) {
      const pos = tr.changes.mapPos(m.pos, 1, MapMode.TrackAfter)
      if (pos != null) out.push({ ...m, pos })
    }
    return out
  },
})

/**
 * Пометка «текст заменён снаружи» (пришла чужая версия исходника). Без неё
 * замена текста выглядела бы как набор с клавиатуры и тут же уехала бы в
 * службу обратно как правка человека.
 */
const СНАРУЖИ = Annotation.define<boolean>()

/** Подсветка строк: точка, ошибка, предупреждение, выполненная и следующая команда. */
const lineMarks = EditorView.decorations.compute([marksField, messagesField, 'doc'], (state) => {
  const m = state.field(marksField)
  const classes = new Map<number, string[]>()
  const titles = new Map<number, string>()
  const add = (n: number | null, cls: string) => {
    if (n == null || n < 1 || n > state.doc.lines) return
    const list = classes.get(n) ?? []
    list.push(cls)
    classes.set(n, list)
  }
  m.bps.forEach((n) => add(n, 'cm-asm-bp'))
  // Две ошибки могли съехаться на одну строку: ошибка важнее предупреждения.
  const messages = new Map<number, PlacedMessage>()
  for (const msg of state.field(messagesField)) {
    const n = state.doc.lineAt(Math.min(msg.pos, state.doc.length)).number
    const had = messages.get(n)
    if (!had || (had.severity === 'warning' && msg.severity === 'error')) messages.set(n, msg)
  }
  messages.forEach((msg, n) => {
    add(n, msg.severity === 'error' ? 'cm-asm-err' : 'cm-asm-warn')
    titles.set(n, m.stale ? translate('asm.source.staleMessage', { text: msg.text }) : msg.text)
  })
  add(m.was, 'cm-asm-was')
  add(m.cur, 'cm-asm-cur')
  const builder = new RangeSetBuilder<Decoration>()
  for (const n of [...classes.keys()].sort((a, b) => a - b)) {
    const from = state.doc.line(n).from
    const title = titles.get(n)
    builder.add(from, from, Decoration.line({ class: classes.get(n)!.join(' '), attributes: title ? { title } : {} }))
  }
  return builder.finish()
})

class DotMarker extends GutterMarker {
  constructor(private readonly cls: string) {
    super()
  }
  override eq(other: GutterMarker) {
    return other instanceof DotMarker && other.cls === this.cls
  }
  override toDOM() {
    const el = document.createElement('span')
    el.className = this.cls
    return el
  }
}

const bpMarker = new DotMarker('cm-asm-bp-dot')
const curMarker = new DotMarker('cm-asm-cur-arrow')
const wasMarker = new DotMarker('cm-asm-was-dot')

/** Поле точек останова: щелчок ставит и снимает точку строки. */
function breakpointGutter(onToggle: (line: number) => void) {
  return gutter({
    class: 'cm-asm-bp-gutter',
    lineMarker(view, line) {
      const m = view.state.field(marksField)
      const n = view.state.doc.lineAt(line.from).number
      if (m.cur === n) return curMarker
      if (m.bps.has(n)) return bpMarker
      if (m.was === n) return wasMarker
      return null
    },
    lineMarkerChange: (u) => u.transactions.some((tr) => tr.effects.some((e) => e.is(setMarks))),
    initialSpacer: () => bpMarker,
    domEventHandlers: {
      mousedown(view, line) {
        onToggle(view.state.doc.lineAt(line.from).number)
        return true
      },
    },
  })
}

const подсветка = HighlightStyle.define([
  { tag: tags.keyword, color: 'var(--code-kw)' },
  { tag: tags.function(tags.variableName), color: 'var(--code-fn)' },
  { tag: tags.special(tags.variableName), color: 'var(--ink-strong)' },
  { tag: tags.labelName, color: 'var(--ink-strong)', fontWeight: '600' },
  { tag: tags.variableName, color: 'var(--ink-strong)' },
  { tag: tags.number, color: 'var(--code-num)' },
  { tag: tags.string, color: 'var(--code-str)' },
  { tag: tags.lineComment, color: 'var(--code-comment)' },
])

const тема = EditorView.theme({
  '&': { height: '100%', color: 'var(--ink)', backgroundColor: 'transparent', fontSize: '12.5px' },
  '.cm-scroller': { fontFamily: 'var(--font-mono)', lineHeight: '19px' },
  '.cm-content': { caretColor: 'var(--accent)' },
  '.cm-cursor, .cm-dropCursor': { borderLeftColor: 'var(--accent)' },
  '.cm-gutters': { backgroundColor: 'var(--surface)', color: 'var(--muted)', border: 'none', borderRight: '1px solid var(--line)' },
  '.cm-activeLine': { backgroundColor: 'var(--asm-line-active)' },
  '.cm-activeLineGutter': { backgroundColor: 'transparent', color: 'var(--ink)' },
  '&.cm-focused': { outline: 'none' },
  // Селекторы — той же длины, что у базовой темы CodeMirror: её
  // `&light.cm-focused > .cm-scroller > .cm-selectionLayer .cm-selectionBackground`
  // (#d7d4f0) иначе перебивает короткое правило, и на тёмной теме выделение
  // выходит почти белым. Редактор не знает, светлая тема сайта или тёмная, —
  // цвет берётся из переменной темы.
  '& > .cm-scroller > .cm-selectionLayer .cm-selectionBackground, &.cm-focused > .cm-scroller > .cm-selectionLayer .cm-selectionBackground':
    { background: 'var(--asm-selection)' },
  '.cm-content ::selection': { color: 'var(--ink)' },
  '.cm-asm-bp-gutter .cm-gutterElement': { width: '18px', display: 'grid', placeItems: 'center', cursor: 'pointer', padding: '0' },
  '.cm-asm-bp-gutter .cm-gutterElement:hover': { backgroundColor: 'var(--err-bg)' },
  '.cm-asm-bp-dot': { display: 'block', width: '9px', height: '9px', borderRadius: '50%', backgroundColor: 'var(--err)' },
  '.cm-asm-cur-arrow': {
    display: 'block',
    width: '0',
    height: '0',
    borderLeft: '7px solid var(--accent)',
    borderTop: '5px solid transparent',
    borderBottom: '5px solid transparent',
  },
  '.cm-asm-was-dot': { display: 'block', width: '4px', height: '4px', borderRadius: '50%', backgroundColor: 'var(--muted)' },
  '.cm-line.cm-asm-bp': { backgroundColor: 'var(--err-bg)' },
  '.cm-line.cm-asm-err': { backgroundColor: 'var(--err-bg)', textDecoration: 'underline wavy var(--err)', textUnderlineOffset: '4px' },
  '.cm-line.cm-asm-warn': { textDecoration: 'underline wavy var(--warn)', textUnderlineOffset: '4px' },
  '.cm-line.cm-asm-cur': { backgroundColor: 'var(--accent-bg)' },
})

/** Сколько последних отправленных версий помнить, чтобы не принять своё же эхо за чужую правку. */
const SENT_MEMORY = 32

export default function Source({ active }: AsmWindowProps) {
  const t = useT()
  const asm = useAsm()
  const { program, run, step, stepIndex, settings, cursorLine, toolchain } = asm
  const tasm = toolchain.id === 'tasm'
  const menu = useAnchorMenu()
  // Подсветка: у TASM — как была, сразу; у остальных режимов — описателя,
  // лениво, и подставляется в редактор, когда загрузится.
  const lang = useToolchainLanguage()
  const langRef = useRef(lang)
  langRef.current = lang
  const langSlot = useRef(new Compartment())
  const mnemonic = (text: string) => (latest.current.toolchain.id === 'tasm' ? mnemonicOf(text) : (langRef.current?.mnemonicOf(text) ?? null))
  const host = useRef<HTMLDivElement | null>(null)
  const viewRef = useRef<EditorView | null>(null)
  // Store и меню держим ссылками: редактор создаётся один раз, а его
  // обработчики должны видеть свежие точки останова и курсор.
  const latest = useRef(asm)
  latest.current = asm
  const openMenu = useRef(menu.open)
  openMenu.current = menu.open
  const sent = useRef<string[]>([])
  const loaded = program != null
  const sectionRef = useRef<HTMLElement | null>(null)

  // Выделение редактора живёт в его состоянии и остаётся нарисованным и без
  // фокуса. Кнопка и Ctrl+J берут его, только пока фокус в окне (в редакторе
  // или на самой кнопке): ушёл человек в другое окно — спрашивает уже о другом.
  const ask = useSelectionAsk({
    window: 'source',
    active,
    root: sectionRef,
    read: () => {
      const view = viewRef.current
      const root = sectionRef.current
      if (!view || !root || !root.contains(document.activeElement)) return null
      const anchor = selectedInView(view)
      if (!anchor) return null
      const c = view.coordsAtPos(view.state.selection.main.head)
      const b = view.scrollDOM.getBoundingClientRect()
      return {
        anchor,
        at: c && { left: c.left, right: c.right, top: c.top, bottom: c.bottom },
        bounds: { left: b.left, right: b.right, top: b.top, bottom: b.bottom },
      }
    },
  })
  const askUpdate = useRef(ask.update)
  askUpdate.current = ask.update

  useEffect(() => {
    if (!host.current || !loaded) return
    const toggle = (line: number) => {
      const a = latest.current
      const list = a.settings.breakpoints
      a.updateSettings({ breakpoints: list.includes(line) ? list.filter((l) => l !== line) : [...list, line].sort((x, y) => x - y) })
    }
    const state = EditorState.create({
      doc: latest.current.program?.source ?? '',
      extensions: [
        marksField,
        messagesField,
        breakpointGutter(toggle),
        lineNumbers(),
        history(),
        drawSelection(),
        highlightActiveLine(),
        highlightActiveLineGutter(),
        indentUnit.of('        '),
        EditorState.tabSize.of(8),
        langSlot.current.of(latest.current.toolchain.id === 'tasm' ? tasmLanguage : (langRef.current?.language ?? [])),
        syntaxHighlighting(подсветка),
        тема,
        lineMarks,
        // Ctrl+Enter — «собрать и запустить» у каркаса; вставку пустой строки по нему убираем.
        keymap.of([...defaultKeymap.filter((b) => b.key !== 'Mod-Enter'), ...historyKeymap, indentWithTab]),
        EditorView.updateListener.of((u) => {
          const a = latest.current
          if (u.docChanged && !u.transactions.some((tr) => tr.annotation(СНАРУЖИ))) {
            const text = u.state.doc.toString()
            sent.current = [...sent.current.slice(-(SENT_MEMORY - 1)), text]
            a.setSource(text)
            const bps = a.settings.breakpoints
            if (bps.length > 0) {
              const moved = [
                ...new Set(
                  bps
                    .filter((n) => n <= u.startState.doc.lines)
                    .map((n) => u.state.doc.lineAt(u.changes.mapPos(u.startState.doc.line(n).from, 1)).number),
                ),
              ].sort((x, y) => x - y)
              if (moved.join(',') !== bps.join(',')) a.updateSettings({ breakpoints: moved })
            }
          }
          if (u.selectionSet && u.view.hasFocus) {
            const n = u.state.doc.lineAt(u.state.selection.main.head).number
            if (n !== a.cursorLine) a.setCursorLine(n)
          }
          if (u.selectionSet || u.focusChanged || u.geometryChanged) askUpdate.current()
        }),
        EditorView.domEventHandlers({
          mousedown(e, view) {
            if (e.button !== 0) return false
            const pos = view.posAtCoords({ x: e.clientX, y: e.clientY })
            if (pos != null) latest.current.select({ kind: 'line', line: view.state.doc.lineAt(pos).number })
            return false
          },
          contextmenu(e, view) {
            const pos = view.posAtCoords({ x: e.clientX, y: e.clientY })
            if (pos == null) return false
            const line = view.state.doc.lineAt(pos)
            openMenu.current(e, { kind: 'line', line: line.number }, mnemonic(line.text), selectedInView(view))
            return true
          },
        }),
        EditorView.contentAttributes.of({ 'aria-label': t(latest.current.toolchain.id === 'tasm' ? 'asm.source.aria' : 'asm64.source.aria') }),
      ],
    })
    const view = new EditorView({ state, parent: host.current })
    viewRef.current = view
    return () => {
      view.destroy()
      viewRef.current = null
    }
    // Редактор создаётся один раз на загруженную программу: текст, отметки и
    // курсор приходят в него отдельными эффектами ниже.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loaded])

  // Подсветка режима загрузилась позже редактора — подставить.
  useEffect(() => {
    const view = viewRef.current
    if (!view || tasm || !lang) return
    view.dispatch({ effects: langSlot.current.reconfigure(lang.language) })
  }, [lang, tasm, loaded])

  // Сообщения сборки встают на строки, когда пришёл прогон или текст заменили
  // снаружи, а дальше едут с правками сами (`messagesField`). Номер сборки
  // переводится в нынешний через store: исходник мог измениться ещё до того,
  // как окно открыли, и старый номер указал бы на чужую строку.
  const placeMessages = useRef(() => {})
  placeMessages.current = () => {
    const view = viewRef.current
    if (!view) return
    const a = latest.current
    const doc = view.state.doc
    const placed: PlacedMessage[] = []
    for (const m of a.run?.build?.messages ?? []) {
      if (m.line == null) continue
      const n = a.sourceLineOf(m.line)
      if (n == null || n > doc.lines) continue
      placed.push({ pos: doc.line(n).from, severity: m.severity, text: m.text })
    }
    view.dispatch({ effects: setMessages.of(placed) })
  }
  const buildMessages = run?.build?.messages
  const builtFrom = run?.source
  useEffect(() => {
    placeMessages.current()
  }, [buildMessages, builtFrom, loaded])

  // Чужая версия исходника (правка в другой вкладке, ответ 409) — заменить текст.
  // Своё эхо — версию, которую редактор сам только что отдал в store, — не трогаем:
  // иначе запоздавший ответ сохранения откатывал бы набранное после него.
  const source = program?.source
  useEffect(() => {
    const view = viewRef.current
    if (!view || source == null) return
    const now = view.state.doc.toString()
    if (now === source || sent.current.includes(source)) return
    view.dispatch({ changes: { from: 0, to: now.length, insert: source }, annotations: СНАРУЖИ.of(true) })
    // Замена целиком снимает все сообщения — ставим их заново по новому тексту.
    placeMessages.current()
  }, [source])

  // Строки трассы — тоже номера сборки.
  const trace = hasTrace(run)
  const { sourceLineOf, buildStale } = asm
  const nextLine = trace ? (nextOf(step)?.line ?? null) : null
  const doneLine = trace && stepIndex > 0 ? (step?.line ?? null) : null
  const cur = nextLine == null ? null : sourceLineOf(nextLine)
  const was = doneLine == null ? null : sourceLineOf(doneLine)
  // Плоская память: адрес следующей команды 16 знаками рядом с именем программы.
  const nextIp = trace && toolchain.memory === 'flat' ? parseHex(nextOf(step)?.ip) : null

  const marks = useMemo<Marks>(
    () => ({ bps: new Set(settings.breakpoints), cur, was, stale: buildStale }),
    [settings.breakpoints, cur, was, buildStale],
  )

  useEffect(() => {
    viewRef.current?.dispatch({ effects: setMarks.of(marks) })
  }, [marks, loaded])

  // Шаг сменился — следующая команда должна быть видна, если человек сейчас не печатает.
  useEffect(() => {
    const view = viewRef.current
    if (!view || cur == null || cur > view.state.doc.lines || view.hasFocus) return
    view.dispatch({ effects: EditorView.scrollIntoView(view.state.doc.line(cur).from, { y: 'nearest' }) })
  }, [cur, stepIndex])

  // Курсор поставили снаружи (Ctrl+G, «Найти», сообщение сборки) — перейти к строке.
  useEffect(() => {
    const view = viewRef.current
    if (!view || cursorLine == null || cursorLine < 1 || cursorLine > view.state.doc.lines) return
    const here = view.state.doc.lineAt(view.state.selection.main.head).number
    if (here === cursorLine) return
    const from = view.state.doc.line(cursorLine).from
    view.dispatch({ selection: { anchor: from }, effects: EditorView.scrollIntoView(from, { y: 'center' }) })
  }, [cursorLine, loaded])

  // «Правка → Отменить/Повторить» в строке меню: меню не знает про редактор и
  // шлёт событие, а историю правок держит сам редактор.
  useEffect(() => {
    const onCommand = (e: Event) => {
      const view = viewRef.current
      if (!view) return
      const what = (e as CustomEvent<unknown>).detail
      if (what === 'undo') undo(view)
      else if (what === 'redo') redo(view)
    }
    window.addEventListener('asm:editor', onCommand)
    return () => window.removeEventListener('asm:editor', onCommand)
  }, [])

  // Вкладка стала видимой — размеры могли смениться, пока редактор был скрыт.
  useEffect(() => {
    if (active) viewRef.current?.requestMeasure()
  }, [active])

  return (
    <section ref={sectionRef} className="relative flex h-full min-h-0 flex-col" aria-label={t('asm.tabs.source')}>
      <div className="pt">
        <span className="m truncate text-ink">{program?.name ?? ''}</span>
        {nextIp != null && <span className="m">{`${t('asm64.slider.addrLabel')} ${hexFlat(nextIp)}`}</span>}
        <span className="grow" />
        <span className="m">{t(tasm ? 'asm.source.hint' : 'asm64.source.hint')}</span>
      </div>
      {loaded ? <div ref={host} className="min-h-0 flex-1 overflow-hidden" /> : <div className="empty">{t('asm.source.loading')}</div>}
      {ask.element}
      {menu.element}
    </section>
  )
}
