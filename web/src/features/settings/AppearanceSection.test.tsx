/**
 * Тест раздела «Оформление».
 *
 * Проверяется то, ради чего раздел и существует: выбор темы и шрифта уезжает в
 * общее хранилище каркаса и в атрибуты `<html>`, а не в собственное состояние
 * компонента. Именно это и делает выбор переживающим перезагрузку — встроенный
 * скрипт `index.html` читает тот же ключ `koritsu.appearance` до первого
 * рендера.
 *
 * Проверяется через настоящий `ThemeProvider`, а не через подменённый
 * `useAppearance`: подмена доказала бы, что компонент зовёт функцию, а нужно,
 * что после нажатия у страницы другая тема.
 */
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it } from 'vitest'

import { ThemeProvider } from '@/theme'

import { AppearanceSection } from './AppearanceSection'

function draw() {
  return render(
    <ThemeProvider>
      <AppearanceSection />
    </ThemeProvider>,
  )
}

beforeEach(() => {
  localStorage.clear()
  document.documentElement.removeAttribute('data-theme')
  document.documentElement.removeAttribute('data-mode')
  document.documentElement.removeAttribute('data-density')
})

describe('оформление', () => {
  it('выбор темы меняет атрибуты <html> и попадает в хранилище', async () => {
    const человек = userEvent.setup()
    draw()

    await человек.click(screen.getByRole('radio', { name: /Бумага/ }))

    expect(document.documentElement.getAttribute('data-theme')).toBe('paper')
    // Смена темы без явного выбора возвращает её родной вариант — «Бумага»
    // светлая.
    expect(document.documentElement.getAttribute('data-mode')).toBe('light')
    expect(JSON.parse(localStorage.getItem('koritsu.appearance') ?? '{}')).toMatchObject({
      theme: 'paper',
      mode: 'light',
    })
  })

  it('плотность «компактная» ставит data-density, обычная — снимает', async () => {
    const человек = userEvent.setup()
    draw()

    await человек.click(screen.getByRole('radio', { name: 'Компактная' }))
    expect(document.documentElement.getAttribute('data-density')).toBe('compact')

    await человек.click(screen.getByRole('radio', { name: 'Обычная' }))
    expect(document.documentElement.getAttribute('data-density')).toBeNull()
  })

  it('выбор шрифта уезжает в переменную --font-ui', async () => {
    const человек = userEvent.setup()
    draw()

    const список = screen.getByLabelText('Шрифт интерфейса')
    await человек.selectOptions(список, screen.getByRole('option', { name: /Georgia/ }))

    expect(document.documentElement.style.getPropertyValue('--font-ui')).toContain('Georgia')
  })
})
