/**
 * gasLanguage — подсветка исходника GNU as (GAS) для x86-64: для редактора
 * (CodeMirror, `StreamLanguage`) и для строк листинга и точек останова.
 *
 * Разбор один на оба места (`nextToken`) — по той же причине, что у TASM:
 * слово, окрашенное в редакторе как команда, в листинге обязано быть командой
 * того же цвета.
 *
 * ── Intel и AT&T одним разбором ──────────────────────────────────────────────
 *
 * Синтаксис у GAS переключается директивами `.intel_syntax` и `.att_syntax` в
 * любом месте файла, а строка листинга приходит без файла вокруг. Поэтому режим
 * разбор не хранит: `%rax` и `rax` — регистр, `$5` — непосредственное число,
 * `movq` — команда `mov` с суффиксом размера, `-8(%rbp)` и `[rbp-8]` — адреса,
 * `qword ptr` — слово размера. Записи двух синтаксисов не пересекаются так,
 * чтобы цвет у одной из них оказался неверным.
 *
 * ── Комментарий и `;` ────────────────────────────────────────────────────────
 *
 * У GAS для x86 (цели Windows и Linux) комментарий — `#` в любом месте строки и
 * блок `/* … *\/`. Точка с запятой — **разделитель команд** в обоих синтаксисах,
 * а не комментарий: `mov rax, 1 ; mov rbx, 2` — две команды, а
 * `mov rax, 1 ; сумма` — ошибка `as` «no such instruction». Поэтому после `;`
 * разбор снова ждёт команду, и привычный по TASM «комментарий» красится как
 * незнакомое имя — ошибка видна до сборки. `/` у этих целей — деление.
 *
 * ── Место в команде ──────────────────────────────────────────────────────────
 *
 * Команда и директива узнаются только в начале команды — в начале строки, после
 * метки или после `;`. Метка `add:` остаётся меткой, `rep movsb` — два слова
 * команды, а имя `loop` в операнде — просто имя.
 */
import { StreamLanguage, type StreamParser } from '@codemirror/language'
import { tags } from '@lezer/highlight'
import { createElement, type ReactNode } from 'react'

import { TOKEN_CLASS, type TasmTokenKind } from './tasmLanguage'

const words = (s: string) => new Set(s.trim().split(/\s+/))

/** Команды x86-64 в записи Intel и имена, которые есть только в AT&T. */
export const GAS_MNEMONICS = words(`
  adc add and bsf bsr bswap bt btc btr bts call cbw cdq cdqe clc cld cli cmc cmp cmpsb cmpsw cmpsd
  cmpsq cmpxchg cpuid cqo cwd cwde dec div enter hlt idiv imul inc int int3 into ja jae jb jbe jc je
  jecxz jrcxz jg jge jl jle jmp jna jnae jnb jnbe jnc jne jng jnge jnl jnle jno jnp jns jnz jo jp jpe
  jpo js jz lahf lea leave lodsb lodsw lodsd lodsq loop loope loopne loopnz loopz mov movabs movsb
  movsw movsd movsq movsx movsxd movzx mul neg nop not or pause pop popf popfq push pushf pushfq rcl
  rcr rdtsc ret retq rol ror sahf sal sar sbb scasb scasw scasd scasq shl shld shr shrd stc std sti
  stosb stosw stosd stosq sub syscall test ud2 xadd xchg xlat xlatb xor
  seta setae setb setbe setc sete setg setge setl setle setna setnae setnb setnbe setnc setne setng
  setnge setnl setnle setno setnp setns setnz seto setp setpe setpo sets setz
  cmova cmovae cmovb cmovbe cmovc cmove cmovg cmovge cmovl cmovle cmovna cmovnae cmovnb cmovnbe cmovnc
  cmovne cmovng cmovnge cmovnl cmovnle cmovno cmovnp cmovns cmovnz cmovo cmovp cmovpe cmovpo cmovs cmovz
  movss movaps movups movapd movupd movd movq addss addsd subss subsd mulss mulsd divss divsd sqrtss
  sqrtsd cvtsi2ss cvtsi2sd cvtss2si cvtsd2si cvttss2si cvttsd2si comiss comisd ucomiss ucomisd pxor
  xorps xorpd andps andpd fld fild fstp fistp
  movs cmps scas lods stos cltq cqto cltd cwtl cbtw cwtd movslq movzbl movzbw movzwl movzbq movzwq
  movsbl movsbw movswl movsbq movswq ljmp lcall lret
`)

/** Префиксы: после них в той же команде снова стоит мнемоника (`rep movsb`). */
const PREFIXES = words('rep repe repz repne repnz lock')

