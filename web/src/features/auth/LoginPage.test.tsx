/**
 * Проверка того, что каркас вообще собирается в работающий экран.
 *
 * Тест не про вход как таковой: он про то, что провайдеры, роутер, переводы,
 * темы и набор компонентов складываются вместе и рисуют форму с русскими
 * подписями. Такая проверка ловит то, что не ловят ни типы, ни линтер:
 * пропавший ключ перевода, забытый провайдер, компонент, упавший на первом же
 * рендере.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import { ThemeProvider } from '@/theme'
import { ToastProvider } from '@/ui'

import { LoginPage } from './LoginPage'

function renderLogin() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <ThemeProvider>
        <ToastProvider>
          <MemoryRouter initialEntries={['/auth/login']}>
            <LoginPage />
          </MemoryRouter>
        </ToastProvider>
      </ThemeProvider>
    </QueryClientProvider>,
  )
}

describe('страница входа', () => {
  it('рисует форму с русскими подписями из словаря', () => {
    renderLogin()

    expect(screen.getByRole('heading', { name: 'Вход' })).toBeInTheDocument()
    expect(screen.getByLabelText('Почта')).toBeInTheDocument()
    expect(screen.getByLabelText('Пароль')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Войти' })).toBeInTheDocument()
  })

  it('не пускает пустую форму в службу и говорит, чего не хватает', async () => {
    const user = userEvent.setup()
    renderLogin()

    await user.click(screen.getByRole('button', { name: 'Войти' }))

    // Проверка zod отрабатывает до запроса: сеть в тесте не подменена вовсе,
    // и любой запрос отсюда был бы виден падением.
    expect(await screen.findByText('Введите почту.')).toBeInTheDocument()
    expect(screen.getByText('Введите пароль.')).toBeInTheDocument()
  })
})
