/**
 * Формы ответов службы, которыми пользуется область «Отчёты».
 *
 * Здесь, а не в `api/types.ts` и не в формах проектов: правило
 * `api/README.md` — «формы своих областей описывайте у себя». Карточка проекта
 * и материалы — общие с проектами, поэтому они берутся оттуда
 * (`@/features/projects/types`), а не переписываются заново: два описания
 * одного ответа разъезжаются на первой же правке службы.
 *
 * У каждой формы стоит ссылка на место в службе, откуда она берётся.
 */

/** `packages/api/projects/routes.py: теги_проекта()` — строка `GET …/tags`. */
export type ProjectTag = {
  /** Ключ тега в шаблоне: `{{цель}}` → `цель`. */
  key: string
  /** Подсказка из `{{ключ:подсказка}}`; пусто — показываем сам ключ. */
  label: string
  /** Тип значения: `markdown` | `text` | `code` | `table` | `image` | … */
  type: string
  required: boolean
  /** Задание модели на этот тег — то, что человек правит рядом с полем. */
  prompt: string
  /** Есть ли у тега хоть одна версия значения. */
  filled: boolean
  /** Кто написал то, что лежит сейчас: `manual` | `agent` | `file` | null. */
  source: string | null
  /** Номер текущей версии; `null` — значения не было. */
  version: number | null
  at: string | null
}

/**
 * Тело `GET /api/projects/{id}/tags`.
 *
 * `constructs` — конструкции бланка, которых сборщик не понимает
 * (`{% for %}`, `{%tr for %}`). Они остаются в документе текстом и сборку не
 * ломают, но знать о них человек должен до сборки, а не после.
 */
export type ProjectTagsBody = { tags: ProjectTag[]; constructs: string[] }

/**
 * Значение тега — форма `hokoku.wire`. Полей у разных типов разные, общее
 * только `type`; текстовые держат текст в `text`, поэтому здесь описан именно
 * общий случай, а не объединение всех восьми типов: сайт правит текст,
 * а остальное показывает как есть.
 */
export type TagValue = {
  type?: string
  text?: string
  [k: string]: unknown
}

/** Тело `GET /api/projects/{id}/values`. */
export type ValuesBody = { values: Record<string, TagValue> }

/** `packages/api/versions/routes.py: _шапка()` — версия значения без него самого. */
export type VersionHead = {
  n: number
  key: string
  at: string
  /** `manual` | `agent` | `file`. */
  source: string
  run: string | null
  flags: string[]
  endpoint: string
  model: string
  prompt_hash: string
  manifest_version: number
  stop: string
  usage: Record<string, unknown>
}

/** Тело `GET …/values/{key}/versions`. */
export type VersionsBody = { key: string; versions: VersionHead[] }

/** Тело `GET …/values/{key}/versions/{n}` — шапка и само значение. */
export type VersionBody = { key: string; version: VersionHead; value: TagValue }

/** Ответ `PUT …/values/{key}`. */
export type ValueWritten = { key: string; version: number; source: string; at: string }

/**
 * `packages/api/keys/routes.py: поставщики()` — пресеты модели и чем по ним
 * платить. `key_source`: `own` — свой ключ, `shared` — общий ключ службы,
 * `none` — платить нечем, прогон откажет.
 */
export type ProvidersBody = {
  providers: string[]
  key_source: Record<string, 'own' | 'shared' | 'none'>
}

/** Результат задания `build` (`packages/api/runs/handlers/build.py`). */
export type BuildResult = {
  ok?: boolean
  /** Вид выхода → идентификатор артефакта: `{docx: "9f2…", pdf: "1a0…"}`. */
  artifacts?: Record<string, string>
  problems?: number
  errors?: unknown[]
  unfilled?: string[]
}

/** Виды заданий отчётов (`packages/api/jobs/registry.py`). */
export const FILL_TAG = 'fill_tag'
export const FILL_REPORT = 'fill_report'
export const BUILD = 'build'

/** Виды кадров потока задания (`runs/handlers/common.py`, `jobs/context.py`). */
export const EV_TEXT = 'text'
export const EV_TAG_CLOSED = 'tag_closed'
export const EV_PROGRESS = 'progress'
export const EV_ARTIFACT = 'artifact'
