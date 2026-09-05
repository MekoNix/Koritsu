/**
 * Тесты отбора в палитре поиска.
 *
 * Проверяется не «работает ли `indexOf`», а четыре случая, из-за которых поиск
 * кажется сломанным, ничего при этом не ломая:
 *
 * 1. пустой запрос обязан давать пустую выдачу, а не весь список — палитра
 *    открывается пустой, а не «всеми работами»;
 * 2. регистр и «ё» не считаются: «Ёлка» находится по «елка»;
 * 3. совпадение по середине имени работает — работы называют «Лабораторная 4 —
 *    сортировки», а ищут «сорти»;
 * 4. работа стоит выше файла: её ищут чаще.
 */
import { describe, expect, it } from 'vitest'

import { currentProjectId, filterHits, score, type Hit } from './filter'

const работа = (id: string, name: string): Hit => ({
  kind: 'project',
  id,
  name,
  workspace: 'Личное',
  to: `/projects/${id}`,
})

const файл = (id: string, name: string): Hit => ({
  kind: 'material',
  id,
  name,
  project: 'Лабораторная 4',
  to: '/projects/p1',
})

const всё: Hit[] = [
  работа('p1', 'Лабораторная 4 — сортировки'),
  работа('p2', 'Ёлка и снег'),
  работа('p3', 'Курсовая по базам данных'),
  файл('m1', 'сортировки.pdf'),
  файл('m2', 'условие.docx'),
]

describe('отбор в палитре', () => {
  it('пустой запрос ничего не показывает', () => {
    expect(filterHits(всё, '   ')).toEqual([])
  })

  it('регистр и «ё» не считаются', () => {
    expect(filterHits(всё, 'елка').map((h) => h.id)).toEqual(['p2'])
    expect(filterHits(всё, 'ЁЛКА').map((h) => h.id)).toEqual(['p2'])
  })

  it('ищет по середине имени и ставит работу выше файла', () => {
    const найдено = filterHits(всё, 'сорти')
    expect(найдено.map((h) => h.id)).toEqual(['p1', 'm1'])
  })

  it('слова ищутся все и в любом порядке', () => {
    expect(filterHits(всё, '4 лабораторная').map((h) => h.id)).toEqual(['p1'])
    expect(filterHits(всё, 'лабораторная тесты')).toEqual([])
  })

  it('несовпадение — это null, а не ноль очков', () => {
    expect(score('Лабораторная 4', 'курсовая')).toBeNull()
    expect(score('Лабораторная 4', 'лаб')).not.toBeNull()
  })
})

describe('какая работа открыта', () => {
  const id = '0f1d4b18-2c3a-4a1e-9c77-1d2e3f4a5b6c'

  it('берётся из адреса модуля', () => {
    expect(currentProjectId(`/projects/${id}`)).toBe(id)
    expect(currentProjectId(`/reports/${id}`)).toBe(id)
    expect(currentProjectId(`/kadai/${id}`)).toBe(id)
    expect(currentProjectId(`/flowcharts/${id}/edit`)).toBe(id)
  })

  it('на экранах без работы её нет', () => {
    expect(currentProjectId('/')).toBeNull()
    expect(currentProjectId('/projects')).toBeNull()
    expect(currentProjectId('/settings/keys')).toBeNull()
  })
})
