/**
 * guards — кто куда пускается.
 *
 * Два правила, и оба проверяются ещё раз на службе. Здесь они нужны не ради
 * безопасности (её обеспечивает служба), а ради того, чтобы человек не видел
 * мигающий пустой экран перед отказом.
 *
 * `RequireAuth` — сессия. Пока профиль не приехал, показывается скелетон, а не
 * редирект: иначе перезагрузка любой внутренней страницы выкидывала бы на вход
 * на долю секунды даже вошедшего.
 *
 * `RequireAdmin` — право админа. Прав нет — не «не найдено» и не пустой экран,
 * а честное «нет доступа» (обязательное состояние экрана).
 */
import type { ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router-dom'

import { useIsAdmin, useMe } from '@/api/hooks'
import { ForbiddenState, SkeletonLines } from '@/ui'

function Waiting() {
  return (
    <div className="p-s5">
      <SkeletonLines count={4} />
    </div>
  )
}

export function RequireAuth({ children }: { children: ReactNode }) {
  const { data: me, isLoading } = useMe()
  const location = useLocation()

  if (isLoading) return <Waiting />
  if (!me) {
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
