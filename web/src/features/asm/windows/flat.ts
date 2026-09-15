/**
 * flat — плоская память Windows x64 для окон режима MinGW x64: числа 64 бит,
 * регистры и их части, RFLAGS, секции и символы образа, разбор адреса, чтение
 * памяти, вызовы API и происхождение слов в стеке.
 *
 * ── Почему отдельный файл и без `store` ────────────────────────────────────
 *
 * Описатель режима (`toolchains/mingw64.ts`) берёт отсюда разбор и формат
 * адреса при загрузке модуля, а `store.tsx` загружает описатели. Импорт
 * `store` или `format.ts` здесь замкнул бы круг, поэтому модуль чистый: только
 * функции над данными прогона. Хуки, которым нужен `useAsm()`, живут в окнах и
 * в `format.ts`.
 *
 * ── Числа ───────────────────────────────────────────────────────────────────
 *
 * Значения регистров — `bigint`: `mov rcx, -11` даёт `FFFFFFFFFFFFFFF5`, и в
 * `number` это число теряет младшие разряды. Адреса — `number`: у образа
 * `0x140001000`, у стека ещё меньше, всё ниже 2^53. Побитовые операции JS
 * режут до 32 бит, поэтому с адресами здесь только арифметика.
 */
import { isFlatLoad, type AsmRunSummary, type AsmStep } from '../types'

import { argSlot, winapi, type WinFunction, type WinParam } from './winapi'

/* ── числа ─────────────────────────────────────────────────────────────────── */

const MASK64 = (1n << 64n) - 1n

/** Hex службы в число; мусор или больше 2^53 — `null`. */
export function hexNum(h: string | null | undefined): number | null {
  if (h == null) return null
  const s = h.trim().replace(/^0x/i, '').replace(/h$/i, '')
  if (!/^[0-9a-f]{1,16}$/i.test(s)) return null
  const n = parseInt(s, 16)
  return Number.isSafeInteger(n) ? n : null
}

/** Hex службы в `bigint`; мусор — `null`. */
export function hexBig(h: string | null | undefined): bigint | null {
  if (h == null) return null
  const s = h.trim().replace(/^0x/i, '').replace(/h$/i, '')
  if (!/^[0-9a-f]{1,16}$/i.test(s)) return null
  return BigInt(`0x${s}`)
}

/** Адрес 16 знаками hex без `0x`: `0000000140001000`. */
export function hex16(n: number): string {
  if (!Number.isFinite(n) || n < 0) return '0'.repeat(16)
  return BigInt(Math.floor(n)).toString(16).toUpperCase().padStart(16, '0')
}

/** Значение `bigint` в hex ровно `digits` знаков (лишнее старшее отрезается). */
export function hexOf(v: bigint, digits: number): string {
  const mask = (1n << BigInt(digits * 4)) - 1n
  return (v & mask).toString(16).toUpperCase().padStart(digits, '0')
}

/** Число со знаком из `bits` младших бит. */
export function signed(v: bigint, bits: number): bigint {
  return BigInt.asIntN(bits, v)
}

/** Разряды по-русски и для `bigint`: `4 294 967 295`. */
export function fmtBig(v: bigint): string {
  const neg = v < 0n
  const s = (neg ? -v : v).toString().replace(/\B(?=(\d{3})+(?!\d))/g, ' ')
  return neg ? `−${s}` : s
}

/** `bigint` в `number`, если помещается точно; иначе `null`. */
export function bigToNum(v: bigint | null): number | null {
  if (v == null || v < 0n || v > BigInt(Number.MAX_SAFE_INTEGER)) return null
  return Number(v)
}

/* ── регистры ──────────────────────────────────────────────────────────────── */

export const REG64_GENERAL = ['rax', 'rbx', 'rcx', 'rdx'] as const
export const REG64_POINTER = ['rsi', 'rdi', 'rbp', 'rsp'] as const
export const REG64_EXT = ['r8', 'r9', 'r10', 'r11', 'r12', 'r13', 'r14', 'r15'] as const
export const REG64_SEGMENT = ['cs', 'ds', 'ss', 'es', 'fs', 'gs'] as const

