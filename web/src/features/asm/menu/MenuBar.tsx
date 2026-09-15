/**
 * MenuBar — строка меню программы, запуск и статус прогона.
 *
 * Своя строка меню, а не `MenuRoot` из `@/ui`: у выпадающего меню Radix нет
 * поведения *строки* — стрелка вправо из открытого «Файла» должна открыть
 * «Правку», наведение при открытом меню переключать соседнее, F10 и одиночный
 * Alt — входить в строку и выходить из неё. Роли (`menubar`, `menu`,
 * `menuitemcheckbox`…) расставлены по ARIA.
 */
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
} from 'react'
import { createPortal } from 'react-dom'

import { useT } from '@/i18n'
import { cn } from '@/lib/cn'

import { useAsm, useAsmUi, type AsmUi } from '../store'
import type { AsmContextValue } from '../store'
import { useAsmActions } from './actions'
import { buildMenus, type MenuEntry } from './items'
import { firstError, fmtSec, fmtSteps, waitsForInput } from '../windows/format'

interface Level {
  items: MenuEntry[]
  x: number
  y: number
  /** Кнопка, открывшая уровень: у верхнего — пункт строки, у вложенного — пункт меню. */
  anchor: HTMLElement
}

/** Какой верхний пункт открыт: номер или −1 — бургер. */
type OpenKey = number | null

