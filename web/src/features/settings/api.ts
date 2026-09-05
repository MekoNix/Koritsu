/**
 * api — запросы настроек аккаунта: ключи моделей, ключи для скриптов, выход
 * отовсюду.
 *
 * Правило одно на все изменения: после удачи сбрасывается тот ключ кэша,
 * который эту правку показывает, и только он. Сброс «всего» после каждой
 * мелочи выглядит безобидно ровно до того дня, когда на экране висит поток
 * задания и его перезапрашивают вместе со списком ключей.
 */
import { useMutation, useQuery, useQueryClient, type UseQueryResult } from '@tanstack/react-query'

import { api, keys as cacheKeys, unwrap } from '@/api'

import type { ApiToken, ApiTokenCreated, KeyProviders, ModelKey } from './types'

// ── ключи моделей ────────────────────────────────────────────────────────────

export function useModelKeys(): UseQueryResult<ModelKey[]> {
  return useQuery({
    queryKey: cacheKeys.modelKeys,
    queryFn: () => unwrap<ModelKey[]>(api.GET('/api/keys')),
  })
}

/**
 * Поставщики, для которых ключ вообще имеет смысл, и чем за каждого платят
 * (`key_source`, если служба его уже отдаёт).
 *
 * Возвращается целиком, а не одним полем `providers`: `key_source` приезжает
 * тем же ответом, и раскладывать один ответ по двум запросам значило бы дать
 * им разойтись.
 *
 * Ключ сбрасывается вместе со списком своих ключей: завёл ключ — `key_source`
 * для этого поставщика стал другим.
 */
export function useKeyProviders(): UseQueryResult<KeyProviders> {
  return useQuery({
    queryKey: cacheKeys.keyProviders,
    queryFn: () => unwrap<KeyProviders>(api.GET('/api/keys/providers')),
    staleTime: 10 * 60_000,
  })
}

export function useAddModelKey() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { provider: string; key: string }) =>
      unwrap<ModelKey>(api.POST('/api/keys', { body })),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: cacheKeys.modelKeys })
      void qc.invalidateQueries({ queryKey: cacheKeys.keyProviders })
    },
  })
}

export function useRevokeModelKey() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (keyId: string) =>
      unwrap(api.DELETE('/api/keys/{key_id}', { params: { path: { key_id: keyId } } })),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: cacheKeys.modelKeys })
      void qc.invalidateQueries({ queryKey: cacheKeys.keyProviders })
    },
  })
}

// ── ключи для скриптов ───────────────────────────────────────────────────────

export function useApiTokens(): UseQueryResult<ApiToken[]> {
  return useQuery({
    queryKey: cacheKeys.apiTokens,
    queryFn: () => unwrap<ApiToken[]>(api.GET('/api/tokens')),
  })
}

/**
 * Завести ключ. Ответ несёт строку ключа — единственный раз за его жизнь, — и
 * дальше её держит у себя экран: в кэш она не кладётся намеренно, иначе
 * «показывается один раз» превратилось бы в «лежит в памяти вкладки до
 * перезагрузки».
 */
export function useCreateApiToken() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { name: string; scopes: string[] }) =>
      unwrap<ApiTokenCreated>(api.POST('/api/tokens', { body })),
    onSuccess: () => qc.invalidateQueries({ queryKey: cacheKeys.apiTokens }),
  })
}

export function useRevokeApiToken() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (tokenId: string) =>
      unwrap<ApiToken>(
        api.DELETE('/api/tokens/{token_id}', { params: { path: { token_id: tokenId } } }),
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: cacheKeys.apiTokens }),
  })
}

// ── безопасность ─────────────────────────────────────────────────────────────

/**
 * Выйти на всех устройствах. Кэш чистится целиком, как и при обычном выходе:
 * в нём лежат проекты, материалы и уведомления вошедшего, и оставлять их
 * следующему нельзя.
 */
export function useLogoutEverywhere() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => unwrap(api.POST('/api/auth/logout-all')),
    onSettled: () => qc.clear(),
  })
}
