/**
 * UsersTab — таблица людей: поиск, отбор по плану, сортировка, страницы, CSV.
 *
 * Всё это считает сайт (`filter.ts`, `table.ts`): служба отдаёт список одним
 * куском и ни поиска, ни сортировки, ни страниц не умеет. Это честно сказано
 * подписью под таблицей — иначе на большой базе человек решит, что видит всех,
 * а увидит первую тысячу.
 *
 * Порядок действий над списком закреплён: сначала отбор (поиск и план), потом
 * сортировка, потом страница. Иначе страница 2 отсортированного списка и
 * страница 2 отобранного показывали бы разное при одинаковом виде экрана.
 *
 * Расход в столбце — за календарный месяц: это то самое число, что называет
 * человеку `GET /api/usage`. Не за период «Обзора»: два разных окна в одном
 * экране — это два числа, которые обязаны совпасть и не совпадут.
 *
 * Строка кликабельна целиком и является кнопкой: карточка открывается и с
 * клавиатуры, а не только мышью.
 *
 * Ник — отдельным столбцом рядом с почтой, а не вместо неё: администратор
 * знает людей по нику, но пишет им и заводит их по почте, и в админке нужны
 * оба.
 */
import { useMemo, useState } from 'react'

import { useT } from '@/i18n'
import {
  Avatar,
  Button,
  Chip,
  EmptyState,
  ErrorState,
  Icon,
  Input,
  Progress,
  Select,
  SkeletonLines,
} from '@/ui'
import { formatBytes, formatDate, formatUnits } from '@/features/settings/format'

import { useAdminUsers } from './api'
import { CreateUserDialog } from './CreateUserDialog'
import { countAdmins, filterUsers, pageCount, pageOf } from './filter'
import { CsvButton, SortHeader } from './parts'
import {
  filterByPlan,
  filterByStatus,
  nextSort,
  planCounts,
  sortRows,
  statusWeight,
  userStatus,
  type SortState,
} from './table'
import { UserDialog } from './UserDialog'
import type { AdminUser } from './types'

const TD = 'border-b border-line px-3 py-2 align-middle'

/** Столбцы, по которым сортируют. Ключ = имя ключа перевода. */
type Col = 'user' | 'nick' | 'plan' | 'spent' | 'storage' | 'status' | 'created'

/** Чем меряется столбец при сортировке. Одно место, чтобы шапка и порядок
 *  строк не разошлись. */
const ПО: Record<Col, (user: AdminUser) => string | number> = {
  user: (u) => u.email,
  // Ник сортируется без учёта регистра: `Ivan` между `ivan` и `иван` — это
  // алфавит таблицы ASCII, а не алфавит человека.
  nick: (u) => (u.nickname ?? '').toLocaleLowerCase('ru'),
  plan: (u) => u.plan,
  spent: (u) => u.spent_units,
  storage: (u) => u.bytes_used,
  // Состояние — не строка, а очерёдность беды: удалённые, потом
  // заблокированные, потом неподтверждённые. Сортировка по слову дала бы
  // алфавит, в котором «активен» стоит первым.
  status: statusWeight,
  created: (u) => u.created_at ?? '',
}

/** Цвет метки состояния. Само состояние считает `table.userStatus` — там же,
 *  где отбор по нему, чтобы столбец и фильтр не разошлись. */
const ТОН = {
  deleted: 'err',
  blocked: 'err',
  unconfirmed: 'warn',
  active: 'ok',
} as const

/** Что предлагается в отборе по состоянию. Пустое значение — «все». */
const СОСТОЯНИЯ = ['active', 'blocked', 'unconfirmed', 'deleted'] as const

