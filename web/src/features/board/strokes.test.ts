/**
 * Точки росчерка: как элемент сцены превращается в траекторию для распознавателя.
 *
 * Цена ошибки здесь — не кривая картинка, а уверенный мусор: формула, уехавшая
 * распознавателю сдвинутой или повёрнутой, разбирается уверенно и не про то, что
 * нарисовано. Поэтому проверяется именно арифметика, а не форма ответа.
 */
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

import { describe, expect, it } from 'vitest'

import type { SceneElement } from './scene'
import { absolutePoints, toScene } from './strokes'

/** Первый росчерк образцовой сцены ядра. */
function росчерк(имя: string): SceneElement {
  // Путь строится через `fileURLToPath`, а не `new URL(…, import.meta.url)`:
  // последнее Vite переписывает в импорт ресурса и отказывает файлу вне `web/`.
  const адрес = join(
    dirname(fileURLToPath(import.meta.url)),
    '..',
    '..',
    '..',
    '..',
    'tests',
    'kokuban',
    'samples',
    `${имя}.excalidraw`,
  )
  const тело = JSON.parse(readFileSync(адрес, 'utf8')) as { elements: SceneElement[] }
  return тело.elements.find((э) => э.type === 'freedraw')!
}

describe('absolutePoints', () => {
  it('локальные точки становятся координатами сцены', () => {
    // `points` у freedraw локальные: первая всегда (0, 0), дальше координаты
    // уходят в минус, как только рука пошла влево или вверх.
    const точки = absolutePoints({
      id: 'а',
      type: 'freedraw',
      x: 100,
      y: 50,
      points: [
        [0, 0],
        [-10, 5],
      ],
    })
    expect(точки).toEqual([
      [100, 50],
      [90, 55],
    ])
  })

  it('поворот считается вокруг центра габарита точек, а не элемента', () => {
    // У росчерка, написанного справа налево, `x + width / 2` промахивается мимо
    // настоящего центра на целый размер элемента.
    const повёрнут = absolutePoints({
      id: 'а',
      type: 'freedraw',
      x: 0,
      y: 0,
      width: 100,
      height: 0,
      angle: Math.PI,
      points: [
        [0, 0],
        [-20, 0],
      ],
    })
    // Разворот на пол-оборота меняет концы местами и сохраняет длину.
    expect(повёрнут[0]?.[0]).toBeCloseTo(-20)
    expect(повёрнут[1]?.[0]).toBeCloseTo(0)
  })

  it('росчерк без точек даёт пустую траекторию, а не падение', () => {
    expect(absolutePoints({ id: 'а', type: 'freedraw', x: 0, y: 0 })).toEqual([])
  })

  it('образцовый росчерк ядра читается целиком', () => {
    const элемент = росчерк('квадратное_верно')
    expect(absolutePoints(элемент).length).toBe((элемент.points ?? []).length)
  })
})

describe('toScene', () => {
  it('экранные координаты переводятся в координаты сцены с учётом масштаба', () => {
    // Панорама посреди формулы иначе сдвигает её половину относительно другой.
    expect(
      toScene(200, 100, {
        scrollX: -50,
        scrollY: -20,
        zoom: { value: 2 },
        offsetLeft: 20,
        offsetTop: 10,
      }),
    ).toEqual({ x: 140, y: 65 })
  })

  it('без состояния вида координаты остаются экранными', () => {
    expect(toScene(10, 20, {})).toEqual({ x: 10, y: 20 })
  })
})
