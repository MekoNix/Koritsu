/**
 * Маршруты входа. Файл агента A; остальные его не трогают.
 *
 * Оболочки (сайдбар, шапка) на этих страницах нет намеренно: до входа нечего
 * показывать в меню и некому — в шапке.
 */
import type { RouteObject } from 'react-router-dom'
import { Navigate } from 'react-router-dom'

import { ConfirmPage } from './ConfirmPage'
import { ForgotPage } from './ForgotPage'
import { LoginPage } from './LoginPage'
import { RegisterPage } from './RegisterPage'
import { ResetPage } from './ResetPage'

export const authRoutes: RouteObject[] = [
  { path: 'auth', element: <Navigate to="/auth/login" replace /> },
  { path: 'auth/login', element: <LoginPage /> },
  { path: 'auth/register', element: <RegisterPage /> },
  { path: 'auth/confirm', element: <ConfirmPage /> },
  { path: 'auth/forgot', element: <ForgotPage /> },
  { path: 'auth/reset', element: <ResetPage /> },
]
