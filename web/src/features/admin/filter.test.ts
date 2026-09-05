/**
 * Тесты поиска и страниц в списке людей.
 *
 * Проверяется здесь не «работает ли `filter`», а два случая, которые ломаются
 * молча: пустой поиск обязан показывать всех (иначе раздел встречает админа
 * словами «никого не нашлось»), и номер страницы обязан приводиться в границы
 * — сузил поиск, стоя на пятой странице, и таблица оказалась бы пустой при
 * непустом списке.
 */
import { describe, expect, it } from 'vitest'

import { countAdmins, filterUsers, pageCount, pageOf } from './filter'
import type { AdminUser } from './types'

function user(id: string, email: string, is_admin = false): AdminUser {
  return {
    id,
    email,
    nickname: email.split('@')[0] as string,
    plan: 'free',
    is_admin,
    limits: {},
    quota_bytes: 1000,
    bytes_used: 0,
    spent_units: 0,
    email_confirmed: true,
    created_at: null,
    deleted_at: null,
    blocked_at: null,
  }
}

const люди = [
  user('aaa11111', 'artem@mail.example'),
  user('bbb22222', 'Maria@mail.example', true),
  user('ccc33333', 'daniil@org.example'),
]

describe('поиск людей', () => {
  it('пустая строка даёт весь список', () => {
    expect(filterUsers(люди, '   ')).toHaveLength(3)
  })

  it('ищет по почте без учёта регистра', () => {
    expect(filterUsers(люди, 'MARIA').map((u) => u.id)).toEqual(['bbb22222'])
  })

  it('ищет по нику', () => {
    expect(filterUsers(люди, 'ARTEM').map((u) => u.id)).toEqual(['aaa11111'])
  })

  it('ищет по идентификатору', () => {
    expect(filterUsers(люди, 'ccc3').map((u) => u.email)).toEqual(['daniil@org.example'])
  })

  it('не находит — пустой список, а не весь', () => {
    expect(filterUsers(люди, 'нет такого')).toEqual([])
  })
})

describe('страницы', () => {
  it('пустой список — одна страница, а не ноль', () => {
    expect(pageCount(0, 20)).toBe(1)
  })

  it('номер за пределами приводится к последней странице', () => {
    expect(pageOf(люди, 99, 2)).toEqual([люди[2]])
  })

  it('номер меньше единицы приводится к первой', () => {
    expect(pageOf(люди, 0, 2)).toEqual([люди[0], люди[1]])
  })
})

describe('счёт админов', () => {
  it('считает только тех, у кого право есть', () => {
    expect(countAdmins(люди)).toBe(1)
  })
})
