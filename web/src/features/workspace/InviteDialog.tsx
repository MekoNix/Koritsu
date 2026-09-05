/**
 * InviteDialog — позвать человека в пространство по почте.
 *
 * Приглашение по почте, а не по идентификатору (решение владельца и довод
 * службы): чужой uuid человеку неоткуда взять, а почту коллеги он знает.
 *
 * **Писем служба не шлёт** (§11): приглашение — это сразу участие. Поэтому у
 * почты, которой в службе нет, отказ `no_such_user`, и текст его говорит
 * правду — «такого человека нет, пусть сперва заведёт аккаунт», а не
 * «приглашение отправлено».
 *
 * Отказ садится в поле почты, а не в тост: служба называет место (`where`:
 * `body.email`) у всех трёх своих отказов (`no_such_user`, `already_member`,
 * `unknown_role`), и человеку править надо именно это поле.
 */
import { useState } from 'react'

import { ApiError, errorText } from '@/api'
import { useT } from '@/i18n'
import { Button, Dialog, Input, Select } from '@/ui'

import { useAddMember } from './data'
import { ROLES } from './types'

export function InviteDialog({
  open,
  onOpenChange,
  workspaceId,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  workspaceId: string
}) {
  const t = useT()
  const add = useAddMember()
  const [email, setEmail] = useState('')
  const [role, setRole] = useState<string>('editor')
  const [error, setError] = useState<string | undefined>(undefined)

  const закрыть = (open: boolean) => {
    if (!open) {
      setEmail('')
      setError(undefined)
    }
    onOpenChange(open)
  }

  const позвать = () => {
    const почта = email.trim()
    if (!почта) {
      setError(t('workspace.invite.required'))
      return
    }
    setError(undefined)
    add.mutate(
      { id: workspaceId, email: почта, role },
      {
        onSuccess: () => закрыть(false),
        // Место отказа служба называет сама; своего разбора кодов здесь нет —
        // русский текст даёт общий словарь по коду.
        onError: (беда) => setError(беда instanceof ApiError ? беда.text : errorText(беда)),
      },
    )
  }

  return (
    <Dialog
      open={open}
      onOpenChange={закрыть}
      title={t('workspace.invite.title')}
      description={t('workspace.invite.desc')}
      footer={
        <>
          <Button variant="ghost" onClick={() => закрыть(false)}>
            {t('workspace.cancel')}
          </Button>
          <Button variant="primary" loading={add.isPending} onClick={позвать}>
            {t('workspace.invite.submit')}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-s3">
        <Input
          label={t('workspace.invite.email')}
          type="email"
          autoComplete="off"
          value={email}
          error={error}
          onChange={(e) => setEmail(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') позвать()
          }}
          placeholder="coworker@example.org"
        />
        <Select
          label={t('workspace.invite.role')}
          value={role}
          onChange={(e) => setRole(e.target.value)}
          hint={t(`workspace.roleHint.${role}`)}
        >
          {ROLES.map((r) => (
            <option key={r} value={r}>
              {t(`workspace.role.${r}`)}
            </option>
          ))}
        </Select>
      </div>
    </Dialog>
  )
}
