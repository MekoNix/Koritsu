/**
 * registry — список окон модуля «Ассемблер».
 *
 * Док знает об окне только то, что здесь: id, ключ заголовка и компонент. Что
 * внутри окна, он не знает, а окно не знает, в какой оно группе, — поэтому окна
 * пишутся отдельно от дока и друг от друга.
 *
 * Каждое окно — свой кусок сборки (`lazy`): отладчик открывают на ноутбуке, где
 * справка на полторы сотни записей и редактор кода не нужны, пока их вкладка не
 * стала активной.
 *
 * **Режим подменяет компонент, но не id.** У MinGW x64 Регистры, Дамп и Стек —
 * свои файлы (плоская 64-битная память в самой раскладке окна), заголовок окна
 * сырого вывода — свой. Id окон общие, поэтому раскладка дока одна на оба режима
 * и не ломается при переходе между программами.
 *
 * Порядок списка — порядок в меню «Окно» и номер для Alt+1…9.
 */
import { lazy, type ComponentType, type LazyExoticComponent } from 'react'

import type { AsmToolchainDef } from '../toolchains'
import type { AsmToolchainId, AsmWindowId, AsmWindowProps } from '../types'

export interface AsmWindowDef {
  id: AsmWindowId
  /** Ключ заголовка вкладки в словаре. */
  title: string
  /** Номер для Alt+N; у окон дальше девятого клавиши нет. */
  hotkey?: string
  Component: LazyExoticComponent<ComponentType<AsmWindowProps>>
}

export const ASM_WINDOWS: readonly AsmWindowDef[] = [
  { id: 'source', title: 'asm.tabs.source', hotkey: 'Alt+1', Component: lazy(() => import('./Source')) },
  { id: 'listing', title: 'asm.tabs.listing', hotkey: 'Alt+2', Component: lazy(() => import('./Listing')) },
  { id: 'registers', title: 'asm.tabs.registers', hotkey: 'Alt+3', Component: lazy(() => import('./Registers')) },
  { id: 'dump', title: 'asm.tabs.dump', hotkey: 'Alt+4', Component: lazy(() => import('./Dump')) },
  { id: 'stack', title: 'asm.tabs.stack', hotkey: 'Alt+5', Component: lazy(() => import('./Stack')) },
  { id: 'output', title: 'asm.tabs.output', hotkey: 'Alt+6', Component: lazy(() => import('./Output')) },
  { id: 'build', title: 'asm.tabs.build', hotkey: 'Alt+7', Component: lazy(() => import('./BuildLog')) },
  { id: 'agent', title: 'asm.tabs.agent', hotkey: 'Alt+8', Component: lazy(() => import('./Agent')) },
  { id: 'docs', title: 'asm.tabs.docs', hotkey: 'Alt+9', Component: lazy(() => import('./Docs')) },
  { id: 'input', title: 'asm.tabs.input', Component: lazy(() => import('./Input')) },
  { id: 'breakpoints', title: 'asm.tabs.breakpoints', Component: lazy(() => import('./Breakpoints')) },
  { id: 'watch', title: 'asm.tabs.watch', Component: lazy(() => import('./Watch')) },
  { id: 'debugx', title: 'asm.tabs.debugx', Component: lazy(() => import('./DebugxRaw')) },
]

export const WINDOW_BY_ID: Record<AsmWindowId, AsmWindowDef> = Object.fromEntries(
  ASM_WINDOWS.map((w) => [w.id, w]),
) as Record<AsmWindowId, AsmWindowDef>

export const WINDOW_IDS: readonly AsmWindowId[] = ASM_WINDOWS.map((w) => w.id)

/**
 * Окна MinGW x64, которые отличаются от окон TASM. Заголовок окна сырого вывода
 * берётся из описателя режима (`toolchain.titles.raw`): здесь описатель не
 * импортируется — `useDock` читает `WINDOW_IDS` при загрузке, а описатели через
 * `format.ts` тянут `store.tsx`, который тянет док.
 */
const MINGW64_OVERRIDES: Partial<Record<AsmWindowId, Partial<AsmWindowDef>>> = {
  registers: { Component: lazy(() => import('./Registers64')) },
  dump: { Component: lazy(() => import('./Dump64')) },
  stack: { Component: lazy(() => import('./Stack64')) },
}

const MINGW64_WINDOWS: readonly AsmWindowDef[] = ASM_WINDOWS.map((w) => ({ ...w, ...MINGW64_OVERRIDES[w.id] }))

const BY_ID: Record<AsmToolchainId, Record<AsmWindowId, AsmWindowDef>> = {
  tasm: WINDOW_BY_ID,
  mingw64: Object.fromEntries(MINGW64_WINDOWS.map((w) => [w.id, w])) as Record<AsmWindowId, AsmWindowDef>,
}

/** Окна режима в порядке меню. */
export function windowsFor(toolchain: AsmToolchainId): readonly AsmWindowDef[] {
  return toolchain === 'mingw64' ? MINGW64_WINDOWS : ASM_WINDOWS
}

/** Окна режима по id. */
export function windowByIdFor(toolchain: AsmToolchainId): Record<AsmWindowId, AsmWindowDef> {
  return BY_ID[toolchain]
}

/** Окно режима с заголовком по описателю: у окна сырого вывода он свой у каждого режима. */
export function windowDefFor(toolchain: Pick<AsmToolchainDef, 'id' | 'titles'>, id: AsmWindowId): AsmWindowDef {
  const def = BY_ID[toolchain.id][id]
  return id === 'debugx' ? { ...def, title: toolchain.titles.raw } : def
}
