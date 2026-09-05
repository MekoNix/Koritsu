/**
 * Маршруты области «Отчёты».
 *
 *     /reports              выбор работы: список с поиском и превью
 *     /reports/:projectId   экран работы: теги, заполнение, превью PDF
 *
 * Адрес экрана работы — тот же, что в карте модулей
 * (`features/projects/moduleRoutes.ts`): кнопка «открыть в модуле» со страницы
 * проекта ведёт сюда.
 */
import type { RouteObject } from 'react-router-dom'

import { ReportWorkPage } from './ReportWorkPage'
import { ReportsHomePage } from './ReportsHomePage'

export const reportsRoutes: RouteObject[] = [
  { path: 'reports', element: <ReportsHomePage /> },
  { path: 'reports/:projectId', element: <ReportWorkPage /> },
]
