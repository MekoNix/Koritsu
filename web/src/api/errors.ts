/**
 * api/errors — единственная форма отказа службы, переведённая на русский.
 *
 * Служба отвечает `{"error": {code, message, where}}` (`packages/api/errors.py`),
 * и `message` там **по-английски** намеренно: перевод — работа интерфейса, по
 * `code`. Поэтому здесь два уровня:
 *
 * 1. `ApiError` — разобранный отказ: код, статус, место (`where`), английский
 *    текст службы и номер запроса (`X-Request-Id`). Бросается из `unwrap()`,
 *    ловится TanStack Query.
 * 2. `errorWhat()` / `errorNext()` — что показать человеку.
 *
 * **Две строки, а не одна.** У каждого кода в `i18n/ru/errors.json` записано
 * «что случилось» (`what`) и «что делать» (`next`): код отказа человеку не
 * говорит ничего, а одно «Не найдено» посреди экрана не говорит, куда идти
 * дальше. Действие есть у каждого кода — это и проверяется (`errors.test.ts`).
 *
 * `errorText()` склеивает обе строки в один абзац и остаётся тем, чем был:
 * его зовут там, где на экране одна строка (подпись под полем формы, `ErrorState`).
 * Где места хватает на две — тост, страница ошибки — зовут `errorWhat()` и
 * `errorNext()` по отдельности.
 *
 * **Незнакомый код.** Служба может отдать код старше или новее словаря. Тогда
 * показывается общее «Что-то пошло не так», а английский текст службы и номер
 * запроса уходят в мелкую строку (`errorDetails()`): человеку они не нужны, а
 * в жалобе «у меня всё сломалось» номер запроса — единственное, чем она
 * связывается с записью в журнале службы.
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
  /**
   * Номер запроса из заголовка `X-Request-Id`: им ответ связывается с записью
   * в журнале службы. Пусто — ответа не было (обрыв связи) или заголовка в нём
   * не оказалось.
   */
  readonly requestId: string | undefined

  constructor(code: string, serverMessage: string, status = 0, where?: string, requestId?: string) {
    super(`${code}: ${serverMessage}`)
    this.name = 'ApiError'
    this.code = code
    this.status = status
    this.where = where
    this.serverMessage = serverMessage
    this.requestId = requestId
  }

  /** Русский текст для человека — обе строки одним абзацем. */
  get text(): string {
    return errorText(this)
  }

  /**
   * Разобрать тело отказа. Форма нарушена (прокси отдал HTML, служба упала до
   * обработчика) — код `unknown`: молчать нельзя, а выдумывать код нечестно.
   */
  static from(payload: unknown, status: number, requestId?: string): ApiError {
    const body = (payload as { error?: ErrorBody } | undefined)?.error
    const code = typeof body?.code === 'string' && body.code ? body.code : UNKNOWN
    const message = typeof body?.message === 'string' ? body.message : `HTTP ${status}`
    const where = typeof body?.where === 'string' ? body.where : undefined
    return new ApiError(code, message, status, where, requestId)
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

/** Есть ли у кода перевод. По `what`: словарь хранит две строки на код. */
function знаком(code: string): boolean {
  return `errors.${code}.what` in dictionary
}

/**
 * Что случилось — первая строка. Порядок ровно такой:
 * русский текст по коду → общее «что-то пошло не так».
 *
 * Английский текст службы сюда не попадает: он написан для того, кто читает
 * документацию API, и посреди русской страницы значит для человека не больше,
 * чем сам код. Место ему — в мелкой строке подробностей (`errorDetails`).
 */
export function errorWhat(e: unknown): string {
  if (isApiError(e)) {
    return знаком(e.code) ? t(`errors.${e.code}.what`) : t('errors.unknown.what')
  }
  if (e instanceof Error && e.message) return e.message
  return t('errors.unknown.what')
}

/** Что делать — вторая строка. У каждого кода она есть. */
export function errorNext(e: unknown): string {
  if (isApiError(e) && знаком(e.code)) return t(`errors.${e.code}.next`)
  return t('errors.unknown.next')
}

/**
 * Мелкая строка под сообщением: английский текст службы и номер запроса.
 *
 * Показывается только там, где сказать больше нечего, — у незнакомого кода.
 * Возвращает пустую строку, если ни того, ни другого нет: пустая мелкая
 * строка на экране читается как оборванный текст.
 */
export function errorDetails(e: unknown): string {
  if (!isApiError(e)) return ''
  const куски: string[] = []
  if (!знаком(e.code) && e.serverMessage) куски.push(e.serverMessage)
  if (e.requestId) куски.push(t('common.error.requestId', { rid: e.requestId }))
  return куски.join(' · ')
}

/**
 * Обе строки одним абзацем — для тех мест, где на экране только одна строка:
 * подпись под полем формы, `ErrorState`, короткое сообщение в панели.
 */
export function errorText(e: unknown): string {
  const что = errorWhat(e)
  const дальше = errorNext(e)
  return дальше ? `${что} ${дальше}` : что
}

/**
 * Отказ, который относится к конкретному полю формы. Возвращает имя поля без
 * префикса `body.` — react-hook-form знает поля так, как они названы в схеме.
 */
export function errorField(e: unknown): string | undefined {
  if (!isApiError(e) || !e.where) return undefined
  return e.where.startsWith('body.') ? e.where.slice('body.'.length) : e.where
}