/** Часть регистра: какой 64-битный, сдвиг и ширина в битах. */
export interface SubReg {
  base: string
  shift: 0 | 8
  bits: 8 | 16 | 32 | 64
}

const LEGACY: Record<string, { e: string; w: string; l: string; h?: string }> = {
  rax: { e: 'eax', w: 'ax', l: 'al', h: 'ah' },
  rbx: { e: 'ebx', w: 'bx', l: 'bl', h: 'bh' },
  rcx: { e: 'ecx', w: 'cx', l: 'cl', h: 'ch' },
  rdx: { e: 'edx', w: 'dx', l: 'dl', h: 'dh' },
  rsi: { e: 'esi', w: 'si', l: 'sil' },
  rdi: { e: 'edi', w: 'di', l: 'dil' },
  rbp: { e: 'ebp', w: 'bp', l: 'bpl' },
  rsp: { e: 'esp', w: 'sp', l: 'spl' },
}

const SUBREGS: Record<string, SubReg> = (() => {
  const out: Record<string, SubReg> = {}
  for (const [base, p] of Object.entries(LEGACY)) {
    out[base] = { base, shift: 0, bits: 64 }
    out[p.e] = { base, shift: 0, bits: 32 }
    out[p.w] = { base, shift: 0, bits: 16 }
    out[p.l] = { base, shift: 0, bits: 8 }
    if (p.h) out[p.h] = { base, shift: 8, bits: 8 }
  }
  for (const base of REG64_EXT) {
    out[base] = { base, shift: 0, bits: 64 }
    out[`${base}d`] = { base, shift: 0, bits: 32 }
    out[`${base}w`] = { base, shift: 0, bits: 16 }
    out[`${base}b`] = { base, shift: 0, bits: 8 }
    out[`${base}l`] = { base, shift: 0, bits: 8 }
  }
  out.rip = { base: 'rip', shift: 0, bits: 64 }
  out.eip = { base: 'rip', shift: 0, bits: 32 }
  out.rflags = { base: 'rflags', shift: 0, bits: 64 }
  out.eflags = { base: 'rflags', shift: 0, bits: 32 }
  out.flags = { base: 'rflags', shift: 0, bits: 16 }
  for (const s of REG64_SEGMENT) out[s] = { base: s, shift: 0, bits: 16 }
  return out
})()

/** Регистр или его часть по имени (`eax`, `r8d`, `sil`, `ah`); незнакомое имя — `null`. */
export function subRegister(name: string): SubReg | null {
  return SUBREGS[name.trim().toLowerCase()] ?? null
}

/** Части 64-битного регистра по убыванию: `rax` → `eax ax ah al`, `r8` → `r8d r8w r8b`. */
export function regParts(base: string): string[] {
  const b = base.toLowerCase()
  const p = LEGACY[b]
  if (p) return [p.e, p.w, ...(p.h ? [p.h] : []), p.l]
  if ((REG64_EXT as readonly string[]).includes(b)) return [`${b}d`, `${b}w`, `${b}b`]
  return []
}

/** Значение регистра или части; нет шага или регистра — `null`. */
export function regBig(step: AsmStep | undefined, name: string): bigint | null {
  const sub = subRegister(name)
  if (!step || !sub) return null
  const v = hexBig(step.reg[sub.base])
  if (v == null) return null
  const mask = (1n << BigInt(sub.bits)) - 1n
  return (v >> BigInt(sub.shift)) & mask
}

/** Значение регистра числом — для адресов (RSP, RBP, RIP); не помещается — `null`. */
export function regNum(step: AsmStep | undefined, name: string): number | null {
  return bigToNum(regBig(step, name))
}

/** Байт в регистре или части. */
export function regBytes(name: string): 1 | 2 | 4 | 8 {
  const bits = subRegister(name)?.bits ?? 64
  return (bits / 8) as 1 | 2 | 4 | 8
}

/* ── RFLAGS ────────────────────────────────────────────────────────────────── */

