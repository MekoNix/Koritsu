/**
 * CreateProjectDialog — «Новая работа»: имя и, если он есть, шаблон DOCX.
 *
 * Шаблон необязателен, и это не мелочь интерфейса, а то, как устроена служба:
 * `POST /api/projects` принимает `template` пустым, и тогда документ строится
 * с нуля. Человек, у которого образца под рукой нет, обязан завести работу без
 * него — поэтому кнопка «Создать» активна и с пустым приёмником.
 *
 * Ошибка приходит кодом (`bad_template` — файл не читается как DOCX), и текст
 * ей даёт общий словарь отказов; своего перевода здесь нет.
 */
import { useState } from 'react'

import { errorText } from '@/api'
import { useT } from '@/i18n'
import { Button, Dialog, Icon, Input } from '@/ui'

import { FileDrop } from './FileDrop'
import { useCreateProject } from './data'
import { formatBytes } from './format'

export type CreateProjectDialogProps = {
  open: boolean
  onOpenChange: (open: boolean) => void
  workspaceId: string | undefined
  /** Куда идти после создания. */
  onCreated: (projectId: string) => void
}

const DOCX = '.docx,.dotx,application/vnd.openxmlformats-officedocument.wordprocessingml.document'

export function CreateProjectDialog({
  open,
  onOpenChange,
  workspaceId,
  onCreated,
}: CreateProjectDialogProps) {
  const t = useT()
  const [name, setName] = useState('')
  const [template, setTemplate] = useState<File | null>(null)
  const create = useCreateProject()

  const close = () => {
    onOpenChange(false)
    setName('')
    setTemplate(null)
    create.reset()
  }

  const submit = () => {
    if (!workspaceId) return
    create.mutate(
      { workspaceId, name: name.trim() || t('projects.create.defaultName'), template },
      {
        onSuccess: (project) => {
          close()
          onCreated(project.id)
        },
      },
    )
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => (next ? onOpenChange(true) : close())}
      title={t('projects.create.title')}
      description={t('projects.create.hint')}
      footer={
        <>
          <Button variant="ghost" onClick={close}>
            {t('common.action.cancel')}
          </Button>
          <Button
            variant="primary"
            onClick={submit}
            loading={create.isPending}
            disabled={!workspaceId}
          >
            {t('common.action.create')}
          </Button>
        </>
      }
    >
      <form
        className="flex flex-col gap-s4"
        onSubmit={(event) => {
          event.preventDefault()
          submit()
        }}
      >
        <Input
          label={t('projects.create.name')}
          placeholder={t('projects.create.namePlaceholder')}
          value={name}
          autoFocus
          maxLength={200}
          onChange={(event) => setName(event.target.value)}
        />

        <div className="flex flex-col gap-1.5">
          <span className="text-sm font-medium text-ink">{t('projects.create.template')}</span>
          {template ? (
            <div className="flex items-center gap-s2 rounded-md border border-line bg-surface-2 px-s3 py-s2">
              <Icon name="file" size={18} className="text-muted" />
              <span className="min-w-0 flex-1 truncate text-sm text-ink">{template.name}</span>
              <span className="shrink-0 text-xs text-muted">{formatBytes(t, template.size)}</span>
              <Button
                variant="ghost"
                size="sm"
                iconOnly
                aria-label={t('projects.create.templateDrop')}
                onClick={() => setTemplate(null)}
              >
                <Icon name="close" size={16} />
              </Button>
            </div>
          ) : (
            <FileDrop
              accept={DOCX}
              label={t('projects.create.templateDrop')}
              hint={t('projects.create.templateHint')}
              onFiles={(files) => setTemplate(files[0] ?? null)}
            />
          )}
          <p className="text-xs text-muted">{t('projects.create.templateOptional')}</p>
        </div>

        {create.isError && (
          <p role="alert" className="text-sm text-err">
            {errorText(create.error)}
          </p>
        )}
      </form>
    </Dialog>
  )
}
