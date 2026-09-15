/**
 * MaterialsPicker — файлы для генерации: загрузить новые или отметить уже
 * загруженные.
 *
 * Файлы лежат в материалах «Тренажёра» пространства и проходят тот же разбор
 * материалов, что везде на сайте (PDF, DOCX, текст, сканы). Агенту уходят
 * только отмеченные галочкой: файл, загруженный для другого набора, в промпт
 * этого сам не попадает — за прочитанное моделью платит человек.
 *
 * Свежезагруженный файл отмечается сразу: его принесли именно для этого
 * набора. Пока файл разбирается, галочка у него стоит, но «Создать» ждёт конца
 * разбора — агент читает разобранный текст, а не байты.
 */
import { useState } from 'react'

import { errorText } from '@/api'
import { useT } from '@/i18n'
import { Chip, Icon, SkeletonLines } from '@/ui'
import { FileDrop } from '@/features/projects/FileDrop'

import {
  materialFailed,
  materialReady,
  useCardsMaterials,
  useUploadCardsMaterial,
  type CardsMaterial,
} from './data'

/** Что принимает разбор материалов для карточек. */
export const ACCEPT = '.pdf,.docx,.doc,.txt,.md,.png,.jpg,.jpeg'

export function MaterialsPicker({
  workspaceId,
  selected,
  onChange,
  disabled,
}: {
  workspaceId: string | undefined
  selected: string[]
  onChange: (ids: string[]) => void
  disabled?: boolean
}) {
  const t = useT()
  const list = useCardsMaterials(workspaceId)
  const upload = useUploadCardsMaterial()
  const [error, setError] = useState<string | null>(null)

  async function put(files: File[]) {
    if (!workspaceId) return
    setError(null)
    const added: string[] = []
    try {
      // По запросу на файл: приём материалов поштучный, разбор идёт очередью.
      for (const file of files) {
        const m = await upload.mutateAsync({ workspaceId, file })
        added.push(m.material_id)
      }
    } catch (e) {
      setError(errorText(e))
    } finally {
      if (added.length) onChange([...new Set([...selected, ...added])])
    }
  }

  function toggle(id: string, on: boolean) {
    onChange(on ? [...new Set([...selected, id])] : selected.filter((x) => x !== id))
  }

  const items = list.data ?? []

  return (
    <div className="flex flex-col gap-s2">
      <FileDrop
        multiple
        compact
        accept={ACCEPT}
        disabled={disabled || upload.isPending || !workspaceId}
        label={upload.isPending ? t('cards.generate.files.uploading') : t('cards.generate.files.drop')}
        hint={t('cards.generate.files.hint')}
        onFiles={(files) => void put(files)}
      />

      {list.isPending ? (
        <SkeletonLines count={2} />
      ) : list.isError ? (
        <p className="text-xs text-err">{errorText(list.error)}</p>
      ) : items.length === 0 ? (
        <p className="text-xs text-muted">{t('cards.generate.files.empty')}</p>
      ) : (
        <ul className="flex flex-col gap-1" data-testid="cards-generate-files">
          {items.map((m) => (
            <MaterialRow
              key={m.material_id}
              m={m}
              checked={selected.includes(m.material_id)}
              disabled={disabled || materialFailed(m)}
              onToggle={(on) => toggle(m.material_id, on)}
            />
          ))}
        </ul>
      )}

      {error && <p className="text-xs text-err">{error}</p>}
    </div>
  )
}

function MaterialRow({
  m,
  checked,
  disabled,
  onToggle,
}: {
  m: CardsMaterial
  checked: boolean
  disabled?: boolean
  onToggle: (on: boolean) => void
}) {
  const t = useT()
  const ready = materialReady(m)
  const failed = materialFailed(m)
  return (
    <li>
      <label className="flex min-h-11 items-center gap-s2 rounded-sm px-1 text-sm text-ink hover:bg-surface-2">
        <input
          type="checkbox"
          className="h-4 w-4 shrink-0 accent-[var(--accent)]"
          checked={checked && !failed}
          disabled={disabled}
          onChange={(e) => onToggle(e.target.checked)}
        />
        <Icon name="file" size={14} className="shrink-0 text-muted" />
        <span className="min-w-0 flex-1 truncate">{m.name}</span>
        {failed ? (
          <Chip tone="err">{t('cards.generate.files.failed')}</Chip>
        ) : !ready ? (
          <Chip tone="info">{t('cards.generate.files.parsing')}</Chip>
        ) : null}
      </label>
      {failed && m.error && <p className="m-0 break-words pb-1 pl-[46px] text-xs text-err">{m.error}</p>}
    </li>
  )
}
