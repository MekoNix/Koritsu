/**
 * AppShell — общий каркас: сайдбар слева, шапка сверху, экран внутри.
 *
 * Здесь же открывается единственный на всё приложение поток событий человека
 * (`useUserEvents`): он гасит и зажигает колокольчик и выдаёт тосты на
 * завершение фоновых задач. Открывать его в экранах нельзя — сколько экранов,
 * столько было бы соединений.
 *
 * Состояние «сайдбар свёрнут» помнится в `localStorage`: бриф требует, чтобы
 * сворачивание происходило по кнопке, а не по наведению, — и значит выбор
 * человека обязан пережить перезагрузку.
 */
import { useCallback, useState } from 'react'
import { Outlet } from 'react-router-dom'

import { useUserEvents } from '@/api/hooks'

import { BreadcrumbProvider } from './breadcrumbs'
import { Sidebar } from './Sidebar'
import { Topbar } from './Topbar'

const KEY = 'koritsu.sidebar.collapsed'

function readCollapsed(): boolean {
  try {
    return localStorage.getItem(KEY) === '1'
  } catch {
    return false
  }
}

export function AppShell() {
  const [collapsed, setCollapsed] = useState(readCollapsed)

  // Поток человека: один на приложение, живёт столько же, сколько оболочка.
  useUserEvents()

  const toggle = useCallback(() => {
    setCollapsed((was) => {
      const next = !was
      try {
        localStorage.setItem(KEY, next ? '1' : '0')
      } catch {
        // Не записалось — переживём: на этой вкладке состояние уже поменялось.
      }
      return next
    })
  }, [])

  return (
    <BreadcrumbProvider>
      <div className="flex min-h-screen">
        <Sidebar collapsed={collapsed} onToggle={toggle} />
        <div className="flex min-w-0 flex-1 flex-col">
          <Topbar />
          <main className="mx-auto w-full max-w-content flex-1 p-s5">
            <Outlet />
          </main>
        </div>
      </div>
    </BreadcrumbProvider>
  )
}
