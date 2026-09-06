/**
 * TemplatesSection — свои шаблоны отчётов (`/settings/templates`).
 *
 * Зачем раздел вообще есть. Раньше шаблон существовал только внутри работы:
 * DOCX приносили телом создания проекта, служба клала его артефактом и
 * забывала. Человек, заводящий пятую работу по тому же ГОСТу, искал один и тот
 * же файл в пятый раз. Теперь шаблон принадлежит человеку (`/api/templates`) и
 * выбирается в диалоге «Новая работа» одним щелчком.
 *
 * Что показывается в строке и почему именно это: имя (его человек и написал),
 * **число тегов** и размер. Число тегов — главное: по нему шаблон узнают, когда
 * имена похожи («ГОСТ 2026» и «ГОСТ 2026 испр.»), и считает его служба тем же
 * разбором, которым строится манифест работы, — то есть в заведённой по нему
 * работе тегов будет ровно столько же.
 *
 * Удаление спрашивает подтверждение, но пугать не должно: работы, заведённые
 * по этому шаблону, целы — байты копируются в проект, а не берутся по ссылке.
 * Ровно это и написано в окне.
 *
 * Тостов на удачу здесь нет (общее правило о тостах): загруженный шаблон
 * виден тем, что появился в списке.
 */
import { useState } from 'react'

import { useT } from '@/i18n'
import {
  Button,
  Card,
  Chip,
  Dialog,
  EmptyState,
  ErrorState,
  Icon,
  Input,
  SkeletonLines,
  useToast,
} from '@/ui'
import { FileDrop } from '@/features/projects/FileDrop'

import { formatBytes, formatDate } from './format'
import { templateUrl, useDeleteTemplate, useTemplates, useUploadTemplate } from './templates'
import type { ReportTemplate } from './types'

/** Что принимает окно выбора файла. То же, что у диалога «Новая работа». */
const DOCX = '.docx,.dotx,application/vnd.openxmlformats-officedocument.wordprocessingml.document'

export function TemplatesSection() {
  const t = useT()
  const toast = useToast()
  const list = useTemplates()
  const upload = useUploadTemplate()
  const remove = useDeleteTemplate()

  const [file, setFile] = useState<File | null>(null)
  const [name, setName] = useState('')
  const [toDelete, setToDelete] = useState<ReportTemplate | null>(null)

  const отправить = async () => {
    if (!file) return
    try {
      await upload.mutateAsync({ file, name: name.trim() })
      setFile(null)
      setName('')
    } catch (e) {
      toast.fail(e)
    }
  }

  const удалить = async () => {
    if (!toDelete) return
    try {
      await remove.mutateAsync(toDelete.id)
      setToDelete(null)
    } catch (e) {
      toast.fail(e)
    }
  }

  return (
    <>
      <Card title={t('settings.templates.title')} desc={t('settings.templates.text')}>
        {list.isLoading && <SkeletonLines count={3} />}
        {list.error && <ErrorState error={list.error} onRetry={() => void list.refetch()} />}

        {list.data && list.data.length === 0 && (
          <EmptyState
            compact
            icon="file"
            title={t('settings.templates.empty')}
            text={t('settings.templates.emptyHint')}
          />
        )}

        {list.data && list.data.length > 0 && (
          <ul className="flex flex-col gap-s2">
            {list.data.map((шаблон) => (
              <li
                key={шаблон.id}
                className="flex flex-wrap items-center gap-s3 rounded-sm border border-line bg-surface-2 px-s3 py-s2"
              >
                <Icon name="file" size={18} className="text-muted" />
                <span className="min-w-0 flex-1 truncate font-semibold text-ink-strong">
                  {шаблон.name}
                </span>
                <Chip tone="accent">{t('settings.templates.tags', { count: шаблон.tags })}</Chip>
                <span className="text-xs text-muted">{formatBytes(шаблон.bytes)}</span>
                <span className="text-xs text-muted">{formatDate(шаблон.created_at)}</span>
                {/* Скачивание — обычной ссылкой: имя файла браузер возьмёт из
                    заголовка ответа, а cookie сессии уедет сама. */}
                <a
                  href={templateUrl(шаблон.id)}
                  className="text-sm text-accent no-underline hover:underline"
                >
                  {t('settings.templates.download')}
                </a>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setToDelete(шаблон)}
                  aria-label={`${t('settings.templates.delete')} ${шаблон.name}`}
                >
                  <Icon name="trash" size={16} />
                  {t('settings.templates.delete')}
                </Button>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Card title={t('settings.templates.add')} desc={t('settings.templates.addHint')}>
        <form
          className="flex flex-col gap-s3"
          onSubmit={(event) => {
            event.preventDefault()
            void отправить()
          }}
        >
          {file ? (
            <div className="flex items-center gap-s2 rounded-md border border-line bg-surface-2 px-s3 py-s2">
              <Icon name="file" size={18} className="text-muted" />
              <span className="min-w-0 flex-1 truncate text-sm text-ink">{file.name}</span>
              <span className="shrink-0 text-xs text-muted">{formatBytes(file.size)}</span>
              <Button
                variant="ghost"
                size="sm"
                iconOnly
                aria-label={t('settings.templates.drop')}
                onClick={() => setFile(null)}
              >
                <Icon name="close" size={16} />
              </Button>
            </div>
          ) : (
            <FileDrop
              accept={DOCX}
              label={t('settings.templates.drop')}
              hint={t('settings.templates.dropHint')}
              onFiles={(files) => setFile(files[0] ?? null)}
            />
          )}

          <Input
            label={t('settings.templates.name')}
            hint={t('settings.templates.nameHint')}
            placeholder={t('settings.templates.namePlaceholder')}
            maxLength={120}
            value={name}
            onChange={(event) => setName(event.target.value)}
          />

          <Button
            type="submit"
            variant="primary"
            className="self-start"
            loading={upload.isPending}
            disabled={!file}
          >
            <Icon name="plus" size={16} />
            {t('settings.templates.add')}
          </Button>
        </form>
      </Card>

      <Dialog
        open={toDelete !== null}
        onOpenChange={(open) => !open && setToDelete(null)}
        title={t('settings.templates.deleteTitle')}
        footer={
          <>
            <Button variant="ghost" onClick={() => setToDelete(null)}>
              {t('common.action.cancel')}
            </Button>
            <Button variant="danger" loading={remove.isPending} onClick={() => void удалить()}>
              {t('settings.templates.delete')}
            </Button>
          </>
        }
      >
        <p className="text-sm text-ink">
          {t('settings.templates.deleteText', { name: toDelete?.name ?? '' })}
        </p>
      </Dialog>
    </>
  )
}
