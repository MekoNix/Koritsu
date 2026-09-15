/**
 * CardStage — карточка захода и кнопки под ней.
 *
 * **Карточка.** Вопрос крупно; короткий вопрос в одну строку — по центру,
 * длинный и многострочный — от левого края, иначе таблица или код в вопросе
 * читаются рваными строками. Ответ появляется под вопросом, разбор под ним
 * свёрнут. Длинная формула прокручивается внутри карточки (`CardView`), а не
 * раздвигает страницу.
 *
 * **Свайп на телефоне** повторяет нижние кнопки, а не живёт своей жизнью: пока
 * ответ не показан, вправо — «Да», влево — «Нет», и карточка остаётся на месте,
 * раскрывая ответ; после показа вправо — «Верно», влево — «Неверно», и карточка
 * улетает к следующему вопросу. Жест берётся, только
 * когда палец ушёл вбок заметно больше, чем вверх или вниз: вертикальная
 * прокрутка длинного ответа остаётся за браузером (`touch-action: pan-y`).
 * Касание, начатое на формуле, которая сама прокручивается вбок, свайпом не
 * считается — иначе формулу нельзя было бы дочитать. Порог — четверть ширины
 * карточки, но не меньше 80 px; не дотянул — карточка возвращается на место.
 * При `prefers-reduced-motion` карточка не улетает, оценка ставится сразу.
 */
import { forwardRef, useRef, useState, type PointerEvent as ReactPointerEvent, type ReactNode } from 'react'

import { useT } from '@/i18n'
import { cn } from '@/lib/cn'
import { Button, ErrorState, Icon, SkeletonLines } from '@/ui'

import { CardView } from '../components/CardView'
import type { CardItem } from '../types'

import type { Step } from './queue'
import type { Answer } from './requests'

/** Короче этого вопрос в одну строку ставится по центру. */
const SHORT_QUESTION = 140
/** Время вылета карточки после свайпа. */
const FLY_MS = 180

function reducedMotion(): boolean {
  try {
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches
  } catch {
    return false
  }
}

/** Касание внутри элемента, который сам прокручивается вбок. */
function insideHorizontalScroll(target: EventTarget | null, root: HTMLElement): boolean {
  let el = target as HTMLElement | null
  while (el && el !== root) {
    if (el.scrollWidth > el.clientWidth + 1) {
      const overflow = getComputedStyle(el).overflowX
      if (overflow === 'auto' || overflow === 'scroll') return true
    }
    el = el.parentElement
  }
  return false
}

export function Kbd({ children }: { children: ReactNode }) {
  return (
    <kbd className="ml-s2 inline-flex min-w-[20px] items-center justify-center rounded-sm border border-line px-1 font-mono text-[11px] font-normal leading-4 text-muted">
      {children}
    </kbd>
  )
}

// ── карточка ─────────────────────────────────────────────────────────────────

export interface CardStageProps {
  step: Step
  card: CardItem | null | undefined
  /** Название темы карточки; `card.topic` — это id (slug), человеку его не показывают. */
  topicTitle?: string | null
  cardError: unknown
  onRetryCards: () => void
  phone: boolean
  copied: boolean
  onCopy: () => void
  /**
   * Свайп со сработавшим порогом; только на телефоне. Что значит ответ, решает
   * страница: до показа ответа это догадка, после — сверка.
   */
  onSwipe?: (answer: Answer) => void
}

