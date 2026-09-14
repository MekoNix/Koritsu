/**
 * tasmLanguage — подсветка исходника TASM: для редактора (CodeMirror,
 * `StreamLanguage`) и для строк листинга и точек останова.
 *
 * Разбор один на оба места (`nextToken`): слово, подсвеченное в редакторе как
 * мнемоника, в листинге обязано быть мнемоникой того же цвета, иначе человек
 * решит, что это две разные строки.
 *
 * Грамматики здесь нет и не нужно: ассемблер строчный, и всё, что требуется для
 * цвета, видно из самого слова — директива, команда, регистр, число с суффиксом
 * системы (`0Ah`, `1010b`, `17o`), строка в кавычках, комментарий после `;`.
 * Метка — слово с двоеточием или слово в начале строки перед `db`/`equ`/`proc`.
 * Регистр букв TASM не различает, и разбор тоже.
 */
import { StreamLanguage, type StreamParser } from '@codemirror/language'
import { tags } from '@lezer/highlight'
import { createElement, type ReactNode } from 'react'

const words = (s: string) => new Set(s.trim().split(/\s+/))

/** Команды 8086 и 186/386, которые встречаются в учебных программах. */
export const MNEMONICS = words(`
  aaa aad aam aas adc add and call cbw clc cld cli cmc cmp cmps cmpsb cmpsw cmpsd cwd daa das dec div
  hlt idiv imul in inc int into iret ja jae jb jbe jc jcxz je jg jge jl jle jmp jna jnae jnb jnbe jnc
  jne jng jnge jnl jnle jno jnp jns jnz jo jp jpe jpo js jz lahf lds lea les lock lods lodsb lodsw
  lodsd loop loope loopne loopnz loopz mov movs movsb movsw movsd mul neg nop not or out pop popf push
  pushf rcl rcr rep repe repne repnz repz ret retf retn rol ror sahf sal sar sbb scas scasb scasw
  scasd shl shr stc std sti stos stosb stosw stosd sub test wait xchg xlat xlatb xor
  bound enter leave pusha popa pushad popad pushfd popfd insb insw outsb outsw
  bsf bsr bt btc btr bts cdq cwde movsx movzx shld shrd jecxz iretd lss lfs lgs
  seta setae setb setbe setc sete setg setge setl setle setna setnae setnb setnbe setnc setne setng
  setnge setnl setnle setno setnp setns setnz seto setp setpe setpo sets setz
`)

/** Директивы, операторы выражений и имена моделей памяти. */
export const DIRECTIVES = words(`
  .model .stack .data .data? .code .const .startup .exit .8086 .186 .286 .386 .486 .radix
  model stack dataseg codeseg udataseg startupcode exitcode ideal masm jumps nojumps locals nolocals
  end proc endp segment ends assume group org even align include includelib public extrn extern global
  db dw dd dq dt df dp equ label macro endm local rept irp irpc exitm purge struc union record
  offset seg ptr byte word dword qword fword tbyte far near short type size length sizeof lengthof
  this dup mod shl shr
  tiny small medium compact large huge flat stdcall pascal c uses arg
  if ifdef ifndef ife else elseif endif comment title %out
  @data @code @stack @datasize @codesize @model
`)

export const REGISTERS = words(`
  ax bx cx dx si di bp sp ip al ah bl bh cl ch dl dh cs ds ss es fs gs
  eax ebx ecx edx esi edi ebp esp eip
`)

/** Слова, перед которыми слово в начале строки — метка без двоеточия: `arr db 3, 7`. */
const AFTER_LABEL = /^\s+(db|dw|dd|dq|dt|df|dp|equ|proc|segment|macro|struc|union|record|label|group|=)(?![\w@?$.])/i

export type TasmTokenKind = 'space' | 'comment' | 'string' | 'number' | 'directive' | 'mnemonic' | 'register' | 'label' | 'ref' | 'punct'

