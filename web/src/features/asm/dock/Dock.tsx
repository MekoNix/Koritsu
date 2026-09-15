/**
 * Dock — отрисовка раскладки: сплиты, группы вкладок, перетаскивание.
 *
 * Поведение «CPU-окна»:
 *
 * * вкладку тянут мышью — на ярлыки другой группы (встаёт между ярлыками), в
 *   центр группы (последней вкладкой) или к краю (группа делится пополам);
 *   зона подсвечивается до отпускания, Esc отменяет;
 * * граница между окнами тянется мышью и двигается стрелками с фокуса;
 * * вкладка закрывается × или средней кнопкой, Delete — с клавиатуры;
 * * на узком экране — одна группа, без перетаскивания.
 *
 * **Окно смонтировано, пока открыто в доке**, а не только пока его вкладка
 * активна: переключение вкладок не должно терять прокрутку листинга и историю
 * правок в редакторе. Монтируется оно при первом показе — справка на полторы
 * сотни записей не грузится, пока её не открыли.
 *
 * **Во время перетаскивания React не перерисовывается.** Призрак ярлыка и
 * подсветка зоны двигаются прямой записью стиля: окна тяжёлые (листинг на
 * тысячи строк), и перерисовка на каждое движение мыши была бы заметна рукой.
 */
import {
  Component,
  Suspense,
  useCallback,
  useEffect,
  useRef,
  type ErrorInfo,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
  type KeyboardEvent as ReactKeyboardEvent,
} from 'react'

import { t as translate, useT } from '@/i18n'
import { cn } from '@/lib/cn'
import { Spinner } from '@/ui'

import { useAsm, useAsmUi } from '../store'
import type { AsmWindowId } from '../types'
import { windowDefFor } from '../windows/registry'
import type { DockGroup, DockNode, DockSplit, DropTarget } from './model'
import { focusTab } from './useDock'

type Side = 'center' | 'left' | 'right' | 'top' | 'bottom'

interface DragState {
  id: AsmWindowId
  x0: number
  y0: number
  on: boolean
  target: DropTarget | null
}

