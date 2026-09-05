/**
 * Маршруты админки. Файл агента E.
 *
 * Отличие от прочих областей одно: `/admin` закрыт правами (`RequireAdmin`) и
 * в сайдбар не выводится никому — правка 2 макетов и решение владельца: «тот
 * же SPA по `/admin`, виден только с `is_admin`, плюс белый список IP на
 * Caddy». Попасть сюда можно только по прямой ссылке.
 *
 * Вкладка — часть адреса (`/admin/queue`), а не состояние страницы: обновление
 * страницы на очереди обязано оставить человека на очереди.
 */
import { Navigate, type RouteObject } from 'react-router-dom'

import { RequireAdmin } from '@/app/guards'

import { AdminPage } from './AdminPage'
import { QueueTab } from './QueueTab'
import { SecurityTab } from './SecurityTab'
import { UsersTab } from './UsersTab'

export const adminRoutes: RouteObject[] = [
  {
    path: 'admin',
    element: (
      <RequireAdmin>
        <AdminPage />
      </RequireAdmin>
    ),
    children: [
      { index: true, element: <Navigate to="users" replace /> },
      { path: 'users', element: <UsersTab /> },
      { path: 'queue', element: <QueueTab /> },
      { path: 'security', element: <SecurityTab /> },
      { path: '*', element: <Navigate to="/admin/users" replace /> },
    ],
  },
]
