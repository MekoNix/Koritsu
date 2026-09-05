/**
 * Проверка многочастных запросов: заведение работы с шаблоном и загрузка файла.
 *
 * Это единственное место области, где тело запроса собирается руками
 * (`FormData` через `bodySerializer`), а типы, снятые с OpenAPI, описывают файл
 * строкой. Ошибка здесь не видна ни компилятору, ни линтеру: служба ответит
 * `400 no_file` или `422`, и то и другое человек прочтёт как «почему-то не
 * грузится».
 *
 * Проверяются три вещи: адрес и метод, тип тела (`multipart/form-data` с
 * границей, а не подставленный клиентом `application/json`) и состав полей.
 *
 * **Состав полей смотрится слежкой за `FormData.append`, а не чтением тела
 * запроса.** Тело `Request` в jsdom прочитать нельзя: поток undici там не
 * дочитывается и `request.formData()` виснет до таймаута теста. Слежка даёт то
 * же знание — какие поля и под какими именами уехали, — и не зависит от того,
 * чьи потоки подложены под окружение.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useCreateProject, useUploadMaterial } from './data'

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}

let fetchSpy: ReturnType<typeof vi.fn>
let appendSpy: ReturnType<typeof vi.spyOn>

/** Имена полей, ушедших в многочастное тело, в порядке добавления. */
function поля(): string[] {
  return appendSpy.mock.calls.map((call) => String(call[0]))
}

/** Первый ушедший запрос. Отдельной функцией — ради проверки «а был ли он». */
function запрос(): Request {
  const call = fetchSpy.mock.calls[0]
  if (!call) throw new Error('запрос в службу не ушёл вовсе')
  return call[0] as Request
}

/** Файл, положенный в поле с таким именем. */
function файл(имя: string): File | undefined {
  const call = appendSpy.mock.calls.find((c) => c[0] === имя)
  return call?.[1] instanceof File ? (call[1] as File) : undefined
}

beforeEach(() => {
  document.cookie = 'koritsu_csrf=token-abc'
  fetchSpy = vi.fn()
  vi.stubGlobal('fetch', fetchSpy)
  appendSpy = vi.spyOn(FormData.prototype, 'append')
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  document.cookie = 'koritsu_csrf=; max-age=0'
})

describe('заведение работы', () => {
  it('шлёт многочастное тело: пространство, имя и файл шаблона', async () => {
    fetchSpy.mockResolvedValue(json({ id: 'p-1', name: 'Лаба' }))
    const { result } = renderHook(() => useCreateProject(), { wrapper })

    const project = await result.current.mutateAsync({
      workspaceId: 'ws-1',
      name: 'Лаба',
      template: new File(['docx'], 'шаблон.docx'),
    })
    expect(project.id).toBe('p-1')

    const request = запрос()
    expect(request.method).toBe('POST')
    expect(new URL(request.url).pathname).toBe('/api/projects')
    // Тип многочастного тела ставит сам браузер — вместе с границей.
    expect(request.headers.get('Content-Type')).toMatch(/^multipart\/form-data; boundary=/)

    expect(поля()).toEqual(['workspace_id', 'name', 'template'])
    expect(файл('template')?.name).toBe('шаблон.docx')
  })

  it('без шаблона поля template в теле нет вовсе', async () => {
    fetchSpy.mockResolvedValue(json({ id: 'p-2', name: 'Без шаблона' }))
    const { result } = renderHook(() => useCreateProject(), { wrapper })

    await result.current.mutateAsync({ workspaceId: 'ws-1', name: 'Без шаблона' })

    expect(поля()).toEqual(['workspace_id', 'name'])
  })
})

describe('загрузка материала', () => {
  it('кладёт файл в поле `file` по адресу проекта и берёт из ответа 202 pending_id', async () => {
    fetchSpy.mockResolvedValue(json({ job: { id: 'j-1' }, pending_id: 'abc' }, 202))
    const { result } = renderHook(() => useUploadMaterial(), { wrapper })

    const accepted = await result.current.mutateAsync({
      projectId: 'p-1',
      file: new File(['%PDF'], 'методичка.pdf'),
    })
    expect(accepted.pending_id).toBe('abc')
    expect(accepted.job.id).toBe('j-1')

    const request = запрос()
    expect(new URL(request.url).pathname).toBe('/api/projects/p-1/materials')
    // Заголовок CSRF ставит клиент: без него служба отказала бы на каждом файле.
    expect(request.headers.get('X-CSRF-Token')).toBe('token-abc')

    expect(поля()).toEqual(['file'])
    expect(файл('file')?.name).toBe('методичка.pdf')
  })
})
