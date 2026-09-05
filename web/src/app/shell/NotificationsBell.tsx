/**
 * NotificationsBell — колокольчик и список последних уведомлений.
 *
 * Решение владельца: страницы уведомлений нет, есть колокольчик и список на
 * дашборде. Здесь — колокольчик: число непрочитанных на иконке и последние
 * записи в выпадающем списке.
 *
 * Открытие списка ничего не помечает прочитанным: человек мог открыть его,
 * чтобы посмотреть, и молча погашенный счётчик означал бы потерянное
 * уведомление. Помечает — кнопка «прочитать все» и клик по записи.
 *
 * **Клик ведёт на экран, где виден результат** (`features/notifications/link.ts`):
 * разбор файла — в опись материалов, тег и сборка — на экран отчёта, kadai — на
 * свою страницу. Проекта в данных нет — вести некуда, и запись просто ничего не
 * открывает: ссылка в никуда хуже её отсутствия. Собранный файл
 * (`data.artifacts`) скачивается прямо отсюда, не открывая экран, — это то
 * самое «скачивание из уведомления» из решений владельца.
 *
 * Счётчик живёт потоком: `useUserEvents` гасит ключ `notifications`, как только
 * служба что-то прислала, и число меняется само, без опроса по таймеру.
 *
 * Список открыт наружу (`features/notifications/bell.ts`): виджет дашборда
 * ссылкой «все» открывает этот же колокольчик, потому что страницы, куда
 * можно было бы уйти, нет.
 */
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { useMarkAllNotificationsRead, useMarkNotificationRead, useNotifications } from '@/api/hooks'
import type { Notification } from '@/api/types'
import { onOpenBell } from '@/features/notifications/bell'
import { notificationDownload, notificationLink } from '@/features/notifications/link'
import { TITLE_KEY, kindTitle, lookOf, when } from '@/features/notifications/present'
import { useT } from '@/i18n'
import { cn } from '@/lib/cn'
import {
  Badge,
  Button,
  Icon,
  MenuContent,
  MenuItem,
  MenuRoot,
  MenuSeparator,
  MenuTrigger,
  SkeletonLines,
} from '@/ui'

export function NotificationsBell() {
  const t = useT()
  const [open, setOpen] = useState(false)
  const { data, isLoading } = useNotifications(20)
  const markOne = useMarkNotificationRead()
  const markAll = useMarkAllNotificationsRead()

  // Виджет дашборда открывает тот же список: страницы уведомлений нет.
  useEffect(() => onOpenBell(() => setOpen(true)), [])

  const unread = data?.unread_count ?? 0
  const items = data?.notifications ?? []

  return (
    <MenuRoot open={open} onOpenChange={setOpen}>
      <MenuTrigger asChild>
        <Button
          variant="ghost"
          size="sm"
          iconOnly
          className="relative text-ink"
          aria-label={t('shell.notifications.label')}
        >
          <Icon name="bell" size={18} />
          <Badge
            count={unread}
            tone="err"
            className="absolute -right-1 -top-1 h-[15px] min-w-[15px] px-1 text-[10px]"
            label={t('shell.notifications.unread', { n: unread })}
          />
        </Button>
      </MenuTrigger>
      <MenuContent className="max-h-[70vh] w-[380px] max-w-[calc(100vw-24px)] overflow-y-auto">
        <div className="flex items-center gap-s2 px-2.5 py-1.5">
          <span className="flex-1 text-xs uppercase tracking-wider text-muted">
            {t('shell.notifications.label')}
          </span>
          {unread > 0 && (
            <button
              type="button"
              className="text-xs text-accent hover:underline"
              onClick={() => markAll.mutate()}
            >
              {t('shell.notifications.readAll')}
            </button>
          )}
        </div>
        <MenuSeparator />
        {isLoading && (
          <div className="p-s3">
            <SkeletonLines count={3} />
          </div>
        )}
        {!isLoading && items.length === 0 && (
          <p className="px-2.5 py-s4 text-center text-sm text-muted">
            {t('shell.notifications.empty')}
          </p>
        )}
        {items.map((item) => (
          <Row key={item.id} item={item} onRead={() => markOne.mutate(item.id)} />
        ))}
      </MenuContent>
    </MenuRoot>
  )
}

function Row({ item, onRead }: { item: Notification; onRead: () => void }) {
  const t = useT()
  const navigate = useNavigate()
  const look = lookOf(item.kind)
  const key = TITLE_KEY[item.kind]
  const title = key ? t(key) : item.kind
  const to = notificationLink(item.data)
  const file = notificationDownload(item.data)
  const вид = typeof item.data?.job_kind === 'string' ? item.data.job_kind : ''
  const подпись = kindTitle(вид)

  return (
    <MenuItem
      className="items-start"
      onSelect={() => {
        if (!item.read_at) onRead()
        if (to) navigate(to)
      }}
      icon={<Icon name={look.icon} size={18} className={look.color} />}
    >
      <span className="min-w-0 flex-1">
        <span
          className={cn(
            'block truncate',
            item.read_at ? 'text-muted' : 'font-semibold text-ink-strong',
          )}
        >
          {title}
        </span>
        <span className="block truncate text-xs text-muted">
          {подпись ? `${подпись} · ` : ''}
          {when(item.created_at)}
        </span>
      </span>
      {file && (
        <a
          href={file.url}
          // Клик по ссылке не должен выбирать пункт меню: скачивание не повод
          // уходить с текущего экрана.
          onClick={(e) => e.stopPropagation()}
          className="ml-s2 shrink-0 self-center text-xs text-accent hover:underline"
        >
          {t('notifications.download')}
        </a>
      )}
    </MenuItem>
  )
}
