/**
 * data — запросы области «Отчёты» одним файлом.
 *
 * То же правило, что у проектов: адрес маршрута, форма ответа и список
 * ключей, которые сбрасываются после изменения, — одно знание, и живёт оно в
 * одном месте. Экраны зовут хуки, а не `api.GET`.
 *
 * Общее с проектами (карточка проекта, материалы, постановка задания, адрес
 * артефакта) берётся из `@/features/projects/data` и здесь не повторяется:
 * второй `useProject` рядом с первым — это два кэша одного проекта, которые
 * расходятся после переименования.
 */
import { useMutation, useQuery, useQueryClient, type UseQueryResult } from '@tanstack/react-query'

import { api, keys, unwrap } from '@/api'
import { useMe } from '@/api/hooks'

import type {
  ProjectTag,
  ProjectTagsBody,
  ProvidersBody,
  TagValue,
  ValueWritten,
  ValuesBody,
  VersionBody,
  VersionHead,
  VersionsBody,
} from './types'

// ── теги и значения ──────────────────────────────────────────────────────────

/**
 * Теги шаблона со состоянием заполнения — то, из чего сделана колонка слева.
 *
 * Именно этот маршрут, а не `project.keys`: карточка проекта отдаёт только
 * ключи, а колонке нужны метка, тип и «кто это написал».
 */
export function useProjectTags(projectId: string | undefined): UseQueryResult<ProjectTag[]> {
  return useQuery({
    queryKey: keys.reports.tags(projectId ?? ''),
    enabled: !!projectId,
    queryFn: async () => {
      const body = await unwrap<ProjectTagsBody>(
        api.GET('/api/projects/{project_id}/tags', {
          params: { path: { project_id: projectId as string } },
        }),
      )
      return body.tags
    },
  })
}

/**
 * Текущие значения всех тегов разом.
 *
 * Разом, а не по одному на выбранный тег: значений столько же, сколько тегов,
 * они короткие, и запрос на каждое переключение в списке — это мигание пустым
 * полем там, где ответ уже лежит в кэше.
 */
export function useProjectValues(
  projectId: string | undefined,
): UseQueryResult<Record<string, TagValue>> {
  return useQuery({
    queryKey: keys.reports.values(projectId ?? ''),
    enabled: !!projectId,
    queryFn: async () => {
      const body = await unwrap<ValuesBody>(
        api.GET('/api/projects/{project_id}/values', {
          params: { path: { project_id: projectId as string } },
        }),
      )
      return body.values
    },
  })
}

/**
 * Записать значение тега рукой человека.
 *
 * `source` службе не передаётся и передан быть не может: по этому маршруту
 * пишет человек, и пометку ставит служба (`projects/routes.py`). Очистка — это
 * тот же вызов с пустым текстом, а не отдельный маршрут: удаления значения у
 * службы нет, у тега есть история, и «очистить» означает «новая версия, в
 * которой пусто».
 */
export function useSetValue(projectId: string | undefined) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ key, value }: { key: string; value: TagValue }) =>
      unwrap<ValueWritten>(
        api.PUT('/api/projects/{project_id}/values/{key}', {
          params: { path: { project_id: projectId as string, key } },
          body: value as Record<string, never>,
        }),
      ),
    onSuccess: (_written, { key }) => {
      void qc.invalidateQueries({ queryKey: keys.reports.tags(projectId ?? '') })
      void qc.invalidateQueries({ queryKey: keys.reports.values(projectId ?? '') })
      void qc.invalidateQueries({ queryKey: keys.reports.versions(projectId ?? '', key) })
    },
  })
}

// ── версии значения ──────────────────────────────────────────────────────────

export function useTagVersions(
  projectId: string | undefined,
  key: string | undefined,
): UseQueryResult<VersionHead[]> {
  return useQuery({
    queryKey: keys.reports.versions(projectId ?? '', key ?? ''),
    enabled: !!projectId && !!key,
    queryFn: async () => {
      const body = await unwrap<VersionsBody>(
        api.GET('/api/projects/{project_id}/values/{key}/versions', {
          params: { path: { project_id: projectId as string, key: key as string } },
        }),
      )
      return body.versions
    },
    // Тег без единого значения отвечает 404 — это не беда, а «истории нет».
    retry: false,
  })
}

