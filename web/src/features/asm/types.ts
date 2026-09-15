/**
 * types — формы модуля «Ассемблер», общие для каркаса и окон.
 *
 * Строки интерфейса. Словарь каркаса и окон TASM — `src/i18n/ru/asm.json`, окон
 * 64 бит — `src/i18n/ru/asm64.json`; ключ = имя файла + путь внутри файла. Брать так:
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
 * `asm.agent.*`; каркас — `asm.menu.*`, `asm.dialog.*`, `asm.list.*`, `asm.new.*`,
 * `asm.toolchain.*`, `asm.status.*`, `asm.hotkeys.*`. Чужую ветку строками не занимать.
 * Голых русских строк в JSX нет; исключение — данные справки (`docs/entries.ts`),
 * это содержимое, а не подписи.
 *
 * ── Режимы ───────────────────────────────────────────────────────────────────
 *
 * У программы один из двух режимов (`AsmToolchainId`), он задаётся при создании и
 * не меняется. Формы прогона общие, смысл части полей — по режиму:
 *
 * | Поле                   | TASM (`tasm`)                       | MinGW x64 (`mingw64`)                      |
 * |------------------------|-------------------------------------|--------------------------------------------|
 * | `step.cs`, `next.cs`   | сегмент кода, 4 hex                 | `null` — плоская память                     |
 * | `step.ip`, `next.ip`   | IP, 4 hex                           | RIP, 16 hex                                 |
 * | `step.reg`             | 14 регистров 8086                   | rax … r15, rip, rflags, cs ds ss es fs gs   |
 * | `step.reg32`           | при `mode32`                        | `null`                                      |
 * | `step.call`            | нет                                 | `'kernel32.WriteFile'` у шага-вызова API     |
 * | `mem[].seg`, `dumps[].seg` | сегмент, 4 hex                  | `null`, `off` — адрес, до 16 hex            |
 * | `load`                 | `{psp, cs, ds, ss}`                 | `{image_base, entry, rsp}`                  |
 * | `build.segments`       | сегменты `.map`, `start` от образа  | секции PE, `start` — виртуальный адрес      |
 * | `build.symbols`        | `segment` TASM, `offset` 4 hex      | `segment` — секция, `offset` — адрес         |
 * | `build.listing.offset` | смещение от сегмента                | адрес после связывания                      |
 *
 * Правило одно: **`seg = null` — плоская память**.
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

/** Набор инструментов программы. */
export type AsmToolchainId = 'tasm' | 'mingw64'

/** Сегмент:смещение (реальный режим DOS) или одно число (Windows x64). */
export type AsmMemoryModel = 'segmented' | 'flat'

/**
 * Шаг трассы. Шаг `i` — состояние **после** `i`-й команды: `reg`, `changed`,
 * `mem`, `out`, `stdin_pos`. `cs`/`ip`/`line`/`asm`/`bytes` — команда, которая
 * выполнилась на этом шаге; `next` — та, что выполнится следующей (`null` после
 * выхода программы). Шаг 0 — состояние до первой команды: `line: null`,
 * `asm: ''`, `next` — точка входа. Текущая строка листинга = `step.next?.line`.
 */
export interface AsmStep {
  i: number
  /** `null` — плоская память (MinGW x64). */
  cs: Hex | null
  /** IP (4 hex) или RIP (16 hex). */
  ip: Hex
  line: number | null
  asm: string
  bytes: string
  /** Порядок ключей — порядок показа; разрядность — по ширине строки. */
  reg: Record<string, Hex>
  reg32: Record<string, Hex> | null
  changed: string[]
  mem: { seg: Hex | null; off: Hex; old: string; new: string }[]
  out: string
  stdin_pos: number
  next: { cs: Hex | null; ip: Hex; line: number | null; asm: string; bytes: string } | null
  /** Вызов API, выполненный этим шагом целиком: `'kernel32.WriteFile'`. У TASM поля нет. */
  call?: string | null
}

