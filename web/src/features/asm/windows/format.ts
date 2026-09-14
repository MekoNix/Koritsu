/**
 * format — общее для окон отладчика: числа, флаги, адреса, память по трассе,
 * окно строк и контекстное меню якоря.
 *
 * ── Почему всё в одном файле ─────────────────────────────────────────────────
 *
 * Окна пишутся независимо друг от друга и от дока, но смотрят на одни и те же
 * данные: регистр AX в «Регистрах», в «Наблюдении» и в контекстном меню должен
 * читаться одной функцией, а ячейка DS:0005 в «Дампе», «Стеке» и «Наблюдении» —
 * одной и той же картой памяти. Две копии разбора адреса разошлись бы на первом
 * же `arr[2]`.
 *
 * ── Трасса читается по порядку и один раз ────────────────────────────────────
 *
 * Шаг хранит только своё: регистры после команды, записи в память, вывод этого
 * шага, позицию во вводе. Всё накопленное — текст вывода к шагу N, сколько раз
 * выполнялась строка, память на шаге N — получается проходом по шагам с начала.
 * Проход (`TraceScan`) живёт на прогон, продвигается по мере того, как store
 * догружает страницы, и запоминает контрольные точки памяти через каждые
 * `CHECKPOINT` шагов: шаг назад на сотом тысячном шаге не перечитывает трассу
 * с нуля.
 */
import { createElement, useCallback, useEffect, useLayoutEffect, useRef, useState, type ReactNode, type RefObject } from 'react'

import { useAsm } from '@/features/asm/store'
import type { AsmAnchor, AsmRunSummary, AsmStep, AsmTextWindow } from '@/features/asm/types'
import { plural } from '@/features/projects/format'
import { t } from '@/i18n'
import { MenuContent, MenuItem, MenuLabel, MenuRoot, MenuSeparator, MenuTrigger } from '@/ui'

/* ── числа ─────────────────────────────────────────────────────────────────── */

/** Высота строки во всех табличных окнах, px. Одна на всех: так строки листинга, стека и дампа стоят вровень в соседних группах. */
export const ROW = 19

export type Radix = 'hex' | 'dec'

/** Hex-строка службы (`"0780"`, `"0000FFFF"`) в число; мусор — `null`. */
export function parseHex(h: string | null | undefined): number | null {
  if (h == null) return null
  const s = h.trim().replace(/h$/i, '')
  if (!/^[0-9a-f]+$/i.test(s)) return null
  return parseInt(s, 16)
}

/** Число в hex верхним регистром без `0x`, дополненное нулями до `width`. */
export function hex(n: number, width = 4): string {
  return (n >>> 0).toString(16).toUpperCase().padStart(width, '0')
}

/** Число с разрядами по-русски: `100 000`. */
export function fmtInt(n: number): string {
  return n.toLocaleString('ru-RU')
}

/** Число шагов со словом: «1 шаг», «3 шага», «1 200 шагов». Склонение — общее правило `plural`. */
export function fmtSteps(n: number): string {
  return `${fmtInt(n)} ${plural(n, [t('asm.plural.step.one'), t('asm.plural.step.few'), t('asm.plural.step.many')])}`
}

/** Миллисекунды в секунды с одним знаком после запятой: `1,5`. Точнее десятой доля секунды прогона ничего не говорит. */
export function fmtSec(ms: number): string {
  return (Math.round(ms / 100) / 10).toLocaleString('ru-RU', { minimumFractionDigits: 1, maximumFractionDigits: 1 })
}

/** Вызов DOS — `int 21h` или `int 20h`: засечки на дорожке ползунка. DebugX пишет вектор без `h`. */
export function isDosCall(asm: string): boolean {
  return /^\s*int\s+0*2[01]h?\s*$/i.test(asm)
}

/** Значение в выбранной системе: hex дополняется до ширины, dec — пробелами до той же ширины в символах. */
export function fmtValue(n: number, radix: Radix, bytes: 1 | 2 | 4): string {
  if (radix === 'hex') return hex(n, bytes * 2)
  const width = bytes === 1 ? 3 : bytes === 2 ? 5 : 10
  return String(n >>> 0).padStart(width, ' ')
}

/** Байты из строки hex, в которой могут быть пробелы: `"B8 80 07"` и `"B88007"` — одно и то же. */
export function hexBytes(s: string): number[] {
  const clean = s.replace(/[^0-9a-f]/gi, '')
  const out: number[] = []
  for (let i = 0; i + 1 < clean.length; i += 2) out.push(parseInt(clean.slice(i, i + 2), 16))
  return out
}

/** Байты команды парами через пробел — как в листинге TASM. */
export function spacedBytes(s: string): string {
  return hexBytes(s)
    .map((b) => hex(b, 2))
    .join(' ')
}

/** Символ ввода или вывода так, чтобы его было видно: перевод строки, пробел, управляющие. */
export function visibleChar(c: string): string {
  if (c === '\n' || c === '\r') return '⏎'
  if (c === ' ') return '␠'
  if (c === '\t') return '⇥'
  const code = c.charCodeAt(0)
  if (code < 32) return '·'
  return c
}

/** Печатный ли байт для колонки ASCII. */
export function asciiOf(b: number): string {
  return b >= 32 && b < 127 ? String.fromCharCode(b) : '·'
}

/* ── флаги ─────────────────────────────────────────────────────────────────── */

/** Порядок флагов — как в строке регистров DebugX. */
export const FLAG_ORDER = ['OF', 'DF', 'IF', 'SF', 'ZF', 'AF', 'PF', 'CF'] as const
export type FlagName = (typeof FLAG_ORDER)[number]

export const FLAG_BIT: Record<FlagName, number> = {
  CF: 0,
  PF: 2,
  AF: 4,
  ZF: 6,
  SF: 7,
  IF: 9,
  DF: 10,
  OF: 11,
}

