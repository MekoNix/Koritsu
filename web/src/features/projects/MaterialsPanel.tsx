/**
 * MaterialsPanel — файлы проекта: приёмник, разбор и опись.
 *
 * **Файлы грузятся на весь проект, а не под тег** (правило брифа): приёмник
 * здесь один, и привязки к тегу у него нет.
 *
 * Путь одного файла: `POST …/materials` → `202` с карточкой задания `parse` →
 * прогресс по `useJobStream` → файл появляется в описи. Поэтому строк здесь два
 * вида — разбирающиеся (по заданию) и разобранные (по описи), и первое не
 * является «загрузкой» второго: разбор чужого PDF идёт секунды, и всё это время
 * человеку надо видеть, что файл принят.
 *
 * Строки разбора берутся из двух мест: свои — из состояния этой страницы, и
 * `GET …/materials/pending` — чтобы перезагрузка страницы или файл, брошенный
 * соседом по пространству, не превращались в пустоту, из которой через десять
 * секунд появляется файл ниоткуда.
 *
 * Тоста на конец разбора здесь нет намеренно: он уже показан оболочкой
 * (`useUserEvents` тостит завершение любой фоновой задачи), и второй был бы
 * дублем. Свой тост — только на отказ самой загрузки: 413, квота, чужой тип.
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'

import { errorText, keys } from '@/api'
import { useJobStream } from '@/api/hooks'
import { useT } from '@/i18n'
import { Button, EmptyState, ErrorState, Icon, SkeletonLines, Spinner, useToast } from '@/ui'

import { FileDrop } from './FileDrop'
import { MaterialCard } from './MaterialCard'
import { Panel } from './Panel'
import { useDeleteMaterial, useMaterials, usePendingMaterials, useUploadMaterial } from './data'
import { formatBytes } from './format'
import { readUploadState, uploadName } from './uploadState'
import type { Material } from './types'

/** Потолок на файл в службе (`Settings.file_max_bytes`, §2). Здесь — для подсказки. */
const FILE_MAX_BYTES = 10 * 1024 * 1024

/** Своя загрузка: пока запрос не ответил, задания ещё нет. */
type LocalUpload = { localId: number; name: string; jobId: string | null }

let nextLocalId = 1