export function MenuBar() {
  const t = useT()
  const asm = useAsm()
  const ui = useAsmUi()
  const actions = useAsmActions()
  const menus = useMemo(() => buildMenus(asm, ui, actions), [asm, ui, actions])

  const bar = useRef<HTMLDivElement>(null)
  const topsRef = useRef<HTMLDivElement>(null)
  const burger = useRef<HTMLButtonElement>(null)
  const prevFocus = useRef<HTMLElement | null>(null)
  const [open, setOpen] = useState<OpenKey>(null)
  const [stack, setStack] = useState<Level[]>([])
  const levelsEl = useRef<(HTMLDivElement | null)[]>([])

  const tops = () => topButtons(topsRef.current)

  const closeAll = useCallback((restore = false) => {
    setStack((was) => {
      if (restore && was[0]) was[0].anchor.focus()
      return []
    })
    setOpen(null)
  }, [])

  const openDropdown = useCallback((key: OpenKey, anchor: HTMLElement, items: MenuEntry[], focusFirst: boolean) => {
    const r = anchor.getBoundingClientRect()
    setOpen(key)
    setStack([{ items, x: r.left, y: r.bottom, anchor }])
    if (focusFirst) requestAnimationFrame(() => firstItem(levelsEl.current[0])?.focus())
  }, [])

  const openTop = useCallback(
    (i: number, focusFirst: boolean) => {
      const b = topButtons(topsRef.current)[i]
      const menu = menus[i]
      if (!b || !menu) return
      b.focus()
      openDropdown(i, b, menu.items(), focusFirst)
    },
    [menus, openDropdown],
  )

  const openSub = useCallback((level: number, anchor: HTMLElement, items: MenuEntry[], focusFirst: boolean) => {
    const r = anchor.getBoundingClientRect()
    setStack((was) => {
      if (was[level + 1]?.anchor === anchor) return was
      return [...was.slice(0, level + 1), { items, x: r.right - 2, y: r.top - 4, anchor }]
    })
    if (focusFirst) requestAnimationFrame(() => firstItem(levelsEl.current[level + 1])?.focus())
  }, [])

  // Меню не вылезает за край окна: позиция уточняется по настоящему размеру.
  useLayoutEffect(() => {
    stack.forEach((lv, i) => {
      const el = levelsEl.current[i]
      if (!el) return
      const r = el.getBoundingClientRect()
      let x = lv.x
      if (i > 0 && x + r.width > innerWidth - 8) x = Math.max(8, lv.anchor.getBoundingClientRect().left - r.width + 2)
      el.style.left = `${Math.max(8, Math.min(x, innerWidth - r.width - 8))}px`
      el.style.top = `${Math.max(8, Math.min(lv.y, innerHeight - r.height - 8))}px`
    })
  }, [stack])

  // Клик мимо меню — закрыть.
  useEffect(() => {
    if (!stack.length) return
    const down = (e: PointerEvent) => {
      const el = e.target as HTMLElement
      if (el.closest('.asm-dd') || bar.current?.contains(el)) return
      closeAll()
    }
    document.addEventListener('pointerdown', down, true)
    return () => document.removeEventListener('pointerdown', down, true)
  }, [stack.length, closeAll])

  // Вход в строку меню и выход — F10 и одиночный Alt (клавиши зовут через ui.menubar).
  const enter = useCallback(() => {
    prevFocus.current = document.activeElement as HTMLElement | null
    const narrow = window.matchMedia?.('(max-width: 760px)').matches
    ;(narrow ? burger.current : topButtons(topsRef.current)[0])?.focus()
  }, [])
  const leave = useCallback(() => {
    closeAll()
    const p = prevFocus.current
    prevFocus.current = null
    if (p && document.contains(p) && p !== document.body) p.focus()
    else (document.activeElement as HTMLElement | null)?.blur?.()
  }, [closeAll])
  const active = useCallback(
    () => !!stack.length || !!bar.current?.contains(document.activeElement),
    [stack.length],
  )
  useEffect(() => {
    ui.menubar.current = { enter, leave, active }
    return () => {
      ui.menubar.current = null
    }
  }, [ui.menubar, enter, leave, active])

  const runItem = (level: number, index: number) => {
    const it = stack[level]?.items[index]
    if (!it || it === 'sep' || it.disabled) return
    if (it.sub) {
      const el = levelsEl.current[level]?.querySelector<HTMLElement>(`[data-i="${index}"]`)
      if (el) openSub(level, el, it.sub(), true)
      return
    }
    const p = prevFocus.current
    prevFocus.current = null
    closeAll()
    if (p && document.contains(p) && p !== document.body) p.focus()
    it.act?.()
  }

  const moveTop = (d: number) => {
    const list = tops()
    const cur = typeof open === 'number' && open >= 0 ? open : list.indexOf(document.activeElement as HTMLButtonElement)
    if (cur < 0) return
    const i = (cur + d + list.length) % list.length
    if (stack.length) openTop(i, true)
    else list[i]?.focus()
  }

  const onDropdownKey = (e: ReactKeyboardEvent<HTMLDivElement>, level: number) => {
    const el = levelsEl.current[level]
    const list = el ? [...el.querySelectorAll<HTMLButtonElement>('.asm-mi:not([aria-disabled="true"])')] : []
    const i = list.indexOf(document.activeElement as HTMLButtonElement)
    const k = e.key
    const stop = () => {
      e.preventDefault()
      e.stopPropagation()
    }
    if (k === 'ArrowDown') {
      stop()
      list[(i + 1) % list.length]?.focus()
    } else if (k === 'ArrowUp') {
      stop()
      list[(i - 1 + list.length) % list.length]?.focus()
    } else if (k === 'Home') {
      stop()
      list[0]?.focus()
    } else if (k === 'End') {
      stop()
      list[list.length - 1]?.focus()
    } else if (k === 'ArrowRight') {
      stop()
      const idx = Number((document.activeElement as HTMLElement | null)?.dataset.i)
      const it = stack[level]?.items[idx]
      if (it && it !== 'sep' && it.sub) runItem(level, idx)
      else if (typeof open === 'number' && open >= 0) moveTop(1)
    } else if (k === 'ArrowLeft') {
      stop()
      if (level > 0) {
        const a = stack[level]?.anchor
        setStack((was) => was.slice(0, level))
        a?.focus()
      } else if (typeof open === 'number' && open >= 0) moveTop(-1)
    } else if (k === 'Escape') {
      stop()
      if (level > 0) {
        const a = stack[level]?.anchor
        setStack((was) => was.slice(0, level))
        a?.focus()
      } else closeAll(true)
    } else if (k === 'Enter' || k === ' ') {
      stop()
      const idx = Number((document.activeElement as HTMLElement | null)?.dataset.i)
      if (Number.isFinite(idx)) runItem(level, idx)
    } else if (k === 'Tab') {
      closeAll()
    }
  }

  const onTopKey = (e: ReactKeyboardEvent<HTMLButtonElement>, i: number) => {
    const k = e.key
    if (k === 'ArrowRight' || k === 'ArrowLeft') {
      e.preventDefault()
      moveTop(k === 'ArrowRight' ? 1 : -1)
    } else if (k === 'ArrowDown' || k === 'Enter' || k === ' ') {
      e.preventDefault()
      openTop(i, true)
    } else if (k === 'ArrowUp') {
      e.preventDefault()
      openTop(i, false)
      requestAnimationFrame(() => {
        const l = levelsEl.current[0]?.querySelectorAll<HTMLElement>('.asm-mi:not([aria-disabled="true"])')
        l?.[l.length - 1]?.focus()
      })
    } else if (k === 'Escape') {
      e.preventDefault()
      leave()
    }
  }

  return (
    <header className="asm-menubar" ref={bar}>
      <button
        ref={burger}
        type="button"
        className="asm-mb-burger"
        aria-haspopup="menu"
        aria-expanded={open === -1}
        aria-label={t('asm.menu.burger')}
        onClick={(e) =>
          open === -1
            ? closeAll()
            : openDropdown(
                -1,
                e.currentTarget,
                menus.map((x) => ({ label: x.label, sub: x.items })),
                e.detail === 0,
              )
        }
      >
        ☰
      </button>
      <div className="asm-mb-items" role="menubar" aria-label={t('asm.menu.label')} ref={topsRef}>
        {menus.map((menu, i) => (
          <button
            key={menu.label}
            type="button"
            className="asm-mb-item"
            role="menuitem"
            aria-haspopup="menu"
            aria-expanded={open === i}
            tabIndex={i === 0 ? 0 : -1}
            onClick={(e) => (open === i ? closeAll() : openTop(i, e.detail === 0))}
            onMouseEnter={() => {
              if (typeof open === 'number' && open >= 0 && open !== i) openTop(i, false)
            }}
            onKeyDown={(e) => onTopKey(e, i)}
          >
            {menu.label}
          </button>
        ))}
      </div>
      <Crumbs asm={asm} ui={ui} />
      <span className="grow" />
      <div className="asm-mb-right">
        <button
          type="button"
          className="asm-mode"
          title={t('asm.toolchain.chipHint')}
          onClick={() => ui.openDialog('buildOpts')}
        >
          {t(`asm.toolchain.${asm.toolchain.id}.chip`, { version: asm.program?.asmVersion ?? '' })}
        </button>
        <button
          type="button"
          className="asm-runbtn"
          disabled={asm.runBusy}
          title={`${t('asm.menu.build.run')} · Ctrl+Enter`}
          onClick={asm.buildAndRun}
        >
          <svg viewBox="0 0 8 9" aria-hidden="true">
            <path d="M0 0v9l8-4.5z" />
          </svg>
          {t('asm.menu.build.run')}
        </button>
        <RunStatus />
      </div>

      {stack.map((lv, level) =>
        createPortal(
          <div
            ref={(el) => {
              levelsEl.current[level] = el
            }}
            className="asm-dd"
            role="menu"
            style={{ left: lv.x, top: lv.y }}
            onKeyDown={(e) => onDropdownKey(e, level)}
          >
            {lv.items.map((it, i) =>
              it === 'sep' ? (
                <div key={`s${i}`} className="asm-dd-sep" role="separator" />
              ) : (
                <button
                  key={`${i}-${it.label}`}
                  type="button"
                  className="asm-mi"
                  data-i={i}
                  tabIndex={-1}
                  role={it.radio ? 'menuitemradio' : it.check !== undefined ? 'menuitemcheckbox' : 'menuitem'}
                  aria-checked={it.check !== undefined ? !!it.check : undefined}
                  aria-haspopup={it.sub ? 'menu' : undefined}
                  aria-expanded={it.sub ? stack[level + 1]?.anchor.dataset.i === String(i) : undefined}
                  aria-disabled={it.disabled || undefined}
                  onMouseEnter={(e) => {
                    if (document.activeElement !== e.currentTarget) e.currentTarget.focus({ preventScroll: true })
                    if (it.sub && !it.disabled) openSub(level, e.currentTarget, it.sub(), false)
                    else if (stack.length > level + 1) setStack((was) => was.slice(0, level + 1))
                  }}
                  onClick={() => runItem(level, i)}
                >
                  <span className="ck">{it.check ? (it.radio ? '●' : '✓') : ''}</span>
                  <span>{it.label}</span>
                  {it.sub ? <span className="sub">▸</span> : it.key ? <kbd>{it.key}</kbd> : <span />}
                </button>
              ),
            )}
          </div>,
          document.body,
          `asm-dd-${level}`,
        ),
      )}
    </header>
  )
}

