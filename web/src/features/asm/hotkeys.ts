/**
 * hotkeys — клавиши CPU-окна, как в Turbo Debugger.
 *
 *     F1 справка по слову     F2 точка останова      F4 до курсора
 *     F7 шаг с заходом        F8 шаг · Shift+F8 назад F9 до точки останова
 *     F6 следующая группа     F10 / Alt строка меню  Home / End начало / конец
 *     Ctrl+Enter собрать и запустить · Ctrl+B только собрать · Ctrl+S сохранить
 *     Ctrl+F найти · Ctrl+G к строке · Ctrl+J агент (про выделенный текст, если он есть)
 *     Alt+1…9 окно · Ctrl+Tab вкладка · Ctrl+Alt+стрелка — вкладку в соседнюю группу
 *
 * **Слушатель на фазе перехвата.** Редактор исходника сам понимает Ctrl+F и
 * F-клавиши не пропускает; перехват срабатывает раньше него. Сочетания, которые
 * здесь заняты, дальше не идут — иначе Ctrl+J заодно открыл бы общую панель
 * агента оболочки, а Ctrl+F — поиск браузера.
 *
 * **F-клавиши и Ctrl-сочетания работают и в поле ввода**, как в отладчике: шаг
 * F8, пока курсор в редакторе, — обычное дело. Home/End и стрелки без
 * модификаторов в поле ввода принадлежат полю.
 */
import { useEffect, useRef } from 'react'

// Перевод без хука: обработчик живёт вне отрисовки.
import { t as latestT } from '@/i18n'

import { useAsm, useAsmUi } from './store'
import { useAsmActions } from './menu/actions'
import { liveTextAnchor } from './windows/format'
import { ASM_WINDOWS } from './windows/registry'

function печатает(el: EventTarget | null): boolean {
  const e = el as HTMLElement | null
  if (!e) return false
  if (e.isContentEditable) return true
  if (e.tagName === 'TEXTAREA' || e.tagName === 'SELECT') return true
  if (e.tagName === 'INPUT') {
    const type = (e as HTMLInputElement).type
    return type !== 'range' && type !== 'checkbox' && type !== 'radio' && type !== 'button'
  }
  return false
}

export function useAsmHotkeys(): void {
  const asm = useAsm()
  const ui = useAsmUi()
  const actions = useAsmActions()
  const latest = useRef({ asm, ui, actions })
  latest.current = { asm, ui, actions }

  useEffect(() => {
    let одинокийAlt = false

    const down = (e: KeyboardEvent) => {
      const { asm: a, ui: u, actions: act } = latest.current
      одинокийAlt = e.key === 'Alt' && !e.repeat && !e.ctrlKey && !e.shiftKey && !e.metaKey
      // Открытый диалог — его клавиатура; строку меню ведёт её же обработчик.
      if (u.dialog || document.querySelector('[role="dialog"][aria-modal="true"]')) return
      const ctrl = e.ctrlKey || e.metaKey
      const typing = печатает(e.target)
      const menubarActive = u.menubar.current?.active() ?? false

      const take = (fn: () => void) => {
        e.preventDefault()
        e.stopPropagation()
        fn()
      }

      if (e.key === 'F10' && !e.shiftKey && !ctrl) {
        return take(() => (menubarActive ? u.menubar.current?.leave() : u.menubar.current?.enter()))
      }
      if (menubarActive) return

      if (ctrl && !e.shiftKey && !e.altKey) {
        switch (e.code) {
          case 'KeyS':
            return take(() => void act.save())
          case 'KeyF':
            return take(() => u.openDialog('find'))
          case 'KeyG':
            return take(() => u.openDialog('line'))
          case 'KeyB':
            return take(a.buildOnly)
          case 'KeyJ':
            // Выделен текст в окне — вопрос о нём; нет — о текущей привязке.
            return take(() => a.askAgent(liveTextAnchor()))
          case 'Enter':
            return take(a.buildAndRun)
        }
      }
      if (ctrl && e.key === 'Enter') return take(a.buildAndRun)

      if (e.altKey && !ctrl && /^Digit[1-9]$/.test(e.code)) {
        const w = ASM_WINDOWS.find((x) => x.hotkey === `Alt+${e.code.slice(5)}`)
        if (w) return take(() => a.openWindow(w.id, { focus: true }))
      }
      if ((ctrl && e.key === 'Tab') || (e.altKey && (e.key === 'PageDown' || e.key === 'PageUp'))) {
        return take(() => u.dock.cycleTab(e.shiftKey || e.key === 'PageUp' ? -1 : 1))
      }
      if (ctrl && e.altKey && (e.key === 'ArrowLeft' || e.key === 'ArrowRight' || e.key === 'ArrowUp' || e.key === 'ArrowDown')) {
        const key = e.key
        return take(() => {
          if (!u.dock.moveToNeighbor(key)) a.toast(latestT('asm.status.noNeighbor'))
        })
      }

      switch (e.key) {
        case 'F1':
          return take(act.help)
        case 'F2':
          return take(ctrl ? a.toStart : act.toggleBp)
        case 'F4':
          return take(a.runToCursor)
        case 'F6':
          return take(u.dock.cycleGroup)
        case 'F7':
          return take(e.shiftKey ? a.stepBack : a.stepInto)
        case 'F8':
          return take(e.shiftKey ? a.stepBack : a.stepOver)
        case 'F9':
          return take(a.runToBreakpoint)
      }

      if (typing || ctrl || e.altKey) return
      const t = e.target as HTMLElement | null
      if (t?.closest?.('.asm-dk-gut, [data-asm-tab], [role="menu"], [role="menubar"]')) return
      if (e.key === 'Home') return take(a.toStart)
      if (e.key === 'End') return take(a.toEnd)
    }

    const up = (e: KeyboardEvent) => {
      if (e.key !== 'Alt' || !одинокийAlt) return
      одинокийAlt = false
      const { ui: u } = latest.current
      if (u.dialog) return
      e.preventDefault()
      if (u.menubar.current?.active()) u.menubar.current.leave()
      else u.menubar.current?.enter()
    }

    const pointer = () => {
      одинокийAlt = false
    }

    window.addEventListener('keydown', down, true)
    window.addEventListener('keyup', up, true)
    window.addEventListener('pointerdown', pointer, true)
    return () => {
      window.removeEventListener('keydown', down, true)
      window.removeEventListener('keyup', up, true)
      window.removeEventListener('pointerdown', pointer, true)
    }
  }, [])
}

