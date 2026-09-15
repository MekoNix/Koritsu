/**
 * PlayPage — заход и итоги, `/cards/:projectId/:setId/play`.
 *
 * **Как сюда попадают.** Страница набора заводит заход (`POST …/sessions`) и
 * переходит сюда с `?s=<session_id>` и ответом службы в состоянии навигации:
 * ключи и первые карточки уже на руках, второго запроса за ними нет. Id
 * захода всегда оказывается в адресе — перезагрузка и закладка открывают тот
 * же заход. Без id страница предлагает «Продолжить» мой незаконченный заход
 * набора (моложе 12 часов, с любого устройства — `GET …/sessions/open`) или
 * «Начать по настройкам».
 *
 * **Две раскладки.** Компьютер: карточка по центру шириной чтения, кнопки под
 * ней, клавиатура. Телефон (≤ 640 px): заход занимает весь экран поверх
 * оболочки, шапка в одну строку, «Показать ответ» и «Да»/«Нет» внизу под
 * большим пальцем, свайп по карточке.
 *
 * **Оценка до показа — догадка, после показа — сверка.** «Да» и «Нет» до
 * показа ответа его и раскрывают, оставляя заход на карточке: ради ответа
 * карточку и решают, а оценка вслепую уносила бы вопрос, так и не показав, как
 * правильно. Дальше стоят «Верно» и «Неверно» — они пишут итоговую оценку (если
 * она разошлась с догадкой, попытка исправляется) и ведут к следующему вопросу.
 * Свайп повторяет те же кнопки: до показа ответа вправо — «Да», влево — «Нет»,
 * после показа — «Верно» и «Неверно».
 *
 * **Путь назад.** Сверка уводит к следующему вопросу, поэтому сразу после неё
 * внизу на несколько секунд появляется полоса «Отменить» — и на телефоне, и на
 * компьютере. Она возвращает заход на ту же карточку, где оценку и ставят
 * заново; та же отмена на клавише `U`. Менять оценку «вслепую», уже уйдя с
 * карточки, нечестно: непонятно, какой вопрос правится.
 *
 * **Клавиатура** (компьютер и телефон с клавиатурой): `Space` — показать
 * ответ, а после оценки — следующий вопрос; `1` — «Да», `2` — «Нет», `U` —
 * отменить последнюю оценку, `C` — скопировать, `Esc` — выйти, `?` — список
 * сокращений. Клавиши
 * берутся по физическому месту (`event.code`), чтобы `U` и `C` работали и в
 * русской раскладке. Нажатия в полях ввода, с `Ctrl`/`Alt`/`Cmd` и при
 * открытом окне не перехватываются. Фокус после каждого действия
 * возвращается на карточку, а не остаётся на кнопке: иначе `Space` нажимал бы
 * кнопку, а не вёл по заходу.
 *
 * **Выход** подтверждается, если оценено меньше половины вопросов захода:
 * заход не пропадает — его можно продолжить, но случайный `Esc` посреди
 * захода не должен уводить со страницы.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate, useParams, useSearchParams } from 'react-router-dom'

import { useDocumentCrumb } from '@/app/shell/breadcrumbs'
import { useT } from '@/i18n'
import { cn } from '@/lib/cn'
import { Button, Dialog, DialogClose, EmptyState, ErrorState, Icon, SkeletonLines, useToast } from '@/ui'

import { startSession, useCardSet, useInvalidateProgress, useOpenSession } from '../api'
import { useIsPhone } from '../hooks/useIsPhone'
import type { CardTopic, SessionPreset, SessionStart } from '../types'

import { CardStage, Kbd, PlayControls } from './CardStage'
import { cardMarkdown, gradedCount } from './queue'
import { repeatWrongOf, type Answer } from './requests'
import { Summary } from './Summary'
import { readLastSession, usePlay } from './usePlay'

/** Сколько живёт «Отменить» после сверки. */
const UNDO_MS = 3000
/** Просвет между полосой «Отменить» и нижними кнопками телефона. */
const UNDO_GAP = 12

