/**
 * theme/store — тема, светлый/тёмный, шрифт и плотность: хранение и применение.
 *
 * Три вещи, которые здесь сходятся:
 *
 * 1. **Хранится в `localStorage`** одним ключом `koritsu.appearance`. Одним, а не
 *    четырьмя: читает его встроенный скрипт в `index.html` (до первого рендера,
 *    иначе страница мигает чужими цветами), и разбирать там четыре ключа значило
 *    бы четырежды повторить одно и то же в разметке.
 * 2. **Применяется атрибутами на `<html>`** (`data-theme`, `data-mode`,
 *    `data-density`) и одной переменной `--font-ui`. Ни один компонент не знает,
 *    какая тема включена, — знает только CSS (`styles/themes.css`).
 * 3. **Разбор терпит мусор.** В `localStorage` может лежать что угодно (чужая
 *    вкладка, старая версия, ручная правка); неузнанное молча заменяется
 *    умолчанием, потому что «сломанные настройки внешнего вида» — не повод
 *    показать человеку пустой экран.
 *
 * Правка `index.html` обязана идти вместе с правкой этого файла: там тот же
 * разбор, написанный без импортов. Расхождение видно сразу — миганием.
 *
 * Имена в коде английские (правило экосистемы TypeScript и договор с агентами
 * B–E), комментарии русские — как во всём репозитории.
 */

import { DEFAULT_FONT } from './fonts'

export const THEMES = ['slate', 'paper', 'linear', 'glass'] as const
export type Theme = (typeof THEMES)[number]

export const MODES = ['light', 'dark'] as const
export type Mode = (typeof MODES)[number]

export const DENSITIES = ['comfortable', 'compact'] as const
export type Density = (typeof DENSITIES)[number]

/** Родной вариант темы: с ним она рисовалась и с ним показывается по умолчанию. */
export const NATIVE_MODE: Record<Theme, Mode> = {
  slate: 'dark',
  paper: 'light',
  linear: 'dark',
  glass: 'dark',
}

/** Название темы. Имя собственное, поэтому не в переводах, а здесь. */
export const THEME_NAME: Record<Theme, string> = {
  slate: 'Slate Pro',
  paper: 'Бумага',
  linear: 'Linear',
  glass: 'Liquid Glass',
}

export type Appearance = {
  theme: Theme
  mode: Mode
  /** Готовый стек CSS (см. `theme/fonts.ts`). */
  font: string
  density: Density
}

const KEY = 'koritsu.appearance'

export const DEFAULT_APPEARANCE: Appearance = {
  theme: 'slate',
  mode: NATIVE_MODE.slate,
  font: DEFAULT_FONT.stack,
  density: 'comfortable',
}

function isTheme(v: unknown): v is Theme {
  return typeof v === 'string' && (THEMES as readonly string[]).includes(v)
}

function isMode(v: unknown): v is Mode {
  return typeof v === 'string' && (MODES as readonly string[]).includes(v)
}

function isDensity(v: unknown): v is Density {
  return typeof v === 'string' && (DENSITIES as readonly string[]).includes(v)
}

/** Прочитать сохранённое. Мусор и отсутствие ключа дают умолчание. */
export function readAppearance(): Appearance {
  try {
    const raw = localStorage.getItem(KEY)
    if (!raw) return DEFAULT_APPEARANCE
    const s = JSON.parse(raw) as Partial<Appearance>
    const theme = isTheme(s.theme) ? s.theme : DEFAULT_APPEARANCE.theme
    return {
      theme,
      mode: isMode(s.mode) ? s.mode : NATIVE_MODE[theme],
      font: typeof s.font === 'string' && s.font ? s.font : DEFAULT_APPEARANCE.font,
      density: isDensity(s.density) ? s.density : DEFAULT_APPEARANCE.density,
    }
  } catch {
    // Приватный режим, переполненное хранилище, испорченный JSON — всё это
    // не повод падать: внешний вид не настолько важен.
    return DEFAULT_APPEARANCE
  }
}

export function writeAppearance(value: Appearance): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(value))
  } catch {
    // Запись может не удаться (квота, приватный режим). Тема на этой вкладке
    // уже применена — терять её из-за неудачной записи незачем.
  }
}

/** Повесить внешний вид на `<html>`. Единственное место, где это делается. */
export function applyAppearance(value: Appearance): void {
  const el = document.documentElement
  el.setAttribute('data-theme', value.theme)
  el.setAttribute('data-mode', value.mode)
  if (value.density === 'compact') el.setAttribute('data-density', 'compact')
  else el.removeAttribute('data-density')
  el.style.setProperty('--font-ui', value.font)
}