/** Флаги RFLAGS в порядке показа, подпись значения — просто `0`/`1`. */
export const RFLAGS = [
  { name: 'OF', bit: 11, label: ['0', '1'] },
  { name: 'DF', bit: 10, label: ['0', '1'] },
  { name: 'IF', bit: 9, label: ['0', '1'] },
  { name: 'TF', bit: 8, label: ['0', '1'] },
  { name: 'SF', bit: 7, label: ['0', '1'] },
  { name: 'ZF', bit: 6, label: ['0', '1'] },
  { name: 'AF', bit: 4, label: ['0', '1'] },
  { name: 'PF', bit: 2, label: ['0', '1'] },
  { name: 'CF', bit: 0, label: ['0', '1'] },
] as const

export type Flag64 = (typeof RFLAGS)[number]['name']

export function isFlag64(s: string): s is Flag64 {
  return RFLAGS.some((f) => f.name === s.trim().toUpperCase())
}

export function flagBitOf(rflags: bigint, name: Flag64): 0 | 1 {
  const f = RFLAGS.find((x) => x.name === name)!
  return Number((rflags >> BigInt(f.bit)) & 1n) as 0 | 1
}

/** Флаги записью gdb `info registers`: `[ ZF PF IF ]` — установленные, от младшего бита. */
export function gdbFlags(rflags: bigint): string {
  const on = [...RFLAGS].sort((a, b) => a.bit - b.bit).filter((f) => flagBitOf(rflags, f.name) === 1)
  return `[ ${on.map((f) => f.name).join(' ')}${on.length ? ' ' : ''}]`
}

/* ── образ: загрузка, секции, символы ─────────────────────────────────────── */

export interface FlatLoad {
  imageBase: number | null
  entry: number | null
  /** RSP при входе в программу. */
  rsp: number | null
}

export function flatLoad(run: AsmRunSummary | undefined): FlatLoad | null {
  const l = run?.load
  if (!isFlatLoad(l)) return null
  return { imageBase: hexNum(l.image_base), entry: hexNum(l.entry), rsp: hexNum(l.rsp) }
}

export interface FlatSection {
  name: string
  cls: string
  start: number
  length: number
  /** Первый адрес за секцией. */
  end: number
}

export interface FlatSymbol {
  name: string
  addr: number
  size: number | null
  section: string
  kind: string
  /** Метка кода, а не переменная. */
  code: boolean
}

export interface FlatImage {
  sections: FlatSection[]
  symbols: FlatSymbol[]
  /** Только переменные (не код): подписи в дампе и наблюдении. */
  data: FlatSymbol[]
}

const CODE_KINDS = new Set(['text', 'code', 'func', 'label', 'proc', 't'])

const images = new WeakMap<AsmRunSummary, FlatImage>()

/** Секции и символы прогона, отсортированные по адресу; считаются один раз на сводку. */
export function flatImage(run: AsmRunSummary | undefined): FlatImage {
  if (!run) return { sections: [], symbols: [], data: [] }
  const had = images.get(run)
  if (had) return had
  const sections: FlatSection[] = []
  for (const s of run.build?.segments ?? []) {
    const start = hexNum(s.start)
    const length = hexNum(s.length) ?? 0
    if (start == null) continue
    sections.push({ name: s.name, cls: s.cls, start, length, end: start + length })
  }
  sections.sort((a, b) => a.start - b.start)
  const clsOf = new Map(sections.map((s) => [s.name, s.cls.toUpperCase()]))
  const symbols: FlatSymbol[] = []
  for (const s of run.build?.symbols ?? []) {
    const addr = hexNum(s.offset)
    if (addr == null) continue
    const cls = clsOf.get(s.segment) ?? ''
    const code = cls === 'CODE' || CODE_KINDS.has(s.kind.toLowerCase())
    symbols.push({ name: s.name, addr, size: s.size, section: s.segment, kind: s.kind, code })
  }
  symbols.sort((a, b) => a.addr - b.addr)
  const img = { sections, symbols, data: symbols.filter((s) => !s.code) }
  images.set(run, img)
  return img
}

