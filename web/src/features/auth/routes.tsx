/**
 * Маршруты входа.
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
import { WithQuery } from './WithQuery'

export const authRoutes: RouteObject[] = [
  { path: 'auth', element: <Navigate to="/auth/login" replace /> },
  { path: 'auth/login', element: <LoginPage /> },
  { path: 'auth/register', element: <RegisterPage /> },
  { path: 'auth/confirm', element: <ConfirmPage /> },
  { path: 'auth/forgot', element: <ForgotPage /> },
  { path: 'auth/reset', element: <ResetPage /> },

  // Ссылки из писем служба собирает без приставки `auth`:
  // `{base_url}/confirm?token=…` и `{base_url}/reset?token=…`
  // (`packages/api/accounts/mail.py`); ту же ссылку получает администратор, заводя
  // человека руками (`POST /api/admin/users`). Без этих двух записей письмо
  // приводило человека в `*` внутри оболочки, оттуда — на форму входа, и токен
  // терялся по дороге: ни подтвердить почту, ни поставить пароль по ссылке
  // было нельзя. Приставка добавляется здесь, а не в службе, потому что письма,
  // уже ушедшие людям, переписать нельзя — а работать они обязаны.
  { path: 'confirm', element: <WithQuery to="/auth/confirm" /> },
  { path: 'reset', element: <WithQuery to="/auth/reset" /> },
]
