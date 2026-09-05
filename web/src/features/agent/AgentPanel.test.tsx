/**
 * Проверка окна агента на подменённых ответах службы.
 *
 * Проверяется то, ради чего панель существует именно панелью: она открывается
 * горячей клавишей с любого экрана, закрывается `Esc`, берёт работу из адреса
 * и **не затемняет** экран под собой — немодальность здесь намеренная, и
 * потерять её случайной правкой легче всего.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ToastProvider } from '@/ui'

import { AgentPanel } from './AgentPanel'
import { closeAgentPanel } from './panelStore'

const ПРОЕКТ = {
  id: 'p-1',
  workspace_id: 'ws-1',
  owner_id: 'u-1',
  name: 'Лабораторная 4 — Сортировки',
  created_at: '2026-09-05T01:00:00+00:00',
  updated_at: '2026-09-05T01:00:00+00:00',
  deleted_at: null,
  purge_after: null,
  bytes_used: 1024,
  keys: ['теория', 'вывод'],
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

/** Служба, отвечающая на всё, что спрашивает открытая панель. */
function служба() {
  return vi.fn((request: Request) => {
    const url = new URL(request.url)
    if (url.pathname === '/api/projects/p-1') return Promise.resolve(json(ПРОЕКТ))
    if (url.pathname === '/api/keys/providers') {
      return Promise.resolve(
        json({
          providers: ['deepseek', 'anthropic'],
          key_source: { deepseek: 'shared', anthropic: 'none' },
        }),
      )
    }
    if (url.pathname === '/api/usage') {
      return Promise.resolve(
        json({
          plan: 'free',
          limit_units: 1000,
          spent_units: 40,
          remaining_units: 960,
          period_start: '2026-09-01T00:00:00+00:00',
          prices: { agent: 12 },
        }),
      )
    }
    if (url.pathname === '/api/jobs') return Promise.resolve(json({ jobs: [] }))
    return Promise.resolve(json({ error: { code: 'not_found', message: 'no' } }, 404))
  })
}

function нарисовать() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <ToastProvider>
        <MemoryRouter initialEntries={['/reports/p-1']}>
          <Routes>
            <Route path="/reports/:projectId" element={<AgentPanel />} />
          </Routes>
        </MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>,
  )
}

describe('AgentPanel', () => {
  beforeEach(() => {
    closeAgentPanel()
    vi.stubGlobal('fetch', служба())
  })

  afterEach(() => {
    closeAgentPanel()
    vi.unstubAllGlobals()
  })

  it('открывается по Ctrl+J, берёт работу из адреса и закрывается Esc', async () => {
    нарисовать()
    expect(screen.queryByRole('dialog')).toBeNull()

    // `act` вокруг нажатия: панель открывается внешним хранилищем
    // (`useSyncExternalStore`), и Radix доводит открытие своими эффектами уже
    // после события — без обёртки React ругается на обновление вне `act`.
    await act(async () => {
      fireEvent.keyDown(window, { key: 'j', ctrlKey: true })
    })
    const панель = await screen.findByRole('dialog')
    expect(панель).toBeInTheDocument()

    // Работа взята из адреса — имя приезжает карточкой проекта.
    expect(await screen.findByText('Лабораторная 4 — Сортировки')).toBeInTheDocument()
    // Цена задания и остаток — до нажатия.
    expect(await screen.findByText(/Стоит 12/)).toBeInTheDocument()

    await act(async () => {
      fireEvent.keyDown(панель, { key: 'Escape' })
    })
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  })

  it('не модальна: экран под ней остаётся живым', async () => {
    нарисовать()
    await act(async () => {
      fireEvent.keyDown(window, { key: 'j', ctrlKey: true })
    })
    const панель = await screen.findByRole('dialog')
    // `aria-modal` у немодального окна не стоит, и затемнения под ним нет:
    // и то и другое отняло бы у человека экран, ради которого он панель открыл.
    expect(панель.getAttribute('aria-modal')).not.toBe('true')
    expect(document.body.style.pointerEvents).not.toBe('none')
  })
})
