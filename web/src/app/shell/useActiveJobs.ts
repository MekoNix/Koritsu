/**
 * useActiveJobs — что считается прямо сейчас: очередь плюс работа.
 *
 * Один запрос на всё приложение, а не по одному на каждого, кому нужны
 * активные задания. Раньше их спрашивали двое — меню в шапке и статистика на
 * дашборде, — и каждый своим ключом кэша: открытая страница означала четыре
 * ответа службы вместо двух, причём с одинаковым содержимым. Ключ здесь один
 * (`keys.jobs.list('active')`), а кому что из списка нужно, решает `select`.
 *
 * Служба фильтрует по одному состоянию за запрос, поэтому запросов внутри всё
 * же два, а список — их склейка: «в работе» без «в очереди» — половина правды.
 *
 * Опроса по таймеру нет и быть не должно: ключ `jobs` гасит поток человека
 * (`useUserEvents`) на каждом событии, и это точнее любого интервала.
 */
import { useQuery, type UseQueryResult } from '@tanstack/react-query'

import { api, unwrap } from '@/api'
import { keys } from '@/api/queryKeys'

export type JobCard = { id: string; kind: string; status: string; created_at: string }

/** Сколько активных заданий показывать. Больше — уже журнал, а его здесь нет. */
const СКОЛЬКО = 20

async function активные(): Promise<JobCard[]> {
  const [running, queued] = await Promise.all([
    unwrap<{ jobs: JobCard[] }>(
      api.GET('/api/jobs', { params: { query: { status: 'running', limit: СКОЛЬКО } } }),
    ),
    unwrap<{ jobs: JobCard[] }>(
      api.GET('/api/jobs', { params: { query: { status: 'queued', limit: СКОЛЬКО } } }),
    ),
  ])
  return [...running.jobs, ...queued.jobs]
}

export function useActiveJobs<T = JobCard[]>(select?: (jobs: JobCard[]) => T): UseQueryResult<T> {
  return useQuery({
    queryKey: keys.jobs.list('active'),
    queryFn: активные,
    ...(select ? { select } : {}),
    staleTime: 10_000,
  }) as UseQueryResult<T>
}
