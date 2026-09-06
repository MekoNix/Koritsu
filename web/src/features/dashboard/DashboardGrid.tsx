/**
 * DashboardGrid — сетка ленты и режим её правки.
 *
 * **Режим, а не постоянные ручки.** Раньше клетку можно было тянуть в любой
 * момент, а узнать об этом было неоткуда: ручка появлялась на наведении, и
 * человек, который не водил мышью по углу плитки, до конца считал ленту
 * неподвижной. Поэтому есть явная кнопка «Править»: вне режима лента — это
 * просто лента, в режиме у каждой клетки видимая ручка и «Убрать», а внизу
 * список убранных с «Вернуть». Правка кончается кнопкой «Готово».
 *
 * **Убрать можно всё.** Обязательного минимума у ленты нет: пустой дашборд —
 * законный ответ человека на вопрос «что показывать», и вместо клеток он
 * видит строчку с приглашением вернуть их. Запрет «хотя бы одна клетка»
 * означал бы, что мы знаем лучше, зачем человек открывает эту страницу.
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
 * Порядок, ширины и память о том и другом живут в `order.ts`; сюда они
 * приезжают готовыми, а сетка знает только, как их показать.
 */
import { useCallback, useState, type ReactNode } from 'react'

import { useT } from '@/i18n'
import { cn } from '@/lib/cn'
import { Button, Icon } from '@/ui'

import {
  ШИРИНА,
  записать,
  записать_скрытые,
  переставить,
  прочитать,
  прочитать_скрытые,
  type CellId,
} from './order'

export type Cell = { id: CellId; node: ReactNode }

export function DashboardGrid({ cells }: { cells: readonly Cell[] }) {
  const t = useT()
  const [порядок, setПорядок] = useState<CellId[]>(прочитать)
  const [скрытые, setСкрытые] = useState<CellId[]>(прочитать_скрытые)
  const [правим, setПравим] = useState(false)
  // Какую клетку сейчас тянут и какой разрешено начать тянуть. Первое рисует
  // саму клетку полупрозрачной, второе включает `draggable` — см. шапку.
  const [тянут, setТянут] = useState<CellId | null>(null)
  const [за_ручку, setЗаРучку] = useState<CellId | null>(null)

  const есть = (id: CellId) => cells.some((c) => c.id === id)
  // Порядок — по всем клеткам, которые вообще есть на этом экране; показываем
  // из него те, что не убраны. Считать «видимые» отдельным списком нельзя:
  // индексы перестановки берутся из полного порядка, иначе возвращённая
  // клетка встала бы не туда, откуда её убрали.
  const по_порядку = порядок.filter(есть)
  const видимые = по_порядку.filter((id) => !скрытые.includes(id))
  const убранные = по_порядку.filter((id) => скрытые.includes(id))

  const переложить = useCallback((откуда: number, куда: number) => {
    setПорядок((был) => {
      const стал = переставить(был, откуда, куда)
      записать(стал)
      return стал
    })
  }, [])

  const убрать = useCallback((id: CellId) => {
    setСкрытые((были) => {
      if (были.includes(id)) return были
      const стали = [...были, id]
      записать_скрытые(стали)
      return стали
    })
  }, [])

  const вернуть = useCallback((id: CellId) => {
    setСкрытые((были) => {
      const стали = были.filter((имя) => имя !== id)
      записать_скрытые(стали)
      return стали
    })
  }, [])

  return (
    <div className="flex flex-col gap-s3">
      <div className="flex flex-wrap items-center justify-end gap-s2">
        {правим && <span className="mr-auto text-xs text-muted">{t('dashboard.edit.hint')}</span>}
        <Button
          variant={правим ? 'primary' : 'ghost'}
          size="sm"
          onClick={() => {
            setПравим((было) => !было)
            setЗаРучку(null)
            setТянут(null)
          }}
        >
          <Icon name={правим ? 'check' : 'edit'} size={16} />
          {правим ? t('dashboard.edit.done') : t('dashboard.edit.start')}
        </Button>
      </div>

      {видимые.length === 0 && (
        <p className="rounded-md border border-dashed border-line bg-surface px-s4 py-s5 text-center text-sm text-muted">
          {t('dashboard.edit.allHidden')}
        </p>
      )}

      <div className="grid grid-cols-1 gap-s3 sm:grid-cols-6 lg:grid-cols-12">
        {видимые.map((id) => {
          const клетка = cells.find((c) => c.id === id)
          if (!клетка) return null
          const подпись = t(`dashboard.cell.${id}`)
          // Место в полном порядке, а не среди видимых: стрелка на ручке
          // двигает клетку по ленте целиком, включая убранные соседние места.
          const место = порядок.indexOf(id)
          return (
            <div
              key={id}
              className={cn('relative min-w-0', ШИРИНА[id], тянут === id && 'opacity-40')}
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
                переложить(порядок.indexOf(тянут), место)
                setТянут(null)
                setЗаРучку(null)
              }}
            >
              {правим && (
                <div className="absolute right-1.5 top-1.5 z-10 flex items-center gap-1">
                  <button
                    type="button"
                    // Имя клетки в разметке: по нему порядок ленты читается
                    // снаружи (сквозные проверки) без разбора русских подписей.
                    data-cell={id}
                    className={cn(
                      'grid h-7 w-7 place-items-center rounded-sm border border-line bg-surface text-muted shadow-1',
                      'cursor-grab hover:bg-surface-2 hover:text-ink',
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
                  <button
                    type="button"
                    data-hide={id}
                    className="grid h-7 w-7 place-items-center rounded-sm border border-line bg-surface text-muted shadow-1 hover:bg-err-bg hover:text-err"
                    aria-label={t('dashboard.edit.hide', { name: подпись })}
                    title={t('dashboard.edit.hide', { name: подпись })}
                    onClick={() => убрать(id)}
                  >
                    <Icon name="close" size={14} />
                  </button>
                </div>
              )}
              {клетка.node}
            </div>
          )
        })}
      </div>

      {правим && убранные.length > 0 && (
        <section className="flex flex-wrap items-center gap-s2 rounded-md border border-line bg-surface px-s3 py-s2">
          <span className="text-xs uppercase tracking-wide text-muted">
            {t('dashboard.edit.hidden')}
          </span>
          {убранные.map((id) => (
            <Button
              key={id}
              variant="ghost"
              size="sm"
              data-restore={id}
              // Подпись кнопки — имя клетки, а вслух читается «Вернуть клетку
              // такую-то»: рядом с кнопкой стоит слово «Убранные», и без
              // глагола список звучал бы как перечень, а не как действие.
              aria-label={t('dashboard.edit.restore', { name: t(`dashboard.cell.${id}`) })}
              title={t('dashboard.edit.restore', { name: t(`dashboard.cell.${id}`) })}
              onClick={() => вернуть(id)}
            >
              <Icon name="plus" size={14} />
              {t(`dashboard.cell.${id}`)}
            </Button>
          ))}
        </section>
      )}
    </div>
  )
}
