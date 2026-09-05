/**
 * Тесты разбора состояния загруженного файла.
 *
 * Проверяется то, что ломается молча: карточка задания приходит от службы, а
 * человек видит из неё три вещи — стадию, долю и текст беды. Ошибка здесь не
 * роняет ни сборку, ни экран: строка просто застревает в «разбирается» навсегда
 * или, наоборот, исчезает, не показав, почему файл не принят.
 */
import { describe, expect, it } from 'vitest'

import type { Job } from '@/api/hooks'

import { readUploadState, uploadName } from './uploadState'

/** Карточка задания `parse` — ровно те поля, которые читает разбор. */
function job(patch: Partial<Job>): Job {
  return {
    id: 'j1',
    kind: 'parse',
    status: 'queued',
    project_id: 'p1',
    result: null,
    error: null,
    created_at: '2026-09-04T21:00:00+00:00',
    ...patch,
  } as Job
}

describe('readUploadState', () => {
  it('без карточки — файл ещё в пути', () => {
    const state = readUploadState(undefined)
    expect(state.phase).toBe('sending')
    expect(state.finished).toBe(false)
    expect(state.percent).toBeNull()
  })

  it('в очереди — доли ещё нет', () => {
    const state = readUploadState(job({ status: 'queued' }))
    expect(state.phase).toBe('queued')
    expect(state.percent).toBeNull()
    expect(state.finished).toBe(false)
  })

  it('в работе — доля считается из шага и итога', () => {
    const state = readUploadState(
      job({ status: 'running', progress: { step: 1, total: 4, note: 'лаба.pdf' } }),
    )
    expect(state.phase).toBe('parsing')
    expect(state.percent).toBe(25)
    expect(state.note).toBe('лаба.pdf')
  })

  it('итог ноль — доли нет, а не деление на ноль', () => {
    const state = readUploadState(job({ status: 'running', progress: { step: 3, total: 0 } }))
    expect(state.percent).toBeNull()
  })

  it('готово — сто процентов и идентификатор материала', () => {
    const state = readUploadState(job({ status: 'done', result: { material: 'df06a90d2382ec18' } }))
    expect(state.phase).toBe('done')
    expect(state.percent).toBe(100)
    expect(state.materialId).toBe('df06a90d2382ec18')
    expect(state.finished).toBe(true)
  })

  it('упало — код беды доезжает до строки, чтобы её перевели', () => {
    const state = readUploadState(
      job({ status: 'failed', error: { code: 'parse_failed', message: 'nope' } }),
    )
    expect(state.phase).toBe('failed')
    expect(state.errorCode).toBe('parse_failed')
    expect(state.finished).toBe(true)
  })

  it('беда без кода не выдумывает код', () => {
    const state = readUploadState(job({ status: 'failed', error: 'сломалось' }))
    expect(state.errorCode).toBeUndefined()
  })

  it('незнакомое состояние службы не роняет строку', () => {
    const state = readUploadState(job({ status: 'что-то новое' }))
    expect(state.phase).toBe('queued')
    expect(state.finished).toBe(false)
  })
})

describe('uploadName', () => {
  it('берёт имя из payload задания', () => {
    expect(uploadName(job({ payload: { name: 'методичка.pdf' } }), 'запас')).toBe('методичка.pdf')
  })

  it('без имени в payload остаётся запасное', () => {
    expect(uploadName(job({ payload: {} }), 'запас')).toBe('запас')
    expect(uploadName(undefined, 'запас')).toBe('запас')
  })
})
