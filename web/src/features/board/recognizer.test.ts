/**
 * Распознавание от сцены: группировка, отпечатки, грязные строки, кэш.
 *
 * Здесь проверяется то, ради чего вся эта арифметика написана: **какие именно
 * росчерки уедут распознавателю и когда**. Ошибка тут не рисует кривую картинку
 * — она отдаёт сервису не то, что написано, и ответ приходит уверенный и не про
 * то; или, наоборот, шлёт запрос там, где ничего не менялось, и платит за это
 * человек.
 *
 * Проверки на образцовых сценах ядра (`tests/kokuban/samples/*.excalidraw`) —
 * тех же, по которым собирает шаги служба, а не на переписанных здесь заново:
 * две копии одной сцены разошлись бы на первой же правке договора, и разошлись
 * бы молча.
 */
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

import { describe, expect, it } from 'vitest'

import {
  dirtyLines,
  fairCopy,
  LINE_STATES,
  mergeRecognized,
  pruneRecognized,
  readCache,
  recognizeBodies,
  recognizedFromScene,
  sceneLines,
  stepsBody,
  syncPlaces,
  typeLine,
  type RecognizedCache,
} from './recognizer'
import type { SceneElement } from './scene'

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
  return (JSON.parse(readFileSync(адрес, 'utf8')) as { elements: SceneElement[] }).elements
}

/** Прямоугольный росчерк: четыре точки по углам. Так строки видно на глаз. */
function росчерк(id: string, x: number, y: number, ширина = 100, высота = 40): SceneElement {
  return {
    id,
    type: 'freedraw',
    x,
    y,
    width: ширина,
    height: высота,
    points: [
      [0, 0],
      [ширина, 0],
      [ширина, высота],
      [0, высота],
    ],
  }
}

/** Сдвинуть элементы целиком — как двигают выделенную строку по холсту. */
function сдвинуть(элементы: SceneElement[], dx: number, dy: number): SceneElement[] {
  return элементы.map((э) => ({ ...э, x: э.x + dx, y: э.y + dy }))
}

