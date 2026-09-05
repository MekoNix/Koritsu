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
 */
import { useMarkAllNotificationsRead, useMarkNotificationRead, useNotifications } from '@/api/hooks'
import type { Notification } from '@/api/types'
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
  type IconName,
} from '@/ui'

/** Вид уведомления → иконка и цвет. Неизвестный вид — нейтральная иконка. */
const LOOK: Record<string, { icon: IconName; color: string }> = {
  job_done: { icon: 'checkCircle', color: 'text-ok' },
  job_failed: { icon: 'error', color: 'text-err' },
  job_cancelled: { icon: 'close', color: 'text-muted' },
  limit_exhausted: { icon: 'warning', color: 'text-warn' },
}

export function NotificationsBell() {
  const t = useT()
  const { data, isLoading } = useNotifications(20)
  const markOne = useMarkNotificationRead()
  const markAll = useMarkAllNotificationsRead()

  const unread = data?.unread_count ?? 0
  const items = data?.notifications ?? []

  return (
    <MenuRoot>
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
      <MenuContent className="w-[360px] max-w-[calc(100vw-24px)]">
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

/**
 * Заголовок записи. Служба присылает вид и данные, а не готовый текст (тексты
 * наружу по-английски), поэтому русский текст собирается здесь — по тому же
 * словарю, что и тосты. Неизвестный вид показывается кодом: это честнее
 * пустой строки и сразу видно, что в словарь надо дописать.
 */
const TITLE_KEY: Record<string, string> = {
  job_done: 'notifications.jobDone',
  job_failed: 'notifications.jobFailed',
  job_cancelled: 'notifications.jobCancelled',
  limit_exhausted: 'notifications.limitExhausted',
}

function Row({ item, onRead }: { item: Notification; onRead: () => void }) {
  const t = useT()
  const look = LOOK[item.kind] ?? { icon: 'info' as IconName, color: 'text-muted' }
  const key = TITLE_KEY[item.kind]
  const title = key ? t(key) : item.kind
  return (
    <MenuItem
      className="items-start"
      onSelect={() => {
        if (!item.read_at) onRead()
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
        <span className="block text-xs text-muted">{when(item.created_at)}</span>
      </span>
    </MenuItem>
  )
}

/** Короткая отметка времени. Дата целиком нужна редко, минуты — всегда. */
function when(iso: string): string {
  const at = new Date(iso)
  if (Number.isNaN(at.getTime())) return iso
  return at.toLocaleString('ru-RU', {
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  })
}
