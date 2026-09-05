/**
 * types — формы ответов службы, нужные экранам схем.
 *
 * Часть обработчиков модулей `flowcharts` и `uml` объявлена как `-> dict`
 * (предпросмотр, перечни), поэтому в документе OpenAPI у них стоит «объект
 * произвольной формы». Прочтение этой формы лежит здесь, один раз на область, —
 * ровно так, как советует `api/types.ts` (свои формы каждая область описывает у
 * себя). Сохранённые схемы служба описывает моделями (`DiagramOut`,
 * `DiagramFullOut`), и здешние типы повторяют их поле в поле: экрану нужен один
 * набор имён, а не два — сгенерированный и свой.
 */

/** Язык исходника. Один и тот же перечень у службы: `orchestrator.diagrams.LANGS`. */
export const LANGS = ['py', 'cs', 'cpp'] as const
export type Lang = (typeof LANGS)[number]

/** Какая диаграмма UML строится. Два разных маршрута службы, не поле в теле. */
export type UmlKind = 'classes' | 'objects'

/** Два модуля схем: у каждого своё хранение и свой список. */
export type Module = 'flowcharts' | 'uml'

/** Что построено. У блок-схем один вид, у UML два. */
export type DiagramKind = 'flowchart' | UmlKind

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

/**
 * Строка списка сохранённых схем (`GET …/flowcharts`, `GET …/uml`).
 *
 * `run_id` — запись журнала запусков работы: под ней схема стоит в списке
 * «Что в работе», и ею же она удаляется (`DELETE …/runs/{run_id}`). Имя пустое
 * — законное значение: русское имя по умолчанию («Схема 2 — Курсовая») рисует
 * сайт из модуля и номера, служба своих имён не сочиняет.
 */
export type SavedDiagram = {
  run_id: string
  project_id: string
  module: Module
  kind: DiagramKind
  name: string
  n: number
  artifact: string
  lang: Lang
  mode: string
  theme: string
  created_at?: string | null
}

/** Сохранённая схема целиком: XML, исходники и замечания разбора. */
export type FullDiagram = SavedDiagram & {
  xml: string
  sources: NamedSource[]
  notices?: Notice[]
  /** Что нарисовано (классы, экземпляры); есть только у только что построенной. */
  items?: string[]
}

/** Исходник: имя нужно замечаниям разбора, путём оно не является. */
export type NamedSource = { name: string; source: string }

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
 * без хранилища. Схема ложится сюда, чтобы попасть в собранный документ, —
 * хранится она не здесь, а в работе (`SavedDiagram`).
 */
export type DiagramValue = {
  type: 'diagram'
  artifact?: string
  xml?: string
  caption?: string
  width_cm?: number
  page?: number
}

/** Схема из списка вместе с работой, в которой она лежит. */
export type DiagramInProject = {
  project: ProjectCard
  diagram: SavedDiagram
}
