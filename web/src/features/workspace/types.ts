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
  created_at: string
}

/** Ответ `POST …/members` и `PATCH …/members/{id}`. */
export type MemberChanged = {
  user_id: string
  role: string
}

/** Роли по убыванию прав (`packages/api/workspaces/service.py: ROLES`). */
export const ROLES = ['owner', 'editor', 'viewer'] as const
export type Role = (typeof ROLES)[number]

/** Участников меняет только владелец пространства. */
export function canManageMembers(role: string | undefined): boolean {
  return role === 'owner'
}

/**
 * Имя личного пространства, которое даёт служба
 * (`workspaces/service.py: PERSONAL_NAME`). По-английски намеренно: «наружу
 * служба говорит по-английски, а перевод „Личное“ сделает интерфейс — он же
 * знает флаг `personal`». Вот он и делает.
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
