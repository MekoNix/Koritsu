/**
 * types — формы модуля «Ассемблер», общие для каркаса и окон.
 *
 * Строки интерфейса. Словарь один — `src/i18n/ru/asm.json`, ключ = `asm.` + путь
 * внутри файла. Брать так:
 *
 *     import { useT } from '@/i18n'
 *     const t = useT()
 *     t('asm.listing.hits')                   // "раз"
 *     t('asm.input.read', { n: 3, step: 17 })   // "Прочитано {n} к шагу {step}"
 *
 * Второй аргумент `t` — только подстановки `{имя}`, запасного текста нет:
 * неизвестный ключ показывается как есть (`asm.listing.hits`), так пропажа видна
 * сразу. Ветки словаря поделены: заголовки вкладок — `asm.tabs.<id>` (каркас);
 * содержимое окна — `asm.<окно>.*` (`asm.listing.*`, `asm.registers.*` …), общее
 * у окон отладчика — `asm.trace.*` и `asm.ctx.*`; справка и агент — `asm.docs.*`,
 * `asm.agent.*`; каркас — `asm.menu.*`, `asm.dialog.*`, `asm.list.*`,
 * `asm.status.*`, `asm.hotkeys.*`. Чужую ветку строками не занимать.
 * Голых русских строк в JSX нет; исключение — данные справки (`docs/entries.ts`),
 * это содержимое, а не подписи.
 */

export type AsmWindowId =
  | 'source'
  | 'listing'
  | 'registers'
  | 'dump'
  | 'stack'
  | 'watch'
  | 'breakpoints'
  | 'output'
  | 'input'
  | 'build'
  | 'debugx'
  | 'agent'
  | 'docs'

export type Hex = string

/**
 * Шаг трассы. Шаг `i` — состояние **после** `i`-й команды: `reg`, `changed`,
 * `mem`, `out`, `stdin_pos`. `cs`/`ip`/`line`/`asm`/`bytes` — команда, которая
 * выполнилась на этом шаге; `next` — та, что выполнится следующей (`null` после
 * выхода программы). Шаг 0 — состояние до первой команды: `line: null`,
 * `asm: ''`, `next` — точка входа. Текущая строка листинга = `step.next?.line`.
 */
export interface AsmStep {
  i: number
  cs: Hex
  ip: Hex
  line: number | null
  asm: string
  bytes: string
  reg: Record<
    'ax' | 'bx' | 'cx' | 'dx' | 'si' | 'di' | 'bp' | 'sp' | 'ip' | 'cs' | 'ds' | 'ss' | 'es' | 'flags',
    Hex
  >
  reg32: Record<string, Hex> | null
  changed: string[]
  mem: { seg: Hex; off: Hex; old: string; new: string }[]
  out: string
  stdin_pos: number
  next: { cs: Hex; ip: Hex; line: number | null; asm: string; bytes: string } | null
}

export interface AsmBuildMessage {
  severity: 'error' | 'warning'
  tool: 'tasm' | 'tlink'
  line: number | null
  text: string
}

export interface AsmListingLine {
  line: number
  segment: string | null
  offset: Hex | null
  bytes: string
  text: string
}

export interface AsmRunSummary {
  run_no: number
  job_id: string | null
  status:
    | 'queued'
    | 'building'
    | 'running'
    | 'done'
    | 'build_error'
    | 'step_limit'
    | 'timeout'
    | 'crashed'
  /**
   * Исходник, из которого собран прогон. Номера строк в сообщениях сборки,
   * листинге и шагах — от этого текста; правка после сборки их сдвигает.
   */
  source: string | null
  build: {
    ok: boolean
    log: string
    messages: AsmBuildMessage[]
    listing: AsmListingLine[]
    segments: { name: string; cls: string; start: Hex; length: Hex }[]
    symbols: { name: string; segment: string; offset: Hex; kind: string; size: number | null }[]
  } | null
  load: { psp: Hex; cs: Hex; ds: Hex; ss: Hex } | null
  stdin: string
  step_limit: number
  mode32: boolean
  totals: { steps: number; ms: number; exit_code: number | null }
  truncated: { head: number; skipped: number; tail: number } | null
  dumps: { step: number; seg: Hex; off: Hex; hex: string }[]
  error: string | null
}

/** Окна, из которых выделенный текст уходит агенту якорем `text`. */
export type AsmTextWindow = 'source' | 'listing' | 'output' | 'debugx' | 'build'

export type AsmAnchor =
  | { kind: 'line'; line: number }
  | { kind: 'register'; name: string }
  | { kind: 'flag'; name: string }
  | { kind: 'cell'; seg: Hex; off: Hex }
  | { kind: 'doc'; id: string }
  | { kind: 'run' }
  /**
   * Выделенный текст окна как есть, до 4000 символов (длиннее — обрезан с
   * пометкой в конце). `line_from`/`line_to` — строки исходника, если окно их
   * знает («Исходник», «Листинг»), иначе `null`.
   */
  | { kind: 'text'; window: AsmTextWindow; text: string; line_from: number | null; line_to: number | null }

export interface AsmSettings {
  stdin: string
  step_limit: number
  mode32: boolean
  tasm_flags: string[]
  tlink_flags: string[]
  breakpoints: number[]
  watches: string[]
}

/** То, что получает каждое окно. Окно — обычный компонент `(props: AsmWindowProps) => JSX`. */
export interface AsmWindowProps {
  /** Активна ли вкладка в своей группе. */
  active: boolean
}
