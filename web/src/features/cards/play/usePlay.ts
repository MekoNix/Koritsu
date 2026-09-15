/**
 * usePlay — состояние одного захода: очередь, оценки, карточки, отправка.
 *
 * **Откуда заход.** Служба хранит ключи захода, позицию и записанные ответы
 * (`GET …/sessions/{sid}`). Вкладка хранит больше: очередь с повторами «Нет»,
 * показан ли ответ, номер следующего ответа. Это лежит в `sessionStorage`
 * под id захода и после перезагрузки берётся оттуда, если ключи захода те
 * же. Нет записи вкладки (другая вкладка, чистое хранилище) — очередь
 * собирается из ответов службы: первая неоценённая карточка становится
 * текущей.
 *
 * **Оценка пишется сразу.** Нажатие «Да»/«Нет» меняет шаг и кладёт ответ в
 * очередь отправки (`outbox.ts`); экран не ждёт службу. Смена оценки до
 * перехода — новый ответ с `corrects`, номером исправляемого.
 *
 * **Карточки подгружаются по ключам** (`?keys=`, до 100 за запрос) на пять
 * шагов вперёд от текущего. Ключ, которого в наборе больше нет (набор заменили
 * новой версией), помечается пустым, и шаг можно пройти без оценки.
 */
import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react'

import { useT } from '@/i18n'
import { useToast } from '@/ui'

import type { CardItem, SessionStart, SessionState } from '../types'

import { enqueue, onRejected, snapshot, subscribe } from './outbox'
import { advanceQueue, retreatQueue, stepsOf, tallyOf, type Step, type Tally } from './queue'
import { fetchCardsByKeys, fetchSessionState, KEYS_PER_REQUEST, type Answer } from './requests'

/** Сколько шагов вперёд держать карточки загруженными. */
const AHEAD = 5
/** «Продолжить» предлагается для захода моложе 12 часов. */
const CONTINUE_WITHIN = 12 * 60 * 60 * 1000

// ── запись вкладки ───────────────────────────────────────────────────────────

interface PlayState {
  keys: string[]
  queue: Step[]
  cursor: number
  /** Номер следующего ответа. */
  seq: number
}

const savedKey = (sid: string) => `koritsu.cards.play.${sid}`

function readSaved(sid: string): PlayState | null {
  try {
    const raw = sessionStorage.getItem(savedKey(sid))
    if (!raw) return null
    const s = JSON.parse(raw) as Partial<PlayState>
    if (!Array.isArray(s.keys) || !Array.isArray(s.queue) || typeof s.cursor !== 'number' || typeof s.seq !== 'number') {
      return null
    }
    return s as PlayState
  } catch {
    return null
  }
}

function writeSaved(sid: string, s: PlayState): void {
  try {
    sessionStorage.setItem(savedKey(sid), JSON.stringify(s))
  } catch {
    // Не записалось — после перезагрузки очередь соберётся из ответов службы.
  }
}

// ── незаконченный заход набора ───────────────────────────────────────────────

const lastKey = (setId: string) => `koritsu.cards.last.${setId}`

/** Последний незаконченный заход набора в этом браузере, если он моложе 12 часов. */
export function readLastSession(setId: string): string | null {
  try {
    const raw = localStorage.getItem(lastKey(setId))
    if (!raw) return null
    const { sid, at } = JSON.parse(raw) as { sid?: unknown; at?: unknown }
    if (typeof sid !== 'string' || typeof at !== 'number') return null
    return Date.now() - at < CONTINUE_WITHIN ? sid : null
  } catch {
    return null
  }
}

function rememberLastSession(setId: string, sid: string): void {
  try {
    localStorage.setItem(lastKey(setId), JSON.stringify({ sid, at: Date.now() }))
  } catch {
    // Без записи «Продолжить» просто не предложится.
  }
}

function forgetLastSession(setId: string, sid: string): void {
  try {
    if (readLastSession(setId) === sid) localStorage.removeItem(lastKey(setId))
  } catch {
    // Нечего делать.
  }
}

// ── сборка из ответов службы ─────────────────────────────────────────────────

function sameKeys(a: readonly string[], b: readonly string[]): boolean {
  return a.length === b.length && a.every((k, i) => k === b[i])
}

