/**
 * Маршруты области «Тренажёр».
 *
 *     /cards                           библиотека наборов пространства
 *     /cards/new                       загрузка файла или текста
 *     /cards/generate                  создание набора агентом
 *     /cards/drafts/:draftId           черновик
 *     /cards/:projectId                перенаправление на /cards
 *     /cards/:projectId/:setId         набор
 *     /cards/:projectId/:setId/play    заход и итоги
 *
 * Статические звенья (`new`, `generate`, `drafts`) выигрывают у параметра сами;
 * идентификатор работы с ними не совпадёт.
 *
 * Работа в адресе набора есть, на экране — нет, как у доски и ассемблера: служба
 * различает наборы парой «работа + набор», а человек работу не выбирал.
 *
 * Заход, генерация и черновик грузятся своими кусками: библиотеку открывают чаще, чем
 * создают наборы, а заход тянет за собой клавиатуру, свайпы и очередь ответов.
 */
import { Suspense, lazy } from 'react'
import { Navigate, type RouteObject } from 'react-router-dom'

import { SkeletonLines } from '@/ui'

import { LibraryPage } from './LibraryPage'
import { SetPage } from './SetPage'
import { UploadPage } from './UploadPage'

const GeneratePage = lazy(() => import('./generate/GeneratePage'))
const DraftPage = lazy(() => import('./generate/DraftPage'))
const PlayPage = lazy(() => import('./play/PlayPage'))

const ожидание = <SkeletonLines count={5} />

export const cardsRoutes: RouteObject[] = [
  { path: 'cards', element: <LibraryPage /> },
  { path: 'cards/new', element: <UploadPage /> },
  {
    path: 'cards/generate',
    element: (
      <Suspense fallback={ожидание}>
        <GeneratePage />
      </Suspense>
    ),
  },
  {
    path: 'cards/drafts/:draftId',
    element: (
      <Suspense fallback={ожидание}>
        <DraftPage />
      </Suspense>
    ),
  },
  { path: 'cards/:projectId', element: <Navigate to="/cards" replace /> },
  { path: 'cards/:projectId/:setId', element: <SetPage /> },
  {
    path: 'cards/:projectId/:setId/play',
    element: (
      <Suspense fallback={ожидание}>
        <PlayPage />
      </Suspense>
    ),
  },
]
