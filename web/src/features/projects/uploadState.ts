/**
 * uploadState — разбор карточки задания в то, что видит человек на загрузке.
 *
 * Служба отвечает на загрузку `202`: байты приняты, разбор уехал в очередь.
 * Дальше о файле известно ровно столько, сколько написано в карточке задания
 * `parse` — состояние, шаг прогресса и, если не сложилось, код беды. Перевод
 * этой карточки в «что показать в строке» вынесен сюда чистой функцией по двум
 * причинам: он одинаков для строки загрузки и для строки из
 * `GET …/materials/pending` (перезагрузили страницу — задание то же), и его
 * можно проверить тестом, не поднимая ни React, ни службу.
 */
import type { Job } from '@/api/hooks'

/** Стадия, на которой находится принесённый файл. */
export type UploadPhase = 'sending' | 'queued' | 'parsing' | 'done' | 'failed' | 'cancelled'

export type UploadView = {
  phase: UploadPhase
  /** Доля разбора, 0–100. `null` — служба ещё не сказала ни шага. */
  percent: number | null
  /** Что именно сейчас разбирается: имя файла или шаг обработчика. */
  note: string
  /** Код отказа для перевода (`errors.<код>`), если задание упало. */
  errorCode?: string
  /** Идентификатор разобранного материала — он же ключ в описи. */
  materialId?: string
  /** Стадия конечная: строке больше нечего ждать. */
  finished: boolean
}

const ЕСТЬ_КАРТОЧКА: Record<string, UploadPhase> = {
  queued: 'queued',
  running: 'parsing',
  done: 'done',
  failed: 'failed',
  cancelled: 'cancelled',
}

type Progress = { step?: unknown; total?: unknown; note?: unknown }

/** Доля из `progress`. Тотал ноль или мусор — доли нет, а не деление на ноль. */
function процент(progress: Progress | null | undefined): number | null {
  if (!progress) return null
  const step = Number(progress.step)
  const total = Number(progress.total)
  if (!Number.isFinite(step) || !Number.isFinite(total) || total <= 0) return null
  return Math.max(0, Math.min(100, Math.round((step / total) * 100)))
}

function код_беды(error: unknown): string | undefined {
  if (!error || typeof error !== 'object') return undefined
  const code = (error as { code?: unknown }).code
  return typeof code === 'string' && code ? code : undefined
}

/**
 * Карточка задания → строка загрузки.
 *
 * Карточки ещё нет (`undefined`) — файл в пути: запрос ушёл, ответа нет. Это
 * не «неизвестно», а вполне определённое состояние, и показать его надо, иначе
 * первые полсекунды после броска файла экран выглядит так, будто ничего не
 * произошло.
 */
export function readUploadState(job: Job | undefined | null): UploadView {
  if (!job) return { phase: 'sending', percent: null, note: '', finished: false }

  const phase = ЕСТЬ_КАРТОЧКА[job.status] ?? 'queued'
  const progress = (job.progress ?? null) as Progress | null
  const результат = (job.result ?? null) as { material?: unknown } | null
  const material = typeof результат?.material === 'string' ? результат.material : undefined

  return {
    phase,
    percent: phase === 'done' ? 100 : процент(progress),
    note: typeof progress?.note === 'string' ? progress.note : '',
    errorCode: phase === 'failed' ? код_беды(job.error) : undefined,
    materialId: material,
    finished: phase === 'done' || phase === 'failed' || phase === 'cancelled',
  }
}

/** Имя файла, под которым его загружали: оно лежит в `payload` задания `parse`. */
export function uploadName(job: Job | undefined | null, fallback = ''): string {
  const payload = (job?.payload ?? null) as { name?: unknown } | null
  return typeof payload?.name === 'string' && payload.name ? payload.name : fallback
}
