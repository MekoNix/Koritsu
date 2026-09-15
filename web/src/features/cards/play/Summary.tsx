/**
 * Summary — итоги захода.
 *
 * «Да N · Нет M» по карточкам, а не по нажатиям: карточка, которая вернулась
 * повтором и со второго раза получила «Да», считается один раз, по последней
 * оценке. Под счётом — список «Нет»: вопрос виден сразу, ответ и разбор
 * раскрываются по нажатию, чтобы итоги читались списком, а не простынёй.
 *
 * «Повторить «Нет»» заводит новый заход (`preset: 'wrong'`): служба берёт
 * карточки с последним ответом «Нет», и эти в их числе.
 */
import { useState } from 'react'
import { Link } from 'react-router-dom'

import { useT } from '@/i18n'
import { cn } from '@/lib/cn'
import { Button, Icon, Skeleton } from '@/ui'

import { CardView } from '../components/CardView'
import type { CardItem } from '../types'

import type { Tally } from './queue'

export interface SummaryProps {
  title?: string
  tally: Tally
  cardOf: (key: string) => CardItem | null | undefined
  setHref: string
  phone: boolean
  repeating: boolean
  onRepeatWrong: () => void
  /** Вернуться к последнему вопросу, чтобы изменить оценку. */
  onBack: () => void
}

export function Summary({ title, tally, cardOf, setHref, phone, repeating, onRepeatWrong, onBack }: SummaryProps) {
  const t = useT()
  const [open, setOpen] = useState<string | null>(null)

  return (
    <div className={cn('mx-auto w-full max-w-[72ch]', phone ? 'px-s4 py-s5' : 'py-s4')}>
      <h1 className="font-display text-xl font-semibold text-ink-strong">{t('cards.play.summary.title')}</h1>
      {title && <p className="mt-s1 truncate text-sm text-muted">{title}</p>}

      <p className="mt-s5 font-display text-2xl font-semibold" aria-live="polite">
        <span className="text-ok">{t('cards.play.tally.yes', { n: tally.yes })}</span>
        <span className="mx-s2 text-muted">·</span>
        <span className="text-err">{t('cards.play.tally.no', { n: tally.no })}</span>
      </p>

      <div className={cn('mt-s5 flex gap-s2', phone ? 'flex-col' : 'flex-wrap')}>
        {tally.no > 0 && (
          <Button
            type="button"
            variant="primary"
            size="lg"
            loading={repeating}
            className={cn(phone && 'h-12 w-full')}
            onClick={onRepeatWrong}
          >
            <Icon name="restore" size={18} />
            {t('cards.play.summary.repeatWrong', { n: tally.no })}
          </Button>
        )}
        <Button asChild variant={tally.no > 0 ? 'secondary' : 'primary'} size="lg" className={cn(phone && 'h-12 w-full')}>
          <Link to={setHref}>{t('cards.play.summary.toSet')}</Link>
        </Button>
        <Button type="button" variant="ghost" size="lg" className={cn(phone && 'h-12 w-full')} onClick={onBack}>
          <Icon name="arrowLeft" size={18} />
          {t('cards.play.summary.back')}
        </Button>
      </div>

      {tally.no > 0 && (
        <section className="mt-s6">
          <h2 className="mb-s3 text-sm font-semibold text-muted">{t('cards.play.summary.wrongList')}</h2>
          <ul className="flex flex-col gap-s2">
            {tally.wrong.map((key) => {
              const card = cardOf(key)
              const expanded = open === key
              const panel = `cards-play-wrong-${key}`
              return (
                <li key={key} className="rounded-md border border-line bg-surface">
                  {card === undefined ? (
                    <div className="p-s4">
                      <Skeleton className="w-3/4" />
                    </div>
                  ) : card === null ? (
                    <p className="p-s4 text-sm text-muted">{t('cards.play.card.missing')}</p>
                  ) : (
                    <>
                      <button
                        type="button"
                        aria-expanded={expanded}
                        aria-controls={panel}
                        onClick={() => setOpen(expanded ? null : key)}
                        className="flex min-h-[48px] w-full items-start gap-s3 rounded-md p-s4 text-left hover:bg-surface-2"
                      >
                        <Icon
                          name="chevronRight"
                          size={18}
                          className={cn('mt-0.5 shrink-0 text-muted transition-transform motion-reduce:transition-none', expanded && 'rotate-90')}
                        />
                        <CardView md={card.q} className="min-w-0 flex-1 text-md text-ink-strong" />
                      </button>
                      {expanded && (
                        <div id={panel} className="border-t border-line px-s4 pb-s4 pt-s3 pl-[calc(var(--space-4)+18px+var(--space-3))]">
                          <CardView md={card.a} className="text-md text-ink" />
                          {card.note && (
                            <div className="mt-s3 rounded-md bg-[var(--card-back)] p-s3">
                              <div className="mb-s1 text-xs font-semibold text-muted">{t('cards.play.card.note')}</div>
                              <CardView md={card.note} className="text-sm text-ink" />
                            </div>
                          )}
                        </div>
                      )}
                    </>
                  )}
                </li>
              )
            })}
          </ul>
        </section>
      )}
    </div>
  )
}
