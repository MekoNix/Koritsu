/**
 * JsonEditor — правка значения тега текстовым JSON (CodeMirror + `lang-json`).
 *
 * Нетекстовые теги правятся так намеренно: не форма по типу, а
 * текст. Форма на каждый тип — это пять разных экранов (таблица с добавлением
 * колонок, выбор картинки, редактор формул), и до них дело дойдёт; JSON же
 * показывает ровно то, что уедет в службу, и не врёт ни в одном поле.
 *
 * Почему CodeMirror, а не `<textarea>`: в тексте таблицы на двадцать строк
 * пропущенная скобка ищется глазами полчаса. Здесь её показывают подсветка,
 * подсветка парных скобок и номер строки. Пакет уже стоит (`features/diagrams`),
 * так что цена — только грамматика JSON.
 *
 * Цвета — переменные темы, как у соседа: вторая палитра разъехалась бы с первой
 * на первой же новой теме.
 */
import { defaultKeymap, history, historyKeymap, indentWithTab } from '@codemirror/commands'
import { json } from '@codemirror/lang-json'
import {
  HighlightStyle,
  bracketMatching,
  indentUnit,
  syntaxHighlighting,
} from '@codemirror/language'
import { Annotation, Compartment, EditorState } from '@codemirror/state'
import {
  EditorView,
  drawSelection,
  highlightActiveLine,
  highlightActiveLineGutter,
  keymap,
  lineNumbers,
} from '@codemirror/view'
import { tags } from '@lezer/highlight'
import { useEffect, useRef } from 'react'

/** Подсветка JSON: имя поля, строка, число, `true`/`false`/`null`. */
const подсветка = HighlightStyle.define([
  { tag: tags.propertyName, color: 'var(--code-kw, var(--accent))' },
  { tag: [tags.string, tags.special(tags.string)], color: 'var(--code-str, var(--ok))' },
  { tag: tags.number, color: 'var(--code-num, var(--warn))' },
  { tag: [tags.bool, tags.null], color: 'var(--code-num, var(--warn))' },
  { tag: tags.punctuation, color: 'var(--muted)' },
])

/**
 * Пометка «текст заменён снаружи, а не набран рукой».
 *
 * CodeMirror не различает, откуда пришла правка: замена текста через
 * `dispatch` поднимает `docChanged` ровно так же, как нажатие клавиши. Без
 * пометки родитель считал бы своё же обновление правкой человека и помечал
 * поле «изменённым» — а «изменённое» поле он потом отказывается перезаписывать
 * пришедшим с сервера значением (чтобы не терять набранное) и уносит его в
 * службу по первому уходу из поля. То есть открытая заготовка пустого тега
 * затирала бы то, что в теге уже лежит.
 */
const СНАРУЖИ = Annotation.define<boolean>()

/**
 * Запрет правки: и состоянию (`readOnly`), и виду (`editable`).
 *
 * Одного мало: `readOnly` не пускает изменения, но поле остаётся
 * редактируемым для браузера — курсор в нём мигает, а буквы не появляются, и
 * человек решает, что сломалась клавиатура.
 */
function правка_запрещена(да: boolean) {
  return [EditorState.readOnly.of(да), EditorView.editable.of(!да)]
}

const тема = EditorView.theme({
  '&': {
    height: '100%',
    color: 'var(--ink)',
    backgroundColor: 'transparent',
    fontSize: 'var(--size-sm)',
  },
  '.cm-scroller': { fontFamily: 'var(--font-mono)', lineHeight: 'var(--leading-normal)' },
  '.cm-content': { caretColor: 'var(--accent)' },
  '.cm-cursor, .cm-dropCursor': { borderLeftColor: 'var(--accent)' },
  '.cm-gutters': {
    backgroundColor: 'transparent',
    color: 'var(--muted)',
    border: 'none',
    paddingRight: '4px',
  },
  '.cm-activeLine': { backgroundColor: 'var(--surface-2)' },
  '.cm-activeLineGutter': { backgroundColor: 'transparent', color: 'var(--ink)' },
  '&.cm-focused': { outline: 'none' },
  '&.cm-focused .cm-selectionBackground, .cm-selectionBackground, ::selection': {
    backgroundColor: 'var(--accent-bg)',
  },
})

export type JsonEditorProps = {
  value: string
  onChange: (value: string) => void
  /** Правка запрещена: идёт прогон или роли не хватает. */
  readOnly?: boolean
  /** Уход из поля — по нему уезжает черновик, как у текстового редактора. */
  onBlur?: () => void
  className?: string
  ariaLabel?: string
}

export function JsonEditor({
  value,
  onChange,
  readOnly = false,
  onBlur,
  className,
  ariaLabel,
}: JsonEditorProps) {
  const хост = useRef<HTMLDivElement | null>(null)
  const вид = useRef<EditorView | null>(null)
  const запрет = useRef(new Compartment())
  // Обработчики держим ссылкой: пересоздавать редактор на каждую перерисовку
  // родителя значило бы терять курсор и историю правок на каждом нажатии.
  const наИзменение = useRef(onChange)
  const наУход = useRef(onBlur)
  наИзменение.current = onChange
  наУход.current = onBlur

  useEffect(() => {
    if (!хост.current) return
    const state = EditorState.create({
      doc: value,
      extensions: [
        lineNumbers(),
        history(),
        drawSelection(),
        bracketMatching(),
        highlightActiveLine(),
        highlightActiveLineGutter(),
        indentUnit.of('  '),
        EditorState.tabSize.of(2),
        EditorView.lineWrapping,
        json(),
        syntaxHighlighting(подсветка),
        тема,
        запрет.current.of(правка_запрещена(readOnly)),
        EditorView.contentAttributes.of(ariaLabel ? { 'aria-label': ariaLabel } : {}),
        keymap.of([...defaultKeymap, ...historyKeymap, indentWithTab]),
        EditorView.updateListener.of((u) => {
          if (!u.docChanged) return
          if (u.transactions.some((t) => t.annotation(СНАРУЖИ))) return
          наИзменение.current(u.state.doc.toString())
        }),
        EditorView.domEventHandlers({
          blur: () => {
            наУход.current?.()
            return false
          },
        }),
      ],
    })
    const view = new EditorView({ state, parent: хост.current })
    вид.current = view
    return () => {
      view.destroy()
      вид.current = null
    }
    // Редактор создаётся один раз: текст и запрет правки меняются эффектами.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Текст снаружи (сменили тег, откатили версию) — заменить целиком. Сверяемся
  // с текущим, иначе каждая перерисовка сбрасывала бы курсор в начало.
  useEffect(() => {
    const view = вид.current
    if (!view) return
    const было = view.state.doc.toString()
    if (было === value) return
    view.dispatch({
      changes: { from: 0, to: было.length, insert: value },
      annotations: СНАРУЖИ.of(true),
    })
  }, [value])

  // Запрет правки — перенастройка отсека, а не пересоздание редактора: иначе
  // на время прогона поле теряло бы историю и позицию курсора.
  useEffect(() => {
    вид.current?.dispatch({
      effects: запрет.current.reconfigure(правка_запрещена(readOnly)),
    })
  }, [readOnly])

  return <div ref={хост} className={className} />
}
