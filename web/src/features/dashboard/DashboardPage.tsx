/**
 * DashboardPage — лента виджетов.
 *
 * **Лента, а не рабочий стол модуля** (правило интерфейса): виджеты разнородные
 * по размеру — утилита и часы маленькой плиткой, статистика широкой, — и
 * порядок у них фиксированный. Перетаскивание и режим правки сетки — на потом,
 * поэтому здесь нет ни ручек, ни меню добавления виджета: пустой механизм
 * настройки хуже его отсутствия.
 *
 * Чего на дашборде нет и не будет: дедлайнов, семестров, учебных групп —
 * приложением пользуется не только студент, и таких данных у службы нет.
 * Уведомления — виджет с пятью последними и колокольчик в шапке; отдельной
 * страницы у них нет.
 *
 * Сетка — двенадцать колонок на широком экране, шесть на среднем, одна на
 * узком; своё место каждый виджет объявляет сам классом `lg:col-span-*`, чтобы
 * порядок ленты читался здесь одним списком, а не таблицей раскладки.
 */
import { useMe } from '@/api/hooks'
import { useT } from '@/i18n'
import { maskEmail } from '@/lib/maskEmail'
import { SkeletonLines } from '@/ui'

import { ClockWidget } from './ClockWidget'
import { ModuleWidgets } from './ModuleWidgets'
import { MyWorksWidget } from './MyWorksWidget'
import { NotificationsWidget } from './NotificationsWidget'
import { StatsWidget } from './StatsWidget'
import { UsageWidget } from './UsageWidget'
import { WordToPdfWidget } from './WordToPdfWidget'

/**
 * Приветствие по времени суток. Ключи — `dashboard.greeting.*`, в каждом есть
 * `{name}`: зовут человека ником.
 */
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
          {/* Приветствие ждёт ника: «Добрый вечер, {name}» без имени читается
              как сломанный экран, а `me` — обычный запрос и приходит не сразу. */}
          {me.data && (
            <>
              <h1 className="font-display text-xl font-bold tracking-tight text-ink-strong">
                {t(`dashboard.greeting.${timeOfDay(now.getHours())}`, {
                  name: me.data.nickname,
                })}
              </h1>
              {/* Почта — частично скрытой: экран открывают при других людях
                  (помощник `lib/maskEmail`). */}
              <p className="truncate text-sm text-muted">{maskEmail(me.data.email)}</p>
            </>
          )}
          {!me.data && <SkeletonLines count={2} />}
        </div>
      </header>

      <div className="grid grid-cols-1 gap-s3 sm:grid-cols-6 lg:grid-cols-12">
        <ClockWidget />
        <WordToPdfWidget />
        <UsageWidget />
        <ModuleWidgets />
        <StatsWidget />
        <MyWorksWidget />
        <NotificationsWidget />
      </div>
    </div>
  )
}
