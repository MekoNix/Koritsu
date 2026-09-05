/**
 * ThemeProvider — внешний вид как состояние React.
 *
 * Первое значение берётся из `localStorage` тем же разбором, что и встроенный
 * скрипт `index.html`, поэтому переключения при загрузке не видно: атрибуты на
 * `<html>` уже стоят те же самые.
 *
 * Что здесь для настроек: `useAppearance()` возвращает текущий вид
 * и `set` — частичную правку (`set({ mode: 'light' })`). Всё остальное (запись
 * в хранилище, атрибуты на `<html>`) делается само.
 */
import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react'

import {
  applyAppearance,
  readAppearance,
  writeAppearance,
  NATIVE_MODE,
  type Appearance,
} from './store'

type ThemeCtx = {
  appearance: Appearance
  set: (patch: Partial<Appearance>) => void
}

const ThemeContext = createContext<ThemeCtx | null>(null)

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [appearance, setState] = useState<Appearance>(() => {
    const value = readAppearance()
    applyAppearance(value)
    return value
  })

  const set = useCallback((patch: Partial<Appearance>) => {
    setState((was) => {
      // Смена темы без явного выбора режима возвращает родной вариант темы:
      // «Бумага» в тёмном и Slate в светлом — законные состояния, но не то,
      // что человек ожидает увидеть, ткнув в тему первый раз.
      const themeChanged = patch.theme !== undefined && patch.theme !== was.theme
      const mode = patch.mode ?? (themeChanged ? NATIVE_MODE[patch.theme!] : was.mode)
      const next: Appearance = { ...was, ...patch, mode }
      applyAppearance(next)
      writeAppearance(next)
      return next
    })
  }, [])

  const value = useMemo<ThemeCtx>(() => ({ appearance, set }), [appearance, set])
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
}

// eslint-disable-next-line react-refresh/only-export-components
export function useAppearance(): ThemeCtx {
  const ctx = useContext(ThemeContext)
  if (!ctx) throw new Error('useAppearance вызван вне ThemeProvider')
  return ctx
}