/** Мнемоники DebugX: `[при 0, при 1]`. Их человек видит в сыром выводе, поэтому они же и в окне. */
export const FLAG_MNEMONIC: Record<FlagName, readonly [string, string]> = {
  OF: ['NV', 'OV'],
  DF: ['UP', 'DN'],
  IF: ['DI', 'EI'],
  SF: ['PL', 'NG'],
  ZF: ['NZ', 'ZR'],
  AF: ['NA', 'AC'],
  PF: ['PO', 'PE'],
  CF: ['NC', 'CY'],
}

export function isFlagName(s: string): s is FlagName {
  return (FLAG_ORDER as readonly string[]).includes(s.toUpperCase())
}

export function flagBit(flags: number, f: FlagName): 0 | 1 {
  return ((flags >> FLAG_BIT[f]) & 1) as 0 | 1
}

/** Слово FLAGS шага; нет шага — `null`. */
export function stepFlags(step: AsmStep | undefined): number | null {
  return step ? parseHex(step.reg.flags) : null
}

/** Флаги строкой DebugX: `NV UP EI PL NZ NA PO NC`. */
export function debugxFlags(flags: number): string {
  return FLAG_ORDER.map((f) => FLAG_MNEMONIC[f][flagBit(flags, f)]).join(' ')
}

/* ── регистры ──────────────────────────────────────────────────────────────── */

export const REG_GENERAL = ['ax', 'bx', 'cx', 'dx'] as const
export const REG_INDEX = ['si', 'di', 'bp', 'sp', 'ip'] as const
export const REG_SEGMENT = ['cs', 'ds', 'ss', 'es'] as const
type Reg16 = (typeof REG_GENERAL)[number] | (typeof REG_INDEX)[number] | (typeof REG_SEGMENT)[number]
const REG16: readonly string[] = [...REG_GENERAL, ...REG_INDEX, ...REG_SEGMENT]

/** Байтовые регистры: какой 16-битный и какой сдвиг. */
const REG8: Record<string, readonly [Reg16, 0 | 8]> = {
  al: ['ax', 0],
  ah: ['ax', 8],
  bl: ['bx', 0],
  bh: ['bx', 8],
  cl: ['cx', 0],
  ch: ['cx', 8],
  dl: ['dx', 0],
  dh: ['dx', 8],
}

export interface RegValue {
  value: number
  bytes: 1 | 2 | 4
}

/**
 * Значение регистра по имени: `AX`, `al`, `EAX`, `FLAGS`. В режиме 32 бит
 * 16-битное имя общего регистра читается как младшая половина 32-битного —
 * это одно и то же место, и показывать разные числа было бы враньём.
 */
export function regValue(step: AsmStep | undefined, name: string): RegValue | null {
  if (!step) return null
  const n = name.trim().toLowerCase()
  if (n === 'flags' || n === 'fl') {
    const v = parseHex(step.reg.flags)
    return v == null ? null : { value: v, bytes: 2 }
  }
  if (REG16.includes(n)) {
    const v = parseHex(step.reg[n as Reg16])
    return v == null ? null : { value: v, bytes: 2 }
  }
  const r8 = REG8[n]
  if (r8) {
    const v = parseHex(step.reg[r8[0]])
    return v == null ? null : { value: (v >> r8[1]) & 0xff, bytes: 1 }
  }
  if (n.length === 3 && n.startsWith('e') && step.reg32) {
    const v = parseHex(step.reg32[n])
    return v == null ? null : { value: v, bytes: 4 }
  }
  return null
}

/** Слово регистра числом или `null`: для мест, где нужен просто SI. */
export function reg(step: AsmStep | undefined, name: Reg16): number | null {
  return step ? parseHex(step.reg[name]) : null
}

/* ── прогон: номера шагов и свёртка ────────────────────────────────────────── */

/**
 * Последний номер шага. Шаг 0 — состояние до первой команды (вывод `R`), шаг N —
 * после N-й команды: его `line`/`asm` — выполненная команда, `next` — следующая.
 * Номера идут от 0 до `totals.steps`.
 */
export function lastStepIndex(run: AsmRunSummary | undefined): number {
  return run ? Math.max(0, run.totals.steps) : 0
}

/** Трасса есть и по ней можно ходить. */
export function hasTrace(run: AsmRunSummary | undefined): run is AsmRunSummary {
  return !!run && (run.status === 'done' || run.status === 'step_limit' || run.status === 'timeout' || run.status === 'crashed') && run.totals.steps > 0
}

/**
 * Программа не вышла в DOS, а встала на чтении: ввод кончился или она ждёт
 * клавиатуру через int 16h. Ядро отдаёт это как `done` без кода выхода и с
 * пояснением в `error` — «завершилась с кодом —» здесь было бы неправдой.
 */
export function waitsForInput(run: AsmRunSummary | undefined): boolean {
  return !!run && run.status === 'done' && run.totals.exit_code == null && !!run.error && run.totals.steps > 0
}

/** Прогон ещё идёт. */
export function isBusy(run: AsmRunSummary | undefined): boolean {
  return !!run && (run.status === 'queued' || run.status === 'building' || run.status === 'running')
}

/**
 * Свёрнутая середина трассы: `[from, to)`; нет свёртки — `null`. Сворачивается
 * не только прогон на лимите шагов, но и завершившаяся программа длиннее
 * двадцати тысяч шагов, поэтому на `status` здесь не смотрим.
 */
export function skippedRange(run: AsmRunSummary | undefined): readonly [number, number] | null {
  const tr = run?.truncated
  if (!tr || tr.skipped <= 0) return null
  return [tr.head, tr.head + tr.skipped]
}

export function isSkipped(run: AsmRunSummary | undefined, i: number): boolean {
  const r = skippedRange(run)
  return !!r && i >= r[0] && i < r[1]
}

/** Во что превратился прогон — для заглушек окон. */
export type TraceState = 'none' | 'queued' | 'building' | 'running' | 'build_error' | 'failed' | 'ready'

export function traceState(run: AsmRunSummary | undefined): TraceState {
  if (!run) return 'none'
  if (run.status === 'queued' || run.status === 'building' || run.status === 'running') return run.status
  if (run.status === 'build_error' || (run.build && !run.build.ok)) return 'build_error'
  return hasTrace(run) ? 'ready' : 'failed'
}

