/**
 * App — провайдеры и роутер.
 *
 * Порядок вложения не декоративный:
 *
 * * `QueryClientProvider` снаружи всех — хуки данных зовутся отовсюду;
 * * `ThemeProvider` до первой отрисовки чего бы то ни было — он ставит
 *   атрибуты на `<html>` (хотя те же атрибуты уже стоят от встроенного скрипта
 *   `index.html`, и потому мигания нет);
 * * `ToastProvider` снаружи роутера — тост переживает переход между страницами;
 * * `BrowserRouter` последним, чтобы `useNavigate` был доступен всему внутри.
 *
 * `UnauthorizedRedirect` — мост между клиентом API и роутером: клиент не знает
 * про React, поэтому получает обычный колбэк.
 */
import { QueryClientProvider } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { BrowserRouter, useLocation, useNavigate, useRoutes } from 'react-router-dom'

import { setUnauthorizedHandler } from '@/api'
import { ThemeProvider } from '@/theme'
import { ToastProvider } from '@/ui'

import { createQueryClient } from './queryClient'
import { routes } from './routes'

function Routed() {
  return useRoutes(routes)
}

function UnauthorizedRedirect() {
  const navigate = useNavigate()
  const location = useLocation()

  useEffect(() => {
    setUnauthorizedHandler(() => {
      // На страницах входа 401 — обычное дело («неверный пароль»), уводить
      // оттуда некуда. Клиент такие ответы и так пропускает, но проверка
      // дешевле, чем разбирательство «почему форму сбросило».
      if (location.pathname.startsWith('/auth/')) return
      navigate('/auth/login', { replace: true, state: { from: location.pathname } })
    })
    return () => setUnauthorizedHandler(null)
  }, [navigate, location.pathname])

  return null
}

export function App() {
  // Клиент кэша создаётся один раз за жизнь приложения: новый на каждой
  // перерисовке означал бы пустой кэш и перезапрос всего.
  const [queryClient] = useState(createQueryClient)

  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <ToastProvider>
          <BrowserRouter>
            <UnauthorizedRedirect />
            <Routed />
          </BrowserRouter>
        </ToastProvider>
      </ThemeProvider>
    </QueryClientProvider>
  )
}
