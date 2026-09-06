/**
 * Тесты клиента: две вещи, которые ломаются молча и дорого.
 *
 * 1. Заголовок CSRF ставится на изменяющем запросе и не ставится на чтении.
 *    Забытый заголовок даёт `403 csrf_failed` на КАЖДОМ сохранении, а лишний на
 *    `GET` — ничего, поэтому проверяются оба случая, а не только первый.
 * 2. Отказ службы разбирается по коду. Это договор с интерфейсом целиком:
 *    русские тексты выбираются по `code`, и потеря кода превращает любую
 *    ошибку в «что-то пошло не так».
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { api, unwrap } from './client'
import { ApiError, NETWORK } from './errors'

/** Ответ службы в том виде, в каком его отдаёт `fetch`. */
function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

let fetchSpy: ReturnType<typeof vi.fn>

beforeEach(() => {
  document.cookie = 'koritsu_csrf=token-abc'
  fetchSpy = vi.fn()
  vi.stubGlobal('fetch', fetchSpy)
})

afterEach(() => {
  vi.unstubAllGlobals()
  document.cookie = 'koritsu_csrf=; max-age=0'
})

describe('заголовок CSRF', () => {
  it('ставится на изменяющем запросе — значением cookie', async () => {
    fetchSpy.mockResolvedValue(jsonResponse({ status: 'ok' }))

    await unwrap(api.POST('/api/auth/logout'))

    const request = fetchSpy.mock.calls[0]?.[0] as Request
    expect(request.headers.get('X-CSRF-Token')).toBe('token-abc')
  })

  it('не ставится на чтении: у GET нет последствий', async () => {
    fetchSpy.mockResolvedValue(jsonResponse([]))

    await unwrap(api.GET('/api/modules'))

    const request = fetchSpy.mock.calls[0]?.[0] as Request
    expect(request.headers.get('X-CSRF-Token')).toBeNull()
  })
})

describe('разбор отказа', () => {
  it('вытаскивает код, статус и место', async () => {
    fetchSpy.mockResolvedValue(
      jsonResponse(
        { error: { code: 'invalid_credentials', message: 'Invalid email or password' } },
        401,
      ),
    )

    const error = await unwrap(
      api.POST('/api/auth/login', { body: { email: 'a@b.c', password: 'x' } }),
    ).catch((e: unknown) => e)

    expect(error).toBeInstanceOf(ApiError)
    const api_error = error as ApiError
    expect(api_error.code).toBe('invalid_credentials')
    expect(api_error.status).toBe(401)
    // Русский текст берётся по коду, а не из английского сообщения службы,
    // и несёт обе строки отказа: что случилось и что делать.
    expect(api_error.text).toBe('Неверная почта или пароль. Проверьте раскладку и повторите вход.')
  })

  it('обрыв сети — тоже ApiError, с кодом network', async () => {
    fetchSpy.mockRejectedValue(new TypeError('Failed to fetch'))

    const error = await unwrap(api.GET('/api/modules')).catch((e: unknown) => e)

    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).code).toBe(NETWORK)
  })
})