export interface AsmBuildMessage {
  severity: 'error' | 'warning'
  tool: 'tasm' | 'tlink' | 'as' | 'ld'
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

export interface AsmSegmentedLoad {
  psp: Hex
  cs: Hex
  ds: Hex
  ss: Hex
}

export interface AsmFlatLoad {
  image_base: Hex
  entry: Hex
  rsp: Hex
}

/** Как программа загружена: у TASM — сегменты DOS, у MinGW x64 — база образа, точка входа и RSP. */
export type AsmLoad = AsmSegmentedLoad | AsmFlatLoad

/** Загрузка DOS: сегменты PSP, кода, данных и стека. */
export function isSegmentedLoad(load: AsmLoad | null | undefined): load is AsmSegmentedLoad {
  return !!load && 'psp' in load
}

/** Загрузка образа Windows: база, точка входа, RSP. */
export function isFlatLoad(load: AsmLoad | null | undefined): load is AsmFlatLoad {
  return !!load && 'image_base' in load
}

/** Регистр шага строкой hex по имени без учёта регистра букв; нет шага или такого регистра — `undefined`. */
export function regHex(step: AsmStep | undefined, name: string): Hex | undefined {
  return step?.reg[name.toLowerCase()]
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
  /** Режим прогона; у прогонов, записанных до появления режимов, — `'tasm'` (подставляет `api.ts`). */
  toolchain: AsmToolchainId
  /** Версия инструментов прогона; нет в итоге — `'4.1'`. */
  toolchain_version: string
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
  load: AsmLoad | null
  stdin: string
  step_limit: number
  mode32: boolean
  totals: { steps: number; ms: number; exit_code: number | null }
  truncated: { head: number; skipped: number; tail: number } | null
  dumps: { step: number; seg: Hex | null; off: Hex; hex: string }[]
  error: string | null
}

/** Окна, из которых выделенный текст уходит агенту якорем `text`. `debugx` — id окна сырого вывода в обоих режимах. */
export type AsmTextWindow = 'source' | 'listing' | 'output' | 'debugx' | 'build'

export type AsmAnchor =
  | { kind: 'line'; line: number }
  | { kind: 'register'; name: string }
  | { kind: 'flag'; name: string }
  /** `seg: null` — адрес плоской памяти. */
  | { kind: 'cell'; seg: Hex | null; off: Hex }
  | { kind: 'doc'; id: string }
  | { kind: 'run' }
  /**
   * Выделенный текст окна как есть, до 4000 символов (длиннее — обрезан с
   * пометкой в конце). `line_from`/`line_to` — строки исходника, если окно их
   * знает («Исходник», «Листинг»), иначе `null`.
   */
  | { kind: 'text'; window: AsmTextWindow; text: string; line_from: number | null; line_to: number | null }

/**
 * Настройки прогона. Флаги обоих режимов лежат рядом: служба проверяет флаги
 * своего режима и хранит чужие как пришли.
 */
export interface AsmSettings {
  stdin: string
  step_limit: number
  mode32: boolean
  tasm_flags: string[]
  tlink_flags: string[]
  as_flags: string[]
  ld_flags: string[]
  breakpoints: number[]
  watches: string[]
}

/**
 * Режим в `GET /api/asm/status`: готовность, версии, компоненты. Версия программы в
 * остальных ответах службы — поле `toolchain_version` (`version` у программы — счётчик
 * записей исходника).
 */
export interface AsmToolchainStatus {
  id: AsmToolchainId
  title: string
  available: boolean
  default_version: string
  versions: { id: string; title: string; detail: string; available: boolean }[]
  parts: Record<string, boolean>
}

/** То, что получает каждое окно. Окно — обычный компонент `(props: AsmWindowProps) => JSX`. */
export interface AsmWindowProps {
  /** Активна ли вкладка в своей группе. */
  active: boolean
}
