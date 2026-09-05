/**
 * Проверка экрана работы на подменённых ответах службы.
 *
 * Смысл — не в разметке, а в том, что экран складывается из настоящих адресов:
 * теги приезжают из `…/tags` (а не из ключей карточки, которых на новом проекте
 * нет), прогресс считается по ним, значение выбранного тега попадает в поле, а
 * цена задания и остаток месяца показаны ДО нажатия — как того требует правило
 * интерфейса.
 *
 * Служба подменяется на уровне `fetch`: так проверяется и разбор ответа
 * клиентом, и то, какие адреса экран на самом деле зовёт.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ThemeProvider } from '@/theme'
import { ToastProvider } from '@/ui'

import { ReportWorkPage } from './ReportWorkPage'

const ПРОЕКТ = {
  id: 'p-1',
  workspace_id: 'ws-1',
  owner_id: 'u-1',
  name: 'Лабораторная 4 — сортировки',
  created_at: '2026-09-02T10:00:00+00:00',
  updated_at: '2026-09-02T10:00:00+00:00',
  deleted_at: null,
  purge_after: null,
  bytes_used: 36658,
  keys: ['цель', 'теория', 'листинг', 'выводы'],
}

const ТЕГИ = [
  {
    key: 'цель',
    label: 'Цель работы',
    type: 'markdown',
    required: true,
    filled: true,
    source: 'agent',
    version: 2,
    at: '2026-09-02T10:05:00+00:00',
  },
  {
    key: 'теория',
    label: 'Теоретические сведения',
    type: 'markdown',
    required: true,
    filled: false,
    source: null,
    version: null,
    at: null,
  },
  {
    key: 'листинг',
    label: 'Листинг быстрой сортировки',
    type: 'code',
    required: true,
    filled: false,
    source: null,
    version: null,
    at: null,
  },
]

function json(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })
}

function служба(теги: unknown[] = ТЕГИ) {
  return vi.fn((request: Request) => {
    const { pathname } = new URL(request.url)
    if (pathname === '/api/projects/p-1') return Promise.resolve(json(ПРОЕКТ))
    if (pathname === '/api/workspaces/ws-1')
      return Promise.resolve(json({ id: 'ws-1', name: 'Личное', personal: true, role: 'owner' }))
    if (pathname === '/api/projects/p-1/tags') return Promise.resolve(json({ tags: теги }))
    if (pathname === '/api/projects/p-1/values')
      return Promise.resolve(
        json({ values: { цель: { type: 'markdown', text: 'Изучить алгоритмы сортировки.' } } }),
      )
    if (pathname === '/api/projects/p-1/materials') return Promise.resolve(json([]))
    if (pathname === '/api/keys/providers')
      return Promise.resolve(
        json({
          providers: ['deepseek', 'anthropic'],
          key_source: { deepseek: 'shared', anthropic: 'none' },
        }),
      )
    if (pathname === '/api/usage')
      return Promise.resolve(
        json({
          plan: 'free',
          limit_units: 2000000,
          spent_units: 200,
          remaining_units: 1999800,
          period_start: '2026-09-01T00:00:00+00:00',
          prices: { fill_tag: 100, fill_report: 1000, build: 50 },
        }),
      )
    throw new Error(`тест не ждал запроса ${pathname}`)
  })
}

function нарисовать() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <ThemeProvider>
        <ToastProvider>
          <MemoryRouter initialEntries={['/reports/p-1']}>
            <Routes>
              <Route path="/reports/:projectId" element={<ReportWorkPage />} />
            </Routes>
          </MemoryRouter>
        </ToastProvider>
      </ThemeProvider>
    </QueryClientProvider>,
  )
}

describe('экран работы над отчётом', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', служба())
  })
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('показывает теги шаблона, прогресс по ним и значение выбранного', async () => {
    нарисовать()
    // Выбранный тег назван дважды — строкой в списке и шапкой редактора.
    expect(await screen.findAllByText('{{цель}}')).toHaveLength(2)
    expect(screen.getByText('{{листинг}}')).toBeInTheDocument()
    // Прогресс — по тегам службы: один заполнен из трёх.
    expect(screen.getByText('1 из 3')).toBeInTheDocument()
    // Первый тег выбирается сам, и его значение уже в поле.
    expect(await screen.findByDisplayValue('Изучить алгоритмы сортировки.')).toBeInTheDocument()
  })

  it('называет цену задания и остаток месяца до нажатия', async () => {
    нарисовать()
    // Цена прогона тега — над полем, цена сборки — в панели превью: остаток
    // назван у каждой кнопки, которая его тратит.
    expect(await screen.findByText(/Стоит 100 ед/)).toBeInTheDocument()
    expect(screen.getByText(/Стоит 50 ед/)).toBeInTheDocument()
    expect(screen.getAllByText(/осталось 1 999 800/).length).toBeGreaterThan(1)
  })

  it('проект без шаблона — пустое состояние, а не пустой список', async () => {
    vi.stubGlobal('fetch', служба([]))
    нарисовать()
    expect(await screen.findByText('У этого проекта нет шаблона')).toBeInTheDocument()
  })
})
