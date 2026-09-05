/**
 * Формы ответов службы, которыми пользуется область «Пространство».
 *
 * Своим файлом, как велит `api/README.md`: общий `api/types.ts` описывает то,
 * что нужно оболочке, и складывать туда формы каждой области значило бы
 * собрать в одном месте половину договора службы.
 */

/** `packages/api/workspaces/routes.py: участники()`. */
export type Member = {
  user_id: string
  /**
   * Ник участника — то, чем его зовут на экране.
   * `null` — по той же причине, что и у почты: строка, оставшаяся от стёртого
   * аккаунта.
   */
  nickname: string | null
  /**
   * Почта участника. `null` бывает у аккаунта, стёртого из `users` мимо
   * каскада; такую строку показываем идентификатором, а не пустотой.
   */
  email: string | null
  /** `owner` | `editor` | `viewer`. */
  role: string
  /**
   * `active` — участник, `pending` — позван и ещё не ответил на приглашение.
   * Приглашение не зачисляет: пока человек не нажал «принять», пространства он
   * не видит, а владелец видит его строку помеченной.
   */
  status: string
  created_at: string
}

/** Ответ `POST …/members` и `PATCH …/members/{id}`. */
export type MemberChanged = {
  user_id: string
  role: string
  /** У приглашения — `pending`; смена роли состояния не трогает. */
  status?: string
}

/** Состояния участия (`packages/api/workspaces/service.py: STATUSES`). */
export const MEMBER_ACTIVE = 'active'
export const MEMBER_PENDING = 'pending'

/** Роли по убыванию прав (`packages/api/workspaces/service.py: ROLES`). */
export const ROLES = ['owner', 'editor', 'viewer'] as const
export type Role = (typeof ROLES)[number]

/** Участников меняет только владелец пространства. */
export function canManageMembers(role: string | undefined): boolean {
  return role === 'owner'
}

/**
 * Запасное имя личного пространства, которое даёт служба
 * строкам, заведённым до того, как у аккаунта появился ник
 * (`workspaces/service.py: PERSONAL_NAME`). Обычное имя личного пространства —
 * `<ник>-workspace`, и его показывают как есть; сюда попадают только старые
 * строки, и вместо этого слова экран пишет ник хозяина.
 */
const PERSONAL_NAME = 'Personal'

/**
 * Как пространство называется на экране. Переименованное личное показывается
 * так, как его назвал человек: перевод подставляется только вместо имени,
 * данного службой.
 */
export function workspaceLabel(
  ws: { name: string; personal: boolean },
  personalText: string,
): string {
  return ws.personal && ws.name === PERSONAL_NAME ? personalText : ws.name
}
