/**
 * data — все запросы области «Пространство» одним файлом.
 *
 * То же правило, что в области «Проекты»: адрес маршрута, форма ответа и то,
 * какие ключи кэша гасятся после изменения, — одно знание, и живёт оно в одном
 * месте. Иначе «сменил роль, а список показывает прежнюю» чинится в трёх
 * компонентах по очереди.
 *
 * Что гасится после правки участников: список участников этого пространства и
 * его карточка (`['workspaces', id]`). Список проектов — нет: состав людей на
 * состав работ не влияет.
 */
import { useMutation, useQuery, useQueryClient, type UseQueryResult } from '@tanstack/react-query'

import { api, keys, unwrap } from '@/api'
import type { Workspace } from '@/api/hooks'

import type { Member, MemberChanged } from './types'

/** Пространства человека. `trash=true` — те, что лежат в корзине. */
export function useWorkspaces(trash = false): UseQueryResult<Workspace[]> {
  return useQuery({
    queryKey: keys.workspaces.list(trash),
    queryFn: async () => {
      const тело = await unwrap<{ workspaces: Workspace[] }>(
        api.GET('/api/workspaces', { params: { query: { trash } } }),
      )
      return тело.workspaces
    },
    staleTime: 60_000,
  })
}

/** Одно пространство: имя и роль спрашивающего. */
export function useWorkspaceCard(id: string | undefined): UseQueryResult<Workspace> {
  return useQuery({
    queryKey: [...keys.workspaces.all, id ?? ''],
    enabled: !!id,
    queryFn: () =>
      unwrap<Workspace>(
        api.GET('/api/workspaces/{workspace_id}', {
          params: { path: { workspace_id: id as string } },
        }),
      ),
    staleTime: 5 * 60_000,
  })
}

/** Участники. Читает любой участник, меняет только владелец. */
export function useMembers(id: string | undefined): UseQueryResult<Member[]> {
  return useQuery({
    queryKey: keys.workspaces.members(id ?? ''),
    enabled: !!id,
    queryFn: async () => {
      const тело = await unwrap<{ members: Member[] }>(
        api.GET('/api/workspaces/{workspace_id}/members', {
          params: { path: { workspace_id: id as string } },
        }),
      )
      return тело.members
    },
  })
}

/**
 * Общий сброс: и список пространств, и карточка, и участники.
 *
 * Имя латиницей и с приставки `use` — этого требует правило хуков в ESLint:
 * оно узнаёт хук по имени, и `useСброс` для него просто функция, из которой
 * нельзя звать `useQueryClient`.
 */
function useInvalidateWorkspaces() {
  const qc = useQueryClient()
  return () => void qc.invalidateQueries({ queryKey: keys.workspaces.all })
}

export function useCreateWorkspace() {
  const сбросить = useInvalidateWorkspaces()
  return useMutation({
    mutationFn: (name: string) =>
      unwrap<Workspace>(api.POST('/api/workspaces', { body: { name } })),
    onSuccess: сбросить,
  })
}

export function useRenameWorkspace() {
  const сбросить = useInvalidateWorkspaces()
  return useMutation({
    mutationFn: ({ id, name }: { id: string; name: string }) =>
      unwrap<Workspace>(
        api.PATCH('/api/workspaces/{workspace_id}', {
          params: { path: { workspace_id: id } },
          body: { name },
        }),
      ),
    onSuccess: сбросить,
  })
}

export function useTrashWorkspace() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) =>
      unwrap<Workspace>(
        api.DELETE('/api/workspaces/{workspace_id}', { params: { path: { workspace_id: id } } }),
      ),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.workspaces.all })
      // Проекты пространства уехали в корзину вместе с ним — списки работ
      // обязаны это заметить, иначе на экране останутся карточки того, чего нет.
      void qc.invalidateQueries({ queryKey: keys.projects.all })
    },
  })
}

export function useRestoreWorkspace() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) =>
      unwrap<Workspace>(
        api.POST('/api/workspaces/{workspace_id}/restore', {
          params: { path: { workspace_id: id } },
        }),
      ),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.workspaces.all })
      void qc.invalidateQueries({ queryKey: keys.projects.all })
    },
  })
}

/** Позвать по почте. Отказы: `no_such_user`, `already_member`, `unknown_role`. */
export function useAddMember() {
  const сбросить = useInvalidateWorkspaces()
  return useMutation({
    mutationFn: ({ id, email, role }: { id: string; email: string; role: string }) =>
      unwrap<MemberChanged>(
        api.POST('/api/workspaces/{workspace_id}/members', {
          params: { path: { workspace_id: id } },
          body: { email, role },
        }),
      ),
    onSuccess: сбросить,
  })
}

export function useSetMemberRole() {
  const сбросить = useInvalidateWorkspaces()
  return useMutation({
    mutationFn: ({ id, userId, role }: { id: string; userId: string; role: string }) =>
      unwrap<MemberChanged>(
        api.PATCH('/api/workspaces/{workspace_id}/members/{user_id}', {
          params: { path: { workspace_id: id, user_id: userId } },
          body: { role },
        }),
      ),
    onSuccess: сбросить,
  })
}

export function useRemoveMember() {
  const сбросить = useInvalidateWorkspaces()
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, userId }: { id: string; userId: string }) =>
      unwrap<{ removed: string }>(
        api.DELETE('/api/workspaces/{workspace_id}/members/{user_id}', {
          params: { path: { workspace_id: id, user_id: userId } },
        }),
      ),
    onSuccess: () => {
      сбросить()
      // Убрали позванного — служба унесла и его приглашение: колокольчик у
      // него обязан это заметить, а у нас в кэше лежит своё число непрочитанных.
      void qc.invalidateQueries({ queryKey: keys.notifications })
    },
  })
}

/**
 * Ответ на приглашение: «принять» и «отклонить».
 *
 * Приглашение не зачисляет — оно приходит уведомлением с двумя кнопками, и
 * ответ шлёт сам приглашённый. Что гасится после ответа, и почему именно это:
 *
 * * `workspaces` — пространство появилось в списке (или не появилось, если
 *   отказ), а список переключателя живёт минуту и сам бы этого не заметил;
 * * `notifications` — служба убрала строку приглашения: отвечать больше не на
 *   что, и кнопки в колокольчике остались бы обманкой;
 * * `projects` — принявший получил чужие работы, и если он тут же переключится
 *   в новое пространство, список обязан быть настоящим, а не пустым.
 */
function useAnswerInvite(путь: 'accept' | 'decline') {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, userId }: { id: string; userId: string }) =>
      unwrap(
        api.POST(
          путь === 'accept'
            ? '/api/workspaces/{workspace_id}/members/{user_id}/accept'
            : '/api/workspaces/{workspace_id}/members/{user_id}/decline',
          { params: { path: { workspace_id: id, user_id: userId } } },
        ),
      ),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.workspaces.all })
      void qc.invalidateQueries({ queryKey: keys.notifications })
      void qc.invalidateQueries({ queryKey: keys.projects.all })
    },
  })
}

export function useAcceptInvite() {
  return useAnswerInvite('accept')
}

export function useDeclineInvite() {
  return useAnswerInvite('decline')
}
