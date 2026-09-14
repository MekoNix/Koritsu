/**
 * model — раскладка окон: дерево сплитов и групп вкладок.
 *
 * Здесь только данные и чистые функции над ними; отрисовка — `Dock.tsx`,
 * состояние и сохранение — `useDock.ts`. Разделено потому, что правило «пустая
 * группа схлопывается, сплит из одного ребёнка растворяется в родителе» должно
 * держаться после любого действия — перетаскивания, закрытия, загрузки из
 * хранилища, — и проверяется оно одним `normalize`, а не в каждом обработчике.
 *
 * Функции не меняют входное дерево: действие работает над копией, и React видит
 * новое значение. Дерево маленькое (дюжина окон), копия дешевле поиска
 * мутации, которая забыла перерисовку.
 */
import type { AsmWindowId } from '../types'

export interface DockGroup {
  type: 'group'
  id: string
  tabs: AsmWindowId[]
  active: AsmWindowId
}

export interface DockSplit {
  type: 'split'
  id: string
  dir: 'row' | 'col'
  children: DockNode[]
  /** Доли детей; сумма — 1. */
  sizes: number[]
}

export type DockNode = DockGroup | DockSplit

/** Куда уронили вкладку: на ярлыки (позиция), в центр группы или к краю. */
export type DropTarget =
  | { gid: string; mode: 'tab'; index: number }
  | { gid: string; mode: 'center' | 'left' | 'right' | 'top' | 'bottom' }

let счётчик = 0
const новыйId = (префикс: string) => `${префикс}${++счётчик}`

/** Счётчик идентификаторов не должен выдать id, уже лежащий в сохранённом дереве. */
export function учестьИдентификаторы(n: DockNode | null | undefined): void {
  if (!n) return
  const m = /^[gs](\d+)$/.exec(n.id)
  if (m) счётчик = Math.max(счётчик, Number(m[1]))
  if (n.type === 'split') n.children.forEach(учестьИдентификаторы)
}

export const G = (tabs: AsmWindowId[], active?: AsmWindowId): DockGroup => ({
  type: 'group',
  id: новыйId('g'),
  tabs,
  active: active ?? tabs[0]!,
})

export const S = (dir: 'row' | 'col', children: DockNode[], sizes: number[]): DockSplit => ({
  type: 'split',
  id: новыйId('s'),
  dir,
  children,
  sizes,
})

/**
 * Раскладка по умолчанию — «CPU-окно» Turbo Debugger: листинг и регистры
 * сверху, дамп и стек под ними, внизу вкладки. Дальше человек перекладывает
 * окна как ему удобно; сброс возвращает эту. «Исходник» стоит вкладкой рядом с
 * листингом: правят программу и смотрят трассу одним и тем же местом экрана,
 * по очереди.
 */
export function defaultLayout(): DockNode {
  return S(
    'col',
    [
      S('row', [G(['source', 'listing'], 'listing'), G(['registers'])], [0.66, 0.34]),
      S('row', [G(['dump']), G(['stack', 'watch', 'breakpoints'])], [0.66, 0.34]),
      G(['output', 'input', 'build', 'debugx', 'agent', 'docs'], 'output'),
    ],
    [0.47, 0.29, 0.24],
  )
}

export function clone<T extends DockNode | null>(n: T): T {
  return (n ? structuredClone(n) : n) as T
}

export function groups(n: DockNode | null, acc: DockGroup[] = []): DockGroup[] {
  if (!n) return acc
  if (n.type === 'group') acc.push(n)
  else n.children.forEach((c) => groups(c, acc))
  return acc
}

interface Found<T extends DockNode> {
  node: T
  parent: DockSplit | null
  index: number
}

function find<T extends DockNode>(
  n: DockNode | null,
  pred: (n: DockNode) => n is T,
  parent: DockSplit | null = null,
  index = 0,
): Found<T> | null {
  if (!n) return null
  if (pred(n)) return { node: n, parent, index }
  if (n.type === 'split') {
    for (let i = 0; i < n.children.length; i++) {
      const r = find(n.children[i]!, pred, n, i)
      if (r) return r
    }
  }
  return null
}

export const groupOf = (root: DockNode | null, id: AsmWindowId): DockGroup | null =>
  find(root, (n): n is DockGroup => n.type === 'group' && n.tabs.includes(id))?.node ?? null

export const groupById = (root: DockNode | null, gid: string): DockGroup | null =>
  find(root, (n): n is DockGroup => n.type === 'group' && n.id === gid)?.node ?? null

export const splitById = (root: DockNode | null, sid: string): DockSplit | null =>
  find(root, (n): n is DockSplit => n.type === 'split' && n.id === sid)?.node ?? null

/** Схлопнуть пустые группы, растворить одиночные сплиты, слить сплиты одного направления. */
export function normalize(n: DockNode | null): DockNode | null {
  if (!n) return null
  if (n.type === 'group') return n.tabs.length ? n : null
  const kids: DockNode[] = []
  const sizes: number[] = []
  n.children.forEach((c, i) => {
    const x = normalize(c)
    if (!x) return
    const s = n.sizes[i] || 0.1
    if (x.type === 'split' && x.dir === n.dir) {
      x.children.forEach((cc, j) => {
        kids.push(cc)
        sizes.push(s * (x.sizes[j] ?? 0))
      })
    } else {
      kids.push(x)
      sizes.push(s)
    }
  })
  if (!kids.length) return null
  if (kids.length === 1) return kids[0]!
  const sum = sizes.reduce((a, b) => a + b, 0)
  n.children = kids
  n.sizes = sizes.map((s) => s / sum)
  return n
}

