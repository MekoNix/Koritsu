/**
 * UsersTab — таблица людей с поиском и страницами.
 *
 * Поиск и страницы считает сайт (`filter.ts`): служба отдаёт список одним
 * куском и ни того, ни другого не умеет. Это честно сказано подписью под
 * таблицей — иначе на большой базе человек решит, что видит всех, а увидит
 * первую тысячу.
 *
 * Строка кликабельна целиком и является кнопкой: карточка открывается и с
 * клавиатуры, а не только мышью.
 */
import { useMemo, useState } from 'react'

import { useT } from '@/i18n'
import { Avatar, Chip, EmptyState, ErrorState, Icon, Input, Progress, SkeletonLines } from '@/ui'
import { formatBytes, formatDate, formatUnits } from '@/features/settings/format'

import { useAdminUsers } from './api'
import { countAdmins, filterUsers, pageCount, pageOf } from './filter'
import { UserDialog } from './UserDialog'
import type { AdminUser } from './types'

const TH =
  'sticky top-0 z-[1] whitespace-nowrap border-b border-line bg-surface px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-muted'
const TD = 'border-b border-line px-3 py-2 align-middle'

function statusOf(user: AdminUser) {
  if (user.deleted_at) return { tone: 'err', key: 'deleted' } as const
  if (!user.email_confirmed) return { tone: 'warn', key: 'unconfirmed' } as const
  return { tone: 'ok', key: 'active' } as const
}

export function UsersTab() {
  const t = useT()
  const users = useAdminUsers()
  const [query, setQuery] = useState('')
  const [page, setPage] = useState(1)
  const [opened, setOpened] = useState<AdminUser | null>(null)

  const all = useMemo(() => users.data ?? [], [users.data])
  const found = useMemo(() => filterUsers(all, query), [all, query])
  const pages = pageCount(found.length)
  const current = Math.min(page, pages)
  const rows = useMemo(() => pageOf(found, current), [found, current])

  if (users.isLoading) return <SkeletonLines count={8} />
  if (users.error) return <ErrorState error={users.error} onRetry={() => void users.refetch()} />

  return (
    <div className="flex flex-col gap-s3">
      <div className="flex flex-wrap items-center gap-s3">
        <Input
          value={query}
          onChange={(e) => {
            setQuery(e.target.value)
            setPage(1)
          }}
          placeholder={t('admin.users.search')}
          aria-label={t('admin.users.search')}
          icon={<Icon name="search" size={16} />}
          wrapperClassName="w-[320px] max-w-full"
        />
        <span className="text-xs text-muted">
          {query
            ? t('admin.users.found', { found: found.length, total: all.length })
            : t('admin.users.total', { total: all.length, admins: countAdmins(all) })}
        </span>
      </div>

      {found.length === 0 ? (
        <EmptyState icon="users" title={t('admin.users.empty')} text={t('admin.users.emptyHint')} />
      ) : (
        <div className="overflow-x-auto rounded-md border border-line bg-surface">
          <table className="w-full border-separate border-spacing-0 text-sm">
            <thead>
              <tr>
                <th className={TH}>{t('admin.users.col.user')}</th>
                <th className={TH}>{t('admin.users.col.plan')}</th>
                <th className={`${TH} text-right`}>{t('admin.users.col.spent')}</th>
                <th className={TH}>{t('admin.users.col.storage')}</th>
                <th className={TH}>{t('admin.users.col.status')}</th>
                <th className={TH}>{t('admin.users.col.created')}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((user) => {
                const status = statusOf(user)
                const share = user.quota_bytes > 0 ? user.bytes_used / user.quota_bytes : 0
                return (
                  <tr
                    key={user.id}
                    tabIndex={0}
                    role="button"
                    onClick={() => setOpened(user)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault()
                        setOpened(user)
                      }
                    }}
                    className="cursor-pointer hover:bg-surface-2 focus-visible:bg-surface-2"
                  >
                    <td className={TD}>
                      <span className="flex items-center gap-s2">
                        <Avatar id={user.id} size={28} />
                        <span className="min-w-0">
                          <span className="block break-all font-medium text-ink-strong">
                            {user.email}
                          </span>
                          <span className="block font-mono text-xs text-muted">
                            {user.id.slice(0, 8)}…
                          </span>
                        </span>
                      </span>
                    </td>
                    <td className={TD}>
                      <span className="flex flex-wrap items-center gap-1.5">
                        <span className="text-ink">{user.plan}</span>
                        {user.is_admin && <Chip tone="info">{t('admin.users.role.admin')}</Chip>}
                      </span>
                    </td>
                    <td className={`${TD} text-right font-mono text-ink-strong`}>
                      {formatUnits(user.spent_units)}
                    </td>
                    <td className={TD}>
                      <span className="flex w-[160px] items-center gap-s2">
                        <Progress
                          value={share}
                          tone={share >= 1 ? 'err' : share >= 0.85 ? 'warn' : 'accent'}
                          className="w-[70px]"
                          label={t('admin.users.col.storage')}
                        />
                        <span className="whitespace-nowrap font-mono text-xs text-muted">
                          {formatBytes(user.bytes_used)}
                        </span>
                      </span>
                    </td>
                    <td className={TD}>
                      <Chip tone={status.tone}>{t(`admin.users.status.${status.key}`)}</Chip>
                    </td>
                    <td className={`${TD} whitespace-nowrap text-muted`}>
                      {formatDate(user.created_at)}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      <div className="flex flex-wrap items-center justify-between gap-s3">
        <span className="text-xs text-muted">{t('admin.users.limitHint')}</span>
        {pages > 1 && (
          <div className="flex items-center gap-s2">
            <button
              type="button"
              aria-label={t('admin.users.prev')}
              disabled={current <= 1}
              onClick={() => setPage(current - 1)}
              className="grid h-[30px] w-[30px] place-items-center rounded-sm text-muted hover:bg-surface-2 hover:text-ink disabled:opacity-40"
            >
              <Icon name="chevronLeft" size={16} />
            </button>
            <span className="text-xs text-muted">
              {t('admin.users.page', { page: current, pages })}
            </span>
            <button
              type="button"
              aria-label={t('admin.users.next')}
              disabled={current >= pages}
              onClick={() => setPage(current + 1)}
              className="grid h-[30px] w-[30px] place-items-center rounded-sm text-muted hover:bg-surface-2 hover:text-ink disabled:opacity-40"
            >
              <Icon name="chevronRight" size={16} />
            </button>
          </div>
        )}
      </div>

      <UserDialog
        user={opened}
        onClose={() => {
          setOpened(null)
          void users.refetch()
        }}
      />
    </div>
  )
}