/** Текст заглушки окна, которому нужна трасса; трасса есть — `null`. */
export function veilText(run: AsmRunSummary | undefined): string | null {
  switch (traceState(run)) {
    case 'ready':
      return null
    case 'queued':
    case 'building':
    case 'running':
      return t('asm.trace.building')
    case 'build_error': {
      const e = firstError(run)
      return e ? t('asm.trace.buildErrorLine', { line: e.line }) : t('asm.trace.buildError')
    }
    case 'failed':
      return t('asm.trace.failed')
    default:
      return t('asm.trace.none')
  }
}

/** Первая ошибка сборки со строкой — к ней ведут кнопки «К строке N». */
export function firstError(run: AsmRunSummary | undefined): { line: number; text: string } | null {
  const m = run?.build?.messages.find((x) => x.severity === 'error' && x.line != null)
  return m && m.line != null ? { line: m.line, text: m.text } : null
}

/**
 * Сегмент времени выполнения по имени сегмента из листинга.
 *
 * В `.map` начало сегмента — смещение от начала образа программы, а образ DOS
 * кладёт сразу за PSP (256 байт, то есть 10h сегментов). Код берётся прямо из
 * загрузки: CS при старте и есть сегмент кода.
 */
export function segmentBase(run: AsmRunSummary | undefined, name: string | null): number | null {
  if (!run || name == null) return null
  const segs = run.build?.segments ?? []
  const s = segs.find((x) => x.name.toUpperCase() === name.toUpperCase())
  const psp = parseHex(run.load?.psp)
  if (s) {
    if (s.cls.toUpperCase() === 'CODE' && run.load) return parseHex(run.load.cs)
    const start = parseHex(s.start)
    if (start != null && psp != null) return (psp + 0x10 + (start >> 4)) & 0xffff
    return null
  }
  return /^[0-9a-f]{4}$/i.test(name) ? parseHex(name) : null
}

/** Чей это сегмент: PSP, код, данные или стек — подпись у сегментных регистров. */
export function segmentRole(run: AsmRunSummary | undefined, seg: number): 'psp' | 'code' | 'data' | 'stack' | null {
  if (!run?.load) return null
  if (seg === parseHex(run.load.psp)) return 'psp'
  if (seg === parseHex(run.load.cs)) return 'code'
  if (seg === parseHex(run.load.ss)) return 'stack'
  // `load.ds` — сегмент данных по карте TLINK, а не DS при загрузке (тот равен PSP).
  if (seg === parseHex(run.load.ds)) return 'data'
  const data = run.build?.segments.find((s) => s.cls.toUpperCase() === 'DATA')
  if (data && seg === segmentBase(run, data.name)) return 'data'
  return null
}

/** Дно стека (SP пустого стека): длина сегмента стека из `.map`, без него — 64 КБ. */
export function stackTop(run: AsmRunSummary | undefined): number {
  const s = run?.build?.segments.find((x) => x.cls.toUpperCase() === 'STACK')
  const len = parseHex(s?.length)
  return len != null && len > 0 ? Math.min(len, 0x10000) : 0x10000
}

/* ── адреса ────────────────────────────────────────────────────────────────── */

export interface Addr {
  seg: number
  off: number
}

/** Линейный адрес реального режима: сегмент × 16 + смещение. */
export function linear(a: Addr): number {
  return (a.seg * 16 + a.off) & 0xfffff
}

export function fmtAddr(a: Addr): string {
  return `${hex(a.seg)}:${hex(a.off & 0xffff)}`
}

/** Переменная сегмента данных из `.map`: имя, смещение от DS, размер в байтах, если известен. */
export interface DataSymbol {
  name: string
  off: number
  size: number | null
}

const CODE_KINDS = new Set(['near', 'far', 'proc', 'label', 'code'])

/**
 * Переменные данных из символов сборки.
 *
 * В `.model small` данные и стек сведены в DGROUP, и DS после `mov ds, ax`
 * указывает на неё — поэтому смещение символа читается от DS. Символы кода
 * (метки, процедуры) и сегмента стека сюда не попадают: в дампе данных им
 * подписывать нечего.
 */
export function dataSymbols(run: AsmRunSummary | undefined): DataSymbol[] {
  const build = run?.build
  if (!build) return []
  const cls = new Map(build.segments.map((s) => [s.name.toUpperCase(), s.cls.toUpperCase()]))
  const out: DataSymbol[] = []
  for (const s of build.symbols) {
    const c = cls.get(s.segment.toUpperCase()) ?? ''
    if (c === 'CODE' || c === 'STACK') continue
    if (CODE_KINDS.has(s.kind.toLowerCase())) continue
    const off = parseHex(s.offset)
    if (off == null) continue
    out.push({ name: s.name, off, size: s.size })
  }
  return out.sort((a, b) => a.off - b.off)
}

/** Переменная, в которую попадает смещение DS; размер неизвестен — до следующей переменной. */
export function symbolAt(symbols: readonly DataSymbol[], off: number): { sym: DataSymbol; index: number; rel: number } | null {
  for (let i = symbols.length - 1; i >= 0; i--) {
    const s = symbols[i]!
    if (off < s.off) continue
    const next = symbols[i + 1]
    const size = s.size ?? (next ? next.off - s.off : 1)
    if (off < s.off + Math.max(1, size)) return { sym: s, index: i, rel: off - s.off }
    return null
  }
  return null
}

/** Сегменты по умолчанию, пока шага нет: из того, как DOS загрузил программу. */
function defaultSegment(name: string, run: AsmRunSummary | undefined): number | null {
  const load = run?.load
  if (!load) return null
  const n = name.toLowerCase()
  if (n === 'cs') return parseHex(load.cs)
  if (n === 'ds' || n === 'es') return parseHex(load.ds)
  if (n === 'ss') return parseHex(load.ss)
  return null
}

const OFF_REGS = ['si', 'di', 'bp', 'sp', 'ip', 'bx']

