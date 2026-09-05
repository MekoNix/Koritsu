/**
 * BlockList — работа карточками блоков в порядке документа.
 *
 * Это и есть «превью живого режима»: список
 * блоков рисует сам сайт — заголовок, текст, код, таблица, схема, — с именем и
 * меткой источника. Быстро и без сборки. Настоящая вёрстка (поля, переносы,
 * номера рисунков) считается только Word/LibreOffice, поэтому рядом на экране
 * всегда есть «как будет в Word»; здесь её нет и притворяться ею нельзя.
 *
 * **Метка источника обязательна.** `agent` и `manual` — это ответ на вопрос
 * «кто это написал», и от него зависит, перепишет ли следующий проход текста
 * этот блок (написанное человеком не переписывается). Спрятать метку значило
 * бы спрятать причину, по которой блок остался прежним.
 *
 * **Клик по блоку — замечание.** Поле «что переделать» и три кнопки:
 * переделать, убрать, переставить. Всё три уезжают в
 * `kadai_rework`; «убрать» и «переставить» — это правка строения, поэтому у
 * них вид `структура`, а само действие сказано словами в замечании: своего
 * вида «убери блок» у службы нет, и выдумывать его на стороне сайта значило бы
 * гадать, что сделает сценарий.
 */
import { useState } from 'react'

import { useT } from '@/i18n'
import { cn } from '@/lib/cn'
import { Button, EmptyState, Icon, SkeletonLines, Textarea, type IconName } from '@/ui'

import { blockText, type ReworkKind } from './stages'
import type { BlockRecordBody } from './types'

/** Значок по виду блока. Вид приходит от движка отчётов (`hokoku.live.KINDS`). */
const ЗНАЧОК: Record<string, IconName> = {
  heading: 'file',
  markdown: 'file',
  text: 'file',
  code: 'flowchart',
  table: 'chart',
  diagram: 'flowchart',
  image: 'eye',
  formula: 'chart',
  toc: 'tasks',
}

/** Ключ перевода вида блока; нет своего слова — показываем код как есть. */
const ВИД: Record<string, string> = {
  heading: 'kadai.blocks.kind.heading',
  markdown: 'kadai.blocks.kind.markdown',
  text: 'kadai.blocks.kind.markdown',
  code: 'kadai.blocks.kind.code',
  table: 'kadai.blocks.kind.table',
  diagram: 'kadai.blocks.kind.diagram',
  image: 'kadai.blocks.kind.image',
  formula: 'kadai.blocks.kind.formula',
  toc: 'kadai.blocks.kind.toc',
}

export type ReworkRequest = { block: string; kind: ReworkKind; note: string }

export function BlockList({
  blocks,
  loading,
  disabled,
  onRework,
}: {
  blocks: BlockRecordBody[] | undefined
  loading: boolean
  /** Идёт прогон: поле замечания заблокировано. */
  disabled: boolean
  onRework: (запрос: ReworkRequest) => void
}) {
  const t = useT()
  const [открыт, setОткрыт] = useState<string | null>(null)

  if (loading) return <SkeletonLines count={8} />
  if (!blocks || blocks.length === 0) {
    return (
      <EmptyState
        icon="tasks"
        title={t('kadai.blocks.emptyTitle')}
        text={t('kadai.blocks.emptyText')}
      />
    )
  }

  return (
    <ol className="flex flex-col gap-s2">
      {blocks.map((блок, i) => (
        <li key={блок.key}>
          <BlockCard
            block={блок}
            n={i + 1}
            open={открыт === блок.key}
            onToggle={() => setОткрыт((было) => (было === блок.key ? null : блок.key))}
            disabled={disabled}
            onRework={onRework}
          />
        </li>
      ))}
    </ol>
  )
}

