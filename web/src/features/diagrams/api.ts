/**
 * api — запросы области схем. Экраны не зовут `unwrap` сами.
 *
 * Маршруты двух модулей делятся на три части: предпросмотр (без проекта,
 * ничего не пишет на том, ограничен темпом), постройка в работу — она же
 * сохранение (роль editor: XML ложится артефактом, схема попадает в журнал
 * запусков вместе с кодом и параметрами) и чтение сохранённого. Здесь они
 * собраны рядом, чтобы разница была видна одним взглядом, а не по адресу в
 * пяти файлах.
 *
 * Скачивание артефакта идёт мимо `openapi-fetch`: маршрут отдаёт байты с
 * `Content-Disposition`, а клиент по документу OpenAPI ждёт JSON. Поэтому
 * `fetch` руками — с той же cookie-сессией и тем же origin.
 */
import { api, unwrap } from '@/api'
import { withBase } from '@/lib/basePath'

import type {
  DiagramValue,
  FlowchartMode,
  FullDiagram,
  Lang,
  Module,
  NamedSource,
  PreviewOut,
  ProjectCard,
  SavedDiagram,
  UmlKind,
  WorkspaceCard,
} from './types'

export type { NamedSource }

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

// ── постройка в проект: она же сохранение ────────────────────────────────────

/**
 * Построить схему в работе. Отдельного «сохранить» нет: построенная схема
 * ложится в работу сама — с записью в журнале запусков, кодом и параметрами.
 *
 * `runId` — перестройка уже сохранённой схемы: та же запись журнала, тот же
 * номер, новая картинка. Без него заводится новая схема. Иначе пять нажатий,
 * пока подбирается код, дали бы пять «Схема 1…5» в работе.
 */
export function buildFlowchart(
  projectId: string,
  body: { source: string; lang: Lang; mode: string },
  runId?: string | null,
): Promise<FullDiagram> {
  if (runId) {
    return unwrap<FullDiagram>(
      api.PUT('/api/projects/{project_id}/flowcharts/{run_id}', {
        params: { path: { project_id: projectId, run_id: runId } },
        body,
      }),
    )
  }
  return unwrap<FullDiagram>(
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
  runId?: string | null,
): Promise<FullDiagram> {
  if (runId) {
    return unwrap<FullDiagram>(
      api.PUT('/api/projects/{project_id}/uml/{run_id}', {
        params: { path: { project_id: projectId, run_id: runId } },
        body,
      }),
    )
  }
  const params = { path: { project_id: projectId } } as const
  return kind === 'classes'
    ? unwrap<FullDiagram>(api.POST('/api/projects/{project_id}/uml/classes', { params, body }))
    : unwrap<FullDiagram>(api.POST('/api/projects/{project_id}/uml/objects', { params, body }))
}

// ── сохранённые схемы работы ─────────────────────────────────────────────────

/**
 * Схемы одного модуля в одной работе, новые сверху.
 *
 * Списка два, по одному на модуль, и это не повтор: у блок-схем и диаграмм UML
 * своё хранение и свой список — иначе человек, пришедший за схемой алгоритма,
 * разбирал бы её среди диаграмм классов.
 */
export function fetchDiagrams(module: Module, projectId: string): Promise<SavedDiagram[]> {
  const params = { path: { project_id: projectId } } as const
  return module === 'uml'
    ? unwrap<SavedDiagram[]>(api.GET('/api/projects/{project_id}/uml', { params }))
    : unwrap<SavedDiagram[]>(api.GET('/api/projects/{project_id}/flowcharts', { params }))
}

/** Одна сохранённая схема: XML, исходники и параметры — всё, чем её открыть. */
export function fetchDiagram(
  module: Module,
  projectId: string,
  runId: string,
): Promise<FullDiagram> {
  const params = { path: { project_id: projectId, run_id: runId } } as const
  return module === 'uml'
    ? unwrap<FullDiagram>(api.GET('/api/projects/{project_id}/uml/{run_id}', { params }))
    : unwrap<FullDiagram>(api.GET('/api/projects/{project_id}/flowcharts/{run_id}', { params }))
}

/**
 * Удалить схему из работы — записью журнала запусков.
 *
 * Своего маршрута удаления у схем нет намеренно: схема и её запись в журнале —
 * одна вещь, и второй способ удалить означал бы порядок вызовов, который
 * однажды переставят местами. XML при этом остаётся на томе: он может стоять
 * значением тега, и снести его вслед за строкой значило бы выбить картинку из
 * готового документа.
 */
export function deleteDiagram(projectId: string, runId: string): Promise<void> {
  return unwrap<void>(
    api.DELETE('/api/projects/{project_id}/runs/{run_id}', {
      params: { path: { project_id: projectId, run_id: runId } },
    }),
  )
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
  return withBase(
    `/api/projects/${encodeURIComponent(projectId)}/artifacts/${encodeURIComponent(artifactId)}`,
  )
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
