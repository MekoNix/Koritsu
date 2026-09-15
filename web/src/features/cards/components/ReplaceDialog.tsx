/**
 * ReplaceDialog — заменить набор новым файлом.
 *
 * Сначала превью: проблемы по строкам и что изменится — «+12 новых · 3 изменены ·
 * 2 удалены». Карточки сопоставляются по id, а без id — по тексту вопроса; у совпавших
 * прогресс остаётся, у изменённых — с пометкой «вопрос изменился». Заменить молча часть
 * файла нельзя: либо весь файл, либо явно «только годными (N из M)».
 */
import { useEffect } from 'react'

import { errorText } from '@/api'
import { useT } from '@/i18n'
import { Button, Chip, ErrorState, Icon, SkeletonLines } from '@/ui'

import { useReplacePreview, useReplaceSet } from '../api'
import { diffCount, hasFileProblems, validOf } from '../types'
import { ProblemsTable } from './ProblemsTable'
import { AdaptiveDialog } from './Sheet'
import { SourcePicker } from './SourcePicker'

export type ReplaceDialogProps = {
  open: boolean
  onOpenChange: (open: boolean) => void
  projectId: string
  setId: string
}

export function ReplaceDialog({ open, onOpenChange, projectId, setId }: ReplaceDialogProps) {
  const t = useT()
  const preview = useReplacePreview()
  const replace = useReplaceSet()
  const { reset: сброситьПревью } = preview
  const { reset: сброситьЗамену } = replace

  useEffect(() => {
    if (!open) {
      сброситьПревью()
      сброситьЗамену()
    }
  }, [open, сброситьПревью, сброситьЗамену])

  const data = preview.data
  const проблемы = data?.problems ?? []
  const числа = validOf(data?.stats)
  const файловые = hasFileProblems(проблемы)
  const можноВсё = !!data && проблемы.length === 0
  const можноГодные = !!data && проблемы.length > 0 && !файловые && (числа ? числа.valid > 0 : true)

  const заменить = (onlyValid: boolean) => {
    if (!data) return
    replace.mutate({ projectId, setId, draftId: data.draft_id, onlyValid }, { onSuccess: () => onOpenChange(false) })
  }

  return (
    <AdaptiveDialog
      open={open}
      onOpenChange={onOpenChange}
      size="lg"
      title={t('cards.set.replaceTitle')}
      description={t('cards.set.replaceHint')}
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            {t('cards.common.cancel')}
          </Button>
          {можноВсё && (
            <Button variant="primary" loading={replace.isPending} onClick={() => заменить(false)}>
              <Icon name="refresh" size={16} />
              {t('cards.set.replaceConfirm')}
            </Button>
          )}
          {можноГодные && (
            <Button variant="primary" loading={replace.isPending} onClick={() => заменить(true)}>
              {числа ? t('cards.set.replaceValid', { valid: числа.valid, total: числа.total }) : t('cards.set.replaceValidShort')}
            </Button>
          )}
        </>
      }
    >
      <div className="flex min-w-0 flex-col gap-s4">
        <SourcePicker busy={preview.isPending} onSource={(s) => preview.mutate({ projectId, setId, ...s })} />
        {preview.isPending && <SkeletonLines count={3} />}
        {preview.isError && <ErrorState error={preview.error} />}
        {data && !preview.isPending && (
          <div aria-live="polite" className="flex flex-col gap-s3">
            <div className="flex flex-wrap items-center gap-s2">
              <Chip tone="ok">{t('cards.set.diffAdded', { n: diffCount(data.diff?.added) })}</Chip>
              <Chip tone="info">{t('cards.set.diffChanged', { n: diffCount(data.diff?.changed) })}</Chip>
              <Chip tone="err">{t('cards.set.diffRemoved', { n: diffCount(data.diff?.removed) })}</Chip>
            </div>
            {проблемы.length === 0 ? (
              <p className="m-0 text-sm text-ok">{t('cards.upload.ok')}</p>
            ) : (
              <>
                <p className="m-0 text-sm text-muted">
                  {файловые ? t('cards.upload.fileProblems') : числа?.valid === 0 ? t('cards.upload.noneValid') : t('cards.upload.fixHint')}
                </p>
                <ProblemsTable problems={проблемы} />
              </>
            )}
          </div>
        )}
        {replace.isError && <p className="m-0 text-sm text-err">{errorText(replace.error)}</p>}
      </div>
    </AdaptiveDialog>
  )
}