function BlockCard({
  block,
  n,
  open,
  onToggle,
  disabled,
  onRework,
}: {
  block: BlockRecordBody
  n: number
  open: boolean
  onToggle: () => void
  disabled: boolean
  onRework: (запрос: ReworkRequest) => void
}) {
  const t = useT()
  const [note, setNote] = useState('')
  const вид = String(block.kind ?? '')
  const текст = blockText(block)
  const заголовок = вид === 'heading'

  return (
    <article
      className={cn(
        'rounded-md border bg-surface shadow-1 transition-colors',
        open ? 'border-accent' : 'border-line hover:border-line-strong',
      )}
    >
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        className="flex w-full items-start gap-s2 p-s3 text-left focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
      >
        <span className="mt-0.5 font-mono text-[11px] text-muted">{n}</span>
        <Icon name={ЗНАЧОК[вид] ?? 'file'} size={15} className="mt-0.5 shrink-0 text-muted" />
        <span className="flex min-w-0 flex-1 flex-col gap-1">
          <span className="flex flex-wrap items-center gap-s2">
            <span
              className={cn(
                'truncate',
                заголовок
                  ? 'font-display text-base font-semibold text-ink-strong'
                  : 'font-medium text-ink-strong',
              )}
            >
              {block.label || block.key}
            </span>
            <span className="rounded-sm bg-surface-2 px-1.5 py-0.5 text-[11px] text-muted">
              {ВИД[вид] ? t(ВИД[вид]) : вид || t('kadai.blocks.kind.unknown')}
            </span>
            <span
              className={cn(
                'rounded-sm px-1.5 py-0.5 text-[11px]',
                block.source === 'manual' ? 'bg-accent-bg text-ink-strong' : 'text-agent',
              )}
            >
              {t(block.source === 'manual' ? 'kadai.blocks.byHuman' : 'kadai.blocks.byAgent')}
            </span>
          </span>
          {текст && (
            <span className="line-clamp-3 whitespace-pre-wrap text-xs text-muted">{текст}</span>
          )}
        </span>
        <Icon
          name={open ? 'chevronDown' : 'chevronRight'}
          size={15}
          className="mt-0.5 text-muted"
        />
      </button>

      {open && (
        <div className="flex flex-col gap-s2 border-t border-line p-s3">
          {текст && (
            <pre className="max-h-[220px] overflow-auto whitespace-pre-wrap rounded-sm border border-line bg-surface-2 p-s2 font-mono text-xs text-ink">
              {текст}
            </pre>
          )}
          <Textarea
            value={note}
            onChange={(e) => setNote(e.target.value)}
            rows={2}
            disabled={disabled}
            placeholder={t('kadai.blocks.notePlaceholder')}
            aria-label={t('kadai.blocks.note')}
          />
          <div className="flex flex-wrap items-center gap-s2">
            <Button
              variant="primary"
              size="sm"
              disabled={disabled || !note.trim()}
              onClick={() => onRework({ block: block.key, kind: вид_замечания(вид), note })}
            >
              {t('kadai.blocks.redo')}
            </Button>
            <Button
              variant="secondary"
              size="sm"
              disabled={disabled}
              onClick={() =>
                onRework({
                  block: block.key,
                  kind: 'структура',
                  note: `${t('kadai.blocks.removeNote')}: ${block.label || block.key}${note.trim() ? `. ${note.trim()}` : ''}`,
                })
              }
            >
              {t('kadai.blocks.remove')}
            </Button>
            <Button
              variant="secondary"
              size="sm"
              disabled={disabled || !note.trim()}
              onClick={() =>
                onRework({
                  block: block.key,
                  kind: 'структура',
                  note: `${t('kadai.blocks.moveNote')}: ${block.label || block.key}. ${note.trim()}`,
                })
              }
            >
              {t('kadai.blocks.move')}
            </Button>
            <span className="text-xs text-muted">{t('kadai.blocks.noteHint')}</span>
          </div>
        </div>
      )}
    </article>
  )
}

/**
 * Вид замечания по виду блока: текст — «кусок», код — «код», схема — «схема».
 *
 * Угадывать вид по словам замечания нельзя (`kadai.rework`: «маршрут по словам
 * не угадывается»), а по виду блока он известен точно: замечание к листингу —
 * это замечание к коду, и переигрывать после него надо больше, чем один абзац.
 */
function вид_замечания(kind: string): ReworkKind {
  if (kind === 'code') return 'код'
  if (kind === 'diagram' || kind === 'image') return 'схема'
  return 'кусок'
}
