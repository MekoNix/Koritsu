/**
 * Формы ответов службы, которыми пользуется область «Задания».
 *
 * Своим файлом, а не в `api/types.ts`: тот описывает то, что нужно оболочке
 * (правило `api/README.md` — «формы своих областей описывайте у себя»). У
 * каждой формы стоит место в службе, откуда она берётся.
 */
import type { StageState } from './stages'

/** `packages/api/modules/kadai/routes.py: стадии()`. */
export type StageNamesBody = { stages: string[] }

/**
 * `packages/api/modules/kadai/routes.py: карточка_решения()` — решение работы.
 *
 * Решений в работе несколько: у каждого своё условие, свои пожелания, свой ход
 * стадий, свой список блоков с историей и своя папка файлов контекста. `id` —
 * то, что остальные маршруты берут параметром `run`.
 *
 * `state` и `stage` приходят из хода стадий на томе и бывают пустыми: только
 * что заведённое решение ещё ни разу не запускали, и это законное состояние, а
 * не пробел в ответе. `condition_name` — имя файла с условием, пока его не
 * назвали, пусто.
 */
export type KadaiRunCard = {
  id: string
  project_id: string
  name: string
  n: number
  user_id?: string | null
  created_at?: string | null
  state?: string | null
  stage?: string | null
  condition_name: string
}

/**
 * `packages/api/modules/kadai/routes.py: общие_файлы()` — общий файл работы.
 *
 * Общий — тот, что приложен ко всей работе, а не к одному решению: методичку
 * кафедры кладут один раз, а нужна она в каждой задаче. `selected` — уезжает ли
 * он в промпт этого решения; по умолчанию уезжают все, включая те, что положат
 * позже.
 */
export type KadaiCommonFile = {
  id: string
  name: string
  kind?: string
  selected: boolean
}

/** Тело `GET/PUT …/kadai/context`. */
export type KadaiContextBody = { common: KadaiCommonFile[] }

/**
 * `packages/api/modules/kadai/routes.py: ход()` — снимок работы с тома.
 *
 * `outputs` — **имена** готовых файлов («отчёт.docx»), а `made` —
 * идентификаторы артефактов. Пара не лишняя: имя показывают человеку, а
 * скачивают по идентификатору, и путать их нельзя (`kadai.stages` проверяет,
 * что в `outputs` нет путей).
 *
 * Ключи `made`: `docx` и `pdf` кладёт стадия «сборка», `archive` — стадия
 * «архив» (`orchestrator.kadai._положить_архив`). Ключа нет — файла ещё нет, и
 * кнопки скачивания на экране тоже.
 */
export type KadaiStatus = {
  work: string | null
  state: string | null
  stage: string | null
  stages: StageState[]
  current: string
  /** Чего работа ждёт от человека. `null` — не ждёт. */
  hold: { stage: string; show: string; note?: string } | null
  /** Карточка материала-условия без текста. */
  condition: { material?: string; name?: string; unit?: string; ocr?: boolean }
  /** Условие так, как его прочитали. Показывается на своём шаге. */
  condition_text: string
  problems: KadaiProblem[]
  outputs: Record<string, string>
  made: Record<string, string>
  requirement: Record<string, unknown>
  wishes: Record<string, unknown>
  since: number
}

/** Общая форма замечания трёх пакетов (`validate.py`, `manifest.py`, `build.py`). */
export type KadaiProblem = {
  module?: string
  level?: string
  code?: string
  key?: string | null
  message?: string
}

/** `packages/api/versions/routes.py: блоки()`. */
export type BlocksBody = { blocks: BlockRecordBody[] }

/** Запись блока на томе (`orchestrator.Project.blocks`). */
export type BlockRecordBody = {
  key: string
  /** Вид блока движка отчётов: `heading` | `markdown` | `code` | `table` | `diagram` | … */
  kind?: string | null
  /** Как блок называется человеку. */
  label?: string | null
  /** Кто его написал: `agent` | `manual` | `file` | `template`. */
  source?: string | null
  value?: Record<string, unknown> | null
}

/** `packages/api/versions/routes.py: _шапка_блоков()`. */
export type BlockVersionHead = {
  n: number
  at: string
  source: string
  note: string | null
  run: string | null
  count: number
}

export type BlockVersionsBody = { versions: BlockVersionHead[] }
export type BlockVersionBody = { version: BlockVersionHead; blocks: BlockRecordBody[] }

/** Виды заданий очереди, которыми работает эта область (`jobs/registry.py`). */
export const KADAI_RUN = 'kadai_run'
export const KADAI_REWORK = 'kadai_rework'

/** Имя события потока: смена стадии сценария (`runs/handlers/common.СТАДИЯ`). */
export const EV_STAGE = 'stage'