/**
 * Убрать вкладку. Возвращает id группы, где она была: туда окно вернётся, если
 * его откроют снова, — человек ищет окно там, где его закрыл.
 */
export function removeTab(root: DockNode | null, id: AsmWindowId): { root: DockNode | null; from: string | null } {
  const g = groupOf(root, id)
  if (!g) return { root, from: null }
  const i = g.tabs.indexOf(id)
  g.tabs.splice(i, 1)
  if (g.active === id && g.tabs.length) g.active = g.tabs[Math.min(i, g.tabs.length - 1)]!
  return { root: normalize(root), from: g.id }
}

function splitAt(root: DockNode | null, gid: string, id: AsmWindowId, side: 'left' | 'right' | 'top' | 'bottom'): DockNode | null {
  const r = find(root, (n): n is DockGroup => n.type === 'group' && n.id === gid)
  if (!r) return root
  const N = G([id])
  const dir = side === 'left' || side === 'right' ? 'row' : 'col'
  const before = side === 'left' || side === 'top'
  if (r.parent && r.parent.dir === dir) {
    const p = r.parent
    const h = (p.sizes[r.index] ?? 0.5) / 2
    p.sizes[r.index] = h
    const at = before ? r.index : r.index + 1
    p.children.splice(at, 0, N)
    p.sizes.splice(at, 0, h)
    return root
  }
  const sp = S(dir, before ? [N, r.node] : [r.node, N], [0.5, 0.5])
  if (!r.parent) return sp
  r.parent.children[r.index] = sp
  return root
}

/** Переложить вкладку. Дерево на входе — копия, его можно менять. */
export function moveTab(
  root: DockNode | null,
  id: AsmWindowId,
  t: DropTarget,
): { root: DockNode | null; from: string | null } {
  const src = groupOf(root, id)
  const tg = groupById(root, t.gid)
  if (!src || !tg) return { root, from: null }
  if (t.mode === 'center' || t.mode === 'tab') {
    if (src === tg) {
      if (t.mode !== 'tab') return { root, from: null }
      const from = src.tabs.indexOf(id)
      let idx = t.index
      src.tabs.splice(from, 1)
      if (idx > from) idx--
      src.tabs.splice(idx, 0, id)
      src.active = id
      return { root, from: null }
    }
    const r = removeTab(root, id)
    const g = groupById(r.root, t.gid)
    if (!g) return r
    g.tabs.splice(t.mode === 'tab' ? Math.min(t.index, g.tabs.length) : g.tabs.length, 0, id)
    g.active = id
    return r
  }
  if (src === tg && src.tabs.length === 1) return { root, from: null }
  const r = removeTab(root, id)
  // Группа-цель могла исчезнуть, только если это была группа-источник из одной
  // вкладки, — этот случай отсечён выше.
  return { root: normalize(splitAt(r.root, t.gid, id, t.mode)), from: r.from }
}

/** Открыть окно: активировать, если оно уже в доке, иначе вернуть туда, где закрыли. */
export function showTab(root: DockNode | null, id: AsmWindowId, lastGroup: string | undefined): DockNode {
  const g = groupOf(root, id)
  if (g) {
    g.active = id
    return root!
  }
  const target =
    (lastGroup ? groupById(root, lastGroup) : null) ??
    groupOf(root, 'output') ??
    groupOf(root, 'agent') ??
    groupOf(root, 'listing') ??
    groups(root)[0]
  if (!target) return G([id])
  target.tabs.push(id)
  target.active = id
  return root!
}

/**
 * Проверить дерево из хранилища. Там лежит то, что записала прошлая версия
 * сайта, — окно могли переименовать или убрать, и такое дерево не рисуется, а
 * заменяется раскладкой по умолчанию.
 */
export function validTree(n: unknown, known: ReadonlySet<string>, seen = new Set<string>()): n is DockNode {
  if (!n || typeof n !== 'object') return false
  const x = n as Partial<Omit<DockSplit, 'type'> & Omit<DockGroup, 'type'>> & { type?: unknown }
  if (typeof x.id !== 'string') return false
  if (x.type === 'group') {
    if (!Array.isArray(x.tabs) || !x.tabs.length) return false
    for (const t of x.tabs) {
      if (!known.has(t) || seen.has(t)) return false
      seen.add(t)
    }
    if (!x.tabs.includes(x.active as AsmWindowId)) x.active = x.tabs[0]
    return true
  }
  if (x.type === 'split') {
    if (!(x.dir === 'row' || x.dir === 'col') || !Array.isArray(x.children) || !x.children.length) return false
    if (!Array.isArray(x.sizes) || x.sizes.length !== x.children.length || x.sizes.some((s) => !(s > 0)))
      x.sizes = x.children.map(() => 1 / x.children!.length)
    return x.children.every((c) => validTree(c, known, seen))
  }
  return false
}
