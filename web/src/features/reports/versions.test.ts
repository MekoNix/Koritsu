/**
 * Проверки истории версий: сборка списка и выбор двух версий для сравнения.
 *
 * Оба места тихие. Список строится из ответа службы, где возврат **не** отдельный
 * источник, а флаг у обычной версии; ошибка здесь означала бы историю, в которой
 * возврат неотличим от новой генерации. Выбор двух версий — правило «одна
 * отметка = эта и текущая», и ошибка в нём показывает человеку разницу не с тем,
 * с чем он просил.
 */
import { describe, expect, it } from 'vitest'

import type { VersionHead } from './types'
import { versionEntries, сравниваемые, заметка } from './versions'

function версия(part: Partial<VersionHead> & { n: number }): VersionHead {
  return {
    key: 'цель',
    at: '2026-09-04T10:00:00+00:00',
    source: 'manual',
    run: null,
    flags: [],
    endpoint: '',
    model: '',
    prompt_hash: '',
    manifest_version: 1,
    stop: '',
    usage: {},
    ...part,
  }
}

/** Словарь в проверках не грузится, поэтому `t` — сам ключ с подстановкой. */
const t = ((key: string, vars?: Record<string, string | number>) =>
  vars ? `${key}:${Object.values(vars).join(',')}` : key) as never

describe('versionEntries', () => {
  it('переносит номер, время и источник как есть', () => {
    const строки = versionEntries(
      [версия({ n: 1, source: 'agent' }), версия({ n: 2, source: 'manual' })],
      t,
    )
    expect(строки.map((s) => [s.n, s.source])).toEqual([
      [1, 'agent'],
      [2, 'manual'],
    ])
    expect(строки.every((s) => s.note === null)).toBe(true)
  })

  it('возврат виден по флагу, а не по источнику', () => {
    // Служба сохраняет `source` от возвращённой версии, поэтому «модель» здесь
    // правда: текст написан моделью. Что его вернули — говорит флаг.
    const строки = versionEntries(
      [версия({ n: 3, source: 'agent', flags: ['вернули версию 1'] })],
      t,
    )
    expect(строки[0]?.source).toBe('agent')
    expect(строки[0]?.note).toBe('reports.versions.restoredFrom:1')
  })

  it('чужие флаги заметкой не становятся', () => {
    expect(заметка(версия({ n: 2, flags: ['черновик', 'обрезано'] }), t)).toBeNull()
  })

  it('пустой ответ — пустой список, а не падение', () => {
    expect(versionEntries(undefined, t)).toEqual([])
  })
})

describe('сравниваемые', () => {
  const версии = [1, 2, 3]

  it('без отметок сравнивать нечего', () => {
    expect(сравниваемые([], версии)).toEqual([null, null])
  })

  it('одна отметка — эта и текущая, младшая слева', () => {
    expect(сравниваемые([1], версии)).toEqual([1, 3])
    expect(сравниваемые([2], версии)).toEqual([2, 3])
  })

  it('отметили текущую — сравниваем с предыдущей, а не саму с собой', () => {
    expect(сравниваемые([3], версии)).toEqual([2, 3])
  })

  it('две отметки — младшая слева, в каком бы порядке ни отметили', () => {
    expect(сравниваемые([3, 1], версии)).toEqual([1, 3])
    expect(сравниваемые([1, 3], версии)).toEqual([1, 3])
  })

  it('единственная версия сравнивается не с чем', () => {
    expect(сравниваемые([1], [1])).toEqual([null, 1])
  })
})
