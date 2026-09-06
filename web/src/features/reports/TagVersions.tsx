/**
 * TagVersions — история значений тега: список, сравнение текстов, возврат.
 *
 * Вся работа с экраном — в общем `VersionHistory` (им же пользуется история
 * списка блоков в `features/kadai`); здесь только то, что знает про теги:
 * откуда берутся версии, как из версии достаётся текст и что означает флаг
 * «вернули версию N».
 *
 * **Возврат ничего не удаляет.** Служба дописывает выбранное значение новой
 * версией и отвечает номером БОЛЬШИМ того, к которому вернулись
 * (`versions/routes.py`), поэтому кнопка называется «вернуть», а не
 * «восстановить», и подписи про «потеряете текущую» здесь нет: терять нечего.
 *
 * История свёрнута по умолчанию: она нужна, когда что-то пошло не так, а место
 * под текстом нужно всегда. Пока свёрнута — версии не запрашиваются вовсе.
 */
import { useState } from 'react'

import { useT } from '@/i18n'
import { Icon } from '@/ui'

import { VersionHistory } from './VersionHistory'
import { useRollbackValue, useTagVersion, useTagVersions } from './data'
import { valueText } from './tags'
import { versionEntries, type VersionText } from './versions'

export function TagVersions({
  projectId,
  report,
  tagKey,
  canEdit,
  currentText,
}: {
  projectId: string
  /** Отчёт работы, которому принадлежит история: у каждого она своя. */
  report: string
  tagKey: string
  canEdit: boolean
  /** Текст, который лежит в теге сейчас: правая сторона сравнения «с текущей». */
  currentText: string
}) {
  const t = useT()
  const [open, setOpen] = useState(false)

  const versions = useTagVersions(projectId, report, open ? tagKey : undefined)
  const rollback = useRollbackValue(projectId, report)

  /**
   * «Дай текст версии N» — то, чем `VersionHistory` кормит сравнение.
   *
   * Определён здесь, а не там, потому что маршрут версии у тега свой
   * (`…/values/{key}/versions/{n}`), а у списка блоков — другой. Зовётся он
   * ровно дважды и всегда, независимо от выбора человека, — правило хуков
   * соблюдено.
   */
  const useVersionText = (n: number | null): VersionText => {
    const запрос = useTagVersion(projectId, report, open ? tagKey : undefined, n)
    return {
      text: запрос.data ? valueText(запрос.data.value) : undefined,
      loading: n !== null && запрос.isPending,
      error: n === null ? null : запрос.error,
    }
  }

  const строки = versionEntries(versions.data, t)

  return (
    <section className="rounded-md border border-line">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center gap-s2 px-s3 py-s2 text-left text-sm text-ink focus-visible:outline focus-visible:-outline-offset-2 focus-visible:outline-accent"
      >
        <Icon name={open ? 'chevronDown' : 'chevronRight'} size={14} />
        {t('reports.versions.title')}
        {open && строки.length > 0 && (
          <span className="text-xs text-muted">
            {t('reports.versions.count', { n: строки.length })}
          </span>
        )}
      </button>

      {open && (
        <div className="border-t border-line p-s3">
          <VersionHistory
            entries={строки}
            loading={versions.isPending}
            error={versions.error}
            useVersionText={useVersionText}
            currentText={currentText}
            canEdit={canEdit}
            onRollback={(n) => rollback.mutate({ key: tagKey, n })}
            rollbackPending={rollback.isPending}
            rollbackError={rollback.isError ? rollback.error : null}
            sourceLabel={(source) => t(`reports.versions.source.${source}`)}
            emptyText={t('reports.versions.none')}
          />
        </div>
      )}
    </section>
  )
}
