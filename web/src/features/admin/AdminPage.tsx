/**
 * AdminPage — оболочка админки: заголовок и вкладки.
 *
 * В сайдбаре пункта нет ни у кого: тот же SPA по `/admin`, виден только с
 * `is_admin`, плюс белый список IP на Caddy. Поэтому попасть сюда можно только
 * по прямому адресу, а право проверяет `RequireAdmin` в `routes.tsx` — и, что
 * важнее, сама служба: весь `/api/admin` закрыт зависимостью `require_admin`.
 *
 * Вкладок пять, и первая — «Обзор» с графиками: администратор, открывший
 * админку, первым делом спрашивает «что происходит», а не «покажи всех по
 * алфавиту». Список людей после этого никуда не делся — он второй.
 */
import { NavLink, Outlet } from 'react-router-dom'

import { useT } from '@/i18n'
import { cn } from '@/lib/cn'
import { Icon, type IconName } from '@/ui'

type Tab = { to: string; key: string; icon: IconName }

const TABS: readonly Tab[] = [
  { to: 'overview', key: 'overview', icon: 'chart' },
  { to: 'users', key: 'users', icon: 'users' },
  { to: 'plans', key: 'plans', icon: 'wallet' },
  { to: 'queue', key: 'queue', icon: 'queue' },
  { to: 'security', key: 'security', icon: 'shield' },
]

export function AdminPage() {
  const t = useT()
  return (
    <section className="flex flex-col gap-s4">
      <header>
        <h1 className="font-display text-xl font-bold tracking-tight text-ink-strong">
          {t('admin.title')}
        </h1>
        <p className="mt-1 max-w-[80ch] text-sm text-muted">{t('admin.subtitle')}</p>
      </header>

      <nav className="flex gap-s1 border-b border-line" aria-label={t('admin.title')}>
        {TABS.map((tab) => (
          <NavLink
            key={tab.to}
            to={tab.to}
            className={({ isActive }) =>
              cn(
                '-mb-px inline-flex items-center gap-1.5 border-b-2 px-3.5 py-2.5 text-sm font-medium no-underline',
                isActive
                  ? 'border-accent text-ink-strong'
                  : 'border-transparent text-muted hover:text-ink',
              )
            }
          >
            <Icon name={tab.icon} size={16} />
            {t(`admin.tab.${tab.key}`)}
          </NavLink>
        ))}
      </nav>

      <Outlet />
    </section>
  )
}
