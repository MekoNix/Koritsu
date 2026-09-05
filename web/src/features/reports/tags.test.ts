/**
 * Проверки счёта по тегам и чтения значения.
 *
 * Проверяется арифметика, которую человек видит первой («7 из 12») и по которой
 * решает, закончил он или нет. Разойтись она может тихо: список слева рисует
 * точки по `filled`, шапка считает проценты, и если считать заполненность
 * по-разному, экран будет противоречить сам себе, ничего не сломав.
 */
import { describe, expect, it } from 'vitest'

import { emptyKeys, filterTags, summarize, textToValue, valueText } from './tags'
import type { ProjectTag } from './types'

function тег(part: Partial<ProjectTag> & { key: string }): ProjectTag {
  return {
    label: '',
    type: 'markdown',
    required: true,
    prompt: '',
    filled: false,
    source: null,
    version: null,
    at: null,
    ...part,
  }
}

const ТЕГИ: ProjectTag[] = [
  тег({ key: 'цель', label: 'Цель работы', filled: true, source: 'agent', version: 2 }),
  тег({
    key: 'теория',
    label: 'Теоретические сведения',
    filled: true,
    source: 'manual',
    version: 1,
  }),
  тег({ key: 'листинг', label: 'Листинг', type: 'code' }),
  тег({ key: 'выводы', label: 'Вывод' }),
]

describe('summarize', () => {
  it('считает заполненные, своё и сделанное моделью', () => {
    expect(summarize(ТЕГИ)).toEqual({
      total: 4,
      filled: 2,
      byAgent: 1,
      manual: 1,
      empty: 2,
      percent: 50,
    })
  })

  it('на пустом списке не делит на ноль', () => {
    expect(summarize([])).toMatchObject({ total: 0, filled: 0, percent: 0 })
    expect(summarize(undefined)).toMatchObject({ total: 0, percent: 0 })
  })

  it('считает по filled, а не по длине текста: пустая строка — тоже значение', () => {
    const пустое = [тег({ key: 'вывод', filled: true, source: 'manual', version: 1 })]
    expect(summarize(пустое).filled).toBe(1)
  })
})

describe('emptyKeys', () => {
  it('отдаёт незаполненные в порядке шаблона', () => {
    expect(emptyKeys(ТЕГИ)).toEqual(['листинг', 'выводы'])
  })
})

describe('filterTags', () => {
  it('ищет и по ключу, и по метке', () => {
    expect(filterTags(ТЕГИ, 'цель', 'all').map((t) => t.key)).toEqual(['цель'])
    expect(filterTags(ТЕГИ, 'Теоретические', 'all').map((t) => t.key)).toEqual(['теория'])
  })

  it('отбирает по состоянию', () => {
    expect(filterTags(ТЕГИ, '', 'empty').map((t) => t.key)).toEqual(['листинг', 'выводы'])
    expect(filterTags(ТЕГИ, '', 'agent').map((t) => t.key)).toEqual(['цель'])
    expect(filterTags(ТЕГИ, '', 'filled')).toHaveLength(2)
  })
})

describe('valueText', () => {
  it('текстовые типы отдают сам текст', () => {
    expect(valueText({ type: 'markdown', text: 'Цель работы — …' })).toBe('Цель работы — …')
  })

  it('значения нет — пустая строка, без выдумок', () => {
    expect(valueText(undefined)).toBe('')
    expect(valueText(null)).toBe('')
  })

  it('нетекстовый тип показывается как JSON', () => {
    const таблица = { type: 'table', rows: [['n', 'мс']] }
    expect(valueText(таблица)).toContain('"rows"')
  })
})

describe('textToValue', () => {
  it('правка текста не стирает соседние поля значения', () => {
    const было = { type: 'code', text: 'int main()', lang: 'cpp', line_numbers: true }
    expect(textToValue('int main(void)', { type: 'code', previous: было })).toEqual({
      type: 'code',
      text: 'int main(void)',
      lang: 'cpp',
      line_numbers: true,
    })
  })

  it('значения не было — тип берётся из манифеста', () => {
    expect(textToValue('текст', { type: 'markdown' })).toEqual({
      type: 'markdown',
      text: 'текст',
    })
  })
})