function parseTerm(term: string, step: AsmStep | undefined): number | null {
  const s = term.trim().toLowerCase()
  if (!s) return null
  if (OFF_REGS.includes(s)) return reg(step, s as Reg16)
  if (/^[0-9a-f]{1,4}h?$/.test(s)) return parseInt(s.replace(/h$/, ''), 16)
  return null
}

/**
 * Адрес из того, что человек пишет: `DS:SI`, `SS:00F0`, `0780:0005`,
 * `DS:SI+2`, имя переменной `arr`, элемент `arr[2]` или `arr+2`.
 *
 * Числа — hex (как везде в отладчике), суффикс `h` можно ставить, можно нет.
 * Регистры берутся со шага `step`; без шага сегментные регистры — из загрузки.
 */
export function parseAddress(
  text: string,
  step: AsmStep | undefined,
  run: AsmRunSummary | undefined,
  symbols: readonly DataSymbol[],
): Addr | null {
  const s = text.trim()
  if (!s) return null
  const pair = /^([0-9a-z]{1,5}h?)\s*:\s*([0-9a-z]{1,5}h?)\s*(?:([+-])\s*([0-9a-f]{1,4}h?))?$/i.exec(s)
  if (pair) {
    const segName = pair[1]!.toLowerCase()
    let seg: number | null
    if ((REG_SEGMENT as readonly string[]).includes(segName)) seg = reg(step, segName as Reg16) ?? defaultSegment(segName, run)
    else seg = parseTerm(segName, undefined)
    let off = parseTerm(pair[2]!, step)
    if (seg == null || off == null) return null
    if (pair[3] && pair[4]) {
      const d = parseInt(pair[4].replace(/h$/i, ''), 16)
      off = pair[3] === '+' ? off + d : off - d
    }
    return { seg, off: off & 0xffff }
  }
  const named = /^([a-z_@?$][\w@?$]*)\s*(?:\[\s*([0-9a-f]+h?)\s*\]|\+\s*([0-9a-f]+h?))?$/i.exec(s)
  if (named) {
    const sym = symbols.find((x) => x.name.toLowerCase() === named[1]!.toLowerCase())
    if (!sym) return null
    const idxText = named[2] ?? named[3]
    // Индекс в скобках — десятичный, как пишут `arr[2]`; после плюса — hex, как адрес.
    const idx = idxText == null ? 0 : named[2] != null && !/h$/i.test(idxText) ? parseInt(idxText, 10) : parseInt(idxText.replace(/h$/i, ''), 16)
    if (Number.isNaN(idx)) return null
    const ds = reg(step, 'ds') ?? defaultSegment('ds', run)
    if (ds == null) return null
    return { seg: ds, off: (sym.off + idx) & 0xffff }
  }
  return null
}

/* ── проход по трассе ──────────────────────────────────────────────────────── */

/** Через сколько шагов снимается копия записанной памяти. */
const CHECKPOINT = 256
/** Сколько шагов проход берёт за один кадр: больше — заметная заминка на медленной машине. */
const SCAN_BUDGET = 8000

type Cell = { v: number; s: number }
export type MemDump = AsmRunSummary['dumps'][number]

/**
 * Накопленное по трассе к шагу. Живёт на прогон (`scanFor`), продвигается
 * вперёд по мере загрузки шагов и назад не откатывается: прошлое трассы не
 * меняется.
 */
export class TraceScan {
  /** Номер следующего непрочитанного шага: всё до него учтено. */
  scanned = 0
  /** Весь вывод прочитанной части трассы одной строкой. */
  out = ''
  /** Длина вывода после шага i. */
  outLen: number[] = []
  /** Где в выводе дырка свёртки: позиция символа и сколько шагов пропущено. */
  outGap: { at: number; steps: number } | null = null
  /** Сколько раз выполнялась строка исходника в прочитанной части. */
  hits = new Map<number, number>()
  /** На каком шаге прочитан i-й символ ввода. */
  reads: number[] = []
  /** Память, дочитанная по запросу (`memory()`), вдобавок к дампам прогона. */
  extraDumps: MemDump[] = []
  private writes = new Map<number, Cell>()
  private checkpoints: Map<number, Cell>[] = []
  private lastMem: { k: number; map: Map<number, Cell> } | null = null

  constructor(readonly run: AsmRunSummary) {}

  /** Всё ли прочитано до конца трассы. */
  get complete(): boolean {
    return this.scanned > lastStepIndex(this.run)
  }

  /**
   * Прочитать шаги до `target` включительно, сколько успеется за кадр и сколько
   * уже загружено. Шаг, которого ещё нет, останавливает проход: store догрузит
   * страницу, окно перерисуется и проход продолжится с того же места.
   */
  advance(getStep: (i: number) => AsmStep | undefined, target: number): boolean {
    const last = Math.min(target, lastStepIndex(this.run))
    const gap = skippedRange(this.run)
    let budget = SCAN_BUDGET
    const before = this.scanned
    while (this.scanned <= last && budget-- > 0) {
      const i = this.scanned
      if (gap && i >= gap[0] && i < gap[1]) {
        // Шагов середины нет вовсе — вывод и память за неё неизвестны, и это
        // отмечается один раз, а длины заполняются тем, что было до дырки.
        this.outGap = { at: this.out.length, steps: gap[1] - gap[0] }
        for (let j = i; j < gap[1]; j++) this.outLen[j] = this.out.length
        this.scanned = gap[1]
        continue
      }
      const st = getStep(i)
      if (!st) break
      if (i % CHECKPOINT === 0) this.checkpoints[i / CHECKPOINT] = new Map(this.writes)
      if (st.out) this.out += st.out
      this.outLen[i] = this.out.length
      // Строка шага — выполненная им команда; у шага 0 её нет.
      if (i > 0 && st.line != null) this.hits.set(st.line, (this.hits.get(st.line) ?? 0) + 1)
      while (this.reads.length < st.stdin_pos) this.reads.push(i)
      for (const w of st.mem) applyWrite(this.writes, w, i)
      this.scanned = i + 1
    }
    return this.scanned !== before
  }

