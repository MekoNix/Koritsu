/**
 * useDock — состояние дока: раскладка, фокус, отметки.
 *
 * **Раскладка одна.** Каждая правка (перетащили вкладку, потянули границу)
 * запоминается сразу; «Окно → Сбросить раскладку» возвращает раскладку по
 * умолчанию. Готовых наборов на выбор нет: окна и так перекладываются как
 * угодно, а второй набор значил бы искать, в каком из них осталось нужное окно.
 *
 * **Раскладка живёт в `localStorage`, с id человека в ключе.** Это про экран
 * этого браузера, а не про программу: на ноутбуке и на большом мониторе удобно
 * разное, и возить раскладку через службу значило бы навязать одну. id в ключе —
 * потому что браузер бывает общим, а раскладка у каждого своя. Хранилище может
 * быть закрыто настройками браузера — тогда раскладка живёт до перезагрузки.
 *
 * **Узкий экран (≤760px) — одна группа.** Сплиты на телефоне превращаются в
 * полоски по сорок пикселей; поэтому там показываются все открытые окна одной
 * строкой вкладок, а сохранённая раскладка не трогается и вернётся на широком.
 */
import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react'

import { WINDOW_IDS } from '../windows/registry'
import type { AsmWindowId } from '../types'
import {
  clone,
  defaultLayout,
  groupById,
  groupOf,
  groups,
  moveTab,
  normalize,
  removeTab,
  showTab,
  splitById,
  validTree,
  учестьИдентификаторы,
  type DockGroup,
  type DockNode,
  type DropTarget,
} from './model'

interface Layout {
  root: DockNode | null
  /** Где окно было перед закрытием. */
  last: Partial<Record<AsmWindowId, string>>
}

const KNOWN = new Set<string>(WINDOW_IDS)
const NARROW = '(max-width: 760px)'

function storageKey(userId: string | undefined): string {
  return `koritsu.asm.dock.v2.${userId ?? 'anon'}`
}

/**
 * Ключ, под которым раскладки лежали, пока их было несколько, —
 * `{ws, layouts: {[ws]: дерево}, last}`. Из него берётся раскладка той, что
 * была выбрана: её человек и видел последней.
 */
function oldStorageKey(userId: string | undefined): string {
  return `koritsu.asm.dock.v1.${userId ?? 'anon'}`
}

function fresh(): Layout {
  return { root: defaultLayout(), last: {} }
}

function readJson(key: string): unknown {
  try {
    const raw = localStorage.getItem(key)
    return raw ? JSON.parse(raw) : null
  } catch {
    return null
  }
}

function lastOf(x: unknown): Layout['last'] {
  const last: Layout['last'] = {}
  if (x && typeof x === 'object') {
    for (const [k, v] of Object.entries(x as Record<string, unknown>)) {
      if (KNOWN.has(k) && typeof v === 'string') last[k as AsmWindowId] = v
    }
  }
  return last
}

/** Дерево из хранилища: `null` — все окна закрыты, `undefined` — не разобрано. */
function treeOf(t: unknown): DockNode | null | undefined {
  if (t === null) return null
  if (!validTree(t, KNOWN)) return undefined
  учестьИдентификаторы(t)
  return normalize(t)
}

function load(userId: string | undefined): Layout {
  const d = readJson(storageKey(userId))
  if (d && typeof d === 'object') {
    const x = d as { root?: unknown; last?: unknown }
    const root = treeOf(x.root)
    return root === undefined ? fresh() : { root, last: lastOf(x.last) }
  }
  const old = readJson(oldStorageKey(userId))
  if (old && typeof old === 'object') {
    const x = old as { ws?: unknown; layouts?: Record<string, unknown>; last?: unknown }
    const t = typeof x.ws === 'string' && x.layouts && typeof x.layouts === 'object' ? x.layouts[x.ws] : undefined
    // Нетронутая среда лежала без дерева — тогда раскладка по умолчанию.
    const root = t === undefined ? undefined : treeOf(t)
    const l = root === undefined ? fresh() : { root, last: lastOf(x.last) }
    save(storageKey(userId), l)
    try {
      localStorage.removeItem(oldStorageKey(userId))
    } catch {
      // Старый ключ полежит — он больше не читается, раз записан новый.
    }
    return l
  }
  return fresh()
}

function save(key: string, l: Layout): void {
  try {
    localStorage.setItem(key, JSON.stringify({ root: l.root, last: l.last }))
  } catch {
    // Хранилище закрыто — раскладка доживёт до перезагрузки, этого хватит.
  }
}

function subscribeNarrow(cb: () => void): () => void {
  if (typeof window === 'undefined' || !window.matchMedia) return () => {}
  const mq = window.matchMedia(NARROW)
  mq.addEventListener('change', cb)
  return () => mq.removeEventListener('change', cb)
}

const isNarrowNow = () =>
  typeof window !== 'undefined' && !!window.matchMedia && window.matchMedia(NARROW).matches

