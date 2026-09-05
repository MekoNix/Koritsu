/**
 * Тесты мелких приведений к человеческому виду.
 *
 * Склонение и размер файла проверяются потому, что ошибка в них не ломает
 * ничего и видна только глазами: «5 работа» и «1234,0 Б» никого не остановят,
 * а читаются как небрежность на каждом экране сразу.
 */
import { describe, expect, it } from 'vitest'

import { fileExt, formatBytes, plural } from './format'

/** Словарь подставляется тестом: сами тексты живут в `i18n/ru/projects.json`. */
const t = (key: string, vars?: Record<string, string | number>) =>
  `${key}:${vars ? String(vars.n) : ''}`

describe('formatBytes', () => {
  it('байты остаются байтами без дробной части', () => {
    expect(formatBytes(t, 512)).toBe('projects.size.b:512')
  })

  it('килобайты получают один знак после запятой', () => {
    expect(formatBytes(t, 36658)).toBe('projects.size.kb:35,8')
  })

  it('от сотни знак после запятой не нужен', () => {
    expect(formatBytes(t, 900 * 1024)).toBe('projects.size.kb:900')
  })

  it('мегабайты — своя ступень', () => {
    expect(formatBytes(t, 10 * 1024 * 1024)).toBe('projects.size.mb:10,0')
  })

  it('отрицательного размера не бывает', () => {
    expect(formatBytes(t, -5)).toBe('projects.size.b:0')
  })
})

describe('plural', () => {
  const формы: [string, string, string] = ['работа', 'работы', 'работ']

  it('единственное — 1, 21, 101', () => {
    for (const n of [1, 21, 101]) expect(plural(n, формы)).toBe('работа')
  })

  it('от двух до четырёх', () => {
    for (const n of [2, 3, 4, 22]) expect(plural(n, формы)).toBe('работы')
  })

  it('пять и подростковые числа', () => {
    for (const n of [0, 5, 11, 12, 14, 100]) expect(plural(n, формы)).toBe('работ')
  })
})

describe('fileExt', () => {
  it('берёт расширение и поднимает его в верхний регистр', () => {
    expect(fileExt('лаба.docx')).toBe('DOCX')
    expect(fileExt('архив.tar.gz')).toBe('GZ')
  })

  it('без расширения — пусто, а не мусор', () => {
    expect(fileExt('README')).toBe('')
    expect(fileExt('.gitignore')).toBe('')
    expect(fileExt('имя.')).toBe('')
  })
})
