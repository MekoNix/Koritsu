/**
 * ModuleWidgets — карточки перехода в модуль.
 *
 * Список — из `GET /api/modules`, и это единственный источник: служба не
 * отдаёт неготовые модули вовсе, поэтому правило брифа («модули в планах в
 * интерфейсе не отображаются, никаких заглушек „скоро“») держится само,
 * без фильтров на стороне сайта.
 *
 * Модуль, у которого на сайте ещё нет раздела, тоже не показывается: адрес
 * берётся из `app/shell/moduleLinks.ts`, и его отсутствие означает «вести
 * некуда». Ссылка в никуда считается ошибкой (решение владельца).
 */
import { Link } from 'react-router-dom'

import { useModules } from '@/api/hooks'
import { MODULE_LINKS } from '@/app/shell/moduleLinks'
import { useT } from '@/i18n'
import { ErrorState, Icon, Skeleton } from '@/ui'

import { Widget } from './Widget'

export function ModuleWidgets() {
  const t = useT()
  const modules = useModules()

  if (modules.isPending) {
    return (
      <>
        {[0, 1, 2].map((i) => (
          <Widget key={i} className="lg:col-span-4">
            <div className="flex flex-col gap-s2">
              <Skeleton className="h-6 w-6 rounded-sm" />
              <Skeleton className="w-1/2" />
              <Skeleton className="h-2.5 w-2/3" />
            </div>
          </Widget>
        ))}
      </>
    )
  }

  if (modules.isError) {
    return (
      <Widget className="lg:col-span-12">
        <ErrorState error={modules.error} onRetry={() => void modules.refetch()} />
      </Widget>
    )
  }

  return (
    <>
      {(modules.data ?? []).map((module) => {
        const link = MODULE_LINKS[module.id]
        if (!link) return null
        return (
          <Link
            key={module.id}
            to={link.path}
            className="group flex min-w-0 flex-col gap-s2 rounded-md border border-line bg-surface p-s4 shadow-1 transition-colors hover:border-line-strong hover:bg-surface-2 lg:col-span-4"
          >
            <Icon
              name={link.icon}
              size={24}
              style={link.colorVar ? { color: `var(${link.colorVar})` } : undefined}
            />
            <span className="truncate font-display text-md font-semibold text-ink-strong">
              {t(`shell.nav.${module.id}`)}
            </span>
            <span className="text-xs text-muted">{t(`dashboard.modules.hint.${module.id}`)}</span>
          </Link>
        )
      })}
    </>
  )
}
