/**
 * CardsList — карточки набора: поиск, фильтр темы, ответ по раскрытию.
 *
 * Список нужен, чтобы найти карточку и проверить её текст, а не чтобы решать: ответ
 * скрыт и раскрывается нажатием на карточку или на стрелку. Стрелка — настоящая кнопка
 * (клавиатура, скринридер), нажатие на саму карточку — удобство для пальца; выделение
 * текста мышью карточку не переключает.
 *
 * Карточки приходят страницами по 50 (`from`/`to`), поиск уходит в службу с задержкой
 * 300 мс; пока новая страница в пути, прежний список остаётся на экране.
 */
import { forwardRef, useEffect, useState } from 'react'

import { useT } from '@/i18n'
import { cn } from '@/lib/cn'
import { Button, Chip, EmptyState, ErrorState, Icon, Input, Select, SkeletonLines } from '@/ui'

import { useCards } from '../api'
import { NO_TOPIC, type CardItem, type CardTopic } from '../types'
import { CardView } from './CardView'

const СТРАНИЦА = 50

export type CardsListProps = {
  projectId: string
  setId: string
  topics: CardTopic[]
  hasNoTopic: boolean
  /** id темы фильтра, `NO_TOPIC` — без темы, `''` — все. */
  topic: string
  onTopic: (topic: string) => void
}

export const CardsList = forwardRef<HTMLElement, CardsListProps>(function CardsList(
  { projectId, setId, topics, hasNoTopic, topic, onTopic },
  ref,
) {
  const t = useT()
  const [запрос, setЗапрос] = useState('')
  const [q, setQ] = useState('')
  const [до, setДо] = useState(СТРАНИЦА)
  const [открытые, setОткрытые] = useState<ReadonlySet<string>>(new Set())

  useEffect(() => {
    const таймер = window.setTimeout(() => setQ(запрос.trim()), 300)
    return () => window.clearTimeout(таймер)
  }, [запрос])

  useEffect(() => {
    setДо(СТРАНИЦА)
  }, [q, topic])

  const cards = useCards(projectId, setId, { from: 0, to: до, ...(q ? { q } : {}), ...(topic ? { topic } : {}) })
  const названия = new Map(topics.map((x) => [x.id, x.title]))

  const переключить = (key: string) =>
    setОткрытые((было) => {
      const стало = new Set(было)
      if (стало.has(key)) стало.delete(key)
      else стало.add(key)
      return стало
    })

  const список = cards.data?.cards ?? []
  const всего = cards.data?.total ?? 0

  return (
    <section ref={ref} aria-labelledby="cards-list-title" className="flex min-w-0 flex-col gap-s3 scroll-mt-[calc(var(--topbar-h)+var(--space-3))]">
      <h2 id="cards-list-title" className="m-0 font-display text-lg font-semibold text-ink-strong">
        {t('cards.set.cards')}
      </h2>

      <div className="flex flex-col gap-s2 min-[641px]:flex-row min-[641px]:items-end">
        <Input
          value={запрос}
          type="search"
          placeholder={t('cards.set.search')}
          aria-label={t('cards.set.search')}
          icon={<Icon name="search" size={16} />}
          className="max-[640px]:min-h-[44px] max-[640px]:text-md"
          wrapperClassName="min-w-0 flex-1 min-[641px]:max-w-[420px]"
          onChange={(e) => setЗапрос(e.target.value)}
        />
        {(topics.length > 0 || hasNoTopic) && (
          <div className="min-[641px]:w-[260px]">
            <Select
              value={topic}
              aria-label={t('cards.set.topicFilter')}
              className="max-[640px]:min-h-[44px] max-[640px]:text-md"
              onChange={(e) => onTopic(e.target.value)}
            >
              <option value="">{t('cards.set.allTopics')}</option>
              {topics.map((x) => (
                <option key={x.id} value={x.id}>
                  {x.title}
                </option>
              ))}
              {hasNoTopic && <option value={NO_TOPIC}>{t('cards.common.noTopic')}</option>}
            </Select>
          </div>
        )}
      </div>

      {cards.isPending ? (
        <SkeletonLines count={5} />
      ) : cards.isError ? (
        <ErrorState error={cards.error} onRetry={() => void cards.refetch()} />
      ) : список.length === 0 ? (
        <EmptyState compact icon="search" title={t('cards.set.nothingFound')} />
      ) : (
        <>
          <ul className={cn('m-0 flex list-none flex-col gap-s2 p-0', cards.isPlaceholderData && 'opacity-60')}>
            {список.map((c) => (
              <CardRow
                key={c.key}
                card={c}
                open={открытые.has(c.key)}
                topicTitle={c.topic ? (названия.get(c.topic) ?? null) : topics.length ? t('cards.common.noTopic') : null}
                onToggle={() => переключить(c.key)}
              />
            ))}
          </ul>
          <div className="flex flex-wrap items-center justify-between gap-s2">
            <span className="text-xs text-muted">{t('cards.set.shown', { n: список.length, total: всего })}</span>
            {список.length < всего && (
              <Button
                variant="secondary"
                loading={cards.isFetching}
                onClick={() => setДо((x) => x + СТРАНИЦА)}
                className="max-[640px]:min-h-[44px] max-[640px]:w-full"
              >
                {t('cards.set.more')}
              </Button>
            )}
          </div>
        </>
      )}
    </section>
  )
})

function CardRow({
  card,
  open,
  topicTitle,
  onToggle,
}: {
  card: CardItem
  open: boolean
  topicTitle: string | null
  onToggle: () => void
}) {
  const t = useT()
  return (
    <li className="min-w-0 rounded-md border border-line bg-surface shadow-1">
      <div
        className="flex min-h-[44px] cursor-pointer items-start gap-s2 px-s4 py-s3 max-[640px]:px-s3"
        onClick={() => {
          // Выделяли текст — не переключаем.
          if (window.getSelection()?.toString()) return
          onToggle()
        }}
      >
        <div className="flex min-w-0 flex-1 flex-col gap-s2">
          <CardView md={card.q} className="text-sm font-medium text-ink-strong" />
          {(topicTitle || card.changed || card.my_last) && (
            <div className="flex flex-wrap items-center gap-s2">
              {topicTitle && <span className="break-words text-xs text-muted">{topicTitle}</span>}
              {card.changed && <Chip tone="warn">{t('cards.common.changed')}</Chip>}
              {card.my_last === 'yes' && <Chip tone="ok">{t('cards.common.lastYes')}</Chip>}
              {card.my_last === 'no' && <Chip tone="err">{t('cards.common.lastNo')}</Chip>}
            </div>
          )}
        </div>
        <Button
          variant="ghost"
          size="sm"
          iconOnly
          aria-expanded={open}
          aria-label={open ? t('cards.set.hideAnswer') : t('cards.set.showAnswer')}
          className="-mr-s2 -mt-1 text-muted max-[640px]:h-11 max-[640px]:w-11"
        >
          <Icon name={open ? 'chevronUp' : 'chevronDown'} size={18} />
        </Button>
      </div>
      {open && (
        <div className="flex flex-col gap-s2 border-t border-line px-s4 py-s3 max-[640px]:px-s3">
          <CardView md={card.a} className="text-sm text-ink" />
          {card.note && (
            <details className="rounded-sm bg-surface-2 px-s3">
              <summary className="flex min-h-[40px] cursor-pointer items-center text-xs font-semibold uppercase tracking-wider text-muted">
                {t('cards.set.note')}
              </summary>
              <div className="pb-s3">
                <CardView md={card.note} className="text-sm text-muted" />
              </div>
            </details>
          )}
        </div>
      )}
    </li>
  )
}
