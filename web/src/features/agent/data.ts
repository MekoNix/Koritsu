/**
 * data — запросы панели агента.
 *
 * Постановка задания берётся у проектов (`useEnqueueJob`), пресеты модели — у
 * отчётов (`useProviders`, `defaultProvider`): второй такой же хук рядом с
 * первым — это два кэша одного ответа, которые расходятся после первой же
 * правки ключа в настройках.
 *
 * Своего здесь два: история прогонов агента по проекту и отмена задания.
 */
import { useMutation, useQuery, useQueryClient, type UseQueryResult } from '@tanstack/react-query'

import { api, keys, unwrap } from '@/api'
import type { Job } from '@/api/hooks'

import { AGENT } from './types'

/** Сколько прошлых прогонов показывает панель. */
const ИСТОРИЯ = 5

/**
 * История прогонов агента по проекту.
 *
 * Фильтра по виду задания у службы нет — `GET /api/jobs` умеет `project_id` и
 * `status` (`packages/api/jobs/routes.py`), — поэтому вид отбирается здесь.
 * Заводить ради этого добавочный параметр службе было бы правкой ради одного
 * читателя: заданий у человека в проекте десятки, а не тысячи, и разбор списка
 * стоит дешевле нового поля в договоре.
 */
export function useAgentRuns(projectId: string | undefined): UseQueryResult<Job[]> {
  return useQuery({
    queryKey: keys.jobs.ofProject(projectId ?? ''),
    enabled: !!projectId,
    queryFn: async () => {
      const body = await unwrap<{ jobs: Job[] }>(
        api.GET('/api/jobs', { params: { query: { project_id: projectId as string } } }),
      )
      return body.jobs.filter((job) => job.kind === AGENT).slice(0, ИСТОРИЯ)
    },
  })
}

/**
 * Попросить задание остановиться.
 *
 * «Попросить», а не «остановить»: ждущее задание служба снимает сразу, а
 * идущее останавливается между ходами — и всё, что успело сохраниться,
 * сохранено. Поэтому после отмены теги проекта
 * перечитываются так же, как после удачного конца.
 */
export function useCancelJob() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (jobId: string) =>
      unwrap<Job>(api.POST('/api/jobs/{job_id}/cancel', { params: { path: { job_id: jobId } } })),
    onSuccess: (job) => {
      void qc.invalidateQueries({ queryKey: keys.jobs.all })
      void qc.invalidateQueries({ queryKey: keys.jobs.one(job.id) })
    },
  })
}
