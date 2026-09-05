/**
 * types — формы ответов службы, нужные экранам схем.
 *
 * Обработчики модулей `flowcharts` и `uml` объявлены как `-> dict`, поэтому в
 * документе OpenAPI у них стоит «объект произвольной формы». Прочтение этой
 * формы лежит здесь, один раз на область, — ровно так, как советует
 * `api/types.ts` (свои формы каждая область описывает у себя).
 */

/** Язык исходника. Один и тот же перечень у службы: `orchestrator.diagrams.LANGS`. */
export const LANGS = ['py', 'cs', 'cpp'] as const
export type Lang = (typeof LANGS)[number]

/** Какая диаграмма UML строится. Два разных маршрута службы, не поле в теле. */
export type UmlKind = 'classes' | 'objects'

/** `GET /api/flowcharts/modes` — режим отрисовки с описанием по-русски. */
export type FlowchartMode = {
  id: string
  description: string
}

/** `kyotsu.Notice.to_dict()` — замечание разбора. */
export type Notice = {
  module: string
  level: string
  code: string
  message: string
  file?: string | null
  line?: number | null
}

/** Ответ трёх маршрутов предпросмотра: XML и замечания, на том ничего не лежит. */
export type PreviewOut = {
  xml: string
  notices?: Notice[]
}

/** Ответ трёх маршрутов «построить в проект»: у схемы появился идентификатор. */
export type BuiltOut = {
  artifact: string
  notices?: Notice[]
  /** Что попало на схему: классы или экземпляры; у блок-схемы поля нет. */
  classes?: string[]
  objects?: string[]
}

/** `packages/api/projects/routes.py: карточка()`. */
export type ProjectCard = {
  id: string
  workspace_id: string
  name: string
  created_at: string
  updated_at: string
  deleted_at: string | null
  bytes_used: number
  /** Ключи тегов, у которых есть значение. Только у карточки одного проекта. */
  keys?: string[]
}

/** `packages/api/workspaces/routes.py: карточка()`. */
export type WorkspaceCard = {
  id: string
  name: string
  personal: boolean
  role: string
}

/**
 * Значение тега со схемой (`hokoku.wire`, вид `diagram`). Ровно одно из
 * `artifact` и `xml`: служба кладёт артефакт, а `xml` бывает у схем, собранных
 * без хранилища.
 */
export type DiagramValue = {
  type: 'diagram'
  artifact?: string
  xml?: string
  caption?: string
  width_cm?: number
  page?: number
}

/** Строка списка «сохранённые схемы»: значение проекта вместе с его проектом. */
export type SavedDiagram = {
  project: ProjectCard
  key: string
  value: DiagramValue
}
