/**
 * Проверка раздела «Шаблоны отчётов» на подменённых ответах службы.
 *
 * Смысл теста — в двух вещах, которые ломаются молча:
 *
 * * в строке видно **число тегов**. По нему шаблон и узнают, когда имена
 *   похожи, и приезжает оно из службы, а не считается здесь;
 * * загрузка уходит формой (`multipart`) на `POST /api/templates` и несёт
 *   написанное имя. Собирается тело руками, поэтому забыть поле легко, а
 *   заметить пропажу — нет: служба возьмёт имя файла и всё будет «работать».
 *
 * Служба подменяется на уровне `fetch`, а не хуков: так проверяется и адрес, и
 * то, что клиент разбирает ответ (тот же приём, что в `ProjectsListPage.test`).
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ThemeProvider } from '@/theme'
import { ToastProvider } from '@/ui'

import { TemplatesSection } from './TemplatesSection'

const ШАБЛОН = {
  id: 't-1',
  name: 'ГОСТ 2026',
  bytes: 36658,
  tags: 12,
  sha256: '0a1b2c3d4e5f6071',
  created_at: '2026-09-04T10:00:00+00:00',
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

/** Служба со списком шаблонов; загрузка отвечает карточкой. */
function служба(список: unknown[]) {
  return vi.fn((request: Request) => {
    const url = new URL(request.url)
    if (url.pathname !== '/api/templates') {
      throw new Error(`тест не ждал запроса ${url.pathname}`)
    }
    if (request.method === 'POST') return Promise.resolve(json(ШАБЛОН, 201))
    return Promise.resolve(json(список))
  })
}

function нарисовать() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <ThemeProvider>
        <ToastProvider>
          <TemplatesSection />
        </ToastProvider>
      </ThemeProvider>
    </QueryClientProvider>,
  )
}

/**
 * Формы, собранные экраном за тест. Ловушкой на `FormData`, потому что прочитать
 * тело у готового запроса в jsdom нельзя (см. ниже, в самом тесте).
 */
let формы: FormData[] = []

beforeEach(() => {
  document.cookie = 'koritsu_csrf=token-abc'
  формы = []
  const Настоящая = globalThis.FormData
  class Ловушка extends Настоящая {
    constructor(...аргументы: ConstructorParameters<typeof FormData>) {
      super(...аргументы)
      формы.push(this)
    }
  }
  vi.stubGlobal('FormData', Ловушка)
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('шаблоны отчётов', () => {
  it('показывает шаблон с числом тегов и размером', async () => {
    vi.stubGlobal('fetch', служба([ШАБЛОН]))
    нарисовать()

    expect(await screen.findByText('ГОСТ 2026')).toBeInTheDocument()
    expect(screen.getByText('тегов: 12')).toBeInTheDocument()
    expect(screen.getByText('36.7 КБ')).toBeInTheDocument()
  })

  it('пустой список — приглашение загрузить, а не белое поле', async () => {
    vi.stubGlobal('fetch', служба([]))
    нарисовать()

    expect(await screen.findByText('Шаблонов пока нет')).toBeInTheDocument()
  })

  it('загрузка уходит формой и несёт написанное имя', async () => {
    const запросы = служба([])
    vi.stubGlobal('fetch', запросы)
    const человек = userEvent.setup()
    нарисовать()

    await screen.findByText('Шаблонов пока нет')

    const файл = new File(['docx'], 'ГОСТ.docx', {
      type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    })
    await человек.upload(screen.getByLabelText(/Перетащите DOCX/), файл)
    await человек.type(screen.getByLabelText('Название'), 'ГОСТ 2026')
    await человек.click(screen.getByRole('button', { name: 'Загрузить шаблон' }))

    const отправка = запросы.mock.calls
      .map(([request]) => request as Request)
      .find((request) => request.method === 'POST')
    expect(отправка).toBeDefined()

    // Тело смотрим у самой формы, а не у запроса: `Request.formData()` и
    // `Request.text()` на multipart в jsdom не возвращаются вовсе (тело —
    // поток, разбирать который там нечем), и тест висел бы до таймаута.
    const форма = формы[0]
    expect(форма).toBeDefined()
    expect(форма?.get('name')).toBe('ГОСТ 2026')
    expect((форма?.get('file') as File).name).toBe('ГОСТ.docx')
  })
})
