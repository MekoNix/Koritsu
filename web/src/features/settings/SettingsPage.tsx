/**
 * SettingsPage — оболочка настроек: слева список разделов, справа раздел.
 *
 * Раздел — это адрес (`/settings/keys`), а не состояние компонента: настройки
 * тем и ссылкой на нужное место, и кнопка «назад» в браузере обязана работать.
 * Дерево маршрутов — в `routes.tsx`, здесь только рамка и навигация.
 *
 * Ширина содержимого ограничена (`max-w-[760px]`, как в макете
 * `10-auth-settings.html`): строка настройки во всю ширину монитора читается
 * хуже, чем в две трети экрана.
 */
import { NavLink, Outlet } from 'react-router-dom'

import { useT } from '@/i18n'
import { cn } from '@/lib/cn'
import { Icon, type IconName } from '@/ui'

type Section = { to: string; key: string; icon: IconName }

const SECTIONS: readonly Section[] = [
  { to: 'profile', key: 'profile', icon: 'user' },
  { to: 'appearance', key: 'appearance', icon: 'palette' },
  { to: 'templates', key: 'templates', icon: 'file' },
  { to: 'hotkeys', key: 'hotkeys', icon: 'search' },
  { to: 'agent', key: 'agent', icon: 'agent' },
  { to: 'keys', key: 'keys', icon: 'key' },
  { to: 'tokens', key: 'tokens', icon: 'file' },
  { to: 'usage', key: 'usage', icon: 'dashboard' },
  { to: 'security', key: 'security', icon: 'shield' },
]

export function SettingsPage() {
  const t = useT()
  return (
    <section className="flex flex-col gap-s4">
      <header>
        <h1 className="font-display text-xl font-bold tracking-tight text-ink-strong">
          {t('settings.title')}
        </h1>
        <p className="mt-1 text-sm text-muted">{t('settings.subtitle')}</p>
      </header>

      <div className="grid items-start gap-s5 lg:grid-cols-[240px_minmax(0,1fr)]">
        <nav aria-label={t('settings.nav.label')}>
          <ul className="flex flex-col gap-0.5 rounded-md border border-line bg-surface p-1.5 shadow-1 backdrop-blur-theme lg:sticky lg:top-s4">
            {SECTIONS.map((section) => (
              <li key={section.to}>
                <NavLink
                  to={section.to}
                  className={({ isActive }) =>
                    cn(
                      // Полоски у активного пункта нет — правило брифа. Активный
                      // пункт отличается заливкой и весом текста.
                      'flex items-center gap-s2 rounded-sm px-2.5 py-2 text-sm no-underline hover:bg-surface-2',
                      isActive ? 'bg-accent-bg font-semibold text-ink-strong' : 'text-ink',
                    )
                  }
                >
                  <Icon name={section.icon} size={18} className="text-muted" />
                  {t(`settings.nav.${section.key}`)}
                </NavLink>
              </li>
            ))}
          </ul>
        </nav>

        <div className="flex min-w-0 max-w-[760px] flex-col gap-s4">
          <Outlet />
        </div>
      </div>
    </section>
  )
}