/** Ответ `POST …/sessions` из состояния навигации: `{start}` или он сам. */
function startOf(state: unknown): SessionStart | null {
  const s = (state as { start?: unknown } | null)?.start ?? state
  if (!s || typeof s !== 'object') return null
  const x = s as Partial<SessionStart>
  return typeof x.session_id === 'string' && Array.isArray(x.keys) ? (s as SessionStart) : null
}

function playHref(projectId: string, setId: string, sid: string): string {
  return `/cards/${projectId}/${setId}/play?s=${encodeURIComponent(sid)}`
}

/** Фокус в поле ввода — клавиши принадлежат полю. */
function typing(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null
  if (!el) return false
  if (el.isContentEditable) return true
  if (el.tagName === 'TEXTAREA' || el.tagName === 'SELECT') return true
  if (el.tagName === 'INPUT') {
    const type = (el as HTMLInputElement).type
    return type !== 'checkbox' && type !== 'radio' && type !== 'button' && type !== 'range'
  }
  return false
}

/** Заход новым запросом и переход в него. */
function useStartSession(projectId: string, setId: string) {
  const navigate = useNavigate()
  const toast = useToast()
  const t = useT()
  const [busy, setBusy] = useState<SessionPreset | null>(null)
  const start = useCallback(
    async (preset: SessionPreset) => {
      setBusy(preset)
      try {
        const res = await startSession(projectId, setId, preset)
        navigate(playHref(projectId, setId, res.session_id), { state: { start: res } })
      } catch (e) {
        toast.fail(e, t('cards.play.startFailed'))
      } finally {
        setBusy(null)
      }
    },
    [navigate, projectId, setId, t, toast],
  )
  return { start, busy }
}

export default function PlayPage() {
  const { projectId = '', setId = '' } = useParams()
  const [params] = useSearchParams()
  const location = useLocation()
  const navigate = useNavigate()
  const set = useCardSet(projectId, setId)
  useDocumentCrumb(set.data?.title)

  const start = startOf(location.state)
  const fromUrl = params.get('s')
  const sid = fromUrl ?? start?.session_id ?? null

  // Id только в состоянии навигации — дописать в адрес, чтобы пережил перезагрузку.
  useEffect(() => {
    if (sid && !fromUrl) navigate(playHref(projectId, setId, sid), { replace: true, state: location.state })
  }, [sid, fromUrl, navigate, projectId, setId, location.state])

  if (!sid) return <PlayGate projectId={projectId} setId={setId} title={set.data?.title} loading={set.isLoading} />

  return (
    <PlaySession
      key={sid}
      projectId={projectId}
      setId={setId}
      sessionId={sid}
      start={start?.session_id === sid ? start : null}
      title={set.data?.title}
      topics={set.data?.topics}
      repeatWrong={repeatWrongOf(set.data)}
    />
  )
}

// ── без захода в адресе ──────────────────────────────────────────────────────

function PlayGate({ projectId, setId, title, loading }: { projectId: string; setId: string; title?: string; loading: boolean }) {
  const t = useT()
  const navigate = useNavigate()
  const phone = useIsPhone()
  const open = useOpenSession(projectId, setId)
  // Служба знает заход с любого устройства; запись браузера — запасной путь, пока
  // служба не ответила или недоступна.
  const [local] = useState(() => readLastSession(setId))
  const last = open.isSuccess ? (open.data?.session_id ?? null) : local
  const { start, busy } = useStartSession(projectId, setId)
  const setHref = `/cards/${projectId}/${setId}`

  return (
    <div className={cn('mx-auto flex w-full max-w-md flex-col gap-s4', phone ? 'px-s1 py-s4' : 'py-s8')}>
      {loading ? (
        <SkeletonLines count={2} />
      ) : (
        <div>
          <h1 className="font-display text-xl font-semibold text-ink-strong">{title ?? t('cards.play.gate.title')}</h1>
          <p className="mt-s1 text-sm text-muted">{last ? t('cards.play.gate.hasLast') : t('cards.play.gate.noLast')}</p>
        </div>
      )}
      <div className="flex flex-col gap-s2">
        {last && (
          <Button
            type="button"
            variant="primary"
            size="lg"
            className="h-12"
            onClick={() => navigate(playHref(projectId, setId, last), { replace: true })}
          >
            <Icon name="restore" size={18} />
            {t('cards.play.gate.continue')}
          </Button>
        )}
        <Button
          type="button"
          variant={last ? 'secondary' : 'primary'}
          size="lg"
          className="h-12"
          loading={busy === 'settings'}
          disabled={busy !== null}
          onClick={() => void start('settings')}
        >
          {t('cards.play.gate.start')}
        </Button>
        <Button type="button" variant="ghost" size="lg" className="h-12" onClick={() => navigate(setHref)}>
          <Icon name="arrowLeft" size={18} />
          {t('cards.play.summary.toSet')}
        </Button>
      </div>
    </div>
  )
}

