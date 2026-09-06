/**
 * TemplatesPanel — бланки работы: что приложено, чем собирается, что убрать.
 *
 * Стоит здесь, на странице отчётов работы, а не в профиле, потому что бланк
 * выбирают там, где им пользуются. Личная полка (`/settings/templates`) при
 * этом остаётся источником: приложить можно и уже загруженный файл, назвав его
 * из списка, — так пятая работа по тому же ГОСТу не заставляет искать файл на
 * диске в пятый раз.
 *
 * **Приложить и выбрать — разные действия.** У работы бланков бывает
 * несколько: титул кафедры, приложение, ГОСТ. Приложенный лежит про запас;
 * собирается работа по выбранному, и видно это пометкой в строке. Молча
 * выбирать за человека нельзя — это чужой ГОСТ в готовой работе.
 *
 * Смена выбранного перестраивает манифест: теги другие, а решения о прежних —
 * задания, типы, ограничения — переезжают, и значения остаются на месте. Об
 * этом сказано прямо в окне: человек должен понимать, чем он рискует, до
 * нажатия, а не по колонке тегов после.
 *
 * Тостов на удачу здесь нет (общее правило): приложенный бланк виден тем, что
 * появился в списке, а выбранный — пометкой.
 */
import { useState } from 'react'

import { useT } from '@/i18n'
import { cn } from '@/lib/cn'
import {
  Button,
  Chip,
  Dialog,
  EmptyState,
  ErrorState,
  Icon,
  Select,
  SkeletonLines,
  useToast,
} from '@/ui'
import { FileDrop } from '@/features/projects/FileDrop'
import {
  useAttachProjectTemplate,
  useDetachProjectTemplate,
  useProjectTemplates,
} from '@/features/projects/data'
import type { ReportTemplate } from '@/features/projects/types'
import { useTemplates } from '@/features/settings/templates'

import { useUseProjectTemplate } from './data'

/** Что принимает окно выбора файла. То же, что у диалога «Новая работа». */
const DOCX = '.docx,.dotx,application/vnd.openxmlformats-officedocument.wordprocessingml.document'

