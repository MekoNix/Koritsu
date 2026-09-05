/**
 * CodeEditor — редактор исходника на CodeMirror 6 (решение владельца).
 *
 * Почему не `<textarea>`: экран схем — это экран чтения кода. Без номеров
 * строк и подсветки человек не находит в нём ни ту функцию, что нарисована
 * справа, ни строку, на которую жалуется разбор. Всё остальное, что умеет
 * CodeMirror (сворачивание, автодополнение, поиск), сюда намеренно не
 * подключено: код здесь правят по мелочи, а не пишут.
 *
 * Языков три, ровно те, что разбирает служба (`orchestrator.diagrams.LANGS`).
 * У C# своего пакета грамматики нет, поэтому берётся потоковый режим `clike`
 * из `@codemirror/legacy-modes` — подсветка та же, разбора она всё равно не
 * делает: разбирает служба.
 *
 * Цвета — переменные темы, а не своя палитра: тем на сайте четыре в двух
 * вариантах, и вторая палитра в редакторе разъехалась бы с первой же новой
 * темой.
 */
import { defaultKeymap, history, historyKeymap, indentWithTab } from '@codemirror/commands'
import { cpp } from '@codemirror/lang-cpp'
import { python } from '@codemirror/lang-python'
import {
  HighlightStyle,
  StreamLanguage,
  bracketMatching,
  indentUnit,
  syntaxHighlighting,
} from '@codemirror/language'
import { csharp } from '@codemirror/legacy-modes/mode/clike'
import { Compartment, EditorState, type Extension } from '@codemirror/state'
import {
  EditorView,
  drawSelection,
  highlightActiveLine,
  highlightActiveLineGutter,
  keymap,
  lineNumbers,
  placeholder as cmPlaceholder,
} from '@codemirror/view'
import { tags } from '@lezer/highlight'
import { useEffect, useRef } from 'react'

import type { Lang } from './types'

/** Грамматика по языку. Один и тот же перечень, что у службы. */
function languageOf(lang: Lang): Extension {
  if (lang === 'py') return python()
  if (lang === 'cpp') return cpp()
  return StreamLanguage.define(csharp)
}

/**
 * Подсветка на переменных темы. Токенов немного намеренно: различать десять
 * оттенков в чужом коде некому, а контраст каждого пришлось бы считать.
 */
const подсветка = HighlightStyle.define([
  { tag: tags.keyword, color: 'var(--code-keyword, var(--accent))' },
  { tag: [tags.controlKeyword, tags.moduleKeyword], color: 'var(--code-keyword, var(--accent))' },
  { tag: [tags.string, tags.special(tags.string)], color: 'var(--code-string, var(--ok))' },
  { tag: [tags.number, tags.bool, tags.null], color: 'var(--code-number, var(--warn))' },
  { tag: tags.comment, color: 'var(--muted)', fontStyle: 'italic' },
  { tag: [tags.function(tags.variableName), tags.labelName], color: 'var(--code-fn, var(--info))' },
  { tag: [tags.typeName, tags.className], color: 'var(--code-type, var(--agent))' },
  { tag: tags.operator, color: 'var(--ink)' },
  { tag: tags.propertyName, color: 'var(--ink)' },
])

const тема = EditorView.theme({
  '&': {
    height: '100%',
    color: 'var(--ink)',
    backgroundColor: 'transparent',
    fontSize: 'var(--size-sm)',
  },
  '.cm-scroller': {
    fontFamily: 'var(--font-mono)',
    lineHeight: 'var(--leading-normal)',
  },
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
  '.cm-placeholder': { color: 'var(--muted)' },
})

export type CodeEditorProps = {
  value: string
  onChange: (value: string) => void
  lang: Lang
  placeholder?: string
  /** Что делать по Ctrl+Enter: построить схему, не дожидаясь задержки. */
  onSubmit?: () => void
  className?: string
  ariaLabel?: string
}

export function CodeEditor({
  value,
  onChange,
  lang,
  placeholder,
  onSubmit,
  className,
  ariaLabel,
}: CodeEditorProps) {
  const хост = useRef<HTMLDivElement | null>(null)
  const вид = useRef<EditorView | null>(null)
  const язык = useRef(new Compartment())
  // Обработчики держим ссылкой: пересоздавать редактор на каждую перерисовку
  // родителя значило бы терять курсор и историю правок на каждом нажатии.
  const наИзменение = useRef(onChange)
  const наОтправку = useRef(onSubmit)
  наИзменение.current = onChange
  наОтправку.current = onSubmit

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
        indentUnit.of('    '),
        EditorState.tabSize.of(4),
        EditorView.lineWrapping,
        syntaxHighlighting(подсветка),
        тема,
        язык.current.of(languageOf(lang)),
        placeholder ? cmPlaceholder(placeholder) : [],
        keymap.of([
          {
            key: 'Mod-Enter',
            run: () => {
              наОтправку.current?.()
              return true
            },
          },
          ...defaultKeymap,
          ...historyKeymap,
          indentWithTab,
        ]),
        EditorView.updateListener.of((u) => {
          if (u.docChanged) наИзменение.current(u.state.doc.toString())
        }),
        EditorView.contentAttributes.of(ariaLabel ? { 'aria-label': ariaLabel } : {}),
      ],
    })
    const view = new EditorView({ state, parent: хост.current })
    вид.current = view
    return () => {
      view.destroy()
      вид.current = null
    }
    // Редактор создаётся один раз: язык и текст меняются отдельными эффектами.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Смена языка — перенастройка отсека, а не пересоздание редактора.
  useEffect(() => {
    вид.current?.dispatch({ effects: язык.current.reconfigure(languageOf(lang)) })
  }, [lang])

  // Текст снаружи (загрузили файл, переключили исходник) — заменить целиком.
  // Сверяемся с текущим, иначе каждая перерисовка сбрасывала бы курсор в начало.
  useEffect(() => {
    const view = вид.current
    if (!view) return
    const было = view.state.doc.toString()
    if (было === value) return
    view.dispatch({ changes: { from: 0, to: было.length, insert: value } })
  }, [value])

  return <div ref={хост} className={className} />
}
