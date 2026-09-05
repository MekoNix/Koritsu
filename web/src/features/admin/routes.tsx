/**
 * Маршруты админки.
 *
 * Отличие от прочих областей одно: `/admin` закрыт правами (`RequireAdmin`) и
 * в сайдбар не выводится никому: тот же SPA по `/admin`, виден только с
 * `is_admin`, плюс белый список IP на Caddy. Попасть сюда можно только по
 * прямой ссылке.
 *
 * Вкладка — часть адреса (`/admin/queue`), а не состояние страницы: обновление
 * страницы на очереди обязано оставить человека на очереди.
 */
import { Navigate, type RouteObject } from 'react-router-dom'

import { RequireAdmin } from '@/app/guards'

import { AdminPage } from './AdminPage'
import { OverviewTab } from './OverviewTab'
import { PlansTab } from './PlansTab'
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
      { index: true, element: <Navigate to="overview" replace /> },
      { path: 'overview', element: <OverviewTab /> },
      { path: 'users', element: <UsersTab /> },
      { path: 'plans', element: <PlansTab /> },
      { path: 'queue', element: <QueueTab /> },
      { path: 'security', element: <SecurityTab /> },
      { path: '*', element: <Navigate to="/admin/overview" replace /> },
    ],
  },
]