export function TemplatesPanel({
  projectId,
  report,
  canEdit,
}: {
  projectId: string
  /**
   * Отчёт работы, чей бланк выбирают. Список приложенных один на работу, а
   * пометка «по нему собирается» — у каждого отчёта своя.
   */
  report: string
  canEdit: boolean
}) {
  const t = useT()
  const toast = useToast()

  const list = useProjectTemplates(projectId, report)
  const shelf = useTemplates()
  const attach = useAttachProjectTemplate()
  const detach = useDetachProjectTemplate()
  const use = useUseProjectTemplate(projectId, report)

  const [file, setFile] = useState<File | null>(null)
  const [fromShelf, setFromShelf] = useState('')
  const [toUse, setToUse] = useState<ReportTemplate | null>(null)

  const приложенные = list.data ?? []
  // На полке предлагаем только то, чего в работе ещё нет: приложить дважды —
  // то же состояние, и пункт, который ничего не меняет, в списке лишний.
  const свободные = (shelf.data ?? []).filter((ш) => !приложенные.some((п) => п.id === ш.id))

  const приложить = async (тело: { file?: File | null; templateId?: string | null }) => {
    try {
      await attach.mutateAsync({ projectId, ...тело })
      setFile(null)
      setFromShelf('')
    } catch (e) {
      toast.fail(e)
    }
  }

  const выбрать = async () => {
    if (!toUse) return
    try {
      await use.mutateAsync({ templateId: toUse.id })
      setToUse(null)
    } catch (e) {
      toast.fail(e)
    }
  }

  return (
    <div className="flex flex-col gap-s4">
      {list.isPending ? (
        <SkeletonLines count={4} />
      ) : list.isError ? (
        <ErrorState error={list.error} onRetry={() => void list.refetch()} />
      ) : приложенные.length === 0 ? (
        <EmptyState
          compact
          title={t('reports.templates.empty')}
          text={t('reports.templates.emptyHint')}
        />
      ) : (
        <ul className="flex flex-col gap-s2">
          {приложенные.map((ш) => (
            <li
              key={ш.id}
              className={cn(
                'flex flex-wrap items-center gap-s3 rounded-sm border px-s3 py-s2',
                ш.active ? 'border-accent bg-accent-bg' : 'border-line bg-surface-2',
              )}
            >
              <Icon name="file" size={18} className="shrink-0 text-muted" />
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm font-medium text-ink-strong">{ш.name}</span>
                <span className="block truncate text-xs text-muted">
                  {t('reports.templates.tags', { n: ш.tags })}
                </span>
              </span>
              {ш.active ? (
                <Chip tone="accent">{t('reports.templates.active')}</Chip>
              ) : (
                canEdit && (
                  <Button
                    variant="secondary"
                    size="sm"
                    loading={use.isPending && use.variables?.templateId === ш.id}
                    onClick={() => setToUse(ш)}
                  >
                    {t('reports.templates.use')}
                  </Button>
                )
              )}
              {canEdit && (
                <Button
                  variant="ghost"
                  size="sm"
                  iconOnly
                  aria-label={t('reports.templates.detach', { name: ш.name })}
                  onClick={() =>
                    detach.mutate(
                      { projectId, templateId: ш.id },
                      { onError: (e) => toast.fail(e) },
                    )
                  }
                >
                  <Icon name="trash" size={16} />
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}

      {canEdit && (
        <div className="flex flex-col gap-s3 border-t border-line pt-s3">
          {file ? (
            <div className="flex items-center gap-s2 rounded-sm border border-line bg-surface-2 px-s3 py-s2">
              <Icon name="file" size={16} className="shrink-0 text-muted" />
              <span className="min-w-0 flex-1 truncate text-sm text-ink">{file.name}</span>
              <Button
                variant="ghost"
                size="sm"
                iconOnly
                aria-label={t('reports.templates.dropLabel')}
                onClick={() => setFile(null)}
              >
                <Icon name="close" size={16} />
              </Button>
            </div>
          ) : (
            <FileDrop
              accept={DOCX}
              label={t('reports.templates.dropLabel')}
              hint={t('reports.templates.dropHint')}
              onFiles={(files) => setFile(files[0] ?? null)}
            />
          )}
          <div className="flex flex-wrap items-center gap-s2">
            <Button
              variant="primary"
              size="sm"
              disabled={!file}
              loading={attach.isPending && !!file}
              onClick={() => void приложить({ file })}
            >
              {t('reports.templates.attachFile')}
            </Button>
            <span className="text-xs text-muted">{t('reports.templates.or')}</span>
            <Select
              aria-label={t('reports.templates.fromShelf')}
              value={fromShelf}
              className="w-auto min-w-[200px]"
              onChange={(e) => setFromShelf(e.target.value)}
            >
              <option value="">{t('reports.templates.fromShelf')}</option>
              {свободные.map((ш) => (
                <option key={ш.id} value={ш.id}>
                  {ш.name}
                </option>
              ))}
            </Select>
            <Button
              variant="secondary"
              size="sm"
              disabled={!fromShelf}
              loading={attach.isPending && !!fromShelf}
              onClick={() => void приложить({ templateId: fromShelf })}
            >
              {t('reports.templates.attachShelf')}
            </Button>
          </div>
        </div>
      )}

      <Dialog
        open={!!toUse}
        onOpenChange={(open) => !open && setToUse(null)}
        title={t('reports.templates.useTitle', { name: toUse?.name ?? '' })}
        description={t('reports.templates.useHint')}
        footer={
          <>
            <Button variant="ghost" onClick={() => setToUse(null)}>
              {t('common.action.cancel')}
            </Button>
            <Button variant="primary" loading={use.isPending} onClick={() => void выбрать()}>
              {t('reports.templates.use')}
            </Button>
          </>
        }
      >
        <p className="text-sm text-muted">{t('reports.templates.useKeeps')}</p>
      </Dialog>
    </div>
  )
}
