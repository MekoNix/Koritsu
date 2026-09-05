/**
 * Маршруты области «Проекты».
 * Как устроен договор — см. `features/dashboard/routes.tsx`.
 *
 * Два адреса и ни одного лишнего:
 *
 *     /projects              список работ и корзина (корзина — вкладка)
 *     /projects/<id>         одна работа: файлы и переходы в модули
 *
 * Корзина не получила своего адреса намеренно: у службы это тот же список с
 * `trash=true`, и второй маршрут означал бы второе описание одних и тех же
 * колонок и состояний.
 */
import type { RouteObject } from 'react-router-dom'

import { ProjectPage } from './ProjectPage'
import { ProjectsListPage } from './ProjectsListPage'

export const projectsRoutes: RouteObject[] = [
  { path: 'projects', element: <ProjectsListPage /> },
  { path: 'projects/:projectId', element: <ProjectPage /> },
]