/** Пункты строки меню. Вне компонента: зовётся из обработчиков, а ссылка — не зависимость. */
function topButtons(el: HTMLElement | null): HTMLButtonElement[] {
  return el ? [...el.querySelectorAll<HTMLButtonElement>('.asm-mb-item')] : []
}

function firstItem(el: HTMLElement | null | undefined): HTMLElement | null {
  return el?.querySelector<HTMLElement>('.asm-mi:not([aria-disabled="true"])') ?? null
}

function Crumbs({ asm, ui }: { asm: AsmContextValue; ui: AsmUi }) {
  const t = useT()
  const state = ui.saveState
  return (
    <div className="asm-crumbs">
      <span>{t('asm.title')}</span>
      <span aria-hidden="true">/</span>
      <button type="button" className="asm-crumb-name" onClick={() => ui.openDialog('rename')} title={t('asm.menu.file.rename')}>
        {asm.program?.name || t('asm.list.untitled')}
      </button>
      {state !== 'saved' && (
        <span className={cn('asm-save', `is-${state}`)} title={ui.saveError ?? undefined}>
          {t(`asm.save.${state}`)}
        </span>
      )}
    </div>
  )
}

/**
 * Чип состояния прогона: точка цвета состояния, короткий заголовок и
 * приглушённые подробности. Состояние — прогона, а не места на трассе: оно не
 * меняется, пока ходят по шагам. Щелчок ведёт туда, где разбираться: при
 * ошибке — в «Сборку» (там лог и текст отказа), иначе — в «Вывод».
 */
