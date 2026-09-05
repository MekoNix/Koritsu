/**
 * DashboardGrid — сетка ленты с перестановкой клеток.
 *
 * Перетаскивание сделано на встроенном в браузер механизме
 * (`draggable` + события `drag*`), без библиотеки. Довод простой: всё, что
 * нужно ленте, — «взял клетку, отпустил над другой», и это ровно то, что
 * встроенный механизм умеет; библиотека принесла бы сюда свои сенсоры,
 * коллизии и сотню килобайт ради того же самого.
 *
 * **Тянется клетка только за ручку.** `draggable` на всей плитке означал бы,
 * что текст в ней нельзя выделить, а кнопку внутри — нажать протяжкой:
 * браузер начал бы перетаскивание вместо выделения. Поэтому признак
 * выставляется на время — пока указатель держит ручку, — и снимается по концу.
 *
 * **Клавиатура умеет то же самое.** Ручка — обычная кнопка, и стрелки на ней
 * двигают клетку на шаг. Раскладка, которую нельзя поменять без мыши, — это
 * раскладка, которой нет у половины людей.
 *
 * Порядок и ширины живут в `order.ts`; сюда они приезжают готовыми, а сетка
 * знает только, как их показать.
 */
import { useCallback, useState, type ReactNode } from 'react'

import { useT } from '@/i18n'
import { cn } from '@/lib/cn'
import { Icon } from '@/ui'

import { ШИРИНА, переставить, прочитать, записать, type CellId } from './order'

export type Cell = { id: CellId; node: ReactNode }

export function DashboardGrid({ cells }: { cells: readonly Cell[] }) {
  const t = useT()
  const [порядок, setПорядок] = useState<CellId[]>(прочитать)
  // Какую клетку сейчас тянут и какой разрешено начать тянуть. Первое рисует
  // саму клетку полупрозрачной, второе включает `draggable` — см. шапку.
  const [тянут, setТянут] = useState<CellId | null>(null)
  const [за_ручку, setЗаРучку] = useState<CellId | null>(null)

  const по_порядку = порядок.filter((id) => cells.some((c) => c.id === id))

  const переложить = useCallback((откуда: number, куда: number) => {
    setПорядок((был) => {
      const стал = переставить(был, откуда, куда)
      записать(стал)
      return стал
    })
  }, [])

  return (
    <div className="grid grid-cols-1 gap-s3 sm:grid-cols-6 lg:grid-cols-12">
      {по_порядку.map((id, место) => {
        const клетка = cells.find((c) => c.id === id)
        if (!клетка) return null
        const подпись = t(`dashboard.cell.${id}`)
        return (
          <div
            key={id}
            className={cn('group/cell relative min-w-0', ШИРИНА[id], тянут === id && 'opacity-40')}
            draggable={за_ручку === id}
            onDragStart={(event) => {
              setТянут(id)
              event.dataTransfer.effectAllowed = 'move'
              // Данные в переносе обязательны: без них Firefox перетаскивание
              // не начинает вовсе. Кладём имя клетки — то же, что и в порядке.
              event.dataTransfer.setData('text/plain', id)
            }}
            onDragEnd={() => {
              setТянут(null)
              setЗаРучку(null)
            }}
            onDragOver={(event) => {
              if (!тянут || тянут === id) return
              // Без этого браузер считает место запретным и не даст отпустить.
              event.preventDefault()
              event.dataTransfer.dropEffect = 'move'
            }}
            onDrop={(event) => {
              event.preventDefault()
              if (!тянут || тянут === id) return
              переложить(порядок.indexOf(тянут), порядок.indexOf(id))
              setТянут(null)
              setЗаРучку(null)
            }}
          >
            <button
              type="button"
              // Имя клетки в разметке: по нему порядок ленты читается снаружи
              // (сквозные проверки) без разбора русских подписей.
              data-cell={id}
              // Ручка не мозолит глаза: видна на наведении и всегда — тому,
              // кто ходит с клавиатуры (фокус).
              className={cn(
                'absolute right-1.5 top-1.5 z-10 grid h-6 w-6 place-items-center rounded-sm text-muted',
                'cursor-grab opacity-0 transition-opacity hover:bg-surface-2 hover:text-ink',
                'focus-visible:opacity-100 group-hover/cell:opacity-100',
              )}
              aria-label={t('dashboard.reorder.handle', { name: подпись })}
              title={t('dashboard.reorder.hint')}
              onPointerDown={() => setЗаРучку(id)}
              onPointerUp={() => setЗаРучку(null)}
              onBlur={() => setЗаРучку(null)}
              onKeyDown={(event) => {
                const шаг =
                  event.key === 'ArrowLeft' || event.key === 'ArrowUp'
                    ? -1
                    : event.key === 'ArrowRight' || event.key === 'ArrowDown'
                      ? 1
                      : 0
                if (!шаг) return
                event.preventDefault()
                переложить(место, место + шаг)
              }}
            >
              <Icon name="grip" size={14} />
            </button>
            {клетка.node}
          </div>
        )
      })}
    </div>
  )
}
