/**
 * useKadaiRun — прогон сценария и замечание к блоку одним хуком.
 *
 * Один хук на два задания (`kadai_run` и `kadai_rework`), потому что снаружи
 * они различаются только телом: обоим нужны пресет модели, поток событий
 * `stage` и один и тот же список того, что после них перечитывается. Два хука
 * рядом разошлись бы на первом же новом ключе кэша.
 *
 *     Почему ход стадий берётся из потока, а не из снимка
 *     ---------------------------------------------------
 *
 * Снимок (`GET …/kadai`) знает состояние всех семи стадий, но устаревает,
 * как только прогон пошёл дальше. Опрашивать его раз в секунду значило бы
 * гнать запрос ради того, что уже приехало событием. Поэтому события копятся
 * здесь, а снимок перечитывается один раз — на конце задания.
 *
 * **Разбор потока — чистая свёртка по кадрам, а не накопление в `ref`.** Поток
 * переподключается с последнего события (`Last-Event-ID`), после чего кадры
 * приезжают те же самые; накопитель, переживший переподключение, показал бы
 * стадию дважды, а свёртка по полному списку кадров даёт один и тот же ответ
 * сколько угодно раз.
 *
 * **Тоста на упавшее задание здесь нет.** Провал тостит оболочка
 * (`useUserEvents`) по коду из уведомления. Беда
 * остаётся на экране строкой: тост уходит через шесть секунд, а человек
 * смотрит именно сюда.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'

import { ApiError, errorText, keys } from '@/api'
import { useJobStream } from '@/api/hooks'
import { useEnqueueJob } from '@/features/projects/data'

import type { ReworkKind, StageEvent, Wishes } from './stages'
import { reworkPayload, runPayload } from './stages'
import { EV_STAGE, KADAI_REWORK, KADAI_RUN } from './types'

export type KadaiRunState = {
  /** Идёт ли прогон прямо сейчас. Поле замечания на это время заблокировано. */
  running: boolean
  /** Вид идущего задания: `kadai_run` | `kadai_rework` | `null`. */
  kind: string | null
  /** События `stage`, пришедшие по потоку этого прогона. */
  stageEvents: StageEvent[]
  /** Строка «что делает сейчас»: заметка последнего события стадии. */
  note: string
  /** Беда прогона или отказ постановки — уже по-русски. */
  error: string | null
  /** Запустить сценарий: до какой стадии и с какими пожеланиями. */
  start: (opts: { until: string | null; stages: string[]; wishes: Wishes; first: boolean }) => void
  /** Замечание к блоку. */
  rework: (opts: { block: string; kind: ReworkKind; note: string }) => void
}

/**
 * `runId` — решение, которое считают. Оно уезжает в `payload.run_id`: работа
 * держит несколько решений, у каждого свой ход стадий и свой список блоков, и
 * задание без этого поля посчитало бы соседнюю задачу. Пусто — работа целиком,
 * какой её видели, пока решение в ней было одно.
 */
export function useKadaiRun(projectId: string, endpoint: string | null, runId = ''): KadaiRunState {
  const qc = useQueryClient()
  const enqueue = useEnqueueJob()

  const [running, setRunning] = useState<{ id: string; kind: string } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const stream = useJobStream(running?.id)
  // Чтобы не показать конец одного задания дважды: поток закрывается, карточка
  // перечитывается, и `done` становится истиной не один раз.
  const закрыто = useRef<string | null>(null)

  const stageEvents = useMemo(() => {
    const события: StageEvent[] = []
    for (const кадр of stream.events) {
      if (кадр.kind !== EV_STAGE) continue
      события.push((кадр.data ?? {}) as StageEvent)
    }
    return события
  }, [stream.events])

  const идёт = !!running && !stream.done

  useEffect(() => {
    if (!running || !stream.done || закрыто.current === running.id) return
    закрыто.current = running.id
    // Перечитывается всё, что могло измениться прогоном: ход работы, блоки, их
    // версии, остаток месяца. Карточка проекта — из-за размера на томе.
    void qc.invalidateQueries({ queryKey: keys.kadai.status(projectId, runId) })
    void qc.invalidateQueries({ queryKey: keys.kadai.blocks(projectId, runId) })
    void qc.invalidateQueries({ queryKey: keys.kadai.blockVersions(projectId, runId) })
    // Карточка решения в списке показывает стадию: после прогона она другая.
    void qc.invalidateQueries({ queryKey: keys.kadai.runs(projectId) })
    void qc.invalidateQueries({ queryKey: keys.projects.one(projectId) })
    void qc.invalidateQueries({ queryKey: keys.usage })
    if (stream.job?.status !== 'done') {
      const беда = (stream.job?.error ?? {}) as { code?: string; message?: string }
      setError(errorText(new ApiError(беда.code || 'unknown', беда.message || '')))
    }
    setRunning(null)
  }, [running, stream.done, stream.job, projectId, runId, qc])

  const поставить = useCallback(
    (kind: string, payload: Record<string, unknown>) => {
      setError(null)
      enqueue.mutate(
        { kind, projectId, payload },
        {
          onSuccess: (задание) => {
            закрыто.current = null
            setRunning({ id: задание.id, kind })
          },
          onError: (беда) => setError(errorText(беда)),
        },
      )
    },
    [enqueue, projectId],
  )

  const start = useCallback(
    ({
      until,
      stages,
      wishes,
      first,
    }: {
      until: string | null
      stages: string[]
      wishes: Wishes
      first: boolean
    }) => {
      if (!endpoint) return
      поставить(KADAI_RUN, {
        ...runPayload({ endpoint, until, stages, wishes, first }),
        ...(runId ? { run_id: runId } : {}),
      })
    },
    [endpoint, runId, поставить],
  )

  const rework = useCallback(
    ({ block, kind, note }: { block: string; kind: ReworkKind; note: string }) => {
      if (!endpoint || !note.trim()) return
      поставить(KADAI_REWORK, {
        ...reworkPayload({ endpoint, block, kind, note }),
        ...(runId ? { run_id: runId } : {}),
      })
    },
    [endpoint, runId, поставить],
  )

  const последнее = stageEvents.length > 0 ? stageEvents[stageEvents.length - 1] : null
  return {
    running: идёт,
    kind: идёт ? (running?.kind ?? null) : null,
    stageEvents,
    note: typeof последнее?.note === 'string' ? последнее.note : '',
    error,
    start,
    rework,
  }
}
