/**
 * KeyBar — строка функциональных клавиш внизу, как у Turbo Debugger.
 *
 * Клавиши работают и без неё (их ловит каркас модуля); строка нужна тому, кто
 * ещё не помнит, что F8 — шаг, а F4 — до курсора. Каждая подпись — кнопка,
 * которая делает то же, что клавиша.
 */
import { useAsm } from '@/features/asm/store'
import { useT } from '@/i18n'

import { mnemonicOf } from './tasmLanguage'

export default function KeyBar() {
  const t = useT()
  const asm = useAsm()
  const { selection, cursorLine, program, settings } = asm

  const docToken = (): string | null => {
    if (!selection) return null
    if (selection.kind === 'register' || selection.kind === 'flag') return selection.name.toUpperCase()
    if (selection.kind === 'doc') return selection.id
    if (selection.kind === 'line') {
      const text = (program?.source ?? '').split('\n')[selection.line - 1]
      return text ? mnemonicOf(text) : null
    }
    return null
  }

  const toggleBp = () => {
    if (cursorLine == null) {
      asm.toast(t('asm.keys.noCursor'))
      return
    }
    const list = settings.breakpoints
    asm.updateSettings({
      breakpoints: list.includes(cursorLine) ? list.filter((l) => l !== cursorLine) : [...list, cursorLine].sort((a, b) => a - b),
    })
  }

  const keys: [string, string, () => void][] = [
    ['F1', t('asm.keys.help'), () => asm.openDocs(docToken())],
    ['F2', t('asm.keys.bp'), toggleBp],
    ['F4', t('asm.keys.cursor'), asm.runToCursor],
    ['F7', t('asm.keys.into'), asm.stepInto],
    ['F8', t('asm.keys.step'), asm.stepOver],
    ['⇧F8', t('asm.keys.back'), asm.stepBack],
    ['F9', t('asm.keys.run'), asm.runToBreakpoint],
    ['Ctrl J', t('asm.keys.ask'), () => asm.askAgent(selection)],
  ]

  return (
    <footer className="keys">
      {keys.map(([key, label, run]) => (
        <button key={key} type="button" onClick={run}>
          <b>{key}</b>
          {label}
        </button>
      ))}
      <span className="grow" />
      <span className="env">{t('asm.keys.env')}</span>
    </footer>
  )
}
