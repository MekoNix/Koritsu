/**
 * useModules — список модулей для сайдбара.
 *
 * Служба отдаёт только готовые (`packages/api/modules`), неготовых в ответе нет
 * вовсе — и это ровно то поведение, которого требует бриф: «модули в планах в
 * интерфейсе не отображаются вообще». Поэтому здесь нет ни фильтра, ни флага
 * `ready`: отфильтровать второй раз значило бы завести второе место, где
 * принимается решение «показывать или нет».
 */
import { useQuery, type UseQueryResult } from '@tanstack/react-query'

import { api, unwrap } from '../client'
import { keys } from '../queryKeys'
import type { ModuleInfo } from '../types'

export function useModules(): UseQueryResult<ModuleInfo[]> {
  return useQuery({
    queryKey: keys.modules,
    queryFn: () => unwrap<ModuleInfo[]>(api.GET('/api/modules')),
    // Реестр модулей меняется выкатом службы, а не действиями человека.
    staleTime: 10 * 60_000,
  })
}
