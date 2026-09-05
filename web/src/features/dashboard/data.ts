/**
 * data — запросы, которые нужны только дашборду.
 *
 * Пока их один: сколько заданий считается прямо сейчас. Служба фильтрует по
 * одному состоянию за запрос (`GET /api/jobs?status=…`), поэтому запросов два,
 * а число — их сумма: «в работе» без «в очереди» — половина правды.
 *
 * Опроса по таймеру нет: ключ `jobs` сбрасывает поток человека
 * (`useUserEvents` в оболочке) на каждом событии, и это точнее любого
 * интервала.
 */
import { useQuery, type UseQueryResult } from '@tanstack/react-query'

import { api, keys, unwrap } from '@/api'

type JobsPage = { jobs: { id: string; kind: string; status: string }[] }

/** Сколько заданий человека сейчас в очереди и в работе. */
export function useQueueSize(): UseQueryResult<number> {
  return useQuery({
    queryKey: [...keys.jobs.list('active'), 'count'],
    queryFn: async () => {
      const [running, queued] = await Promise.all([
        unwrap<JobsPage>(
          api.GET('/api/jobs', { params: { query: { status: 'running', limit: 100 } } }),
        ),
        unwrap<JobsPage>(
          api.GET('/api/jobs', { params: { query: { status: 'queued', limit: 100 } } }),
        ),
      ])
      return (running.jobs?.length ?? 0) + (queued.jobs?.length ?? 0)
    },
    staleTime: 10_000,
  })
}
