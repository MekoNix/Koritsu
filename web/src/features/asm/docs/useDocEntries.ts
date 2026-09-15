/**
 * useDocEntries — набор записей справки для режима открытой программы.
 *
 * Набор берётся из описателя режима (`useAsm().toolchain.docs()`) и грузится
 * лениво: справка MinGW x64 не нужна тому, кто пишет на TASM, и наоборот.
 * Загруженный набор держится на уровне модуля — окно «Справка» и окно «Агент»
 * (подпись якоря-записи) не грузят его дважды, а перемонтирование вкладки не
 * показывает пустое окно.
 */
import { useEffect, useState } from 'react'

import { useAsm } from '../store'
import type { DocEntry } from './entries'

const loaded = new Map<string, readonly DocEntry[]>()

export interface DocEntriesState {
  /** `null` — набор ещё грузится или не загрузился. */
  entries: readonly DocEntry[] | null
  error: boolean
}

export function useDocEntries(): DocEntriesState {
  const { toolchain } = useAsm()
  const id = toolchain.id
  const [failed, setFailed] = useState<string | null>(null)
  const [, setReady] = useState(0)

  useEffect(() => {
    if (loaded.has(id)) return
    let live = true
    toolchain.docs().then(
      (entries) => {
        loaded.set(id, entries)
        if (live) setReady((n) => n + 1)
      },
      () => {
        if (live) setFailed(id)
      },
    )
    return () => {
      live = false
    }
  }, [id, toolchain])

  const entries = loaded.get(id) ?? null
  return { entries, error: !entries && failed === id }
}
