/**
 * Сортировка таблиц, выгрузка в CSV и разбор по планам.
 *
 * Проверяется то, что ломается молча: порядок равных строк, пустые значения,
 * поле с точкой с запятой внутри и почта, которую Excel примет за формулу.
 */
import { describe, expect, it } from 'vitest'

import {
  csvField,
  filterByPlan,
  filterByStatus,
  nextSort,
  planCounts,
  planRows,
  sortRows,
  statusWeight,
  toCsv,
  userStatus,
} from './table'
import type { AdminUser } from './types'

function человек(поля: Partial<AdminUser> & { id: string }): AdminUser {
  return {
    email: `${поля.id}@пример.рф`,
    nickname: поля.id,
    plan: 'free',
    is_admin: false,
    limits: {},
    quota_bytes: 100,
    bytes_used: 0,
    spent_units: 0,
    email_confirmed: true,
    created_at: null,
    deleted_at: null,
    blocked_at: null,
    ...поля,
  }
}

describe('sortRows', () => {
  const строки = [
    { имя: 'борис', число: 2 },
    { имя: 'анна', число: 10 },
    { имя: 'вера', число: 2 },
  ]

  it('числа сравниваются числами, а не строками', () => {
    // По строкам «10» оказалось бы раньше «2», и расход сортировался бы
    // алфавитом — беда, не видная на трёх строках и видная на трёхстах.
    expect(sortRows(строки, (с) => с.число, 'asc').map((с) => с.число)).toEqual([2, 2, 10])
    expect(sortRows(строки, (с) => с.число, 'desc').map((с) => с.число)).toEqual([10, 2, 2])
  })

  it('строки сравниваются по-русски', () => {
    expect(sortRows(строки, (с) => с.имя, 'asc').map((с) => с.имя)).toEqual([
      'анна',
      'борис',
      'вера',
    ])
  })

  it('равные значения сохраняют прежний порядок', () => {
    // Иначе строки прыгают на каждом перерисовывании.
    expect(sortRows(строки, (с) => с.число, 'asc').map((с) => с.имя)).toEqual([
      'борис',
      'вера',
      'анна',
    ])
  })

  it('пустые значения всегда внизу — в обе стороны', () => {
    const с_дырами = [{ д: null }, { д: 'б' }, { д: '' }, { д: 'а' }]
    expect(sortRows(с_дырами, (с) => с.д, 'asc').map((с) => с.д)).toEqual(['а', 'б', null, ''])
    expect(sortRows(с_дырами, (с) => с.д, 'desc').map((с) => с.д)).toEqual(['б', 'а', null, ''])
  })

  it('исходный массив не трогается', () => {
    const было = [...строки]
    sortRows(строки, (с) => с.число, 'desc')
    expect(строки).toEqual(было)
  })
})

describe('nextSort', () => {
  it('щелчки по столбцу идут по кругу: вверх, вниз, никак', () => {
    const первый = nextSort(null, 'plan')
    expect(первый).toEqual({ col: 'plan', dir: 'asc' })
    const второй = nextSort(первый, 'plan')
    expect(второй).toEqual({ col: 'plan', dir: 'desc' })
    expect(nextSort(второй, 'plan')).toBeNull()
  })

  it('другой столбец начинает с возрастания', () => {
    expect(nextSort({ col: 'plan', dir: 'desc' }, 'spent')).toEqual({ col: 'spent', dir: 'asc' })
  })
})

describe('csvField и toCsv', () => {
  it('поле с разделителем, кавычкой или переводом строки берётся в кавычки', () => {
    expect(csvField('обычное')).toBe('обычное')
    expect(csvField('а;б')).toBe('"а;б"')
    expect(csvField('он сказал "нет"')).toBe('"он сказал ""нет"""')
    expect(csvField('две\nстроки')).toBe('"две\nстроки"')
  })

  it('поле, похожее на формулу, обезвреживается', () => {
    // Excel выполняет такое поле при открытии файла (CSV injection).
    expect(csvField('=1+1')).toBe("'=1+1")
    expect(csvField('@СУММ(A1)')).toBe("'@СУММ(A1)")
    expect(csvField('-5')).toBe("'-5")
  })

  it('пустое значение — пустое поле, а не «null»', () => {
    expect(csvField(null)).toBe('')
    expect(csvField(undefined)).toBe('')
  })

  it('таблица собирается с точкой с запятой и CRLF', () => {
    expect(toCsv(['а', 'б'], [[1, 'два']])).toBe('а;б\r\n1;два')
  })
})

