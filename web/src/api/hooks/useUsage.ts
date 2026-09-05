/**
 * useUsage — остаток месяца и цены видов заданий.
 *
 * Решение владельца: «остаток месяца и цена задания показываются ДО нажатия».
 * Поэтому цена приезжает тем же ответом, что и остаток (`prices`), и экранам не
 * приходится складывать два запроса, которые могут разойтись.
 *
 * Ключ сбрасывается после каждого поставленного задания — цифра «осталось»,
 * не меняющаяся после запуска, читается как поломка.
 */
import { useQuery, type UseQueryResult } from '@tanstack/react-query'

import { api, unwrap } from '../client'
import { keys } from '../queryKeys'
import type { Usage } from '../types'

export function useUsage(): UseQueryResult<Usage> {
  return useQuery({
    queryKey: keys.usage,
    queryFn: () => unwrap<Usage>(api.GET('/api/usage')),
    staleTime: 30_000,
  })
}
