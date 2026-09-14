/**
 * callouts — замечание репетитора становится выноской у своего куска холста.
 *
 * Здесь работает симметрия, ради которой всё и затевалось: **наружу едут
 * идентификаторы, внутрь приезжают координаты**. Модель не видела ни одной
 * координаты — она вернула `objects: ["<id>"]`, а место на экране считается
 * здесь, из `x/y/width/height` элемента сцены. Поэтому выноска не может встать
 * «в пустом месте по мнению модели»: она встаёт там, где действительно лежит
 * названный элемент, или не встаёт вовсе, и замечание живёт только списком.
 *
 * Второе следствие: пересчёт обязан идти на каждое изменение холста. Прокрутка и
 * масштаб живут в состоянии вида, а не в элементах; выноска, посчитанная один
 * раз, отклеится от росчерка на первом же сдвиге холста, и человек будет читать
 * замечание не о том.
 *
 * Выноски — **наложение над холстом, а не элементы сцены**: они принадлежат
 * прогону, а не решению человека, и переживать перезагрузку не обязаны. Правка
 * холста после проверки гасит вердикт и бледнит выноски: они относятся к
 * прежнему снимку.
 */

import { bounds, type Box, type SceneElement } from './scene'
import type { ViewState } from './strokes'
import type { BoardRemark, RemarkKind } from './types'

/** Прямоугольник в пикселях контейнера холста. */
export type Rect = { x: number; y: number; width: number; height: number }

/**
 * Тон выноски по виду замечания. Только токены тем — своих цветов у доски нет.
 *
 * `missing` и `hint` делят предупреждающий тон намеренно: оба говорят «здесь
 * чего-то не хватает», и разводить их третьим цветом значило бы просить человека
 * помнить четыре цвета вместо трёх.
 */
export const REMARK_TONE: Record<RemarkKind, 'ok' | 'err' | 'warn' | 'info'> = {
  ok: 'ok',
  error: 'err',
  hint: 'info',
  missing: 'warn',
}

/** Координаты сцены → пиксели внутри контейнера холста. */
export function toViewport(
  point: { x: number; y: number },
  view: ViewState,
): { x: number; y: number } {
  const масштаб = view.zoom?.value ?? 1
  return {
    x: (point.x + (view.scrollX ?? 0)) * масштаб,
    y: (point.y + (view.scrollY ?? 0)) * масштаб,
  }
}

/** Прямоугольник сцены в пикселях контейнера холста. */
export function boxToViewport(box: Box, view: ViewState): Rect {
  const левоверх = toViewport({ x: box.x, y: box.y }, view)
  const масштаб = view.zoom?.value ?? 1
  return {
    x: левоверх.x,
    y: левоверх.y,
    // Меньше дюжины пикселей выноска не бывает: у точки над «i» габарит почти
    // нулевой, и рамка вокруг неё была бы невидимой.
    width: Math.max(box.width * масштаб, 12),
    height: Math.max(box.height * масштаб, 12),
  }
}

/** Виден ли прямоугольник хоть частью в окне холста. */
export function inView(rect: Rect, view: ViewState): boolean {
  return (
    rect.x + rect.width > -40 &&
    rect.y + rect.height > -40 &&
    rect.x < (view.width ?? 0) + 40 &&
    rect.y < (view.height ?? 0) + 40
  )
}

/**
 * Место выноски по замечанию.
 *
 * `null`, если ни один из названных элементов в сцене не найден: замечание тогда
 * уходит в ленту, а не рисуется наугад. Служба и так переносит выдуманные
 * идентификаторы в замечание с пустым `objects`, но проверить это ещё раз дёшево,
 * а последствие «выноска в пустом месте» — дорогое.
 */
export function calloutRect(
  remark: Pick<BoardRemark, 'objects'>,
  elements: readonly SceneElement[],
  view: ViewState,
): Rect | null {
  const набор = new Set(remark.objects ?? [])
  if (набор.size === 0) return null
  const свои = elements.filter((э) => набор.has(э.id) && !э.isDeleted)
  if (свои.length === 0) return null
  const рамка = bounds(свои)
  if (!рамка) return null
  return boxToViewport(рамка, view)
}

/** Место подсветки одной строки чистовика на холсте: те же правила. */
export function highlightRect(
  ids: readonly string[],
  elements: readonly SceneElement[],
  view: ViewState,
): Rect | null {
  return calloutRect({ objects: [...ids] }, elements, view)
}
