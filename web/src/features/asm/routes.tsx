/**
 * Маршруты области «Ассемблер».
 *
 *     /asm                          программы текущего пространства
 *     /asm/:projectId               перенаправление на /asm
 *     /asm/:projectId/:programId    CPU-окно программы
 *
 * Работа в адресе есть, на экране — нет, по той же причине, что у доски:
 * служба различает программы парой «работа + решение», а человек работу не
 * выбирал.
 */
import { Navigate, type RouteObject } from 'react-router-dom'

import { AsmListPage } from './AsmListPage'
import { AsmPage } from './AsmPage'

export const asmRoutes: RouteObject[] = [
  { path: 'asm', element: <AsmListPage /> },
  { path: 'asm/:projectId', element: <Navigate to="/asm" replace /> },
  { path: 'asm/:projectId/:programId', element: <AsmPage /> },
]