/** Одна версия целиком: шапка и само значение — то, что показывают перед «вернуть». */
export function useTagVersion(
  projectId: string | undefined,
  key: string | undefined,
  n: number | null,
): UseQueryResult<VersionBody> {
  return useQuery({
    queryKey: keys.reports.version(projectId ?? '', key ?? '', n ?? 0),
    enabled: !!projectId && !!key && n !== null,
    queryFn: () =>
      unwrap<VersionBody>(
        api.GET('/api/projects/{project_id}/values/{key}/versions/{n}', {
          params: { path: { project_id: projectId as string, key: key as string, n: n as number } },
        }),
      ),
  })
}

/**
 * Вернуть прошлую версию.
 *
 * Возврат ничего не удаляет: служба дописывает выбранное значение новой
 * версией, и в ответе номер БОЛЬШЕ того, к которому вернулись
 * (`versions/routes.py`). Поэтому список версий после возврата обязан
 * перечитаться — иначе человек увидит историю без своего же действия.
 */
export function useRollbackValue(projectId: string | undefined) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ key, n }: { key: string; n: number }) =>
      unwrap<{ key: string; version: VersionHead; restored_from: number }>(
        api.POST('/api/projects/{project_id}/values/{key}/rollback', {
          params: { path: { project_id: projectId as string, key } },
          body: { n },
        }),
      ),
    onSuccess: (_answer, { key }) => {
      void qc.invalidateQueries({ queryKey: keys.reports.tags(projectId ?? '') })
      void qc.invalidateQueries({ queryKey: keys.reports.values(projectId ?? '') })
      void qc.invalidateQueries({ queryKey: keys.reports.versions(projectId ?? '', key) })
    },
  })
}

// ── пресеты модели ───────────────────────────────────────────────────────────

/**
 * Пресеты модели и чем по каждому платить (`own` | `shared` | `none`).
 *
 * Без `key_source` выбор пресета был бы гаданием: свой ключ сайт видит, общий
 * ключ службы не виден ниоткуда, кроме этого ответа, и пресет, которым платить
 * нечем, даёт отказ вместо работы.
 */
export function useProviders(): UseQueryResult<ProvidersBody> {
  return useQuery({
    queryKey: keys.keyProviders,
    queryFn: () => unwrap<ProvidersBody>(api.GET('/api/keys/providers')),
    staleTime: 5 * 60_000,
  })
}

/**
 * Какой пресет предложить по умолчанию: сначала свой ключ, потом общий.
 *
 * Свой вперёд общего по той же причине, по которой их так же выбирает служба
 * (`keys/service.resolve_key`): человек завёл ключ затем, чтобы расход был
 * виден у него. `null` — платить нечем ни по одному пресету, и экран обязан
 * сказать это словами до нажатия, а не отказом после.
 */
export function defaultProvider(body: ProvidersBody | undefined): string | null {
  if (!body) return null
  const source = body.key_source ?? {}
  return (
    body.providers.find((p) => source[p] === 'own') ??
    body.providers.find((p) => source[p] === 'shared') ??
    null
  )
}

/**
 * Что подставить в выбор пресета: выбор человека, а если его нет — правило
 * сайта (`defaultProvider`).
 *
 * Выбор живёт в профиле (`me.default_endpoint`, раздел настроек «Агент и
 * модели»), а не в браузере: человек открывает работу и с ноутбука, и с чужой
 * машины, и умолчание, оставшееся в `localStorage` первой, на второй молча
 * исчезло бы.
 *
 * Хуком, а не аргументом `defaultProvider`: профиль читается тем же
 * `useMe`, что и вся оболочка, и просить каждый экран передать его сюда
 * значило бы четыре одинаковых строки в четырёх местах.
 */
export function useDefaultEndpoint(): string | null {
  const me = useMe()
  const providers = useProviders()
  return me.data?.default_endpoint ?? defaultProvider(providers.data)
}