export function sectionAt(sections: readonly FlatSection[], addr: number): FlatSection | null {
  return sections.find((s) => addr >= s.start && addr < Math.max(s.end, s.start + 1)) ?? null
}

/**
 * Символ, в который попадает адрес. Размер известен — по размеру; нет — до
 * следующего символа той же секции, но не дальше конца секции.
 */
export function symbolAt(
  img: FlatImage,
  addr: number,
  list: readonly FlatSymbol[] = img.data,
): { sym: FlatSymbol; index: number; rel: number } | null {
  for (let i = list.length - 1; i >= 0; i--) {
    const s = list[i]!
    if (addr < s.addr) continue
    let end: number
    if (s.size != null && s.size > 0) end = s.addr + s.size
    else {
      const next = list.slice(i + 1).find((x) => x.addr > s.addr)
      const sec = img.sections.find((x) => x.name === s.section)
      end = Math.min(next ? next.addr : Infinity, sec ? sec.end : s.addr + 1)
      if (!Number.isFinite(end)) end = s.addr + 1
    }
    return addr < end ? { sym: s, index: i, rel: addr - s.addr } : null
  }
  return null
}

/** Адрес кода символом: `main+0x1b`; вне символов — `null`. */
export function symbolize(img: FlatImage, addr: number): string | null {
  let best: FlatSymbol | null = null
  for (const s of img.symbols) {
    if (s.addr > addr) break
    best = s
  }
  if (!best) return null
  const sec = sectionAt(img.sections, addr)
  if (sec && best.section !== sec.name) return null
  const rel = addr - best.addr
  return rel === 0 ? best.name : `${best.name}+0x${rel.toString(16)}`
}

/* ── адреса ────────────────────────────────────────────────────────────────── */

/** Ссылка на память из выражения человека. */
export interface FlatRef {
  addr: number
  /** Выражение в скобках `[…]`: нужно значение по адресу, а не сам адрес. */
  deref: boolean
  /** Размер из `byte/word/dword/qword [ptr]`; не задан — `null`. */
  size: 1 | 2 | 4 | 8 | null
  /** Символ, названный в выражении, если он один. */
  symbol: FlatSymbol | null
}

const SIZE_WORDS: Record<string, 1 | 2 | 4 | 8> = { byte: 1, word: 2, dword: 4, qword: 8 }

/** Число GAS: `0x1F`, `1Fh`, `0b101`, `42`; `hexDefault` — голое число как hex (адрес в отладчике). */
function parseNumber(s: string, hexDefault: boolean): number | null {
  const t = s.trim().toLowerCase()
  let n: number
  if (/^0x[0-9a-f]+$/.test(t)) n = parseInt(t.slice(2), 16)
  else if (/^[0-9][0-9a-f]*h$/.test(t)) n = parseInt(t.slice(0, -1), 16)
  else if (/^0b[01]+$/.test(t)) n = parseInt(t.slice(2), 2)
  else if (hexDefault && /^[0-9a-f]+$/.test(t)) n = parseInt(t, 16)
  else if (/^[0-9]+$/.test(t)) n = parseInt(t, 10)
  else return null
  return Number.isSafeInteger(n) ? n : null
}

/**
 * Выражение адреса: `0x140001000`, `140001000h`, `140001000`, `rsp+32`,
 * `rbx+rsi*8+16`, `message`, `message+8`, `.data`, `rip+message`,
 * `[rip+handle]`, `qword ptr [rsp+32]`.
 *
 * Числа после регистра или символа — по правилам GAS (десятичные, `0x`/`h` —
 * hex): так пишут в исходнике `[rsp+32]`. Одно голое число — hex: так
 * отладчик показывает адреса. `rip+символ` — адрес символа, как в GAS
 * (адресация относительно RIP считается ассемблером).
 */
