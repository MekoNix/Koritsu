/**
 * useCurrentWorkspace — в каком пространстве человек сейчас работает.
 *
 * До ночи 2 сайт знал одно пространство — личное (`GET /api/workspaces/personal`),
 * и каждый список проектов спрашивал именно его. Пространств у человека может
 * быть несколько (его позвали в чужое), поэтому «текущее» стало отдельным
 * состоянием оболочки. Живёт оно в двух местах, и оба обязательны:
 *
 * * **`localStorage`** — чтобы выбор пережил перезагрузку. Пространство,
 *   сбрасывающееся на личное при каждом F5, — это не переключатель;
 * * **подписка (`useSyncExternalStore`)** — чтобы все экраны узнали о смене
 *   разом. Контекст здесь не заведён намеренно: он потребовал бы провайдера в
 *   `app/` (чужая область), а состояние тут — одна строка на всё приложение.
 *
 * **Запрос остаётся один.** Выбора нет — спрашивается личное, ровно как
 * раньше; выбор есть — спрашивается это пространство по идентификатору.
 * Списка пространств здесь не запрашивается вовсе: он нужен только
 * переключателю и странице участников, и платить за него на каждом экране
 * незачем.
 *
 * Выбранного пространства не стало (удалили, убрали из участников) — выбор
 * гасится сам, и человек возвращается в личное, а не смотрит на «не найдено».
 */
import { useQuery, type UseQueryResult } from '@tanstack/react-query'
import { useEffect, useSyncExternalStore } from 'react'

import { ApiError } from '../errors'
import { api, unwrap } from '../client'
import { keys } from '../queryKeys'

/** `packages/api/workspaces/routes.py: карточка()`. */
export type Workspace = {
  id: string
  name: string
  personal: boolean
  /** Роль спрашивающего: `owner` | `editor` | `viewer`. */
  role: string
  created_at: string
  deleted_at: string | null
  purge_after: string | null
}

/** Где помнится выбор. Ключ с приставкой: `localStorage` один на весь домен. */
const STORAGE_KEY = 'koritsu.workspace'

function прочитать(): string | null {
  try {
    return window.localStorage.getItem(STORAGE_KEY)
  } catch {
    // Приватный режим и запрет на хранилище — не повод падать: без памяти
    // сайт работает, просто выбор не переживёт перезагрузку.
    return null
  }
}

let текущий: string | null = typeof window === 'undefined' ? null : прочитать()
const подписчики = new Set<() => void>()

function подписаться(слушатель: () => void): () => void {
  подписчики.add(слушатель)
  return () => подписчики.delete(слушатель)
}

function снимок(): string | null {
  return текущий
}

/** Сменить текущее пространство. `null` — вернуться в личное. */
export function setCurrentWorkspaceId(id: string | null): void {
  if (текущий === id) return
  текущий = id
  try {
    if (id) window.localStorage.setItem(STORAGE_KEY, id)
    else window.localStorage.removeItem(STORAGE_KEY)
  } catch {
    // См. `прочитать`: без хранилища выбор живёт до перезагрузки.
  }
  for (const слушатель of подписчики) слушатель()
}

/** Идентификатор выбранного пространства или `null`, если это личное. */
export function useCurrentWorkspaceId(): string | null {
  return useSyncExternalStore(подписаться, снимок, () => null)
}

/**
 * Текущее пространство целиком: имя (для переключателя) и роль спрашивающего
 * (по ней экраны решают, показывать ли кнопки правки).
 *
 * Форма ответа та же, что у прежнего `usePersonalWorkspace`, — экраны меняют
 * одну строку импорта и больше ничего.
 */
export function useCurrentWorkspace(): UseQueryResult<Workspace> {
  const id = useCurrentWorkspaceId()

  const личное = useQuery({
    queryKey: keys.workspaces.personal,
    queryFn: () => unwrap<Workspace>(api.GET('/api/workspaces/personal')),
    enabled: !id,
    staleTime: 5 * 60_000,
  })

  const выбранное = useQuery({
    queryKey: [...keys.workspaces.all, id ?? ''],
    enabled: !!id,
    queryFn: () =>
      unwrap<Workspace>(
        api.GET('/api/workspaces/{workspace_id}', {
          params: { path: { workspace_id: id as string } },
        }),
      ),
    staleTime: 5 * 60_000,
    // Пропавшее пространство повторять незачем: оно не появится.
    retry: false,
  })

  // Пространства больше нет или человека из него убрали — выбор гасится, и
  // экраны сами возвращаются в личное.
  const пропало =
    !!id && выбранное.isError && выбранное.error instanceof ApiError
      ? выбранное.error.status === 404 || выбранное.error.status === 403
      : false
  useEffect(() => {
    if (пропало) setCurrentWorkspaceId(null)
  }, [пропало])

  return id ? выбранное : личное
}
