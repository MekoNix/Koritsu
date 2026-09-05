/**
 * DashboardPage — лента виджетов.
 *
 * **Лента, а не рабочий стол модуля** (правило интерфейса): клетки разнородные
 * по размеру — утилита и часы маленькой плиткой, статистика широкой.
 *
 * **Клетки переставляются рукой**, и порядок помнится в браузере: раскладка
 * ленты — свойство экрана, за которым человек сидит, а не свойство аккаунта
 * (`order.ts`). Меню «добавить виджет» при этом нет: лента показывает то, что
 * у человека есть, и прятать половину её было бы настройкой ради настройки.
 *
 * Чего на дашборде нет и не будет: дедлайнов, семестров, учебных групп —
 * приложением пользуется не только студент, и таких данных у службы нет.
 * Уведомления — виджет с пятью последними и колокольчик в шапке; отдельной
 * страницы у них нет.
 *
 * Сетка — двенадцать колонок на широком экране, шесть на среднем, одна на
 * узком; ширины клеток лежат таблицей рядом с порядком (`order.ts`), а не
 * внутри самих клеток: переставленная клетка обязана унести ширину с собой.
 */
import { useMe } from '@/api/hooks'
import { useT } from '@/i18n'
import { maskEmail } from '@/lib/maskEmail'
import { SkeletonLines } from '@/ui'

import { ClockWidget } from './ClockWidget'
import { DashboardGrid, type Cell } from './DashboardGrid'
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

/**
 * Клетки ленты. Имена — те же, что в `order.ts`: там лежит порядок по
 * умолчанию и ширина каждой, здесь — что в ней нарисовано.
 */
const КЛЕТКИ: readonly Cell[] = [
  { id: 'clock', node: <ClockWidget /> },
  { id: 'wordToPdf', node: <WordToPdfWidget /> },
  { id: 'usage', node: <UsageWidget /> },
  { id: 'modules', node: <ModuleWidgets /> },
  { id: 'stats', node: <StatsWidget /> },
  { id: 'works', node: <MyWorksWidget /> },
  { id: 'notifications', node: <NotificationsWidget /> },
]

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

      <DashboardGrid cells={КЛЕТКИ} />
    </div>
  )
}