  /** Записи в память, сделанные к шагу k; `null` — трасса до k ещё не прочитана. */
  writesAt(getStep: (i: number) => AsmStep | undefined, k: number): Map<number, Cell> | null {
    if (k >= this.scanned) return null
    if (this.lastMem?.k === k) return this.lastMem.map
    const cpIndex = Math.floor(k / CHECKPOINT)
    const base = this.checkpoints[cpIndex]
    if (!base) return null
    const map = new Map(base)
    for (let i = cpIndex * CHECKPOINT; i <= k; i++) {
      const st = getStep(i)
      if (!st) {
        if (isSkipped(this.run, i)) continue
        return null
      }
      for (const w of st.mem) applyWrite(map, w, i)
    }
    this.lastMem = { k, map }
    return map
  }
}

function applyWrite(map: Map<number, Cell>, w: AsmStep['mem'][number], step: number) {
  const seg = parseHex(w.seg)
  const off = parseHex(w.off)
  if (seg == null || off == null) return
  hexBytes(w.new).forEach((v, j) => map.set(linear({ seg, off: off + j }), { v, s: step }))
}

const scans = new Map<string, TraceScan>()

/** Проход для прогона. Ключ включает статус: трасса идущего прогона ещё растёт, законченного — уже нет. */
export function scanFor(programId: string, run: AsmRunSummary): TraceScan {
  const key = `${programId}:${run.run_no}:${run.status}:${run.totals.steps}`
  let s = scans.get(key)
  if (!s) {
    // Держим проходы двух последних прогонов: сравнить с прошлым — обычное дело, дальше память дороже.
    if (scans.size >= 2) scans.delete(scans.keys().next().value as string)
    s = new TraceScan(run)
    scans.set(key, s)
  }
  return s
}

/**
 * Проход по трассе для окна. `to` — докуда читать: `'current'` — до текущего
 * шага, `'end'` — до конца (нужно, чтобы показать будущий вывод и счётчики за
 * весь прогон). Скрытая вкладка (`enabled = false`) трассу не читает и страниц
 * не просит.
 */
export function useTraceScan(to: 'current' | 'end', enabled: boolean): TraceScan | null {
  const { run, programId, getStep, stepIndex } = useAsm()
  const [, setTick] = useState(0)
  const scan = run && hasTrace(run) ? scanFor(programId, run) : null
  const target = to === 'end' ? lastStepIndex(run) : stepIndex
  useEffect(() => {
    if (!scan || !enabled) return
    if (scan.advance(getStep, target) && scan.scanned <= target) {
      // Бюджет кадра кончился, а шаги ещё есть: продолжить в следующем кадре.
      const id = requestAnimationFrame(() => setTick((n) => n + 1))
      return () => cancelAnimationFrame(id)
    }
    return undefined
  })
  return scan
}

/* ── память на шаге ────────────────────────────────────────────────────────── */

export interface MemView {
  /** Байт по линейному адресу; `null` — неизвестен: не попал ни в один дамп и не записывался. */
  get(addr: number): number | null
  /** Адреса, записанные именно этим шагом. */
  changed: Set<number>
  /** Адреса, в которые трасса писала к этому шагу. */
  written: Set<number>
  /** С какого шага дампа взят байт (для подсказки «по дампу шага N»). */
  dumpStep(addr: number): number | null
}

/**
 * Память на шаге k: дампы (прогона и дочитанные) не позже k, поверх — записи
 * трассы. Из двух источников побеждает более поздний: дамп после шага s уже
 * учитывает всё записанное до s.
 */
export function memView(scan: TraceScan | null, run: AsmRunSummary | undefined, step: AsmStep | undefined, k: number, getStep: (i: number) => AsmStep | undefined): MemView {
  const dumped = new Map<number, Cell>()
  const dumps = [...(run?.dumps ?? []), ...(scan?.extraDumps ?? [])].filter((d) => d.step <= k).sort((a, b) => a.step - b.step)
  for (const d of dumps) {
    const seg = parseHex(d.seg)
    const off = parseHex(d.off)
    if (seg == null || off == null) continue
    hexBytes(d.hex).forEach((v, j) => dumped.set(linear({ seg, off: off + j }), { v, s: d.step }))
  }
  const writes = scan?.writesAt(getStep, k) ?? null
  const changed = new Set<number>()
  if (step) for (const w of step.mem) {
    const seg = parseHex(w.seg)
    const off = parseHex(w.off)
    if (seg == null || off == null) continue
    hexBytes(w.new).forEach((_, j) => changed.add(linear({ seg, off: off + j })))
  }
  const written = new Set<number>(writes ? writes.keys() : [])
  return {
    get(addr) {
      const d = dumped.get(addr)
      const w = writes?.get(addr)
      if (d && w) return w.s > d.s ? w.v : d.v
      return (w ?? d)?.v ?? null
    },
    changed,
    written,
    dumpStep(addr) {
      return dumped.get(addr)?.s ?? null
    },
  }
}

/** Хук поверх `memView` для текущего шага. */
export function useMemView(enabled: boolean): { mem: MemView; scan: TraceScan | null } {
  const { run, step, stepIndex, getStep } = useAsm()
  const scan = useTraceScan('current', enabled)
  return { mem: memView(scan, run, step, stepIndex, getStep), scan }
}

/* ── окно строк ────────────────────────────────────────────────────────────── */

/**
 * Виртуальный список строк одинаковой высоты.
 *
 * Листинг на тысячу строк и вывод на сто тысяч шагов рисуются целиком за
 * секунды и тормозят каждый шаг; видно же из них три десятка. Поэтому
 * рисуется только видимое плюс запас, а высота прокрутки держится пустыми
 * отступами сверху и снизу.
 */
