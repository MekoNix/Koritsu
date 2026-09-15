/**
 * queue — очередь шагов захода без React: повтор «Нет», итог, текст для копии.
 *
 * **Шаг, а не ключ.** Служба выдаёт заходу список ключей, но на экране
 * карточка может встретиться до трёх раз: «Нет» возвращает её через три
 * вопроса, не больше двух раз за заход. Поэтому очередь — список шагов
 * `{key, round}`, где `round` 0 — первый показ, 1 и 2 — повторы.
 *
 * **Повтор вставляется при переходе, а не при оценке.** До перехода оценку
 * можно изменить, и «Нет», исправленное на «Да», не должно оставлять за собой
 * повтора. Шаг, породивший повтор, помечается `spawned`: отмена перехода
 * убирает повтор обратно, а второй переход не вставляет его дважды.
 */
import type { CardItem } from '../types'

import type { Answer } from './requests'

/** Через сколько вопросов возвращается «Нет». */
export const REPEAT_GAP = 3
/** Сколько раз за заход карточка возвращается. */
export const REPEAT_MAX = 2

export interface Grade {
  answer: Answer
  /** `client_seq` записанного ответа — на него ссылается исправление. */
  seq: number
}

export interface Step {
  key: string
  round: number
  /** Показан ли ответ. */
  shown?: boolean
  grade?: Grade
  /** За этим шагом в очередь вставлен повтор. */
  spawned?: boolean
}

export function stepsOf(keys: readonly string[]): Step[] {
  return keys.map((key) => ({ key, round: 0 }))
}

/** Переход с шага `cursor`: вставить повтор, если он положен. */
export function advanceQueue(queue: readonly Step[], cursor: number, repeatWrong: boolean): Step[] {
  const step = queue[cursor]
  if (!step?.grade) return queue.slice()
  const next = queue.slice()
  if (repeatWrong && step.grade.answer === 'no' && !step.spawned && step.round < REPEAT_MAX) {
    next[cursor] = { ...step, spawned: true }
    const at = Math.min(cursor + 1 + REPEAT_GAP, next.length)
    next.splice(at, 0, { key: step.key, round: step.round + 1 })
  }
  return next
}

/** Возврат на шаг `cursor`: убрать ещё не пройденный повтор, который он вставил. */
export function retreatQueue(queue: readonly Step[], cursor: number): Step[] {
  const step = queue[cursor]
  if (!step?.spawned) return queue.slice()
  const next = queue.slice()
  const i = next.findIndex((s, j) => j > cursor && s.key === step.key && s.round === step.round + 1 && !s.grade)
  if (i >= 0) next.splice(i, 1)
  next[cursor] = { ...step, spawned: false }
  return next
}

export interface Tally {
  yes: number
  no: number
  /** Ключи с последней оценкой «Нет», в порядке первой встречи. */
  wrong: string[]
}

/** Итог по карточкам: считается последняя оценка каждой карточки. */
export function tallyOf(queue: readonly Step[]): Tally {
  const last = new Map<string, Answer>()
  for (const step of queue) if (step.grade) last.set(step.key, step.grade.answer)
  let yes = 0
  const wrong: string[] = []
  for (const [key, answer] of last) {
    if (answer === 'yes') yes += 1
    else wrong.push(key)
  }
  return { yes, no: wrong.length, wrong }
}

/** Сколько шагов уже оценено — для вопроса «выйти, пройдя меньше половины?». */
export function gradedCount(queue: readonly Step[]): number {
  return queue.reduce((n, s) => n + (s.grade ? 1 : 0), 0)
}

/**
 * Карточка в Markdown для «Скопировать»: вопрос заголовком, продолжение вопроса
 * до `---`, ответ, разбор цитатой. Это текст для чтения и обсуждения карточки
 * (например, с агентом), а не часть файла набора: файл набора — JSON.
 */
export function cardMarkdown(card: Pick<CardItem, 'q' | 'a' | 'note'>): string {
  const [head = '', ...rest] = card.q.trim().split('\n')
  const parts = [`## ${head.trim()}`]
  const tail = rest.join('\n').trim()
  if (tail) parts.push(tail, '---')
  parts.push(card.a.trim())
  if (card.note?.trim()) {
    parts.push(
      card.note
        .trim()
        .split('\n')
        .map((line) => (line ? `> ${line}` : '>'))
        .join('\n'),
    )
  }
  return parts.join('\n\n') + '\n'
}
