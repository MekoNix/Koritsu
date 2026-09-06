/**
 * ContextFiles — папка файлов контекста одного решения.
 *
 * У каждого решения работы своя папка: методичка, исходники и таблица данных
 * одной задачи в промпт другой не едут. Причина не в порядке, а в цене — чужая
 * методичка сбивает модель ровно так же, как чужое условие, и платит за это
 * человек.
 *
 * **Общие файлы работы здесь не показываются.** Файл, приложенный ко всей
 * работе (опись `GET …/materials` без `run`), виден отчётам и схемам, как
 * раньше, но в промпт решения не уезжает: иначе выбор «положить файл в это
 * решение» не значил бы ничего.
 *
 * **«Убрать» уносит файл с тома, а не только из папки.** Файл, положенный
 * сюда, принадлежит этому решению, и «убрал из папки, а он остался в работе»
 * было бы состоянием, которого человек не просил и не видит. Условие при этом
 * убрать нельзя: без него решать нечего, и меняется оно своим шагом.
 */
import { useState } from 'react'

import { errorText } from '@/api'
import { useT } from '@/i18n'
import { Button, Icon, SkeletonLines } from '@/ui'
import { useDeleteMaterial, useUploadMaterial } from '@/features/projects/data'
import { FileDrop } from '@/features/projects/FileDrop'

import { useContextMaterials } from './data'

/** Что принимает разбор материалов: те же виды, что и опись работы. */
export const ПРИНИМАЕМ = '.docx,.doc,.pdf,.txt,.md,.png,.jpg,.jpeg,.py,.cs,.cpp,.c,.h'

export function ContextFiles({
  projectId,
  runId,
  conditionId,
  disabled,
}: {
  projectId: string
  runId: string
  /** Материал-условие: его из папки не убирают — без него решать нечего. */
  conditionId: string | undefined
  disabled: boolean
}) {
  const t = useT()
  const files = useContextMaterials(projectId, runId)
  const upload = useUploadMaterial()
  const remove = useDeleteMaterial()
  const [беда, setБеда] = useState<string | null>(null)

  async function положить(список: File[]) {
    setБеда(null)
    try {
      // По запросу на файл: приём материалов у службы поштучный, а разбор всё
      // равно идёт очередью, и пачка не сделала бы его быстрее.
      for (const файл of список) {
        await upload.mutateAsync({ projectId, file: файл, runId })
      }
      await files.refetch()
    } catch (е) {
      setБеда(errorText(е))
    }
  }

  return (
    <section className="flex flex-col gap-s2 rounded-md border border-line bg-surface p-s3 shadow-1">
      <header className="flex flex-wrap items-center gap-s2">
        <Icon name="file" size={16} className="text-muted" />
        <span className="font-semibold text-ink-strong">{t('kadai.context.title')}</span>
        <span className="text-xs text-muted">{t('kadai.context.hint')}</span>
      </header>

      {files.isPending ? (
        <SkeletonLines count={2} />
      ) : (files.data ?? []).length === 0 ? (
        <p className="text-xs text-muted">{t('kadai.context.empty')}</p>
      ) : (
        <ul className="flex flex-col gap-1 text-sm text-ink" data-testid="kadai-context-list">
          {(files.data ?? []).map((m) => (
            <li key={m.id} className="flex items-center gap-s2">
              <Icon name="file" size={14} className="text-muted" />
              <span className="truncate">{m.name}</span>
              {m.id === conditionId ? (
                <span className="ml-auto rounded-sm bg-surface-2 px-1.5 py-0.5 text-xs text-muted">
                  {t('kadai.context.isCondition')}
                </span>
              ) : (
                <Button
                  variant="ghost"
                  size="sm"
                  className="ml-auto"
                  disabled={disabled || remove.isPending}
                  onClick={() => remove.mutate({ projectId, materialId: m.id })}
                >
                  {t('kadai.context.remove')}
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}

      <FileDrop
        multiple
        accept={ПРИНИМАЕМ}
        disabled={disabled || upload.isPending}
        label={t('kadai.context.drop')}
        hint={t('kadai.context.dropHint')}
        onFiles={(список) => void положить(список)}
      />

      {беда && <p className="text-xs text-err">{беда}</p>}
      {remove.isError && <p className="text-xs text-err">{errorText(remove.error)}</p>}
    </section>
  )
}
