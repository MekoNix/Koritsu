/**
 * useIsAdmin — пускать ли в `/admin`.
 *
 * Ответ один и берётся из профиля: `GET /api/auth/me` отдаёт `is_admin`
 * (`packages/api/accounts/routes.py: профиль()`, колонка `users.is_admin`).
 *
 * Правом это поле не заведует. Доступ решают админские маршруты — они
 * проверяют ту же колонку и отвечают `403 forbidden` кому угодно с любым
 * флагом в браузере, — и белый список адресов на прокси. Здесь оно нужно
 * только затем, чтобы не рисовать человеку страницу, за которую всё равно
 * откажут.
 */
import { useMe } from './useMe'

export type AdminState = {
  /** `undefined` — профиль ещё не приехал. */
  isAdmin: boolean | undefined
  isLoading: boolean
}

export function useIsAdmin(): AdminState {
  const me = useMe()
  if (me.isLoading) return { isAdmin: undefined, isLoading: true }
  return { isAdmin: me.data?.is_admin ?? false, isLoading: false }
}
