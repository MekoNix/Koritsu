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
import { withBase } from '@/lib/basePath'

import type {
  Material,
  MaterialRemoved,
  MaterialText,
  PendingMaterial,
  Project,
  ProjectRun,
  ReportTemplate,
  RunSort,
  UploadAccepted,
  Workspace,
} from './types'

/**
 * Сколько ответ считается свежим там, где об изменении сообщает поток событий.
 *
 * Материалы, разбираемые файлы и значения тегов меняются заданиями, а конец
 * задания гасит их ключи явно (обработчики потока на экранах). Значит,
 * перезапрашивать их при каждом возврате на экран не нужно вовсе: это плата за
 * переход, а не свежесть. Число одно на все три, потому что довод у них один.
 */
export const СВЕЖЕСТЬ_ПОД_ПОТОКОМ = 5 * 60_000

/** Вид задания «разобрать принесённый файл» (`packages/api/jobs/registry.py`). */
export const PARSE = 'parse'
/** Вид задания «собрать документ из значений проекта». */
export const BUILD = 'build'

// ── пространства ─────────────────────────────────────────────────────────────

/** Личное пространство человека (`GET /api/workspaces/personal`). */
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
  /** Шаблон DOCX файлом. Без него служба строит документ с нуля — законный случай. */
  template?: File | null
  /**
   * Свой сохранённый шаблон (`/api/templates`) вместо файла. Служба копирует
   * его байты в работу, поэтому удаление шаблона потом её не ломает.
   *
   * Оба сразу служба не принимает (`400 bad_template`): молча выбранный за
   * человека шаблон — это чужой ГОСТ в готовой работе. Диалог поэтому даёт
   * выбрать одно из двух, а не оба.
   */
  templateId?: string | null
  /**
   * Каким модулем эта работа делается. Пусто — не назначен: работу заводят
   * раньше, чем решают, чем её делать, и главная модуля потом отбирает свои
   * работы по этому полю.
   */
  module?: string
}

export function useCreateProject() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ workspaceId, name, template, templateId, module }: CreateProjectInput) => {
      const form = new FormData()
      form.append('workspace_id', workspaceId)
      form.append('name', name)
      form.append('module', module ?? '')
      if (template) form.append('template', template, template.name)
      else if (templateId) form.append('template_id', templateId)
      return unwrap<Project>(
        api.POST('/api/projects', {
          body: { workspace_id: workspaceId, name, module: module ?? '' },
          bodySerializer: () => form,
        }),
      )
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.projects.all }),
  })
}

/**
 * Правка работы: имя, модуль или и то, и другое. Оба поля необязательны —
 * служба меняет только присланное, поэтому смена модуля не переписывает имя
 * тем, что лежало в форме на момент её открытия.
 */
export function useRenameProject() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, name, module }: { id: string; name?: string; module?: string }) =>
      unwrap<Project>(
        api.PATCH('/api/projects/{project_id}', {
          params: { path: { project_id: id } },
          body: {
            ...(name === undefined ? {} : { name }),
            ...(module === undefined ? {} : { module }),
          },
        }),
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.projects.all }),
  })
}

// ── журнал запусков ──────────────────────────────────────────────────────────

/**
 * Что в работе делали: какой модуль, когда, как называется.
 *
 * Порядок считает служба, а не браузер: список растёт, и сортировать его на
 * клиенте значило бы сортировать ту часть, которую успели выкачать.
 */
export function useProjectRuns(
  projectId: string | undefined,
  sort: RunSort = 'new',
): UseQueryResult<ProjectRun[]> {
  return useQuery({
    queryKey: keys.projects.runs(projectId ?? '', sort),
    enabled: !!projectId,
    queryFn: () =>
      unwrap<ProjectRun[]>(
        api.GET('/api/projects/{project_id}/runs', {
          params: { path: { project_id: projectId as string }, query: { sort } },
        }),
      ),
  })
}

/**
 * Записать запуск. Отчёт и решение заводятся отдельно и привязываются к
 * текущей работе — этой записью и привязываются.
 *
 * Имя не передаётся, когда его не дали: имя по умолчанию рисует сайт из модуля
 * и номера (`n`), который считает служба.
 */
export function useCreateProjectRun() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({
      projectId,
      module,
      name,
      artifactId,
    }: {
      projectId: string
      module: string
      name?: string
      artifactId?: string
    }) =>
      unwrap<ProjectRun>(
        api.POST('/api/projects/{project_id}/runs', {
          params: { path: { project_id: projectId } },
          body: { module, name: name ?? '', artifact_id: artifactId ?? null },
        }),
      ),
    onSuccess: (_data, { projectId }) =>
      qc.invalidateQueries({ queryKey: keys.projects.one(projectId) }),
  })
}

/**
 * Переименовать запуск — так переименовывается схема, отчёт или решение.
 *
 * Имя правится в одном месте на всё: запись журнала и есть та вещь, которую
 * человек видит списком в модуле, строкой в «Что в работе» и заголовком на
 * экране схемы. Второе хранилище имени рядом разошлось бы с этим на первом же
 * переименовании.
 *
 * Пустое имя — не отказ, а возврат к имени по умолчанию: его рисует сайт из
 * модуля и номера (`runTitle`), и стереть своё название человек должен уметь
 * тем же полем, которым он его давал.
 */
