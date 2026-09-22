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
  /** Выбранная модель поставщика. Пусто — умолчание пресета. */
  model?: string
  created_at: string | null
  revoked_at: string | null
}

/**
 * Поставщики ключей распознавания рукописи.
 *
 * Они лежат в той же таблице, что и ключи моделей, и заводятся тем же
 * маршрутом, но платят за другое: ключ модели — за прогон, ключ MyScript — за
 * открытие доски. Поэтому в настройках у них свой подраздел, а список ключей
 * моделей их не показывает.
 *
 * Служба помечает их `kind: "ink"` в `GET /api/keys/providers`; имена повторены
 * здесь, чтобы разделение работало и на ответе без этой пометки.
 */
export const INK_PROVIDER_APP = 'myscript_app'
export const INK_PROVIDER_HMAC = 'myscript_hmac'
export const INK_PROVIDERS: readonly string[] = [INK_PROVIDER_APP, INK_PROVIDER_HMAC]

/**
 * Поставщик распознавания рукописи: по пометке службы, а если её нет — по имени.
 *
 * Одна функция на оба подраздела: «ключи моделей» отбирает ею то, чего не
 * показывает, а «распознавание рукописи» — то, что показывает. Два разных отбора
 * рядом разъехались бы на первом же новом поставщике, и ключ оказался бы либо в
 * обоих списках, либо ни в одном.
 */
export function isInkProvider(providers: KeyProviders | undefined, provider: string): boolean {
  const вид = providers?.kind?.[provider]
  return вид ? вид === 'ink' : INK_PROVIDERS.includes(provider)
}

/**
 * Поставщики моделей — те, кем агент вообще может работать.
 *
 * Отдельной функцией, потому что спрашивают её трое: выбор пресета агента,
 * список ключей и подстановка умолчания. Список, собранный по месту, однажды
 * забыл бы отфильтровать чернила — и в выборе пресета появился бы
 * `myscript_app`, у которого пресета не существует вовсе, а прогон с ним
 * служба отвергает `400 unknown_provider`.
 */
export function modelProviders(providers: KeyProviders | undefined): string[] {
  return (providers?.providers ?? []).filter((имя) => !isInkProvider(providers, имя))
}

/**
 * Тело `GET /api/keys/providers`.
 *
 * `has_key` — двоичный ответ, и другим он быть не может: прогон идёт на ключе
 * самого человека и ни на чьём другом, общего ключа службы нет. Раньше здесь
 * стоял `key_source` с тремя значениями, третьим из которых был «общий ключ»;
 * поставщик без ключа теперь просто недоступен, и экран говорит об этом прямо,
 * а не оттенком пометки.
 */
export type KeyProviders = {
  providers: string[]
  /** Есть ли у человека рабочий ключ этого поставщика. */
  has_key?: Partial<Record<string, boolean>>
  /**
   * Чем поставщик занят: `model` — вызовы модели, `ink` — распознавание
   * рукописи. Поле появилось позже списка, поэтому необязательное: пока его
   * нет, поставщиков распознавания отбирает список имён (`INK_PROVIDERS`).
   */
  kind?: Partial<Record<string, 'model' | 'ink'>>
  /** Выбранная модель поставщика. Пусто — умолчание пресета. */
  model?: Partial<Record<string, string>>
}

/** Одна модель поставщика: `GET /api/keys/{provider}/models`. */
export type ProviderModel = { id: string; title: string }

/**
 * Тело `GET /api/keys/{provider}/models`.
 *
 * `source` отвечает на вопрос, который человек задаёт, не увидев в списке
 * знакомого имени: список пришёл от поставщика (`provider`) или это то немногое,
 * что мы знаем без него (`preset`). Во втором случае `note` называет причину
 * словом из `llm.ErrorKind` — `auth`, `transport`, `no_key`.
 */
export type ProviderModels = {
  models: ProviderModel[]
  source: 'provider' | 'preset'
  note?: string
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
