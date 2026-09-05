/**
 * Тест на форму ответа `GET /api/auth/me`.
 *
 * Служба отвечает `{"user": {…}}`, а не профилем в корне тела. Ошибка здесь
 * не ломает ни сборку, ни типы (в OpenAPI ответ объявлен как «объект»
 * произвольной формы) — она проявляется тем, что `me.email` везде
 * `undefined`, то есть тихо и в каждом экране сразу. Такое ловится только
 * тестом.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { fetchMe } from './useMe'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

const ПРОФИЛЬ = {
  id: 'u1',
  email: 'ivan@example.org',
  plan: 'free',
  email_confirmed: true,
  totp_enabled: false,
  is_admin: true,
  created_at: '2026-09-04T12:00:00+00:00',
}

let fetchSpy: ReturnType<typeof vi.fn>

beforeEach(() => {
  fetchSpy = vi.fn()
  vi.stubGlobal('fetch', fetchSpy)
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('fetchMe', () => {
  it('снимает обёртку {"user": …} и отдаёт профиль', async () => {
    fetchSpy.mockResolvedValue(jsonResponse({ user: ПРОФИЛЬ }))

    const me = await fetchMe()

    expect(me?.email).toBe('ivan@example.org')
    // Признак админа доезжает: по нему открывается `/admin`.
    expect(me?.is_admin).toBe(true)
  })

  it('401 — это не беда, а «не вошёл»', async () => {
    fetchSpy.mockResolvedValue(
      jsonResponse({ error: { code: 'unauthenticated', message: 'Sign in first' } }, 401),
    )

    await expect(fetchMe()).resolves.toBeNull()
  })
})