/** Токен строки с позиции `pos`: где кончается и что это. */
export function nextToken(s: string, pos: number): { end: number; kind: TasmTokenKind } {
  const ch = s[pos] ?? ''
  if (/\s/.test(ch)) {
    let end = pos + 1
    while (end < s.length && /\s/.test(s[end]!)) end++
    return { end, kind: 'space' }
  }
  if (ch === ';') return { end: s.length, kind: 'comment' }
  if (ch === "'" || ch === '"') {
    // Кавычка внутри строки удваивается: 'it''s'. Незакрытая строка тянется до конца.
    let end = pos + 1
    while (end < s.length) {
      if (s[end] === ch) {
        if (s[end + 1] === ch) end += 2
        else return { end: end + 1, kind: 'string' }
      } else end++
    }
    return { end: s.length, kind: 'string' }
  }
  if (/[0-9]/.test(ch)) {
    const m = /^[0-9][0-9a-z]*/i.exec(s.slice(pos))
    return { end: pos + (m ? m[0].length : 1), kind: 'number' }
  }
  if (/[a-z_@?$.%]/i.test(ch)) {
    const m = /^[a-z_@?$.%][\w@?$.]*/i.exec(s.slice(pos))
    const word = m ? m[0] : ch
    const end = pos + word.length
    const w = word.toLowerCase()
    const isReg = REGISTERS.has(w)
    if (!isReg && s[end] === ':' && !DIRECTIVES.has(w) && !MNEMONICS.has(w)) return { end, kind: 'label' }
    if (!isReg && !DIRECTIVES.has(w) && !MNEMONICS.has(w) && s.slice(0, pos).trim() === '' && AFTER_LABEL.test(s.slice(end)))
      return { end, kind: 'label' }
    if (DIRECTIVES.has(w)) return { end, kind: 'directive' }
    if (MNEMONICS.has(w)) return { end, kind: 'mnemonic' }
    if (isReg) return { end, kind: 'register' }
    return { end, kind: 'ref' }
  }
  return { end: pos + 1, kind: 'punct' }
}

export function tokenize(line: string): { text: string; kind: TasmTokenKind }[] {
  const out: { text: string; kind: TasmTokenKind }[] = []
  let pos = 0
  while (pos < line.length) {
    const { end, kind } = nextToken(line, pos)
    out.push({ text: line.slice(pos, end), kind })
    pos = end
  }
  return out
}

/** Слово строки для справки: первая команда, а без неё — первая директива. */
export function mnemonicOf(line: string): string | null {
  const toks = tokenize(line)
  const m = toks.find((x) => x.kind === 'mnemonic') ?? toks.find((x) => x.kind === 'directive')
  return m ? m.text.toLowerCase() : null
}

/** Классы цвета токена в строках окон (`styles.css` модуля) — те же переменные темы, что у редактора. */
export const TOKEN_CLASS: Record<TasmTokenKind, string> = {
  space: '',
  punct: '',
  comment: 't-cm',
  string: 't-str',
  number: 't-num',
  directive: 't-kw',
  mnemonic: 't-mn',
  register: 't-reg',
  label: 't-lbl',
  ref: 't-ref',
}

/** Строка исходника цветными кусками — для листинга и списка точек. */
export function tasmSpans(line: string): ReactNode[] {
  return tokenize(line).map((tok, i) =>
    tok.kind === 'space' || tok.kind === 'punct' ? tok.text : createElement('span', { key: i, className: TOKEN_CLASS[tok.kind] }, tok.text),
  )
}

const parser: StreamParser<null> = {
  name: 'tasm',
  startState: () => null,
  token(stream) {
    const { end, kind } = nextToken(stream.string, stream.pos)
    stream.pos = Math.max(end, stream.pos + 1)
    return kind === 'space' || kind === 'punct' ? null : kind
  },
  languageData: { commentTokens: { line: ';' } },
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

/** Язык TASM для CodeMirror. */
export const tasmLanguage = StreamLanguage.define(parser)
