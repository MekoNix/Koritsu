/**
 * Главная отчётов на подменённых ответах службы.
 *
 * Проверяется не разметка, а обещания страницы, каждое из которых иначе
 * ломается молча:
 *
 * 1. **Отчёты видны сразу и всеми работами.** Лента берётся одним запросом
 *    (`GET /api/reports?workspace_id=`), и шага «выберите работу» перед ней
 *    нет: отчёты двух разных работ стоят на экране рядом, каждый назван своей
 *    работой.
 * 2. **Работа — отбор, а не шаг.** `?project=<работа>` показывает ту же ленту,
 *    суженную до одной работы: по этому адресу приходят старые ссылки, и он же
 *    получается от выпадающего списка над сеткой.
 * 3. **Отчёт заводится отсюда же**, окном с выбором работы, и уводит на
 *    заведённый отчёт, а не обратно в список.
 *
 * Служба подменяется на уровне `fetch`: так проверяется и разбор ответа
 * клиентом, и то, какие адреса страница на самом деле зовёт.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ThemeProvider } from '@/theme'
import { ToastProvider } from '@/ui'

import { ReportsHomePage } from './ReportsHomePage'

const ПРОСТРАНСТВО = { id: 'ws-1', name: 'Личное', personal: true, role: 'owner' }

const РАБОТЫ = [
  { id: 'p-1', workspace_id: 'ws-1', name: 'Курсовая', workspace_name: 'Личное' },
  { id: 'p-2', workspace_id: 'ws-1', name: 'Практика', workspace_name: 'Личное' },
]

/** Лента службы: новые сверху, отчёты разных работ вперемешку. */
const ЛЕНТА = [
  {
    id: 'r-2',
    project_id: 'p-2',
    project_name: 'Практика',
    name: 'Дневник практики',
    n: 1,
    user_id: 'u-1',
    created_at: '2026-09-04T10:00:00+00:00',
    preview_artifact_id: null,
    template_name: 'Бланк практики',
    tags: 4,
  },
  {
    id: 'r-1',
    project_id: 'p-1',
    project_name: 'Курсовая',
    name: 'Глава 1',
    n: 1,
    user_id: 'u-1',
    created_at: '2026-09-02T10:00:00+00:00',
    preview_artifact_id: null,
    template_name: 'ГОСТ кафедры',
    tags: 7,
  },
]

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

/** Служба: пространство, работы, лента отчётов, бланки и заведение отчёта. */
function служба(лента: unknown[] = ЛЕНТА) {
  return vi.fn((request: Request) => {
    const { pathname, searchParams } = new URL(request.url)
    if (pathname === '/api/workspaces/personal') return Promise.resolve(json(ПРОСТРАНСТВО))
    if (pathname === '/api/projects') return Promise.resolve(json({ projects: РАБОТЫ }))
    if (pathname === '/api/reports') {
      // Отбор по работе — дело страницы, а не службы: маршрут отдаёт
      // пространство целиком, и подмена обязана вести себя так же.
      expect(searchParams.get('workspace_id')).toBe('ws-1')
      return Promise.resolve(json(лента))
    }
    if (pathname === '/api/projects/p-1/templates')
      return Promise.resolve(json([{ id: 't-1', name: 'ГОСТ кафедры', tags: 7, sha256: 'a' }]))
    if (pathname === '/api/projects/p-2/templates') return Promise.resolve(json([]))
    if (pathname === '/api/projects/p-2/reports' && request.method === 'POST')
      return Promise.resolve(json({ ...ЛЕНТА[0], id: 'r-9', name: 'Отчёт по практике' }, 201))
    throw new Error(`тест не ждал запроса ${request.method} ${pathname}`)
  })
}

/** Куда увела страница: адрес виден только изнутри роутера. */
function CurrentUrl() {
  const { pathname, search } = useLocation()
  return <span data-testid="адрес">{pathname + search}</span>
}

