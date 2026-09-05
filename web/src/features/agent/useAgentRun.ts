/**
 * useAgentRun — один прогон агента от постановки до итога.
 *
 * Отдельно от компонента, потому что это состояние переживает закрытие панели:
 * панель монтирована всегда (`AgentPanel` рисует пустоту, пока закрыта), и
 * прогон, начатый и спрятанный, продолжает идти, а поток — приходить. Если бы
 * состояние жило в разметке панели, «закрыл окно — работа продолжается» из
 * макета работало бы только на словах.
 *
 * Что здесь есть и чего нет:
 *
 * * **тоста на провал задания нет.** Его показывает оболочка (`useUserEvents`)
 *   по коду из уведомления, и второй был бы дублем — решение сведения ночи 1.
 *   Свой тост остаётся только на отказ постановки (обычный запрос, не задание);
 * * **после конца прогона запросы проекта сбрасываются** — теги, значения,
 *   версии и схемы. Экран под панелью не перезагружают руками: агент менял
 *   именно то, на что человек смотрит.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'

import { errorText, keys } from '@/api'
import { useJobStream, type Job } from '@/api/hooks'
import { useT } from '@/i18n'
import { useToast } from '@/ui'
import { useEnqueueJob } from '@/features/projects/data'

import { useCancelJob } from './data'
import { buildAgentPayload, changedKeys, readAgentStream, type AgentMove } from './stream'
import { AGENT, type AgentJobResult } from './types'

export type AgentRunState = {
  /** Задание, которое панель показывает сейчас (идущее или последнее). */
  job: Job | undefined
  /** Идёт ли прогон прямо сейчас. */
  running: boolean
  /** Постановка задания в пути. */
  starting: boolean
  /** Ходы: по одному на поставленный тег. */
  moves: AgentMove[]
  /** Текст ответа модели по мере прихода. */
  text: string
  step: number
  total: number
  /** Месячный остаток кончился до первого вызова модели. */
  limitExhausted: boolean
  /** Итог задания, когда он есть. */
  result: AgentJobResult | null
  /** Какие теги изменились. */
  changed: string[]
  /** Задача последнего прогона — её повторяет «перегенерировать». */
  lastTask: string
  /** Отказ постановки задания (лимит, нет ключа) — показывается в панели. */
  startError: unknown
  start: (task: string) => void
  regenerate: () => void
  cancel: () => void
}

export function useAgentRun(
  projectId: string | null,
  endpoint: string | null,
  overwrite: boolean,
): AgentRunState {
  const t = useT()
  const toast = useToast()
  const qc = useQueryClient()
  const enqueue = useEnqueueJob()
  const cancelJob = useCancelJob()

  const [jobId, setJobId] = useState<string | null>(null)
  const [lastTask, setLastTask] = useState('')
  const stream = useJobStream(jobId)
  // Чтобы не сбросить кэш проекта дважды: поток закрывается, карточка
  // перечитывается, и `done` становится истиной не один раз.
  const закрыто = useRef<string | null>(null)

  const разбор = useMemo(() => readAgentStream(stream.events), [stream.events])
  const result = (stream.job?.result ?? null) as AgentJobResult | null
  const running = !!jobId && !stream.done

  useEffect(() => {
    if (!jobId || !stream.done || закрыто.current === jobId || !projectId) return
    закрыто.current = jobId
    // Один сброс на весь проект: теги, значения и версии лежат под ключом
    // `projects.one` (`api/queryKeys.ts`), схемы — своим ключом области D.
    void qc.invalidateQueries({ queryKey: keys.projects.one(projectId) })
    void qc.invalidateQueries({ queryKey: keys.diagrams.values(projectId) })
  }, [jobId, stream.done, projectId, qc])

  const поставить = useCallback(
    (task: string) => {
      if (!projectId || !endpoint) return
      const текст = task.trim()
      if (!текст) return
      enqueue.mutate(
        {
          kind: AGENT,
          projectId,
          payload: buildAgentPayload({ endpoint, task: текст, overwrite }),
        },
        {
          onSuccess: (задание) => {
            закрыто.current = null
            setLastTask(текст)
            setJobId(задание.id)
          },
          onError: (беда) => toast.error(t('agent.toast.startFailed'), errorText(беда)),
        },
      )
    },
    [enqueue, endpoint, overwrite, projectId, toast, t],
  )

  const regenerate = useCallback(() => поставить(lastTask), [поставить, lastTask])

  const cancel = useCallback(() => {
    if (!jobId) return
    cancelJob.mutate(jobId, {
      onError: (беда) => toast.error(t('agent.toast.cancelFailed'), errorText(беда)),
    })
  }, [cancelJob, jobId, toast, t])

  return {
    job: stream.job,
    running,
    starting: enqueue.isPending,
    moves: разбор.moves,
    text: разбор.text,
    step: разбор.step,
    total: разбор.total,
    limitExhausted: разбор.limitExhausted,
    result,
    changed: changedKeys(result, разбор.moves),
    lastTask,
    startError: enqueue.error,
    start: поставить,
    regenerate,
    cancel,
  }
}
