/**
 * tasm — описатель режима TASM: DOS, реальный режим 8086, DebugX.
 *
 * Своей логики здесь нет: описатель оборачивает то, что уже делают
 * `windows/format.ts` (адреса сегмент:смещение, вызовы DOS) и
 * `windows/tasmLanguage.ts` (подсветка), чтобы общие места спрашивали режим, а
 * поведение TASM не менялось.
 *
 * Значения `format.ts` берутся только внутри функций: модуль загружается раньше
 * него (`store.tsx` → `toolchains` → сюда → `format.ts` → `store.tsx`).
 */
import type { StreamLanguage } from '@codemirror/language'

import { dataSymbols, fmtAddr, isDosCall, linear, parseAddress, parseHex } from '../windows/format'
import type { AsmToolchainDef } from './index'

function joinFlags(parts: string[]): string {
  return parts.join(' ').replace(/ {2,}/g, ' ')
}

export const TASM: AsmToolchainDef = {
  id: 'tasm',
  memory: 'segmented',
  bits: 16,
  bitsSwitch: true,
  registers: [
    { id: 'general', names: ['ax', 'bx', 'cx', 'dx'] },
    { id: 'index', names: ['si', 'di', 'bp', 'sp'] },
    { id: 'ip', names: ['ip'] },
    { id: 'segment', names: ['cs', 'ds', 'ss', 'es'] },
  ],
  // Порядок и мнемоники — как в строке регистров DebugX.
  flags: [
    { name: 'OF', bit: 11, label: ['NV', 'OV'] },
    { name: 'DF', bit: 10, label: ['UP', 'DN'] },
    { name: 'IF', bit: 9, label: ['DI', 'EI'] },
    { name: 'SF', bit: 7, label: ['PL', 'NG'] },
    { name: 'ZF', bit: 6, label: ['NZ', 'ZR'] },
    { name: 'AF', bit: 4, label: ['NA', 'AC'] },
    { name: 'PF', bit: 2, label: ['PO', 'PE'] },
    { name: 'CF', bit: 0, label: ['NC', 'CY'] },
  ],
  stages: ['tasm', 'tlink', 'trace'],
  tools: ['tasm', 'tlink'],
  titles: { raw: 'asm.tabs.debugx', env: 'asm.keys.env' },
  language: () =>
    import('../windows/tasmLanguage').then((m) => ({
      language: m.tasmLanguage as StreamLanguage<unknown>,
      spans: m.tasmSpans,
      mnemonicOf: m.mnemonicOf,
    })),
  docs: () => import('../docs/entries').then((m) => m.DOC_ENTRIES),
  addr: {
    width: 4,
    parse: (text, step, run) => parseAddress(text, step, run, dataSymbols(run)),
    fmt: (a) => fmtAddr({ seg: a.seg ?? 0, off: a.off }),
    linear: (a) => linear({ seg: a.seg ?? 0, off: a.off }),
    sp: (step) => parseHex(step?.reg.sp),
  },
  isSysCall: (step) => isDosCall(step.asm),
  buildFlags: {
    keys: ['tasm_flags', 'tlink_flags'],
    preview: (s, base) =>
      `${joinFlags(['tasm', ...s.tasm_flags, `${base}.asm`])}\n${joinFlags(['tlink', ...s.tlink_flags, `${base}.obj`])}`,
  },
}
