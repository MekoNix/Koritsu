/**
 * Палитра графиков во всех восьми сочетаниях тема × режим.
 *
 * Проверяется не «цвета красивые», а пять вычислимых правил skill `dataviz`
 * (`paletteCheck`): полоса светлоты, пол хромы, различимость при протанопии и
 * дейтеранопии, различимость при обычном зрении и контраст к поверхности, на
 * которой график лежит. Все пары, а не только соседние: у графиков админки нет
 * одного порядка рядов, и любые два цвета могут оказаться рядом.
 *
 * Тест читает `themes.css` файлом, а не через собранный стиль: переменные тем —
 * это и есть данные, и проверять надо их, а не то, что из них построил браузер.
 * Забыли `--chart-3` в одной из восьми тем — здесь и видно; поставили в тёмной
 * теме цвет светлой — тоже.
 *
 * Поверхность считается честно: у тем `linear` и `glass` `--surface`
 * полупрозрачна, и настоящий фон под графиком — это она, положенная на `--bg`.
 * Проверять контраст к «rgba(255,255,255,.045)» бессмысленно.
 */
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { describe, expect, it } from 'vitest'

import { validatePalette } from './paletteCheck'

const ТЕМЫ = ['slate', 'paper', 'linear', 'glass']
const РЕЖИМЫ = ['light', 'dark'] as const

/** Переменные, которые обязаны быть в каждом из восьми блоков. */
const ПЕРЕМЕННЫЕ = [
  '--chart-1',
  '--chart-2',
  '--chart-3',
  '--chart-4',
  '--chart-bad',
  '--chart-grid',
]

/** Ряды: они и проверяются как палитра. Сетка — опора, а не данные. */
const РЯДЫ = ['--chart-1', '--chart-2', '--chart-3', '--chart-4', '--chart-bad']

// Путь от корня проверок (`web/`), а не от `import.meta.url`: под jsdom он
// http'шный, и `readFileSync` от него отказывается.
const css = readFileSync(resolve(process.cwd(), 'src/styles/themes.css'), 'utf8')

type Цвет = { rgb: [number, number, number]; a: number }

function разобрать(значение: string): Цвет {
  const rgba = /rgba\(([\d.]+),\s*([\d.]+),\s*([\d.]+),\s*([\d.]+)\)/.exec(значение)
  if (rgba) {
    return { rgb: [Number(rgba[1]), Number(rgba[2]), Number(rgba[3])], a: Number(rgba[4]) }
  }
  const hex = /#([0-9A-Fa-f]{6})/.exec(значение)
  if (!hex) throw new Error(`не цвет: ${значение}`)
  const h = hex[1] as string
  return {
    rgb: [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16)) as [number, number, number],
    a: 1,
  }
}

function блок(тема: string, режим: string): string {
  const начало = css.indexOf(`[data-theme='${тема}'][data-mode='${режим}'] {`)
  expect(начало, `нет блока ${тема}/${режим}`).toBeGreaterThan(-1)
  return css.slice(начало, css.indexOf('\n}', начало))
}

function переменная(тело: string, имя: string): string {
  const m = new RegExp(`${имя}:([^;]+);`).exec(тело)
  expect(m, `нет ${имя}`).not.toBeNull()
  return (m as RegExpExecArray)[1]!.trim()
}

/** Настоящий фон под графиком: `--surface` (может быть полупрозрачной) на `--bg`. */
function поверхность(тело: string): string {
  const bg = разобрать(переменная(тело, '--bg'))
  const surface = разобрать(переменная(тело, '--surface'))
  const смесь = surface.rgb.map((v, i) => v * surface.a + (bg.rgb[i] as number) * (1 - surface.a))
  return `#${смесь.map((v) => Math.round(v).toString(16).padStart(2, '0')).join('')}`
}

describe.each(ТЕМЫ)('тема %s', (тема) => {
  describe.each(РЕЖИМЫ)('режим %s', (режим) => {
    const тело = блок(тема, режим)

    it('все переменные графиков объявлены', () => {
      for (const имя of ПЕРЕМЕННЫЕ) {
        expect(переменная(тело, имя), `${тема}/${режим}: ${имя}`).toMatch(/^#[0-9A-Fa-f]{6}$/)
      }
    })

    it('палитра проходит все проверки dataviz', () => {
      const палитра = РЯДЫ.map((имя) => переменная(тело, имя))
      const итог = validatePalette(палитра, { mode: режим, surface: поверхность(тело) })
      const провалено = итог
        .filter((п) => !п.pass)
        .map((п) => `${п.name}: ${п.detail}`)
        .join('; ')
      expect(провалено, `${тема}/${режим} — ${провалено}`).toBe('')
    })
  })
})

it('во всех восьми сочетаниях палитры разные', () => {
  // Одинаковые цвета в четырёх темах означали бы, что переменные заведены зря:
  // графики нужны под тему, а не общий набор с восемью адресами.
  const наборы = new Set<string>()
  for (const тема of ТЕМЫ) {
    for (const режим of РЕЖИМЫ) {
      наборы.add(РЯДЫ.map((имя) => переменная(блок(тема, режим), имя)).join(','))
    }
  }
  expect(наборы.size).toBe(8)
})
