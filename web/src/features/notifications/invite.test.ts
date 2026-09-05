/**
 * Разбор приглашения из уведомления.
 *
 * Проверяется ровно то, чем приглашение отличается от прочих строк
 * колокольчика: у него есть куда отвечать. Строка без `workspace_id` —
 * не приглашение, а мусор, и кнопок ей не положено: нажатие ушло бы в никуда.
 */
import { describe, expect, it } from 'vitest'

import { inviteOf } from './invite'

const ПОЛНОЕ = {
  kind: 'workspace_invite',
  data: {
    workspace_id: 'ws-1',
    workspace_name: 'Кафедра ИУ7',
    role: 'editor',
    from_nickname: 'kurisu',
  },
}

describe('inviteOf', () => {
  it('разбирает приглашение целиком', () => {
    expect(inviteOf(ПОЛНОЕ)).toEqual({
      workspaceId: 'ws-1',
      workspaceName: 'Кафедра ИУ7',
      role: 'editor',
      fromNickname: 'kurisu',
    })
  })

  it('чужой вид уведомления приглашением не считает', () => {
    expect(inviteOf({ kind: 'job_done', data: { workspace_id: 'ws-1' } })).toBeNull()
  })

  it('без пространства кнопок не будет: отвечать некуда', () => {
    expect(inviteOf({ kind: 'workspace_invite', data: { workspace_name: 'Кафедра' } })).toBeNull()
  })

  it('вместо пропавшего имени показывает идентификатор, а не пустоту', () => {
    const разбор = inviteOf({ kind: 'workspace_invite', data: { workspace_id: 'ws-2' } })
    expect(разбор).toEqual({
      workspaceId: 'ws-2',
      workspaceName: 'ws-2',
      role: 'viewer',
      fromNickname: null,
    })
  })
})