export const CardStage = forwardRef<HTMLDivElement, CardStageProps>(function CardStage(
  { step, card, topicTitle, cardError, onRetryCards, phone, copied, onCopy, onSwipe },
  ref,
) {
  const t = useT()
  const surface = useRef<HTMLDivElement | null>(null)
  const drag = useRef<{ id: number; x: number; y: number; lock: 'h' | null } | null>(null)
  const [dx, setDx] = useState(0)
  const [dragging, setDragging] = useState(false)

  const swipeOn = phone && !!onSwipe && !!card

  const threshold = () => Math.max(80, (surface.current?.offsetWidth ?? 320) * 0.25)

  function down(e: ReactPointerEvent<HTMLDivElement>) {
    if (!swipeOn || !surface.current) return
    if (e.pointerType === 'mouse' && e.button !== 0) return
    if (insideHorizontalScroll(e.target, surface.current)) return
    drag.current = { id: e.pointerId, x: e.clientX, y: e.clientY, lock: null }
  }

  function move(e: ReactPointerEvent<HTMLDivElement>) {
    const d = drag.current
    if (!d || e.pointerId !== d.id) return
    const mx = e.clientX - d.x
    const my = e.clientY - d.y
    if (!d.lock) {
      if (Math.abs(mx) > 10 && Math.abs(mx) > Math.abs(my) * 1.2) {
        d.lock = 'h'
        setDragging(true)
        try {
          surface.current?.setPointerCapture(e.pointerId)
        } catch {
          // Захват не обязателен: без него жест просто оборвётся за краем.
        }
      } else if (Math.abs(my) > 10) {
        drag.current = null
        return
      } else {
        return
      }
    }
    setDx(mx)
  }

  function up(e: ReactPointerEvent<HTMLDivElement>) {
    const d = drag.current
    if (!d || e.pointerId !== d.id) return
    drag.current = null
    setDragging(false)
    if (d.lock !== 'h') return
    const distance = e.clientX - d.x
    if (Math.abs(distance) < threshold() || !onSwipe) {
      setDx(0)
      return
    }
    const answer: Answer = distance > 0 ? 'yes' : 'no'
    // Догадка до показа ответа оставляет заход на карточке: улетевшая и тут же
    // вернувшаяся карточка выглядела бы сбоем.
    if (reducedMotion() || !step.shown) {
      setDx(0)
      onSwipe(answer)
      return
    }
    const width = surface.current?.offsetWidth ?? 320
    setDx(Math.sign(distance) * width * 1.2)
    window.setTimeout(() => {
      setDx(0)
      onSwipe(answer)
    }, FLY_MS)
  }

  function cancel() {
    drag.current = null
    setDragging(false)
    setDx(0)
  }

  const strength = Math.min(Math.abs(dx) / threshold(), 1)
  const short = !!card && card.q.length <= SHORT_QUESTION && !card.q.includes('\n')

  return (
    <div
      ref={(el) => {
        surface.current = el
        if (typeof ref === 'function') ref(el)
        else if (ref) ref.current = el
      }}
      tabIndex={-1}
      role="group"
      aria-label={t('cards.play.card.label')}
      onPointerDown={down}
      onPointerMove={move}
      onPointerUp={up}
      onPointerCancel={cancel}
      style={{
        transform: dx ? `translateX(${dx}px) rotate(${dx / 40}deg)` : undefined,
        touchAction: swipeOn ? 'pan-y' : undefined,
      }}
      className={cn(
        'relative flex min-w-0 flex-col rounded-lg border border-line bg-[var(--card-front)] shadow-1 outline-none',
        'focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent',
        !dragging && 'transition-transform duration-200 ease-out motion-reduce:transition-none',
        // На телефоне карточка не растянута на весь экран, а по высоте
        // содержимого: место под ней отдаёт подсказке о свайпе, а вопрос стоит
        // сразу под темой. Длинный ответ не раздвигает экран — карточка сжимается
        // до свободной высоты (`min-h-0`) и прокручивается внутри себя.
        phone ? 'min-h-0 overflow-y-auto overscroll-contain p-s4' : 'p-s6',
      )}
    >
      {swipeOn && strength > 0 && (
        <div
          aria-hidden="true"
          style={{ opacity: strength }}
          className={cn(
            'pointer-events-none absolute top-s4 rounded-md border-2 px-s3 py-s1 font-display text-lg font-semibold',
            dx > 0 ? 'left-s4 border-ok bg-ok-bg text-ok' : 'right-s4 border-err bg-err-bg text-err',
          )}
        >
          {dx > 0
            ? t(step.shown ? 'cards.play.right' : 'cards.play.yes')
            : t(step.shown ? 'cards.play.wrong' : 'cards.play.no')}
        </div>
      )}

      <div className="mb-s4 flex min-h-[28px] flex-wrap items-center gap-s2 text-xs text-muted">
        {card && topicTitle && (
          <span className="truncate rounded-full bg-surface-2 px-s2 py-0.5 font-semibold">{topicTitle}</span>
        )}
        {step.round > 0 && (
          <span className="inline-flex items-center gap-1 rounded-full bg-accent-bg px-s2 py-0.5 text-accent">
            <Icon name="restore" size={14} />
            {t('cards.play.card.repeat')}
          </span>
        )}
        {card?.changed && (
          <span
            className="inline-flex items-center gap-1 rounded-full bg-warn-bg px-s2 py-0.5 text-warn"
            title={t('cards.play.card.changedHint')}
          >
            <Icon name="warning" size={14} />
            {t('cards.play.card.changed')}
          </span>
        )}
        <span className="flex-1" />
        {card && !phone && (
          <Button type="button" variant="ghost" size="sm" onClick={onCopy}>
            <Icon name={copied ? 'check' : 'copy'} size={16} />
            {copied ? t('common.action.copied') : t('common.action.copy')}
            <Kbd>C</Kbd>
          </Button>
        )}
      </div>

      {cardError != null && card === undefined ? (
        <ErrorState error={cardError} onRetry={onRetryCards} title={t('cards.play.card.loadFailed')} />
      ) : card === undefined ? (
        <SkeletonLines count={4} />
      ) : card === null ? (
        <div className="py-s6 text-center text-muted">
          <p className="font-display text-lg font-semibold text-ink-strong">{t('cards.play.card.missing')}</p>
          <p className="mt-s2 text-sm">{t('cards.play.card.missingHint')}</p>
        </div>
      ) : (
        <div className="flex min-w-0 flex-col">
          <CardView
            md={card.q}
            className={cn(
              'font-semibold leading-snug text-ink-strong',
              phone ? 'text-xl' : 'text-2xl',
              short && 'text-center',
            )}
          />
          {step.shown && (
            // Ответ — своя плашка с цветной кромкой, а не продолжение вопроса за
            // линейкой: на экране сразу видно, где кончился вопрос.
            <section
              aria-label={t('cards.play.card.answer')}
              className="mt-s5 rounded-md border-l-4 border-accent bg-[var(--card-back)] p-s4"
            >
              <div className="mb-s2 text-sm font-semibold text-ink-strong">{t('cards.play.card.answer')}</div>
              <CardView md={card.a} className="text-md text-ink" />
              {card.note && (
                <details className="group mt-s4 rounded-md border border-line bg-surface">
                  <summary className="flex min-h-[44px] cursor-pointer select-none items-center gap-s2 px-s3 text-sm font-semibold text-ink">
                    <Icon name="chevronRight" size={16} className="transition-transform group-open:rotate-90 motion-reduce:transition-none" />
                    {t('cards.play.card.note')}
                  </summary>
                  <div className="px-s3 pb-s3">
                    <CardView md={card.note} className="text-sm text-ink" />
                  </div>
                </details>
              )}
            </section>
          )}
        </div>
      )}
    </div>
  )
})

