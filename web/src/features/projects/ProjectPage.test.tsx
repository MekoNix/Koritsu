/**
 * Проверка страницы работы на подменённых ответах службы.
 *
 * Проверяется то, ради чего страница существует: имя работы, переходы в
 * готовые модули по адресам, о которых договорились области, и опись файлов с
 * приёмником. Плюс отдельное состояние «работа в корзине» — служба отвечает на
 * него `409 in_trash`, и показать это надо не экраном ошибки, а выходом
 * («восстановить»).
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ThemeProvider } from '@/theme'
import { ToastProvider } from '@/ui'

import { ProjectPage } from './ProjectPage'

const ПРОЕКТ = {
  id: 'p-1',
  workspace_id: 'ws-1',
  owner_id: 'u-1',
  name: 'Курсовая — ИС библиотеки',
  created_at: '2026-09-02T10:00:00+00:00',
  updated_at: '2026-09-02T10:00:00+00:00',
  deleted_at: null,
  purge_after: null,
  bytes_used: 1048576,
  keys: ['цель', 'выводы'],
}

const МАТЕРИАЛ = {
  id: 'df06a90d2382ec18',
  name: 'методичка.pdf',
  kind: 'pdf',
  bytes: 36658,
  unit: 'page',
  units: 12,
  lang: 'cyrillic',
  added: '2026-09-02T10:05:00+00:00',
  notes: [],
  children: [],
}

const МОДУЛИ = [
  { id: 'reports', title: 'Reports', routes: '/api/projects' },
  { id: 'flowcharts', title: 'Flowcharts', routes: '/api/flowcharts' },
  { id: 'uml', title: 'UML diagrams', routes: '/api/uml' },
]

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

/** Служба, отвечающая на всё, что спрашивает страница работы. */
function служба(проект: unknown | 'in_trash') {
  return vi.fn((request: Request) => {
    const path = new URL(request.url).pathname
    if (path === '/api/projects/p-1') {
      if (проект === 'in_trash') {
        return Promise.resolve(
          json({ error: { code: 'in_trash', message: 'Project is in the trash' } }, 409),
        )
      }
      return Promise.resolve(json(проект))
    }
    if (path === '/api/workspaces/ws-1') {
      return Promise.resolve(json({ id: 'ws-1', name: 'Личное', personal: true, role: 'owner' }))
    }
    if (path === '/api/modules') return Promise.resolve(json(МОДУЛИ))
    if (path === '/api/projects/p-1/materials') return Promise.resolve(json([МАТЕРИАЛ]))
    if (path === '/api/projects/p-1/materials/pending') return Promise.resolve(json([]))
    throw new Error(`тест не ждал запроса ${path}`)
  })
}

function нарисовать() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <ThemeProvider>
        <ToastProvider>
          <MemoryRouter initialEntries={['/projects/p-1']}>
            <Routes>
              <Route path="/projects/:projectId" element={<ProjectPage />} />
            </Routes>
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

describe('страница работы', () => {
  it('показывает имя, файлы и переходы в готовые модули', async () => {
    vi.stubGlobal('fetch', служба(ПРОЕКТ))
    нарисовать()

    expect(await screen.findByRole('heading', { name: 'Курсовая — ИС библиотеки' })).toBeVisible()

    // Адреса экранов модулей — договор между областями ночи.
    expect(await screen.findByRole('link', { name: /Отчёты/ })).toHaveAttribute(
      'href',
      '/reports/p-1',
    )
    expect(screen.getByRole('link', { name: /Блок-схемы/ })).toHaveAttribute(
      'href',
      '/flowcharts/p-1',
    )
    expect(screen.getByRole('link', { name: /UML/ })).toHaveAttribute('href', '/uml/p-1')

    expect(await screen.findByText('методичка.pdf')).toBeVisible()
    expect(screen.getByText(/12 страниц/)).toBeVisible()
    // Приёмник файлов один на всю работу, а не под тег.
    expect(screen.getByText('Перетащите файлы или выберите их')).toBeVisible()
  })

  it('работа в корзине — не ошибка, а предложение восстановить', async () => {
    vi.stubGlobal('fetch', служба('in_trash'))
    нарисовать()

    expect(await screen.findByText('Работа в корзине')).toBeVisible()
    expect(screen.getByRole('button', { name: /Восстановить/ })).toBeVisible()
  })
})