describe('sceneLines', () => {
  it('шесть написанных строк дают шесть групп', () => {
    // Образец собран из двенадцати росчерков, по два в строке, и сам называет
    // своё деление группами. Геометрия обязана прочитать его так же — иначе
    // экран покажет одно, а служба соберёт другое.
    const строки = sceneLines(образец('квадратное_верно'))
    expect(строки).toHaveLength(6)
    expect(строки.map((с) => с.strokes.length)).toEqual([2, 2, 2, 2, 2, 2])
  })

  it('группы совпадают с разметкой самого образца', () => {
    const элементы = образец('квадратное_верно')
    const поГруппам = new Map<string, string[]>()
    for (const э of элементы) {
      if (э.type !== 'freedraw') continue
      const имя = (э.groupIds ?? [])[0] as string
      поГруппам.set(имя, [...(поГруппам.get(имя) ?? []), э.id])
    }
    const наши = sceneLines(элементы).map((с) => [...с.strokes].sort().join(','))
    const свои = [...поГруппам.values()].map((ид) => [...ид].sort().join(','))
    expect(наши.sort()).toEqual(свои.sort())
  })

  it('строки идут сверху вниз, а идентификатор берётся у самого раннего росчерка', () => {
    const строки = sceneLines(образец('квадратное_верно'))
    const высоты = строки.map((с) => с.box.y)
    expect([...высоты].sort((а, б) => а - б)).toEqual(высоты)
    expect(строки[0]?.id).toBe(строки[0]?.strokes[0])
  })

  it('короткое имя строки — то же, что считает служба', () => {
    // Им репетитор называет строку в замечании, и по нему замечание
    // разрешается обратно в объект на доске. Разойдись эти два счёта — и
    // замечание к «строке 3» не нашло бы на холсте ничего. Образец шагов ядра
    // собран службой, и имена в нём сверяются с нашими один в один.
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
    const служба = JSON.parse(readFileSync(адрес, 'utf8')) as { id: string; elements: string[] }[]
    const наши = sceneLines(образец('квадратное_верно'))
    expect(наши.map((с) => с.step)).toEqual(служба.map((ш) => ш.id))
  })

  it('соседи по горизонтали — одна строка, разрыв по вертикали — новая', () => {
    const строки = sceneLines([
      росчерк('а', 0, 0),
      // Зазор в полсотни пикселей при высоте строки 40 — это пробел, а не конец
      // строки: потолок здесь полторы высоты.
      росчерк('б', 150, 0),
      росчерк('в', 0, 100),
    ])
    expect(строки.map((с) => с.strokes)).toEqual([['а', 'б'], ['в']])
  })

  it('точка над буквой остаётся в своей строке', () => {
    // У точки высота почти нулевая, и по бо́льшей высоте перекрытие с ней не
    // насчитать никогда — потому мерой и взята меньшая высота.
    const строки = sceneLines([росчерк('строка', 0, 0), росчерк('точка', 30, 5, 3, 3)])
    expect(строки).toHaveLength(1)
    expect(строки[0]?.strokes).toContain('точка')
  })

  it('строка, вписанная между второй и третьей, встаёт на своё место', () => {
    const строки = sceneLines([
      росчерк('первая', 0, 0),
      росчерк('вторая', 0, 100),
      росчерк('третья', 0, 300),
      // Дописана последней, но стоит выше третьей — порядок чтения идёт по
      // сцене, а не по времени письма.
      росчерк('вписанная', 0, 200),
    ])
    expect(строки.map((с) => с.id)).toEqual(['первая', 'вторая', 'вписанная', 'третья'])
  })

  it('удалённое и не-рукопись в строки не идут', () => {
    const строки = sceneLines([
      росчерк('живой', 0, 0),
      { ...росчерк('стёртый', 0, 100), isDeleted: true },
      { ...росчерк('текст', 0, 200), type: 'text' },
      { ...росчерк('репетитор', 0, 300), customData: { agent: true } },
    ])
    expect(строки.map((с) => с.id)).toEqual(['живой'])
  })
})

describe('отпечаток', () => {
  it('перенос строки целиком отпечатка не меняет', () => {
    // Точки считаются относительно габарита группы — иначе панорама группой или
    // сдвиг формулы на поля означали бы повторное распознавание всей строки.
    const было = sceneLines([росчерк('а', 0, 0), росчерк('б', 150, 0)])
    const стало = sceneLines(сдвинуть([росчерк('а', 0, 0), росчерк('б', 150, 0)], 317.5, -42.25))
    expect(стало[0]?.fingerprint).toBe(было[0]?.fingerprint)
  })

  it('дорисованный росчерк отпечаток меняет', () => {
    const было = sceneLines([росчерк('а', 0, 0)])
    const стало = sceneLines([росчерк('а', 0, 0), росчерк('б', 150, 0)])
    expect(стало[0]?.fingerprint).not.toBe(было[0]?.fingerprint)
  })

  it('другая форма при том же габарите отпечаток меняет', () => {
    const прямой = sceneLines([росчерк('а', 0, 0)])
    const кривой = sceneLines([
      {
        ...росчерк('а', 0, 0),
        points: [
          [0, 0],
          [100, 0],
          [100, 40],
          [50, 20],
        ],
      },
    ])
    expect(кривой[0]?.fingerprint).not.toBe(прямой[0]?.fingerprint)
  })

  it('стёртый и заново нарисованный росчерк — другая строка', () => {
    // Идентификаторы росчерков входят в отпечаток наравне с точками.
    const было = sceneLines([росчерк('а', 0, 0)])
    const стало = sceneLines([росчерк('новый', 0, 0)])
    expect(стало[0]?.fingerprint).not.toBe(было[0]?.fingerprint)
  })
})

