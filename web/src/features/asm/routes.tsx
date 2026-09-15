/**
 * Маршруты области «Ассемблер».
 *
 *     /asm                          программы текущего пространства, обоих режимов
 *     /asm/new?toolchain=           новая программа: режим, версия, имя
 *     /asm/:projectId               перенаправление на /asm
 *     /asm/:projectId/:programId    CPU-окно программы
 *
 * `asm/new` стоит раньше `asm/:projectId`: статический сегмент и так выигрывает
 * у параметра, порядок в списке это только подчёркивает.
 *
 * Работа в адресе есть, на экране — нет, по той же причине, что у доски:
 * служба различает программы парой «работа + решение», а человек работу не
 * выбирал. Режима в адресе программы нет: он записан у самой программы, и второй
 * источник правды разошёлся бы с первым.
 */
import { Navigate, type RouteObject } from 'react-router-dom'

import { AsmListPage } from './AsmListPage'
import { AsmNewPage } from './AsmNewPage'
import { AsmPage } from './AsmPage'

export const asmRoutes: RouteObject[] = [
  { path: 'asm', element: <AsmListPage /> },
  { path: 'asm/new', element: <AsmNewPage /> },
  { path: 'asm/:projectId', element: <Navigate to="/asm" replace /> },
  { path: 'asm/:projectId/:programId', element: <AsmPage /> },
]
