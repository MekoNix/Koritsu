/**
 * data — все запросы области «Проекты» одним файлом.
 *
 * Экраны не зовут `api.GET` сами: адрес маршрута, форма ответа и то, какие
 * ключи кэша сбрасываются после изменения, — это одно знание, и жить оно
 * должно в одном месте. Иначе «после переименования список не обновился»
 * чинится в трёх компонентах по очереди.
 *
 * Многочастные тела (`multipart/form-data`) собираются здесь же: служба
 * принимает шаблон проекта и материал телом запроса, а типы, снятые с OpenAPI,
 * описывают файл как строку (`format: binary`). Поэтому тело уезжает готовым
 * `FormData` через `bodySerializer` — openapi-fetch в этом случае сам не ставит
 * `Content-Type`, и границу многочастного тела расставляет браузер.
 */
import { useMutation, useQuery, useQueryClient, type UseQueryResult } from '@tanstack/react-query'

import { api, keys, unwrap } from '@/api'

import type {
  Material,
  MaterialRemoved,
  MaterialText,
  Project,
  PendingMaterial,
  UploadAccepted,
  Workspace,
} from './types'

/** Вид задания «разобрать принесённый файл» (`packages/api/jobs/registry.py`). */
export const PARSE = 'parse'
/** Вид задания «собрать документ из значений проекта». */
export const BUILD = 'build'

// ── пространства ─────────────────────────────────────────────────────────────

/**
 * Личное пространство человека. Ночь 1 работает только с ним: участники и
 * общие пространства — ночь 2 (решение владельца), и заводить переключатель
 * ради одного значения незачем.
 */
export function usePersonalWorkspace(): UseQueryResult<Workspace> {
  return useQuery({
    queryKey: keys.workspaces.personal,
    queryFn: () => unwrap<Workspace>(api.GET('/api/workspaces/personal')),
    staleTime: 5 * 60_000,
  })
}

/**
 * Одно пространство — ради роли спрашивающего: по ней страница проекта решает,
 * показывать ли приёмник файлов и кнопки правки. Роль приезжает в карточке
 * пространства (`карточка(ws, role)`), поэтому второго запроса за правами нет.
 */
export function useWorkspace(workspaceId: string | undefined): UseQueryResult<Workspace> {
  return useQuery({
    queryKey: [...keys.workspaces.all, workspaceId ?? ''],
    enabled: !!workspaceId,
    queryFn: () =>
      unwrap<Workspace>(
        api.GET('/api/workspaces/{workspace_id}', {
          params: { path: { workspace_id: workspaceId as string } },
        }),
      ),
    staleTime: 5 * 60_000,
  })
}

/** Роли, которым позволено менять содержимое (`workspaces/service.py`). */
const РЕДАКТОРЫ = new Set(['owner', 'editor'])

export function canEditWorkspace(role: string | undefined): boolean {
  return !!role && РЕДАКТОРЫ.has(role)
}

// ── проекты ──────────────────────────────────────────────────────────────────

export function useProjects(
  workspaceId: string | undefined,
  trash = false,
): UseQueryResult<Project[]> {
  return useQuery({
    queryKey: keys.projects.list(workspaceId ?? '', trash),
    enabled: !!workspaceId,
    queryFn: async () => {
      const body = await unwrap<{ projects: Project[] }>(
        api.GET('/api/projects', {
          params: { query: { workspace_id: workspaceId as string, trash } },
        }),
      )
      return body.projects
    },
  })
}

export function useProject(projectId: string | undefined): UseQueryResult<Project> {
  return useQuery({
    queryKey: keys.projects.one(projectId ?? ''),
    enabled: !!projectId,
    queryFn: () =>
      unwrap<Project>(
        api.GET('/api/projects/{project_id}', {
          params: { path: { project_id: projectId as string } },
        }),
      ),
  })
}

export type CreateProjectInput = {
  workspaceId: string
  name: string
  /** Шаблон DOCX. Без него служба строит документ с нуля — это законный случай. */
  template?: File | null
}

export function useCreateProject() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ workspaceId, name, template }: CreateProjectInput) => {
      const form = new FormData()
      form.append('workspace_id', workspaceId)
      form.append('name', name)
      if (template) form.append('template', template, template.name)
      return unwrap<Project>(
        api.POST('/api/projects', {
          body: { workspace_id: workspaceId, name },
          bodySerializer: () => form,
        }),
      )
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.projects.all }),
  })
}

export function useRenameProject() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, name }: { id: string; name: string }) =>
      unwrap<Project>(
        api.PATCH('/api/projects/{project_id}', {
          params: { path: { project_id: id } },
          body: { name },
        }),
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.projects.all }),
  })
}

export function useTrashProject() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) =>
      unwrap<Project>(
        api.DELETE('/api/projects/{project_id}', { params: { path: { project_id: id } } }),
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.projects.all }),
  })
}