export function useRowWindow(count: number, opts?: { row?: number; header?: number; overscan?: number }) {
  const row = opts?.row ?? ROW
  const header = opts?.header ?? 0
  const overscan = opts?.overscan ?? 10
  const ref = useRef<HTMLDivElement | null>(null)
  const [view, setView] = useState({ top: 0, height: 480 })

  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    const update = () => setView({ top: el.scrollTop, height: el.clientHeight })
    update()
    el.addEventListener('scroll', update, { passive: true })
    const ro = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(update) : null
    ro?.observe(el)
    return () => {
      el.removeEventListener('scroll', update)
      ro?.disconnect()
    }
  }, [])

  const first = Math.max(0, Math.floor((view.top - header) / row) - overscan)
  const last = Math.min(count, Math.ceil((view.top - header + view.height) / row) + overscan)

  /** Прокрутить к строке, если её не видно; `center` — поставить посередине. */
  const reveal = useCallback(
    (index: number, center = true) => {
      const el = ref.current
      if (!el || index < 0) return
      const y = header + index * row
      const visibleTop = el.scrollTop + header
      const visibleBottom = el.scrollTop + el.clientHeight - row
      if (y >= visibleTop && y <= visibleBottom) return
      el.scrollTop = center ? Math.max(0, y - el.clientHeight / 2) : y < visibleTop ? y - header : y - el.clientHeight + row * 2
    },
    [header, row],
  )

  return {
    ref,
    first,
    last,
    /** Первая строка, видимая на экране (без запаса). */
    visibleFirst: Math.max(0, Math.floor((view.top - header) / row)),
    padTop: first * row,
    padBottom: Math.max(0, (count - last) * row),
    reveal,
    height: view.height,
  }
}

/* ── якорь: подпись, справка, контекстное меню ─────────────────────────────── */

/** Слово для справки по якорю: мнемоника строки, имя регистра или флага. */
export function docTokenOf(anchor: AsmAnchor, lineText?: (line: number) => string | undefined, mnemonic?: (text: string) => string | null): string | null {
  if (anchor.kind === 'register' || anchor.kind === 'flag') return anchor.name.toUpperCase()
  if (anchor.kind === 'line' && lineText && mnemonic) {
    const text = lineText(anchor.line)
    return text ? mnemonic(text) : null
  }
  return null
}

export function sameAnchor(a: AsmAnchor | null, b: AsmAnchor): boolean {
  if (!a || a.kind !== b.kind) return false
  switch (b.kind) {
    case 'line':
      return a.kind === 'line' && a.line === b.line
    case 'register':
    case 'flag':
      return (a.kind === 'register' || a.kind === 'flag') && a.name.toUpperCase() === b.name.toUpperCase()
    case 'cell':
      return a.kind === 'cell' && parseHex(a.seg) === parseHex(b.seg) && parseHex(a.off) === parseHex(b.off)
    case 'doc':
      return a.kind === 'doc' && a.id === b.id
    case 'text':
      return a.kind === 'text' && a.window === b.window && a.text === b.text
    default:
      return true
  }
}

export function cellAnchor(a: Addr): AsmAnchor {
  return { kind: 'cell', seg: hex(a.seg), off: hex(a.off & 0xffff) }
}

/** Подпись якоря для заголовка меню. */
export function anchorLabel(anchor: AsmAnchor): string {
  switch (anchor.kind) {
    case 'line':
      return t('asm.ctx.line', { line: anchor.line })
    case 'register':
      return t('asm.ctx.register', { name: anchor.name.toUpperCase() })
    case 'flag':
      return t('asm.ctx.flag', { name: anchor.name.toUpperCase() })
    case 'cell':
      return t('asm.ctx.cell', { addr: `${anchor.seg}:${anchor.off}` })
    case 'doc':
      return anchor.id
    case 'text':
      return t('asm.ctx.text')
    default:
      return t('asm.ctx.run')
  }
}

export interface AnchorMenuState {
  x: number
  y: number
  anchor: AsmAnchor
  /** Слово для пункта «Справка», если есть. */
  token: string | null
  /** Выделенный в окне текст на момент щелчка: пункт «Спросить агента про выделенное». */
  text: TextAnchor | null
}

type MenuPoint = { clientX: number; clientY: number; preventDefault(): void }

/**
 * Контекстное меню якоря: «Спросить агента», «Справка», и дальше по виду якоря —
 * точка останова и «до этой строки» у строки, «в наблюдение» у регистра, флага
 * и ячейки, «показать в дампе» у указателей и ячеек. Выделен в окне текст —
 * следом за «Спросить агента» идёт «Спросить агента про выделенное». Меню,
 * открытое прямо на выделенном тексте (`anchor.kind === 'text'`), — только этот
 * пункт: в «Выводе» или логе сборки строки и регистра под щелчком нет.
 *
 * Меню — выпадающее меню кита, открытое на невидимом якоре в точке щелчка:
 * клавиатура, `Esc`, фокус и роли у него уже правильные, второе меню со своими
 * правилами окну не нужно.
 */
