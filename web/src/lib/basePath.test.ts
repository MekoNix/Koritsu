/**
 * Проверки префикса пути. В Vitest `import.meta.env.BASE_URL` всегда `/`, то
 * есть здесь проверяется корневой случай — и это ровно тот, в котором ошибка
 * страшнее: под префиксом лишняя косая видна на первой же странице, а в корне
 * `//api/jobs` тихо работает у половины прокси и ломается у другой.
 */
import { describe, expect, it } from 'vitest'

import { BASE_PATH, ROUTER_BASENAME, withBase } from './basePath'

describe('префикс пути', () => {
  it('в корне пуст, а роутеру отдаётся косая', () => {
    expect(BASE_PATH).toBe('')
    // React Router просит `/`, а не пустую строку.
    expect(ROUTER_BASENAME).toBe('/')
  })

  it('withBase не добавляет и не съедает косую', () => {
    expect(withBase('/api/jobs')).toBe('/api/jobs')
    expect(withBase('/api/projects/p-1/artifacts/a-1')).toBe('/api/projects/p-1/artifacts/a-1')
  })

  it('префикс — без косой на конце, чтобы склейка давала ровно один разделитель', () => {
    // Проверяется само правило, а не значение: со строкой из `.env` оно
    // единственное, что отличает `/k7f3x9/api` от `/k7f3x9//api`.
    expect(BASE_PATH.endsWith('/')).toBe(false)
  })
})
