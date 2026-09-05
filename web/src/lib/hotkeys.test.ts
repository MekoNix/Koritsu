/**
 * Тесты переназначения горячих клавиш.
 *
 * Проверяется то, ради чего раздел «Горячие клавиши» и заведён: нажатие
 * превращается в сочетание, сочетание переживает перезагрузку страницы
 * (`localStorage`) и возвращается к исходному по «Вернуть».
 *
 * `comboFromEvent` проверяется отдельно от хука намеренно: именно она решает,
 * что считать сочетанием, и именно её ошибка была бы незаметной — сайт просто
 * запомнил бы «ctrl» вместо «ctrl+k» и перестал бы реагировать.
 */
import { beforeEach, describe, expect, it } from 'vitest'

import { comboFromEvent, hotkeyLabel, resetHotkeys, setHotkey } from './hotkeys'

beforeEach(() => {
  localStorage.clear()
  resetHotkeys()
})

describe('сочетание из нажатия', () => {
  it('модификатор с клавишей — сочетание', () => {
    const событие = new KeyboardEvent('keydown', { key: 'K', ctrlKey: true })
    expect(comboFromEvent(событие)).toBe('ctrl+k')
  })

  it('один модификатор — ещё не сочетание', () => {
    // Человек держит Ctrl и выбирает вторую клавишу: запоминать тут нечего.
    expect(comboFromEvent(new KeyboardEvent('keydown', { key: 'Control', ctrlKey: true }))).toBe(
      null,
    )
  })

  it('буква без модификатора не берётся', () => {
    // Иначе одиночная буква ловилась бы посреди набора текста в любом поле.
    expect(comboFromEvent(new KeyboardEvent('keydown', { key: 'k' }))).toBe(null)
  })

  it('Cmd считается за Ctrl: на маке Ctrl+J не нажимают', () => {
    const событие = new KeyboardEvent('keydown', { key: 'j', metaKey: true })
    expect(comboFromEvent(событие)).toBe('ctrl+j')
  })

  it('подпись читается человеком', () => {
    expect(hotkeyLabel('ctrl+shift+k')).toBe('Ctrl Shift K')
    expect(hotkeyLabel('escape')).toBe('Esc')
  })
})

describe('переназначение', () => {
  it('сохраняется в хранилище браузера и снимается «вернуть»', () => {
    setHotkey('search', 'ctrl+shift+f')
    expect(JSON.parse(localStorage.getItem('koritsu.hotkeys') ?? '{}')).toEqual({
      search: 'ctrl+shift+f',
    })

    setHotkey('search', null)
    expect(JSON.parse(localStorage.getItem('koritsu.hotkeys') ?? '{}')).toEqual({})
  })

  it('«вернуть все» чистит все переназначения разом', () => {
    setHotkey('search', 'ctrl+shift+f')
    setHotkey('agent', 'ctrl+shift+a')
    resetHotkeys()
    expect(JSON.parse(localStorage.getItem('koritsu.hotkeys') ?? '{}')).toEqual({})
  })
})
