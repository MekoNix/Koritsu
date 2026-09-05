/**
 * Проверки сравнения текстов по словам.
 *
 * Предмет проверки — не «работает ли LCS» (он работает), а три обещания, на
 * которых стоит экран истории версий и которые ломаются молча:
 *
 * 1. **склейка кусков даёт исходные тексты знак в знак.** Сравнение, потерявшее
 *    пробел или переставившее слово, показало бы человеку текст, которого он не
 *    писал, — и был бы это самый убедительный вид вранья;
 * 2. **правка красится словом, а не абзацем.** Ради этого разбиение и сделано
 *    по словам: «изменён весь абзац» на замене одного слова означает, что
 *    сравнение бесполезно;
 * 3. **за потолком работа не начинается.** Иначе вкладка встанет молча.
 */
import { describe, expect, it } from 'vitest'

import { diffStats, diffTokens, diffWords, splitWords, ПОТОЛОК } from './diffWords'

/** Склеить куски одной судьбы обратно: `same` + `del` — это «было». */
function было(parts: { kind: string; text: string }[]): string {
  return parts
    .filter((p) => p.kind !== 'add')
    .map((p) => p.text)
    .join('')
}

function стало(parts: { kind: string; text: string }[]): string {
  return parts
    .filter((p) => p.kind !== 'del')
    .map((p) => p.text)
    .join('')
}

describe('splitWords', () => {
  it('пробелы — свои единицы, склейка даёт исходный текст', () => {
    const текст = 'Цель  работы\n\nизучить\tметод.'
    expect(splitWords(текст).join('')).toBe(текст)
    expect(splitWords('')).toEqual([])
  })
})

describe('diffWords', () => {
  it('одно заменённое слово красит одно слово, а не весь абзац', () => {
    const куски = diffWords(
      'Цель работы — изучить метод конечных элементов.',
      'Цель работы — изучить метод конечных разностей.',
    )
    expect(куски.filter((p) => p.kind === 'del').map((p) => p.text)).toEqual(['элементов.'])
    expect(куски.filter((p) => p.kind === 'add').map((p) => p.text)).toEqual(['разностей.'])
    // Остальное осталось общим: если бы разбиение было по абзацам, здесь была
    // бы одна пара «убрано всё / добавлено всё».
    expect(diffStats(куски)).toEqual({ added: 1, removed: 1, same: 6 })
  })

  it('вставка в середину ничего не удаляет', () => {
    const куски = diffWords('первый второй', 'первый новый второй')
    expect(куски.some((p) => p.kind === 'del')).toBe(false)
    expect(стало(куски)).toBe('первый новый второй')
    expect(было(куски)).toBe('первый второй')
  })

  it('пустая версия против непустой — чистое добавление и чистое удаление', () => {
    expect(diffWords('', 'текст появился')).toEqual([{ kind: 'add', text: 'текст появился' }])
    expect(diffWords('текст исчез', '')).toEqual([{ kind: 'del', text: 'текст исчез' }])
    expect(diffWords('', '')).toEqual([])
  })

  it('одинаковые тексты — один кусок и нулевой счёт', () => {
    const куски = diffWords('ничего не менялось', 'ничего не менялось')
    expect(куски).toEqual([{ kind: 'same', text: 'ничего не менялось' }])
    expect(diffStats(куски)).toMatchObject({ added: 0, removed: 0 })
  })

  it('перестановка абзацев читается как перенос, а не как замена всего', () => {
    const куски = diffWords('А\n\nБ\n\nВ', 'А\n\nВ\n\nБ')
    expect(было(куски)).toBe('А\n\nБ\n\nВ')
    expect(стало(куски)).toBe('А\n\nВ\n\nБ')
    // Тронут один абзац из трёх: два слова, а не шесть.
    expect(diffStats(куски).added + diffStats(куски).removed).toBe(2)
  })

  it('склейка кусков возвращает оба текста знак в знак', () => {
    const a = 'Первая строка.\n  Вторая  строка.\n'
    const b = 'Первая строка!\n  Вторая строка.\nТретья.'
    const куски = diffWords(a, b)
    expect(было(куски)).toBe(a)
    expect(стало(куски)).toBe(b)
  })

  it('соседние куски одной судьбы склеены — по узлу на слово не рисуем', () => {
    const куски = diffWords('раз два три четыре', 'раз ноль ноль четыре')
    for (let i = 1; i < куски.length; i++) {
      expect(куски[i]?.kind).not.toBe(куски[i - 1]?.kind)
    }
  })

  it('за потолком не считает матрицу, а честно заменяет целиком', () => {
    // Ровно тот случай, ради которого потолок и объявлен: два больших разных
    // текста без общих краёв. Проверяется не время, а обещанная форма ответа.
    const n = Math.ceil(Math.sqrt(ПОТОЛОК)) + 10
    const a = Array.from({ length: n }, (_, i) => `a${i}`)
    const b = Array.from({ length: n }, (_, i) => `b${i}`)
    expect(diffTokens(a, b)).toEqual([
      { kind: 'del', text: a.join('') },
      { kind: 'add', text: b.join('') },
    ])
  })
})

describe('diffStats', () => {
  it('считает слова, а не пробелы и переносы', () => {
    const куски = diffWords('одно', 'одно\n\nдва   три')
    expect(diffStats(куски)).toMatchObject({ added: 2, removed: 0, same: 1 })
  })
})
