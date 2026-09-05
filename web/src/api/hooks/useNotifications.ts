/**
 * useNotifications — колокольчик.
 *
 * Решение владельца: тост показывается только на завершение фоновой задачи и на
 * ошибку, всё остальное живёт в колокольчике. Поэтому здесь два разных
 * источника одного и того же списка:
 *
 * * `useNotifications()` — обычный запрос, из него берётся число непрочитанных;
 * * `useUserEvents()` (`hooks/useUserEvents.ts`) — поток, который сбрасывает
 *   этот ключ, как только служба что-то прислала. Опроса по таймеру нет: он
 *   означал бы задержку в полминуты на то, что уже пришло потоком.
 */
import { useMutation, useQuery, useQueryClient, type UseQueryResult } from '@tanstack/react-query'

import { api, unwrap } from '../client'
import { keys } from '../queryKeys'
import type { NotificationsPage } from '../types'

export function useNotifications(limit = 50): UseQueryResult<NotificationsPage> {
  return useQuery({
    queryKey: [...keys.notifications, limit],
    queryFn: () =>
      unwrap<NotificationsPage>(api.GET('/api/notifications', { params: { query: { limit } } })),
    staleTime: 15_000,
  })
}

/** Пометить одно прочитанным. */
export function useMarkNotificationRead() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) =>
      unwrap(
        api.POST('/api/notifications/{notification_id}/read', {
          params: { path: { notification_id: id } },
        }),
      ),
    onSuccess: () => void qc.invalidateQueries({ queryKey: keys.notifications }),
  })
}

/** Пометить прочитанным всё. */
export function useMarkAllNotificationsRead() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => unwrap(api.POST('/api/notifications/read-all')),
    onSuccess: () => void qc.invalidateQueries({ queryKey: keys.notifications }),
  })
}
