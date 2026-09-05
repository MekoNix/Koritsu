/**
 * CreateProjectDialog — «Новая работа»: имя и, если он есть, шаблон DOCX.
 *
 * Шаблон необязателен, и это не мелочь интерфейса, а то, как устроена служба:
 * `POST /api/projects` принимает `template` пустым, и тогда документ строится
 * с нуля. Человек, у которого образца под рукой нет, обязан завести работу без
 * него — поэтому кнопка «Создать» активна и с пустым приёмником.
 *
 * **Шаблон берётся из двух мест, и одновременно они не работают.** У
 * человека есть свои сохранённые шаблоны (`/settings/templates`), и чаще всего
 * нужен именно один из них: тот же ГОСТ на десятой работе подряд. Файл при
 * этом никуда не делся — им пользуются, когда шаблон принесли впервые. Служба
 * принимает либо файл, либо `template_id` и на оба сразу отвечает отказом,
 * поэтому выбор здесь один на двоих: взяли файл — выбранный шаблон снимается, и
 * наоборот. Молча выбранный за человека шаблон — это чужой ГОСТ в готовой
 * работе, и замечают его на кафедре.
 *
 * Ошибка приходит кодом (`bad_template` — файл не читается как DOCX), и текст
 * ей даёт общий словарь отказов; своего перевода здесь нет.
 */
import { useState } from 'react'

import { errorText } from '@/api'
import { useT } from '@/i18n'
import { Button, Dialog, Icon, Input, Select } from '@/ui'
import { useTemplates } from '@/features/settings/templates'

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
  const [templateId, setTemplateId] = useState('')
  // Спрашиваем список только когда окно открыто: диалог смонтирован всегда.
  const templates = useTemplates(open)
  const create = useCreateProject()

  const close = () => {
    onOpenChange(false)
    setName('')
    setTemplate(null)
    setTemplateId('')
    create.reset()
  }

  const submit = () => {
    if (!workspaceId) return
    create.mutate(
      {
        workspaceId,
        name: name.trim() || t('projects.create.defaultName'),
        template,
        templateId,
      },
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

          {/* Свои шаблоны показываются, только если они есть: пустой список с
              одним пунктом «—» ничего не объясняет и место занимает. */}
          {(templates.data?.length ?? 0) > 0 && (
            <Select
              label={t('projects.create.templateSaved')}
              hint={t('projects.create.templateSavedHint')}
              value={templateId}
              onChange={(event) => {
                setTemplateId(event.target.value)
                // Выбрали сохранённый — принесённый файл снимается: служба
                // принимает что-то одно.
                if (event.target.value) setTemplate(null)
              }}
            >
              <option value="">{t('projects.create.templateNone')}</option>
              {templates.data?.map((шаблон) => (
                <option key={шаблон.id} value={шаблон.id}>
                  {шаблон.name} · {t('settings.templates.tags', { count: шаблон.tags })}
                </option>
              ))}
            </Select>
          )}

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
              onFiles={(files) => {
                setTemplate(files[0] ?? null)
                // Принесли файл — выбранный сохранённый снимается (см. заголовок).
                if (files[0]) setTemplateId('')
              }}
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
