/**
 * actions — действия, которые зовут и меню, и горячие клавиши.
 *
 * Одно место, потому что пункт «Отладка → До курсора» и F4 обязаны делать одно
 * и то же; написанные дважды, они разошлись бы на первой правке.
 */
import { useCallback, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'

import { useT } from '@/i18n'

import { useAsm, useAsmUi } from '../store'
import { SOURCE_EXT } from '../toolchains'
import { regHex, type AsmAnchor, type AsmWindowId } from '../types'

/** Директивы и мнемоники, по которым в справке есть запись, берутся из строки как слово. */
const СЛОВО = /^\s*(?:[A-Za-z_@$?][\w@$?]*:)?\s*(\.?[A-Za-z@][\w@]*)/

/** Слово для справки из якоря: мнемоника строки, имя регистра или флага. */
export function tokenOf(anchor: AsmAnchor | null, source: string): string | null {
  if (!anchor) return null
  switch (anchor.kind) {
    case 'line': {
      const text = (source.split('\n')[anchor.line - 1] ?? '').replace(/;.*$/, '')
      // `arr db 1,2` — слово справки `db`, а не имя переменной.
      const m = /^\s*[A-Za-z_@$?][\w@$?]*\s+(db|dw|dd|dq|dt|equ|proc|endp|segment|ends|macro|endm|label|struc|ends)\b/i.exec(text)
      if (m) return m[1]!.toLowerCase()
      return СЛОВО.exec(text)?.[1]?.toLowerCase() ?? null
    }
    case 'register':
    case 'flag':
      return anchor.name
    case 'doc':
      return anchor.id
    default:
      return null
  }
}

function download(name: string, text: string): void {
  const url = URL.createObjectURL(new Blob([text], { type: 'text/plain;charset=utf-8' }))
  const a = document.createElement('a')
  a.href = url
  a.download = name
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

/** Имя файла из имени программы: DOS, TASM и командная строка сборки не любят пробелов и кириллицы в имени. */
export function fileBase(name: string): string {
  const base = name.trim().replace(/\.(asm|s)$/i, '').replace(/[^\w.-]+/g, '_')
  return base || 'program'
}

export function useAsmActions() {
  const t = useT()
  const asm = useAsm()
  const ui = useAsmUi()
  const navigate = useNavigate()
  const ext = SOURCE_EXT[asm.toolchain.id]

  /** Окно для перехода к строке: то из двух, что человек смотрит, иначе исходник. */
  const lineWindow = useCallback((): AsmWindowId => {
    if (ui.dock.focus === 'listing' || ui.dock.focus === 'source') return ui.dock.focus
    return ui.dock.isVisible('listing') && !ui.dock.isVisible('source') ? 'listing' : 'source'
  }, [ui.dock])

  const gotoLine = useCallback(
    (line: number) => {
      asm.setCursorLine(line)
      asm.select({ kind: 'line', line })
      asm.openWindow(lineWindow(), { focus: true })
    },
    [asm, lineWindow],
  )

  // Отказ записи и так виден полосой над доком; подтверждение нужно удаче —
  // без него Ctrl+S не показал бы ничего.
  const save = useCallback(async () => {
    if (await ui.flush()) asm.toast(t('asm.status.saved', { name: asm.program?.name ?? '' }))
  }, [ui, asm, t])

  const toggleBp = useCallback(() => {
    const line = asm.cursorLine ?? (asm.selection?.kind === 'line' ? asm.selection.line : null)
    if (line == null) {
      asm.toast(t('asm.status.noCursor'))
      return
    }
    ui.toggleBreakpoint(line)
  }, [asm, ui, t])

  const help = useCallback(() => {
    asm.openDocs(tokenOf(asm.selection, asm.program?.source ?? ''))
  }, [asm])

  const copy = useCallback(() => {
    const a = asm.selection
    const step = asm.step
    let text = ''
    if (!a) text = ''
    else if (a.kind === 'line') text = (asm.program?.source.split('\n')[a.line - 1] ?? '').trimEnd()
    else if (a.kind === 'register') {
      const v = regHex(step, a.name) ?? step?.reg32?.[a.name.toLowerCase()]
      text = v ? `${a.name.toUpperCase()}=${v}` : a.name.toUpperCase()
    } else if (a.kind === 'flag') text = a.name.toUpperCase()
    else if (a.kind === 'cell') text = a.seg == null ? a.off : `${a.seg}:${a.off}`
    else if (a.kind === 'doc') text = a.id
    else if (a.kind === 'text') text = a.text
    if (!text) {
      asm.toast(t('asm.status.nothingToCopy'))
      return
    }
    if (!navigator.clipboard) {
      asm.toast(t('asm.status.clipboardDenied'))
      return
    }
    navigator.clipboard.writeText(text).then(
      () => asm.toast(t('asm.status.copied', { text })),
      () => asm.toast(t('asm.status.clipboardDenied')),
    )
  }, [asm, t])

  /** Отмена и повтор принадлежат редактору: сюда он подписан событием `asm:editor`. */
  const editor = useCallback(
    (command: 'undo' | 'redo') => {
      asm.openWindow('source', { focus: true })
      window.dispatchEvent(new CustomEvent('asm:editor', { detail: command }))
    },
    [asm],
  )

  // Новая программа — через страницу выбора режима; режим текущей программы предвыбран.
  const newProgram = useCallback(() => {
    navigate(`/asm/new?toolchain=${asm.toolchain.id}`)
  }, [navigate, asm.toolchain.id])

  const openFromDisk = useCallback(() => {
    const input = document.createElement('input')
    input.type = 'file'
    input.accept = '.asm,.inc,.s,.S,.txt,text/plain'
    input.onchange = async () => {
      const file = input.files?.[0]
      if (!file) return
      const text = await file.text()
      asm.setSource(text.replace(/\r\n?/g, '\n'))
      asm.openWindow('source', { focus: true })
    }
    input.click()
  }, [asm])

  const downloadSource = useCallback(() => {
    download(`${fileBase(asm.program?.name ?? '')}.${ext}`, asm.program?.source ?? '')
  }, [asm.program, ext])

  const exportListing = useCallback(() => {
    const listing = asm.run?.build?.listing
    if (!listing?.length) {
      asm.toast(t('asm.status.noListing'))
      return
    }
    const text = listing
      .map((l) =>
        [
          String(l.line).padStart(5, ' '),
          l.segment && l.offset ? `${l.segment}:${l.offset}` : ''.padEnd(9, ' '),
          l.bytes.padEnd(20, ' '),
          l.text,
        ].join('  '),
      )
      .join('\n')
    download(`${fileBase(asm.program?.name ?? '')}.lst`, text)
  }, [asm, t])

  return useMemo(
    () => ({
      gotoLine,
      lineWindow,
      save,
      toggleBp,
      help,
      copy,
      editor,
      newProgram,
      openFromDisk,
      downloadSource,
      exportListing,
      toList: () => navigate('/asm'),
    }),
    [gotoLine, lineWindow, save, toggleBp, help, copy, editor, newProgram, openFromDisk, downloadSource, exportListing, navigate],
  )
}

export type AsmActions = ReturnType<typeof useAsmActions>
