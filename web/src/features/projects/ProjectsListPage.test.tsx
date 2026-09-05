/**
 * Проверка списка работ на подменённых ответах службы.
 *
 * Смысл теста — не в разметке, а в том, что экран целиком складывается:
 * личное пространство спрашивается первым, список берётся по его
 * идентификатору, корзина — тот же список с `trash=true`, а пустой ответ даёт
 * пустое состояние с приглашением, а не белое поле (§7 спецификации).
 *
 * Служба подменяется на уровне `fetch`, а не хуков: так проверяется и то, как
 * клиент разбирает ответ, и то, какие адреса экран на самом деле зовёт.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ThemeProvider } from '@/theme'
import { ToastProvider } from '@/ui'

import { ProjectsListPage } from './ProjectsListPage'

const ПРОСТРАНСТВО = {
  id: 'ws-1',
  name: 'Личное',
  personal: true,
  role: 'owner',
  created_at: '2026-09-01T10:00:00+00:00',
  deleted_at: null,
  purge_after: null,
}

function проект(patch: Record<string, unknown> = {}) {
  return {
    id: 'p-1',
    workspace_id: 'ws-1',
    owner_id: 'u-1',
    name: 'Лабораторная 4 — сортировки',
    created_at: '2026-09-02T10:00:00+00:00',
    updated_at: '2026-09-02T10:00:00+00:00',
    deleted_at: null,
    purge_after: null,
    bytes_used: 36658,
    ...patch,
  }
}

function json(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })
}

/** Ответы по адресу: тест задаёт, что лежит в активном списке и в корзине. */
function служба(активные: unknown[], корзина: unknown[]) {
  return vi.fn((request: Request) => {
    const url = new URL(request.url)
    if (url.pathname === '/api/workspaces/personal') return Promise.resolve(json(ПРОСТРАНСТВО))
    if (url.pathname === '/api/projects') {
      const trash = url.searchParams.get('trash') === 'true'
      return Promise.resolve(json({ projects: trash ? корзина : активные }))
    }
    throw new Error(`тест не ждал запроса ${url.pathname}`)
  })
}

function нарисовать() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <ThemeProvider>
        <ToastProvider>
          <MemoryRouter initialEntries={['/projects']}>
            <ProjectsListPage />
          </MemoryRouter>
        </ToastProvider>
      </ThemeProvider>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  document.cookie = 'koritsu_csrf=token-abc'
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('список работ', () => {
  it('показывает работы пространства и их размер', async () => {
    vi.stubGlobal('fetch', служба([проект()], []))
    нарисовать()

    expect(await screen.findByText('Лабораторная 4 — сортировки')).toBeInTheDocument()
    expect(screen.getByText(/35,8 КБ/)).toBeInTheDocument()
  })

  it('пустой список — приглашение завести работу, а не белое поле', async () => {
    vi.stubGlobal('fetch', служба([], []))
    нарисовать()

    expect(await screen.findByText('Работ пока нет')).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: /Новая работа/ }).length).toBeGreaterThan(0)
  })

  it('корзина — тот же список с trash=true, со своим пустым состоянием', async () => {
    const fetchSpy = служба([проект()], [])
    vi.stubGlobal('fetch', fetchSpy)
    const user = userEvent.setup()
    нарисовать()

    await screen.findByText('Лабораторная 4 — сортировки')
    await user.click(screen.getByRole('button', { name: 'Корзина' }))

    expect(await screen.findByText('Корзина пуста')).toBeInTheDocument()
    const адреса = fetchSpy.mock.calls.map(([request]) => (request as Request).url)
    expect(адреса.some((url) => url.includes('trash=true'))).toBe(true)
  })
})
