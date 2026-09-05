/**
 * useBuild — сборка DOCX и PDF заданием `build` и адреса готовых файлов.
 *
 * Собирается всегда пара `docx` + `pdf`, а не то, что просят кнопкой: PDF
 * получается из DOCX тем же прогоном LibreOffice, и вторая сборка ради второго
 * файла — это второй запуск чужой программы и вторая цена задания за один и тот
 * же документ. Поэтому «показать превью» и «скачать Word» — одна работа с двумя
 * исходами.
 *
 * Артефакты приезжают дважды: событиями `artifact` по ходу (`build.py`) и в
 * `job.result.artifacts` на конце. Берём из результата, а события используем
 * только чтобы показать превью, как только PDF готов, не дожидаясь закрытия
 * задания.
 *
 * Модель здесь не участвует (`needs_secret=False`), поэтому пресета сборка не
 * спрашивает и без ключей работает.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'

import { ApiError, errorText, keys } from '@/api'
import { useJobStream } from '@/api/hooks'
import { useT } from '@/i18n'
import { useToast } from '@/ui'
import { artifactUrl, useEnqueueJob } from '@/features/projects/data'

import { BUILD, EV_ARTIFACT, type BuildResult } from './types'

export type BuiltArtifacts = { docx?: string; pdf?: string }

export type BuildState = {
  /** Идёт ли сборка. */
  running: boolean
  /** Что собрано в этот раз: идентификаторы артефактов. */
  artifacts: BuiltArtifacts
  /** Адрес PDF для ссылки «скачать»; `null` — собирать ещё нечего. */
  pdfUrl: string | null
  /** Тот же PDF, но с `?inline=1` — адрес для `<embed>` (см. `PdfPreview`). */
  pdfInlineUrl: string | null
  docxUrl: string | null
  /** Беда сборки — уже по-русски. */
  error: string | null
  /** Замечания сборки: незаполненные теги и жалобы шаблона. */
  unfilled: string[]
  start: () => void
}

export function useBuild(projectId: string): BuildState {
  const t = useT()
  const toast = useToast()
  const qc = useQueryClient()
  const enqueue = useEnqueueJob()

  const [jobId, setJobId] = useState<string | null>(null)
  const [artifacts, setArtifacts] = useState<BuiltArtifacts>({})
  const [error, setError] = useState<string | null>(null)
  const [unfilled, setUnfilled] = useState<string[]>([])
  const stream = useJobStream(jobId)
  const закрыто = useRef<string | null>(null)

  // Артефакт из потока: PDF показывается, как только он есть, а не когда
  // задание закроется, — между этими двумя моментами секунды ожидания зря.
  const из_потока = useMemo(() => {
    const найдено: BuiltArtifacts = {}
    for (const событие of stream.events) {
      if (событие.kind !== EV_ARTIFACT) continue
      const тело = (событие.data ?? {}) as { output?: unknown; artifact?: unknown }
      if (typeof тело.output === 'string' && typeof тело.artifact === 'string') {
        if (тело.output === 'pdf' || тело.output === 'docx') найдено[тело.output] = тело.artifact
      }
    }
    return найдено
  }, [stream.events])

  useEffect(() => {
    if (!jobId || !stream.done || закрыто.current === jobId) return
    закрыто.current = jobId
    void qc.invalidateQueries({ queryKey: keys.usage })
    const статус = stream.job?.status
    if (статус === 'done') {
      const итог = (stream.job?.result ?? {}) as BuildResult
      setArtifacts({ ...из_потока, ...(итог.artifacts as BuiltArtifacts | undefined) })
      setUnfilled(итог.unfilled ?? [])
      setError(null)
    } else {
      // Тоста здесь нет: провал задания тостит оболочка (`useUserEvents`) по
      // коду из уведомления. Беда всё равно остаётся
      // на экране, в самой колонке превью: тост уходит через шесть секунд, а
      // человек смотрит именно сюда.
      const беда = (stream.job?.error ?? {}) as { code?: string; message?: string }
      setError(errorText(new ApiError(беда.code || 'unknown', беда.message || '')))
    }
    setJobId(null)
  }, [jobId, stream.done, stream.job, из_потока, qc])

  const start = useCallback(() => {
    setError(null)
    setUnfilled([])
    enqueue.mutate(
      { kind: BUILD, projectId, payload: { outputs: ['docx', 'pdf'] } },
      {
        onSuccess: (задание) => {
          закрыто.current = null
          setArtifacts({})
          setJobId(задание.id)
        },
        onError: (беда) => {
          setError(errorText(беда))
          toast.error(t('reports.toast.buildFailed'), errorText(беда))
        },
      },
    )
  }, [enqueue, projectId, toast, t])

  const готово: BuiltArtifacts = { ...из_потока, ...artifacts }
  return {
    running: !!jobId && !stream.done,
    artifacts: готово,
    pdfUrl: готово.pdf ? artifactUrl(projectId, готово.pdf) : null,
    pdfInlineUrl: готово.pdf ? artifactUrl(projectId, готово.pdf, { inline: true }) : null,
    docxUrl: готово.docx ? artifactUrl(projectId, готово.docx) : null,
    error,
    unfilled,
    start,
  }
}
