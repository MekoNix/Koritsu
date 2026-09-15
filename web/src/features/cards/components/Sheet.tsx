/**
 * Sheet — нижний лист телефона и окно, которое само выбирает вид.
 *
 * `BottomSheet` — модальный лист у нижнего края: заголовок, прокручиваемое содержимое,
 * кнопки внизу под большим пальцем с отступом `safe-area` (полоса жестов iPhone их не
 * перекрывает). Устроен на том же Radix Dialog, что и `ui/Dialog`: ловушка фокуса,
 * `Esc`, возврат фокуса и блокировка прокрутки под листом — оттуда.
 *
 * `AdaptiveDialog` — те же свойства: на телефоне (≤ 640 px) лист, на компьютере —
 * обычное окно по центру. Окно по центру на узком экране упирается в края и прячет
 * кнопки под клавиатурой, лист — нет.
 */
import * as RadixDialog from '@radix-ui/react-dialog'
import type { ReactNode } from 'react'

import { useT } from '@/i18n'
import { Button, Dialog, Icon } from '@/ui'

import { useIsPhone } from '../hooks/useIsPhone'

export type BottomSheetProps = {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: ReactNode
  description?: ReactNode
  children?: ReactNode
  /** Кнопки внизу; на листе встают столбиком во всю ширину, последняя — ниже всех. */
  footer?: ReactNode
}

export function BottomSheet({ open, onOpenChange, title, description, children, footer }: BottomSheetProps) {
  const t = useT()
  return (
    <RadixDialog.Root open={open} onOpenChange={onOpenChange}>
      <RadixDialog.Portal>
        <RadixDialog.Overlay className="fixed inset-0 z-[100] bg-overlay" />
        <RadixDialog.Content
          {...(description ? {} : { 'aria-describedby': undefined })}
          className="fixed inset-x-0 bottom-0 z-[101] flex max-h-[88vh] flex-col rounded-t-lg border-t border-line bg-elevated shadow-2 outline-none backdrop-blur-theme"
        >
          <div aria-hidden="true" className="mx-auto mt-s2 h-1 w-10 shrink-0 rounded-full bg-line-strong" />
          <div className="flex items-center gap-s2 px-s4 pt-s1">
            <RadixDialog.Title className="min-w-0 flex-1 font-display text-lg font-semibold text-ink-strong">{title}</RadixDialog.Title>
            <RadixDialog.Close asChild>
              <Button variant="ghost" size="lg" iconOnly aria-label={t('ui.dialog.close')} className="-mr-s2">
                <Icon name="close" size={20} />
              </Button>
            </RadixDialog.Close>
          </div>
          {description && <RadixDialog.Description className="px-s4 text-sm text-muted">{description}</RadixDialog.Description>}
          <div
            className={
              footer
                ? 'min-h-0 flex-1 overflow-y-auto overscroll-contain px-s4 py-s3'
                : 'min-h-0 flex-1 overflow-y-auto overscroll-contain px-s4 pt-s3 pb-[max(env(safe-area-inset-bottom),var(--space-4))]'
            }
          >
            {children}
          </div>
          {footer && (
            <div className="flex flex-col gap-s2 border-t border-line bg-surface-2 px-s4 pt-s3 pb-[max(env(safe-area-inset-bottom),var(--space-3))] [&>button]:min-h-[44px] [&>button]:w-full">
              {footer}
            </div>
          )}
        </RadixDialog.Content>
      </RadixDialog.Portal>
    </RadixDialog.Root>
  )
}

export type AdaptiveDialogProps = BottomSheetProps & { size?: 'md' | 'lg' | 'xl' }

export function AdaptiveDialog({ size = 'md', ...props }: AdaptiveDialogProps) {
  const isPhone = useIsPhone()
  if (isPhone) return <BottomSheet {...props} />
  return (
    <Dialog
      open={props.open}
      onOpenChange={props.onOpenChange}
      title={props.title}
      description={props.description}
      footer={props.footer}
      size={size}
    >
      {props.children}
    </Dialog>
  )
}
