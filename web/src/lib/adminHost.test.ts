/**
 * Проверки имени, на котором живёт админка.
 *
 * Проверяется тут одно правило и его отсутствие: с чужого имени админки нет, а
 * без домена (машина разработчика, стенд) есть везде. Ошибка в любую сторону
 * стоит дорого — либо админка открывается там, где служба ответит 404, либо
 * пропадает у того, кто пришёл по правильному адресу.
 */
import { afterEach, describe, expect, it } from 'vitest'

import { адресАдминки, админкаНаЭтомИмени, доменАдминки, запомнитьДоменАдминки } from './adminHost'

/** Подменить адрес страницы: в jsdom `location` меняется только так. */
function наСтранице(href: string): void {
  window.history.replaceState({}, '', '/')
  Object.defineProperty(window, 'location', {
    configurable: true,
    value: new URL(href),
  })
}

afterEach(() => {
  запомнитьДоменАдминки('')
  наСтранице('http://localhost:3000/')
})

describe('домен админки', () => {
  it('без домена админка открывается там же, где сайт', () => {
    запомнитьДоменАдминки('')
    expect(доменАдминки()).toBe('')
    expect(админкаНаЭтомИмени()).toBe(true)
  })

  it('поля не пришло — считаем, что домена нет', () => {
    запомнитьДоменАдминки(undefined)
    expect(админкаНаЭтомИмени()).toBe(true)
  })

  it('с чужого имени админки нет', () => {
    запомнитьДоменАдминки('admin.koritsu.example')
    наСтранице('https://koritsu.example/admin')
    expect(админкаНаЭтомИмени()).toBe(false)
  })

  it('на своём имени есть, и порт со схемой этому не мешают', () => {
    запомнитьДоменАдминки('  ADMIN.koritsu.example  ')
    наСтранице('http://admin.koritsu.example:8443/admin')
    expect(доменАдминки()).toBe('admin.koritsu.example')
    expect(админкаНаЭтомИмени()).toBe(true)
  })

  it('ссылка ведёт на имя админки, сохраняя схему и порт страницы', () => {
    запомнитьДоменАдминки('admin.koritsu.example')
    наСтранице('https://koritsu.example:8443/dashboard')
    expect(адресАдминки()).toBe('https://admin.koritsu.example:8443/admin')
  })
})
