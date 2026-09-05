/**
 * useNotifications — колокольчик.
 *
 * Правило: тост показывается только на завершение фоновой задачи и на
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

/**
 * Сколько записей показывает колокольчик — и, значит, сколько их кладёт в себя
 * сводка первого экрана (`useBootstrap`). Число одно на оба места намеренно:
 * длина списка — часть ключа кэша, и разойдясь, они дали бы второй запрос за
 * тем же самым списком сразу после загрузки.
 */
export const СКОЛЬКО_В_КОЛОКОЛЬЧИКЕ = 20

export function useNotifications(
  limit = СКОЛЬКО_В_КОЛОКОЛЬЧИКЕ,
): UseQueryResult<NotificationsPage> {
  return useQuery({
    queryKey: [...keys.notifications, limit],
    queryFn: () =>
      unwrap<NotificationsPage>(api.GET('/api/notifications', { params: { query: { limit } } })),
    // Список приезжает потоком человека: `useUserEvents` гасит этот ключ, как
    // только служба что-то прислала. Поэтому свежесть здесь долгая — короткая
    // означала бы перезапрос на каждом переходе между экранами ради того, что
    // и так уже пришло.
    staleTime: 5 * 60_000,
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

/**
 * Убрать одно уведомление насовсем.
 *
 * Колокольчик — не архив: прочитанная строка о задании недельной давности
 * человеку мешает. За строкой не уходит ничего, кроме неё самой, — ни задание,
 * ни собранный им файл.
 */
export function useDeleteNotification() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) =>
      unwrap(
        api.DELETE('/api/notifications/{notification_id}', {
          params: { path: { notification_id: id } },
        }),
      ),
    onSuccess: () => void qc.invalidateQueries({ queryKey: keys.notifications }),
  })
}