describe('dirtyLines', () => {
  const элементы = [росчерк('а', 0, 0), росчерк('б', 0, 100), росчерк('в', 0, 200)]
  const строки = sceneLines(элементы)
  const кэш: RecognizedCache = Object.fromEntries(
    строки.map((с) => [
      с.id,
      {
        fingerprint: с.fingerprint,
        latex: 'x',
        state: LINE_STATES.recognized,
        elements: с.strokes,
        box: с.box,
        at: '',
      },
    ]),
  )

  it('ничего не менялось — грязных нет, и запроса не будет', () => {
    expect(dirtyLines(строки, кэш)).toHaveLength(0)
  })

  it('правка во второй строке делает грязной только вторую', () => {
    const правленые = sceneLines([...элементы, росчерк('минус', 150, 100, 30, 4)])
    const грязные = dirtyLines(правленые, кэш)
    expect(грязные.map((с) => с.id)).toEqual(['б'])
  })

  it('строка без записи в словаре грязна всегда', () => {
    expect(dirtyLines(строки, {}).map((с) => с.id)).toEqual(['а', 'б', 'в'])
  })

  it('набранная руками не грязна никогда', () => {
    // Росчерки её не перезаписывают: человек уже сказал, что здесь написано.
    const своими = typeLine(кэш, строки[1]!, 'x=2', '')
    const правленые = sceneLines([...элементы, росчерк('минус', 150, 100, 30, 4)])
    expect(dirtyLines(правленые, своими).map((с) => с.id)).toEqual([])
  })

  it('у стёртой строки распознанное выпадает из словаря', () => {
    const оставшиеся = sceneLines(элементы.filter((э) => э.id !== 'б'))
    expect(Object.keys(pruneRecognized(кэш, оставшиеся))).toEqual(['а', 'в'])
  })
})

describe('recognizeBodies', () => {
  it('в теле не больше восьми строк; девятая уезжает вторым вызовом', () => {
    const элементы = Array.from({ length: 9 }, (_, и) => росчерк(`с${и}`, 0, и * 100))
    const тела = recognizeBodies(элементы, sceneLines(элементы))
    expect(тела.map((т) => т.lines.length)).toEqual([8, 1])
    expect(тела[0]?.dpi).toBe(96)
  })

  it('точки уезжают с запасом и без отрицательных координат', () => {
    // Координаты сцены бывают и отрицательными, и шестизначными, а сервису
    // нужна страница.
    const элементы = [росчерк('а', -900, -400)]
    const тело = recognizeBodies(элементы, sceneLines(элементы))[0]
    const штрих = тело?.lines[0]?.strokes[0]
    expect(Math.min(...(штрих?.x ?? []))).toBeGreaterThan(0)
    expect(Math.min(...(штрих?.y ?? []))).toBeGreaterThan(0)
    // Времени в сцене нет вовсе: `t` — номер точки, как и у библиотеки.
    expect(штрих?.t).toEqual([0, 1, 2, 3])
  })

  it('строки пачки сохраняют взаимное расположение, а не сваливаются в одну точку', () => {
    // Вся пачка уезжает сервису одним вызовом. Сдвинь каждую строку к своему
    // началу — они лягут там друг на друга, и сервис вернёт их склеенными.
    const элементы = [росчерк('первая', 0, 0), росчерк('вторая', 0, 300)]
    const тело = recognizeBodies(элементы, sceneLines(элементы))[0]
    const сверху = тело?.lines[0]?.strokes[0]?.y ?? []
    const снизу = тело?.lines[1]?.strokes[0]?.y ?? []
    expect(Math.min(...снизу) - Math.min(...сверху)).toBeCloseTo(300)
    // И по горизонтали столбик остаётся столбиком.
    expect(тело?.lines[0]?.strokes[0]?.x[0]).toBeCloseTo(тело?.lines[1]?.strokes[0]?.x[0] ?? -1)
  })

  it('длинный росчерк прореживается до потолка сервиса', () => {
    const точки: [number, number][] = Array.from({ length: 5000 }, (_, и) => [и, и % 40])
    const элементы: SceneElement[] = [{ id: 'а', type: 'freedraw', x: 0, y: 0, points: точки }]
    const тело = recognizeBodies(элементы, sceneLines(элементы))[0]
    const сколько = тело?.lines[0]?.strokes[0]?.x.length ?? 0
    expect(сколько).toBeLessThanOrEqual(2000)
    expect(сколько).toBeGreaterThan(1000)
  })
})

