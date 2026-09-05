/**
 * Проверка того, откуда панель берёт работу: из адреса экрана под ней.
 * Ошибка здесь означала бы прогон в чужом проекте, и заметить её глазами
 * поздно — деньги уже потрачены.
 */
import { describe, expect, it } from 'vitest'

import { projectFromPath, tagHref } from './context'

describe('projectFromPath', () => {
  it('узнаёт работу во всех пяти разделах', () => {
    expect(projectFromPath('/reports/p-1')).toBe('p-1')
    expect(projectFromPath('/projects/p-2')).toBe('p-2')
    expect(projectFromPath('/flowcharts/p-3')).toBe('p-3')
    expect(projectFromPath('/uml/p-4')).toBe('p-4')
    expect(projectFromPath('/kadai/p-5')).toBe('p-5')
  })

  it('не путает раздел без работы и чужие адреса', () => {
    expect(projectFromPath('/reports')).toBeNull()
    expect(projectFromPath('/')).toBeNull()
    expect(projectFromPath('/settings/keys')).toBeNull()
    expect(projectFromPath('/admin/users')).toBeNull()
  })

  it('берёт работу и на вложенном адресе', () => {
    expect(projectFromPath('/reports/p-1/versions/3')).toBe('p-1')
  })
})

describe('tagHref', () => {
  it('уводит на экран отчёта с выбранным тегом', () => {
    expect(tagHref('p-1', 'цель работы')).toBe(
      '/reports/p-1?tag=%D1%86%D0%B5%D0%BB%D1%8C%20%D1%80%D0%B0%D0%B1%D0%BE%D1%82%D1%8B',
    )
  })
})