export function parseFlatRef(text: string, step: AsmStep | undefined, run: AsmRunSummary | undefined): FlatRef | null {
  let s = text.trim()
  if (!s) return null
  let size: FlatRef['size'] = null
  const sized = /^(byte|word|dword|qword)\s+(?:ptr\s+)?(.*)$/i.exec(s)
  if (sized) {
    size = SIZE_WORDS[sized[1]!.toLowerCase()] ?? null
    s = sized[2]!.trim()
  }
  let deref = false
  const br = /^\[\s*(.*?)\s*\]$/.exec(s)
  if (br) {
    deref = true
    s = br[1]!
  }
  if (!s) return null
  const img = flatImage(run)
  // `ah`, `dh`, `face` похожи на hex, но регистр или символ важнее числа.
  const single =
    /^(?:0x[0-9a-f]+|[0-9a-f]+h?)$/i.test(s) && !subRegister(s) && !img.symbols.some((x) => x.name.toLowerCase() === s.toLowerCase())
  if (single) {
    const n = parseNumber(s, true)
    return n == null ? null : { addr: n, deref, size, symbol: null }
  }
  const tokens = s.replace(/\s+/g, '').match(/[+-]?[^+-]+/g)
  if (!tokens) return null
  let sum = 0
  let ripTerm = 0
  let named: FlatSymbol | null = null
  let symbols = 0
  for (const tok of tokens) {
    const sign = tok.startsWith('-') ? -1 : 1
    const body = tok.replace(/^[+-]/, '')
    const [baseText, scaleText, ...rest] = body.split('*')
    if (rest.length || !baseText) return null
    const scale = scaleText == null ? 1 : parseNumber(scaleText, false)
    if (scale == null) return null
    const low = baseText.toLowerCase()
    let v: number | null
    if (low === 'rip') {
      v = regNum(step, 'rip') ?? hexNum(step?.next?.ip)
      if (v == null) return null
      ripTerm += sign * v * scale
      continue
    }
    if (subRegister(low)) {
      const big = regBig(step, low)
      v = bigToNum(big)
    } else if (/^\.[a-z_][\w.$]*$/i.test(baseText)) {
      v = img.sections.find((x) => x.name.toLowerCase() === low)?.start ?? null
    } else if (/^[a-z_.$@?][\w.$@?]*$/i.test(baseText)) {
      const sym = img.symbols.find((x) => x.name === baseText) ?? img.symbols.find((x) => x.name.toLowerCase() === low)
      v = sym?.addr ?? null
      if (sym) {
        named = sym
        symbols++
      }
    } else v = parseNumber(baseText, false)
    if (v == null) return null
    sum += sign * v * scale
  }
  // `rip+символ` — адрес символа; RIP без символа (`rip+0x2ff9`) — настоящая сумма.
  const addr = symbols > 0 ? sum : sum + ripTerm
  if (!Number.isSafeInteger(addr) || addr < 0) return null
  return { addr, deref, size, symbol: symbols === 1 ? named : null }
}

/* ── память ────────────────────────────────────────────────────────────────── */

/** Байт по адресу; неизвестен — `null`. */
export type ByteGetter = (addr: number) => number | null

/** Целое little-endian из `size` байт; хоть один неизвестен — `null`. */
export function readLE(get: ByteGetter, addr: number, size: number): bigint | null {
  let v = 0n
  for (let i = size - 1; i >= 0; i--) {
    const b = get(addr + i)
    if (b == null) return null
    v = (v << 8n) | BigInt(b)
  }
  return v & MASK64
}

/** Строка ASCII по адресу до нуля или `max` байт; неизвестный байт обрывает её. */
export function readText(get: ByteGetter, addr: number, max = 32): { text: string; complete: boolean } | null {
  let text = ''
  for (let i = 0; i < max; i++) {
    const b = get(addr + i)
    if (b == null) return text ? { text, complete: false } : null
    if (b === 0) return { text, complete: true }
    text += b === 10 ? '\\n' : b === 13 ? '\\r' : b === 9 ? '\\t' : b >= 32 && b < 127 ? String.fromCharCode(b) : '·'
  }
  return { text, complete: false }
}

/** Адрес ссылки с учётом `[…]`: значение по адресу читается восемью байтами. */
export function resolveFlatAddress(ref: FlatRef | null, get: ByteGetter): number | null {
  if (!ref) return null
  if (!ref.deref) return ref.addr
  return bigToNum(readLE(get, ref.addr, 8))
}