describe('кэш и состояния строки', () => {
  const элементы = [росчерк('а', 0, 0), росчерк('б', 0, 100)]
  const строки = sceneLines(элементы)
  const первая = строки[0]!

  it('ответ ложится прочитанной строкой вместе с её местом на холсте', () => {
    const кэш = mergeRecognized({}, строки, [{ id: 'а', latex: 'x+1' }], 'сейчас')
    expect(кэш['а']).toMatchObject({ latex: 'x+1', state: LINE_STATES.recognized })
    expect(кэш['а']?.fingerprint).toBe(первая.fingerprint)
    // Росчерки и габарит едут на том вместе с текстом: по ним служба выстраивает
    // решение сверху вниз, когда строки отстали от сцены.
    expect(кэш['а']?.elements).toEqual(первая.strokes)
    expect(кэш['а']?.box).toEqual(первая.box)
  })

  it('прочитанное заново перезаписывает прежнее: подтверждать нечего', () => {
    let кэш = mergeRecognized({}, строки, [{ id: 'а', latex: 'x' }], '')
    кэш = mergeRecognized(кэш, строки, [{ id: 'а', latex: 'x+1' }], '')
    expect(кэш['а']).toMatchObject({ latex: 'x+1', state: LINE_STATES.recognized })
  })

  it('набранную руками распознавание не перезаписывает', () => {
    let кэш = typeLine({}, первая, 'x=2', '')
    кэш = mergeRecognized(кэш, строки, [{ id: 'а', latex: 'мусор' }], '')
    expect(кэш['а']).toMatchObject({ latex: 'x=2', state: LINE_STATES.manual })
  })

  it('строку дописали, пока строка читалась, — ответ не выдаёт себя за новое', () => {
    // Отпечаток в словаре описывает те росчерки, которые распознавали. Возьми
    // он нынешний — доска сочла бы строку разобранной и показала бы под ней
    // формулу без дописанной степени, и исправить это было бы уже нечем.
    const кэш = mergeRecognized({}, строки, [{ id: 'а', latex: 'x' }], '')
    const дописанные = sceneLines([...элементы, росчерк('степень', 110, 5, 10, 10)])
    expect(dirtyLines(дописанные, кэш).map((с) => с.id)).toContain('а')
  })

  it('строка с ошибкой в словарь не попадает и остаётся грязной', () => {
    const кэш = mergeRecognized({}, строки, [{ id: 'а', latex: '', error: 'сервис отказал' }], '')
    expect(кэш['а']).toBeUndefined()
    expect(dirtyLines(строки, кэш).map((с) => с.id)).toContain('а')
  })

  it('перенос строки обновляет её место, не трогая отпечатка', () => {
    // Отпечаток считается относительно габарита, поэтому перенесённая строка не
    // читается заново. Но её габарит в словаре обязан догнать сцену: по нему
    // строится порядок решения.
    const кэш = mergeRecognized({}, строки, [{ id: 'а', latex: 'x' }], '')
    const съехавшие = sceneLines(сдвинуть(элементы, 300, 400))
    expect(dirtyLines(съехавшие, кэш).map((с) => с.id)).not.toContain('а')
    const сведённый = syncPlaces(кэш, съехавшие)
    expect(сведённый['а']?.box.y).toBe(съехавшие[0]?.box.y)
    expect(сведённый['а']?.fingerprint).toBe(кэш['а']?.fingerprint)
  })

  it('словарь доски с подтверждениями читается как прочитанные строки', () => {
    // Такие доски заведены до того, как подтверждение убрали. Распознавать их
    // заново незачем — текст в словаре тот же самый.
    const прежний = {
      а: { fingerprint: 'ф', latex: 'x', state: 'confirmed', confirmedLatex: 'x-1', at: '' },
      б: { fingerprint: 'ц', latex: 'y', state: 'manual', at: '' },
    }
    const кэш = readCache(прежний)
    expect(кэш['а']).toMatchObject({ latex: 'x', state: LINE_STATES.recognized })
    expect(кэш['а']).not.toHaveProperty('confirmedLatex')
    expect(кэш['б']?.state).toBe(LINE_STATES.manual)
  })
})

