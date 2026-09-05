/**
 * Маршруты админки.
 *
 * Отличий от прочих областей два, и оба про доступ.
 *
 * 1. **Своё имя.** Админка живёт на домене третьего уровня; на основном имени
 *    её страниц нет вовсе — там 404 отвечают и прокси, и служба, и сайт
 *    показывает то же самое (`НаСвоёмИмени`). Без домена (машина
 *    разработчика, стенд) `/admin` открывается там же, где весь сайт.
 * 2. **Права.** `RequireAdmin` по `is_admin`; в сайдбар пункт не выводится
 *    никому, попасть сюда можно ссылкой из меню пользователя.
 *
 * Порядок проверок именно такой: сначала имя, потом права. Обратный показал бы
 * «нет доступа» тому, кто пришёл на имя, где админки не существует, — то есть
 * рассказал бы про неё.
 *
 * Вкладка — часть адреса (`/admin/queue`), а не состояние страницы: обновление
 * страницы на очереди обязано оставить человека на очереди.
 */
import type { ReactNode } from 'react'
import { Navigate, type RouteObject } from 'react-router-dom'

import { RequireAdmin } from '@/app/guards'
import { NotFoundPage } from '@/app/NotFoundPage'
import { админкаНаЭтомИмени } from '@/lib/adminHost'

import { AdminPage } from './AdminPage'
import { OverviewTab } from './OverviewTab'
import { PlansTab } from './PlansTab'
import { QueueTab } from './QueueTab'
import { SecurityTab } from './SecurityTab'
import { UsersTab } from './UsersTab'

/**
 * «Страницы нет» вместо админки, когда имя не то.
 *
 * Именно `NotFoundPage`, а не «нет доступа»: с основного имени админка обязана
 * выглядеть несуществующей — ровно так же, как она выглядит для прокси и для
 * службы. «Нет доступа» рассказало бы, что такой адрес всё-таки есть.
 */
function НаСвоёмИмени({ children }: { children: ReactNode }) {
  if (!админкаНаЭтомИмени()) return <NotFoundPage />
  return <>{children}</>
}

export const adminRoutes: RouteObject[] = [
  {
    path: 'admin',
    element: (
      <НаСвоёмИмени>
        <RequireAdmin>
          <AdminPage />
        </RequireAdmin>
      </НаСвоёмИмени>
    ),
    children: [
      { index: true, element: <Navigate to="overview" replace /> },
      { path: 'overview', element: <OverviewTab /> },
      { path: 'users', element: <UsersTab /> },
      { path: 'plans', element: <PlansTab /> },
      { path: 'queue', element: <QueueTab /> },
      { path: 'security', element: <SecurityTab /> },
      { path: '*', element: <Navigate to="/admin/overview" replace /> },
    ],
  },
]
