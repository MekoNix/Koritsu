/**
 * TagVersions — история значений тега: список, просмотр одной, возврат.
 *
 * **Возврат ничего не удаляет.** Служба дописывает выбранное значение новой
 * версией и отвечает номером БОЛЬШИМ того, к которому вернулись
 * (`versions/routes.py`), поэтому кнопка называется «вернуть», а не
 * «восстановить», и подписи про «потеряете текущую» здесь нет: терять нечего.
 *
 * Сравнение текстов — ночь 2 (решение владельца), здесь его нет намеренно:
 * версия открывается целиком, соседняя — тоже, и это честнее, чем показать
 * половину разницы.
 *
 * История свёрнута по умолчанию: она нужна, когда что-то пошло не так, а место
 * под текстом нужно всегда.
 */
import { useState } from 'react'

import { errorText } from '@/api'
import { useT } from '@/i18n'
import { Button, Dialog, Icon, SkeletonLines } from '@/ui'

import { useRollbackValue, useTagVersion, useTagVersions } from './data'
import { valueText } from './tags'

export function TagVersions({
  projectId,
  tagKey,
  canEdit,
}: {
  projectId: string
  tagKey: string
  canEdit: boolean
}) {
  const t = useT()
  const [open, setOpen] = useState(false)
  const [viewing, setViewing] = useState<number | null>(null)

  const versions = useTagVersions(projectId, open ? tagKey : undefined)
  const rollback = useRollbackValue(projectId)
  const version = useTagVersion(projectId, tagKey, viewing)

  const список = versions.data ?? []

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
        {open && список.length > 0 && (
          <span className="text-xs text-muted">
            {t('reports.versions.count', { n: список.length })}
          </span>
        )}
      </button>

      {open && (
        <div className="border-t border-line p-s3">
          {versions.isPending ? (
            <SkeletonLines count={3} />
          ) : versions.isError ? (
            // 404 у тега без единого значения — это «истории нет», а не беда.
            <p className="text-xs text-muted">{t('reports.versions.none')}</p>
          ) : (
            <ul className="flex flex-col gap-s1">
              {[...список].reverse().map((v) => (
                <li
                  key={v.n}
                  className="flex flex-wrap items-center gap-s2 rounded-sm px-s2 py-1.5 text-xs hover:bg-surface-2"
                >
                  <span className="font-mono text-ink-strong">v{v.n}</span>
                  <span className={v.source === 'agent' ? 'text-agent' : 'text-muted'}>
                    {t(`reports.versions.source.${v.source}`)}
                  </span>
                  <span className="text-muted">{when(v.at)}</span>
                  {v.n === список[список.length - 1]?.n && (
                    <span className="rounded-sm bg-ok-bg px-1.5 py-0.5 text-ok">
                      {t('reports.versions.current')}
                    </span>
                  )}
                  <span className="ml-auto flex gap-s1">
                    <Button variant="ghost" size="sm" onClick={() => setViewing(v.n)}>
                      {t('common.action.open')}
                    </Button>
                    <Button
                      variant="secondary"
                      size="sm"
                      disabled={!canEdit || rollback.isPending}
                      onClick={() => rollback.mutate({ key: tagKey, n: v.n })}
                    >
                      {t('reports.versions.rollback')}
                    </Button>
                  </span>
                </li>
              ))}
            </ul>
          )}
          {rollback.isError && (
            <p className="mt-s2 text-xs text-err">{errorText(rollback.error)}</p>
          )}
        </div>
      )}

      <Dialog
        open={viewing !== null}
        onOpenChange={(v) => !v && setViewing(null)}
        title={t('reports.versions.viewTitle', { n: viewing ?? 0, tag: tagKey })}
        size="lg"
        footer={
          <>
            <Button variant="ghost" onClick={() => setViewing(null)}>
              {t('common.action.close')}
            </Button>
            <Button
              variant="primary"
              disabled={!canEdit || viewing === null}
              onClick={() => {
                if (viewing !== null) rollback.mutate({ key: tagKey, n: viewing })
                setViewing(null)
              }}
            >
              {t('reports.versions.rollback')}
            </Button>
          </>
        }
      >
        {version.isPending ? (
          <SkeletonLines count={6} />
        ) : version.isError ? (
          <p className="text-sm text-err">{errorText(version.error)}</p>
        ) : (
          <pre className="whitespace-pre-wrap break-words font-body text-sm text-ink">
            {valueText(version.data?.value)}
          </pre>
        )}
      </Dialog>
    </section>
  )
}

/** Время версии человеку: дата и часы, без секунд и без «менее минуты назад». */
function when(iso: string): string {
  const дата = new Date(iso)
  if (Number.isNaN(дата.getTime())) return iso
  return дата.toLocaleString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}
