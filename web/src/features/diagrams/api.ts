/**
 * api — запросы области схем. Экраны не зовут `unwrap` сами.
 *
 * Маршрутов у двух модулей семь, и делятся они на две ровные половины:
 * предпросмотр (без проекта, ничего не пишет на том, ограничен темпом) и
 * постройка в проект (роль editor, XML ложится артефактом). Здесь они собраны
 * рядом, чтобы разница между ними была видна одним взглядом, а не по адресу в
 * пяти файлах.
 *
 * Скачивание артефакта идёт мимо `openapi-fetch`: маршрут отдаёт байты с
 * `Content-Disposition`, а клиент по документу OpenAPI ждёт JSON. Поэтому
 * `fetch` руками — с той же cookie-сессией и тем же origin.
 */
import { api, unwrap } from '@/api'

import type {
  BuiltOut,
  DiagramValue,
  FlowchartMode,
  Lang,
  PreviewOut,
  ProjectCard,
  SavedDiagram,
  UmlKind,
  WorkspaceCard,
} from './types'

/** Исходник для UML: имя нужно замечаниям разбора, путём оно не является. */
export type NamedSource = { name: string; source: string }

// ── перечни строителя ────────────────────────────────────────────────────────

export function fetchModes(): Promise<FlowchartMode[]> {
  return unwrap<FlowchartMode[]>(api.GET('/api/flowcharts/modes'))
}

export function fetchThemes(): Promise<string[]> {
  return unwrap<string[]>(api.GET('/api/uml/themes'))
}

// ── предпросмотр: без проекта и без записи на том ────────────────────────────

export function previewFlowchart(body: {
  source: string
  lang: Lang
  mode: string
}): Promise<PreviewOut> {
  return unwrap<PreviewOut>(api.POST('/api/flowcharts/preview', { body }))
}

export function previewUml(
  kind: UmlKind,
  body: { sources: NamedSource[]; lang: Lang; theme: string },
): Promise<PreviewOut> {
  return kind === 'classes'
    ? unwrap<PreviewOut>(api.POST('/api/uml/classes/preview', { body }))
    : unwrap<PreviewOut>(api.POST('/api/uml/objects/preview', { body }))
}

// ── постройка в проект: у схемы появляется идентификатор ─────────────────────

export function buildFlowchart(
  projectId: string,
  body: { source: string; lang: Lang; mode: string },
): Promise<BuiltOut> {
  return unwrap<BuiltOut>(
    api.POST('/api/projects/{project_id}/flowcharts', {
      params: { path: { project_id: projectId } },
      body,
    }),
  )
}

export function buildUml(
  projectId: string,
  kind: UmlKind,
  body: { sources: NamedSource[]; lang: Lang; theme: string },
): Promise<BuiltOut> {
  const params = { path: { project_id: projectId } } as const
  return kind === 'classes'
    ? unwrap<BuiltOut>(api.POST('/api/projects/{project_id}/uml/classes', { params, body }))
    : unwrap<BuiltOut>(api.POST('/api/projects/{project_id}/uml/objects', { params, body }))
}

// ── проекты и их значения ────────────────────────────────────────────────────

/**
 * Все проекты человека: пространства → проекты каждого.
 *
 * Список проектов служба отдаёт по одному пространству за раз (`workspace_id`
 * обязателен), а главная страница модуля показывает схемы отовсюду. Склейка
 * поэтому здесь, а не в экране: экрану нужен один список, и собирать его в
 * `useMemo` из семи запросов означало бы разбирать в разметке то, что и есть
 * запрос.
 */
export async function fetchAllProjects(): Promise<ProjectCard[]> {
  const { workspaces } = await unwrap<{ workspaces: WorkspaceCard[] }>(api.GET('/api/workspaces'))
  const пачки = await Promise.all(
    workspaces.map((ws) =>
      unwrap<{ projects: ProjectCard[] }>(
        api.GET('/api/projects', { params: { query: { workspace_id: ws.id } } }),
      ).then((тело) => тело.projects),
    ),
  )
  return пачки.flat()
}

export function fetchProject(projectId: string): Promise<ProjectCard> {
  return unwrap<ProjectCard>(
    api.GET('/api/projects/{project_id}', { params: { path: { project_id: projectId } } }),
  )
}

export function fetchValues(projectId: string): Promise<Record<string, unknown>> {
  return unwrap<{ values: Record<string, unknown> }>(
    api.GET('/api/projects/{project_id}/values', { params: { path: { project_id: projectId } } }),
  ).then((тело) => тело.values ?? {})
}

/** Значение тега рукой человека. Схема ложится сюда — оттуда её берёт сборка. */
export function setValue(
  projectId: string,
  key: string,
  value: DiagramValue,
): Promise<{ key: string; version: number }> {
  return unwrap<{ key: string; version: number }>(
    api.PUT('/api/projects/{project_id}/values/{key}', {
      params: { path: { project_id: projectId, key } },
      body: value as unknown as Record<string, never>,
    }),
  )
}

/** Отобрать из значений проекта те, что схемы. Порядок — по ключу тега. */
export function diagramsOf(project: ProjectCard, values: Record<string, unknown>): SavedDiagram[] {
  const out: SavedDiagram[] = []
  for (const [key, value] of Object.entries(values)) {
    if (!value || typeof value !== 'object') continue
    const тело = value as Record<string, unknown>
    if (тело.type !== 'diagram') continue
    out.push({ project, key, value: тело as DiagramValue })
  }
  return out.sort((a, b) => a.key.localeCompare(b.key, 'ru'))
}

// ── задание сборки Word ──────────────────────────────────────────────────────

/**
 * Задание `build` в очередь. → идентификатор задания.
 *
 * `POST /api/jobs` отдаёт **карточку задания целиком**, а не `{job: …}`
 * (`api/jobs/routes.py: service.карточка(задание)`), и идентификатор берётся с
 * верхнего уровня. Написано это здесь, а не в экране: экрану нужен только `id`,
 * и разбирать форму ответа в обработчике нажатия — тот же второй договор со
 * службой, ради избавления от которого заведён `features/<область>/types.ts`.
 */
export function startBuildJob(projectId: string, name: string): Promise<string> {
  return unwrap<{ id: string }>(
    api.POST('/api/jobs', {
      body: {
        kind: 'build',
        project_id: projectId,
        payload: { outputs: ['docx'], name },
      },
    }),
  ).then((карточка) => карточка.id)
}

// ── артефакты ────────────────────────────────────────────────────────────────

function artifactUrl(projectId: string, artifactId: string): string {
  return `/api/projects/${encodeURIComponent(projectId)}/artifacts/${encodeURIComponent(artifactId)}`
}

/**
 * Артефакт байтами. Мимо сгенерированного клиента — см. докстроку модуля.
 * Отказ приходит тем же JSON `{"error":{code}}`, поэтому разбираем его сами и
 * бросаем тот же `ApiError`, что и весь остальной сайт.
 */
export async function fetchArtifact(projectId: string, artifactId: string): Promise<Blob> {
  const { ApiError } = await import('@/api')
  let ответ: Response
  try {
    ответ = await fetch(artifactUrl(projectId, artifactId), { credentials: 'include' })
  } catch (cause) {
    throw ApiError.network(cause)
  }
  if (!ответ.ok) {
    const тело = await ответ.json().catch(() => undefined)
    throw ApiError.from(тело, ответ.status)
  }
  return ответ.blob()
}

export async function fetchArtifactText(projectId: string, artifactId: string): Promise<string> {
  return (await fetchArtifact(projectId, artifactId)).text()
}
