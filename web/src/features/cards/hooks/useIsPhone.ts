/**
 * useIsPhone — узкий экран (телефон), ширина окна не больше 640 px.
 *
 * Экраны тренажёра устроены в двух раскладках, а не сжатым компьютерным видом:
 * на телефоне настройки — нижним листом, кнопки захода — внизу под большим пальцем.
 * Что можно сделать разметкой, делается классами `max-[640px]:` / `min-[641px]:`
 * (нет мигания при первой отрисовке); хук нужен там, где раскладки отличаются
 * устройством — лист вместо панели, другой порядок блоков.
 *
 * Граница та же, что у классов: `(max-width: 640px)`.
 */
import { useSyncExternalStore } from 'react'

export const PHONE_QUERY = '(max-width: 640px)'

function медиа(): MediaQueryList | null {
  return typeof window !== 'undefined' && typeof window.matchMedia === 'function' ? window.matchMedia(PHONE_QUERY) : null
}

function подписаться(слушатель: () => void): () => void {
  const m = медиа()
  if (!m) return () => {}
  m.addEventListener('change', слушатель)
  return () => m.removeEventListener('change', слушатель)
}

function снимок(): boolean {
  return медиа()?.matches ?? false
}

export function useIsPhone(): boolean {
  return useSyncExternalStore(подписаться, снимок, () => false)
}