function fromServer(server: SessionState): PlayState {
  const queue = stepsOf(server.keys)
  let maxSeq = 0
  for (const a of server.answers) {
    const seq = a.client_seq ?? 0
    maxSeq = Math.max(maxSeq, seq)
    const grade = { answer: a.answer, seq }
    let i = a.corrects != null ? queue.findIndex((s) => s.grade?.seq === a.corrects) : -1
    if (i < 0) i = queue.findIndex((s) => s.key === a.key && !s.grade)
    if (i < 0) {
      for (let j = queue.length - 1; j >= 0; j--) if (queue[j]!.key === a.key) { i = j; break }
    }
    if (i >= 0) queue[i] = { ...queue[i]!, grade, shown: queue[i]!.shown || !!a.shown }
  }
  const firstOpen = queue.findIndex((s) => !s.grade)
  return {
    keys: server.keys,
    queue,
    cursor: firstOpen < 0 ? queue.length : firstOpen,
    seq: Math.max(maxSeq, server.answers.length) + 1,
  }
}

// ── хук ──────────────────────────────────────────────────────────────────────

export type PlayStatus = 'loading' | 'error' | 'empty' | 'playing' | 'done'

export interface UsePlayArgs {
  projectId: string
  setId: string
  sessionId: string
  /** Ответ `POST …/sessions`, если экран открыт сразу после старта захода. */
  start?: SessionStart | null
  repeatWrong: boolean
}

export interface Play {
  status: PlayStatus
  error: unknown
  reload: () => void

  queue: readonly Step[]
  cursor: number
  step: Step | undefined
  /** Карточка текущего шага: `undefined` — грузится, `null` — нет в наборе. */
  card: CardItem | null | undefined
  cardError: unknown
  retryCards: () => void
  cardOf: (key: string) => CardItem | null | undefined

  tally: Tally
  /** Ответов захода, ещё не принятых службой. */
  unsaved: number

  reveal: () => void
  grade: (answer: Answer) => boolean
  next: () => boolean
  back: () => boolean
}

