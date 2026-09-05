/**
 * DashboardPage — лента виджетов.
 *
 * **Лента, а не рабочий стол модуля** (бриф): виджеты разнородные по размеру —
 * утилита и часы маленькой плиткой, статистика широкой, — и порядок у них
 * фиксированный. Перетаскивание и режим правки сетки — решение владельца
 * «потом», поэтому здесь нет ни ручек, ни меню добавления виджета: пустой
 * механизм настройки хуже его отсутствия.
 *
 * Чего на дашборде нет и не будет: дедлайнов, семестров, учебных групп —
 * приложением пользуется не только студент, и таких данных у службы нет
 * (правка 2 макетов). Список уведомлений — ночь 2, пока он только в
 * колокольчике.
 *
 * Сетка — двенадцать колонок на широком экране, шесть на среднем, одна на
 * узком; своё место каждый виджет объявляет сам классом `lg:col-span-*`, чтобы
 * порядок ленты читался здесь одним списком, а не таблицей раскладки.
 */
import { useMe } from '@/api/hooks'
import { useT } from '@/i18n'

import { ClockWidget } from './ClockWidget'
import { ModuleWidgets } from './ModuleWidgets'
import { MyWorksWidget } from './MyWorksWidget'
import { StatsWidget } from './StatsWidget'
import { UsageWidget } from './UsageWidget'
import { WordToPdfWidget } from './WordToPdfWidget'

/** Приветствие по времени суток. Ключи — `dashboard.greeting.*`. */
function timeOfDay(hour: number): 'night' | 'morning' | 'day' | 'evening' {
  if (hour < 5) return 'night'
  if (hour < 12) return 'morning'
  if (hour < 18) return 'day'
  return 'evening'
}

export function DashboardPage() {
  const t = useT()
  const me = useMe()
  const now = new Date()

  return (
    <div className="flex flex-col gap-s4">
      <header className="flex flex-wrap items-end justify-between gap-s3">
        <div className="min-w-0">
          <p className="text-xs uppercase tracking-wider text-muted">
            {now.toLocaleDateString('ru-RU', { weekday: 'long', day: 'numeric', month: 'long' })}
          </p>
          <h1 className="font-display text-xl font-bold tracking-tight text-ink-strong">
            {t(`dashboard.greeting.${timeOfDay(now.getHours())}`)}
          </h1>
          {me.data && <p className="truncate text-sm text-muted">{me.data.email}</p>}
        </div>
      </header>

      <div className="grid grid-cols-1 gap-s3 sm:grid-cols-6 lg:grid-cols-12">
        <ClockWidget />
        <WordToPdfWidget />
        <UsageWidget />
        <ModuleWidgets />
        <StatsWidget />
        <MyWorksWidget />
      </div>
    </div>
  )
}
