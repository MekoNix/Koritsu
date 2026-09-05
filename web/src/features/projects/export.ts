/**
 * export — выгрузка работы файлом: какие форматы бывают и как их заказать.
 *
 *     Пунктов два, потому что заданий два
 *     -----------------------------------
 *
 * `POST /api/projects/{id}/export` (`packages/api/export`) умеет ровно одно:
 * сложить **архив** — оригиналы материалов, всё построенное службой,
 * `values.json`, `blocks.json` и опись — и положить его артефактом проекта.
 * Ни DOCX, ни PDF он не строит и о шаблоне не знает.
 *
 * Word и PDF делает другое задание — `build` (`runs/handlers/build.py`), и
 * делает их **парой за один прогон**: PDF получается из DOCX тем же вызовом
 * LibreOffice.
 *
 * Раньше пунктов было три — «Word», «PDF» и «Архив», — и первые два вели в
 * одно и то же задание с одной ценой. Выбор, за которым ничего не стоит, —
 * это не выбор, а вопрос, на который человек обязан отвечать зря: что бы он ни
 * нажал, приезжали оба файла. Поэтому пунктов два — «Документ (Word и PDF)» и
 * «Архив», по пункту на задание.
 *
 * **Скачивание — не отсюда.** Готовый файл забирается по адресу артефакта
 * (`artifactUrl` в `data.ts`), и ссылка на него приезжает двумя путями:
 * в результате задания (если диалог ещё открыт) и в уведомлении колокольчика
 * (`data.artifacts`, `packages/api/notifications/service.py`): экспорт — кнопка
 * в проекте, задание, скачивание из уведомления.
 */
import { useMutation, useQueryClient } from '@tanstack/react-query'

import { api, keys, unwrap } from '@/api'

import type { Enqueued } from './data'

/** Виды заданий, которыми делается выгрузка (`packages/api/jobs/registry.py`). */
export const EXPORT = 'export'
export const BUILD = 'build'

/** Что человек выбирает в диалоге. По пункту на задание. */
export type ExportFormat = 'document' | 'archive'

export type ФорматВыгрузки = {
  id: ExportFormat
  /** Вид задания, которым это делается: от него цена и путь постановки. */
  job: typeof EXPORT | typeof BUILD
  /** Нужен ли проекту шаблон: без него `build` собирать нечего. */
  needsTemplate: boolean
}

const АРХИВ: ФорматВыгрузки = { id: 'archive', job: EXPORT, needsTemplate: false }

export const ФОРМАТЫ: ФорматВыгрузки[] = [
  { id: 'document', job: BUILD, needsTemplate: true },
  АРХИВ,
]

/** Строка таблицы по выбору человека. Неизвестное имя — архив: он есть всегда. */
export function формат(id: ExportFormat): ФорматВыгрузки {
  return ФОРМАТЫ.find((ф) => ф.id === id) ?? АРХИВ
}

/**
 * Поставить выгрузку архива. → карточка задания.
 *
 * Свой маршрут, а не `POST /api/jobs`, потому что он у службы есть и делает
 * ровно это (`export/routes.py`): проверка роли `editor`, месячный лимит и
 * постановка одним вызовом. Ставить то же самое общим маршрутом значило бы
 * обойти дверь, заведённую для этого действия.
 */
export function useExportProject() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (projectId: string) =>
      unwrap<{ job: Enqueued }>(
        api.POST('/api/projects/{project_id}/export', {
          params: { path: { project_id: projectId } },
        }),
      ).then((тело) => тело.job),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.jobs.all })
      void qc.invalidateQueries({ queryKey: keys.usage })
    },
  })
}

/**
 * Артефакты законченного задания: `{вид: идентификатор}`.
 *
 * Два договора, потому что задания два: `export` кладёт один архив
 * (`result.artifact`), `build` — пару выходов (`result.artifacts`). Тот же
 * разбор делает служба, заводя уведомление (`notifications.service.артефакты`),
 * и оба обязаны отвечать одинаково — иначе ссылка в диалоге и ссылка в
 * колокольчике вели бы в разные места.
 */
export function jobArtifacts(result: unknown): Record<string, string> {
  const итог = (result ?? {}) as { artifact?: unknown; artifacts?: unknown }
  const найдено: Record<string, string> = {}
  if (typeof итог.artifact === 'string' && итог.artifact) найдено.file = итог.artifact
  if (итог.artifacts && typeof итог.artifacts === 'object') {
    for (const [вид, art] of Object.entries(итог.artifacts as Record<string, unknown>)) {
      if (typeof art === 'string' && art) найдено[вид] = art
    }
  }
  return найдено
}

/**
 * Ссылки скачивания из уведомления — то, чем колокольчик показывает «готово».
 *
 * `data.artifacts` кладёт служба при закрытии задания; `project_id` там же,
 * потому что артефакт скачивается маршрутом проекта. Уведомление без файлов
 * (упавшее задание, разбор материала) даёт пустой список — и это не ошибка.
 */
export function notificationArtifacts(data: unknown): { kind: string; artifactId: string }[] {
  const тело = (data ?? {}) as { artifacts?: unknown }
  if (!тело.artifacts || typeof тело.artifacts !== 'object') return []
  return Object.entries(тело.artifacts as Record<string, unknown>)
    .filter(([, art]) => typeof art === 'string' && art)
    .map(([kind, art]) => ({ kind, artifactId: art as string }))
}
