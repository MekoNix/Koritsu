/**
 * Menu — выпадающее меню на Radix (`DropdownMenu`).
 *
 * Radix даёт то, что руками пишется неделю и всё равно с дырами: стрелки,
 * `Home`/`End`, набор первой буквы, закрытие по `Esc` и клику мимо, возврат
 * фокуса, правильные роли. Здесь — вид по макету и три вещи для удобства:
 * `MenuItem` с иконкой, `danger` для «выйти» и «удалить», `MenuSeparator`.
 *
 * Пункт меню — это `<div role="menuitem">`, не ссылка. Если нужен переход,
 * оборачивайте `Link` через `asChild`: тогда работает Ctrl+клик и «открыть в
 * новой вкладке», без которых меню профиля раздражает.
 */
import * as RadixMenu from '@radix-ui/react-dropdown-menu'
import type { ComponentPropsWithoutRef, ReactNode } from 'react'

import { cn } from '@/lib/cn'

export const MenuRoot = RadixMenu.Root
export const MenuTrigger = RadixMenu.Trigger

export function MenuContent({
  className,
  align = 'end',
  sideOffset = 6,
  children,
  ...rest
}: ComponentPropsWithoutRef<typeof RadixMenu.Content>) {
  return (
    <RadixMenu.Portal>
      <RadixMenu.Content
        align={align}
        sideOffset={sideOffset}
        className={cn(
          'z-[60] min-w-[200px] rounded-md border border-line bg-elevated p-1 shadow-2 backdrop-blur-theme',
          className,
        )}
        {...rest}
      >
        {children}
      </RadixMenu.Content>
    </RadixMenu.Portal>
  )
}

export type MenuItemProps = ComponentPropsWithoutRef<typeof RadixMenu.Item> & {
  icon?: ReactNode
  /** Опасное действие — выход, удаление. */
  danger?: boolean
}

export function MenuItem({ className, icon, danger, children, ...rest }: MenuItemProps) {
  return (
    <RadixMenu.Item
      className={cn(
        'flex w-full cursor-pointer select-none items-center gap-s2 rounded-sm px-2.5 py-2 text-sm outline-none',
        'data-[highlighted]:bg-surface-2',
        'data-[disabled]:pointer-events-none data-[disabled]:opacity-50',
        danger ? 'text-err' : 'text-ink',
        className,
      )}
      {...rest}
    >
      {icon && <span className={danger ? 'text-err' : 'text-muted'}>{icon}</span>}
      {children}
    </RadixMenu.Item>
  )
}

export function MenuSeparator({ className }: { className?: string }) {
  return <RadixMenu.Separator className={cn('my-1 h-px bg-line', className)} />
}

export function MenuLabel({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <RadixMenu.Label
      className={cn('px-2.5 pb-1 pt-1.5 text-xs uppercase tracking-wider text-muted', className)}
    >
      {children}
    </RadixMenu.Label>
  )
}
