/**
 * AuthLayout — общая раскладка страниц входа по макету `10-auth-settings`.
 *
 * Композиция намеренно не «карточка по центру»: центрированная карточка —
 * признак отсутствия характера у темы. Поэтому
 * экран разрезан пополам — слева обещание продукта, справа полоса поверхности
 * с формой. На узкой ширине левая половина уходит: на телефоне обещание
 * продукта отнимает экран у поля ввода.
 *
 * Обещание короткое и общее: служба — это набор инструментов, а не один
 * генератор отчётов. Перечислять модули в заголовке нельзя — список меняется
 * с каждым новым модулем, и первое, что человек читает о продукте, устаревало
 * бы раньше всего остального.
 *
 * За текстом левой половины — рисунок (`AuthBackdrop`): он лежит фоном, ничего
 * не перекрывает и не занимает места в порядке чтения.
 */
import type { ReactNode } from 'react'

import { useT } from '@/i18n'

import { AuthBackdrop } from './AuthBackdrop'

export function AuthLayout({ children }: { children: ReactNode }) {
  const t = useT()
  return (
    <div className="grid min-h-screen lg:grid-cols-2">
      <section className="relative hidden flex-col justify-between overflow-hidden p-s8 lg:flex">
        <AuthBackdrop />
        <div className="relative flex items-center gap-s3">
          <span className="grid h-8 w-8 place-items-center rounded-sm bg-accent font-mono text-sm font-bold text-accent-ink">
            K
          </span>
          <span className="font-display text-xl font-bold tracking-tight text-ink-strong">
            {t('shell.brand')}
          </span>
        </div>

        <div className="relative max-w-[46ch]">
          <h1 className="font-display text-2xl font-bold leading-tight tracking-tight text-ink-strong">
            {t('auth.hero.title')}
          </h1>
          <p className="mt-s4 text-md text-muted">{t('auth.hero.text')}</p>
        </div>

        <p className="relative text-xs text-muted">{t('auth.hero.footer')}</p>
      </section>

      <section className="flex items-center justify-center border-l border-line bg-surface p-s5">
        <div className="w-full max-w-[400px]">{children}</div>
      </section>
    </div>
  )
}

/** Заголовок формы с подписью. Один на все страницы входа. */
export function AuthHeading({ title, text }: { title: string; text?: ReactNode }) {
  return (
    <header className="mb-s5">
      <h2 className="font-display text-xl font-bold tracking-tight text-ink-strong">{title}</h2>
      {text && <p className="mt-1 text-sm text-muted">{text}</p>}
    </header>
  )
}