describe('recognizedFromScene', () => {
  it('доска, заведённая до словаря, открывается без единого запроса', () => {
    // Распознанное у неё лежит в разметке росчерков. Прочитать его — значит не
    // платить за распознавание всего, что человек уже подтвердил.
    const элементы = образец('квадратное_верно')
    const строки = sceneLines(элементы)
    const кэш = recognizedFromScene(элементы, строки)
    expect(Object.keys(кэш)).toHaveLength(строки.length)
    expect(dirtyLines(строки, кэш)).toHaveLength(0)
    expect(fairCopy(строки, кэш)[0]).toMatchObject({
      state: LINE_STATES.recognized,
      latex: 'x^{2}+2x=8',
    })
  })

  it('пометка «подтверждена» из старой разметки ничего больше не решает', () => {
    const элементы = образец('неподтверждённая_формула')
    const строки = sceneLines(элементы)
    const кэш = recognizedFromScene(элементы, строки)
    expect(fairCopy(строки, кэш).every((с) => с.state !== LINE_STATES.manual)).toBe(true)
  })
})

describe('fairCopy и stepsBody', () => {
  const элементы = [росчерк('а', 0, 0), росчерк('б', 0, 100), росчерк('в', 0, 200)]
  const строки = sceneLines(элементы)

  it('строка без записи — законное «ещё не прочитано», а не беда', () => {
    const чистовик = fairCopy(строки, {})
    expect(чистовик.map((с) => с.state)).toEqual(['recognized', 'recognized', 'recognized'])
    expect(чистовик.map((с) => с.latex)).toEqual(['', '', ''])
    expect(чистовик.map((с) => с.n)).toEqual([1, 2, 3])
  })

  it('набранная руками помечается, когда росчерки после набора менялись', () => {
    const кэш = typeLine({}, строки[0]!, 'x', '')
    const правленые = sceneLines([...элементы, росчерк('хвост', 150, 0, 20, 20)])
    expect(fairCopy(правленые, кэш)[0]?.behind).toBe(true)
    expect(fairCopy(строки, кэш)[0]?.behind).toBe(false)
  })

  it('агенту уезжают прочитанные строки сверху вниз, и все — как принятые', () => {
    const кэш = mergeRecognized(
      {},
      строки,
      [
        { id: 'а', latex: 'x' },
        { id: 'б', latex: 'y' },
      ],
      '',
    )
    const тело = stepsBody(строки, кэш)
    // Имя строки в теле — короткое: им её зовут и файл распознанного, и
    // репетитор. Настоящие идентификаторы едут рядом, в `elements`.
    expect(тело.lines.map((с) => с.id)).toEqual(строки.slice(0, 2).map((с) => с.step))
    expect(тело.lines[0]).toMatchObject({ latex: 'x', confirmed: true })
    expect(тело.lines[1]).toMatchObject({ latex: 'y', confirmed: true })
    expect(тело.lines[1]?.elements).toEqual(['б'])
    // Третью строку не прочитал никто: своего текста у неё нет, и шагом решения
    // она не притворяется.
    expect(тело.lines).toHaveLength(2)
  })

  it('набранное руками так и называется источником', () => {
    const кэш = typeLine({}, строки[0]!, 'x=2', '')
    const прочитана = mergeRecognized(кэш, строки, [{ id: 'б', latex: 'y' }], '')
    const тело = stepsBody(строки, прочитана)
    expect(тело.lines[0]).toMatchObject({ latex: 'x=2', source: 'manual', confirmed: true })
    expect(тело.lines[1]?.source).toBe('myscript')
  })
})