export function UsersTab() {
  const t = useT()
  const users = useAdminUsers()
  const [query, setQuery] = useState('')
  const [plan, setPlan] = useState('')
  const [status, setStatus] = useState('')
  const [sort, setSort] = useState<SortState<Col>>(null)
  const [page, setPage] = useState(1)
  const [opened, setOpened] = useState<AdminUser | null>(null)
  const [creating, setCreating] = useState(false)

  const all = useMemo(() => users.data ?? [], [users.data])
  const планы = useMemo(() => planCounts(all), [all])
  const found = useMemo(
    () => sortOf(filterByStatus(filterByPlan(filterUsers(all, query), plan), status), sort),
    [all, query, plan, status, sort],
  )
  const pages = pageCount(found.length)
  const current = Math.min(page, pages)
  const rows = useMemo(() => pageOf(found, current), [found, current])

  if (users.isLoading) return <SkeletonLines count={8} />
  if (users.error) return <ErrorState error={users.error} onRetry={() => void users.refetch()} />

  const сортировать = (col: Col) => {
    setSort((было) => nextSort(было, col))
    setPage(1)
  }

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
        <Select
          aria-label={t('admin.users.planFilter')}
          value={plan}
          onChange={(e) => {
            setPlan(e.target.value)
            setPage(1)
          }}
          className="w-[200px]"
        >
          <option value="">{t('admin.users.planAll')}</option>
          {планы.map((строка) => (
            <option key={строка.plan} value={строка.plan}>
              {строка.plan} ({строка.count})
            </option>
          ))}
        </Select>
        <Select
          aria-label={t('admin.users.statusFilter')}
          value={status}
          onChange={(e) => {
            setStatus(e.target.value)
            setPage(1)
          }}
          className="w-[200px]"
        >
          <option value="">{t('admin.users.statusAll')}</option>
          {СОСТОЯНИЯ.map((имя) => (
            <option key={имя} value={имя}>
              {t(`admin.users.status.${имя}`)}
            </option>
          ))}
        </Select>
        <span className="text-xs text-muted">
          {query || plan || status
            ? t('admin.users.found', { found: found.length, total: all.length })
            : t('admin.users.total', { total: all.length, admins: countAdmins(all) })}
        </span>
        <span className="grow" />
        <Button variant="secondary" size="sm" onClick={() => setCreating(true)}>
          <Icon name="plus" size={16} />
          {t('admin.users.create')}
        </Button>
        <CsvButton
          name="koritsu-users.csv"
          disabled={found.length === 0}
          headers={[
            t('admin.users.col.nick'),
            t('admin.users.col.user'),
            'id',
            t('admin.users.col.plan'),
            t('admin.users.role.admin'),
            t('admin.users.col.spent'),
            t('admin.users.col.storage'),
            t('admin.users.col.status'),
            t('admin.users.col.created'),
          ]}
          // Выгружается отобранное и отсортированное целиком, а не страница:
          // человек, нажавший «CSV» после поиска, ждёт найденное, а не двадцать
          // строк из него.
          rows={() =>
            found.map((user) => [
              user.nickname,
              user.email,
              user.id,
              user.plan,
              user.is_admin ? 1 : 0,
              user.spent_units,
              user.bytes_used,
              t(`admin.users.status.${userStatus(user)}`),
              user.created_at ?? '',
            ])
          }
        />
      </div>

      {found.length === 0 ? (
        <EmptyState icon="users" title={t('admin.users.empty')} text={t('admin.users.emptyHint')} />
      ) : (
        <div className="overflow-x-auto rounded-md border border-line bg-surface">
          <table className="w-full border-separate border-spacing-0 text-sm">
            <thead>
              <tr>
                <SortHeader col="user" state={sort} onSort={сортировать}>
                  {t('admin.users.col.user')}
                </SortHeader>
                <SortHeader col="nick" state={sort} onSort={сортировать}>
                  {t('admin.users.col.nick')}
                </SortHeader>
                <SortHeader col="plan" state={sort} onSort={сортировать}>
                  {t('admin.users.col.plan')}
                </SortHeader>
                <SortHeader col="spent" state={sort} onSort={сортировать} className="text-right">
                  {t('admin.users.col.spent')}
                </SortHeader>
                <SortHeader col="storage" state={sort} onSort={сортировать}>
                  {t('admin.users.col.storage')}
                </SortHeader>
                <SortHeader col="status" state={sort} onSort={сортировать}>
                  {t('admin.users.col.status')}
                </SortHeader>
                <SortHeader col="created" state={sort} onSort={сортировать}>
                  {t('admin.users.col.created')}
                </SortHeader>
              </tr>
            </thead>
            <tbody>
              {rows.map((user) => {
                const состояние = userStatus(user)
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
                    <td className={`${TD} font-medium text-ink-strong`}>{user.nickname}</td>
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
                      <Chip tone={ТОН[состояние]}>{t(`admin.users.status.${состояние}`)}</Chip>
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

      <CreateUserDialog
        open={creating}
        onClose={() => {
          setCreating(false)
          void users.refetch()
        }}
      />
    </div>
  )
}

/** Порядок строк: выбранный столбец или тот, в котором отдала служба. */
function sortOf(users: AdminUser[], sort: SortState<Col>): AdminUser[] {
  return sort ? sortRows(users, ПО[sort.col], sort.dir) : users
}
