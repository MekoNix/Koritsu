/**
 * Проверки частичного показа почты.
 *
 * Предмет проверки — обещание «домен виден, остальное нет». Ломается оно молча
 * и в обе стороны: спрятать лишнее — человек не узнаёт свой адрес среди своих
 * же; спрятать недостаточно — прятка бессмысленна, а выглядит сделанной.
 */
import { describe, expect, it } from 'vitest'

import { maskEmail } from './maskEmail'

describe('maskEmail', () => {
  it('оставляет первую букву и домен', () => {
    expect(maskEmail('ivan@mail.ru')).toBe('i***@mail.ru')
    expect(maskEmail('a.b.c@example.co.uk')).toBe('a***@example.co.uk')
  })

  it('длину имени не выдаёт: звёздочек всегда три', () => {
    expect(maskEmail('ab@x.ru')).toBe('a***@x.ru')
    expect(maskEmail('abcdefghijklmnop@x.ru')).toBe('a***@x.ru')
  })

  it('кириллическую почту показывает так же', () => {
    expect(maskEmail('хозяин@пример.рф')).toBe('х***@пример.рф')
  })

  it('прячет только имя, даже если `@` есть и в нём', () => {
    // Адрес с `@` внутри имени — редкость, но домен берётся по последней
    // собаке: иначе часть домена уехала бы под звёздочки.
    expect(maskEmail('"a@b"@mail.ru')).toBe('"***@mail.ru')
  })

  it('не почту и пустоту возвращает как есть', () => {
    expect(maskEmail('строка')).toBe('строка')
    expect(maskEmail('')).toBe('')
    expect(maskEmail(null)).toBe('')
    expect(maskEmail(undefined)).toBe('')
    // Имени нет вовсе — прятать нечего.
    expect(maskEmail('@mail.ru')).toBe('@mail.ru')
  })

  it('края обрезает', () => {
    expect(maskEmail('  ivan@mail.ru ')).toBe('i***@mail.ru')
  })
})
