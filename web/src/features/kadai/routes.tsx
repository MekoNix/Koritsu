/**
 * Маршруты области «Задания» (kadai).
 *
 *     /kadai              список работ модуля и заведение новой
 *     /kadai/:projectId   экран работы: стадии, условие, блоки, «как в Word»
 *
 * Адрес экрана работы — тот же, что в `features/projects/moduleRoutes.ts`:
 * кнопка «открыть в модуле» со страницы проекта ведёт сюда.
 */
import type { RouteObject } from 'react-router-dom'

import { KadaiHomePage } from './KadaiHomePage'
import { KadaiWorkPage } from './KadaiWorkPage'

export const kadaiRoutes: RouteObject[] = [
  { path: 'kadai', element: <KadaiHomePage /> },
  { path: 'kadai/:projectId', element: <KadaiWorkPage /> },
]
