/**
 * MaterialCard — один разобранный файл проекта.
 *
 * Карточка отвечает на три вопроса, которые человек задаёт о принесённом
 * файле: что это (имя, вид, размер), что из него вычитала служба (сколько
 * страниц или абзацев, замечания разборщика) и то ли это, что он приносил, —
 * поэтому текст раскрывается прямо здесь, а не в отдельном окне.
 *
 * Текст запрашивается только в раскрытом виде: опись из двадцати файлов иначе
 * тянула бы двадцать кусков содержимого ради строк, которых никто не читал.
 * Отсюда `enabled` у запроса, а не постоянная загрузка со скрытием по CSS.
 */
import { useState } from 'react'

import { errorText } from '@/api'
import { useT } from '@/i18n'
import { Button, Icon, SkeletonLines } from '@/ui'

import { materialBlobUrl, useMaterialText } from './data'
import { fileExt, formatBytes, plural } from './format'
import type { Material } from './types'

/** Единицы нумерации содержимого, которые называет `packages/materials`. */
const ЕДИНИЦЫ = new Set(['page', 'paragraph', 'line'])

export type MaterialCardProps = {
  projectId: string
  material: Material
  onDelete: (material: Material) => void
  deleting?: boolean
  /** Можно ли править содержимое проекта (роль `editor` и выше). */
  canEdit: boolean
}

export function MaterialCard({
  projectId,
  material,
  onDelete,
  deleting = false,
  canEdit,
}: MaterialCardProps) {
  const t = useT()
  const [open, setOpen] = useState(false)
  const text = useMaterialText(projectId, material.id, open)

  const ext = fileExt(material.name) || material.kind.toUpperCase()
  // Единицы разбора служба называет тремя словами (`page`, `paragraph`,
  // `line`); четвёртое однажды появится, и подпись для него — «единиц», а не
  // пропавший ключ перевода.
  const unit = ЕДИНИЦЫ.has(material.unit) ? material.unit : 'other'
  const units = material.units
    ? t('projects.materials.units', {
        n: material.units,
        word: plural(material.units, [
          t(`projects.unit.${unit}.one`),
          t(`projects.unit.${unit}.few`),
          t(`projects.unit.${unit}.many`),
        ]),
      })
    : ''

  return (
    <li className="flex min-w-0 flex-col gap-s2 rounded-md border border-line bg-surface-2 p-s3">
      <div className="flex min-w-0 items-center gap-s3">
        <span
          aria-hidden="true"
          className="grid h-9 w-9 shrink-0 place-items-center rounded-sm bg-surface text-[10px] font-semibold text-muted"
        >
          {ext || <Icon name="file" size={16} />}
        </span>

        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-semibold text-ink-strong" title={material.name}>
            {material.name}
          </div>
          <div className="truncate text-xs text-muted">
            {[formatBytes(t, material.bytes), units].filter(Boolean).join(' · ')}
          </div>
        </div>

        <Button
          variant="ghost"
          size="sm"
          onClick={() => setOpen((was) => !was)}
          aria-expanded={open}
        >
          <Icon name={open ? 'chevronDown' : 'chevronRight'} size={16} />
          {t('projects.materials.preview')}
        </Button>
        <Button
          variant="ghost"
          size="sm"
          iconOnly
          asChild
          aria-label={t('projects.materials.download')}
        >
          <a href={materialBlobUrl(projectId, material.id)} download>
            <Icon name="download" size={16} />
          </a>
        </Button>
        {canEdit && (
          <Button
            variant="ghost"
            size="sm"
            iconOnly
            aria-label={t('projects.materials.delete')}
            loading={deleting}
            onClick={() => onDelete(material)}
          >
            <Icon name="trash" size={16} />
          </Button>
        )}
      </div>

      {material.notes.length > 0 && (
        <ul className="flex flex-wrap gap-1.5">
          {material.notes.map((note) => (
            <li
              key={note}
              className="rounded-full bg-warn-bg px-2 py-0.5 text-[11px] font-medium text-warn"
            >
              {note}
            </li>
          ))}
        </ul>
      )}

      {open && (
        <div className="rounded-sm border border-line bg-surface p-s3">
          {text.isPending ? (
            <SkeletonLines count={3} />
          ) : text.isError ? (
            <p className="text-sm text-err">{errorText(text.error)}</p>
          ) : text.data && text.data.text.trim() ? (
            <>
              <pre className="max-h-64 overflow-auto whitespace-pre-wrap break-words font-mono text-xs text-ink">
                {text.data.text}
              </pre>
              <p className="mt-s2 text-xs text-muted">{text.data.anchor}</p>
            </>
          ) : (
            <p className="text-sm text-muted">{t('projects.materials.noText')}</p>
          )}
        </div>
      )}
    </li>
  )
}
