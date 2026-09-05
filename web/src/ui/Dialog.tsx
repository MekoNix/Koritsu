/**
 * Dialog — модальное окно на Radix.
 *
 * Radix берёт на себя всё, что легко забыть и невозможно заметить глазами:
 * ловушку фокуса, возврат фокуса на кнопку после закрытия, `Esc`, блокировку
 * прокрутки под окном и `aria-modal`. Здесь — только вид по макету.
 *
 * Заголовок обязателен (`title`): диалог без заголовка скринридер объявляет
 * как «диалог», и человек не знает, о чём его спросили.
 */
import * as RadixDialog from '@radix-ui/react-dialog'
import type { ReactNode } from 'react'

import { useT } from '@/i18n'
import { cn } from '@/lib/cn'

import { Button } from './Button'
import { Icon } from './Icon'

export type DialogProps = {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: ReactNode
  description?: ReactNode
  children?: ReactNode
  /** Кнопки внизу. */
  footer?: ReactNode
  size?: 'md' | 'lg' | 'xl'
}

const SIZES = {
  md: 'w-[min(520px,100%)]',
  lg: 'w-[min(860px,100%)]',
  xl: 'w-[min(1100px,100%)]',
} as const

export function Dialog({
  open,
  onOpenChange,
  title,
  description,
  children,
  footer,
  size = 'md',
}: DialogProps) {
  const t = useT()
  return (
    <RadixDialog.Root open={open} onOpenChange={onOpenChange}>
      <RadixDialog.Portal>
        <RadixDialog.Overlay className="fixed inset-0 z-[100] bg-overlay" />
        <RadixDialog.Content
          className={cn(
            'fixed left-1/2 top-1/2 z-[101] flex max-h-[90vh] -translate-x-1/2 -translate-y-1/2 flex-col overflow-hidden',
            'rounded-lg border border-line bg-elevated shadow-2 backdrop-blur-theme',
            SIZES[size],
          )}
        >
          <div className="flex items-center gap-3 border-b border-line px-s5 py-s4">
            <RadixDialog.Title className="flex-1 font-display text-lg font-semibold text-ink-strong">
              {title}
            </RadixDialog.Title>
            <RadixDialog.Close asChild>
              {/* «Закрыть окно», а не «Закрыть»: в подвале окна часто стоит
                  своя кнопка «Закрыть», и две кнопки с одним именем — это
                  клавиатура и скринридер, в которых не отличить одну от другой. */}
              <Button variant="ghost" size="sm" iconOnly aria-label={t('ui.dialog.close')}>
                <Icon name="close" size={16} />
              </Button>
            </RadixDialog.Close>
          </div>
          {description && (
            <RadixDialog.Description className="px-s5 pt-s4 text-sm text-muted">
              {description}
            </RadixDialog.Description>
          )}
          <div className="overflow-auto p-s5">{children}</div>
          {footer && (
            <div className="flex justify-end gap-s2 border-t border-line bg-surface-2 px-s5 py-s3">
              {footer}
            </div>
          )}
        </RadixDialog.Content>
      </RadixDialog.Portal>
    </RadixDialog.Root>
  )
}

export const DialogClose = RadixDialog.Close
