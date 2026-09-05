/**
 * RenameProjectDialog — переименование работы.
 *
 * Отдельным диалогом, а не правкой имени прямо в строке: имя уезжает и в базу,
 * и в `project.json` на томе одним запросом, и «сохранилось ли» человеку надо
 * показать — в строке списка для этого нет места.
 *
 * Открытость определяется наличием проекта (`project !== null`), а не вторым
 * флагом: два источника одного состояния однажды разойдутся, и окно откроется
 * пустым.
 */
import { useEffect, useState } from 'react'

import { errorText } from '@/api'
import { useT } from '@/i18n'
import { Button, Dialog, Input } from '@/ui'

import { useRenameProject } from './data'
import type { Project } from './types'

export function RenameProjectDialog({
  project,
  onClose,
}: {
  project: Project | null
  onClose: () => void
}) {
  const t = useT()
  const [name, setName] = useState('')
  const rename = useRenameProject()

  // Имя подставляется при каждом открытии: окно живёт дольше одной работы.
  useEffect(() => {
    if (project) setName(project.name)
  }, [project])

  const close = () => {
    rename.reset()
    onClose()
  }

  const submit = () => {
    const next = name.trim()
    if (!project || !next) return
    rename.mutate({ id: project.id, name: next }, { onSuccess: close })
  }

  return (
    <Dialog
      open={!!project}
      onOpenChange={(open) => !open && close()}
      title={t('projects.rename.title')}
      footer={
        <>
          <Button variant="ghost" onClick={close}>
            {t('common.action.cancel')}
          </Button>
          <Button
            variant="primary"
            onClick={submit}
            loading={rename.isPending}
            disabled={!name.trim()}
          >
            {t('common.action.save')}
          </Button>
        </>
      }
    >
      <form
        onSubmit={(event) => {
          event.preventDefault()
          submit()
        }}
      >
        <Input
          label={t('projects.create.name')}
          value={name}
          autoFocus
          maxLength={200}
          onChange={(event) => setName(event.target.value)}
          error={rename.isError ? errorText(rename.error) : undefined}
        />
      </form>
    </Dialog>
  )
}
