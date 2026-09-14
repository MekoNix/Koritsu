/**
 * Разметка формулы в сцене — на образцовых сценах ядра.
 *
 * Образцы (`tests/kokuban/samples/*.excalidraw`) — те же, по которым служба
 * собирает шаги, и берутся они именно оттуда, а не пишутся здесь заново: две
 * копии одной сцены разошлись бы на первой же правке договора, и разошлись бы
 * молча — экран показывал бы одно, а модель видела другое.
 *
 * Проверяется главное, ради чего разметка вообще существует: формула — это
 * группа росчерков с общим `groupIds[0]`, а `customData` лежит у первого
 * элемента группы в порядке массива. Разъехавшийся «первый» означает, что служба
 * увидит две формулы там, где человек написал одну.
 */
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

import { describe, expect, it } from 'vitest'

import {
  bounds,
  formulaCarrier,
  formulaElements,
  markFormula,
  placeTask,
  sceneFormulas,
  sceneToJSON,
  sha256hex,
  shortId,
  sortByReading,
  SOURCES,
  unconfirmFormula,
  type SceneElement,
} from './scene'

/** Сцена-образец ядра. Путь от этого файла, а не от корня запуска. */
function образец(имя: string): SceneElement[] {
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
  return тело.elements
}

describe('чтение образцовой сцены', () => {
  it('формулы находятся по носителю и собираются со всеми своими росчерками', () => {
    const формулы = sceneFormulas(образец('квадратное_верно'))
    expect(формулы.length).toBeGreaterThan(0)
    for (const формула of формулы) {
      // Носитель — первый элемент группы в порядке массива.
      expect(формула.elements[0]?.id).toBe(формула.carrier.id)
      expect(формула.elements.length).toBeGreaterThanOrEqual(1)
    }
    expect(формулы[0]?.latex).toBe('x^{2}+2x=8')
    expect(формулы[0]?.confirmed).toBe(true)
  })

  it('неподтверждённая формула остаётся формулой — просто не подтверждённой', () => {
    const формулы = sceneFormulas(образец('неподтверждённая_формула'))
    const неподтверждённые = формулы.filter((ф) => !ф.confirmed)
    expect(неподтверждённые.length).toBe(1)
    // Строка у неё есть: агенту она не уедет, а человеку показывается.
    expect(неподтверждённые[0]?.latex).toBe('D=2^{2}-4\\cdot 1\\cdot (-8)=36')
  })

  it('порядок чтения — сверху вниз, как читает человек и собирает служба', () => {
    const формулы = sortByReading(sceneFormulas(образец('квадратное_ошибка')))
    const высоты = формулы.map((ф) => ф.carrier.y)
    expect([...высоты].sort((а, б) => а - б)).toEqual(высоты)
  })

  it('элементы формулы находятся по любому её росчерку, не только по носителю', () => {
    const элементы = образец('квадратное_верно')
    const формула = sceneFormulas(элементы)[0]!
    const хвост = формула.elements[формула.elements.length - 1]!
    expect(formulaElements(элементы, хвост.id).map((э) => э.id)).toEqual(
      формула.elements.map((э) => э.id),
    )
    expect(formulaCarrier(элементы, хвост.id)?.id).toBe(формула.carrier.id)
  })
})

describe('markFormula', () => {
  const росчерк = (id: string, x: number): SceneElement => ({
    id,
    type: 'freedraw',
    x,
    y: 0,
    width: 10,
    height: 10,
    groupIds: [],
  })

  it('строка ложится у первого элемента группы, и только у него', () => {
    const размечено = markFormula(
      [росчерк('а', 0), росчерк('б', 20)],
      ['а', 'б'],
      'x=1',
      SOURCES.myscript,
    )
    expect(размечено[0]?.customData).toMatchObject({
      kind: 'formula',
      latex: 'x=1',
      latexConfirmed: true,
      latexSource: 'myscript',
    })
    expect(размечено[1]?.customData).toBeUndefined()
    // Группа общая и стоит первой: так её читает служба.
    expect(размечено[0]?.groupIds?.[0]).toBe(размечено[1]?.groupIds?.[0])
  })

  it('повторная правка не плодит вторую группу поверх первой', () => {
    const первый = markFormula(
      [росчерк('а', 0), росчерк('б', 20)],
      ['а', 'б'],
      'x=1',
      SOURCES.myscript,
    )
    const второй = markFormula(первый, ['а', 'б'], 'x=2', SOURCES.manual)
    expect(второй[0]?.groupIds).toEqual(первый[0]?.groupIds)
    expect(второй[0]?.customData).toMatchObject({ latex: 'x=2', latexSource: 'manual' })
  })

  it('хвост прежней разметки снимается с не-первого элемента', () => {
    // Иначе служба увидит две формулы там, где человек написал одну.
    const чужое = { ...росчерк('б', 20), customData: { kind: 'formula', latex: 'старое' } }
    const размечено = markFormula([росчерк('а', 0), чужое], ['а', 'б'], 'x=1', SOURCES.myscript)
    expect(размечено[1]?.customData).toBeNull()
  })

  it('версия элемента растёт: иначе правка не доходит до редактора', () => {
    const было = росчерк('а', 0)
    const стало = markFormula([было], ['а'], 'x=1', SOURCES.myscript)[0]!
    expect(стало.version).toBe((было.version ?? 1) + 1)
    expect(стало).not.toBe(было)
  })

  it('снятие подтверждения оставляет строку на месте', () => {
    const размечено = markFormula([росчерк('а', 0)], ['а'], 'x=1', SOURCES.myscript)
    const снято = unconfirmFormula(размечено, 'а')
    expect(снято[0]?.customData).toMatchObject({ latex: 'x=1', latexConfirmed: false })
  })
})