export function useRenameProjectRun() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ projectId, runId, name }: { projectId: string; runId: string; name: string }) =>
      unwrap<ProjectRun>(
        api.PATCH('/api/projects/{project_id}/runs/{run_id}', {
          params: { path: { project_id: projectId, run_id: runId } },
          body: { name },
        }),
      ),
    onSuccess: (_data, { projectId }) => {
      void qc.invalidateQueries({ queryKey: keys.projects.one(projectId) })
      // Схемы — те же записи журнала, только показанные модулем: списки схем
      // обязаны узнать новое имя тем же действием, иначе оно появится в них
      // только после перезагрузки страницы. Отчёты — такие же записи, и их
      // лента по пространству лежит своим ключом.
      void qc.invalidateQueries({ queryKey: keys.diagrams.all })
      void qc.invalidateQueries({ queryKey: keys.projects.workspaceReportsAll })
    },
  })
}

/**
 * Убрать запись журнала — так удаляется схема из работы.
 *
 * Артефакт при этом остаётся на томе: он адресуется содержимым и может стоять
 * значением тега (`packages/api/projects/runs.py`).
 */
export function useDeleteProjectRun() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ projectId, runId }: { projectId: string; runId: string }) =>
      unwrap<void>(
        api.DELETE('/api/projects/{project_id}/runs/{run_id}', {
          params: { path: { project_id: projectId, run_id: runId } },
        }),
      ),
    onSuccess: (_data, { projectId }) =>
      qc.invalidateQueries({ queryKey: keys.projects.one(projectId) }),
  })
}

// ── шаблоны работы ───────────────────────────────────────────────────────────

/**
 * Бланки, приложенные к работе: у неё их бывает несколько.
 *
 * `report` — какой отчёт работы спрашивает. Список приложенных от отчёта не
 * зависит, а вот пометка «по этому бланку собирается» зависит: отчётов в работе
 * несколько, и каждый собирается своим. Без отчёта спрашивают из мест, где
 * документ у работы один (карточка работы).
 */
export function useProjectTemplates(
  projectId: string | undefined,
  report = '',
): UseQueryResult<ReportTemplate[]> {
  return useQuery({
    queryKey: keys.projects.projectTemplates(projectId ?? '', report),
    enabled: !!projectId,
    queryFn: () =>
      unwrap<ReportTemplate[]>(
        api.GET('/api/projects/{project_id}/templates', {
          params: { path: { project_id: projectId as string }, query: { report } },
        }),
      ),
  })
}

/**
 * Приложить бланк к работе: файлом или идентификатором своего сохранённого.
 * Оба сразу служба не принимает — тот же довод, что при создании работы.
 */
export function useAttachProjectTemplate() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({
      projectId,
      file,
      templateId,
      name,
    }: {
      projectId: string
      file?: File | null
      templateId?: string | null
      name?: string
    }) => {
      const form = new FormData()
      if (file) form.append('file', file, file.name)
      else if (templateId) form.append('template_id', templateId)
      if (name) form.append('name', name)
      return unwrap<ReportTemplate>(
        api.POST('/api/projects/{project_id}/templates', {
          params: { path: { project_id: projectId } },
          body: { file: '' },
          bodySerializer: () => form,
        }),
      )
    },
    onSuccess: (_data, { projectId }) => {
      void qc.invalidateQueries({ queryKey: keys.projects.projectTemplatesAll(projectId) })
      void qc.invalidateQueries({ queryKey: keys.templates })
    },
  })
}

/** Убрать бланк из работы. Файл остаётся на полке у того, кто его загрузил. */
export function useDetachProjectTemplate() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ projectId, templateId }: { projectId: string; templateId: string }) =>
      unwrap<void>(
        api.DELETE('/api/projects/{project_id}/templates/{template_id}', {
          params: { path: { project_id: projectId, template_id: templateId } },
        }),
      ),
    onSuccess: (_data, { projectId }) =>
      qc.invalidateQueries({ queryKey: keys.projects.projectTemplatesAll(projectId) }),
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
    // Опись меняется только концом разбора, и тот гасит этот ключ сам
    // (`MaterialsPanel.finished`, `KadaiWorkPage`). Нулевая свежесть означала
    // бы перезапрос при каждом возврате на экран ради списка, который не мог
    // измениться, — цена перехода между экранами, а не свежесть данных.
    staleTime: СВЕЖЕСТЬ_ПОД_ПОТОКОМ,
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
    // Тот же довод, что у описи: список разбираемых меняют загрузка и конец
    // задания, и оба гасят ключ сами.
    staleTime: СВЕЖЕСТЬ_ПОД_ПОТОКОМ,
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
    mutationFn: ({
      projectId,
      file,
      runId,
    }: {
      projectId: string
      file: File
      /**
       * Решение, в папку контекста которого ложится файл. Пусто — файл общий
       * для работы: его видят отчёты и схемы, как раньше. Приписка уезжает той
       * же формой, что и байты: «файл принят, но неизвестно куда» — состояние,
       * которого лучше не заводить.
       */
      runId?: string
    }) => {
      const form = new FormData()
      form.append('file', file, file.name)
      if (runId) form.append('run_id', runId)
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
  return withBase(
    `/api/projects/${encodeURIComponent(projectId)}/materials/${encodeURIComponent(materialId)}/blob`,
  )
}

/**
 * Адрес скачивания артефакта проекта (собранный PDF, DOCX, выгрузка).
 *
 * `inline` — просьба показать файл, а не скачать: служба меняет
 * `Content-Disposition` на `inline` (`packages/api/modules/artifacts.py`), и
 * только с ним браузер соглашается нарисовать PDF в `<embed>`. Показывать она
 * умеет PDF и растровые картинки; всё остальное с этим параметром скачивается
 * как обычно, поэтому ставить его на ссылку «скачать» бессмысленно и вредно.
 */
export function artifactUrl(
  projectId: string,
  artifactId: string,
  { inline = false }: { inline?: boolean } = {},
): string {
  const адрес = withBase(
    `/api/projects/${encodeURIComponent(projectId)}/artifacts/${encodeURIComponent(artifactId)}`,
  )
  return inline ? `${адрес}?inline=1` : адрес
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
