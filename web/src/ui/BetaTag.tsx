/**
 * BetaTag — метка «Beta» у модуля, который уже открыт людям, но ещё обкатывается.
 *
 * Не `Chip`: у пилюли состояния точка и моноширинный текст, она подписывает то, что
 * меняется (прогон идёт, ключ отозван). Метка беты постоянна для модуля и стоит рядом с
 * его названием — в сайдбаре, на плитке дашборда и в заголовке страницы, — поэтому она
 * меньше, без точки и одного цвета с акцентом.
 */
import { cn } from '@/lib/cn'

export function BetaTag({ label, className }: { label: string; className?: string }) {
  return (
    <span
      className={cn(
        'inline-flex shrink-0 items-center rounded-full border px-1.5 py-px text-[10px] font-semibold uppercase leading-none tracking-wider',
        'border-[color-mix(in_srgb,var(--accent)_45%,transparent)] bg-accent-bg text-accent',
        className,
      )}
    >
      {label}
    </span>
  )
}
