/**
 * Маршруты области «Доска».
 *
 *     /board                      доски текущего пространства
 *     /board/:projectId           перенаправление на /board
 *     /board/:projectId/:boardId  экран доски: холст и панель репетитора
 *
 * **Работа осталась в адресе доски и пропала из экрана.** Доска на томе —
 * решение работы, и служба различает доски парой «работа + решение»; человеку
 * же работа не показывается нигде, потому что он её не выбирал. Адрес поэтому
 * прежний: закладка на доску, сделанная вчера, обязана открываться сегодня.
 *
 * Список досок одной работы отдельным экраном больше не существует — есть один
 * список, по пространству. Адрес `/board/:projectId` остался перенаправлением:
 * по нему приходят старые закладки, и отвечать им «страницы нет» значило бы
 * наказать человека за то, что экран переделали.
 *
 * Постоянного звена вроде `new` здесь нет намеренно: доска заводится одним
 * нажатием и сразу открывается — спрашивать до неё нечего, условие называют уже
 * на самой доске.
 */
import { Navigate, type RouteObject } from 'react-router-dom'

import { BoardListPage } from './BoardListPage'
import { BoardErrorBoundary } from './BoardErrorBoundary'
import { BoardPage } from './BoardPage'

export const boardRoutes: RouteObject[] = [
  { path: 'board', element: <BoardListPage /> },
  { path: 'board/:projectId', element: <Navigate to="/board" replace /> },
  {
    path: 'board/:projectId/:boardId',
    element: (
      <BoardErrorBoundary>
        <BoardPage />
      </BoardErrorBoundary>
    ),
  },
]
