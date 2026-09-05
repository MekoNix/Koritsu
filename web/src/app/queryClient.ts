/**
 * queryClient — общие правила кэша для всех запросов.
 *
 * Умолчания подобраны под службу, а не взяты из документации:
 *
 * * `retry` не повторяет отказы 4xx. Повторять «нет прав» или «не найдено»
 *   бессмысленно, а «слишком часто» (429) повтор только усугубляет. Сеть и
 *   пятисотые повторяются дважды.
 * * `refetchOnWindowFocus: false` — фоновые задания и так шлют события потоком
 *   (`useUserEvents`), и перезапрос всего при каждом переключении вкладки
 *   означал бы шквал запросов у человека с двумя мониторами.
 * * `staleTime` по умолчанию нулевой; каждый хук назначает свой осознанно.
 */
import { QueryClient } from '@tanstack/react-query'

import { isApiError } from '@/api/errors'

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        refetchOnWindowFocus: false,
        retry: (attempt, error) => {
          if (isApiError(error) && error.status >= 400 && error.status < 500) return false
          return attempt < 2
        },
      },
      mutations: {
        // Изменяющий запрос не повторяется никогда: повтор «создать проект»
        // после неясного отказа создаёт два проекта.
        retry: false,
      },
    },
  })
}