export function MaterialsPanel({ projectId, canEdit }: { projectId: string; canEdit: boolean }) {
  const t = useT()
  const toast = useToast()
  const qc = useQueryClient()

  const materials = useMaterials(projectId)
  const pending = usePendingMaterials(projectId)
  const upload = useUploadMaterial()
  const remove = useDeleteMaterial()

  const [own, setOwn] = useState<LocalUpload[]>([])

  const take = useCallback(
    (files: File[]) => {
      for (const file of files) {
        const localId = nextLocalId++
        setOwn((was) => [...was, { localId, name: file.name, jobId: null }])
        upload.mutate(
          { projectId, file },
          {
            onSuccess: (accepted) => {
              setOwn((was) =>
                was.map((row) =>
                  row.localId === localId ? { ...row, jobId: accepted.job.id } : row,
                ),
              )
              void qc.invalidateQueries({ queryKey: keys.projects.pending(projectId) })
            },
            onError: (error) => {
              // Отказ загрузки — единственное, о чём тостит этот экран: файл
              // не принят вовсе, и в описи его не будет ни через секунду, ни
              // потом. Текст берётся по коду службы (413, квота, чужой тип).
              setOwn((was) => was.filter((row) => row.localId !== localId))
              toast.error(
                t('projects.materials.uploadFailed', { name: file.name }),
                errorText(error),
              )
            },
          },
        )
      }
    },
    [projectId, qc, t, toast, upload],
  )

  /**
   * Задание кончилось. `drop` — убирать ли строку: разобранный файл уходит из
   * строк разбора в опись, а упавший остаётся на месте с текстом беды, пока
   * человек не закроет его сам. Иначе единственным следом отказа был бы тост,
   * который через шесть секунд исчезает.
   */
  const finished = useCallback(
    (localId: number | null, drop: boolean) => {
      if (drop && localId !== null) setOwn((was) => was.filter((row) => row.localId !== localId))
      void qc.invalidateQueries({ queryKey: keys.projects.materials(projectId) })
      void qc.invalidateQueries({ queryKey: keys.projects.pending(projectId) })
      void qc.invalidateQueries({ queryKey: keys.projects.one(projectId) })
    },
    [projectId, qc],
  )

  /**
   * Строки разбора: свои и чужие, без повторов. Своя строка знает `localId` и
   * убирается по концу задания; чужая живёт до следующего ответа службы.
   */
  const rows = useMemo(() => {
    const мои = own.map((row) => ({ key: `own-${row.localId}`, ...row }))
    const занятые = new Set(own.map((row) => row.jobId).filter(Boolean))
    const чужие = (pending.data ?? [])
      .filter((row) => !занятые.has(row.job.id))
      .map((row) => ({
        key: `pending-${row.job.id}`,
        localId: null as number | null,
        name: row.name,
        jobId: row.job.id,
      }))
    return [...мои, ...чужие]
  }, [own, pending.data])

  return (
    <Panel
      title={t('projects.materials.title')}
      note={t('projects.materials.note')}
      action={
        materials.data && materials.data.length > 0 ? (
          <span className="text-xs text-muted">
            {formatBytes(
              t,
              materials.data.reduce((sum, m) => sum + m.bytes, 0),
            )}
          </span>
        ) : null
      }
    >
      <div className="flex flex-col gap-s3">
        {canEdit && (
          <FileDrop
            multiple
            onFiles={take}
            label={t('projects.materials.drop')}
            hint={t('projects.materials.dropHint', { size: formatBytes(t, FILE_MAX_BYTES) })}
          />
        )}

        {rows.length > 0 && (
          <ul className="flex flex-col gap-s2">
            {rows.map((row) => (
              <UploadRow
                key={row.key}
                jobId={row.jobId}
                name={row.name}
                onFinished={(drop) => finished(row.localId, drop)}
              />
            ))}
          </ul>
        )}

        {materials.isPending ? (
          <SkeletonLines count={3} />
        ) : materials.isError ? (
          <ErrorState error={materials.error} onRetry={() => void materials.refetch()} />
        ) : materials.data && materials.data.length > 0 ? (
          <ul className="flex flex-col gap-s2">
            {materials.data.map((material) => (
              <MaterialCard
                key={material.id}
                projectId={projectId}
                material={material}
                canEdit={canEdit}
                deleting={remove.isPending && remove.variables?.materialId === material.id}
                onDelete={(m: Material) =>
                  remove.mutate(
                    { projectId, materialId: m.id },
                    { onError: (error) => toast.error(errorText(error)) },
                  )
                }
              />
            ))}
          </ul>
        ) : rows.length === 0 ? (
          <EmptyState
            compact
            icon="inbox"
            title={t('projects.materials.empty')}
            text={t('projects.materials.emptyHint')}
          />
        ) : null}
      </div>
    </Panel>
  )
}

/**
 * Строка разбирающегося файла. Каждая — со своим потоком: `useJobStream` берёт
 * одно задание, а хук в цикле невозможен, поэтому цикл сделан из компонентов.
 */
function UploadRow({
  jobId,
  name,
  onFinished,
}: {
  jobId: string | null
  name: string
  /** `drop` — убрать строку; на упавшем задании строка остаётся с текстом беды. */
  onFinished: (drop: boolean) => void
}) {
  const t = useT()
  const { job } = useJobStream(jobId)
  const state = readUploadState(job)
  const title = uploadName(job, name)

  useEffect(() => {
    if (state.finished) onFinished(state.phase !== 'failed')
    // Зависимость — только конец задания: `onFinished` пересоздаётся вместе с
    // проектом, и держать его в списке значило бы звать сброс кэша по кругу.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.finished, state.phase])

  const текст =
    state.phase === 'failed'
      ? t(`errors.${state.errorCode ?? 'unknown'}`)
      : t(`projects.materials.phase.${state.phase}`)

  return (
    <li className="flex min-w-0 items-center gap-s3 rounded-md border border-line bg-surface-2 px-s3 py-s2">
      {state.phase === 'failed' ? (
        <Icon name="error" size={18} className="text-err" />
      ) : (
        <Spinner size={18} />
      )}
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm text-ink-strong">{title}</div>
        <div className="truncate text-xs text-muted">{текст}</div>
        {state.percent !== null && (
          <div className="mt-1 h-1 w-full overflow-hidden rounded-full bg-surface-3">
            <div
              className="h-full bg-accent transition-[width] duration-300"
              style={{ width: `${state.percent}%` }}
            />
          </div>
        )}
      </div>
      {state.phase === 'failed' && (
        <Button variant="ghost" size="sm" onClick={() => onFinished(true)}>
          {t('common.action.close')}
        </Button>
      )}
    </li>
  )
}
