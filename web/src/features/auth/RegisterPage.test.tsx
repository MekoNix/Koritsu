/**
 * Проверка формы регистрации — той её части, которая появилась вместе с ником.
 *
 * Три обещания, и все три ломаются молча:
 *
 * 1. **поле ника есть и оно обязательное.** Ник — имя человека на всех
 *    экранах; форма, отправившая регистрацию без него, получила бы отказ
 *    службы вместо подсказки под полем;
 * 2. **границы и знаки проверяются на месте.** «Ник из одной буквы» и «ник с
 *    пробелом» — разные беды и чинятся по-разному, поэтому и сообщения разные;
 * 3. **годный ник уезжает в службу тем же полем `nickname`.** Ошибка в имени
 *    поля не видна ни типам (тело собирается из значений формы), ни глазами.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { ThemeProvider } from '@/theme'
import { ToastProvider } from '@/ui'

import { RegisterPage } from './RegisterPage'

function нарисовать() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <ThemeProvider>
        <ToastProvider>
          <MemoryRouter initialEntries={['/auth/register']}>
            <RegisterPage />
          </MemoryRouter>
        </ToastProvider>
      </ThemeProvider>
    </QueryClientProvider>,
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('страница регистрации', () => {
  it('спрашивает почту, ник и пароль', () => {
    нарисовать()

    expect(screen.getByRole('heading', { name: 'Регистрация' })).toBeInTheDocument()
    expect(screen.getByLabelText('Почта')).toBeInTheDocument()
    expect(screen.getByLabelText('Ник')).toBeInTheDocument()
    expect(screen.getByLabelText('Пароль')).toBeInTheDocument()
  })

  it('пустую форму в службу не пускает и говорит про ник', async () => {
    const user = userEvent.setup()
    нарисовать()

    await user.click(screen.getByRole('button', { name: 'Зарегистрироваться' }))

    // Сеть в этом тесте не подменена: любой запрос отсюда упал бы сам.
    expect(await screen.findByText('Придумайте ник.')).toBeInTheDocument()
  })

  it('короткий ник и ник с пробелом — разные сообщения', async () => {
    const user = userEvent.setup()
    нарисовать()

    await user.type(screen.getByLabelText('Ник'), 'и')
    await user.click(screen.getByRole('button', { name: 'Зарегистрироваться' }))
    expect(await screen.findByText('Ник короче двух знаков.')).toBeInTheDocument()

    await user.clear(screen.getByLabelText('Ник'))
    await user.type(screen.getByLabelText('Ник'), 'ник с пробелом')
    await user.click(screen.getByRole('button', { name: 'Зарегистрироваться' }))
    expect(
      await screen.findByText('В нике можно только буквы, цифры, «_» и «-».'),
    ).toBeInTheDocument()
  })

  it('годный ник уезжает в службу полем nickname', async () => {
    // Аргумент объявлен, чтобы `fetch.mock.calls[0][0]` имел тип: без него
    // `vi.fn` считает мок беспараметрическим и тело запроса не достать.
    const fetch = vi.fn((_input: Request | string | URL) =>
      Promise.resolve(
        new Response(JSON.stringify({ status: 'confirmation_sent' }), {
          status: 201,
          headers: { 'Content-Type': 'application/json' },
        }),
      ),
    )
    vi.stubGlobal('fetch', fetch)
    const user = userEvent.setup()
    нарисовать()

    await user.type(screen.getByLabelText('Почта'), 'kirisu@example.org')
    await user.type(screen.getByLabelText('Ник'), 'Курису_2026')
    await user.type(screen.getByLabelText('Пароль'), 'длинный-пароль-1')
    await user.click(screen.getByRole('button', { name: 'Зарегистрироваться' }))

    expect(await screen.findByText('Проверьте почту')).toBeInTheDocument()
    const запрос = fetch.mock.calls[0]?.[0] as Request
    expect(await запрос.clone().json()).toMatchObject({
      email: 'kirisu@example.org',
      nickname: 'Курису_2026',
    })
  })

  it('«ник занят» встаёт под полем ника, а не общей ошибкой', async () => {
    vi.stubGlobal('fetch', () =>
      Promise.resolve(
        new Response(
          JSON.stringify({
            error: {
              code: 'nickname_taken',
              message: 'This nickname is already taken',
              where: 'body.nickname',
            },
          }),
          { status: 409, headers: { 'Content-Type': 'application/json' } },
        ),
      ),
    )
    const user = userEvent.setup()
    нарисовать()

    await user.type(screen.getByLabelText('Почта'), 'kirisu@example.org')
    await user.type(screen.getByLabelText('Ник'), 'курису')
    await user.type(screen.getByLabelText('Пароль'), 'длинный-пароль-1')
    await user.click(screen.getByRole('button', { name: 'Зарегистрироваться' }))

    expect(
      await screen.findByText('Такой ник уже занят. Придумайте другой ник.'),
    ).toBeInTheDocument()
  })
})
