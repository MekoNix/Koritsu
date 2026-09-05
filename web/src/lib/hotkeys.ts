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
 *   `Cmd`. Владелец назвал сочетание словом «Ctrl», и оно остаётся написанным
 *   так в подсказке, но принимаются оба — иначе на маке клавиши просто нет.
 * * **Действие браузера отменяется** (`preventDefault`): `Ctrl+J` в Chrome
 *   открывает загрузки, `Ctrl+K` в Firefox уводит фокус в строку поиска.
 * * **Печатающему не мешаем только там, где сочетание без модификатора.** Наши
 *   сочетания с `Ctrl`, и в поле ввода они значат то же самое, что снаружи:
 *   человек, набирающий задачу агенту, вправе закрыть панель тем же `Ctrl+J`.
 *
 * Пример:
 *
 *     useHotkey('ctrl+j', toggleAgentPanel)
 */
import { useEffect, useRef } from 'react'

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
