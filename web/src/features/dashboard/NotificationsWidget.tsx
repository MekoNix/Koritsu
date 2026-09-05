/**
 * NotificationsWidget — последние уведомления на дашборде.
 *
 * Правило: уведомления — только колокольчик плюс список на дашборде, страницы
 * нет. Отсюда две особенности виджета:
 *
 * * показываются **пять последних**, а не все: лента дашборда — обзор, а не
 *   журнал; ссылка «все» открывает тот же колокольчик, потому что уходить
 *   некуда — страницы нет;
 * * клик по строке помечает прочитанным и ведёт туда же, куда из колокольчика
 *   (`features/notifications/link.ts`), — два разных поведения у одной записи
 *   человек воспринял бы как две разные записи.
 *
 * Строка — кнопка, а не `div` с обработчиком: список открывается и с
 * клавиатуры. Убрать строку можно и отсюда: колокольчик — не архив, и правило
 * «два разных поведения у одной записи человек прочитает как две разные записи»
 * действует и здесь.
 *
 * Приглашение в пространство отвечать на себя отсюда не даёт: кнопки «принять»
 * и «отклонить» стоят в колокольчике, а виджет — обзор на пять строк, и
 * действие, спрятанное в обзоре, человек находит случайно. Строка приглашения
 * поэтому просто открывает колокольчик.
 */
import { useNavigate } from 'react-router-dom'

import { useDeleteNotification, useMarkNotificationRead, useNotifications } from '@/api/hooks'
import { openBell } from '@/features/notifications/bell'
import { inviteOf } from '@/features/notifications/invite'
import { notificationLink } from '@/features/notifications/link'
import { TITLE_KEY, lookOf, when } from '@/features/notifications/present'
import { useT } from '@/i18n'
import { cn } from '@/lib/cn'
import { EmptyState, ErrorState, Icon, SkeletonLines } from '@/ui'

import { Widget } from './Widget'

/** Сколько записей в виджете. Больше — уже журнал, а журнала здесь нет. */
const СКОЛЬКО = 5

export function NotificationsWidget() {
  const t = useT()
  const navigate = useNavigate()
  const { data, isLoading, error, refetch } = useNotifications(20)
  const markOne = useMarkNotificationRead()
  const drop = useDeleteNotification()

  const items = (data?.notifications ?? []).slice(0, СКОЛЬКО)

  return (
    <Widget
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
            const приглашение = inviteOf(item)
            const to = приглашение ? null : notificationLink(item.data)
            return (
              <li key={item.id} className="flex items-start gap-s1">
                <button
                  type="button"
                  className="flex min-w-0 flex-1 items-start gap-s2 rounded-sm px-2 py-1.5 text-left hover:bg-surface-2"
                  onClick={() => {
                    // На приглашение отвечают кнопками в колокольчике — туда и
                    // ведём, вместо того чтобы прятать ответ в обзоре.
                    if (приглашение) {
                      openBell()
                      return
                    }
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
                      {приглашение
                        ? t('notifications.invite.title', { name: приглашение.workspaceName })
                        : key
                          ? t(key)
                          : item.kind}
                    </span>
                    <span className="block text-xs text-muted">{when(item.created_at)}</span>
                  </span>
                </button>
                <button
                  type="button"
                  aria-label={t('notifications.delete')}
                  title={t('notifications.delete')}
                  className="mt-1.5 shrink-0 rounded-sm p-1 text-muted hover:bg-surface-2 hover:text-err"
                  onClick={() => drop.mutate(item.id)}
                >
                  <Icon name="close" size={14} />
                </button>
              </li>
            )
          })}
        </ul>
      )}
    </Widget>
  )
}
