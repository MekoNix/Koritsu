/**
 * Маршруты области «Решения» (kadai).
 *
 *     /kadai                    работы пространства и их решения
 *     /kadai/:projectId         то же, с выбранной работой
 *     /kadai/:projectId/new     страница нового решения: условие, файлы, пожелания
 *     /kadai/:projectId/:runId  экран решения: стадии, условие, блоки, «как в Word»
 *
 * Адрес `/kadai/:projectId` — тот же, что в `features/projects/moduleRoutes.ts`:
 * кнопка «открыть в модуле» со страницы работы ведёт сюда, и попадает человек в
 * список её решений, а не в одно из них наугад.
 *
 * `new` стоит рядом с `:runId` не по порядку строк, а по устройству
 * маршрутизатора: постоянное звено пути он предпочитает переменному, поэтому
 * «новое решение» не читается как идентификатор решения.
 */
import type { RouteObject } from 'react-router-dom'

import { KadaiHomePage } from './KadaiHomePage'
import { KadaiNewRunPage } from './KadaiNewRunPage'
import { KadaiWorkPage } from './KadaiWorkPage'

export const kadaiRoutes: RouteObject[] = [
  { path: 'kadai', element: <KadaiHomePage /> },
  { path: 'kadai/:projectId', element: <KadaiHomePage /> },
  { path: 'kadai/:projectId/new', element: <KadaiNewRunPage /> },
  { path: 'kadai/:projectId/:runId', element: <KadaiWorkPage /> },
]