function Screen() {
  return (
    <>
      <CurrentUrl />
      <Routes>
        <Route path="/reports" element={<ReportsHomePage />} />
        <Route path="/reports/:projectId/:runId" element={<span>экран отчёта</span>} />
      </Routes>
    </>
  )
}

function нарисовать(адрес = '/reports') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <ThemeProvider>
        <ToastProvider>
          <MemoryRouter initialEntries={[адрес]}>
            <Screen />
          </MemoryRouter>
        </ToastProvider>
      </ThemeProvider>
    </QueryClientProvider>,
  )
}

/** Сетка карточек: имена работ есть ещё и в выпадающих списках. */
function карточки() {
  return within(screen.getByTestId('report-cards'))
}

describe('главная отчётов', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', служба())
  })
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('показывает отчёты всех работ пространства сразу, без выбора работы', async () => {
    нарисовать()
    expect(await screen.findByText('Дневник практики')).toBeInTheDocument()
    expect(карточки().getByText('Глава 1')).toBeInTheDocument()
    // Каждый отчёт назван своей работой: без этого две «Главы 1» из разных
    // курсовых в одной ленте неразличимы. Имя работы — ссылка на саму работу.
    expect(карточки().getByRole('link', { name: 'Практика' })).toHaveAttribute(
      'href',
      '/projects/p-2',
    )
    expect(карточки().getByRole('link', { name: 'Курсовая' })).toHaveAttribute(
      'href',
      '/projects/p-1',
    )
  })

  it('адрес с работой сужает ленту до неё одной', async () => {
    нарисовать('/reports?project=p-1')
    expect(await screen.findByText('Глава 1')).toBeInTheDocument()
    expect(screen.queryByText('Дневник практики')).not.toBeInTheDocument()
  })

  it('выпадающий список работ отбирает, не уводя со страницы', async () => {
    const человек = userEvent.setup()
    нарисовать()
    expect(await screen.findByText('Дневник практики')).toBeInTheDocument()
    await человек.selectOptions(screen.getByLabelText('Отбор по работе'), 'p-1')
    await waitFor(() => expect(screen.queryByText('Дневник практики')).not.toBeInTheDocument())
    expect(карточки().getByText('Глава 1')).toBeInTheDocument()
    // Отбор стоит в адресе: перезагрузка и ссылка сохраняют его.
    expect(screen.getByTestId('адрес')).toHaveTextContent('/reports?project=p-1')
  })

  it('поиск идёт и по имени отчёта, и по имени работы', async () => {
    const человек = userEvent.setup()
    нарисовать()
    expect(await screen.findByText('Дневник практики')).toBeInTheDocument()
    await человек.type(screen.getByLabelText('Найти отчёт или работу'), 'курсов')
    await waitFor(() => expect(screen.queryByText('Дневник практики')).not.toBeInTheDocument())
    expect(карточки().getByText('Глава 1')).toBeInTheDocument()
  })

  it('отчёт заводится окном с выбором работы и уводит на сам отчёт', async () => {
    const человек = userEvent.setup()
    нарисовать()
    expect(await screen.findByText('Дневник практики')).toBeInTheDocument()

    await человек.click(screen.getByRole('button', { name: 'Создать отчёт' }))
    const окно = await screen.findByRole('dialog')
    // Работа выбирается здесь же: шага «сначала работа» перед списком нет.
    await человек.selectOptions(within(окно).getByLabelText('Работа'), 'p-2')
    await человек.click(within(окно).getByRole('button', { name: 'Создать' }))

    await waitFor(() => expect(screen.getByTestId('адрес')).toHaveTextContent('/reports/p-2/r-9'))
  })

  it('отчётов нет — предложение завести первый, а не пустой экран', async () => {
    vi.stubGlobal('fetch', служба([]))
    нарисовать()
    expect(await screen.findByText('Отчётов пока нет')).toBeInTheDocument()
  })
})
