/**
 * items — пункты строки меню: Файл · Правка · Сборка · Отладка · Вид · Окно · Справка.
 *
 * Пункты строятся функцией при каждом открытии, а не лежат постоянными: галочки
 * («Строка клавиш», «Точка останова» на строке курсора, открытые окна) должны
 * показывать то, что есть в момент открытия меню.
 */
import { t } from '@/i18n'

import type { AsmContextValue, AsmUi } from '../store'
import { windowDefFor, windowsFor } from '../windows/registry'
import type { AsmActions } from './actions'

export type MenuEntry =
  | 'sep'
  | {
      label: string
      key?: string
      /** Галочка; `undefined` — пункт без галочки. */
      check?: boolean
      /** Галочка-кружок: один из группы. */
      radio?: boolean
      disabled?: boolean
      act?: () => void
      sub?: () => MenuEntry[]
    }

export interface MenuTop {
  label: string
  items: () => MenuEntry[]
}

export function buildMenus(asm: AsmContextValue, ui: AsmUi, a: AsmActions): MenuTop[] {
  const m = (k: string) => t(`asm.menu.${k}`)
  const noTrace = !ui.traceReady
  const cursorBp = asm.cursorLine != null && asm.settings.breakpoints.includes(asm.cursorLine)
  // Переключатель 16/32 — только у режима, где он что-то значит (TASM).
  const bits: MenuEntry[] = asm.toolchain.bitsSwitch
    ? [
        { label: m('view.bits16'), radio: true, check: asm.view.bits === 16, act: () => asm.setView({ bits: 16 }) },
        { label: m('view.bits32'), radio: true, check: asm.view.bits === 32, act: () => asm.setView({ bits: 32 }) },
        'sep',
      ]
    : []

  return [
    {
      label: m('file.title'),
      items: () => [
        { label: m('file.new'), act: a.newProgram },
        { label: m('file.open'), act: a.openFromDisk },
        { label: m('file.toList'), act: a.toList },
        'sep',
        { label: m('file.save'), key: 'Ctrl+S', act: () => void a.save() },
        { label: m('file.saveAs'), act: () => ui.openDialog('saveAs') },
        { label: m('file.rename'), act: () => ui.openDialog('rename') },
        'sep',
        { label: m('file.download'), act: a.downloadSource },
        { label: m('file.exportListing'), disabled: !asm.run?.build?.listing.length, act: a.exportListing },
      ],
    },
    {
      label: m('edit.title'),
      items: () => [
        { label: m('edit.undo'), key: 'Ctrl+Z', act: () => a.editor('undo') },
        { label: m('edit.redo'), key: 'Ctrl+Y', act: () => a.editor('redo') },
        'sep',
        { label: m('edit.copy'), key: 'Ctrl+C', disabled: !asm.selection, act: a.copy },
        'sep',
        { label: m('edit.find'), key: 'Ctrl+F', act: () => ui.openDialog('find') },
        { label: m('edit.gotoLine'), key: 'Ctrl+G', act: () => ui.openDialog('line') },
        { label: m('edit.gotoAddr'), act: () => ui.openDialog('addr') },
      ],
    },
    {
      label: m('build.title'),
      items: () => [
        { label: m('build.run'), key: 'Ctrl+Enter', disabled: asm.runBusy, act: asm.buildAndRun },
        { label: m('build.only'), key: 'Ctrl+B', disabled: asm.runBusy, act: asm.buildOnly },
        'sep',
        { label: m('build.options'), act: () => ui.openDialog('buildOpts') },
        { label: m('build.showLog'), act: () => asm.openWindow('build') },
        { label: m('build.showListing'), act: () => asm.openWindow('listing') },
      ],
    },
    {
      label: m('debug.title'),
      items: () => [
        { label: m('debug.stepOver'), key: 'F8', disabled: noTrace, act: asm.stepOver },
        { label: m('debug.stepInto'), key: 'F7', disabled: noTrace, act: asm.stepInto },
        { label: m('debug.stepBack'), key: 'Shift+F8', disabled: noTrace, act: asm.stepBack },
        { label: m('debug.toCursor'), key: 'F4', disabled: noTrace, act: asm.runToCursor },
        { label: m('debug.toBreakpoint'), key: 'F9', disabled: noTrace, act: asm.runToBreakpoint },
        'sep',
        { label: m('debug.toStart'), key: 'Home', disabled: noTrace, act: asm.toStart },
        { label: m('debug.toEnd'), key: 'End', disabled: noTrace, act: asm.toEnd },
        'sep',
        { label: m('debug.breakpoint'), key: 'F2', check: cursorBp, act: a.toggleBp },
        {
          label: m('debug.clearBreakpoints'),
          disabled: !asm.settings.breakpoints.length,
          act: () => asm.updateSettings({ breakpoints: [] }),
        },
        { label: m('debug.addWatch'), act: () => ui.openDialog('watch') },
        'sep',
        { label: m('debug.runParams'), act: () => asm.openWindow('input') },
      ],
    },
    {
      label: m('view.title'),
      items: () => [
        ...bits,
        { label: m('view.hex'), radio: true, check: asm.view.radix === 'hex', act: () => asm.setView({ radix: 'hex' }) },
        { label: m('view.dec'), radio: true, check: asm.view.radix === 'dec', act: () => asm.setView({ radix: 'dec' }) },
        'sep',
        { label: m('view.keyBar'), check: asm.view.keyBar, act: () => asm.setView({ keyBar: !asm.view.keyBar }) },
        {
          label: m('view.traceSlider'),
          check: asm.view.traceSlider,
          act: () => asm.setView({ traceSlider: !asm.view.traceSlider }),
        },
      ],
    },
    {
      label: m('window.title'),
      items: () => [
        { label: m('window.resetLayout'), act: ui.dock.resetLayout },
        'sep',
        ...windowsFor(asm.toolchain.id).map((w) => ({
          label: t(windowDefFor(asm.toolchain, w.id).title),
          check: ui.dock.isOpen(w.id),
          key: w.hotkey ?? '',
          act: () => asm.openWindow(w.id, { focus: true }),
        })),
      ],
    },
    {
      label: m('help.title'),
      items: () => [
        { label: m('help.word'), key: 'F1', act: a.help },
        { label: m('help.reference'), act: () => asm.openDocs(null) },
        { label: m('help.askAgent'), key: 'Ctrl+J', act: () => asm.askAgent() },
        'sep',
        { label: m('help.hotkeys'), act: () => ui.openDialog('hotkeys') },
      ],
    },
  ]
}
