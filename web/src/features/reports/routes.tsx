/**
 * Маршруты области «Отчёты». Файл агента C.
 *
 *     /reports              выбор работы: список с поиском и превью
 *     /reports/:projectId   экран работы: теги, заполнение, превью PDF
 *
 * Адрес экрана работы — тот, о котором договорились агенты ночи
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
