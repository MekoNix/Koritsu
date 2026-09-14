/**
 * strokes — как элемент сцены превращается в траекторию и как перо разводится
 * с пальцем.
 *
 * Распознавание читает **сцену**, а не поток пера: точки строки берутся у
 * элементов Excalidraw, когда строка признана грязной (`recognizer.ts`). Свои
 * слушатели пера ради траектории здесь больше не нужны — и это к лучшему: они
 * видели и то, что росчерком не стало (панорама, промах мимо холста, второй
 * палец), и каждый такой призрак уезжал распознавателю линией, которой на доске
 * нет.
 *
 * Осталось два дела, и оба про планшет:
 *
 * 1. `absolutePoints` — точки росчерка в координатах сцены, с поворотом. Цена
 *    ошибки здесь не кривая картинка, а уверенный мусор: повёрнутая формула
 *    уезжает распознавателю сдвинутой, и он отвечает уверенно и не про то.
 * 2. `PenWatch` и `FingerPan` — разведение пера с пальцем: там, где есть стилус,
 *    пишет только он, а палец и ладонь двигают холст. Решать «ладонь не рисует»
 *    надо до того, как росчерк появился, а не стирать его потом, — поэтому
 *    касание перехватывается на входе и до редактора не доходит вовсе.
 */

import type { SceneElement } from './scene'

/** Состояние холста, по которому экранные координаты переводятся в сцену. */
export type ViewState = {
  scrollX?: number
  scrollY?: number
  zoom?: { value: number }
  offsetLeft?: number
  offsetTop?: number
  width?: number
  height?: number
}

/** Поворот точки вокруг центра на угол в радианах. */
function повернуть(x: number, y: number, цx: number, цy: number, угол: number): [number, number] {
  const с = Math.cos(угол)
  const си = Math.sin(угол)
  const dx = x - цx
  const dy = y - цy
  return [цx + dx * с - dy * си, цy + dx * си + dy * с]
}

/**
 * Абсолютные точки одного росчерка `freedraw`.
 *
 * `points` у `freedraw` локальные: первая всегда (0, 0), дальше координаты
 * уходят в минус, как только рука пошла влево или вверх. Центр поворота — центр
 * габарита **точек**, а не `x + width / 2`: точки не нормализуются, и у
 * росчерка, написанного справа налево, `x + width / 2` промахивается мимо
 * настоящего центра на целый размер элемента. Так же считает и сам редактор.
 *
 * Цена ошибки здесь — не кривая картинка, а уверенный мусор: повёрнутая формула
 * уезжает распознавателю сдвинутой, и он отвечает уверенно и не про то.
 */
export function absolutePoints(element: SceneElement): [number, number][] {
  const { x, y, angle } = element
  const список = element.points ?? []
  if (список.length === 0) return []
  if (!angle) return список.map(([пx, пy]) => [x + пx, y + пy] as [number, number])
  let минX = Infinity
  let максX = -Infinity
  let минY = Infinity
  let максY = -Infinity
  for (const [пx, пy] of список) {
    if (пx < минX) минX = пx
    if (пx > максX) максX = пx
    if (пy < минY) минY = пy
    if (пy > максY) максY = пy
  }
  const цx = x + (минX + максX) / 2
  const цy = y + (минY + максY) / 2
  return список.map(([пx, пy]) => повернуть(x + пx, y + пy, цx, цy, angle))
}

/** Экранные координаты → координаты сцены. Формула та же, что у редактора. */
export function toScene(
  clientX: number,
  clientY: number,
  view: ViewState,
): { x: number; y: number } {
  const масштаб = view.zoom?.value ?? 1
  return {
    x: (clientX - (view.offsetLeft ?? 0)) / масштаб - (view.scrollX ?? 0),
    y: (clientY - (view.offsetTop ?? 0)) / масштаб - (view.scrollY ?? 0),
  }
}

export type PenWatchOptions = {
  /** Впервые увидели стилус: дальше палец только двигает холст. */
  onPenSeen?: () => void
}

/**
 * Видели ли на этой доске стилус.
 *
 * Один пассивный слушатель на контейнер холста и одно поле. Пока стилуса не
 * видели, палец обязан рисовать, как рисовал: на планшете без пера и на мыши
 * другого способа писать нет. Как только стилус коснулся доски хотя бы раз,
 * `FingerPan` начинает уводить касания в панораму.
 *
 * Слушатель пассивный и на всплытии — он ничего не перехватывает и потому не
 * может отнять ввод у редактора.
 */
export class PenWatch {
  private onPenSeen?: () => void
  private узел: HTMLElement | null = null
  private былоПеро = false

  private _вниз = (со: PointerEvent) => {
    if (со.pointerType !== 'pen' || this.былоПеро) return
    this.былоПеро = true
    this.onPenSeen?.()
  }

  constructor({ onPenSeen }: PenWatchOptions = {}) {
    this.onPenSeen = onPenSeen
  }

  attach(узел: HTMLElement | null): void {
    if (this.узел === узел) return
    this.detach()
    if (!узел) return
    this.узел = узел
    узел.addEventListener('pointerdown', this._вниз, { passive: true })
  }

  detach(): void {
    this.узел?.removeEventListener('pointerdown', this._вниз)
    this.узел = null
  }

