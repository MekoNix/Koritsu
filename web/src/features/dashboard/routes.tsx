/**
 * Маршруты области «Дашборд». Файл агента B.
 *
 * Договор: область объявляет свои маршруты здесь и только здесь, а
 * `app/routes.tsx` подключает список одной строкой. Пути — относительные:
 * область не знает, под каким префиксом её повесили.
 */
import type { RouteObject } from 'react-router-dom'

import { DashboardPage } from './DashboardPage'

export const dashboardRoutes: RouteObject[] = [
  { index: true, element: <DashboardPage /> },
  { path: 'dashboard', element: <DashboardPage /> },
]