export function Dock() {
  const t = useT()
  const { dock } = useAsmUi()
  // Окна и заголовки — по режиму программы; id и раскладка общие.
  const { toolchain } = useAsm()
  const toolchainRef = useRef(toolchain)
  toolchainRef.current = toolchain
  const ghost = useRef<HTMLDivElement>(null)
  const drop = useRef<HTMLDivElement>(null)
  const ins = useRef<HTMLDivElement>(null)
  const root = useRef<HTMLDivElement>(null)
  const drag = useRef<DragState | null>(null)
  const dockRef = useRef(dock)
  dockRef.current = dock
  /** Окна, которые уже показывались: их больше не размонтируем, пока они в доке. */
  const mounted = useRef(new Set<AsmWindowId>())

  const hideOverlay = useCallback(() => {
    if (ghost.current) ghost.current.hidden = true
    if (drop.current) drop.current.hidden = true
    if (ins.current) ins.current.hidden = true
    document.body.classList.remove('asm-dragging')
  }, [])

  const targetAt = useCallback((x: number, y: number) => {
    const el = document.elementFromPoint(x, y)
    const g = el?.closest<HTMLElement>('[data-asm-group]')
    if (!g || !root.current?.contains(g) || !g.dataset.asmGroup) return null
    const gid = g.dataset.asmGroup
    const tabs = g.querySelector<HTMLElement>('[data-asm-tabs]')
    const body = g.querySelector<HTMLElement>('[data-asm-body]')
    if (!tabs || !body) return null
    const tr = tabs.getBoundingClientRect()
    if (y <= tr.bottom) {
      const list = [...tabs.querySelectorAll<HTMLElement>('[data-asm-tab]')]
      let index = list.length
      let mx: number | null = null
      for (let i = 0; i < list.length; i++) {
        const r = list[i]!.getBoundingClientRect()
        if (x < r.left + r.width / 2) {
          index = i
          mx = r.left
          break
        }
      }
      if (mx == null) mx = list.length ? list[list.length - 1]!.getBoundingClientRect().right : tr.left
      return {
        target: { gid, mode: 'tab', index } as DropTarget,
        mark: { x: Math.min(mx, tr.right - 2), top: tr.top, h: tr.height },
      }
    }
    const b = body.getBoundingClientRect()
    const rx = (x - b.left) / b.width
    const ry = (y - b.top) / b.height
    const ds: Record<Exclude<Side, 'center'>, number> = { left: rx, right: 1 - rx, top: ry, bottom: 1 - ry }
    let side: Side = 'center'
    let m = 0.25
    for (const k of Object.keys(ds) as (keyof typeof ds)[]) {
      if (ds[k] < m) {
        m = ds[k]
        side = k
      }
    }
    const rect = { left: b.left, top: b.top, width: b.width, height: b.height }
    if (side === 'left') rect.width /= 2
    if (side === 'right') {
      rect.left += b.width / 2
      rect.width /= 2
    }
    if (side === 'top') rect.height /= 2
    if (side === 'bottom') {
      rect.top += b.height / 2
      rect.height /= 2
    }
    return { target: { gid, mode: side } as DropTarget, rect, side }
  }, [])

  const onMove = useCallback(
    (e: PointerEvent) => {
      const d = drag.current
      if (!d) return
      if (!d.on) {
        if (Math.hypot(e.clientX - d.x0, e.clientY - d.y0) < 6) return
        d.on = true
        document.body.classList.add('asm-dragging')
        if (ghost.current) {
          ghost.current.textContent = translate(windowDefFor(toolchainRef.current, d.id).title)
          ghost.current.hidden = false
        }
      }
      if (ghost.current) {
        ghost.current.style.left = `${e.clientX + 12}px`
        ghost.current.style.top = `${e.clientY + 10}px`
      }
      const hit = targetAt(e.clientX, e.clientY)
      d.target = hit?.target ?? null
      if (hit && 'mark' in hit && hit.mark && ins.current && drop.current) {
        drop.current.hidden = true
        ins.current.hidden = false
        Object.assign(ins.current.style, {
          left: `${hit.mark.x}px`,
          top: `${hit.mark.top}px`,
          height: `${hit.mark.h}px`,
        })
      } else if (hit && 'rect' in hit && hit.rect && ins.current && drop.current) {
        ins.current.hidden = true
        drop.current.hidden = false
        Object.assign(drop.current.style, {
          left: `${hit.rect.left}px`,
          top: `${hit.rect.top}px`,
          width: `${hit.rect.width}px`,
          height: `${hit.rect.height}px`,
        })
        const label = drop.current.firstElementChild
        if (label) label.textContent = translate(`asm.dock.drop.${hit.side}`)
      } else {
        if (drop.current) drop.current.hidden = true
        if (ins.current) ins.current.hidden = true
      }
    },
    [targetAt],
  )

  const end = useRef<(cancel: boolean) => void>(() => {})
  const onUp = useCallback(() => end.current(false), [])
  const onKey = useCallback((e: KeyboardEvent) => {
    if (e.key === 'Escape') {
      e.preventDefault()
      e.stopPropagation()
      end.current(true)
    }
  }, [])
  end.current = (cancel: boolean) => {
    window.removeEventListener('pointermove', onMove)
    window.removeEventListener('pointerup', onUp)
    window.removeEventListener('keydown', onKey, true)
    const d = drag.current
    drag.current = null
    hideOverlay()
    if (!cancel && d?.on && d.target) {
      dockRef.current.move(d.id, d.target)
      focusTab(d.id)
    }
  }

  useEffect(() => () => end.current(true), [])

  const startDrag = useCallback(
    (e: ReactPointerEvent, id: AsmWindowId) => {
      drag.current = { id, x0: e.clientX, y0: e.clientY, on: false, target: null }
      window.addEventListener('pointermove', onMove)
      window.addEventListener('pointerup', onUp)
      window.addEventListener('keydown', onKey, true)
    },
    [onMove, onUp, onKey],
  )

  // Закрытое окно размонтируется: открытое снова начнёт с чистого листа.
  if (dock.tree) {
    for (const id of [...mounted.current]) if (!dock.isOpen(id)) mounted.current.delete(id)
  }

  return (
    <main className="asm-dock" ref={root} data-asm-dock aria-label={t('asm.dock.label')}>
      {dock.tree ? (
        <DockNodeView node={dock.tree} startDrag={startDrag} mounted={mounted.current} />
      ) : (
        <div className="asm-dk-empty">
          <b>{t('asm.dock.emptyTitle')}</b>
          <span>{t('asm.dock.emptyText')}</span>
          <button type="button" className="asm-btn" onClick={dock.resetLayout}>
            {t('asm.menu.window.resetLayout')}
          </button>
        </div>
      )}
      <div ref={ghost} className="asm-ghost" hidden />
      <div ref={drop} className="asm-drop" hidden>
        <span />
      </div>
      <div ref={ins} className="asm-insmark" hidden />
    </main>
  )
}

