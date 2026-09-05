/**
 * Маршруты области «Схемы» (блок-схемы и UML). Файл агента D.
 *
 * Два модуля службы (`flowcharts`, `uml`) живут одной областью: экран у них
 * один и тот же — код слева, встроенный draw.io справа, — и разводить его на
 * два дерева файлов значило бы держать две копии одного экрана. В сайдбаре
 * они всё равно двумя пунктами (`app/shell/moduleLinks.ts`).
 *
 * Адреса — верхнего уровня (`/flowcharts`, `/uml`), а не `/diagrams/…`:
 * подтверждено главной сессией, на них же ссылаются сайдбар и страница
 * проекта. Прежние `/diagrams/*` из заготовки каркаса остались
 * перенаправлениями: ссылки на них могли уже разойтись по чужим экранам, и
 * молча ронять их в «страница не найдена» — худшее из решений.
 *
 * Без проекта схему не сохранить, поэтому рабочий экран живёт по адресу
 * проекта, а корень модуля — это список уже сохранённых схем и вход в новую.
 */
import { Navigate, type RouteObject } from 'react-router-dom'

import { DiagramWorkbench } from './DiagramWorkbench'
import { DiagramsHome } from './DiagramsHome'

export const diagramsRoutes: RouteObject[] = [
  { path: 'flowcharts', element: <DiagramsHome module="flowcharts" /> },
  { path: 'flowcharts/:projectId', element: <DiagramWorkbench module="flowcharts" /> },
  { path: 'uml', element: <DiagramsHome module="uml" /> },
  { path: 'uml/:projectId', element: <DiagramWorkbench module="uml" /> },

  // Старые адреса заготовки — на новые.
  { path: 'diagrams/flowcharts/*', element: <Navigate to="/flowcharts" replace /> },
  { path: 'diagrams/uml/*', element: <Navigate to="/uml" replace /> },
  { path: 'diagrams/*', element: <Navigate to="/flowcharts" replace /> },
]