// ── заход ────────────────────────────────────────────────────────────────────

interface PlaySessionProps {
  projectId: string
  setId: string
  sessionId: string
  start: SessionStart | null
  title?: string
  /** Темы набора: у карточки `topic` — id, на экране — название. */
  topics?: CardTopic[]
  repeatWrong: boolean
}

function PlaySession({ projectId, setId, sessionId, start, title, topics, repeatWrong }: PlaySessionProps) {
  const t = useT()
  const navigate = useNavigate()
  const invalidateProgress = useInvalidateProgress()
  const phone = useIsPhone()
  const play = usePlay({ projectId, setId, sessionId, start, repeatWrong })
  const { start: startNew, busy } = useStartSession(projectId, setId)
  const setHref = `/cards/${projectId}/${setId}`

  const cardRef = useRef<HTMLDivElement | null>(null)
  const [announce, setAnnounce] = useState('')
  const [copied, setCopied] = useState(false)
  const [confirmExit, setConfirmExit] = useState(false)
  const [help, setHelp] = useState(false)
  const [undo, setUndo] = useState<Answer | null>(null)
  const undoTimer = useRef<number | null>(null)

  // Полоса «Отменить» встаёт над нижними кнопками телефона, а их высота зависит
  // от того, что сейчас на экране: одна «Дальше», «Показать ответ» с парой
  // оценок или «Верно»/«Неверно» с подсказкой. Отступ поэтому считается от
  // измеренной высоты полосы кнопок, а не задан числом, которое устаревает при
  // любой правке кнопок.
  const [controlsH, setControlsH] = useState(0)
  const controlsSize = useRef<ResizeObserver | null>(null)
  const controlsRef = useCallback((el: HTMLDivElement | null) => {
    controlsSize.current?.disconnect()
    controlsSize.current = null
    // Элемента нет (ушли в итоги) — последняя высота и не нужна: полоса скрыта.
    if (!el) return
    setControlsH(el.offsetHeight)
    if (typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(() => setControlsH(el.offsetHeight))
    observer.observe(el)
    controlsSize.current = observer
  }, [])

  const { status, queue, cursor, step, card, tally } = play
  const total = queue.length
  const n = Math.min(cursor + 1, total)
  const topicTitle = card?.topic ? (topics?.find((x) => x.id === card.topic)?.title ?? null) : null

  const focusCard = useCallback(() => {
    // После перерисовки: новая карточка ещё не в DOM в момент нажатия.
    window.requestAnimationFrame(() => cardRef.current?.focus({ preventScroll: true }))
  }, [])

  // Смена вопроса: фокус на карточку и объявление для скринридера.
  useEffect(() => {
    if (status !== 'playing' || !step) return
    focusCard()
    setAnnounce(
      t('cards.play.live.question', { n: cursor + 1, total }) + (step.round > 0 ? ` ${t('cards.play.card.repeat')}` : ''),
    )
    // Объявляется переход на другой шаг, а не каждая правка очереди.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status, cursor, focusCard])

  useEffect(() => {
    if (status === 'done') setAnnounce(t('cards.play.live.done', { yes: tally.yes, no: tally.no }))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status])

  // Прогресс набора пересчитывается службой; обновить, когда ответы захода дошли.
  const settled = status === 'done' && play.unsaved === 0
  useEffect(() => {
    // Функция сброса новая на каждой отрисовке; сброс нужен один раз на переход.
    if (settled) invalidateProgress(projectId, setId)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [settled, projectId, setId])

  useEffect(
    () => () => {
      if (undoTimer.current) window.clearTimeout(undoTimer.current)
    },
    [],
  )

  // ── действия ──
  const answerWord = (a: Answer) => (a === 'yes' ? t('cards.play.yes') : t('cards.play.no'))

  const showUndo = useCallback((a: Answer) => {
    if (undoTimer.current) window.clearTimeout(undoTimer.current)
    setUndo(a)
    undoTimer.current = window.setTimeout(() => setUndo(null), UNDO_MS)
  }, [])

  const doUndo = useCallback(() => {
    if (undoTimer.current) window.clearTimeout(undoTimer.current)
    setUndo(null)
    if (play.back()) focusCard()
  }, [play, focusCard])

  /**
   * Догадка до показа ответа: и «Да», и «Нет» только раскрывают ответ, заход
   * остаётся на карточке — ради ответа её и решают, и человек сверяет себя сам.
   */
  const doGrade = useCallback(
    (a: Answer) => {
      if (!card) return
      play.grade(a)
      setAnnounce(t('cards.play.live.graded', { answer: answerWord(a) }))
      play.reveal()
      focusCard()
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [card, play, focusCard],
  )

  const doReveal = useCallback(() => {
    play.reveal()
    focusCard()
  }, [play, focusCard])

  /**
   * Сверка после показа ответа: «Верно» или «Неверно» — это и есть итоговая
   * оценка карточки (если она разошлась с догадкой, пишется исправляющая
   * попытка), и сразу следующий вопрос. Уйти с карточки не страшно: следом
   * появляется «Отменить».
   */
  const doConfirm = useCallback(
    (a: Answer) => {
      if (!card) return
      play.grade(a)
      setAnnounce(t('cards.play.live.graded', { answer: answerWord(a) }))
      play.next()
      showUndo(a)
      focusCard()
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [card, play, showUndo, focusCard],
  )

  /** `1` и `2`: до показа ответа — догадка, после — сверка. */
  const gradeKey = useCallback(
    (a: Answer) => (step?.shown ? doConfirm(a) : doGrade(a)),
    [step, doConfirm, doGrade],
  )

  const doNext = useCallback(() => {
    if (play.next()) {
      setUndo(null)
      focusCard()
    }
  }, [play, focusCard])

  const doCopy = useCallback(async () => {
    if (!card) return
    try {
      await navigator.clipboard.writeText(cardMarkdown(card))
    } catch {
      // Буфер обмена запрещён — остаётся выделить текст руками.
      return
    }
    setCopied(true)
    setAnnounce(t('common.action.copied'))
    window.setTimeout(() => setCopied(false), 1500)
  }, [card, t])

  const requestExit = useCallback(() => {
    if (status === 'playing' && gradedCount(queue) < total / 2) setConfirmExit(true)
    else navigate(setHref)
  }, [status, queue, total, navigate, setHref])

  const primary = useCallback(() => {
    if (!step) return
    if (step.grade || card === null) doNext()
    else if (!step.shown && card) doReveal()
    else if (card) setAnnounce(t('cards.play.live.gradeHint'))
  }, [step, card, doNext, doReveal, t])

  // ── клавиатура ──
  const keys = useRef({ status, primary, gradeKey, doUndo, doCopy, requestExit })
  keys.current = { status, primary, gradeKey, doUndo, doCopy, requestExit }

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.defaultPrevented || e.ctrlKey || e.metaKey || e.altKey || e.isComposing) return
      if (typing(e.target)) return
      if (document.querySelector('[role="dialog"], [role="alertdialog"]')) return
      const k = keys.current
      const take = (fn: () => void) => {
        e.preventDefault()
        fn()
      }
      if (e.key === '?' || (e.code === 'Slash' && e.shiftKey)) return take(() => setHelp(true))
      if (e.key === 'Escape') return take(k.requestExit)
      if (k.status !== 'playing' || e.repeat) return
      switch (e.code) {
        case 'Space':
          return take(k.primary)
        case 'Digit1':
        case 'Numpad1':
          return take(() => k.gradeKey('yes'))
        case 'Digit2':
        case 'Numpad2':
          return take(() => k.gradeKey('no'))
        case 'KeyU':
          return take(k.doUndo)
        case 'KeyC':
          return take(() => void k.doCopy())
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  // ── отрисовка ──
  const header = (
    <PlayHeader
      phone={phone}
      title={title}
      n={n}
      total={total}
      tally={tally}
      unsaved={play.unsaved}
      playing={status === 'playing'}
      canCopy={!!card && status === 'playing'}
      copied={copied}
      onCopy={() => void doCopy()}
      onHelp={() => setHelp(true)}
      onExit={requestExit}
    />
  )

  let body
  if (status === 'loading') {
    body = <SkeletonLines count={6} className={cn('mx-auto w-full max-w-[72ch]', phone && 'p-s4')} />
  } else if (status === 'error') {
    body = (
      <ErrorState
        className={cn('mx-auto w-full max-w-[72ch]', phone && 'm-s4 w-auto')}
        error={play.error}
        title={t('cards.play.loadFailed')}
        onRetry={play.reload}
        action={
          <Button type="button" variant="ghost" onClick={() => navigate(setHref)}>
            {t('cards.play.summary.toSet')}
          </Button>
        }
      />
    )
  } else if (status === 'empty') {
    body = (
      <EmptyState
        title={t('cards.play.empty.title')}
        text={t('cards.play.empty.text')}
        action={
          <Button type="button" variant="primary" onClick={() => navigate(setHref)}>
            {t('cards.play.summary.toSet')}
          </Button>
        }
      />
    )
  } else if (status === 'done') {
    body = (
      <Summary
        title={title}
        tally={tally}
        cardOf={play.cardOf}
        setHref={setHref}
        phone={phone}
        repeating={busy === 'wrong'}
        onRepeatWrong={() => void startNew('wrong')}
        onBack={doUndo}
      />
    )
  } else if (step) {
    body = phone ? (
      <>
        {/* Карточка по высоте вопроса, а не во весь экран: иначе тема прижата к
            верху, а вопрос стоит далеко от неё посреди пустоты. Карточка с
            подсказкой стоят по центру свободного места, а длинный ответ
            прокручивается внутри карточки — она сжимается, а экран не растёт. */}
        <div className="flex min-h-0 flex-1 flex-col justify-center px-s3 py-s3">
          <CardStage
            key={cursor}
            ref={cardRef}
            step={step}
            card={card}
            topicTitle={topicTitle}
            cardError={play.cardError}
            onRetryCards={play.retryCards}
            phone
            copied={copied}
            onCopy={() => void doCopy()}
            onSwipe={gradeKey}
          />
          <p className="mt-s2 shrink-0 text-center text-xs text-muted" aria-hidden="true">
            {t(step.shown ? 'cards.play.swipeHintCheck' : 'cards.play.swipeHint')}
          </p>
        </div>
        <PlayControls
          ref={controlsRef}
          step={step}
          card={card}
          phone
          onReveal={doReveal}
          onGrade={doGrade}
          onConfirm={doConfirm}
          onNext={doNext}
        />
      </>
    ) : (
      <div className="mx-auto w-full max-w-[72ch]">
        <CardStage
          key={cursor}
          ref={cardRef}
          step={step}
          card={card}
          topicTitle={topicTitle}
          cardError={play.cardError}
          onRetryCards={play.retryCards}
          phone={false}
          copied={copied}
          onCopy={() => void doCopy()}
        />
        <PlayControls
          step={step}
          card={card}
          phone={false}
          onReveal={doReveal}
          onGrade={doGrade}
          onConfirm={doConfirm}
          onNext={doNext}
        />
        <p className="mt-s5 text-center text-xs text-muted">
          <button type="button" className="underline-offset-2 hover:underline" onClick={() => setHelp(true)}>
            {t('cards.play.help.hint')}
          </button>
        </p>
      </div>
    )
  }

  return (
    <div
      className={cn(
        phone
          ? 'fixed inset-0 z-[60] flex h-[100dvh] flex-col overflow-hidden bg-bg'
          : // Карточка стоит по середине экрана, а не жмётся к шапке: высота —
            // окно без верхней полосы и отступов страницы, `min-h` (не `h`),
            // чтобы длинный ответ просто удлинял страницу.
            'flex min-h-[calc(100dvh-var(--topbar-h)-2*var(--page-pad,var(--space-5)))] flex-col',
      )}
    >
      {header}
      <div
        className={cn(
          phone ? 'flex min-h-0 flex-1 flex-col' : 'flex flex-1 flex-col justify-center pb-s6 pt-s2',
          phone && status === 'done' && 'overflow-y-auto',
        )}
      >
        {body}
      </div>

      <div className="sr-only" aria-live="polite" aria-atomic="true">
        {announce}
      </div>

      {undo && (
        <div
          role="status"
          className={cn(
            'fixed left-1/2 z-[70] flex w-[min(420px,calc(100vw-24px))] -translate-x-1/2 items-center gap-s3 rounded-md border border-line bg-elevated px-s4 py-s2 text-sm shadow-2 animate-toast-in',
            !phone && 'bottom-s5',
          )}
          // Над нижними кнопками телефона: их измеренная высота уже включает
          // отступ от полосы жестов, остаётся добавить просвет.
          style={phone ? { bottom: controlsH + UNDO_GAP } : undefined}
        >
          <span className="flex-1 text-ink">{t('cards.play.undo.text', { answer: answerWord(undo) })}</span>
          <Button type="button" variant="ghost" size="md" className="min-h-[44px] font-semibold text-accent" onClick={doUndo}>
            {t('cards.play.undo.action')}
          </Button>
        </div>
      )}

      <Dialog
        open={confirmExit}
        onOpenChange={setConfirmExit}
        title={t('cards.play.exit.title')}
        description={t('cards.play.exit.text', { done: gradedCount(queue), total })}
        footer={
          <>
            <DialogClose asChild>
              <Button type="button" variant="secondary">
                {t('cards.play.exit.stay')}
              </Button>
            </DialogClose>
            <Button type="button" variant="primary" onClick={() => navigate(setHref)}>
              {t('cards.play.exit.leave')}
            </Button>
          </>
        }
      />

      <ShortcutsDialog open={help} onOpenChange={setHelp} />
    </div>
  )
}

// ── шапка ────────────────────────────────────────────────────────────────────

interface PlayHeaderProps {
  phone: boolean
  title?: string
  n: number
  total: number
  tally: { yes: number; no: number }
  unsaved: number
  playing: boolean
  canCopy: boolean
  copied: boolean
  onCopy: () => void
  onHelp: () => void
  onExit: () => void
}

function PlayHeader({ phone, title, n, total, tally, unsaved, playing, canCopy, copied, onCopy, onHelp, onExit }: PlayHeaderProps) {
  const t = useT()
  const progress = total ? Math.min(100, Math.round(((n - (playing ? 1 : 0)) / total) * 100)) : 0

  const unsavedMark = unsaved > 0 && (
    <span
      className="inline-flex items-center gap-1 rounded-full bg-warn-bg px-s2 py-0.5 text-xs text-warn"
      title={t('cards.play.unsaved.hint')}
      role="status"
    >
      <Icon name="clock" size={14} />
      {phone ? unsaved : t('cards.play.unsaved.label', { n: unsaved })}
    </span>
  )

  const bar = (
    <div
      className="h-1 w-full overflow-hidden bg-surface-2"
      role="progressbar"
      aria-label={t('cards.play.progress')}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={progress}
    >
      <div className="h-full bg-accent transition-[width] duration-300 motion-reduce:transition-none" style={{ width: `${progress}%` }} />
    </div>
  )

  if (phone) {
    return (
      <header className="shrink-0 border-b border-line bg-surface" style={{ paddingTop: 'env(safe-area-inset-top)' }}>
        <div className="flex h-14 items-center gap-s1 px-s1">
          <Button type="button" variant="ghost" size="lg" iconOnly aria-label={t('cards.play.exit.action')} onClick={onExit}>
            <Icon name="close" size={20} />
          </Button>
          <div className="min-w-0 flex-1">
            <div className="truncate text-sm font-semibold text-ink-strong">{title ?? ' '}</div>
            <div className="flex items-center gap-s2 text-xs text-muted">
              {playing && <span>{t('cards.play.counterShort', { n, total })}</span>}
              <span className="rounded-full bg-ok-bg px-1.5 font-semibold text-ok">
                {t('cards.play.tally.yes', { n: tally.yes })}
              </span>
              <span className="rounded-full bg-err-bg px-1.5 font-semibold text-err">
                {t('cards.play.tally.no', { n: tally.no })}
              </span>
            </div>
          </div>
          {unsavedMark}
          {canCopy && (
            <Button
              type="button"
              variant="ghost"
              size="lg"
              iconOnly
              aria-label={copied ? t('common.action.copied') : t('common.action.copy')}
              onClick={onCopy}
            >
              <Icon name={copied ? 'check' : 'copy'} size={20} />
            </Button>
          )}
        </div>
        {bar}
      </header>
    )
  }

  return (
    <header className="mx-auto mb-s4 w-full max-w-[72ch]">
      <div className="flex flex-wrap items-center gap-x-s4 gap-y-s2 pb-s3">
        <h1 className="min-w-0 flex-1 truncate font-display text-lg font-semibold text-ink-strong">{title ?? ' '}</h1>
        {playing && <span className="text-sm text-muted">{t('cards.play.counter', { n, total })}</span>}
        <span className="flex items-center gap-s2 text-sm font-semibold">
          <span className="rounded-full bg-ok-bg px-s2 py-0.5 text-ok">{t('cards.play.tally.yes', { n: tally.yes })}</span>
          <span className="rounded-full bg-err-bg px-s2 py-0.5 text-err">{t('cards.play.tally.no', { n: tally.no })}</span>
        </span>
        {unsavedMark}
        <Button type="button" variant="ghost" size="sm" iconOnly aria-label={t('cards.play.help.title')} onClick={onHelp}>
          <span aria-hidden="true" className="font-mono text-sm">?</span>
        </Button>
        <Button type="button" variant="ghost" size="sm" onClick={onExit}>
          <Icon name="close" size={16} />
          {t('cards.play.exit.action')}
          <Kbd>Esc</Kbd>
        </Button>
      </div>
      <div className="overflow-hidden rounded-full">{bar}</div>
    </header>
  )
}

// ── сокращения ───────────────────────────────────────────────────────────────

function ShortcutsDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const t = useT()
  const rows: [string, string][] = [
    ['Space', t('cards.play.help.space')],
    ['1', t('cards.play.help.yes')],
    ['2', t('cards.play.help.no')],
    ['U', t('cards.play.help.undo')],
    ['C', t('cards.play.help.copy')],
    ['Esc', t('cards.play.help.exit')],
    ['?', t('cards.play.help.list')],
  ]
  return (
    <Dialog open={open} onOpenChange={onOpenChange} title={t('cards.play.help.title')}>
      <dl className="grid grid-cols-[auto_1fr] items-center gap-x-s4 gap-y-s2 text-sm">
        {rows.map(([key, text]) => (
          <div key={key} className="contents">
            <dt>
              <kbd className="inline-flex min-w-[32px] items-center justify-center rounded-sm border border-line-strong bg-surface-2 px-s2 py-0.5 font-mono text-xs text-ink">
                {key}
              </kbd>
            </dt>
            <dd className="text-ink">{text}</dd>
          </div>
        ))}
      </dl>
      <p className="mt-s4 text-xs text-muted">{t('cards.play.help.phone')}</p>
    </Dialog>
  )
}
