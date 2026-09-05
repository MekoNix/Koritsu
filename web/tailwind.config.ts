import type { Config } from 'tailwindcss'

// Единственный источник цвета и ритма — переменные темы (`src/styles/themes.css`).
// Tailwind здесь не заводит своей палитры: любой класс вида `bg-surface` разворачивается
// в `var(--surface)`, поэтому смена темы на `<html>` перекрашивает всё разом и ни один
// компонент не знает, какая тема включена.
//
// Прозрачность через `/50` у таких цветов не работает (значение переменной — готовый
// цвет, а не тройка каналов). Если нужен полупрозрачный оттенок — берите готовую
// переменную (`--accent-bg`, `--ok-bg`, …) или `color-mix` в собственном CSS.
const config: Config = {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        bg: 'var(--bg)',
        surface: 'var(--surface)',
        'surface-2': 'var(--surface-2)',
        'surface-3': 'var(--surface-3)',
        elevated: 'var(--surface-elevated)',
        overlay: 'var(--overlay)',

        ink: 'var(--ink)',
        'ink-strong': 'var(--ink-strong)',
        muted: 'var(--muted)',
        line: 'var(--line)',
        'line-strong': 'var(--line-strong)',

        accent: 'var(--accent)',
        'accent-ink': 'var(--accent-ink)',
        'accent-bg': 'var(--accent-bg)',
        ok: 'var(--ok)',
        'ok-bg': 'var(--ok-bg)',
        warn: 'var(--warn)',
        'warn-bg': 'var(--warn-bg)',
        err: 'var(--err)',
        'err-bg': 'var(--err-bg)',
        info: 'var(--info)',
        'info-bg': 'var(--info-bg)',
        agent: 'var(--agent)',
        'agent-ink': 'var(--agent-ink)',
        'agent-bg': 'var(--agent-bg)',

        'mod-dashboard': 'var(--mod-dashboard)',
        'mod-flowcharts': 'var(--mod-flowcharts)',
        'mod-uml': 'var(--mod-uml)',
        'mod-reports': 'var(--mod-reports)',
      },
      borderRadius: {
        sm: 'var(--radius-sm)',
        DEFAULT: 'var(--radius)',
        md: 'var(--radius)',
        lg: 'var(--radius-lg)',
        full: 'var(--radius-full)',
        btn: 'var(--btn-radius)',
      },
      borderWidth: {
        DEFAULT: 'var(--border-w)',
      },
      fontFamily: {
        // `--font-ui` — то, что выбирается в настройках; темы подставляют его
        // в `--font-display`/`--font-body` (кроме «Бумаги», см. themes.css).
        ui: 'var(--font-ui)',
        display: 'var(--font-display)',
        body: 'var(--font-body)',
        mono: 'var(--font-mono)',
      },
      fontSize: {
        xs: ['var(--size-xs)', { lineHeight: 'var(--leading-normal)' }],
        sm: ['var(--size-sm)', { lineHeight: 'var(--leading-normal)' }],
        md: ['var(--size-md)', { lineHeight: 'var(--leading-normal)' }],
        base: ['var(--size-md)', { lineHeight: 'var(--leading-normal)' }],
        lg: ['var(--size-lg)', { lineHeight: 'var(--leading-tight)' }],
        xl: ['var(--size-xl)', { lineHeight: 'var(--leading-tight)' }],
        '2xl': ['var(--size-2xl)', { lineHeight: 'var(--leading-tight)' }],
      },
      spacing: {
        s1: 'var(--space-1)',
        s2: 'var(--space-2)',
        s3: 'var(--space-3)',
        s4: 'var(--space-4)',
        s5: 'var(--space-5)',
        s6: 'var(--space-6)',
        s8: 'var(--space-8)',
        sidebar: 'var(--sidebar-w)',
        'sidebar-collapsed': 'var(--sidebar-w-collapsed)',
        topbar: 'var(--topbar-h)',
      },
      maxWidth: {
        content: 'var(--content-max)',
      },
      boxShadow: {
        1: 'var(--shadow-1)',
        2: 'var(--shadow-2)',
      },
      backdropBlur: {
        theme: '14px',
      },
      keyframes: {
        shimmer: { to: { backgroundPosition: '-200% 0' } },
        spin: { to: { transform: 'rotate(360deg)' } },
        'toast-in': { from: { opacity: '0', transform: 'translateY(8px)' } },
      },
      animation: {
        shimmer: 'shimmer 1.4s infinite linear',
        'toast-in': 'toast-in .2s ease-out',
      },
    },
  },
  plugins: [],
}

export default config
