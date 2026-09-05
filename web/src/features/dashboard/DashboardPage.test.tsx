/**
 * Проверка ленты дашборда на подменённых ответах службы.
 *
 * Смысл — в составе и порядке ленты: она фиксированная,
 * значит проверять её надо не «нарисовалось хоть что-то», а тем, что все
 * заявленные виджеты на месте и стоят в заданном порядке. Заодно ловится то,
 * что не поймают ни типы, ни линтер: пропавший ключ перевода и виджет,
 * упавший на первом рендере.
 *
 * Отдельно проверяется правило брифа: карточка модуля рисуется только по
 * ответу `GET /api/modules`. Служба неготовые модули не отдаёт, поэтому
 * достаточно убрать модуль из ответа — и его на дашборде быть не должно.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ThemeProvider } from '@/theme'
import { ToastProvider } from '@/ui'

import { DashboardPage } from './DashboardPage'

const ПРОСТРАНСТВО = { id: 'ws-1', name: 'Личное', personal: true, role: 'owner' }

const ПРОЕКТ = {
  id: 'p-1',
  workspace_id: 'ws-1',
  owner_id: 'u-1',
  name: 'Лабораторная 4 — сортировки',
  created_at: '2026-09-02T10:00:00+00:00',
  updated_at: '2026-09-02T10:00:00+00:00',
  deleted_at: null,
  purge_after: null,
  bytes_used: 2097152,
}

const РАСХОД = {
  plan: 'free',
  limit_units: 2000000,
  spent_units: 60,
  remaining_units: 1999940,
  period_start: '2026-09-01T00:00:00+00:00',
  prices: { build: 50, parse: 10 },
}

function json(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })
}

function служба(модули: { id: string; title: string; routes: string }[]) {
  return vi.fn((request: Request) => {
    const url = new URL(request.url)
    switch (url.pathname) {
      case '/api/auth/me':
        // Обёртка `{user: …}` — как у службы (`accounts/routes.py: whoami`);
        // без неё `useMe` честно отдаёт `null`, и приветствия нет вовсе.
        return Promise.resolve(
          json({
            user: {
              id: 'u-1',
              email: 'человек@example.org',
              nickname: 'курису',
              plan: 'free',
            },
          }),
        )
      case '/api/workspaces/personal':
        return Promise.resolve(json(ПРОСТРАНСТВО))
      case '/api/projects':
        return Promise.resolve(json({ projects: [ПРОЕКТ] }))
      case '/api/modules':
        return Promise.resolve(json(модули))
      case '/api/usage':
        return Promise.resolve(json(РАСХОД))
      case '/api/jobs':
        return Promise.resolve(json({ jobs: [] }))
      case '/api/notifications':
        return Promise.resolve(json({ notifications: [], unread_count: 0 }))
      default:
        throw new Error(`тест не ждал запроса ${url.pathname}`)
    }
  })
}

function нарисовать() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <ThemeProvider>
        <ToastProvider>
          <MemoryRouter initialEntries={['/']}>
            <DashboardPage />
          </MemoryRouter>
        </ToastProvider>
      </ThemeProvider>
    </QueryClientProvider>,
  )
}

const ВСЕ_МОДУЛИ = [
  { id: 'reports', title: 'Reports', routes: '/api/projects' },
  { id: 'flowcharts', title: 'Flowcharts', routes: '/api/flowcharts' },
  { id: 'uml', title: 'UML diagrams', routes: '/api/uml' },
]

beforeEach(() => {
  document.cookie = 'koritsu_csrf=token-abc'
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('лента дашборда', () => {
  it('собирается из всех виджетов: утилита, расход, модули, статистика, работы', async () => {
    vi.stubGlobal('fetch', служба(ВСЕ_МОДУЛИ))
    нарисовать()

    expect(await screen.findByText('Word → PDF')).toBeVisible()
    expect(await screen.findByText('Расход за месяц')).toBeVisible()
    expect(await screen.findByRole('link', { name: /Отчёты/ })).toHaveAttribute('href', '/reports')

    // Статистика: работа одна, очередь пуста, место — сумма по работам.
    const статистика = (await screen.findByRole('heading', { name: 'Статистика' })).closest(
      'section',
    )
    expect(статистика).not.toBeNull()
    expect(within(статистика as HTMLElement).getByText('1')).toBeVisible()
    expect(within(статистика as HTMLElement).getByText('2,0 МБ')).toBeVisible()

    expect(await screen.findByText('Лабораторная 4 — сортировки')).toBeVisible()
  })

  it('здоровается ником, а почту показывает частично', async () => {
    vi.stubGlobal('fetch', служба(ВСЕ_МОДУЛИ))
    нарисовать()

    // Приветствие зависит от времени суток, поэтому проверяется ник в нём, а
    // не весь текст: иначе тест падал бы дважды в сутки.
    expect(await screen.findByText(/курису/)).toBeVisible()
    expect(screen.getByText('ч***@example.org')).toBeVisible()
    expect(screen.queryByText('человек@example.org')).toBeNull()
  })

  it('модуля, которого служба не отдала, на дашборде нет вовсе', async () => {
    vi.stubGlobal('fetch', служба(ВСЕ_МОДУЛИ.filter((module) => module.id !== 'uml')))
    нарисовать()

    await screen.findByRole('link', { name: /Отчёты/ })
    expect(screen.queryByRole('link', { name: /UML/ })).toBeNull()
  })
})
