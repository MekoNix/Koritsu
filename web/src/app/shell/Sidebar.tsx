/**
 * Sidebar — боковое меню.
 *
 * Три правила брифа, которые здесь закон, а не вкус:
 *
 * 1. **Никакой цветной полоски у активного пункта.** Активность показывается
 *    фоном (`--accent-bg`) и насыщенностью текста — и больше ничем.
 * 2. **Сворачивается по кнопке, не по наведению.** Кнопка стоит наверху, у
 *    логотипа (как в макетах). Состояние помнится в `localStorage`: меню,
 *    разворачивающееся само при каждой перезагрузке, — это то же раскрытие по
 *    наведению, только медленнее.
 * 3. **Неготовые модули не показываются вовсе.** Список приходит из
 *    `GET /api/modules`, где их нет; фильтра здесь нет намеренно — второй
 *    фильтр означал бы второе место, где принимается это решение.
 *
 * Пункты собираются из трёх кусков: постоянные сверху (Дашборд, Проекты),
 * модули из службы, постоянные снизу (Настройки). Админки в меню нет ни у
 * кого. Агента в меню нет тоже, и это не упущение: он не страница, а панель
 * поверх текущего экрана — открывается кнопкой в шапке и сочетанием клавиш,
 * а пункт меню обещал бы место, куда можно уйти.
 *
 * Наверху — только название, и оно же ссылка на дашборд.
 */
import { Link, NavLink } from 'react-router-dom'

import { useModules } from '@/api/hooks'
import { useT } from '@/i18n'
import { cn } from '@/lib/cn'
import { Button, Icon, Skeleton, type IconName } from '@/ui'

import { WorkspaceSwitcher } from '@/features/workspace/WorkspaceSwitcher'

import { MODULE_LINKS } from './moduleLinks'

type Item = {
  key: string
  to: string
  icon: IconName
  label: string
  colorVar?: string
  /** `/` совпадает со всем — точное совпадение нужно только дашборду. */
  end?: boolean
}

export type SidebarProps = {
  collapsed: boolean
  onToggle: () => void
}

export function Sidebar({ collapsed, onToggle }: SidebarProps) {
  const t = useT()
  const modules = useModules()

  const fixedTop: Item[] = [
    { key: 'dashboard', to: '/', icon: 'dashboard', label: t('shell.nav.dashboard'), end: true },
    { key: 'projects', to: '/projects', icon: 'folder', label: t('shell.nav.projects') },
  ]

  const moduleItems: Item[] = (modules.data ?? []).flatMap((m) => {
    const link = MODULE_LINKS[m.id]
    if (!link) return [] // модуль, которому на сайте ещё нет страницы
    return [
      {
        key: m.id,
        to: link.path,
        icon: link.icon,
        // Название по ключу перевода; служба отдаёт английское `title`, и оно
        // остаётся запасным вариантом для модуля, которого ещё нет в словаре.
        label: t(`shell.nav.${m.id}`) === `shell.nav.${m.id}` ? m.title : t(`shell.nav.${m.id}`),
        ...(link.colorVar ? { colorVar: link.colorVar } : {}),
      },
    ]
  })

  const fixedBottom: Item[] = [
    { key: 'settings', to: '/settings', icon: 'settings', label: t('shell.nav.settings') },
  ]

  return (
    <aside
      className={cn(
        'sticky top-0 flex h-screen flex-col gap-s1 overflow-hidden border-r border-line bg-surface p-s3',
        'transition-[width] duration-200',
        collapsed ? 'w-sidebar-collapsed items-center px-2' : 'w-sidebar',
      )}
    >
      <div className={cn('flex items-center gap-s1', collapsed && 'flex-col gap-s2')}>
        {/* Название — ссылка на дашборд: это первое, за что хватается рука,
            когда надо вернуться в начало. Значка рядом нет — квадрат с буквой
            ничего не сообщал, а место занимал. */}
        <Link
          to="/"
          className={cn(
            'flex h-[calc(var(--topbar-h)-var(--space-3))] items-center rounded-sm p-s2 font-display text-lg font-bold tracking-tight text-ink-strong no-underline',
            'hover:bg-surface-2 hover:text-ink-strong hover:no-underline',
            collapsed ? 'flex-none px-2' : 'min-w-0 flex-1',
          )}
          aria-label={t('shell.brand')}
        >
          {/* Свёрнутое меню оставляет одну букву — как и пунктам оставляет
              одни иконки. */}
          <span className="truncate">
            {collapsed ? t('shell.brand').slice(0, 1) : t('shell.brand')}
          </span>
        </Link>
        <Button
          variant="ghost"
          size="sm"
          iconOnly
          onClick={onToggle}
          aria-label={collapsed ? t('shell.sidebar.expand') : t('shell.sidebar.collapse')}
          aria-expanded={!collapsed}
          className="text-muted"
        >
          <Icon name={collapsed ? 'panelOpen' : 'panelClose'} size={18} />
        </Button>
      </div>

      {/* Рабочее пространство — рамка, в которой показаны все работы; стоит
          над пунктами меню и в их число не входит (см. WorkspaceSwitcher). */}
      <WorkspaceSwitcher collapsed={collapsed} />

      <nav className="flex flex-col gap-s1" aria-label={t('shell.sidebar.modules')}>
        {fixedTop.map((item) => (
          <NavItem key={item.key} item={item} collapsed={collapsed} />
        ))}

        {!collapsed && (
          <div className="px-s2 pb-s1 pt-s3 text-xs uppercase tracking-wider text-muted">
            {t('shell.sidebar.modules')}
          </div>
        )}
        {modules.isLoading &&
          Array.from({ length: 3 }, (_, i) => (
            <Skeleton key={i} className={cn('my-1 h-6', collapsed ? 'w-9' : 'w-full')} />
          ))}
        {moduleItems.map((item) => (
          <NavItem key={item.key} item={item} collapsed={collapsed} />
        ))}
      </nav>

      <div className="mt-auto w-full border-t border-line pt-s2">
        {fixedBottom.map((item) => (
          <NavItem key={item.key} item={item} collapsed={collapsed} />
        ))}
      </div>
    </aside>
  )
}

function NavItem({ item, collapsed }: { item: Item; collapsed: boolean }) {
  return (
    <NavLink
      to={item.to}
      end={item.end}
      title={collapsed ? item.label : undefined}
      className={({ isActive }) =>
        cn(
          'flex items-center gap-s3 whitespace-nowrap rounded-sm px-2.5 py-2 text-sm font-medium no-underline',
          'hover:bg-surface-2 hover:text-ink hover:no-underline',
          // Активность — фоном и насыщенностью текста. Полоски слева нет и не
          // будет: это прямой запрет брифа.
          isActive ? 'bg-accent-bg font-semibold text-ink-strong' : 'text-muted',
          collapsed && 'w-11 justify-center px-0 py-2.5',
        )
      }
    >
      <Icon
        name={item.icon}
        size={18}
        style={item.colorVar ? { color: `var(${item.colorVar})` } : undefined}
      />
      {!collapsed && <span className="truncate">{item.label}</span>}
    </NavLink>
  )
}