/** Слова операнда Intel-синтаксиса: размер ячейки, `offset`, режим `.intel_syntax`. */
export const GAS_KEYWORDS = words('byte word dword qword tbyte fword xmmword ymmword zmmword ptr offset flat short near far noprefix prefix')

function registerNames(): Set<string> {
  const out = new Set<string>()
  for (const r of ['a', 'b', 'c', 'd']) {
    for (const n of [`r${r}x`, `e${r}x`, `${r}x`, `${r}l`, `${r}h`]) out.add(n)
  }
  for (const r of ['si', 'di', 'bp', 'sp']) {
    for (const n of [`r${r}`, `e${r}`, r, `${r}l`]) out.add(n)
  }
  for (let i = 8; i <= 15; i++) for (const s of ['', 'd', 'w', 'b']) out.add(`r${i}${s}`)
  for (let i = 0; i <= 15; i++) {
    out.add(`xmm${i}`)
    out.add(`ymm${i}`)
  }
  for (let i = 0; i <= 7; i++) {
    out.add(`mm${i}`)
    out.add(`dr${i}`)
  }
  for (const n of 'rip eip ip cs ds ss es fs gs st cr0 cr2 cr3 cr4 cr8'.split(' ')) out.add(n)
  return out
}

export const GAS_REGISTERS = registerNames()

/** Команда ли это слово в начале команды: как есть или с суффиксом размера AT&T (`addq`, `pushl`). */
function isMnemonic(w: string): boolean {
  if (GAS_MNEMONICS.has(w) || PREFIXES.has(w)) return true
  return /^[a-z0-9]+[bwlq]$/.test(w) && GAS_MNEMONICS.has(w.slice(0, -1))
}

export type GasTokenKind = TasmTokenKind

export interface GasToken {
  end: number
  kind: GasTokenKind
  /** Ждёт ли следующий токен начала команды: после метки, `;` и префикса — да. */
  head: boolean
}