describe('planCounts', () => {
  const люди = [
    человек({ id: '1', plan: 'free', spent_units: 10 }),
    человек({ id: '2', plan: 'pro', spent_units: 5, is_admin: true }),
    человек({ id: '3', plan: 'free', spent_units: 1 }),
    человек({ id: '4', plan: '' }),
  ]

  it('считает людей, админов и расход по каждому плану', () => {
    const строки = planCounts(люди)
    expect(строки.map((с) => с.plan)).toEqual(['free', '—', 'pro'])
    expect(строки[0]).toEqual({ plan: 'free', count: 2, admins: 0, spent: 11 })
    expect(строки.find((с) => с.plan === 'pro')).toEqual({
      plan: 'pro',
      count: 1,
      admins: 1,
      spent: 5,
    })
  })

  it('пустой план не теряется, а становится прочерком', () => {
    expect(planCounts(люди).find((с) => с.plan === '—')?.count).toBe(1)
  })

  it('пустой список — пустая таблица, а не строка с нулями', () => {
    expect(planCounts([])).toEqual([])
  })
})

describe('filterByPlan', () => {
  const люди = [человек({ id: '1', plan: 'free' }), человек({ id: '2', plan: 'pro' })]

  it('пустая строка — все планы, а не «план равен пустому»', () => {
    expect(filterByPlan(люди, '')).toHaveLength(2)
  })

  it('отбирает по точному совпадению', () => {
    expect(filterByPlan(люди, 'pro').map((ч) => ч.id)).toEqual(['2'])
  })
})

describe('userStatus и filterByStatus', () => {
  const удалённый = человек({ id: '1', deleted_at: 'вчера', blocked_at: 'вчера' })
  const заблокированный = человек({ id: '2', blocked_at: 'вчера' })
  const неподтверждённый = человек({ id: '3', email_confirmed: false })
  const обычный = человек({ id: '4' })
  const все = [удалённый, заблокированный, неподтверждённый, обычный]

  it('удалённый старше заблокированного: ячейка одна, показать надо главное', () => {
    expect(userStatus(удалённый)).toBe('deleted')
  })

  it('заблокированный отличается от неподтверждённого и от обычного', () => {
    expect(userStatus(заблокированный)).toBe('blocked')
    expect(userStatus(неподтверждённый)).toBe('unconfirmed')
    expect(userStatus(обычный)).toBe('active')
  })

  it('отбор «заблокированные» не тянет удалённых заодно', () => {
    expect(filterByStatus(все, 'blocked').map((ч) => ч.id)).toEqual(['2'])
  })

  it('пустая строка — все, а не «состояние равно пустому»', () => {
    expect(filterByStatus(все, '')).toHaveLength(4)
  })

  it('сортировка ставит беду наверх, а не алфавит', () => {
    const порядок = sortRows(все, statusWeight, 'asc').map((ч) => ч.id)
    expect(порядок).toEqual(['1', '2', '3', '4'])
  })
})

describe('planRows', () => {
  const справочник = [
    { plan: 'free', monthly_units: 100, quota_bytes: 1000 },
    { plan: 'pro', monthly_units: 900, quota_bytes: 9000 },
  ]
  const люди = [
    человек({ id: '1', plan: 'free' }),
    человек({ id: '2', plan: 'free', is_admin: true, spent_units: 7 }),
    человек({ id: '3', plan: 'старьё' }),
  ]

  it('порядок — справочника, а не алфавита', () => {
    // Алфавит поставил бы `free` между `pro` и `team`, то есть старший план
    // оказался бы посередине.
    expect(planRows(люди, справочник).map((с) => с.plan)).toEqual(['free', 'pro', 'старьё'])
  })

  it('к плану справочника прикладываются числа и люди', () => {
    const строка = planRows(люди, справочник)[0]
    expect(строка).toMatchObject({
      plan: 'free',
      count: 2,
      admins: 1,
      spent: 7,
      monthly_units: 100,
      quota_bytes: 1000,
      unknown: false,
    })
  })

  it('план без людей остаётся строкой: это справочник, а не отчёт', () => {
    expect(planRows(люди, справочник).find((с) => с.plan === 'pro')).toMatchObject({
      count: 0,
      monthly_units: 900,
    })
  })

  it('план не из справочника виден отдельно и без чисел', () => {
    const чужой = planRows(люди, справочник).find((с) => с.plan === 'старьё')
    expect(чужой).toMatchObject({ count: 1, unknown: true, monthly_units: null, quota_bytes: null })
  })

  it('пустой справочник не прячет людей', () => {
    expect(
      planRows(люди, [])
        .map((с) => с.plan)
        .sort(),
    ).toEqual(['free', 'старьё'])
  })
})