/** Сдвинуть фокус клавиатуры на ярлык окна — после перерисовки. */
export function focusTab(id: AsmWindowId): void {
  requestAnimationFrame(() => {
    const el = document.querySelector<HTMLElement>(`[data-asm-tab="${id}"]`)
    el?.focus({ preventScroll: true })
  })
}

export interface DockApi {
  /** Дерево для отрисовки: на узком экране — одна группа из всех открытых окон. */
  tree: DockNode | null
  narrow: boolean
  focus: AsmWindowId | null
  unread: ReadonlySet<AsmWindowId>
  isOpen(id: AsmWindowId): boolean
  isVisible(id: AsmWindowId): boolean
  activate(id: AsmWindowId): void
  close(id: AsmWindowId): void
  show(id: AsmWindowId, opts?: { focus?: boolean; ifOpen?: boolean }): boolean
  move(id: AsmWindowId, target: DropTarget): void
  setSizes(splitId: string, sizes: number[]): void
  setFocus(id: AsmWindowId | null): void
  /** Вернуть раскладку по умолчанию. */
  resetLayout(): void
  cycleTab(dir: 1 | -1): void
  cycleGroup(): void
  /** Перенести фокусное окно в соседнюю группу по стрелке. `false` — в ту сторону групп нет. */
  moveToNeighbor(key: 'ArrowLeft' | 'ArrowRight' | 'ArrowUp' | 'ArrowDown'): boolean
  markUnread(id: AsmWindowId): void
}

