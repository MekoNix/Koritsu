/**
 * Формы и имена, которыми пользуется панель агента.
 *
 * Своим файлом области, а не в `api/types.ts` (правило `api/README.md`).
 * У каждой формы стоит ссылка на место в службе: поменяется там — ломаться
 * должно в одном файле.
 */

/** Вид задания уровня 3 (`packages/api/jobs/registry.py`). */
export const AGENT = 'agent'

// ── имена событий потока (`packages/api/runs/handlers/common.py`) ────────────
/** Кусок ответа модели. У уровня 3 он один и приходит в конце прогона. */
export const EV_TEXT = 'text'
/** Тег дописан и сохранён — это и есть «ход» агента наружу. */
export const EV_TAG_CLOSED = 'tag_closed'
/** Сколько шагов сделано (`JobContext.progress`). */
export const EV_PROGRESS = 'progress'
/** Месяц кончился до старта; задание закрывается `failed`. */
export const EV_LIMIT = 'limit_exhausted'

/**
 * Итог задания `agent` — то, что лежит в `job.result`.
 * `packages/api/runs/handlers/agent.py: прогнать_агента()`.
 *
 * `filled` — ключи тегов, которые прогон поставил; именно он отвечает на
 * вопрос «что изменилось», и добавочного поля службе для этого не понадобилось.
 */
export type AgentJobResult = {
  filled?: string[]
  outcome?: string
  ok?: boolean
  steps?: number
  calls?: number
  problems?: number
  stop?: string
  run?: string | null
  task_chars?: number
  key_source?: string
}

/** Тело `payload` задания `agent`. */
export type AgentPayload = {
  endpoint: string
  task: string
  /** Переписывать ли значения, поставленные рукой человека. */
  overwrite: boolean
  /** В какой отчёт работы писать; пусто — в её единственный документ. */
  report: string
}

/** Потолок задачи в знаках (`ЗАДАЧА_МАКС` в обработчике службы). */
export const TASK_MAX = 15_000
