/**
 * guards — кто куда пускается.
 *
 * Два правила, и оба проверяются ещё раз на службе. Здесь они нужны не ради
 * безопасности (её обеспечивает служба), а ради того, чтобы человек не видел
 * мигающий пустой экран перед отказом.
 *
 * `RequireAuth` — сессия. Пока ответ не приехал, показывается скелетон, а не
 * редирект: иначе перезагрузка любой внутренней страницы выкидывала бы на вход
 * на долю секунды даже вошедшего.
 *
 * **Спрашивается здесь не профиль, а сводка первого экрана** (`useBootstrap`,
 * `GET /api/bootstrap`): тем же ответом приезжают модули, расход, пространства
 * и колокольчик, и к моменту, когда охрана пустит экраны рисоваться, они уже
 * лежат в кэше. Спрашивать сначала профиль, а сводку потом значило бы два
 * запроса на загрузку вместо одного; «кто вошёл» при этом решается той же
 * cookie и тем же кодом отказа, что и раньше.
 *
 * `RequireAdmin` — право админа. Прав нет — не «не найдено» и не пустой экран,
 * а честное «нет доступа» (обязательное состояние экрана).
 */
import type { ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router-dom'

import { useBootstrap, useIsAdmin } from '@/api/hooks'
import { ForbiddenState, SkeletonLines } from '@/ui'

function Waiting() {
  return (
    <div className="p-s5">
      <SkeletonLines count={4} />
    </div>
  )
}

export function RequireAuth({ children }: { children: ReactNode }) {
  const { data, isLoading } = useBootstrap()
  const location = useLocation()

  if (isLoading) return <Waiting />
  if (!data) {
    // Запоминаем, куда человек шёл: после входа вернём его туда, а не на
    // дашборд — иначе ссылка на конкретный отчёт из письма теряется.
    return (
      <Navigate to="/auth/login" replace state={{ from: location.pathname + location.search }} />
    )
  }
  return <>{children}</>
}

export function RequireAdmin({ children }: { children: ReactNode }) {
  const { isAdmin, isLoading } = useIsAdmin()

  if (isLoading || isAdmin === undefined) return <Waiting />
  if (!isAdmin) return <ForbiddenState />
  return <>{children}</>
}
