/**
 * invite — приглашение в рабочее пространство, каким его видит колокольчик.
 *
 * Приглашение приходит обычным уведомлением (`kind === 'workspace_invite'`), но
 * ведёт себя иначе всех прочих: это не весть о случившемся, а дело с двумя
 * кнопками — «принять» и «отклонить». Пока человек не ответил, пространства для
 * него не существует: служба не считает его участником
 * (`packages/api/workspaces/service.py`), и спросить у неё имя приглашающего
 * пространства он не может. Поэтому всё нужное лежит в самом уведомлении, а
 * разбор `data` — здесь, в одном месте на оба списка (колокольчик и виджет
 * дашборда).
 *
 * Что кладёт служба (`notifications/service.py: пригласили`):
 *
 *     workspace_id, workspace_name, role, from_nickname
 *
 * Без `workspace_id` строка не приглашение, а мусор: отвечать некуда. Такая
 * строка показывается обычным уведомлением без кнопок — то же правило, что и у
 * ссылки в никуда.
 */
import type { Notification } from '@/api/types'

/** Вид уведомления о приглашении (`notifications/service.py: WORKSPACE_INVITE`). */
export const WORKSPACE_INVITE = 'workspace_invite'

export type Invite = {
  workspaceId: string
  /** Имя пространства: своего запроса за ним у приглашённого нет. */
  workspaceName: string
  /** Предложенная роль: `owner` | `editor` | `viewer`. */
  role: string
  /** Ник позвавшего; пусто у строки, оставшейся от стёртого аккаунта. */
  fromNickname: string | null
}

function строка(data: Record<string, unknown> | undefined, поле: string): string | null {
  const значение = data?.[поле]
  return typeof значение === 'string' && значение ? значение : null
}

/** Приглашение из уведомления или `null`, если это не оно. */
export function inviteOf(item: Pick<Notification, 'kind' | 'data'>): Invite | null {
  if (item.kind !== WORKSPACE_INVITE) return null
  const workspaceId = строка(item.data, 'workspace_id')
  if (!workspaceId) return null
  return {
    workspaceId,
    workspaceName: строка(item.data, 'workspace_name') ?? workspaceId,
    role: строка(item.data, 'role') ?? 'viewer',
    fromNickname: строка(item.data, 'from_nickname'),
  }
}
