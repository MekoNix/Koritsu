/**
 * useJobStream — события одного задания потоком.
 *
 * Что делает сверх `useSseStream`:
 *
 * * знает адрес (`GET /api/jobs/{id}/stream`) и то, что служба закрывает поток
 *   сама, когда задание дошло до конечного состояния;
 * * отличает «закончилось» от «оборвалось»: после закрытия потока перечитывает
 *   карточку задания и переподключается, только если задание ещё живо. Иначе
 *   вкладка молотила бы переподключениями по завершённому заданию;
 * * держит карточку задания (`job`), чтобы экран показывал состояние и
 *   результат, а не только ленту кадров;
 * * на конце задания сбрасывает `usage`: остаток месяца изменился, а цифра,
 *   застывшая после запуска, читается как поломка.
 *
 * Пример:
 *
 *     const { events, job, done, status } = useJobStream(jobId)
 *
 * Виды кадров (`event.kind`) задают обработчики службы, список открыт —
 * разбирайте их у себя в области; здесь они намеренно не перечислены.
 */
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useCallback, useMemo } from 'react'

import { api, unwrap } from '../client'
import { keys } from '../queryKeys'
import { useSseStream, type SseState } from '../sse'
import { isTerminal, type JobEvent } from '../types'

/** Карточка задания. Форма — `packages/api/jobs/service.py: карточка()`. */
export type Job = {
  id: string
  kind: string
  status: string
  project_id: string | null
  result: Record<string, unknown> | null
  error: unknown
  created_at: string
  [k: string]: unknown
}

export type JobStreamState = SseState & {
  /** Карточка задания; перечитывается на конце потока. */
  job: Job | undefined
  /** Кадры, приведённые к форме события задания. */
  events: JobEvent[]
  /** Задание дошло до конечного состояния. */
  done: boolean
}

function fetchJob(id: string): Promise<Job> {
  return unwrap<Job>(api.GET('/api/jobs/{job_id}', { params: { path: { job_id: id } } }))
}

export function useJobStream(jobId: string | null | undefined): JobStreamState {
  const qc = useQueryClient()
  const id = jobId ?? null

  const jobQuery = useQuery({
    queryKey: keys.jobs.one(id ?? ''),
    queryFn: () => fetchJob(id as string),
    enabled: !!id,
  })

  const job = jobQuery.data
  const done = isTerminal(job?.status)

  const shouldReconnect = useCallback(async () => {
    if (!id) return false
    // Перечитываем карточку мимо кэша: решение «живо ли задание» принимается
    // по свежему ответу службы, а не по тому, что успело устареть.
    const fresh = await qc.fetchQuery({
      queryKey: keys.jobs.one(id),
      queryFn: () => fetchJob(id),
      staleTime: 0,
    })
    if (isTerminal(fresh.status)) {
      void qc.invalidateQueries({ queryKey: keys.usage })
      void qc.invalidateQueries({ queryKey: keys.jobs.all })
      return false
    }
    return true
  }, [id, qc])

  // Поток не открывается вовсе, если задание уже кончилось: события лежат в
  // `GET /api/jobs/{id}/events`, а поток закрылся бы первым же кадром.
  const url = id && !done ? `/api/jobs/${encodeURIComponent(id)}/stream` : null
  const stream = useSseStream({ url, shouldReconnect })

  const events = useMemo<JobEvent[]>(
    () => stream.frames.map((f) => f.data as JobEvent).filter((e): e is JobEvent => !!e),
    [stream.frames],
  )

  return { ...stream, events, job, done }
}
