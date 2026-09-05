/**
 * FormError — общая ошибка формы.
 *
 * `role="alert"` обязателен: сообщение появляется после нажатия, и без live-
 * region тот, кто не смотрит на экран, о нём не узнает вовсе.
 */
import { Icon } from '@/ui'

export function FormError({ text }: { text: string | null }) {
  if (!text) return null
  return (
    <div
      role="alert"
      className="flex items-start gap-s2 rounded-md border border-[color-mix(in_srgb,var(--err)_35%,transparent)] bg-err-bg px-s3 py-s2 text-sm text-ink"
    >
      <Icon name="error" size={18} className="mt-0.5 shrink-0 text-err" />
      <span>{text}</span>
    </div>
  )
}