export function useAnchorMenu(): {
  open: (e: MenuPoint, anchor: AsmAnchor, token?: string | null, text?: TextAnchor | null) => void
  element: ReactNode
} {
  const asm = useAsm()
  const [state, setState] = useState<AnchorMenuState | null>(null)

  const open = (e: MenuPoint, anchor: AsmAnchor, token: string | null = null, text: TextAnchor | null = null) => {
    e.preventDefault()
    // Выделенный текст привязкой становится только по «Спросить»: щелчок правой
    // кнопкой по выводу не должен менять, о чём спросит Ctrl+J.
    if (anchor.kind !== 'text') asm.select(anchor)
    if (anchor.kind === 'line') asm.setCursorLine(anchor.line)
    setState({ x: e.clientX, y: e.clientY, anchor, token, text: anchor.kind === 'text' ? anchor : text })
  }

  let element: ReactNode = null
  if (state) {
    const { anchor, token, text } = state
    const close = () => setState(null)
    const items: ReactNode[] = [createElement(MenuLabel, { key: 'label', children: anchorLabel(anchor) })]
    const item = (key: string, label: string, onSelect: () => void) => createElement(MenuItem, { key, onSelect }, label)
    if (anchor.kind !== 'text') items.push(item('ask', t('asm.ctx.ask'), () => asm.askAgent(anchor)))
    if (text) items.push(item('askText', t('asm.ctx.askText'), () => asm.askAgent(text)))
    if (token) items.push(item('help', t('asm.ctx.help', { token }), () => asm.openDocs(token)))
    if (anchor.kind === 'line') {
      const bps = asm.settings.breakpoints
      const has = bps.includes(anchor.line)
      items.push(createElement(MenuSeparator, { key: 'sep1' }))
      items.push(
        item('bp', has ? t('asm.ctx.bpRemove') : t('asm.ctx.bpAdd'), () =>
          asm.updateSettings({ breakpoints: has ? bps.filter((l) => l !== anchor.line) : [...bps, anchor.line].sort((a, b) => a - b) }),
        ),
      )
      if (asm.run && hasTrace(asm.run))
        items.push(
          item('cursor', t('asm.ctx.runToLine'), () => {
            asm.setCursorLine(anchor.line)
            asm.runToCursor()
          }),
        )
    }
    const watchExpr = anchor.kind === 'register' || anchor.kind === 'flag' ? anchor.name.toUpperCase() : anchor.kind === 'cell' ? `${anchor.seg}:${anchor.off}` : null
    if (watchExpr) {
      items.push(createElement(MenuSeparator, { key: 'sep2' }))
      items.push(
        item('watch', t('asm.ctx.watch'), () => {
          const w = asm.settings.watches
          if (!w.some((x) => x.toUpperCase() === watchExpr)) asm.updateSettings({ watches: [...w, watchExpr] })
          asm.openWindow('watch', { focus: true })
        }),
      )
    }
    const pointer = anchor.kind === 'register' && ['SI', 'DI', 'BX', 'BP', 'SP', 'DX'].includes(anchor.name.toUpperCase())
    if (pointer || anchor.kind === 'cell') {
      items.push(
        item('dump', t('asm.ctx.toDump'), () => {
          if (anchor.kind === 'cell') asm.select(anchor)
          else {
            const n = anchor.name.toLowerCase()
            const segName = n === 'sp' || n === 'bp' ? 'ss' : n === 'di' ? 'es' : 'ds'
            const seg = reg(asm.step, segName)
            const off = reg(asm.step, n as Reg16)
            if (seg != null && off != null) asm.select(cellAnchor({ seg, off }))
          }
          asm.openWindow('dump', { focus: true })
        }),
      )
    }
    element = createElement(
      MenuRoot,
      { open: true, onOpenChange: (o: boolean) => (o ? undefined : close()), modal: false },
      createElement(MenuTrigger, {
        asChild: true,
        children: createElement('span', {
          'aria-hidden': true,
          style: { position: 'fixed', left: state.x, top: state.y, width: 0, height: 0 },
        }),
      }),
      createElement(MenuContent, { align: 'start', sideOffset: 2, className: 'min-w-[230px] text-xs' }, items),
    )
  }
  return { open, element }
}

/** Сочетание Shift+F10 / клавиша меню на строке окна — открыть меню там, где строка. */
export function isMenuKey(e: { key: string; shiftKey: boolean }): boolean {
  return e.key === 'ContextMenu' || (e.key === 'F10' && e.shiftKey)
}

/** Точка для меню, открытого с клавиатуры: левый край элемента, по вертикали — середина. */
export function menuPointOf(el: Element): { clientX: number; clientY: number; preventDefault(): void } {
  const r = el.getBoundingClientRect()
  return { clientX: r.left + 12, clientY: r.top + r.height / 2, preventDefault() {} }
}

/* ── выделенный текст: якорь, кнопка «Спросить агента», Ctrl+J ─────────────── */

export type TextAnchor = Extract<AsmAnchor, { kind: 'text' }>

/** Потолок выделения, которое уходит агенту, в символах. Служба проверяет тот же. */
export const TEXT_ANCHOR_MAX = 4000

/**
 * Якорь из выделенного текста; пустое или из одних пробелов — `null`.
 *
 * Длиннее потолка — начало с пометкой, сколько было выделено: агент должен
 * знать, что видит не всё, а служба такой якорь не примет вовсе.
 */
export function textAnchor(win: AsmTextWindow, raw: string, lineFrom: number | null = null, lineTo: number | null = null): TextAnchor | null {
  const text = raw.replace(/\r\n?/g, '\n')
  if (!text.trim()) return null
  let body = text
  if (text.length > TEXT_ANCHOR_MAX) {
    const mark = t('asm.agent.truncated', { n: fmtInt(text.length) })
    let end = TEXT_ANCHOR_MAX - mark.length
    // Не резать суррогатную пару: половина символа не переживёт JSON службы.
    if (/[\uD800-\uDBFF]/.test(text.charAt(end - 1))) end--
    body = text.slice(0, end) + mark
  }
  const a = lineFrom ?? lineTo
  const b = lineTo ?? lineFrom
  return {
    kind: 'text',
    window: win,
    text: body,
    line_from: a == null || b == null ? null : Math.min(a, b),
    line_to: a == null || b == null ? null : Math.max(a, b),
  }
}

/**
 * Живые выделения окон для Ctrl+J. Окно кладёт сюда чтение своего выделения;
 * чтение отвечает, только пока выделение действительно «в руках» — выделение
 * DOM внутри окна или фокус в редакторе с непустым выделением. Выделение живое
 * одно на страницу, поэтому первого ответившего достаточно.
 */
const liveText = new Map<AsmTextWindow, () => TextAnchor | null>()

/** Выделенный текст, с которым человек работает сейчас, или `null`. */
export function liveTextAnchor(): TextAnchor | null {
  for (const read of liveText.values()) {
    const a = read()
    if (a) return a
  }
  return null
}

/** Где на экране конец выделения и в каких границах окна его показывать. */
export interface SelectionAt {
  anchor: TextAnchor
  /** Прямоугольник конца выделения; не на экране — `null`. */
  at: { left: number; right: number; top: number; bottom: number } | null
  bounds: { left: number; right: number; top: number; bottom: number }
}