// ── кнопки ───────────────────────────────────────────────────────────────────

export interface PlayControlsProps {
  step: Step
  card: CardItem | null | undefined
  phone: boolean
  onReveal: () => void
  /** Оценка до показа ответа — догадка: ответ раскроется, заход останется. */
  onGrade: (answer: Answer) => void
  /** Сверка после показа ответа: она и есть итоговая оценка, дальше — шаг. */
  onConfirm: (answer: Answer) => void
  onNext: () => void
}

/**
 * Цвет оценок. «Да» и «Нет» окрашены всегда, а не только после нажатия: на
 * телефоне их ищут большим пальцем, не читая, и цвет опознаётся быстрее слова.
 * Выбранная оценка заливается целиком — видно, что она уже стоит, и при этом
 * зелёное с красным не спорят за внимание.
 */
function gradeClass(answer: Answer, picked: boolean): string {
  if (answer === 'yes') {
    return picked
      ? 'border-ok bg-ok text-white hover:bg-ok'
      : 'border-ok bg-ok-bg text-ok hover:bg-ok-bg hover:brightness-105'
  }
  return picked
    ? 'border-err bg-err text-white hover:bg-err'
    : 'border-err bg-err-bg text-err hover:bg-err-bg hover:brightness-105'
}

export const PlayControls = forwardRef<HTMLDivElement, PlayControlsProps>(function PlayControls(
  { step, card, phone, onReveal, onGrade, onConfirm, onNext },
  ref,
) {
  const t = useT()
  const picked = step.grade?.answer
  const ready = !!card

  if (card === null) {
    return (
      <div ref={ref} className={cn('flex justify-center', phone && 'px-s3 pt-s3')} style={phone ? bottomInset : undefined}>
        <Button type="button" variant="primary" size="lg" className={cn(phone && 'h-14 w-full')} onClick={onNext}>
          {t('cards.play.next')}
          {!phone && <Kbd>Space</Kbd>}
        </Button>
      </div>
    )
  }

  if (phone) {
    return (
      <div ref={ref} className="shrink-0 border-t border-line bg-surface px-s3 pt-s3" style={bottomInset}>
        {step.shown ? (
          <>
            <p className="mb-s2 m-0 text-center text-xs text-muted">{t('cards.play.checkHint')}</p>
            <div className="grid grid-cols-2 gap-s2">
              <Button
                type="button"
                size="lg"
                className={cn('h-14 text-md', gradeClass('no', false))}
                disabled={!ready}
                onClick={() => onConfirm('no')}
              >
                <Icon name="close" size={18} />
                {t('cards.play.wrong')}
              </Button>
              <Button
                type="button"
                size="lg"
                className={cn('h-14 text-md', gradeClass('yes', false))}
                disabled={!ready}
                onClick={() => onConfirm('yes')}
              >
                <Icon name="check" size={18} />
                {t('cards.play.right')}
              </Button>
            </div>
          </>
        ) : (
          <>
            <Button
              type="button"
              variant="secondary"
              size="lg"
              className="mb-s2 h-12 w-full"
              disabled={!ready}
              onClick={onReveal}
            >
              <Icon name="eye" size={18} />
              {t('cards.play.reveal')}
            </Button>
            <div className="grid grid-cols-2 gap-s2">
              <Button
                type="button"
                size="lg"
                aria-pressed={picked === 'no'}
                className={cn('h-14 text-md', gradeClass('no', picked === 'no'))}
                disabled={!ready}
                onClick={() => onGrade('no')}
              >
                <Icon name="close" size={18} />
                {t('cards.play.no')}
              </Button>
              <Button
                type="button"
                size="lg"
                aria-pressed={picked === 'yes'}
                className={cn('h-14 text-md', gradeClass('yes', picked === 'yes'))}
                disabled={!ready}
                onClick={() => onGrade('yes')}
              >
                <Icon name="check" size={18} />
                {t('cards.play.yes')}
              </Button>
            </div>
          </>
        )}
      </div>
    )
  }

  if (step.shown) {
    return (
      <div ref={ref} className="mt-s5 flex flex-col items-center gap-s3">
        <p className="m-0 text-sm text-muted">{t('cards.play.checkHint')}</p>
        <div className="flex flex-wrap items-center justify-center gap-s2">
          <Button
            type="button"
            size="lg"
            className={gradeClass('yes', false)}
            disabled={!ready}
            onClick={() => onConfirm('yes')}
          >
            <Icon name="check" size={18} />
            {t('cards.play.right')}
            <Kbd>1</Kbd>
          </Button>
          <Button
            type="button"
            size="lg"
            className={gradeClass('no', false)}
            disabled={!ready}
            onClick={() => onConfirm('no')}
          >
            <Icon name="close" size={18} />
            {t('cards.play.wrong')}
            <Kbd>2</Kbd>
          </Button>
        </div>
      </div>
    )
  }

  return (
    <div ref={ref} className="mt-s5 flex flex-col items-center gap-s3">
      <div className="flex flex-wrap items-center justify-center gap-s2">
        <Button type="button" variant="primary" size="lg" disabled={!ready} onClick={onReveal}>
          <Icon name="eye" size={18} />
          {t('cards.play.reveal')}
          <Kbd>Space</Kbd>
        </Button>
        <Button
          type="button"
          size="lg"
          aria-pressed={picked === 'yes'}
          className={gradeClass('yes', picked === 'yes')}
          disabled={!ready}
          onClick={() => onGrade('yes')}
        >
          <Icon name="check" size={18} />
          {t('cards.play.yes')}
          <Kbd>1</Kbd>
        </Button>
        <Button
          type="button"
          size="lg"
          aria-pressed={picked === 'no'}
          className={gradeClass('no', picked === 'no')}
          disabled={!ready}
          onClick={() => onGrade('no')}
        >
          <Icon name="close" size={18} />
          {t('cards.play.no')}
          <Kbd>2</Kbd>
        </Button>
      </div>
    </div>
  )
})

/** Нижние кнопки телефона не уходят под полосу жестов и вырез экрана. */
const bottomInset = { paddingBottom: 'max(env(safe-area-inset-bottom), 12px)' } as const
