/**
 * api/client — единственная дверь в службу.
 *
 * Клиент типизирован документом OpenAPI (`schema.d.ts`, генерируется
 * `pnpm gen:api`), поэтому путь, метод, тело и ответ проверяет компилятор:
 * опечатка в адресе — ошибка сборки, а не пустой экран у человека.
 *
 * Три вещи, которые клиент делает сам и о которых экраны не думают:
 *
 * 1. **Cookie-сессия.** `credentials: 'include'` на каждом запросе. Origin тот
 *    же (`vite.config.ts` проксирует `/api`), поэтому CORS не участвует.
 * 2. **Заголовок `X-CSRF-Token`** на изменяющих запросах. Служба выдаёт
 *    cookie `koritsu_csrf` без `HttpOnly` именно затем, чтобы сайт прочитал её
 *    и повторил в заголовке (двойная отправка, `packages/api/csrf.py`).
 *    Заголовок ставится middleware, а не на вызове: маршрутов больше сотни, и
 *    первый же забытый `POST` — это 403 у человека.
 * 3. **401 → вход.** Сессия протухла — разговаривать больше не о чем.
 *    Исключение: `/api/auth/*`, где 401 значит «неверный пароль», а не
 *    «выкиньте меня отсюда».
 *
 * Разбор ошибки живёт в `unwrap()`: openapi-fetch по умолчанию отдаёт отказ
 * полем `error`, а TanStack Query ждёт исключения.
 */

import createClient, { type Middleware } from 'openapi-fetch'

import { ApiError } from './errors'
import type { paths } from './schema'

/** Имя cookie CSRF. То же, что `csrf.COOKIE` в службе. */
const CSRF_COOKIE = 'koritsu_csrf'
const CSRF_HEADER = 'X-CSRF-Token'

/** Методы с последствиями. Тот же список, что `csrf.ИЗМЕНЯЮЩИЕ`. */
const MUTATING = new Set(['POST', 'PUT', 'PATCH', 'DELETE'])

export function readCookie(name: string): string | null {
  // `document.cookie` — одна строка «a=1; b=2»; значение может быть закодировано.
  for (const part of document.cookie.split(';')) {
    const eq = part.indexOf('=')
    if (eq < 0) continue
    if (part.slice(0, eq).trim() !== name) continue
    return decodeURIComponent(part.slice(eq + 1).trim())
  }
  return null
}

/**
 * Куда уводить, когда сессии больше нет. Ставится один раз из `App`, чтобы
 * уход происходил роутером, а не перезагрузкой страницы.
 */
let onUnauthorized: (() => void) | null = null

export function setUnauthorizedHandler(handler: (() => void) | null): void {
  onUnauthorized = handler
}

const csrfMiddleware: Middleware = {
  onRequest({ request }) {
    if (!MUTATING.has(request.method.toUpperCase())) return undefined
    const token = readCookie(CSRF_COOKIE)
    if (token) request.headers.set(CSRF_HEADER, token)
    return request
  },
  onResponse({ request, response }) {
    if (response.status === 401 && !isAuthPath(request.url)) onUnauthorized?.()
    return response
  },
}

function isAuthPath(url: string): boolean {
  try {
    return new URL(url, BASE_URL).pathname.startsWith('/api/auth/')
  } catch {
    return false
  }
}

/**
 * Адрес службы — тот же origin, что у страницы. Записан явно, а не оставлен
 * пустым: `new Request('/api/…')` без схемы и хоста — законный вызов в
 * браузере и ошибка в Node, где живут тесты. Один и тот же клиент обязан
 * работать в обоих.
 */
const BASE_URL = globalThis.location?.origin ?? 'http://localhost'

export const api = createClient<paths>({
  baseUrl: BASE_URL,
  credentials: 'include',
  // `fetch` берётся при каждом вызове, а не один раз при создании клиента.
  // Разница видна только в тестах — и ровно там она и нужна: подменённый
  // `globalThis.fetch` иначе не подхватывался бы, потому что клиент создаётся
  // при импорте модуля, то есть заведомо раньше подмены.
  fetch: (request) => globalThis.fetch(request),
})
api.use(csrfMiddleware)

/** Форма ответа openapi-fetch — ровно столько, сколько нужно `unwrap`. */
type FetchResult = { data?: unknown; error?: unknown; response: Response }

/**
 * Развернуть ответ: данные или брошенный `ApiError`.
 *
 * TanStack Query отличает удачу от беды броском, а openapi-fetch — полем.
 * Мост между ними один и лежит здесь, поэтому «как выглядит ошибка» написано
 * в проекте один раз.
 *
 *     const me = await unwrap<Me>(api.GET('/api/auth/me'))
 *
 * Тип ответа задаётся параметром, а не выводится из схемы, и это не небрежность:
 * половина обработчиков службы объявлена как `-> dict`, поэтому в документе
 * OpenAPI у них стоит «объект произвольной формы», и вывод дал бы
 * `Record<string, unknown>` вместо полезного типа. Формы, которые нам нужны,
 * описаны в `api/types.ts` рядом со ссылкой на место в службе.
 */
export async function unwrap<T = unknown>(promise: Promise<FetchResult>): Promise<T> {
  let result: FetchResult
  try {
    result = await promise
  } catch (cause) {
    // Сюда попадает только несостоявшийся запрос: обрыв, отказ DNS, отменённый
    // fetch. Ответ службы, даже пятисотый, приходит полем `error`.
    throw ApiError.network(cause)
  }
  const { data, error, response } = result
  if (error !== undefined || !response.ok) throw ApiError.from(error, response.status)
  return data as T
}