  /** Видели ли стилус: по этому и разводятся перо с пальцем. */
  get penSeen(): boolean {
    return this.былоПеро
  }
}

export type FingerPanOptions = {
  /** Разводить ли перо с пальцем прямо сейчас (стилус уже видели). */
  enabled: () => boolean
  /** Текущее состояние холста. */
  view: () => ViewState
  /** Сдвинуть и масштабировать холст: значения уже готовы к записи в `appState`. */
  onView: (next: { scrollX: number; scrollY: number; zoom: number }) => void
}

/** Во сколько раз можно ужать и растянуть холст пальцами. Пределы редактора. */
const МАСШТАБ_ОТ = 0.1
const МАСШТАБ_ДО = 30

/**
 * Палец и ладонь: холст двигается, росчерка не появляется.
 *
 * Слушатель стоит на **перехвате** и с `preventDefault`: касание не должно
 * дойти до редактора вовсе. Иначе ладонь, легшая на планшет рядом с пером,
 * рисует линию через всю доску, и убрать её можно только ластиком — а до этого
 * распознаватель успевает получить её вместе с формулой.
 *
 * Пока стилуса не видели, обработчик молчит целиком: на планшете без пера и на
 * мыши палец обязан рисовать, как рисовал.
 */
export class FingerPan {
  private enabled: () => boolean
  private view: () => ViewState
  private onView: (next: { scrollX: number; scrollY: number; zoom: number }) => void

  private узел: HTMLElement | null = null
  private касания = new Map<number, { x: number; y: number }>()
  private прежний: { x: number; y: number; расстояние: number } | null = null

  private _вниз = (со: PointerEvent) => this.вниз(со)
  private _движение = (со: PointerEvent) => this.движение(со)
  private _вверх = (со: PointerEvent) => this.вверх(со)

  constructor({ enabled, view, onView }: FingerPanOptions) {
    this.enabled = enabled
    this.view = view
    this.onView = onView
  }

  attach(узел: HTMLElement | null): void {
    if (this.узел === узел) return
    this.detach()
    if (!узел) return
    this.узел = узел
    узел.addEventListener('pointerdown', this._вниз, { capture: true })
    узел.addEventListener('pointermove', this._движение, { capture: true })
    узел.addEventListener('pointerup', this._вверх, { capture: true })
    узел.addEventListener('pointercancel', this._вверх, { capture: true })
  }

  detach(): void {
    if (!this.узел) return
    this.узел.removeEventListener('pointerdown', this._вниз, { capture: true })
    this.узел.removeEventListener('pointermove', this._движение, { capture: true })
    this.узел.removeEventListener('pointerup', this._вверх, { capture: true })
    this.узел.removeEventListener('pointercancel', this._вверх, { capture: true })
    this.узел = null
    this.касания.clear()
    this.прежний = null
  }

  private наше(со: PointerEvent): boolean {
    return this.enabled() && со.pointerType === 'touch'
  }

  /** Центр и разброс касаний: одним пальцем — панорама, двумя — ещё и масштаб. */
  private слепок(): { x: number; y: number; расстояние: number } | null {
    const точки = [...this.касания.values()]
    if (точки.length === 0) return null
    const x = точки.reduce((с, т) => с + т.x, 0) / точки.length
    const y = точки.reduce((с, т) => с + т.y, 0) / точки.length
    const первая = точки[0]
    const вторая = точки[1]
    if (!первая || !вторая) return { x, y, расстояние: 0 }
    return { x, y, расстояние: Math.hypot(первая.x - вторая.x, первая.y - вторая.y) }
  }

  private вниз(со: PointerEvent): void {
    if (!this.наше(со)) return
    со.preventDefault()
    со.stopPropagation()
    this.касания.set(со.pointerId, { x: со.clientX, y: со.clientY })
    this.прежний = this.слепок()
  }

  private движение(со: PointerEvent): void {
    if (!this.наше(со) || !this.касания.has(со.pointerId)) return
    со.preventDefault()
    со.stopPropagation()
    this.касания.set(со.pointerId, { x: со.clientX, y: со.clientY })
    const текущий = this.слепок()
    const прежний = this.прежний
    this.прежний = текущий
    if (!текущий || !прежний) return

    const вид = this.view()
    const было = вид.zoom?.value ?? 1
    const стало =
      текущий.расстояние > 0 && прежний.расстояние > 0
        ? Math.min(
            МАСШТАБ_ДО,
            Math.max(МАСШТАБ_ОТ, (было * текущий.расстояние) / прежний.расстояние),
          )
        : было

    // Прокрутка считается так, чтобы точка сцены под центром касаний осталась
    // под ним же: иначе щипок уводит холст из-под пальцев.
    const подПальцем = toScene(прежний.x, прежний.y, вид)
    const scrollX = (текущий.x - (вид.offsetLeft ?? 0)) / стало - подПальцем.x
    const scrollY = (текущий.y - (вид.offsetTop ?? 0)) / стало - подПальцем.y
    this.onView({ scrollX, scrollY, zoom: стало })
  }

  private вверх(со: PointerEvent): void {
    if (!this.касания.has(со.pointerId)) return
    со.preventDefault()
    со.stopPropagation()
    this.касания.delete(со.pointerId)
    this.прежний = this.слепок()
  }
}
