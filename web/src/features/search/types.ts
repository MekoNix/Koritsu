/**
 * types — форма ответа поиска и строка палитры.
 *
 * Своим файлом, а не в `api/types.ts`: тот описывает то, что нужно оболочке
 * (правило `api/README.md` — «формы своих областей описывайте у себя»).
 */

/** `packages/api/search/routes.py: найти()` — работа в выдаче. */
export type ProjectFound = {
  id: string
  name: string
  workspace_id: string
  workspace_name: string
  /** Личное ли пространство: имя ему сайт даёт своё, а не `Personal`. */
  workspace_personal: boolean
  /** Каким модулем открывать работу: `kadai` | `reports`. */
  module: string
}

/** `packages/api/search/routes.py: найти()` — файл в выдаче. */
export type MaterialFound = {
  id: string
  name: string
  project_id: string
  project_name: string
}

export type SearchBody = { projects: ProjectFound[]; materials: MaterialFound[] }

/**
 * Строка палитры. Две формы, а не одна с необязательными полями: у работы
 * подпись — имя пространства, у файла — имя работы, и «может быть, а может и
 * нет» здесь означало бы строку без подписи вовсе.
 */
export type ProjectHit = {
  kind: 'project'
  id: string
  name: string
  /** Имя пространства — в списке из нескольких пространств без него не понять. */
  workspace: string
  to: string
}

export type MaterialHit = {
  kind: 'material'
  id: string
  name: string
  /** Имя работы, в которой лежит файл. */
  project: string
  to: string
}

export type Hit = ProjectHit | MaterialHit