/* ── вызовы ────────────────────────────────────────────────────────────────── */

export function isCallText(asm: string | null | undefined): boolean {
  return !!asm && /^\s*call[qlw]?\b/i.test(asm)
}

export function isRetText(asm: string | null | undefined): boolean {
  return !!asm && /^\s*ret[qn]?\b/i.test(asm)
}

/** Число байт команды из hex. */
export function byteLen(bytes: string): number {
  return Math.floor(bytes.replace(/[^0-9a-f]/gi, '').length / 2)
}

/** Вызов, который выполнится следующим: функция API (если узнана) и цель. */
export interface PendingCall {
  /** Имя, как его удалось узнать: `WriteFile`, `hextochar`; не узнано — `null`. */
  name: string | null
  fn: WinFunction | null
  /** Вызов уходит в DLL и выполнится одним шагом. */
  api: boolean
}

/**
 * Что вызовет `call` следующей команды шага. Надёжнее всего — поле `call`
 * следующего шага: трасса сама отметила вызов API. Без него — имя из текста
 * команды (`call 0x140001600 <WriteFile>`, `call [rip+__imp_WriteFile]`) или
 * символ по адресу цели.
 */
export function pendingCall(step: AsmStep | undefined, nextStep: AsmStep | undefined, img: FlatImage): PendingCall | null {
  const asm = step?.next?.asm
  if (!isCallText(asm)) return null
  if (nextStep?.call) {
    const fn = winapi(nextStep.call)
    return { name: fn?.name ?? nextStep.call.replace(/^.*\./, ''), fn, api: true }
  }
  const operand = asm!.replace(/^\s*call[qlw]?\s+/i, '')
  let name: string | null = /<([^>+]+)(?:\+[^>]*)?>/.exec(operand)?.[1] ?? null
  if (!name) {
    const m = /(?:0x)?([0-9a-f]{6,16})\b/i.exec(operand)
    const target = m ? hexNum(m[1]) : null
    const hit = target == null ? null : img.symbols.find((x) => x.addr === target)
    name = hit?.name ?? /(?:^|[^\w@])([a-z_][\w@]*)\s*\]?\s*$/i.exec(operand)?.[1] ?? null
  }
  if (name && subRegister(name)) name = null
  // Переходник `WriteFile` в `.text` ставит сам `ld`, поэтому знакомое имя —
  // вызов API, даже если символ с таким именем лежит в секции кода.
  const fn = winapi(name)
  return { name: fn?.name ?? name, fn, api: !!fn }
}

/** Параметр вызова на момент `call`: где лежит и что там. */
export interface CallArg {
  index: number
  param: WinParam
  reg: string | null
  /** Адрес слота в стеке у пятого параметра и дальше. */
  slot: number | null
  /** Значение с учётом размера параметра (DWORD — младшие 32 бита). */
  value: bigint | null
}

/** Параметры функции API на шаге перед `call`: RCX, RDX, R8, R9, `[RSP+32]`… */
export function callArgs(fn: WinFunction, step: AsmStep | undefined, get: ByteGetter): CallArg[] {
  const rsp = regNum(step, 'rsp')
  return fn.params.map((param, index) => {
    const where = argSlot(index)
    const mask = param.size === 4 ? 0xffffffffn : MASK64
    if ('reg' in where) {
      const v = regBig(step, where.reg)
      return { index, param, reg: where.reg, slot: null, value: v == null ? null : v & mask }
    }
    const slot = rsp == null ? null : rsp + where.stack
    const v = slot == null ? null : readLE(get, slot, 8)
    return { index, param, reg: null, slot, value: v == null ? null : v & mask }
  })
}

/* ── происхождение слов в стеке ────────────────────────────────────────────── */

/** Кто положил слово в стек: `call` (адрес возврата), `push rbp` (кадр) или другой `push`. */
export interface StackOrigin {
  step: number
  kind: 'ret' | 'rbp' | 'push'
  addr: number
  /** Сколько байт положено: `push bp` кладёт 2, `call` — 8. */
  size: number
  line: number | null
  asm: string
  /** Что должно лежать в слоте: адрес возврата или значение регистра; неизвестно — `null`. */
  value: bigint | null
  /** Для `call` — куда ушёл вызов. */
  target: number | null
}

