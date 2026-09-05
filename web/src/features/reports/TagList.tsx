/**
 * TagList — колонка тегов слева: прогресс над списком, поиск, сами теги.
 *
 * Композиция A макета (`05-reports.html`): сверху сводка «сколько заполнено»,
 * под ней поиск и отбор, дальше список, внизу — файлы проекта. Прогресс стоит
 * НАД списком, а не в шапке страницы, потому что относится он к списку и
 * читается вместе с ним.
 *
 * Состояние тега показано точкой, а не иконкой с подписью: строк бывает сорок,
 * и каждая лишняя буква в них — это сорок лишних букв на экране. Цвет точки
 * различает своё и сделанное моделью (`--agent`) — правило спецификации о
 * маркере «сделано агентом». Пустой тег — пустой кружок и ничего больше:
 * «без драматизации» (бриф).
 */
import type { ReactNode } from 'react'

import { useT } from '@/i18n'
import { cn } from '@/lib/cn'
import { Icon, Input, SkeletonLines, Spinner } from '@/ui'

import { summarize, tagTitle, type TagFilter } from './tags'
import type { ProjectTag } from './types'

const ФИЛЬТРЫ: TagFilter[] = ['all', 'empty', 'filled', 'agent']

export type TagListProps = {
  tags: ProjectTag[] | undefined
  /** Всё, что нашлось по поиску и отбору. */
  shown: ProjectTag[]
  loading: boolean
  selected: string | null
  onSelect: (key: string) => void
  query: string
  onQuery: (value: string) => void
  filter: TagFilter
  onFilter: (value: TagFilter) => void
  /** Теги, по которым сейчас идёт прогон. */
  busy: Set<string>
  /** Тег, который печатается прямо сейчас. */
  current: string | null
  /** Низ колонки: файлы проекта. */
  footer?: ReactNode
  /** Конструкции бланка, которых сборщик не понимает (`{% for %}` и подобные). */
  constructs?: string[]
}

export function TagList({
  tags,
  shown,
  loading,
  selected,
  onSelect,
  query,
  onQuery,
  filter,
  onFilter,
  busy,
  current,
  footer,
  constructs,
}: TagListProps) {
  const t = useT()
  const сводка = summarize(tags)

  // `h-full` обязателен, а не украшение: колонка лежит блоком внутри секции
  // сетки, и без заданной высоты `flex-1 overflow-auto` ниже считает высоту по
  // содержимому — список растёт вниз за край экрана, и до нижних тегов
  // домотать нельзя ничем.
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="border-b border-line p-s3">
        <div className="flex items-baseline justify-between text-sm">
          <span className="font-semibold text-ink-strong">{t('reports.tags.title')}</span>
          <span className="font-mono text-xs text-muted">
            {t('reports.tags.counter', { filled: сводка.filled, total: сводка.total })}
          </span>
        </div>
        <div
          className="mt-s2 h-1.5 overflow-hidden rounded-full bg-surface-2"
          role="progressbar"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={сводка.percent}
          aria-label={t('reports.tags.progressLabel')}
        >
          <div
            className="h-full rounded-full bg-accent transition-[width] duration-300"
            style={{ width: `${сводка.percent}%` }}
          />
        </div>
        {сводка.byAgent > 0 && (
          <div className="mt-s2 text-xs text-agent">
            {t('reports.tags.byAgent', { n: сводка.byAgent })}
          </div>
        )}
      </div>

      <div className="flex flex-col gap-s2 border-b border-line p-s3">
        <Input
          value={query}
          onChange={(e) => onQuery(e.target.value)}
          placeholder={t('reports.tags.searchPlaceholder')}
          aria-label={t('reports.tags.searchPlaceholder')}
        />
        <div
          className="flex flex-wrap gap-1"
          role="group"
          aria-label={t('reports.tags.filterLabel')}
        >
          {ФИЛЬТРЫ.map((f) => (
            <button
              key={f}
              type="button"
              onClick={() => onFilter(f)}
              aria-pressed={filter === f}
              className={cn(
                'rounded-btn border px-2 py-1 text-xs transition-colors',
                'focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent',
                filter === f
                  ? 'border-transparent bg-accent text-accent-ink'
                  : 'border-line-strong bg-surface text-muted hover:bg-surface-2',
              )}
            >
              {t(`reports.tags.filter.${f}`)}
            </button>
          ))}
        </div>
      </div>

      {/* Конструкции бланка, которых сборщик не понимает. Показаны здесь, над
          списком тегов, потому что вопрос у человека один и тот же: «почему в
          отчёте не то, что в бланке». Сборку они не ломают и остаются в
          документе текстом — так и написано. */}
      {constructs && constructs.length > 0 && (
        <div className="border-b border-line bg-warn-bg p-s3 text-xs text-warn">
          <p>{t('reports.tags.unknownConstructs', { n: constructs.length })}</p>
          <ul className="mt-s2 flex flex-col gap-1">
            {constructs.map((текст) => (
              <li key={текст} className="truncate font-mono" title={текст}>
                {текст}
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="min-h-0 flex-1 overflow-auto">
        {loading ? (
          <SkeletonLines count={8} className="p-s3" />
        ) : shown.length === 0 ? (
          <p className="p-s4 text-center text-xs text-muted">
            {сводка.total === 0 ? t('reports.tags.none') : t('reports.tags.nothingFound')}
          </p>
        ) : (
          <ul className="py-s1">
            {shown.map((tag, i) => (
              <li key={tag.key}>
                <button
                  type="button"
                  onClick={() => onSelect(tag.key)}
                  aria-current={selected === tag.key}
                  className={cn(
                    'flex w-full items-center gap-s2 px-s3 py-1.5 text-left text-sm',
                    'focus-visible:outline focus-visible:-outline-offset-2 focus-visible:outline-accent',
                    selected === tag.key ? 'bg-accent-bg' : 'hover:bg-surface-2',
                  )}
                >
                  <StatusDot tag={tag} busy={busy.has(tag.key)} streaming={current === tag.key} />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate font-mono text-xs text-ink">
                      {`{{${tag.key}}}`}
                    </span>
                    <span className="block truncate text-xs text-muted">{tagTitle(tag)}</span>
                  </span>
                  <span className="shrink-0 font-mono text-[10px] text-muted">{i + 1}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      {footer && <div className="border-t border-line p-s3">{footer}</div>}
    </div>
  )
}

/** Точка состояния: идёт прогон, сделано моделью, написано рукой, пусто. */
function StatusDot({
  tag,
  busy,
  streaming,
}: {
  tag: ProjectTag
  busy: boolean
  streaming: boolean
}) {
  const t = useT()
  if (streaming) return <Spinner size={12} className="shrink-0" />
  if (busy) return <Icon name="clock" size={12} className="shrink-0 text-muted" />
  const агент = tag.source === 'agent'
  const подпись = tag.filled
    ? агент
      ? t('reports.tags.state.agent')
      : t('reports.tags.state.manual')
    : t('reports.tags.state.empty')
  return (
    <span
      title={подпись}
      aria-label={подпись}
      role="img"
      className={cn(
        'h-2.5 w-2.5 shrink-0 rounded-full border',
        tag.filled
          ? агент
            ? 'border-agent bg-agent'
            : 'border-ok bg-ok'
          : 'border-line-strong bg-transparent',
      )}
    />
  )
}
