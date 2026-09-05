/**
 * api/errors — единственная форма отказа службы, переведённая на русский.
 *
 * Служба отвечает `{"error": {code, message, where}}` (`packages/api/errors.py`),
 * и `message` там **по-английски** намеренно: перевод — работа интерфейса, по
 * `code`. Поэтому здесь два уровня:
 *
 * 1. `ApiError` — разобранный отказ: код, статус, место (`where`), английский
 *    текст службы. Бросается из `unwrap()`, ловится TanStack Query.
 * 2. `errorText()` — что показать человеку: русский текст по коду из
 *    `i18n/ru/errors.json`, а если кода в словаре нет — английский `message`
 *    службы. Запасной вариант нужен ровно затем, чтобы новый код на стороне
 *    службы не превращался в пустой тост.
 *
 * Сеть, упавшая до ответа, — тоже `ApiError`, с кодом `network`: экрану всё
 * равно, отказала служба или кабель, а различать эти два случая по типу
 * исключения пришлось бы в каждом обработчике.
 */

import { dictionary, t } from '@/i18n'

export const NETWORK = 'network'
export const UNKNOWN = 'unknown'

/** Тело отказа службы. */
type ErrorBody = { code?: unknown; message?: unknown; where?: unknown }

export class ApiError extends Error {
  /** Машинный код: по нему и только по нему разбирают случай. */
  readonly code: string
  /** HTTP-статус (0 — ответа не было вовсе). */
  readonly status: number
  /** Поле или параметр, о котором речь: `body.email`. */
  readonly where: string | undefined
  /** Английский текст службы. Показывается только как запасной. */
  readonly serverMessage: string

  constructor(code: string, serverMessage: string, status = 0, where?: string) {
    super(`${code}: ${serverMessage}`)
    this.name = 'ApiError'
    this.code = code
    this.status = status
    this.where = where
    this.serverMessage = serverMessage
  }

  /** Русский текст для человека. */
  get text(): string {
    return errorText(this)
  }

  /**
   * Разобрать тело отказа. Форма нарушена (прокси отдал HTML, служба упала до
   * обработчика) — код `unknown`: молчать нельзя, а выдумывать код нечестно.
   */
  static from(payload: unknown, status: number): ApiError {
    const body = (payload as { error?: ErrorBody } | undefined)?.error
    const code = typeof body?.code === 'string' && body.code ? body.code : UNKNOWN
    const message = typeof body?.message === 'string' ? body.message : `HTTP ${status}`
    const where = typeof body?.where === 'string' ? body.where : undefined
    return new ApiError(code, message, status, where)
  }

  /** Отказ сети: запрос не доехал или ответ не прочитался. */
  static network(cause: unknown): ApiError {
    const message = cause instanceof Error ? cause.message : String(cause)
    return new ApiError(NETWORK, message, 0)
  }
}

export function isApiError(e: unknown): e is ApiError {
  return e instanceof ApiError
}

/**
 * Что показать человеку. Порядок ровно такой:
 * русский текст по коду → английский текст службы → общее «что-то пошло не так».
 */
export function errorText(e: unknown): string {
  if (isApiError(e)) {
    const key = `errors.${e.code}`
    if (key in dictionary) return t(key)
    return e.serverMessage || t('errors.unknown')
  }
  if (e instanceof Error && e.message) return e.message
  return t('errors.unknown')
}

/**
 * Отказ, который относится к конкретному полю формы. Возвращает имя поля без
 * префикса `body.` — react-hook-form знает поля так, как они названы в схеме.
 */
export function errorField(e: unknown): string | undefined {
  if (!isApiError(e) || !e.where) return undefined
  return e.where.startsWith('body.') ? e.where.slice('body.'.length) : e.where
}
