/**
 * Арифметика графиков: масштаб, плотный ряд, координаты столбцов.
 *
 * Проверяется здесь ровно то, чем график может соврать: пропущенный день,
 * съехавший потолок оси и столбец, ставший невидимым из-за деления. Всё
 * остальное в `Chart.tsx` — разметка, и она врать не умеет.
 */
import { describe, expect, it } from 'vitest'

import { columns, fillDays, labelIndexes, niceMax, scaleOf, shortDay, sumOf } from './chart'

describe('niceMax', () => {
  it('округляет потолок оси до понятного числа', () => {
    expect(niceMax(137)).toBe(200)
    expect(niceMax(1)).toBe(1)
    expect(niceMax(3)).toBe(5)
    expect(niceMax(12)).toBe(20)
    expect(niceMax(1000)).toBe(1000)
  })

  it('на пустых и отрицательных данных даёт 1, а не 0', () => {
    // Ноль в знаменателе превратил бы все высоты в NaN, и график исчез бы
    // вместо того, чтобы стать плоским.
    expect(niceMax(0)).toBe(1)
    expect(niceMax(-5)).toBe(1)
    expect(niceMax(Number.NaN)).toBe(1)
  })
})

describe('scaleOf', () => {
  it('даёт три деления: низ, середину и верх', () => {
    expect(scaleOf([1, 7, 3])).toEqual({ max: 10, ticks: [0, 5, 10] })
  })

  it('пустой ряд — не беда', () => {
    expect(scaleOf([]).max).toBe(1)
  })

  it('дробная середина не подписывается — она соврала бы округлением', () => {
    // Ось от 0 до 1 с делением 0,5 подписалась бы как «0, 1, 1».
    expect(scaleOf([1]).ticks).toEqual([0, 1])
    expect(scaleOf([4]).ticks).toEqual([0, 5])
    expect(scaleOf([2]).ticks).toEqual([0, 1, 2])
  })
})

describe('fillDays', () => {
  it('заполняет пропущенные дни нулями', () => {
    const ряд = fillDays('2026-09-01T00:00:00+00:00', 4, [
      { day: '2026-09-01', value: 5 },
      { day: '2026-09-04', value: 7 },
    ])
    expect(ряд).toEqual([
      { day: '2026-09-01', value: 5 },
      { day: '2026-09-02', value: 0 },
      { day: '2026-09-03', value: 0 },
      { day: '2026-09-04', value: 7 },
    ])
  })

  it('дни идут подряд и через границу месяца', () => {
    const ряд = fillDays('2026-08-30', 4, [])
    expect(ряд.map((т) => т.day)).toEqual(['2026-08-30', '2026-08-31', '2026-09-01', '2026-09-02'])
  })

  it('лишние точки вне окна не попадают в ряд', () => {
    const ряд = fillDays('2026-09-02', 2, [
      { day: '2026-08-01', value: 999 },
      { day: '2026-09-02', value: 1 },
    ])
    expect(sumOf(ряд)).toBe(1)
  })

  it('битое начало и пустой период дают пустой ряд, а не падение', () => {
    expect(fillDays('не дата', 5, [])).toEqual([])
    expect(fillDays('2026-09-01', 0, [])).toEqual([])
  })
})

describe('columns', () => {
  const ряд = [
    { day: '2026-09-01', value: 0 },
    { day: '2026-09-02', value: 50 },
    { day: '2026-09-03', value: 100 },
  ]

  it('высота считается от потолка оси, а не от максимума ряда', () => {
    const столбцы = columns(ряд, 300, 100, 100)
    expect(столбцы.map((с) => с.height)).toEqual([0, 50, 100])
    // Начало отсчёта сверху, как в SVG: столбец во всю высоту начинается с нуля.
    expect(столбцы.map((с) => с.y)).toEqual([100, 50, 0])
  })

  it('между столбцами есть зазор, и они не налезают друг на друга', () => {
    const столбцы = columns(ряд, 300, 100, 100)
    expect(столбцы.map((с) => с.width)).toEqual([98, 98, 98])
    const налезают = столбцы.some(
      (с, i) => i > 0 && с.x < (столбцы[i - 1]?.x ?? 0) + (столбцы[i - 1]?.width ?? 0),
    )
    expect(налезают).toBe(false)
  })

  it('маленькое, но ненулевое значение всё равно видно', () => {
    // Столбец в полпикселя визуально равен нулю, а «сегодня чуть-чуть» и
    // «сегодня ничего» — разные новости.
    const столбцы = columns([{ day: '2026-09-01', value: 1 }], 100, 100, 10_000)
    expect(столбцы.map((с) => с.height)).toEqual([2])
  })

  it('пустой ряд и нулевые размеры не роняют счёт', () => {
    expect(columns([], 300, 100, 10)).toEqual([])
    expect(columns(ряд, 0, 100, 10)).toEqual([])
  })

  it('нулевой потолок не даёт NaN', () => {
    const столбцы = columns(ряд, 300, 100, 0)
    expect(столбцы.every((с) => Number.isFinite(с.height))).toBe(true)
  })
})

describe('labelIndexes', () => {
  it('на коротком ряде подписывает все дни', () => {
    expect(labelIndexes(4)).toEqual([0, 1, 2, 3])
  })

  it('на длинном — первый, последний и ровные промежутки', () => {
    const метки = labelIndexes(30)
    expect(метки.at(0)).toBe(0)
    expect(метки.at(-1)).toBe(29)
    expect(метки.length).toBeLessThanOrEqual(6)
  })

  it('пустой ряд — ни одной подписи', () => {
    expect(labelIndexes(0)).toEqual([])
  })
})

describe('shortDay', () => {
  it('день читается в UTC, а не в поясе браузера', () => {
    // Иначе 1 сентября в минусовом поясе показывалось бы как 31 августа, и
    // столбец переезжал бы на сутки у половины читателей.
    expect(shortDay('2026-09-01')).toContain('1')
    expect(shortDay('не дата')).toBe('не дата')
  })
})