/** Сколько шагов разбор берёт за кадр. */
const ORIGIN_BUDGET = 8000

const PUSH_SIZES: Record<string, number> = { 16: 2, 32: 4, 64: 8 }

/**
 * Разметка стека по трассе. Живёт на прогон, читает шаги по порядку и один
 * раз, как проход по трассе в `format.ts`: трасса знает каждый `call` и `push`,
 * поэтому у слова в стеке есть происхождение, а не догадка.
 */
export class StackOrigins {
  scanned = 0
  readonly events: StackOrigin[] = []

  constructor(
    readonly last: number,
    readonly gap: readonly [number, number] | null,
  ) {}

  /** Прочитать шаги до `target` включительно, сколько успеется; `true` — продвинулись. */
  advance(getStep: (i: number) => AsmStep | undefined, target: number): boolean {
    const end = Math.min(target, this.last)
    const before = this.scanned
    let budget = ORIGIN_BUDGET
    while (this.scanned <= end && budget-- > 0) {
      const i = this.scanned
      if (this.gap && i >= this.gap[0] && i < this.gap[1]) {
        this.scanned = this.gap[1]
        continue
      }
      const st = getStep(i)
      if (!st) break
      if (i > 0) this.read(st, getStep(i - 1))
      this.scanned = i + 1
    }
    return this.scanned !== before
  }

  private read(st: AsmStep, prev: AsmStep | undefined) {
    const rsp = regNum(st, 'rsp')
    if (rsp == null) return
    const asm = st.asm.trim()
    if (isCallText(asm) && !st.call) {
      const ip = hexNum(st.ip)
      this.events.push({
        step: st.i,
        kind: 'ret',
        addr: rsp,
        size: 8,
        line: st.line,
        asm,
        value: ip == null ? null : BigInt(ip + byteLen(st.bytes)),
        target: hexNum(st.next?.ip),
      })
      return
    }
    const push = /^push([fqwl]*)\s*(\S*)/i.exec(asm)
    if (!push) return
    const operand = (push[2] ?? '').toLowerCase()
    const sub = subRegister(operand)
    const prevRsp = regNum(prev, 'rsp')
    const size = prevRsp != null && prevRsp > rsp ? prevRsp - rsp : sub ? (PUSH_SIZES[sub.bits] ?? 8) : 8
    const kind = operand === 'rbp' ? 'rbp' : 'push'
    this.events.push({ step: st.i, kind, addr: rsp, size, line: st.line, asm, value: sub ? regBig(prev, operand) : null, target: null })
  }

  /** Последнее событие не позже шага `k`, положившее слово ровно по адресу. */
  at(addr: number, k: number): StackOrigin | null {
    for (let j = this.events.length - 1; j >= 0; j--) {
      const e = this.events[j]!
      if (e.step <= k && e.addr === addr) return e
    }
    return null
  }

  /** Все события не позже `k`, задевающие диапазон `[from, to)`, — последнее на адрес. */
  inRange(from: number, to: number, k: number): Map<number, StackOrigin> {
    const out = new Map<number, StackOrigin>()
    for (let j = this.events.length - 1; j >= 0; j--) {
      const e = this.events[j]!
      if (e.step > k || e.addr < from || e.addr >= to || out.has(e.addr)) continue
      out.set(e.addr, e)
    }
    return out
  }
}

const origins = new Map<string, StackOrigins>()

/** Разметка стека для прогона; ключ тот же, что у прохода по трассе. */
export function stackOriginsFor(programId: string, run: AsmRunSummary, gap: readonly [number, number] | null): StackOrigins {
  const key = `${programId}:${run.run_no}:${run.status}:${run.totals.steps}`
  let o = origins.get(key)
  if (!o) {
    if (origins.size >= 2) origins.delete(origins.keys().next().value as string)
    o = new StackOrigins(Math.max(0, run.totals.steps), gap)
    origins.set(key, o)
  }
  return o
}
