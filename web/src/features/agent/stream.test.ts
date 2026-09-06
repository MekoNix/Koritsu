/**
 * Проверка договора со службой: что уезжает в `payload` и что приезжает в
 * потоке. Это единственное место, где сайт знает про уровень 3, и проверяется
 * оно без браузера.
 */
import { describe, expect, it } from 'vitest'

import type { JobEvent } from '@/api/types'

import { buildAgentPayload, changedKeys, readAgentStream } from './stream'
import { TASK_MAX } from './types'

function кадр(seq: number, kind: string, data: Record<string, unknown>): JobEvent {
  return { seq, kind, data, at: '2026-09-05T01:00:00+00:00' }
}

describe('buildAgentPayload', () => {
  it('складывает пресет, задачу и признак перезаписи', () => {
    expect(
      buildAgentPayload({ endpoint: 'deepseek', task: '  перепиши введение короче  ' }),
    ).toEqual({
      endpoint: 'deepseek',
      task: 'перепиши введение короче',
      overwrite: false,
      report: '',
    })
  })

  it('обрезает задачу по потолку службы, а не отправляет отказ', () => {
    const длинная = 'я'.repeat(TASK_MAX + 100)
    const payload = buildAgentPayload({ endpoint: 'anthropic', task: длинная, overwrite: true })
    expect(payload.task).toHaveLength(TASK_MAX)
    expect(payload.overwrite).toBe(true)
  })
})

describe('readAgentStream', () => {
  const события = [
    кадр(1, 'progress', { step: 0, total: 12, note: 'agent' }),
    кадр(2, 'text', { text: 'Разобрал ' }),
    кадр(3, 'text', { text: 'проект.' }),
    кадр(4, 'tag_closed', { key: 'теория', ok: true }),
    кадр(5, 'tag_closed', { key: 'вывод', ok: true }),
    кадр(6, 'progress', { step: 7, total: 7, note: 'agent' }),
  ]

  it('разбирает кадры в ходы, текст и прогресс', () => {
    const read = readAgentStream(события)
    expect(read.moves.map((m) => m.key)).toEqual(['теория', 'вывод'])
    expect(read.text).toBe('Разобрал проект.')
    expect(read.step).toBe(7)
    expect(read.total).toBe(7)
    expect(read.limitExhausted).toBe(false)
  })

  it('даёт тот же ответ на повторно приехавших кадрах', () => {
    // Поток переподключается с последнего события, и кадры приходят те же:
    // свёртка обязана быть устойчивой к этому, накопитель — нет.
    expect(readAgentStream(события)).toEqual(readAgentStream([...события]))
  })

  it('замечает кончившийся месячный остаток', () => {
    expect(readAgentStream([кадр(1, 'limit_exhausted', {})]).limitExhausted).toBe(true)
  })
})

describe('changedKeys', () => {
  it('берёт итог задания, когда он есть', () => {
    const moves = [{ seq: 1, key: 'теория' }]
    expect(changedKeys({ filled: ['теория', 'вывод'] }, moves)).toEqual(['теория', 'вывод'])
  })

  it('пока итога нет — берёт ходы, без повторов', () => {
    const moves = [
      { seq: 1, key: 'теория' },
      { seq: 2, key: 'теория' },
    ]
    expect(changedKeys(null, moves)).toEqual(['теория'])
  })
})
