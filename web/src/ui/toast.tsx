/**
 * toast — короткое сообщение в углу.
 *
 * **Когда тостить.** Правило: тост показывается на завершение
 * фоновой задачи и на ошибку, всё остальное живёт в колокольчике. Это правило
 * держится не документацией, а тем, что тост вызывается ровно из двух мест —
 * из потока событий (`useUserEvents`) и из обработки отказов. Появление
 * `toast.info('сохранено')` в экране — повод не звать, а убрать.
 *
 * **Почему Radix.** Тост — самая коварная мелочь в доступности: он обязан
 * объявиться скринридеру, не украв фокус, и не исчезнуть под курсором.
 * `@radix-ui/react-toast` делает это (`role="status"`, live-region, пауза на
 * наведении и на фокусе, свайп).
 *
 * Тексты сюда приходят готовыми: тост ничего не переводит сам, иначе перевод
 * ошибки оказался бы в двух местах — здесь и в `errorText()`.
 */
import * as RadixToast from '@radix-ui/react-toast'
import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react'

import { useT } from '@/i18n'
import { cn } from '@/lib/cn'

import { Icon, type IconName } from './Icon'

export type ToastKind = 'ok' | 'err' | 'warn' | 'info' | 'agent'

type ToastItem = {
  id: number
  kind: ToastKind
  title: string
  text?: string
}

type ToastApi = {
  show: (kind: ToastKind, title: string, text?: string) => void
  success: (title: string, text?: string) => void
  error: (title: string, text?: string) => void
  warn: (title: string, text?: string) => void
  agent: (title: string, text?: string) => void
}

const ToastContext = createContext<ToastApi | null>(null)

const ICONS: Record<ToastKind, IconName> = {
  ok: 'checkCircle',
  err: 'error',
  warn: 'warning',
  info: 'info',
  agent: 'agent',
}

const COLORS: Record<ToastKind, string> = {
  ok: 'text-ok',
  err: 'text-err',
  warn: 'text-warn',
  info: 'text-info',
  agent: 'text-agent',
}

/** Шесть секунд — как в макете: хватает прочитать, не хватает надоесть. */
const DURATION = 6000

let nextId = 1

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([])
  const t = useT()

  const show = useCallback((kind: ToastKind, title: string, text?: string) => {
    setItems((was) => [...was, { id: nextId++, kind, title, text }])
  }, [])

  const api = useMemo<ToastApi>(
    () => ({
      show,
      success: (title, text) => show('ok', title, text),
      error: (title, text) => show('err', title, text),
      warn: (title, text) => show('warn', title, text),
      agent: (title, text) => show('agent', title, text),
    }),
    [show],
  )

  const drop = useCallback((id: number) => {
    setItems((was) => was.filter((item) => item.id !== id))
  }, [])

  return (
    <ToastContext.Provider value={api}>
      <RadixToast.Provider duration={DURATION} label={t('ui.toast.region')}>
        {children}
        {items.map((item) => (
          <RadixToast.Root
            key={item.id}
            onOpenChange={(open) => !open && drop(item.id)}
            className={cn(
              'flex items-start gap-s3 rounded-md border border-line bg-elevated px-s4 py-s3 text-sm shadow-2',
              'backdrop-blur-theme animate-toast-in',
            )}
          >
            <Icon name={ICONS[item.kind]} className={cn('mt-0.5', COLORS[item.kind])} />
            <div className="min-w-0 flex-1">
              <RadixToast.Title className="font-semibold text-ink-strong">
                {item.title}
              </RadixToast.Title>
              {item.text && (
                <RadixToast.Description className="text-muted">{item.text}</RadixToast.Description>
              )}
            </div>
            <RadixToast.Close
              aria-label={t('ui.toast.close')}
              className="text-muted hover:text-ink"
            >
              <Icon name="close" size={16} />
            </RadixToast.Close>
          </RadixToast.Root>
        ))}
        <RadixToast.Viewport className="fixed bottom-s4 right-s4 z-[200] flex w-[min(380px,calc(100vw-32px))] flex-col gap-s2 outline-none" />
      </RadixToast.Provider>
    </ToastContext.Provider>
  )
}

// eslint-disable-next-line react-refresh/only-export-components
export function useToast(): ToastApi {
  const ctx = useContext(ToastContext)
  if (!ctx) throw new Error('useToast вызван вне ToastProvider')
  return ctx
}