interface NodeProps {
  startDrag: (e: ReactPointerEvent, id: AsmWindowId) => void
  mounted: Set<AsmWindowId>
}

function DockNodeView({ node, ...rest }: NodeProps & { node: DockNode }) {
  return node.type === 'split' ? <SplitView node={node} {...rest} /> : <GroupView group={node} {...rest} />
}

function SplitView({ node, ...rest }: NodeProps & { node: DockSplit }) {
  const t = useT()
  const { dock } = useAsmUi()
  const box = useRef<HTMLDivElement>(null)

  const cells = () =>
    box.current ? [...box.current.children].filter((c): c is HTMLElement => c.classList.contains('asm-dk-cell')) : []

  const pair = (sizes: number[], i: number, a: number, b: number) => {
    const min = 0.06
    const sum = a + b
    if (a < min) {
      a = min
      b = sum - min
    }
    if (b < min) {
      b = min
      a = sum - min
    }
    const next = [...sizes]
    next[i] = a
    next[i + 1] = b
    const els = cells()
    if (els[i]) els[i].style.flexGrow = String(a)
    if (els[i + 1]) els[i + 1]!.style.flexGrow = String(b)
    return next
  }

  const onDown = (e: ReactPointerEvent<HTMLDivElement>, i: number) => {
    e.preventDefault()
    const gut = e.currentTarget
    gut.setPointerCapture(e.pointerId)
    gut.classList.add('is-drag')
    const horiz = node.dir === 'row'
    const rect = box.current!.getBoundingClientRect()
    const total = horiz ? rect.width : rect.height
    const sa = node.sizes[i] ?? 0.5
    const sb = node.sizes[i + 1] ?? 0.5
    const p0 = horiz ? e.clientX : e.clientY
    let sizes = node.sizes
    const mv = (ev: PointerEvent) => {
      const d = ((horiz ? ev.clientX : ev.clientY) - p0) / total
      sizes = pair(node.sizes, i, sa + d, sb - d)
    }
    const up = () => {
      gut.classList.remove('is-drag')
      gut.removeEventListener('pointermove', mv)
      gut.removeEventListener('pointerup', up)
      gut.removeEventListener('pointercancel', up)
      dock.setSizes(node.id, sizes)
    }
    gut.addEventListener('pointermove', mv)
    gut.addEventListener('pointerup', up)
    gut.addEventListener('pointercancel', up)
  }

  const onKey = (e: ReactKeyboardEvent, i: number) => {
    const dec = node.dir === 'row' ? 'ArrowLeft' : 'ArrowUp'
    const inc = node.dir === 'row' ? 'ArrowRight' : 'ArrowDown'
    if (e.key !== dec && e.key !== inc) return
    e.preventDefault()
    e.stopPropagation()
    const d = e.key === inc ? 0.03 : -0.03
    dock.setSizes(node.id, pair(node.sizes, i, (node.sizes[i] ?? 0.5) + d, (node.sizes[i + 1] ?? 0.5) - d))
  }

  return (
    <div ref={box} className={cn('asm-dk-split', node.dir)}>
      {node.children.map((c, i) => (
        <SplitChild key={c.id}>
          {i > 0 && (
            <div
              className="asm-dk-gut"
              role="separator"
              tabIndex={0}
              aria-orientation={node.dir === 'row' ? 'vertical' : 'horizontal'}
              aria-label={t('asm.dock.gutter')}
              onPointerDown={(e) => onDown(e, i - 1)}
              onKeyDown={(e) => onKey(e, i - 1)}
            />
          )}
          <div className="asm-dk-cell" style={{ flexGrow: node.sizes[i] }}>
            <DockNodeView node={c} {...rest} />
          </div>
        </SplitChild>
      ))}
    </div>
  )
}

/** Обёртка без разметки: ключ ребёнка держит и границу перед ним, и ячейку. */
function SplitChild({ children }: { children: ReactNode }) {
  return <>{children}</>
}

