/**
 * Тест переключения рабочего пространства.
 *
 * Проверяются два обещания, на которых держится переключение:
 *
 * 1. **пока выбора нет, ничего не меняется** — сайт спрашивает личное
 *    пространство ровно тем же запросом, что и раньше; иначе экраны начали бы
 *    ходить в службу вторым маршрутом без всякой на то причины;
 * 2. **выбор переключает списки** — после `setCurrentWorkspaceId` хук отдаёт
 *    другое пространство, и выбор переживает перезагрузку (лежит в
 *    `localStorage`).
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { setCurrentWorkspaceId, useCurrentWorkspace } from './useCurrentWorkspace'

const ЛИЧНОЕ = {
  id: 'ws-personal',
  name: 'Личное',
  personal: true,
  role: 'owner',
  created_at: '2026-09-01T10:00:00+00:00',
  deleted_at: null,
  purge_after: null,
}

const КАФЕДРА = { ...ЛИЧНОЕ, id: 'ws-2', name: 'Кафедра', personal: false, role: 'editor' }

function json(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })
}

let адреса: string[] = []

function обёртка({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}

beforeEach(() => {
  адреса = []
  window.localStorage.clear()
  setCurrentWorkspaceId(null)
  vi.stubGlobal(
    'fetch',
    vi.fn((request: Request) => {
      const url = new URL(request.url)
      адреса.push(url.pathname)
      if (url.pathname === '/api/workspaces/personal') return Promise.resolve(json(ЛИЧНОЕ))
      if (url.pathname === `/api/workspaces/${КАФЕДРА.id}`) return Promise.resolve(json(КАФЕДРА))
      throw new Error(`тест не ждал запроса ${url.pathname}`)
    }),
  )
})

afterEach(() => {
  vi.unstubAllGlobals()
  setCurrentWorkspaceId(null)
  window.localStorage.clear()
})

describe('текущее пространство', () => {
  it('без выбора спрашивает личное — и только его', async () => {
    const { result } = renderHook(() => useCurrentWorkspace(), { wrapper: обёртка })

    await waitFor(() => expect(result.current.data?.id).toBe('ws-personal'))
    expect(адреса).toEqual(['/api/workspaces/personal'])
  })

  it('после выбора отдаёт выбранное и помнит его', async () => {
    const { result } = renderHook(() => useCurrentWorkspace(), { wrapper: обёртка })
    await waitFor(() => expect(result.current.data?.id).toBe('ws-personal'))

    // Смена — снаружи React: подписка `useSyncExternalStore` обязана её
    // подхватить, и `act` здесь только затем, чтобы дождаться перерисовки.
    act(() => setCurrentWorkspaceId(КАФЕДРА.id))

    await waitFor(() => expect(result.current.data?.id).toBe(КАФЕДРА.id))
    expect(result.current.data?.role).toBe('editor')
    // Выбор пережил бы перезагрузку: он лежит в хранилище, а не в состоянии.
    expect(window.localStorage.getItem('koritsu.workspace')).toBe(КАФЕДРА.id)
  })
})