export function useRestoreProject() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) =>
      unwrap<Project>(
        api.POST('/api/projects/{project_id}/restore', { params: { path: { project_id: id } } }),
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.projects.all }),
  })
}

// ── материалы ────────────────────────────────────────────────────────────────

export function useMaterials(projectId: string | undefined): UseQueryResult<Material[]> {
  return useQuery({
    queryKey: keys.projects.materials(projectId ?? ''),
    enabled: !!projectId,
    queryFn: () =>
      unwrap<Material[]>(
        api.GET('/api/projects/{project_id}/materials', {
          params: { path: { project_id: projectId as string } },
        }),
      ),
  })
}

/**
 * Принятые, но ещё не разобранные файлы. Нужны затем, что опись показывает
 * только разобранное: без этого списка загруженный файл исчезает на десяток
 * секунд, и человек грузит его второй раз.
 */
export function usePendingMaterials(
  projectId: string | undefined,
): UseQueryResult<PendingMaterial[]> {
  return useQuery({
    queryKey: keys.projects.pending(projectId ?? ''),
    enabled: !!projectId,
    queryFn: () =>
      unwrap<PendingMaterial[]>(
        api.GET('/api/projects/{project_id}/materials/pending', {
          params: { path: { project_id: projectId as string } },
        }),
      ),
  })
}

/** Кусок содержимого материала — показывается в раскрытии карточки. */
export function useMaterialText(
  projectId: string | undefined,
  materialId: string | undefined,
  enabled: boolean,
): UseQueryResult<MaterialText> {
  return useQuery({
    queryKey: keys.projects.materialText(projectId ?? '', materialId ?? ''),
    enabled: enabled && !!projectId && !!materialId,
    queryFn: () =>
      unwrap<MaterialText>(
        api.GET('/api/projects/{project_id}/materials/{material_id}/text', {
          params: {
            path: { project_id: projectId as string, material_id: materialId as string },
            // Первые страницы: раскрытие карточки — это «что там внутри», а не
            // чтение файла целиком. Границы включительные, нумерация с единицы.
            query: { start: 1, end: 3 },
          },
        }),
      ),
  })
}

/**
 * Загрузка одного файла. Служба отвечает `202`: байты приняты, разбор уехал в
 * очередь, и материала в этот момент ещё нет. Поэтому здесь нет ни `onSuccess`
 * со сбросом описи, ни ожидания карточки — за концом разбора следит
 * `useJobStream` в `MaterialUploads`.
 */
export function useUploadMaterial() {
  return useMutation({
    mutationFn: ({ projectId, file }: { projectId: string; file: File }) => {
      const form = new FormData()
      form.append('file', file, file.name)
      return unwrap<UploadAccepted>(
        api.POST('/api/projects/{project_id}/materials', {
          params: { path: { project_id: projectId } },
          body: { file: '' },
          bodySerializer: () => form,
        }),
      )
    },
  })
}

export function useDeleteMaterial() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ projectId, materialId }: { projectId: string; materialId: string }) =>
      unwrap<MaterialRemoved>(
        api.DELETE('/api/projects/{project_id}/materials/{material_id}', {
          params: { path: { project_id: projectId, material_id: materialId } },
        }),
      ),
    onSuccess: (_data, { projectId }) => {
      void qc.invalidateQueries({ queryKey: keys.projects.materials(projectId) })
      void qc.invalidateQueries({ queryKey: keys.projects.one(projectId) })
    },
  })
}

/** Адрес скачивания оригинала. Ссылкой, а не `fetch`: качает браузер. */
export function materialBlobUrl(projectId: string, materialId: string): string {
  return `/api/projects/${encodeURIComponent(projectId)}/materials/${encodeURIComponent(materialId)}/blob`
}

/** Адрес скачивания артефакта проекта (собранный PDF, DOCX, выгрузка). */
export function artifactUrl(projectId: string, artifactId: string): string {
  return `/api/projects/${encodeURIComponent(projectId)}/artifacts/${encodeURIComponent(artifactId)}`
}

// ── задания ──────────────────────────────────────────────────────────────────

export type Enqueued = { id: string; kind: string; status: string; [k: string]: unknown }

/** Поставить задание в очередь. Ответ — карточка, работа идёт в воркере. */
export function useEnqueueJob() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({
      kind,
      projectId,
      payload,
    }: {
      kind: string
      projectId?: string
      payload?: Record<string, unknown>
    }) =>
      unwrap<Enqueued>(
        api.POST('/api/jobs', {
          body: { kind, project_id: projectId ?? null, payload: payload ?? {} },
        }),
      ),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.jobs.all })
      void qc.invalidateQueries({ queryKey: keys.usage })
    },
  })
}
