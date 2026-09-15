/**
 * SetDialogs — переименование и удаление набора (редактор).
 *
 * Удаление подтверждается своим окном, а не `confirm()` браузера: окно называет набор
 * по имени и напоминает, что он пропадёт у всех участников пространства, — и что файл
 * можно заранее скачать.
 */
import { useEffect, useState } from 'react'

import { errorText } from '@/api'
import { useT } from '@/i18n'
import { Button, Input, Textarea } from '@/ui'

import { useDeleteCardSet, useUpdateCardSet } from '../api'
import { AdaptiveDialog } from './Sheet'

type Общие = {
  open: boolean
  onOpenChange: (open: boolean) => void
  projectId: string
  setId: string
  title: string
}

export function RenameDialog({ open, onOpenChange, projectId, setId, title, description }: Общие & { description: string }) {
  const t = useT()
  const update = useUpdateCardSet()
  const { reset } = update
  const [имя, setИмя] = useState(title)
  const [описание, setОписание] = useState(description)

  useEffect(() => {
    if (!open) return
    setИмя(title)
    setОписание(description)
    reset()
  }, [open, title, description, reset])

  const сохранить = () => {
    if (!имя.trim()) return
    update.mutate(
      { projectId, setId, title: имя.trim(), description: описание.trim() },
      { onSuccess: () => onOpenChange(false) },
    )
  }

  return (
    <AdaptiveDialog
      open={open}
      onOpenChange={onOpenChange}
      title={t('cards.set.renameTitle')}
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            {t('cards.common.cancel')}
          </Button>
          <Button variant="primary" loading={update.isPending} disabled={!имя.trim()} onClick={сохранить}>
            {t('cards.set.save')}
          </Button>
        </>
      }
    >
      <form
        className="flex flex-col gap-s4"
        onSubmit={(e) => {
          e.preventDefault()
          сохранить()
        }}
      >
        <Input
          label={t('cards.set.name')}
          value={имя}
          maxLength={200}
          className="max-[640px]:min-h-[44px] max-[640px]:text-md"
          onChange={(e) => setИмя(e.target.value)}
        />
        <Textarea
          label={t('cards.set.description')}
          value={описание}
          rows={3}
          maxLength={2000}
          className="max-[640px]:text-md"
          onChange={(e) => setОписание(e.target.value)}
        />
        {update.isError && <p className="m-0 text-sm text-err">{errorText(update.error)}</p>}
      </form>
    </AdaptiveDialog>
  )
}

export function DeleteDialog({ open, onOpenChange, projectId, setId, title, onDeleted }: Общие & { onDeleted: () => void }) {
  const t = useT()
  const remove = useDeleteCardSet()
  const { reset } = remove

  useEffect(() => {
    if (open) reset()
  }, [open, reset])

  return (
    <AdaptiveDialog
      open={open}
      onOpenChange={onOpenChange}
      title={t('cards.set.deleteTitle', { name: title })}
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            {t('cards.common.cancel')}
          </Button>
          <Button
            variant="danger"
            loading={remove.isPending}
            onClick={() => remove.mutate({ projectId, setId }, { onSuccess: onDeleted })}
          >
            {t('cards.set.deleteConfirm')}
          </Button>
        </>
      }
    >
      <p className="m-0 text-sm text-muted">{t('cards.set.deleteHint')}</p>
      {remove.isError && <p className="mt-s3 text-sm text-err">{errorText(remove.error)}</p>}
    </AdaptiveDialog>
  )
}