/** Выделение DOM целиком внутри `root`: текст и диапазон. */
export function domSelectionIn(root: HTMLElement | null): { text: string; range: Range } | null {
  const sel = typeof window === 'undefined' ? null : window.getSelection()
  if (!root || !sel || sel.isCollapsed || sel.rangeCount === 0) return null
  const range = sel.getRangeAt(0)
  if (!root.contains(range.commonAncestorContainer)) return null
  const text = sel.toString()
  return text.trim() ? { text, range } : null
}

function rectOf(r: DOMRect | DOMRectReadOnly): SelectionAt['bounds'] {
  return { left: r.left, right: r.right, top: r.top, bottom: r.bottom }
}

/** Примерные размеры кнопки: ставится до того, как её можно измерить. */
const FAB_W = 132
const FAB_H = 22

export interface SelectionAskOptions {
  window: AsmTextWindow
  /** Вкладка на виду: у скрытой кнопка не висит поверх соседних окон. */
  active: boolean
  /** Корень окна: выделение за его пределами — чужое. */
  root: RefObject<HTMLElement | null>
  /**
   * Своё чтение выделения — у редактора, где выделение живёт в его состоянии,
   * а не в DOM. Не задано — выделение DOM внутри `root`.
   */
  read?: () => SelectionAt | null
  /** Строки исходника для выделения DOM — у окна, которое их знает. */
  lines?: (range: Range) => readonly [number | null, number | null]
  /** Текст выделения DOM, если сырой `toString()` окну не годится. */
  textOf?: (range: Range, raw: string) => string
}

/**
 * Выделенный текст окна → вопрос агенту.
 *
 * Даёт плавающую кнопку «Спросить агента» у конца выделения и регистрирует
 * выделение для Ctrl+J. Кнопка — обычная `<button>` сразу за содержимым окна:
 * Tab из окна доходит до неё, `mousedown` на ней не снимает выделение. Снято
 * выделение, фокус ушёл из редактора или вкладка скрыта — кнопки нет.
 *
 * У окон без своего чтения здесь же Ctrl+A: выделяет содержимое окна, а не
 * всю страницу, — так выделить вывод можно и без мыши.
 */
export function useSelectionAsk(opts: SelectionAskOptions): { element: ReactNode; update(): void; current(): TextAnchor | null } {
  const asm = useAsm()
  const [shown, setShown] = useState<SelectionAt | null>(null)
  const o = useRef(opts)
  o.current = opts

  const readNow = useCallback((): SelectionAt | null => {
    const { read, root, window: win, lines, textOf } = o.current
    if (read) return read()
    const el = root.current
    const got = domSelectionIn(el)
    if (!el || !got) return null
    const [from, to] = lines ? lines(got.range) : [null, null]
    const anchor = textAnchor(win, textOf ? textOf(got.range, got.text) : got.text, from, to)
    if (!anchor) return null
    const rects = got.range.getClientRects()
    const last = rects.length > 0 ? rects[rects.length - 1]! : got.range.getBoundingClientRect()
    return { anchor, at: rectOf(last), bounds: rectOf(el.getBoundingClientRect()) }
  }, [])

  const frame = useRef(0)
  const update = useCallback(() => {
    if (frame.current) return
    frame.current = requestAnimationFrame(() => {
      frame.current = 0
      setShown(readNow())
    })
  }, [readNow])

  const win = opts.window
  useEffect(() => {
    const read = () => readNow()?.anchor ?? null
    liveText.set(win, read)
    return () => {
      if (liveText.get(win) === read) liveText.delete(win)
    }
  }, [win, readNow])

  useEffect(() => {
    document.addEventListener('selectionchange', update)
    document.addEventListener('focusin', update)
    window.addEventListener('scroll', update, true)
    window.addEventListener('resize', update)
    return () => {
      document.removeEventListener('selectionchange', update)
      document.removeEventListener('focusin', update)
      window.removeEventListener('scroll', update, true)
      window.removeEventListener('resize', update)
      cancelAnimationFrame(frame.current)
      frame.current = 0
    }
  }, [update])

  const ownRead = !!opts.read
  const { root } = opts
  useEffect(() => {
    const el = root.current
    if (!el || ownRead) return
    const onKey = (e: KeyboardEvent) => {
      if (!(e.ctrlKey || e.metaKey) || e.shiftKey || e.altKey || e.code !== 'KeyA') return
      const target = e.target as HTMLElement | null
      if (target && (target.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName))) return
      e.preventDefault()
      const range = document.createRange()
      range.selectNodeContents(el)
      const sel = window.getSelection()
      sel?.removeAllRanges()
      sel?.addRange(range)
    }
    el.addEventListener('keydown', onKey)
    return () => el.removeEventListener('keydown', onKey)
  }, [root, ownRead])

  let element: ReactNode = null
  const at = shown?.at
  if (shown && at && opts.active) {
    const b = shown.bounds
    if (at.bottom >= b.top && at.top <= b.bottom) {
      const left = Math.max(b.left + 4, Math.min(at.right + 6, b.right - FAB_W - 4))
      let top = at.bottom + 4
      if (top + FAB_H > b.bottom) top = Math.max(b.top + 2, at.top - FAB_H - 4)
      const anchor = shown.anchor
      element = createElement(
        'button',
        {
          type: 'button',
          className: 'askfab',
          style: { left, top },
          title: t('asm.ctx.askFabHint'),
          'data-testid': 'asm-ask-selection',
          onMouseDown: (e: { preventDefault(): void }) => e.preventDefault(),
          onClick: () => asm.askAgent(anchor),
        },
        t('asm.ctx.askFab'),
      )
    }
  }

  return { element, update, current: () => readNow()?.anchor ?? null }
}

/** Строка исходника под узлом: ближайший предок с `data-line`. */
export function lineOfNode(node: Node | null): number | null {
  const el = node instanceof Element ? node : (node?.parentElement ?? null)
  const row = el?.closest('[data-line]')
  const n = row ? Number(row.getAttribute('data-line')) : NaN
  return Number.isInteger(n) && n > 0 ? n : null
}

/** Следующая команда шага: `step.next`; конец программы или нет шага — `null`. */
export function nextOf(step: AsmStep | undefined): NonNullable<AsmStep['next']> | null {
  return step?.next ?? null
}
