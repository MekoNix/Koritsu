/**
 * types — формы, которые служба объявляет как `-> dict`, поэтому в документе
 * OpenAPI у них «объект произвольной формы». Описаны здесь один раз, со
 * ссылкой на место в службе (тот же приём, что в `api/types.ts`).
 */

/** `packages/api/keys/models.py: ModelKey.to_dict()` — тело `GET /api/keys`. */
export type ModelKey = {
  id: string
  /** Имя пресета модели: `deepseek`, `anthropic`, `openrouter`. */
  provider: string
  /** Последние четыре знака — единственное, что служба рассказывает о ключе. */
  last4: string
  created_at: string | null
  revoked_at: string | null
}

/**
 * Чем платит человек за этого поставщика:
 * `own` — свой ключ, `shared` — общий ключ службы, `none` — платить нечем.
 */
export type KeySource = 'own' | 'shared' | 'none'

/**
 * Тело `GET /api/keys/providers`.
 *
 * `key_source` появился в службе позже списка, поэтому поле необязательное:
 * пока его нет, экран не догадывается про общий ключ, а просто не показывает
 * пометку. Терпимость здесь дешевле сайта, падающего от отсутствия поля.
 */
export type KeyProviders = {
  providers: string[]
  key_source?: Partial<Record<string, KeySource>>
}

/**
 * `packages/api/templates/routes.py: TemplateOut` — свой шаблон отчёта.
 *
 * `tags` — сколько тегов нашла служба тем же разбором, которым строится
 * манифест работы. Это и есть то, по чему шаблон узнают в списке, когда имена
 * похожи.
 */
export type ReportTemplate = {
  id: string
  name: string
  bytes: number
  tags: number
  /** Первые знаки sha256 содержимого: по ним видно, что файл тот же самый. */
  sha256: string
  created_at: string | null
}

/** `packages/api/tokens/routes.py: ApiTokenOut`. */
export type ApiToken = {
  id: string
  name: string
  /** Первые знаки строки после `kor_`: по ним ключ узнают в списке. */
  prefix: string
  scopes: string[]
  created_at: string | null
  last_used_at: string | null
  revoked_at: string | null
}

/** `ApiTokenCreated`: то же плюс строка ключа — в первый и последний раз. */
export type ApiTokenCreated = ApiToken & { token: string }

/**
 * Права ключа. Список закрыт службой (`packages/api/tokens/service.ПРАВА`), а
 * маршрута, который бы его отдавал, нет: имена приходится повторить здесь.
 * Ошибка не молчит — служба отвечает `400 unknown_scope` с перечислением
 * допустимых, и текст этого отказа виден человеку.
 */
export const TOKEN_SCOPES = [
  'projects:read',
  'projects:write',
  'materials:write',
  'runs:run',
] as const

export type TokenScope = (typeof TOKEN_SCOPES)[number]