export function usePlay({ projectId, setId, sessionId, start, repeatWrong }: UsePlayArgs): Play {
  const t = useT()
  const toast = useToast()

  const [phase, setPhase] = useState<'loading' | 'error' | 'ready'>('loading')
  const [error, setError] = useState<unknown>(null)
  const [attempt, setAttempt] = useState(0)
  const [state, setState] = useState<PlayState>({ keys: [], queue: [], cursor: 0, seq: 1 })
  const stateRef = useRef(state)

  const commit = useCallback(
    (next: PlayState) => {
      stateRef.current = next
      setState(next)
      writeSaved(sessionId, next)
    },
    [sessionId],
  )

  // ── карточки ──
  const cache = useRef(new Map<string, CardItem | null>())
  const [, setCardsVersion] = useState(0)
  const [cardError, setCardError] = useState<unknown>(null)
  const want = useRef(new Set<string>())
  const pumping = useRef(false)

  const put = useCallback((cards: readonly CardItem[]) => {
    for (const c of cards) cache.current.set(c.key, c)
  }, [])

  const pump = useCallback(async () => {
    if (pumping.current) return
    pumping.current = true
    try {
      for (;;) {
        const need = [...want.current].filter((k) => !cache.current.has(k)).slice(0, KEYS_PER_REQUEST)
        if (!need.length) break
        put(await fetchCardsByKeys(projectId, setId, need))
        // Ключа нет в ответе — такой карточки в наборе больше нет: помечается
        // пустой, иначе запрос за ней повторялся бы на каждом шаге.
        for (const k of need) if (!cache.current.has(k)) cache.current.set(k, null)
        setCardsVersion((v) => v + 1)
      }
      setCardError(null)
    } catch (e) {
      setCardError(e)
    } finally {
      pumping.current = false
    }
  }, [projectId, setId, put])

  // ── загрузка захода ──
  useEffect(() => {
    let cancelled = false
    setPhase('loading')
    setError(null)
    if (start?.session_id === sessionId && Array.isArray(start.cards)) put(start.cards)

    const saved = readSaved(sessionId)
    const fresh: SessionState | null =
      start?.session_id === sessionId ? { keys: start.keys, pos: 0, answers: [] } : null

    fetchSessionState(projectId, sessionId)
      .catch((e: unknown) => {
        // Открыли сразу после старта, а сеть пропала — ключи уже на руках.
        if (fresh) return fresh
        throw e
      })
      .then((server) => {
        if (cancelled) return
        const base = saved && sameKeys(saved.keys, server.keys) ? saved : fromServer(server)
        // Номер не должен повторить ни записанный, ни ждущий отправки ответ.
        const waiting = snapshot()
          .filter((x) => x.sessionId === sessionId)
          .reduce((m, x) => Math.max(m, x.body.client_seq), 0)
        commit({ ...base, seq: Math.max(base.seq, waiting + 1) })
        setPhase('ready')
      })
      .catch((e: unknown) => {
        if (cancelled) return
        setError(e)
        setPhase('error')
      })
    return () => {
      cancelled = true
    }
    // `start` читается один раз при открытии захода.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, setId, sessionId, attempt, commit, put])

  const { queue, cursor } = state
  const done = phase === 'ready' && queue.length > 0 && cursor >= queue.length
  const tally = useMemo(() => tallyOf(queue), [queue])

  // Карточки на несколько шагов вперёд, а в итогах — все «Нет».
  useEffect(() => {
    if (phase !== 'ready') return
    const keys = done ? tally.wrong : queue.slice(cursor, cursor + AHEAD).map((s) => s.key)
    let added = false
    for (const k of keys) {
      if (!want.current.has(k)) {
        want.current.add(k)
        added = true
      }
    }
    if (added) void pump()
  }, [phase, done, queue, cursor, tally.wrong, pump])

  // Незаконченный заход предлагается продолжить со страницы набора.
  useEffect(() => {
    if (phase !== 'ready' || !queue.length) return
    if (done) forgetLastSession(setId, sessionId)
    else rememberLastSession(setId, sessionId)
  }, [phase, done, queue.length, setId, sessionId])

  // Время на карточке — от её появления до оценки.
  const shownAt = useRef(Date.now())
  useEffect(() => {
    shownAt.current = Date.now()
  }, [cursor])

  // ── очередь отправки ──
  const outbox = useSyncExternalStore(subscribe, snapshot)
  const unsaved = useMemo(() => outbox.filter((x) => x.sessionId === sessionId).length, [outbox, sessionId])

  useEffect(
    () =>
      onRejected((item, e) => {
        if (item.sessionId === sessionId) toast.fail(e, t('cards.play.saveFailed'))
      }),
    [sessionId, t, toast],
  )

  // ── действия ──
  const step = queue[cursor]
  const card = step ? cache.current.get(step.key) : undefined

  const reveal = useCallback(() => {
    const s = stateRef.current
    const cur = s.queue[s.cursor]
    if (!cur || cur.shown) return
    const q = s.queue.slice()
    q[s.cursor] = { ...cur, shown: true }
    commit({ ...s, queue: q })
  }, [commit])

  const grade = useCallback(
    (answer: Answer) => {
      const s = stateRef.current
      const cur = s.queue[s.cursor]
      if (!cur || cur.grade?.answer === answer) return false
      const seq = s.seq
      const q = s.queue.slice()
      q[s.cursor] = { ...cur, grade: { answer, seq } }
      commit({ ...s, queue: q, seq: seq + 1 })
      enqueue({
        projectId,
        setId,
        sessionId,
        body: {
          key: cur.key,
          answer,
          shown: !!cur.shown,
          ms: Math.max(0, Date.now() - shownAt.current),
          client_seq: seq,
          ...(cur.grade ? { corrects: cur.grade.seq } : {}),
        },
      })
      return true
    },
    [commit, projectId, setId, sessionId],
  )

  const next = useCallback(() => {
    const s = stateRef.current
    const cur = s.queue[s.cursor]
    if (!cur) return false
    // Карточку, пропавшую из набора, можно пройти без оценки.
    if (!cur.grade && cache.current.get(cur.key) !== null) return false
    commit({ ...s, queue: advanceQueue(s.queue, s.cursor, repeatWrong), cursor: s.cursor + 1 })
    return true
  }, [commit, repeatWrong])

  const back = useCallback(() => {
    const s = stateRef.current
    if (s.cursor <= 0) return false
    const prev = s.cursor - 1
    commit({ ...s, queue: retreatQueue(s.queue, prev), cursor: prev })
    return true
  }, [commit])

  const retryCards = useCallback(() => {
    setCardError(null)
    void pump()
  }, [pump])

  const cardOf = useCallback((key: string) => cache.current.get(key), [])

  const status: PlayStatus =
    phase === 'loading' ? 'loading' : phase === 'error' ? 'error' : !queue.length ? 'empty' : done ? 'done' : 'playing'

  return {
    status,
    error,
    reload: () => setAttempt((n) => n + 1),
    queue,
    cursor,
    step,
    card,
    cardError,
    retryCards,
    cardOf,
    tally,
    unsaved,
    reveal,
    grade,
    next,
    back,
  }
}