export function useDock(userId: string | undefined): DockApi {
  const key = storageKey(userId)
  const [layout, setLayout] = useState<Layout>(() => load(userId))
  const загружено = useRef(key)
  const [focus, setFocusState] = useState<AsmWindowId | null>('listing')
  const [narrowActive, setNarrowActive] = useState<AsmWindowId | null>(null)
  const [unread, setUnread] = useState<ReadonlySet<AsmWindowId>>(() => new Set())
  const narrow = useSyncExternalStore(subscribeNarrow, isNarrowNow, () => false)

  // Профиль мог приехать позже первой отрисовки — тогда перечитываем раскладку
  // уже под своим ключом, а не пишем чужую поверх.
  useEffect(() => {
    if (загружено.current === key) return
    загружено.current = key
    setLayout(load(userId))
  }, [key, userId])

  useEffect(() => {
    if (загружено.current === key) save(key, layout)
  }, [key, layout])

  // Последнее значение — для чтения из обработчиков без пересоздания функций.
  const ref = useRef({ layout, focus, narrow, narrowActive })
  ref.current = { layout, focus, narrow, narrowActive }

  const commit = useCallback((fn: (l: Layout) => Layout) => {
    setLayout((was) => {
      const next = fn({ ...was, root: clone(was.root), last: { ...was.last } })
      return { ...next, root: normalize(next.root) }
    })
  }, [])

  const openIds = useCallback(
    (root: DockNode | null) => WINDOW_IDS.filter((id) => !!groupOf(root, id)),
    [],
  )

  const tree = useMemo<DockNode | null>(() => {
    if (!narrow) return layout.root
    const open = openIds(layout.root)
    if (!open.length) return null
    const active =
      narrowActive && open.includes(narrowActive)
        ? narrowActive
        : focus && open.includes(focus)
          ? focus
          : open[0]!
    const g: DockGroup = { type: 'group', id: 'narrow', tabs: open, active }
    return g
  }, [narrow, layout.root, narrowActive, focus, openIds])

  const clearUnread = useCallback((id: AsmWindowId) => {
    setUnread((was) => {
      if (!was.has(id)) return was
      const n = new Set(was)
      n.delete(id)
      return n
    })
  }, [])

  const isOpen = useCallback((id: AsmWindowId) => !!groupOf(ref.current.layout.root, id), [])

  const isVisible = useCallback((id: AsmWindowId) => {
    const { layout: l, narrow: n, narrowActive: na, focus: f } = ref.current
    const g = groupOf(l.root, id)
    if (!g) return false
    if (!n) return g.active === id
    const open = openIds(l.root)
    const active = na && open.includes(na) ? na : f && open.includes(f) ? f : open[0]
    return active === id
  }, [openIds])

  const activate = useCallback(
    (id: AsmWindowId) => {
      if (ref.current.narrow) setNarrowActive(id)
      else
        commit((l) => {
          const g = groupOf(l.root, id)
          if (g) g.active = id
          return l
        })
      setFocusState(id)
      clearUnread(id)
    },
    [commit, clearUnread],
  )

  const close = useCallback(
    (id: AsmWindowId) => {
      const { layout: l, focus: f } = ref.current
      if (!groupOf(l.root, id)) return
      const r = removeTab(clone(l.root), id)
      setLayout({ ...l, root: r.root, last: { ...l.last, ...(r.from ? { [id]: r.from } : {}) } })
      if (f === id) {
        const ng = r.from ? groupById(r.root, r.from) : null
        setFocusState(ng?.active ?? groups(r.root)[0]?.active ?? null)
      }
    },
    [],
  )

  const show = useCallback(
    (id: AsmWindowId, opts: { focus?: boolean; ifOpen?: boolean } = {}) => {
      const l = ref.current.layout
      if (!groupOf(l.root, id) && opts.ifOpen) return false
      commit((x) => ({ ...x, root: showTab(x.root, id, x.last[id]) }))
      if (ref.current.narrow) setNarrowActive(id)
      if (opts.focus) setFocusState(id)
      if (opts.focus || ref.current.narrow || !groupOf(l.root, id) || groupOf(l.root, id)?.active !== id)
        clearUnread(id)
      return true
    },
    [commit, clearUnread],
  )

  const move = useCallback(
    (id: AsmWindowId, target: DropTarget) => {
      commit((l) => {
        const r = moveTab(l.root, id, target)
        return { ...l, root: r.root, last: r.from ? { ...l.last, [id]: r.from } : l.last }
      })
      setFocusState(id)
    },
    [commit],
  )

  const setSizes = useCallback(
    (splitId: string, sizes: number[]) => {
      commit((l) => {
        const s = splitById(l.root, splitId)
        if (s && s.sizes.length === sizes.length) s.sizes = sizes
        return l
      })
    },
    [commit],
  )

  const resetLayout = useCallback(() => {
    setLayout((l) => ({ ...l, root: defaultLayout() }))
    setNarrowActive(null)
    setFocusState('listing')
  }, [])

  const cycleTab = useCallback(
    (dir: 1 | -1) => {
      const { layout: l, focus: f, narrow: n } = ref.current
      const g = n
        ? (tree as DockGroup | null)
        : (f ? groupOf(l.root, f) : null) ?? groups(l.root)[0] ?? null
      if (!g || g.type !== 'group' || !g.tabs.length) return
      const i = g.tabs.indexOf(g.active)
      const next = g.tabs[(i + dir + g.tabs.length) % g.tabs.length]!
      activate(next)
      focusTab(next)
    },
    [activate, tree],
  )

  const cycleGroup = useCallback(() => {
    const els = [...document.querySelectorAll<HTMLElement>('[data-asm-group]')]
    if (!els.length) return
    const f = ref.current.focus
    const i = els.findIndex((el) => f && el.querySelector(`[data-asm-tab="${f}"][aria-selected="true"]`))
    const g = els[(i + 1) % els.length]!
    const tab = g.querySelector<HTMLElement>('[data-asm-tab][aria-selected="true"]')
    const id = tab?.dataset.asmTab as AsmWindowId | undefined
    if (!id) return
    setFocusState(id)
    tab!.focus()
  }, [])

  const moveToNeighbor = useCallback(
    (key: 'ArrowLeft' | 'ArrowRight' | 'ArrowUp' | 'ArrowDown') => {
      const { layout: l, focus: f, narrow: n } = ref.current
      if (n || !f) return false
      const g = groupOf(l.root, f)
      if (!g) return false
      const el = document.querySelector<HTMLElement>(`[data-asm-group="${g.id}"]`)
      if (!el) return false
      const r = el.getBoundingClientRect()
      const cx = r.left + r.width / 2
      const cy = r.top + r.height / 2
      let best: HTMLElement | null = null
      let bd = Infinity
      document.querySelectorAll<HTMLElement>('[data-asm-group]').forEach((o) => {
        if (o === el) return
        const q = o.getBoundingClientRect()
        const ok =
          key === 'ArrowLeft'
            ? q.right <= r.left + 2
            : key === 'ArrowRight'
              ? q.left >= r.right - 2
              : key === 'ArrowUp'
                ? q.bottom <= r.top + 2
                : q.top >= r.bottom - 2
        if (!ok) return
        const d = Math.abs(q.left + q.width / 2 - cx) + Math.abs(q.top + q.height / 2 - cy)
        if (d < bd) {
          bd = d
          best = o
        }
      })
      const цель = best as HTMLElement | null
      if (!цель?.dataset.asmGroup) return false
      move(f, { gid: цель.dataset.asmGroup, mode: 'center' })
      focusTab(f)
      return true
    },
    [move],
  )

  const markUnread = useCallback(
    (id: AsmWindowId) => {
      if (isVisible(id)) return
      setUnread((was) => (was.has(id) ? was : new Set(was).add(id)))
    },
    [isVisible],
  )

  const setFocus = useCallback(
    (id: AsmWindowId | null) => {
      setFocusState(id)
      if (id && isVisible(id)) clearUnread(id)
    },
    [clearUnread, isVisible],
  )

  return {
    tree,
    narrow,
    focus,
    unread,
    isOpen,
    isVisible,
    activate,
    close,
    show,
    move,
    setSizes,
    setFocus,
    resetLayout,
    cycleTab,
    cycleGroup,
    moveToNeighbor,
    markUnread,
  }
}
