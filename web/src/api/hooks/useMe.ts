/**
 * useMe — кто вошёл. Основа защищённых маршрутов.
 *
 * Отсутствие сессии здесь **не беда**: `401 unauthenticated` превращается в
 * `null`, потому что «не вошёл» — обычное состояние первой страницы, а не
 * ошибка, которую надо показывать красным. Всё остальное бросается как есть.
 */
import { useMutation, useQuery, useQueryClient, type UseQueryResult } from '@tanstack/react-query'

import { api, unwrap } from '../client'
import { isApiError } from '../errors'
import { keys } from '../queryKeys'
import type { Me } from '../types'

/**
 * Служба отвечает `{"user": {…}}`, а не профилем в корне тела
 * (`accounts/routes.py: whoami`). Обёртка снимается здесь, один раз: иначе
 * `me.data.email` было бы `undefined` в каждом экране, который её не снял, —
 * и молча, потому что тип ответа в OpenAPI объявлен как «объект».
 */
export async function fetchMe(): Promise<Me | null> {
  try {
    const body = await unwrap<{ user?: Me }>(api.GET('/api/auth/me'))
    return body?.user ?? null
  } catch (e) {
    if (isApiError(e) && e.status === 401) return null
    throw e
  }
}

export function useMe(): UseQueryResult<Me | null> {
  return useQuery({
    queryKey: keys.me,
    queryFn: fetchMe,
    // Профиль спрашивают все экраны сразу; полминуты свежести снимают
    // десяток одинаковых запросов при переходах, а вход и выход и так
    // сбрасывают ключ руками.
    staleTime: 30_000,
    retry: false,
  })
}

/** Выход. Гасит сессию на службе и весь кэш — чужих данных в нём остаться не должно. */
export function useLogout() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => unwrap(api.POST('/api/auth/logout')),
    onSettled: () => {
      // Именно `clear`, а не сброс ключа `me`: в кэше лежат проекты, материалы
      // и уведомления вошедшего, и оставить их следующему — утечка.
      qc.clear()
    },
  })
}
