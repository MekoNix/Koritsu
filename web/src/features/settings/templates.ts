/**
 * templates — свои шаблоны отчётов (`/api/templates`).
 *
 * Отдельным файлом, а не строками в `api.ts`: шаблоны читает не только раздел
 * настроек, но и диалог «Новая работа» (`features/projects`), и импорт списка
 * ключей аккаунта ради одного списка шаблонов был бы связью ни за чем.
 *
 * **Тело загрузки собирается руками, а отправляет его тот же клиент.**
 * `multipart/form-data` с границей, которую ставит сам браузер, из типов
 * OpenAPI не собрать — поэтому `FormData` строится здесь и уезжает
 * `bodySerializer`'ом (тот же приём, что у создания работы в
 * `features/projects/data.ts`). Клиент при этом остаётся общим: он и
 * подставляет `X-CSRF-Token`, и уводит на вход по `401`, и разбирает отказ в
 * `ApiError` — своим `fetch` пришлось бы повторить всё это заново.
 */
import { useMutation, useQuery, useQueryClient, type UseQueryResult } from '@tanstack/react-query'

import { api, keys as cacheKeys, unwrap } from '@/api'
import { withBase } from '@/lib/basePath'

import type { ReportTemplate } from './types'

/**
 * Свои шаблоны, новые сверху.
 *
 * `enabled` — не украшение: диалог «Новая работа» смонтирован на экране работ
 * всегда, а спрашивать список шаблонов он должен только когда его открыли.
 */
export function useTemplates(enabled = true): UseQueryResult<ReportTemplate[]> {
  return useQuery({
    queryKey: cacheKeys.templates,
    queryFn: () => unwrap<ReportTemplate[]>(api.GET('/api/templates')),
    enabled,
  })
}

/**
 * Загрузить DOCX. Ответ — карточка с числом тегов: их считает служба тем же
 * разбором, которым строится манифест работы, поэтому «12 тегов» в списке и
 * «12 тегов» в заведённой по нему работе — одно и то же число.
 */
export function useUploadTemplate() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ file, name }: { file: File; name: string }) => {
      const форма = new FormData()
      форма.append('file', file, file.name)
      форма.append('name', name)
      return unwrap<ReportTemplate>(
        api.POST('/api/templates', {
          // Тело объявлено формой, и клиент требует его по схеме; настоящее
          // тело собирает `bodySerializer` (тот же приём, что у создания
          // работы в `features/projects/data.ts`).
          body: { file: file.name, name },
          bodySerializer: () => форма,
        }),
      )
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: cacheKeys.templates })
      // Место на томе изменилось — расход и лимиты показывают его же.
      void qc.invalidateQueries({ queryKey: cacheKeys.usage })
    },
  })
}

export function useDeleteTemplate() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (templateId: string) =>
      unwrap(
        api.DELETE('/api/templates/{template_id}', {
          params: { path: { template_id: templateId } },
        }),
      ),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: cacheKeys.templates })
      void qc.invalidateQueries({ queryKey: cacheKeys.usage })
    },
  })
}

/**
 * Адрес скачивания шаблона. Ссылкой, а не `fetch` с `blob:`: браузер сам
 * возьмёт имя файла из `Content-Disposition`, а cookie сессии уедет с
 * запросом, потому что адрес — тот же origin.
 *
 * `withBase`, а не строка от корня: без домена сайт живёт под случайным
 * префиксом пути, и ссылка от корня в бою вела бы в никуда.
 */
export function templateUrl(templateId: string): string {
  return withBase(`/api/templates/${encodeURIComponent(templateId)}/blob`)
}