function RunStatus() {
  const t = useT()
  const asm = useAsm()
  const ui = useAsmUi()
  const run = asm.run

  let tone: 'idle' | 'run' | 'ok' | 'warn' | 'err' = 'idle'
  let head = t('asm.status.chip.idle')
  const details: string[] = []
  /** Полная причина остановки — только в подсказке: в строке меню ей тесно. */
  let reason: string | null = null
  let toBuild = false

  if (asm.runBusy) {
    tone = 'run'
    const { stage, n } = ui.progress
    // Ступени сборки — по режиму: `tasm`/`tlink` или `as`/`ld`.
    const buildStage = !!stage && (stage === asm.toolchain.stages[0] || stage === asm.toolchain.stages[1])
    if (stage === 'trace' || (!stage && run?.status === 'running')) {
      head = t('asm.status.chip.tracing')
      if (stage === 'trace' && n != null) details.push(fmtSteps(n))
    } else if (buildStage || (!stage && run?.status === 'building')) {
      head = t('asm.status.chip.building')
      if (stage) details.push(t(`asm.status.stages.${stage}`))
    } else head = t('asm.status.chip.queued')
  } else if (ui.runError) {
    tone = 'err'
    head = t('asm.status.chip.failed')
    details.push(ui.runError)
    toBuild = true
  } else if (ui.traceError) {
    tone = 'err'
    head = t('asm.status.chip.traceFailed')
    details.push(ui.traceError)
  } else if (run) {
    const steps = fmtSteps(run.totals.steps)
    const sec = t('asm.status.chip.sec', { s: fmtSec(run.totals.ms) })
    switch (run.status) {
      case 'build_error': {
        tone = 'err'
        head = t('asm.status.chip.buildError')
        toBuild = true
        const e = firstError(run)
        const errors = run.build?.messages.filter((m) => m.severity === 'error').length ?? 0
        if (e) details.push(t('asm.status.chip.line', { line: e.line }))
        else if (errors) details.push(t('asm.status.chip.errors', { n: errors }))
        break
      }
      case 'step_limit':
        tone = 'warn'
        head = t('asm.status.chip.stepLimit')
        details.push(steps)
        break
      case 'timeout':
        tone = 'err'
        head = t('asm.status.chip.timeout')
        details.push(steps, sec)
        reason = run.error
        break
      case 'crashed':
        tone = 'err'
        head = t('asm.status.chip.crashed')
        toBuild = true
        if (run.error) details.push(run.error)
        break
      case 'done':
        if (!run.totals.steps) {
          tone = 'ok'
          head = t('asm.status.chip.built')
          details.push(t('asm.status.chip.noRun'), sec)
        } else if (waitsForInput(run)) {
          tone = 'warn'
          head = t('asm.status.chip.waitInput')
          details.push(steps)
          reason = run.error
        } else {
          tone = 'ok'
          head = t('asm.status.chip.ready')
          details.push(steps, sec)
        }
        break
      default:
        tone = 'run'
        head = t('asm.status.chip.queued')
    }
  }

  const hint = [[head, ...details].join(' · '), reason, t(toBuild ? 'asm.status.chip.openBuild' : 'asm.status.chip.openOutput')]
    .filter(Boolean)
    .join('\n')

  return (
    <button
      type="button"
      className={cn('asm-status', `is-${tone}`)}
      title={hint}
      aria-live="polite"
      onClick={() => asm.openWindow(toBuild ? 'build' : 'output', { focus: true })}
    >
      <i aria-hidden="true" />
      <span className="hd">{head}</span>
      {details.length > 0 && <span className="dt">{details.join(' · ')}</span>}
    </button>
  )
}
