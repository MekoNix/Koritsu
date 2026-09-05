/**
 * api — запросы админки.
 *
 * **Список людей берётся целиком.** Служба отдаёт `GET /api/admin/users` одним
 * куском (`limit` до 1000) и не умеет ни поиска, ни страниц, ни сортировки —
 * см. `packages/api/admin/routes.py`. Поэтому и поиск, и страницы считает
 * сайт (`filter.ts`), а не притворяется, что ходит за ними на службу: запрос
 * `?search=` служба молча проигнорировала бы, и человек получил бы полный
 * список под видом найденного.
 *
 * **Очередь перезапрашивается сама.** Это страница «жива ли машина», и
 * цифра, застывшая на месте, читается как поломка. Пять секунд — компромисс:
 * чаще незачем, реже уже не «сейчас».
 */
import { useMutation, useQuery, useQueryClient, type UseQueryResult } from '@tanstack/react-query'

import { api, keys as cacheKeys, unwrap } from '@/api'

import type {
  AdminQueue,
  AdminUser,
  AdminUsersPage,
  SecurityEvent,
  SecurityEventsPage,
  UserPatch,
} from './types'

/** Сколько людей просить у службы за раз. Потолок маршрута — 1000. */
export const USERS_LIMIT = 1000

/** Как часто перезапрашивается очередь, мс. */
export const QUEUE_REFETCH_MS = 5000

/** Сколько событий безопасности показывать. Потолок маршрута — 1000. */
export const EVENTS_LIMIT = 200

export function useAdminUsers(limit = USERS_LIMIT): UseQueryResult<AdminUser[]> {
  return useQuery({
    queryKey: cacheKeys.admin.users(limit),
    queryFn: async () =>
      (await unwrap<AdminUsersPage>(api.GET('/api/admin/users', { params: { query: { limit } } })))
        .users,
  })
}

export function usePatchAdminUser() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ userId, patch }: { userId: string; patch: UserPatch }) =>
      unwrap<AdminUser>(
        api.PATCH('/api/admin/users/{user_id}', {
          params: { path: { user_id: userId } },
          body: patch,
        }),
      ),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: cacheKeys.admin.all })
      // Себе же можно снять право админа — тогда `/admin` обязан закрыться
      // сразу, а не после перезагрузки страницы.
      void qc.invalidateQueries({ queryKey: cacheKeys.me })
    },
  })
}

export function useAdminQueue(): UseQueryResult<AdminQueue> {
  return useQuery({
    queryKey: cacheKeys.admin.queue,
    queryFn: () => unwrap<AdminQueue>(api.GET('/api/admin/queue')),
    refetchInterval: QUEUE_REFETCH_MS,
  })
}

export function useSecurityEvents(
  kind: string | null,
  limit = EVENTS_LIMIT,
): UseQueryResult<SecurityEvent[]> {
  return useQuery({
    queryKey: cacheKeys.admin.security(kind, limit),
    queryFn: async () =>
      (
        await unwrap<SecurityEventsPage>(
          api.GET('/api/admin/security', {
            params: { query: kind ? { kind, limit } : { limit } },
          }),
        )
      ).events,
  })
}
