/**
 * Словарь отказов полон, и у каждого кода есть действие.
 *
 * Код отказа — договор между службой и сайтом: служба отвечает `not_found`,
 * сайт показывает русскую строку. Договор этот ломается тихо. Новый код
 * появляется в маршруте, перевода к нему никто не пишет, и человек получает
 * посреди русской страницы английское `bad_outputs` — или, того хуже, пустое
 * место. Заметить это можно только глазами и только на том экране, где новый
 * отказ случается.
 *
 * Поэтому список кодов уезжает из службы в документ OpenAPI полем
 * `x-error-codes` (`packages/api/errors.py: КОДЫ`, проверка полноты —
 * `tests/api/test_error_codes.py`), а здесь он сверяется со словарём. Новый код
 * без перевода роняет `pnpm test`, а не экран у человека.
 *
 * Второе, что проверяется, — **действие**. У каждого кода две строки: что
 * случилось (`what`) и что делать (`next`). Одно «Место кончилось» оставляет
 * человека перед выбором без подсказки, и правило «у отказа есть выход»
 * держится проверкой, а не памятью того, кто дописывает словарь.
 */
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { describe, expect, it } from 'vitest'

import errors from '@/i18n/ru/errors.json'

import { ApiError, errorDetails, errorNext, errorText, errorWhat } from './errors'

/**
 * Коды службы — из того же документа, по которому собран клиент. Читаем
 * файлом, а не импортом: `openapi.json` весит сотни килобайт, и втягивать его
 * в сборку проверки ради одного массива незачем.
 *
 * Путь считается от корня сайта (`process.cwd()`), а не от `import.meta.url`:
 * проверки идут в jsdom, где адрес модуля не файловый, и `readFileSync` по нему
 * отказывается читать вовсе.
 */
const КОДЫ: string[] = JSON.parse(readFileSync(resolve(process.cwd(), 'openapi.json'), 'utf-8'))[
  'x-error-codes'
]

/**
 * Коды, которых у службы нет и не будет: их заводит сам сайт. `network` —
 * запрос, не доехавший до службы; `unknown` — ответ, в котором кода не
 * оказалось вовсе.
 */
const СВОИ = ['network', 'unknown']

/** Ключ `_` — записка о том, как устроен файл, а не код отказа. */
const словарь = errors as unknown as Record<string, { what?: string; next?: string } | string>
const коды_словаря = Object.keys(словарь).filter((k) => k !== '_')

describe('словарь отказов', () => {
  it('знает каждый код службы', () => {
    const нет = КОДЫ.filter((код) => !коды_словаря.includes(код))
    expect(нет, 'нет перевода в src/i18n/ru/errors.json').toEqual([])
  })

  it('не хранит кодов, которых служба не отдаёт', () => {
    // Обратная сторона: строка, оставшаяся от снесённого маршрута, — это
    // перевод, который никто не увидит, и его чинят вместе с маршрутом.
    const лишние = коды_словаря.filter((код) => !КОДЫ.includes(код) && !СВОИ.includes(код))
    expect(лишние, 'кода нет ни в x-error-codes, ни среди своих').toEqual([])
  })

  it('у каждого кода есть и «что случилось», и «что делать»', () => {
    const плохие = коды_словаря.filter((код) => {
      const строка = словарь[код]
      return typeof строка !== 'object' || !строка.what?.trim() || !строка.next?.trim()
    })
    expect(плохие, 'нужны обе строки: what и next').toEqual([])
  })
})

describe('текст отказа', () => {
  it('берёт обе строки по коду', () => {
    const беда = new ApiError('quota_exceeded', 'Storage quota exceeded', 413)
    expect(errorWhat(беда)).toBe('Место на диске кончилось.')
    expect(errorNext(беда)).toBe('Удалите лишние файлы или очистите корзину.')
    expect(errorText(беда)).toBe(`${errorWhat(беда)} ${errorNext(беда)}`)
  })

  it('незнакомый код — общий текст, а подробности мелкой строкой', () => {
    // Служба новее сайта: код есть, перевода ещё нет. Молчать нельзя, показать
    // английское сообщение вместо русского — тоже: оно написано для того, кто
    // читает документацию API.
    const беда = new ApiError('такого_кода_нет', 'Something odd', 400, undefined, 'rid-42')
    expect(errorWhat(беда)).toBe('Что-то пошло не так.')
    expect(errorNext(беда)).not.toBe('')
    expect(errorDetails(беда)).toContain('Something odd')
    expect(errorDetails(беда)).toContain('rid-42')
  })

  it('у знакомого кода английского текста службы человек не видит', () => {
    // Номер запроса остаётся: по нему жалоба связывается с журналом службы.
    const беда = new ApiError('not_found', 'Project not found', 404, undefined, 'rid-7')
    expect(errorDetails(беда)).not.toContain('Project not found')
    expect(errorDetails(беда)).toContain('rid-7')
  })
})
