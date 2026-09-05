/**
 * useHotkey — горячая клавиша на всё окно.
 *
 * Общий хук, а не свой `addEventListener` в каждой области: горячих клавиш у
 * сайта две (Ctrl+J — панель агента, Ctrl+K — поиск), и написанные по месту они
 * разошлись бы в мелочах, которые видно только руками, — одна ловит `keydown`,
 * другая `keyup`, одна отменяет действие браузера, другая нет.
 *
 * Что хук делает и почему:
 *
 * * **`ctrl` — это и `Cmd`.** На маке `Ctrl+J` не нажимают: там модификатор
 *   `Cmd`. Сочетание названо словом «Ctrl», и оно остаётся написанным
 *   так в подсказке, но принимаются оба — иначе на маке клавиши просто нет.
 * * **Действие браузера отменяется** (`preventDefault`): `Ctrl+J` в Chrome
 *   открывает загрузки, `Ctrl+K` в Firefox уводит фокус в строку поиска.
 * * **Печатающему не мешаем только там, где сочетание без модификатора.** Наши
 *   сочетания с `Ctrl`, и в поле ввода они значат то же самое, что снаружи:
 *   человек, набирающий задачу агенту, вправе закрыть панель тем же `Ctrl+J`.
 *
 * **Сочетание можно переназначить** (раздел настроек «Горячие клавиши»).
 * Переназначения живут в `localStorage` этого браузера и нигде больше: служба
 * про клавиатуру человека ничего не знает, и заводить ради двух строк поле в
 * профиле значило бы возить их запросом на каждом открытии страницы. Читает их `useActionHotkey`, и только он — сочетание,
 * написанное в вызове буквой, остаётся буквой (`useHotkey('ctrl+j', …)`
 * по-прежнему работает и ничего не спрашивает).
 *
 * Пример:
 *
 *     useActionHotkey('agent', toggleAgentPanel)   // с учётом переназначения
 *     useHotkey('ctrl+j', toggleAgentPanel)        // жёстко, как написано
 */
import { useEffect, useRef, useSyncExternalStore } from 'react'

/** Разобранное сочетание: модификаторы и сама клавиша. */
type Combo = { ctrl: boolean; shift: boolean; alt: boolean; key: string }

function parse(combo: string): Combo {
  const части = combo
    .toLowerCase()
    .split('+')
    .map((s) => s.trim())
    .filter(Boolean)
  return {
    ctrl: части.includes('ctrl') || части.includes('cmd') || части.includes('mod'),
    shift: части.includes('shift'),
    alt: части.includes('alt'),
    key: части[части.length - 1] ?? '',
  }
}

function matches(event: KeyboardEvent, combo: Combo): boolean {
  // `Cmd` — это `metaKey`; принимаем его наравне с `ctrlKey` (см. заголовок).
  const ctrl = event.ctrlKey || event.metaKey
  if (combo.ctrl !== ctrl) return false
  if (combo.shift !== event.shiftKey) return false
  if (combo.alt !== event.altKey) return false
  return event.key.toLowerCase() === combo.key
}

export function useHotkey(
  combo: string,
  handler: (event: KeyboardEvent) => void,
  enabled = true,
): void {
  // Обработчик в `ref`, чтобы подписка не пересоздавалась на каждой перерисовке:
  // иначе `useEffect` снимал бы и ставил слушателя по десять раз в секунду.
  const свежий = useRef(handler)
  свежий.current = handler

  useEffect(() => {
    if (!enabled) return
    const разобрано = parse(combo)
    if (!разобрано.key) return
    const слушать = (event: KeyboardEvent) => {
      if (!matches(event, разобрано)) return
      event.preventDefault()
      свежий.current(event)
    }
    window.addEventListener('keydown', слушать)
    return () => window.removeEventListener('keydown', слушать)
  }, [combo, enabled])
}

// ── что вообще можно нажать ──────────────────────────────────────────────────

/**
 * Одно действие сайта: как оно зовётся и какой клавишей вызывается.
 *
 * `fixed: true` — сочетание, которое живёт не в этом хуке: `Ctrl+Enter`
 * обрабатывает само поле ввода (иначе оно срабатывало бы и вне формы), `Esc`
 * закрывает окно силами Radix (и он же возвращает фокус туда, откуда окно
 * открыли). Показывать их в списке надо — человек ищет там все клавиши сайта,
 * а не только переназначаемые, — а обещать переназначение нельзя: оно бы
 * просто не работало.
 */
export type HotkeyAction = {
  id: string
  /** Сочетание, с которым сайт приехал. */
  default: string
  fixed?: boolean
}

/**
 * Список сочетаний сайта. Здесь, а не в разделе настроек: настройки его
 * показывают, а работает по нему `useActionHotkey` — второй такой список
 * разошёлся бы с первым молча, и человек менял бы сочетание, которое ничего
 * не делает.
 */
export const HOTKEY_ACTIONS: readonly HotkeyAction[] = [
  { id: 'search', default: 'ctrl+k' },
  { id: 'agent', default: 'ctrl+j' },
  { id: 'send', default: 'ctrl+enter', fixed: true },
  { id: 'close', default: 'escape', fixed: true },
]