describe('сцена на том', () => {
  it('в записи только фон и сетка: вид холста туда не входит', () => {
    const тело = sceneToJSON([], { viewBackgroundColor: '#fff', gridSize: 20 })
    expect(тело).toMatchObject({ type: 'excalidraw', version: 2, source: 'koritsu/board' })
    expect(Object.keys(тело.appState).sort()).toEqual(['gridSize', 'viewBackgroundColor'])
  })

  it('удалённые элементы на том не уезжают', () => {
    const тело = sceneToJSON([
      { id: 'жив', type: 'freedraw', x: 0, y: 0 },
      { id: 'стёрт', type: 'freedraw', x: 0, y: 0, isDeleted: true },
    ])
    expect(тело.elements.map((э) => э.id)).toEqual(['жив'])
  })
})

describe('placeTask', () => {
  it('задача ложится ниже всего написанного, а не посреди решения', () => {
    const было: SceneElement[] = [{ id: 'а', type: 'freedraw', x: 0, y: 0, width: 50, height: 40 }]
    const стало = placeTask(было, 'Решите уравнение', 'x^{2}=9')
    const добавленные = стало.slice(было.length)
    expect(добавленные.length).toBe(2)
    for (const элемент of добавленные) {
      expect(элемент.y).toBeGreaterThan(bounds(было)!.y + bounds(было)!.height)
    }
  })

  it('без формулы кладётся только текст условия', () => {
    expect(placeTask([], 'Решите уравнение', '').length).toBe(1)
  })
})

/**
 * Короткое имя строки: им её зовут служба, файл распознанного и репетитор.
 *
 * Считают его обе стороны по отдельности — одна на Python, другая здесь, — и
 * разойдись они хоть в одном знаке, замечание к «строке 3» не нашло бы на
 * холсте ничего. Поэтому проверяется не «функция что-то вернула», а совпадение
 * с образцом шагов, собранным службой.
 */
describe('shortId', () => {
  it('sha256 считается как везде', () => {
    expect(sha256hex('')).toBe('e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855')
    expect(sha256hex('abc')).toBe(
      'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad',
    )
    // Длиннее одного блока в 64 байта: дополнение считается по-другому.
    expect(sha256hex('я'.repeat(100))).toHaveLength(64)
  })

  it('имя строки совпадает с тем, что дала служба образцу', () => {
    const адрес = join(
      dirname(fileURLToPath(import.meta.url)),
      '..',
      '..',
      '..',
      '..',
      'tests',
      'kokuban',
      'samples',
      'квадратное_верно.steps.json',
    )
    const шаги = JSON.parse(readFileSync(адрес, 'utf8')) as { id: string; elements: string[] }[]
    for (const шаг of шаги) expect(shortId(шаг.elements[0] as string)).toBe(шаг.id)
  })

  it('при столкновении имя удлиняется, а не получает счётчик', () => {
    // Счётчик зависел бы от порядка обхода, и одна и та же доска называла бы
    // строки по-разному от раза к разу.
    const занятые = new Map<string, string>([[sha256hex('чужой').slice(0, 6), 'чужой']])
    const имя = shortId('чужой', занятые)
    expect(имя).toHaveLength(6)
    const занятые2 = new Map<string, string>([[sha256hex('свой').slice(0, 6), 'другой']])
    expect(shortId('свой', занятые2)).toHaveLength(7)
  })
})
