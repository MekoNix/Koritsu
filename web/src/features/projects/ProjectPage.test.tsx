/**
 * Проверка страницы работы на подменённых ответах службы.
 *
 * Проверяется то, ради чего страница существует: имя работы, журнал запусков
 * (в том числе имя схемы, которое сайт рисует сам), переходы в готовые модули
 * по адресам, о которых договорились области, и опись файлов с приёмником. Плюс отдельное состояние «работа в корзине» — служба отвечает на
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
  workspace_name: 'Личное',
  owner_id: 'u-1',
  name: 'Курсовая — ИС библиотеки',
  created_at: '2026-09-02T10:00:00+00:00',
  updated_at: '2026-09-02T10:00:00+00:00',
  deleted_at: null,
  purge_after: null,
  bytes_used: 1048576,
  module: 'reports',
  keys: ['цель', 'выводы'],
}

/**
 * Журнал запусков. Вторая запись — без имени: его сайт собирает сам из модуля,
 * номера и имени работы, потому что наружу служба говорит по-английски.
 */
const ЗАПУСКИ = [
  {
    id: 'r-1',
    project_id: 'p-1',
    module: 'reports',
    name: 'Отчёт по практике',
    n: 1,
    artifact_id: null,
    user_id: 'u-1',
    created_at: '2026-09-02T10:10:00+00:00',
  },
  {
    id: 'r-2',
    project_id: 'p-1',
    module: 'flowcharts',
    name: '',
    n: 2,
    artifact_id: 'a1b2c3d4e5f60718',
    user_id: 'u-1',
    created_at: '2026-09-02T10:20:00+00:00',
  },
]

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
    if (path === '/api/workspaces/ws-1' || path === '/api/workspaces/personal') {
      return Promise.resolve(json({ id: 'ws-1', name: 'Личное', personal: true, role: 'owner' }))
    }
    // Подпись «Пространство» и полоска «работа из другого пространства» знают
    // текущее пространство и ник хозяина — отсюда эти два ответа.
    if (path === '/api/auth/me') {
      return Promise.resolve(json({ user: { id: 'u-1', nickname: 'курису' } }))
    }
    if (path === '/api/modules') return Promise.resolve(json(МОДУЛИ))
    if (path === '/api/projects/p-1/runs') return Promise.resolve(json(ЗАПУСКИ))
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

    // Адреса экранов модулей — договор между областями. Плитки ищутся по
    // приписке, а не по названию модуля: то же название стоит и в строке
    // журнала, и поиск по нему нашёл бы две ссылки вместо одной.
    expect(await screen.findByRole('link', { name: /Заполнить теги/ })).toHaveAttribute(
      'href',
      '/reports/p-1',
    )
    expect(screen.getByRole('link', { name: /Блок-схема по коду/ })).toHaveAttribute(
      'href',
      '/flowcharts/p-1',
    )
    expect(screen.getByRole('link', { name: /Диаграмма классов/ })).toHaveAttribute(
      'href',
      '/uml/p-1',
    )

    // Журнал: своё имя показывается как есть, а безымянной схеме имя рисует
    // сайт — служба его не сочиняет.
    expect(await screen.findByText('Отчёт по практике')).toBeVisible()
    expect(screen.getByText('Схема 2 — Курсовая — ИС библиотеки')).toBeVisible()

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