// Переназначения живут в `localStorage` этого браузера и нигде больше: служба
// про клавиатуру человека ничего не знает, и заводить ради двух строк поле в
// профиле значило бы возить их запросом на каждом открытии страницы.
const ХРАНИЛИЩЕ = 'koritsu.hotkeys'

let переназначения = прочитать()
const слушатели = new Set<() => void>()

function прочитать(): Record<string, string> {
  try {
    const сырое = localStorage.getItem(ХРАНИЛИЩЕ)
    if (!сырое) return {}
    const разобрано: unknown = JSON.parse(сырое)
    if (!разобрано || typeof разобрано !== 'object') return {}
    // Проверяется каждое значение: в хранилище лежит то, что туда положила
    // прошлая версия сайта, и `null` вместо строки уронил бы разбор сочетания.
    const годные: Record<string, string> = {}
    for (const [id, combo] of Object.entries(разобрано as Record<string, unknown>)) {
      if (typeof combo === 'string' && combo) годные[id] = combo
    }
    return годные
  } catch {
    // Хранилище закрыто настройками браузера или в нём мусор — значит
    // сочетания просто те, с которыми сайт приехал.
    return {}
  }
}

function записать(): void {
  try {
    localStorage.setItem(ХРАНИЛИЩЕ, JSON.stringify(переназначения))
  } catch {
    // Не записалось — переживём: на этой вкладке сочетание уже поменялось.
  }
}

function разослать(): void {
  for (const слушатель of слушатели) слушатель()
}

/** Переназначить сочетание. `null` — вернуть то, с которым сайт приехал. */
export function setHotkey(id: string, combo: string | null): void {
  const следующие = { ...переназначения }
  if (combo) следующие[id] = combo
  else delete следующие[id]
  переназначения = следующие
  записать()
  разослать()
}

/** Вернуть все сочетания к умолчаниям. */
export function resetHotkeys(): void {
  переназначения = {}
  записать()
  разослать()
}

function subscribe(слушатель: () => void): () => void {
  слушатели.add(слушатель)
  return () => слушатели.delete(слушатель)
}

/**
 * Какое сочетание сейчас у этого действия. `useSyncExternalStore`, а не чтение
 * при отрисовке: сменил сочетание в настройках — и слушатель, и подсказка в
 * шапке обязаны поменяться сразу, без перезагрузки страницы.
 */
export function useHotkeyBinding(id: string): string {
  const действие = HOTKEY_ACTIONS.find((д) => д.id === id)
  const умолчание = действие?.default ?? ''
  const снимок = () => (действие?.fixed ? умолчание : (переназначения[id] ?? умолчание))
  return useSyncExternalStore(subscribe, снимок, () => умолчание)
}

/** Все сочетания разом — этим живёт список в настройках. */
export function useHotkeyBindings(): Record<string, string> {
  const свои = useSyncExternalStore(
    subscribe,
    () => переназначения,
    () => ПУСТО,
  )
  const итог: Record<string, string> = {}
  for (const действие of HOTKEY_ACTIONS) {
    итог[действие.id] = действие.fixed ? действие.default : (свои[действие.id] ?? действие.default)
  }
  return итог
}

// Один и тот же пустой объект: снимок для отрисовки на сервере обязан быть
// стабильным, иначе React считает, что значение меняется на каждой отрисовке.
const ПУСТО: Record<string, string> = {}

/** Горячая клавиша действия — с учётом переназначения человеком. */
export function useActionHotkey(
  id: string,
  handler: (event: KeyboardEvent) => void,
  enabled = true,
): void {
  useHotkey(useHotkeyBinding(id), handler, enabled)
}

/**
 * Сочетание словами: `ctrl+k` → «Ctrl K». Одно место на весь сайт, потому что
 * подпись рисуют трое: список настроек, подсказка в шапке и панель агента.
 */
const ИМЕНА_КЛАВИШ: Record<string, string> = {
  ctrl: 'Ctrl',
  cmd: 'Cmd',
  mod: 'Ctrl',
  shift: 'Shift',
  alt: 'Alt',
  enter: 'Enter',
  escape: 'Esc',
  ' ': 'Space',
}

export function hotkeyLabel(combo: string): string {
  return combo
    .split('+')
    .map((часть) => ИМЕНА_КЛАВИШ[часть] ?? (часть.length === 1 ? часть.toUpperCase() : часть))
    .join(' ')
}

/**
 * Сочетание из нажатия. `null` — нажали только модификатор (человек держит
 * `Ctrl` и выбирает вторую клавишу) или клавишу без модификатора.
 *
 * Без модификатора сочетание не берём намеренно: одиночная буква ловилась бы
 * посреди набора текста в любом поле сайта.
 *
 * `event.key`, а не `event.code`: сочетание запоминается тем знаком, который
 * человек видит на клавише, и на русской раскладке «Ctrl+К» обязано остаться
 * «Ctrl+К», а не превратиться в `KeyK`.
 */
export function comboFromEvent(event: KeyboardEvent): string | null {
  const клавиша = event.key.toLowerCase()
  if (['control', 'shift', 'alt', 'meta', 'os'].includes(клавиша)) return null
  const части: string[] = []
  if (event.ctrlKey || event.metaKey) части.push('ctrl')
  if (event.shiftKey) части.push('shift')
  if (event.altKey) части.push('alt')
  if (части.length === 0) return null
  части.push(клавиша === ' ' ? ' ' : клавиша)
  return части.join('+')
}
