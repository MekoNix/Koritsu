/**
 * fonts — список шрифтов интерфейса для выбора в настройках.
 *
 * Правило брифа: **только шрифты с полной кириллицей**. Поэтому список закрытый
 * и лежит здесь, а не собирается из того, что нашлось в системе: «нашлось» на
 * чужой машине означает подстановку, в которой половина букв другой ширины.
 *
 * `bundled: true` — шрифт приезжает с сайтом (npm-пакет `@fontsource/*`,
 * кириллическое подмножество), то есть выглядит одинаково у всех. Остальные —
 * системные: они есть почти везде и все они кириллические, но рисуются
 * шрифтом операционной системы.
 *
 * Google Fonts не подключаются нигде и никогда.
 *
 * Что делают настройки: показывают `FONTS` списком, при выборе зовут
 * `set({ font: <stack> })` из `useAppearance()`. Значение хранится готовым
 * стеком CSS — так его кладут прямо в `--font-ui`, и новый шрифт не требует ни
 * одной правки в применении темы.
 */

export type Font = {
  /** Короткий идентификатор для настроек и тестов. */
  id: string
  /** Как называется в списке (имя шрифта, не текст интерфейса, — поэтому не в переводах). */
  name: string
  /**
   * Ключ перевода, если названия у шрифта нет и в списке стоит слово («системный»).
   * Имя собственное («Arial») в словарь не кладётся — переводить его нечем.
   */
  nameKey?: string
  /** Значение для `--font-ui`. */
  stack: string
  /** Приезжает с сайтом (иначе — системный). */
  bundled: boolean
}

export const FONTS: readonly Font[] = [
  {
    id: 'plex',
    name: 'IBM Plex Sans',
    stack: "'IBM Plex Sans', system-ui, 'Segoe UI', Roboto, sans-serif",
    bundled: true,
  },
  {
    id: 'system',
    name: 'System UI',
    nameKey: 'settings.appearance.fontSystemName',
    stack: "system-ui, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif",
    bundled: false,
  },
  {
    id: 'arial',
    name: 'Arial',
    stack: "Arial, 'Helvetica Neue', Helvetica, sans-serif",
    bundled: false,
  },
  {
    id: 'verdana',
    name: 'Verdana',
    stack: 'Verdana, Geneva, sans-serif',
    bundled: false,
  },
  {
    id: 'tahoma',
    name: 'Tahoma',
    stack: 'Tahoma, Geneva, Verdana, sans-serif',
    bundled: false,
  },
  {
    id: 'georgia',
    name: 'Georgia',
    stack: "Georgia, 'Times New Roman', serif",
    bundled: false,
  },
] as const

/** Шрифт по умолчанию — тот, что приезжает с сайтом. */
export const DEFAULT_FONT: Font = FONTS[0] as Font

export function fontByStack(stack: string | null | undefined): Font | undefined {
  return FONTS.find((f) => f.stack === stack)
}
