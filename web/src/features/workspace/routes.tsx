/**
 * Маршруты области «Пространство».
 *
 * Два адреса на один экран: `/workspace` — то пространство, в котором человек
 * работает сейчас, `/workspace/:id` — названное. Второй нужен для ссылки на
 * чужое пространство: открыть его состав, не переключая своё рабочее место.
 */
import type { RouteObject } from 'react-router-dom'

import { WorkspacePage } from './WorkspacePage'

export const workspaceRoutes: RouteObject[] = [
  { path: 'workspace', element: <WorkspacePage /> },
  { path: 'workspace/:id', element: <WorkspacePage /> },
]
