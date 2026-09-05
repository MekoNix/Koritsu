/**
 * NotificationsWidget — последние уведомления на дашборде.
 *
 * Решение владельца дословно: «уведомления — только колокольчик плюс список на
 * дашборде, страницы нет». Отсюда две особенности виджета:
 *
 * * показываются **пять последних**, а не все: лента дашборда — обзор, а не
 *   журнал; ссылка «все» открывает тот же колокольчик, потому что уходить
 *   некуда — страницы нет;
 * * клик по строке помечает прочитанным и ведёт туда же, куда из колокольчика
 *   (`features/notifications/link.ts`), — два разных поведения у одной записи
 *   человек воспринял бы как две разные записи.
 *
 * Строка — кнопка, а не `div` с обработчиком: список открывается и с
 * клавиатуры.
 */
import { useNavigate } from 'react-router-dom'

import { useMarkNotificationRead, useNotifications } from '@/api/hooks'
import { openBell } from '@/features/notifications/bell'
import { notificationLink } from '@/features/notifications/link'
import { TITLE_KEY, lookOf, when } from '@/features/notifications/present'
import { useT } from '@/i18n'
import { cn } from '@/lib/cn'
import { EmptyState, ErrorState, Icon, SkeletonLines } from '@/ui'

import { Widget } from './Widget'

/** Сколько записей в виджете. Больше — уже журнал, а его владелец не просил. */
const СКОЛЬКО = 5

export function NotificationsWidget() {
  const t = useT()
  const navigate = useNavigate()
  const { data, isLoading, error, refetch } = useNotifications(20)
  const markOne = useMarkNotificationRead()

  const items = (data?.notifications ?? []).slice(0, СКОЛЬКО)

  return (
    <Widget
      className="sm:col-span-6 lg:col-span-6"
      title={t('notifications.widget.title')}
      note={
        data && data.unread_count > 0
          ? t('notifications.widget.unread', { n: data.unread_count })
          : undefined
      }
      action={
        <button type="button" className="text-xs text-accent hover:underline" onClick={openBell}>
          {t('notifications.widget.all')}
        </button>
      }
    >
      {isLoading && <SkeletonLines count={3} />}
      {error && <ErrorState error={error} onRetry={() => void refetch()} />}
      {!isLoading && !error && items.length === 0 && (
        <EmptyState
          compact
          icon="bell"
          title={t('notifications.widget.empty')}
          text={t('notifications.widget.emptyHint')}
        />
      )}
      {items.length > 0 && (
        <ul className="flex flex-col">
          {items.map((item) => {
            const look = lookOf(item.kind)
            const key = TITLE_KEY[item.kind]
            const to = notificationLink(item.data)
            return (
              <li key={item.id}>
                <button
                  type="button"
                  className="flex w-full items-start gap-s2 rounded-sm px-2 py-1.5 text-left hover:bg-surface-2"
                  onClick={() => {
                    if (!item.read_at) markOne.mutate(item.id)
                    if (to) navigate(to)
                  }}
                >
                  <Icon name={look.icon} size={18} className={cn('mt-0.5', look.color)} />
                  <span className="min-w-0 flex-1">
                    <span
                      className={cn(
                        'block truncate text-sm',
                        item.read_at ? 'text-muted' : 'font-semibold text-ink-strong',
                      )}
                    >
                      {key ? t(key) : item.kind}
                    </span>
                    <span className="block text-xs text-muted">{when(item.created_at)}</span>
                  </span>
                </button>
              </li>
            )
          })}
        </ul>
      )}
    </Widget>
  )
}
