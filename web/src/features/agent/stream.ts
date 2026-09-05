/**
 * stream — сборка `payload` и разбор кадров прогона агента.
 *
 * Обе функции чистые и живут отдельно от компонента намеренно: это то
 * единственное место, где сайт знает договор со службой про уровень 3, и
 * проверяться оно должно без браузера.
 *
 *     Что видно снаружи из хода работы
 *     --------------------------------
 *
 * Правило: «ходы агента — только итог и прогресс; инструменты и аргументы
 * наружу не уезжают». Поэтому в потоке
 * задания `agent` есть ровно три вида кадров, и больше взять неоткуда:
 *
 *     progress      сколько шагов сделано из скольких
 *     tag_closed    тег поставлен — это и есть ход, видимый человеку
 *     text          ответ модели; у уровня 3 он один и приходит в конце
 *
 * Чем инструмент был вызван и с какими аргументами — не приезжает вовсе, и
 * рисовать это нечем. Подробный след остаётся в журнале прогона.
 *
 * **Разбор — свёртка по всему списку кадров, а не накопление.** Поток
 * переподключается с последнего события (`Last-Event-ID`), и кадры после
 * обрыва приезжают те же самые; накопитель удвоил бы текст, а свёртка даёт
 * один и тот же ответ сколько угодно раз.
 */
import type { JobEvent } from '@/api/types'

import { EV_LIMIT, EV_PROGRESS, EV_TAG_CLOSED, EV_TEXT, TASK_MAX, type AgentPayload } from './types'

/** Ход агента в том виде, в каком его показывает панель. */
export type AgentMove = {
  /** Номер кадра — он же ключ списка: номера в потоке не повторяются. */
  seq: number
  /** Ключ поставленного тега. */
  key: string
}

export type AgentStreamRead = {
  /** Ходы: по одному на поставленный тег, в порядке потока. */
  moves: AgentMove[]
  /** Текст ответа модели, склеенный из кусков. */
  text: string
  /** Сделано шагов (из последнего `progress`). */
  step: number
  /** Всего шагов, если служба назвала их число; иначе 0. */
  total: number
  /** Месячный остаток кончился до первого вызова модели. */
  limitExhausted: boolean
}

/**
 * Собрать `payload` задания `agent`.
 *
 * Задача обрезается по потолку службы (15 000 знаков, `ЗАДАЧА_МАКС`), а не
 * отправляется как есть: служба отвечает на длинную задачу `400 task_too_long`,
 * и лучше не дать написать лишнее, чем показать отказ после нажатия. Поле в
 * панели стоит с тем же `maxLength`, и здесь обрезка — вторая проверка на тот
 * случай, если текст пришёл не с клавиатуры (вставка, повтор из истории).
 */
export function buildAgentPayload({
  endpoint,
  task,
  overwrite = false,
}: {
  endpoint: string
  task: string
  overwrite?: boolean
}): AgentPayload {
  return {
    endpoint,
    task: task.trim().slice(0, TASK_MAX),
    overwrite: !!overwrite,
  }
}

/** Разобрать кадры потока в ходы, текст и прогресс. */
export function readAgentStream(events: JobEvent[]): AgentStreamRead {
  const moves: AgentMove[] = []
  let text = ''
  let step = 0
  let total = 0
  let limitExhausted = false

  for (const событие of events) {
    const тело = (событие.data ?? {}) as {
      text?: unknown
      key?: unknown
      step?: unknown
      total?: unknown
    }
    if (событие.kind === EV_TEXT) {
      text += typeof тело.text === 'string' ? тело.text : ''
    } else if (событие.kind === EV_TAG_CLOSED) {
      const ключ = typeof тело.key === 'string' ? тело.key : ''
      if (ключ) moves.push({ seq: событие.seq, key: ключ })
    } else if (событие.kind === EV_PROGRESS) {
      if (typeof тело.step === 'number') step = тело.step
      if (typeof тело.total === 'number') total = тело.total
    } else if (событие.kind === EV_LIMIT) {
      limitExhausted = true
    }
  }

  return { moves, text, step, total, limitExhausted }
}

/**
 * Какие теги изменил прогон.
 *
 * Итог задания вернее потока: он приезжает целиком и переживает перезагрузку
 * страницы, тогда как кадры видит только та вкладка, что смотрела на прогон.
 * Поток берётся, пока итога ещё нет, — чтобы список наполнялся по ходу работы.
 */
export function changedKeys(
  result: { filled?: string[] } | null | undefined,
  moves: AgentMove[],
): string[] {
  const изИтога = Array.isArray(result?.filled) ? result.filled.filter((k) => !!k) : []
  if (изИтога.length) return изИтога
  return Array.from(new Set(moves.map((m) => m.key)))
}
