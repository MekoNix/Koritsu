/**
 * routes — всё дерево маршрутов сайта.
 *
 * **Как оно собрано и почему так.** Каждая область объявляет свои маршруты у
 * себя (`features/<область>/routes.tsx`), а здесь они перечислены по одной
 * строке на область. Причина простая: над сайтом работают пятеро сразу, и файл
 * с полусотней `<Route>` означал бы пять правок в одно место каждую ночь.
 * Добавить область — импорт и строка в `...spread`; больше здесь ничего не
 * трогается.
 *
 * Два уровня:
 *
 * * `/auth/*` — без оболочки: до входа нечего показывать в сайдбаре;
 * * всё остальное — внутри `RequireAuth` и `AppShell`.
 *
 * `/admin` живёт среди обычных маршрутов, но закрыт `RequireAdmin` (это делает
 * `features/admin/routes.tsx`) и в сайдбар не выводится никому.
 */
import type { RouteObject } from 'react-router-dom'

import { adminRoutes } from '@/features/admin/routes'
import { authRoutes } from '@/features/auth/routes'
import { dashboardRoutes } from '@/features/dashboard/routes'
import { diagramsRoutes } from '@/features/diagrams/routes'
import { kadaiRoutes } from '@/features/kadai/routes'
import { projectsRoutes } from '@/features/projects/routes'
import { reportsRoutes } from '@/features/reports/routes'
import { settingsRoutes } from '@/features/settings/routes'
import { workspaceRoutes } from '@/features/workspace/routes'

import { NotFoundPage } from './NotFoundPage'
import { RequireAuth } from './guards'
import { AppShell } from './shell/AppShell'

export const routes: RouteObject[] = [
  ...authRoutes,
  {
    path: '/',
    element: (
      <RequireAuth>
        <AppShell />
      </RequireAuth>
    ),
    children: [
      ...dashboardRoutes,
      ...projectsRoutes,
      ...reportsRoutes,
      ...kadaiRoutes,
      ...diagramsRoutes,
      ...settingsRoutes,
      ...workspaceRoutes,
      ...adminRoutes,
      { path: '*', element: <NotFoundPage /> },
    ],
  },
]
