/**
 * panelStore — открыта ли панель агента.
 *
 * Хранилище на модуль, а не React-контекст, по одной причине: кнопку агента
 * рисует шапка (`app/shell/Topbar.tsx`), а панель монтируется в оболочке, и
 * контекст потребовал бы обернуть провайдером всё дерево — то есть править
 * общий файл ради одного булева значения. Здесь же оболочке достаётся ровно
 * одна строка монтирования, а шапке — один хук.
 *
 * **Открытость помнится в `sessionStorage`, а не в `localStorage`**: панель —
 * состояние сеанса работы, а не настройка человека. Закрыл вкладку — начал с
 * чистого экрана; перезагрузил страницу посреди прогона — панель на месте.
 *
 * `useSyncExternalStore` вместо своего `useState` + событий: он и есть
 * штатный способ подписать React на внешнее значение, и он же даёт правильный
 * снимок при отрисовке на сервере (её у нас нет, но заглушка обязательна).
 */
import { useSyncExternalStore } from 'react'

const KEY = 'koritsu.agent.open'

let открыта = read()
const слушатели = new Set<() => void>()

function read(): boolean {
  try {
    return sessionStorage.getItem(KEY) === '1'
  } catch {
    // Хранилище закрыто настройками браузера — значит панель просто не помнится.
    return false
  }
}

function write(value: boolean): void {
  try {
    sessionStorage.setItem(KEY, value ? '1' : '0')
  } catch {
    // Не записалось — переживём: на этой вкладке состояние уже поменялось.
  }
}

function set(value: boolean): void {
  if (открыта === value) return
  открыта = value
  write(value)
  for (const слушатель of слушатели) слушатель()
}

export function openAgentPanel(): void {
  set(true)
}

export function closeAgentPanel(): void {
  set(false)
}

export function toggleAgentPanel(): void {
  set(!открыта)
}

function subscribe(слушатель: () => void): () => void {
  слушатели.add(слушатель)
  return () => слушатели.delete(слушатель)
}

/** Открыта ли панель. Читают и шапка (подсветить кнопку), и сама панель. */
export function useAgentPanelOpen(): boolean {
  return useSyncExternalStore(
    subscribe,
    () => открыта,
    () => false,
  )
}
