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

/**
 * Из чего сделан отчёт — им и различаются карточки одной ленты.
 *
 * `template` — отчёт по бланку: теги, значения, сборка по шаблону. `live` —
 * отчёт из задания: приложенное задание, блоки, замечания по ним и собранный
 * документ на выходе. Дороги у них разные с первого экрана, поэтому вид стоит
 * в карточке, а не выводится из заполненных полей.
 */
export type ReportKind = 'template' | 'live'

/**
 * Чем карточка «отчёта из задания» отличается от карточки отчёта по бланку.
 *
 * Поля необязательные, потому что в одной ленте едут карточки обоих видов:
 * различает их `kind`, а карточка без него — отчёт по бланку, каким лента была
 * до появления второго вида.
 */
export type LiveReportFields = {
  kind?: ReportKind
  /** Стадия сценария, на которой стоит отчёт. Пусто — его ещё не запускали. */
  stage?: string | null
  /** Состояние прогона: `running` | `waiting_user` | `done` | `failed` | … */
  state?: string | null
  /** Когда его трогали в последний раз. */
  updated_at?: string | null
}

/**
 * `packages/api/projects/reports.py: карточка()` — строка `GET …/reports`.
 *
 * Отчёт — запись журнала запусков и свой документ рядом с ней: `id` здесь и
 * есть тот `run_id`, который остальные запросы области передают как `report`.
 * `preview_artifact_id` — картинка первой страницы последней сборки; пусто у
 * отчёта, который ещё ни разу не собирали.
 *
 * `n`, `template_name` и `tags` описывают отчёт **по бланку**: у отчёта из
 * задания бланка нет вовсе, и читать их можно только после проверки `kind`.
 */
export type ProjectReport = LiveReportFields & {
  id: string
  project_id: string
  /** Имя, данное человеком. Пусто — имя рисует сайт из номера. */
  name: string
  /** Какой это отчёт работы по счёту, с 1. */
  n: number
  user_id: string | null
  created_at: string | null
  preview_artifact_id: string | null
  /** Имя бланка, по которому собирается этот отчёт; пусто — бланк неизвестен. */
  template_name: string
  /** Сколько тегов в его бланке. */
  tags: number
}

/**
 * `packages/api/projects/reports.py: список_пространства()` — строка
 * `GET /api/reports?workspace_id=`.
 *
 * Тот же отчёт, но названный вместе со своей работой: лента главной смешивает
 * отчёты разных работ, и без имени работы две «Главы 1» из разных курсовых на
 * экране неразличимы.
 */
export type WorkspaceReport = ProjectReport & {
  /** Как зовётся работа, которой принадлежит отчёт. */
  project_name: string
}

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

/**
 * Ответ `POST …/kadai/template` — бланк, сделанный из блоков отчёта.
 *
 * Бланк ложится сразу в два места: на личную полку бланков автора
 * (`template_id`) и артефактом работы (`artifact`). Первое — чтобы им можно
 * было собрать следующую работу, второе — чтобы файл остался у работы, даже
 * если запись с полки снесут.
 *
 * `blob` — готовый путь службы, по которому файл скачивается; собирать его на
 * сайте незачем, адрес бланка знает служба.
 */
export type KadaiTemplateMade = {
  template_id: string
  name: string
  /** Сколько тегов вышло из блоков. */
  tags: number
  sha256: string
  blob: string
  artifact: string
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