function GroupView({ group, startDrag, mounted }: NodeProps & { group: DockGroup }) {
  const t = useT()
  const { dock } = useAsmUi()
  const { toolchain } = useAsm()
  const narrow = group.id === 'narrow'
  mounted.add(group.active)
  const isFocus = dock.focus === group.active

  const onTabDown = (e: ReactPointerEvent<HTMLDivElement>, id: AsmWindowId) => {
    if ((e.target as HTMLElement).closest('.asm-tab-x')) return
    if (e.button === 1) {
      e.preventDefault()
      dock.close(id)
      return
    }
    if (e.button !== 0) return
    dock.activate(id)
    if (!narrow) startDrag(e, id)
  }

  const onTabKey = (e: ReactKeyboardEvent<HTMLDivElement>, id: AsmWindowId) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault()
      dock.activate(id)
      focusTab(id)
    } else if (e.key === 'Delete') {
      e.preventDefault()
      const i = group.tabs.indexOf(id)
      const nb = group.tabs[i + 1] ?? group.tabs[i - 1]
      dock.close(id)
      if (nb) focusTab(nb)
    } else if ((e.key === 'ArrowRight' || e.key === 'ArrowLeft') && !e.ctrlKey && !e.altKey) {
      e.preventDefault()
      const i = group.tabs.indexOf(id)
      const n = group.tabs[(i + (e.key === 'ArrowRight' ? 1 : -1) + group.tabs.length) % group.tabs.length]!
      dock.activate(n)
      focusTab(n)
    }
  }

  return (
    <div className={cn('asm-dk-group', isFocus && 'is-focus')} data-asm-group={group.id}>
      <div className="asm-dk-tabs" role="tablist" data-asm-tabs>
        {group.tabs.map((id) => {
          const def = windowDefFor(toolchain, id)
          const sel = id === group.active
          const title = t(def.title)
          return (
            <div
              key={id}
              className={cn('asm-dk-tab', dock.unread.has(id) && 'has-dot')}
              role="tab"
              tabIndex={sel ? 0 : -1}
              aria-selected={sel}
              aria-controls={`asm-panel-${id}`}
              id={`asm-tab-${id}`}
              data-asm-tab={id}
              data-window={id}
              title={def.hotkey ? `${title} · ${def.hotkey}` : title}
              onPointerDown={(e) => onTabDown(e, id)}
              onKeyDown={(e) => onTabKey(e, id)}
            >
              <span className="asm-dotm" aria-hidden="true" />
              {title}
              <button
                type="button"
                className="asm-tab-x"
                tabIndex={-1}
                aria-label={t('asm.dock.close', { name: title })}
                onClick={() => dock.close(id)}
              >
                ×
              </button>
            </div>
          )
        })}
      </div>
      <div className="asm-dk-body" data-asm-body>
        {group.tabs.map((id) => {
          if (!mounted.has(id)) return null
          const active = id === group.active
          const { Component } = windowDefFor(toolchain, id)
          return (
            <section
              key={id}
              id={`asm-panel-${id}`}
              className="asm-panel"
              role="tabpanel"
              aria-labelledby={`asm-tab-${id}`}
              hidden={!active}
              data-panel={id}
              onPointerDownCapture={() => {
                if (dock.focus !== id) dock.setFocus(id)
              }}
            >
              <WindowBoundary>
                <Suspense
                  fallback={
                    <div className="asm-panel-wait">
                      <Spinner />
                    </div>
                  }
                >
                  <Component active={active} />
                </Suspense>
              </WindowBoundary>
            </section>
          )
        })}
      </div>
    </div>
  )
}

/**
 * Упавшее окно не роняет страницу: остальные окна и незаписанный исходник
 * важнее, чем одна вкладка. Ошибка остаётся в консоли.
 */
class WindowBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  override state = { failed: false }

  static getDerivedStateFromError() {
    return { failed: true }
  }

  override componentDidCatch(error: unknown, info: ErrorInfo) {
    console.error('[asm] окно упало', error, info.componentStack)
  }

  override render() {
    if (!this.state.failed) return this.props.children
    return (
      <div className="asm-empty">
        {translate('asm.dock.windowFailed')}{' '}
        <button type="button" className="asm-linkbtn" onClick={() => this.setState({ failed: false })}>
          {translate('asm.dock.retry')}
        </button>
      </div>
    )
  }
}
