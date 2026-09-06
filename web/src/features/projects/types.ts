/**
 * Формы ответов службы, которыми пользуется область «Проекты».
 *
 * Здесь, а не в `api/types.ts`: тот файл описывает то, что нужно оболочке, и
 * дописывать в него формы каждой области значило бы собрать в одном месте
 * половину договора службы. Правило `api/README.md` — «формы своих областей
 * описывайте у себя».
 *
 * У каждой формы стоит ссылка на место в службе, откуда она берётся: поменяется
 * там — ломаться должно в одном файле.
 */

/** `packages/api/workspaces/routes.py: карточка()`. */
export type Workspace = {
  id: string
  name: string
  personal: boolean
  /** Роль спрашивающего в этом пространстве: `owner` | `editor` | `viewer`. */
  role: string
  created_at: string
  deleted_at: string | null
  purge_after: string | null
}

/** `packages/api/projects/routes.py: карточка()`. */
export type Project = {
  id: string
  workspace_id: string
  /**
   * Имя пространства, в котором лежит работа. Приезжает вместе с работой, а не
   * добирается вторым запросом: идентификатор пространства на экране человеку
   * ничего не говорит, а список работ и без того знает про них всё остальное.
   */
  workspace_name: string
  owner_id: string
  name: string
  /**
   * Каким модулем эта работа делается: `reports`, `kadai`, `flowcharts`,
   * `uml`. Пусто — не назначен, и это законное состояние: работу заводят
   * раньше, чем решают, чем её делать.
   */
  module: string
  created_at: string
  updated_at: string
  /** Не `null` — проект в корзине. */
  deleted_at: string | null
  /** Когда каталог снесут с тома. */
  purge_after: string | null
  bytes_used: number
  /**
   * Ключи тегов из манифеста. Приезжают только в карточке одного проекта:
   * в списке их нет намеренно (сотня проектов — сотня обходов каталога).
   */
  keys?: string[]
}

/** `packages/api/projects/runs.py: карточка()` — запись журнала запусков. */
export type ProjectRun = {
  id: string
  project_id: string
  /** Идентификатор модуля из `GET /api/modules`. */
  module: string
  /** Пусто — имя рисует сайт из модуля, номера и имени работы. */
  name: string
  /** Который это запуск этого модуля в этой работе, с единицы. Считает служба. */
  n: number
  /** Что запуск произвёл, если произвёл: XML схемы, собранный документ. */
  artifact_id: string | null
  user_id: string | null
  created_at: string | null
}

/** Порядок журнала запусков — тот же перечень, что понимает служба. */
export type RunSort = 'new' | 'old' | 'name' | 'module'

/** `packages/api/templates/routes.py: TemplateOut`. */
export type ReportTemplate = {
  id: string
  name: string
  bytes: number
  /** Сколько тегов нашёл разбор DOCX. */
  tags: number
  sha256: string
  /** Чей это файл: у работы бывает бланк, загруженный другим участником. */
  user_id: string | null
  created_at: string | null
  /**
   * Собирается ли работа по этому бланку. Есть только в списке бланков работы:
   * на личной полке вопрос не имеет смысла, и служба поля там не шлёт.
   */
  active?: boolean | null
}

/** `packages/api/materials/service.py: карточка()`. */
export type Material = {
  id: string
  name: string
  /** Вид файла из пакета `materials`: `pdf` | `docx` | `code` | `text` | … */
  kind: string
  bytes: number
  /** Чем нумеруется содержимое: `page` | `paragraph` | `line`. */
  unit: string
  /** Сколько таких единиц в материале. */
  units: number
  lang: string
  added: string
  /** Замечания разборщика: то, что он не смог или счёл важным. */
  notes: string[]
  /** Материалы, извлечённые из этого (картинки страниц PDF и Word). */
  children: string[]
}

/** Тело `GET …/materials/{id}/text`. */
export type MaterialText = {
  id: string
  name: string
  unit: string
  start: number
  end: number
  text: string
  /** Ссылка, по которой человек проверит цитату: «с. 3–4 файла X». */
  anchor: string
}

/** Строка `GET …/materials/pending` — файл принят, разбор ещё идёт. */
export type PendingMaterial = {
  /** Идентификатор, который материал получит после разбора (sha256 содержимого). */
  pending_id: string
  name: string
  job: { id: string; status: string; [k: string]: unknown }
}

/** Ответ `POST …/materials`: 202, карточка задания и будущий идентификатор. */
export type UploadAccepted = {
  job: { id: string; status: string; [k: string]: unknown }
  pending_id: string
}

/** Ответ `DELETE …/materials/{id}`: что убрано, что осталось. */
export type MaterialRemoved = {
  removed: string[]
  kept: string[]
}