/** Минус перед цифрой — знак числа, если перед ним нет операнда: `, -11`, `.float -1.4`, `$-5`. */
function isSign(s: string, pos: number): boolean {
  const before = s[pos - 1]
  if (before === undefined || /\s/.test(before)) return true
  return /[,([$=:;*+]/.test(before)
}

/** Конец числа с позиции `start`: `0x5A`, `0b101`, `-1.4`, `1.5e-3`, `0Ah`. */
function numberEnd(s: string, start: number): number {
  const m = /^(?:0x[0-9a-f]+|0b[01]+|[0-9]+(?:\.[0-9]+(?:e[+-]?[0-9]+)?)?[0-9a-z_]*)/i.exec(s.slice(start))
  return start + (m ? m[0].length : 1)
}

/** Токен строки с позиции `pos`; `head` — стоит ли `pos` в начале команды. */
export function nextToken(s: string, pos: number, head: boolean): GasToken {
  const ch = s[pos] ?? ''
  const after = s[pos + 1] ?? ''

  if (/\s/.test(ch)) {
    let end = pos + 1
    while (end < s.length && /\s/.test(s[end]!)) end++
    return { end, kind: 'space', head }
  }
  if (ch === '#') return { end: s.length, kind: 'comment', head }
  if (ch === '/' && after === '*') {
    const close = s.indexOf('*/', pos + 2)
    return { end: close < 0 ? s.length : close + 2, kind: 'comment', head }
  }
  if (ch === ';') return { end: pos + 1, kind: 'punct', head: true }

  if (ch === '"') {
    let end = pos + 1
    while (end < s.length) {
      if (s[end] === '\\') end += 2
      else if (s[end] === '"') return { end: end + 1, kind: 'string', head: false }
      else end++
    }
    return { end: s.length, kind: 'string', head: false }
  }
  // Символ: '0' и старая запись без закрывающей кавычки '0; '\n' с экранированием.
  if (ch === "'" || (ch === '$' && after === "'")) {
    let end = pos + (ch === '$' ? 2 : 1)
    end += s[end] === '\\' ? 2 : 1
    if (s[end] === "'") end++
    return { end: Math.min(end, s.length), kind: 'string', head: false }
  }

  if (ch === '$' && (/[0-9]/.test(after) || (after === '-' && /[0-9]/.test(s[pos + 2] ?? '')))) {
    return { end: numberEnd(s, after === '-' ? pos + 2 : pos + 1), kind: 'number', head: false }
  }
  if (/[0-9]/.test(ch) || (ch === '-' && /[0-9]/.test(after) && isSign(s, pos))) {
    const start = ch === '-' ? pos + 1 : pos
    const end = numberEnd(s, start)
    // Локальная метка `1:` и ссылки на неё `1f` / `1b`.
    if (ch !== '-' && head && s[end] === ':') return { end, kind: 'label', head: true }
    if (/^[0-9]+[bf]$/i.test(s.slice(start, end))) return { end, kind: 'ref', head: false }
    return { end, kind: 'number', head: false }
  }

  if (ch === '%' && /[a-z]/i.test(after)) {
    const m = /^%[a-z][a-z0-9]*/i.exec(s.slice(pos))
    const end = pos + (m ? m[0].length : 1)
    return { end, kind: GAS_REGISTERS.has(s.slice(pos + 1, end).toLowerCase()) ? 'register' : 'ref', head: false }
  }

  if (/[a-z_.$@?]/i.test(ch)) {
    const m = /^[a-z_.$@?][\w.$@?]*/i.exec(s.slice(pos))
    const word = m ? m[0] : ch
    const end = pos + word.length
    const w = word.toLowerCase()
    const isReg = GAS_REGISTERS.has(w)

    if (head && !isReg && s[end] === ':' && s[end + 1] !== ':') return { end, kind: 'label', head: true }
    if (head && !isReg && /^\s*=(?!=)/.test(s.slice(end))) return { end, kind: 'label', head: false }
    // Точка одна — счётчик адреса: `.-message-1`.
    if (w === '.') return { end, kind: 'directive', head: false }
    if (head) {
      if (w.startsWith('.')) return { end, kind: 'directive', head: false }
      if (PREFIXES.has(w)) return { end, kind: 'mnemonic', head: true }
      if (isMnemonic(w)) return { end, kind: 'mnemonic', head: false }
      return { end, kind: 'ref', head: false }
    }
    if (isReg) return { end, kind: 'register', head: false }
    if (GAS_KEYWORDS.has(w)) return { end, kind: 'directive', head: false }
    return { end, kind: 'ref', head: false }
  }

  return { end: pos + 1, kind: 'punct', head }
}

export function tokenize(line: string): { text: string; kind: GasTokenKind }[] {
  const out: { text: string; kind: GasTokenKind }[] = []
  let pos = 0
  let head = true
  while (pos < line.length) {
    const tok = nextToken(line, pos, head)
    const end = Math.max(tok.end, pos + 1)
    out.push({ text: line.slice(pos, end), kind: tok.kind })
    head = tok.head
    pos = end
  }
  return out
}

/**
 * Слово строки для справки: первая команда без префикса, без неё — префикс, без
 * них — первая директива. Суффикс AT&T не снимается: это делает поиск справки.
 */
export function mnemonicOf(line: string): string | null {
  const toks = tokenize(line)
  const mnemonics = toks.filter((x) => x.kind === 'mnemonic').map((x) => x.text.toLowerCase())
  const m = mnemonics.find((x) => !PREFIXES.has(x)) ?? mnemonics[0]
  if (m) return m
  const d = toks.find((x) => x.kind === 'directive' && x.text !== '.')
  return d ? d.text.toLowerCase() : null
}

/** Строка исходника цветными кусками — для листинга и списка точек. Классы те же, что у TASM. */
export function gasSpans(line: string): ReactNode[] {
  return tokenize(line).map((tok, i) =>
    tok.kind === 'space' || tok.kind === 'punct' ? tok.text : createElement('span', { key: i, className: TOKEN_CLASS[tok.kind] }, tok.text),
  )
}

interface GasState {
  head: boolean
  /** Строка кончилась внутри `/* … *\/`. */
  block: boolean
}

const parser: StreamParser<GasState> = {
  name: 'gas',
  startState: () => ({ head: true, block: false }),
  copyState: (s) => ({ ...s }),
  token(stream, state) {
    if (stream.sol()) state.head = true
    const s = stream.string
    if (state.block) {
      const close = s.indexOf('*/', stream.pos)
      if (close < 0) stream.skipToEnd()
      else {
        stream.pos = close + 2
        state.block = false
      }
      return 'comment'
    }
    const tok = nextToken(s, stream.pos, state.head)
    if (tok.kind === 'comment' && s.startsWith('/*', stream.pos) && s.indexOf('*/', stream.pos + 2) < 0) state.block = true
    state.head = tok.head
    stream.pos = Math.max(tok.end, stream.pos + 1)
    return tok.kind === 'space' || tok.kind === 'punct' ? null : tok.kind
  },
  languageData: { commentTokens: { line: '#', block: { open: '/*', close: '*/' } } },
  tokenTable: {
    comment: tags.lineComment,
    string: tags.string,
    number: tags.number,
    directive: tags.keyword,
    mnemonic: tags.function(tags.variableName),
    register: tags.special(tags.variableName),
    label: tags.labelName,
    ref: tags.variableName,
  },
}

/** Язык GAS (x86-64, Intel и AT&T) для CodeMirror. */
export const gasLanguage = StreamLanguage.define(parser)
