/**
 * TagEditor — середина экрана: заполнение выбранного тега.
 *
 * Три действия над полем (бриф): сгенерировать, скопировать, очистить. На время
 * генерации поле заблокировано (решение владельца) — не «только для чтения», а
 * именно `disabled`: правка, набранная поверх приходящего текста, была бы
 * потеряна первым же куском потока.
 *
 * **Черновик локальный, отправляется по уходу из поля.** Каждое нажатие клавиши
 * в службу не уезжает: там у значения версия и история, и сорок версий на один
 * абзац сделали бы её нечитаемой. Поэтому правка копится в поле, а `PUT` уходит
 * на `blur` и по кнопке.
 *
 * **Очистить — это новая версия с пустым текстом**, а не удаление: удаления
 * значения у службы нет вовсе, и «очистить» обязано так же откатываться, как
 * всё прочее.
 */
import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'

import { errorText } from '@/api'
import { useT } from '@/i18n'
import { cn } from '@/lib/cn'
import { Button, Icon, Spinner, Textarea } from '@/ui'

import { TagVersions } from './TagVersions'
import { useSetValue } from './data'
import { isTextual, tagTitle, textToValue, valueText } from './tags'
import type { ProjectTag, TagValue } from './types'

export type TagEditorProps = {
  projectId: string
  tag: ProjectTag | undefined
  value: TagValue | undefined
  /** Текст, приходящий по потоку прямо сейчас; `undefined` — прогон не идёт. */
  streamed: string | undefined
  /** Идёт ли прогон по этому тегу. */
  busy: boolean
  canEdit: boolean
  onGenerate: (key: string) => void
  /** Цена прогона и остаток месяца — показываются ДО нажатия. */
  priceHint: ReactNode
  /** Можно ли вообще звать модель (есть ли пресет с ключом). */
  canGenerate: boolean
}

export function TagEditor({
  projectId,
  tag,
  value,
  streamed,
  busy,
  canEdit,
  onGenerate,
  priceHint,
  canGenerate,
}: TagEditorProps) {
  const t = useT()
  const save = useSetValue(projectId)

  const серверный = valueText(value)
  const [draft, setDraft] = useState(серверный)
  const [dirty, setDirty] = useState(false)
  const [copied, setCopied] = useState(false)
  // Ключ, под который набран черновик: смена тега обязана сбрасывать поле,
  // иначе текст одного тега уедет в другой по первому же `blur`.
  const ключ = tag?.key ?? ''
  const прежний = useRef(ключ)

  useEffect(() => {
    if (прежний.current !== ключ) {
      прежний.current = ключ
      setDraft(серверный)
      setDirty(false)
      return
    }
    // Значение переписали не мы (прогон, откат, сосед по пространству) —
    // показываем пришедшее. Свою несохранённую правку при этом не трогаем:
    // потерять набранное хуже, чем показать устаревшее.
    if (!dirty) setDraft(серверный)
  }, [ключ, серверный, dirty])

  // Напечатанное потоком остаётся в поле и после конца прогона — до того, как
  // приедет перечитанное значение. Иначе текст на секунду пропадает: задание
  // уже кончилось, а ответ службы ещё в пути, и человек видит, как написанное
  // моделью исчезает.
  useEffect(() => {
    if (busy && streamed !== undefined) setDraft(streamed)
  }, [busy, streamed])

  const записать = useCallback(
    (текст: string) => {
      if (!tag) return
      save.mutate({ key: tag.key, value: textToValue(текст, { type: tag.type, previous: value }) })
      setDirty(false)
    },
    [save, tag, value],
  )

  if (!tag) {
    return (
      <div className="flex h-full items-center justify-center p-s6 text-center text-sm text-muted">
        {t('reports.editor.pick')}
      </div>
    )
  }

  const текстовый = isTextual(value?.type ?? tag.type)
  const показ = busy && streamed !== undefined ? streamed : draft
  const заблокировано = busy || !canEdit || !текстовый

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="flex flex-wrap items-center gap-s2 border-b border-line p-s3">
        <span
          className={cn(
            'rounded-sm border px-1.5 py-0.5 font-mono text-xs',
            tag.source === 'agent'
              ? 'border-transparent bg-agent-bg text-agent'
              : 'border-line-strong text-ink',
          )}
        >{`{{${tag.key}}}`}</span>
        <span className="truncate font-semibold text-ink-strong">{tagTitle(tag)}</span>
        <span className="rounded-sm bg-surface-2 px-1.5 py-0.5 text-xs text-muted">{tag.type}</span>
        {tag.filled && (
          <span className="text-xs text-muted">
            {t(tag.source === 'agent' ? 'reports.editor.byAgent' : 'reports.editor.byHand', {
              n: tag.version ?? 0,
            })}
          </span>
        )}
      </header>

      <div className="flex min-h-0 flex-1 flex-col gap-s3 overflow-auto p-s3">
        <div className="flex flex-wrap items-center gap-s2">
          <Button
            variant="agent"
            size="sm"
            disabled={!canEdit || busy || !canGenerate}
            onClick={() => onGenerate(tag.key)}
          >
            {busy ? <Spinner size={14} /> : <Icon name="agent" size={14} />}
            {t('reports.editor.generate')}
          </Button>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => {
              void navigator.clipboard?.writeText(показ)
              setCopied(true)
              window.setTimeout(() => setCopied(false), 1500)
            }}
          >
            {copied ? t('common.action.copied') : t('common.action.copy')}
          </Button>
          <Button
            variant="ghost"
            size="sm"
            disabled={заблокировано || (!показ && !tag.filled)}
            onClick={() => {
              setDraft('')
              записать('')
            }}
          >
            {t('reports.editor.clear')}
          </Button>
          <Button
            variant="primary"
            size="sm"
            disabled={!dirty || заблокировано}
            loading={save.isPending}
            onClick={() => записать(draft)}
          >
            {t('common.action.save')}
          </Button>
          <span className="ml-auto text-xs text-muted">{priceHint}</span>
        </div>

        <Textarea
          value={показ}
          disabled={заблокировано}
          aria-label={t('reports.editor.field', { tag: tag.key })}
          onChange={(e) => {
            setDraft(e.target.value)
            setDirty(true)
          }}
          onBlur={() => {
            if (dirty) записать(draft)
          }}
          className={cn(
            'min-h-[220px] flex-1 font-body text-md leading-relaxed',
            busy && 'text-agent',
          )}
        />

        <div className="flex flex-wrap items-center justify-between gap-s2 text-xs text-muted">
          <span>
            {t('reports.editor.chars', { n: показ.length })}
            {!текстовый && ` · ${t('reports.editor.notTextual')}`}
          </span>
          {save.isError && <span className="text-err">{errorText(save.error)}</span>}
        </div>

        <TagVersions
          projectId={projectId}
          tagKey={tag.key}
          canEdit={canEdit && !busy}
          currentText={серверный}
        />
      </div>
    </div>
  )
}
