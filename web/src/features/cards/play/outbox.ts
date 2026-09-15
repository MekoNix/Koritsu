/**
 * outbox — очередь неотправленных ответов вкладки.
 *
 * Оценка пишется сразу: экран показывает её в ту же секунду, а запрос уходит
 * отсюда. Пропала сеть — ответы копятся и уходят по порядку, как только связь
 * вернётся. Очередь одна на вкладку и живёт на уровне модуля, а не экрана:
 * человек, вышедший из захода без сети, не должен терять ответы оттого, что
 * экран размонтировался.
 *
 * **Переживает перезагрузку.** Очередь лежит в `sessionStorage` — хранилище
 * вкладки, а не браузера: две вкладки с одним заходом не отправят ответы
 * друг друга дважды. Хранилище может быть недоступно (приватный режим,
 * запрет сайта) — тогда очередь живёт в памяти до перезагрузки.
 *
 * **Повтор без двойной записи.** У каждого ответа свой `client_seq`, и пара
 * «заход + номер» у службы уникальна: повтор ответа, который служба уже
 * приняла, но подтверждение не дошло, второй попытки не создаёт. `409` на
 * повторе тоже считается записью.
 *
 * **Что повторяется.** Обрыв связи, `408`, `429` и `5xx` — с паузой от 1 до
 * 30 секунд, а также сразу по событию `online` и при возврате на вкладку.
 * Прочие отказы (`400`, `403`, `404`) повтор не исправит: такой ответ
 * выбрасывается из очереди, а экран узнаёт об этом через `onRejected`.
 */
import { isApiError } from '@/api'

import { postAnswer } from '../api'
import type { AnswerBody } from '../types'

export interface OutboxItem {
  projectId: string
  setId: string
  sessionId: string
  body: AnswerBody
}

const KEY = 'koritsu.cards.outbox'
const PAUSE_MIN = 1_000
const PAUSE_MAX = 30_000

function read(): OutboxItem[] {
  try {
    const raw = sessionStorage.getItem(KEY)
    const parsed: unknown = raw ? JSON.parse(raw) : []
    return Array.isArray(parsed) ? (parsed as OutboxItem[]) : []
  } catch {
    return []
  }
}

function write(list: OutboxItem[]): void {
  try {
    if (list.length) sessionStorage.setItem(KEY, JSON.stringify(list))
    else sessionStorage.removeItem(KEY)
  } catch {
    // Не записалось — очередь остаётся в памяти этой вкладки.
  }
}

let items: OutboxItem[] = read()
let flushing = false
let pause = PAUSE_MIN
let timer: ReturnType<typeof setTimeout> | null = null
const listeners = new Set<() => void>()
const rejectedListeners = new Set<(item: OutboxItem, error: unknown) => void>()

function set(next: OutboxItem[]): void {
  items = next
  write(items)
  listeners.forEach((fn) => fn())
}

function retryable(error: unknown): boolean {
  if (!isApiError(error)) return true
  const s = error.status
  return s === 0 || s === 408 || s === 429 || s >= 500
}

function schedule(): void {
  if (timer) return
  timer = setTimeout(() => {
    timer = null
    void flush()
  }, pause)
  pause = Math.min(pause * 2, PAUSE_MAX)
}

async function flush(): Promise<void> {
  if (flushing) return
  flushing = true
  try {
    while (items.length) {
      const head = items[0]
      if (!head) break
      try {
        await postAnswer(head.projectId, head.sessionId, head.body)
      } catch (error) {
        if (isApiError(error) && error.status === 409) {
          // Уже записано прежней попыткой.
        } else if (retryable(error)) {
          schedule()
          return
        } else {
          rejectedListeners.forEach((fn) => fn(head, error))
        }
      }
      pause = PAUSE_MIN
      // Сравнение по ссылке: пока шёл запрос, в хвост могли добавиться ответы.
      set(items.filter((x) => x !== head))
    }
  } finally {
    flushing = false
  }
}

function wake(): void {
  if (!items.length) return
  if (timer) {
    clearTimeout(timer)
    timer = null
  }
  pause = PAUSE_MIN
  void flush()
}

export function enqueue(item: OutboxItem): void {
  set([...items, item])
  wake()
}

export function subscribe(fn: () => void): () => void {
  listeners.add(fn)
  return () => {
    listeners.delete(fn)
  }
}

export function snapshot(): readonly OutboxItem[] {
  return items
}

export function onRejected(fn: (item: OutboxItem, error: unknown) => void): () => void {
  rejectedListeners.add(fn)
  return () => {
    rejectedListeners.delete(fn)
  }
}

if (typeof window !== 'undefined') {
  window.addEventListener('online', wake)
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') wake()
  })
  // Очередь, оставшаяся с прошлой загрузки страницы, уходит сразу.
  wake()
}
