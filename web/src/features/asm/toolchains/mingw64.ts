/**
 * mingw64 — описатель режима MinGW x64: консольная программа Windows x64 на GAS,
 * сборка GNU `as` и `ld`, трасса без захода в kernel32.
 *
 * Память плоская: адрес — одно 64-битное число, показывается 16 знаками hex.
 * Регистры — только 64 бит, без переключателя; сегментные показываются
 * свёрнутыми. Флаги RFLAGS подписаны `0`/`1` — мнемоник DebugX в Windows нет.
 * Засечка на дорожке — шаг, выполнивший вызов API целиком (`step.call`).
 *
 * Значения берутся из `windows/flat.ts` и `windows/winapi.ts`: оба модуля не
 * читают `store.tsx`, поэтому круга загрузки нет. Подсветка и справка — лениво.
 */
import type { StreamLanguage } from '@codemirror/language'

import { hex16, parseFlatRef, regNum, RFLAGS } from '../windows/flat'
import type { AsmFlagDef, AsmToolchainDef } from './index'

function joinFlags(parts: readonly string[]): string {
  return parts.filter(Boolean).join(' ').replace(/ {2,}/g, ' ')
}

/** Каталог библиотек в команде лабы (MSYS2 UCRT64); на сервере его подставляет ядро. */
const LAB_LIB_DIR = 'c:\\msys64\\ucrt64\\lib'

export const MINGW64: AsmToolchainDef = {
  id: 'mingw64',
  memory: 'flat',
  bits: 64,
  bitsSwitch: false,
  // Две группы `general`: у окна x64 старые общие и R8–R15 стоят разными блоками.
  registers: [
    { id: 'general', names: ['rax', 'rbx', 'rcx', 'rdx'] },
    { id: 'index', names: ['rsi', 'rdi', 'rbp', 'rsp'] },
    { id: 'general', names: ['r8', 'r9', 'r10', 'r11', 'r12', 'r13', 'r14', 'r15'] },
    { id: 'ip', names: ['rip', 'rflags'] },
    { id: 'segment', names: ['cs', 'ds', 'ss', 'es', 'fs', 'gs'] },
  ],
  flags: RFLAGS.map((f): AsmFlagDef => ({ name: f.name, bit: f.bit, label: f.label })),
  stages: ['as', 'ld', 'trace'],
  tools: ['as', 'ld'],
  titles: { raw: 'asm64.tabs.raw', env: 'asm64.keys.env' },
  language: () =>
    import('../windows/gasLanguage').then((m) => ({
      language: m.gasLanguage as StreamLanguage<unknown>,
      spans: m.gasSpans,
      mnemonicOf: m.mnemonicOf,
    })),
  docs: () => import('../docs/entries64').then((m) => m.DOC_ENTRIES_64),
  addr: {
    width: 16,
    // Разбор без чтения памяти: `[rsp]` даёт адрес ячейки, значение по нему
    // читает окно, у которого есть память шага.
    parse: (text, step, run) => {
      const ref = parseFlatRef(text, step, run)
      return ref ? { seg: null, off: ref.addr } : null
    },
    fmt: (a) => hex16(a.off),
    linear: (a) => a.off,
    sp: (step) => regNum(step, 'rsp'),
  },
  isSysCall: (step) => step.call != null,
  buildFlags: {
    keys: ['as_flags', 'ld_flags'],
    // Команды — как в build.bat лабы; `-a=`, `-o`, `-L`, `-lkernel32` сайт ставит сам.
    preview: (s, base) =>
      `${joinFlags(['as', ...s.as_flags, `-a=${base}.lst`, `${base}.s`, '-o', `${base}.obj`])}\n` +
      joinFlags(['ld', ...s.ld_flags, '-o', `${base}.exe`, `${base}.obj`, '-L', LAB_LIB_DIR, '-lkernel32']),
  },
}
