/**
 * TutorPanel — панель репетитора: условие, переписка, поле сообщения.
 *
 * ── Это чат, и только чат ────────────────────────────────────────────────────
 *
 * Человек пишет репетитору словами — «проверь», «что тут написано», «с чего
 * начать», — а репетитор отвечает словами же. Кнопок-режимов, вердиктов полосой
 * и перечней сверенного здесь нет: всё это — ответ таблицей на вопрос, заданный
 * фразой. Что репетитор видит на доске, приложено к каждому сообщению скрепкой:
 * строки, прочитанные с холста, — те же, что стоят призраками под росчерками.
 *
 * ── Переписка лежит на томе ─────────────────────────────────────────────────
 *
 * Сообщения приходят с тома (`useBoardChat`), а не копятся в состоянии
 * страницы: открытая заново доска показывает тот же разговор. Единственное, что
 * страница держит у себя, — сообщение, которое уже отправлено и ещё не
 * записано: оно стоит в конце разговора, пока не приедет запись с ответом.
 *
 * ── Действие на экране всегда одно ───────────────────────────────────────────
 *
 * Пока идёт прогон, на месте «Отправить» — «Остановить»: два одновременных
 * сообщения репетитору — это два списания и два ответа, из которых человек
 * прочтёт один.
 */
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'

import { useT } from '@/i18n'
import { cn } from '@/lib/cn'
import { Button, Chip, Icon, Input, Textarea } from '@/ui'

import { Formula } from './Formula'
import { EXTRA, INK_STATES, type InkState } from './ink'
import { LINE_STATES, willSee, type FairLine } from './recognizer'
import type { ChatMessage } from './types'
import type { BoardCheckState } from './useBoardCheck'

/**
 * Строка, которую правят руками прямо сейчас.
 *
 * `where` говорит, **где** открыто поле: под росчерками на холсте или в списке
 * строк. Одно и то же значение правится в двух местах, и без этого поля оба
 * места открыли бы по живому полю MathLive на одну строку — а два поля,
 * забирающих себе ввод на каждом нажатии, отнимают его друг у друга.
 */
export type Editing = { id: string; latex: string; where: 'ghost' | 'list' }

/**
 * Сообщение, которое отправлено и ещё не записано на том.
 *
 * `lines` — снимок вложения на момент отправки, а не ссылка на нынешние строки:
 * человек дописывает доску, пока репетитор думает, и вложение, которое менялось
 * бы вслед за холстом, врало бы о том, что именно репетитор видел.
 */
export type PendingMessage = { text: string; lines: FairLine[]; sceneVersion: number }

export type TutorPanelProps = {
  /** Имя доски — заголовок панели. */
  name: string

  /** Условие задачи текстом. Пусто — законное состояние, и о нём сказано. */
  task: string
  onTask: (task: string) => void

  ink: { state: InkState; note: string; reason: string }
  /** Открытий сессии распознавания за месяц: по ним живёт месячный потолок. */
  inkOpens: number | null

  /** Строки доски сверху вниз — те же, что призраками на холсте. */
  lines: FairLine[]
  /**
   * Что уедет с сообщением: строки из выделенного на холсте, а без выделения —
   * все. Отдельно от `lines` затем, что скрепка показывает именно это.
   */
  attached: FairLine[]
  /** На холсте есть выделение, и вложение сужено до него. */
  selected: boolean
  /** Строка, открытая на правку руками; `null` — не правят ничего. */
  editing: Editing | null
  onEdit: (id: string) => void
  onEditChange: (latex: string) => void
  onEditSave: () => void
  onEditCancel: () => void
  /** Подсветить строку на холсте (и снять подсветку). */
  onHover: (ids: string[] | null) => void

  /** Переписка с тома, старые сообщения первыми. */
  messages: ChatMessage[]
  /** Отправленное и ещё не записанное сообщение; `null` — такого нет. */
  pending: PendingMessage | null
  run: BoardCheckState
  /** Цена сообщения в единицах; `null` — служба её ещё не назвала. */
  price: number | null
  /** Можно ли писать: есть пресет модели. */
  canAsk: boolean
  onSend: (text: string) => void
  /** Собрать строки заново: этим чинится отказ «доска изменилась». */
  onRebuild: () => void
  /** Свернуть панель в рейку. */
  onCollapse: () => void
}

export function TutorPanel(props: TutorPanelProps) {
  const t = useT()

  return (
    <aside
      className="flex h-full min-h-0 w-full flex-col border-l border-line bg-surface"
      aria-label={t('board.chat.tutor')}
      data-testid="board-tutor"
    >
      <Header {...props} />
      <InkStrip {...props} />
      <Chat {...props} />
      <Composer {...props} />
    </aside>
  )
}

/** Шапка: имя доски, условие строкой, кнопка «свернуть». */
function Header({ name, task, onTask, onCollapse }: TutorPanelProps) {
  const t = useT()
  const [правим, setПравим] = useState(false)
  const [черновик, setЧерновик] = useState(task)

  function записать() {
    setПравим(false)
    if (черновик.trim() !== task.trim()) onTask(черновик.trim())
  }

  return (
    <header className="flex flex-col gap-s2 border-b border-line px-s3 py-s2">
      <div className="flex items-center gap-s2">
        <Icon name="board" size={18} style={{ color: 'var(--mod-board)' }} />
        <h2 className="min-w-0 flex-1 truncate font-display text-md font-semibold text-ink-strong">
          {name}
        </h2>
        <Button
          variant="ghost"
          size="sm"
          iconOnly
          aria-label={t('board.board.panelHide')}
          onClick={onCollapse}
        >
          <Icon name="panelClose" size={16} />
        </Button>
      </div>

      {правим ? (
        <Input
          label={t('board.board.condition')}
          autoFocus
          value={черновик}
          onChange={(e) => setЧерновик(e.target.value)}
          onBlur={записать}
          onKeyDown={(e) => {
            if (e.key === 'Enter') записать()
            if (e.key === 'Escape') {
              setЧерновик(task)
              setПравим(false)
            }
          }}
        />
      ) : (
        <button
          type="button"
          className="truncate rounded-sm px-1 py-0.5 text-left text-xs text-muted hover:bg-surface-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
          onClick={() => {
            setЧерновик(task)
            setПравим(true)
          }}
        >
          {task || t('board.board.conditionEmpty')}
        </button>
      )}
    </header>
  )
}

/**
 * Полоса состояния распознавания.
 *
 * Говорит не только «работает / не работает», но и **каким путём**: живая сессия
 * стоит одного оплаченного открытия на всю доску, а запасной пакетный вход —
 * вызова на каждую прочитанную строку. Человек, у которого месячный потолок
 * кончается втрое быстрее обычного, вправе знать об этом до того, как он
 * кончится. Без ключей доска рисует и сохраняется — это состояние, а не беда, и
 * у него своя строка со ссылкой в настройки.
 */
function InkStrip({ ink, inkOpens }: TutorPanelProps) {
  const t = useT()
  const тон =
    ink.state === INK_STATES.live
      ? 'ok'
      : ink.state === INK_STATES.batch
        ? 'warn'
        : ink.state === INK_STATES.busy || ink.state === INK_STATES.connecting
          ? 'info'
          : ink.state === INK_STATES.off
            ? 'muted'
            : 'warn'
  const слово =
    ink.state === INK_STATES.live
      ? t('board.ink.live')
      : ink.state === INK_STATES.batch
        ? t('board.ink.batch')
        : ink.state === INK_STATES.busy
          ? t('board.ink.busy')
          : ink.state === INK_STATES.connecting
            ? t('board.ink.connecting')
            : ink.state === INK_STATES.error
              ? t('board.ink.lost')
              : ink.reason === 'no_keys'
                ? t('board.ink.noKeys')
                : t('board.ink.off')

  return (
    <div
      className="flex flex-wrap items-center gap-s2 border-b border-line px-s3 py-1.5 text-xs text-muted"
      data-testid="board-ink"
      data-state={ink.state}
    >
      <Chip tone={тон}>{слово}</Chip>
      {ink.reason === 'no_keys' && (
        <Link to="/settings/agent" className="underline">
          {t('board.ink.toSettings')}
        </Link>
      )}
      {ink.note && (
        <span className="min-w-0 flex-1 truncate">
          {ink.note.startsWith(EXTRA)
            ? t('board.ink.extra', { n: ink.note.slice(EXTRA.length) })
            : ink.note}
        </span>
      )}
      {ink.reason === 'no_keys' && <span className="ml-auto">{t('board.ink.freeQuota')}</span>}
      {typeof inkOpens === 'number' && ink.state !== INK_STATES.off && (
        <span className="ml-auto tabular-nums">{t('board.ink.opens', { n: inkOpens })}</span>
      )}
    </div>
  )
}

/* ── список строк ────────────────────────────────────────────────────────── */

type LinesListProps = {
  lines: readonly FairLine[]
  /** Правка строки. Без него список только показывает — таково вложение в переписке. */
  editing?: Editing | null
  onEdit?: (id: string) => void
  onEditChange?: (latex: string) => void
  onEditSave?: () => void
  onEditCancel?: () => void
  onHover?: (ids: string[] | null) => void
}

/**
 * Список строк: один компонент и для меню скрепки, и для вложения в переписке.
 *
 * Один намеренно: это один и тот же предмет — то, что уезжает репетитору, — и
 * два списка рядом разошлись бы видом, а потом и содержанием. Разница между
 * местами ровно одна: в меню строку можно поправить, во вложении отправленного
 * сообщения — нет, там показано то, что уже уехало.
 */
function LinesList({
  lines,
  editing,
  onEdit,
  onEditChange,
  onEditSave,
  onEditCancel,
  onHover,
}: LinesListProps) {
  const t = useT()
  if (lines.length === 0) {
    return <p className="text-sm text-muted">{t('board.lines.emptyTitle')}</p>
  }
  return (
    <ol className="flex flex-col gap-1.5" data-testid="board-steps">
      {lines.map((строка) => {
        const правится = editing?.id === строка.id && editing.where === 'list'
        return (
          <li
            key={строка.id}
            data-step={строка.step}
            data-state={строка.state}
            onPointerEnter={onHover ? () => onHover(строка.strokes) : undefined}
            onPointerLeave={onHover ? () => onHover(null) : undefined}
            className={cn(
              'flex items-start gap-s2 rounded-sm border border-line px-s2 py-1.5',
              !строка.latex.trim() && 'border-dashed border-line-strong',
            )}
          >
            <span className="mt-0.5 w-5 shrink-0 text-right font-mono text-xs text-muted tabular-nums">
              {строка.n}
            </span>
            <div className="min-w-0 flex-1">
              {правится && editing ? (
                <Formula
                  latex={editing.latex}
                  editable
                  onChange={onEditChange}
                  onSubmit={onEditSave}
                  onCancel={onEditCancel}
                  label={t('board.lines.title')}
                />
              ) : строка.latex ? (
                <Formula latex={строка.latex} label={t('board.lines.title')} />
              ) : (
                <span className="text-sm text-muted">
                  {t('board.lines.unreadable', { n: строка.strokes.length })}
                </span>
              )}
              {строка.state === LINE_STATES.manual && (
                <p className="mt-0.5 text-xs text-muted">
                  {строка.behind ? t('board.lines.manualBehind') : t('board.lines.manual')}
                </p>
              )}
            </div>
            {onEdit &&
              (правится ? (
                <div className="flex shrink-0 flex-col gap-1">
                  <Button variant="primary" size="sm" className="min-h-11" onClick={onEditSave}>
                    <Icon name="check" size={16} />
                    {t('board.lines.save')}
                  </Button>
                  <Button variant="ghost" size="sm" onClick={onEditCancel}>
                    {t('board.lines.cancel')}
                  </Button>
                </div>
              ) : (
                <Button
                  variant="ghost"
                  size="sm"
                  className="min-h-11 shrink-0"
                  onClick={() => onEdit(строка.id)}
                >
                  {строка.latex ? t('board.lines.fix') : t('board.lines.type')}
                </Button>
              ))}
          </li>
        )
      })}
    </ol>
  )
}

/* ── переписка ───────────────────────────────────────────────────────────── */

/**
 * Переписка: сообщения с тома, за ними — отправленное и ещё не записанное.
 *
 * Прокрутка держится у конца: новое сообщение — внизу, и человек, написавший
 * его секунду назад, смотрит именно туда.
 */
function Chat({ messages, pending, run, onRebuild, onHover }: TutorPanelProps) {
  const t = useT()
  const конец = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    конец.current?.scrollIntoView({ block: 'end' })
  }, [messages.length, pending, run.text, run.running, run.error])

  const пусто = messages.length === 0 && !pending

  return (
    <div
      className="flex min-h-0 flex-1 flex-col gap-s2 overflow-y-auto p-s3"
      data-testid="board-chat"
    >
      {пусто && <p className="text-sm text-muted">{t('board.chat.empty')}</p>}
      {messages.map((сообщение, и) => (
        <Bubble key={`${и}-${сообщение.at ?? ''}`} role={сообщение.role} text={сообщение.text} />
      ))}
      {pending && (
        <>
          <Bubble role="you" text={pending.text} lines={pending.lines} onHover={onHover} />
          {run.running ? (
            <Bubble role="tutor" text={run.text} waiting />
          ) : run.error ? (
            <div className="rounded-sm border border-err bg-err-bg px-s2 py-1.5 text-sm text-err">
              <p>{run.error}</p>
              {run.errorCode === 'scene_stale' && (
                <Button variant="secondary" size="sm" className="mt-1.5" onClick={onRebuild}>
                  <Icon name="refresh" size={14} />
                  {t('board.lines.rebuild')}
                </Button>
              )}
            </div>
          ) : run.stopped ? (
            <p className="text-sm text-muted">{t('board.ask.stopped')}</p>
          ) : null}
        </>
      )}
      <div ref={конец} />
    </div>
  )
}

/** Одно сообщение: своё — справа, репетитора — слева; вложение — скрепкой. */
function Bubble({
  role,
  text,
  waiting = false,
  lines,
  onHover,
}: {
  role: ChatMessage['role']
  text: string
  /** Ответа ещё нет: вместо текста — «думает». */
  waiting?: boolean
  lines?: FairLine[]
  onHover?: (ids: string[] | null) => void
}) {
  const t = useT()
  const [видно, setВидно] = useState(false)
  const своё = role === 'you'
  return (
    <article
      data-role={role}
      className={cn(
        'flex max-w-[92%] flex-col gap-1 rounded-md border px-s2 py-1.5',
        своё ? 'self-end border-accent bg-accent-bg' : 'self-start border-line bg-surface-2',
      )}
    >
      <span className="text-xs font-semibold uppercase tracking-wide text-muted">
        {своё ? t('board.chat.you') : t('board.chat.tutor')}
      </span>
      {text ? (
        <MathText text={text} />
      ) : waiting ? (
        <p className="text-sm text-muted">{t('board.ask.busy')}</p>
      ) : null}
      {lines && lines.length > 0 && (
        <>
          <button
            type="button"
            className="flex items-center gap-1 self-start text-xs text-muted underline"
            onClick={() => setВидно((в) => !в)}
          >
            <Icon name="paperclip" size={14} />
            {t('board.chat.attached', { n: lines.length })}
          </button>
          {видно && <LinesList lines={lines} onHover={onHover} />}
        </>
      )}
    </article>
  )
}

/** Формула в тексте: `$…$` — в строке, `$$…$$` — отдельной строкой. */
const МАТЕМАТИКА = /\$\$([\s\S]+?)\$\$|\$([^$\n]+?)\$/g

/**
 * Текст сообщения с формулами.
 *
 * Формулы репетитор пишет LaTeX между знаками доллара — так же, как они лежат
 * в строках доски, — и показываются они тем же полем, что и строки: второй
 * способ рисовать формулу разошёлся бы с первым на первом же корне.
 */
function MathText({ text }: { text: string }) {
  const куски: ReactNode[] = []
  let последний = 0
  let n = 0
  for (const м of text.matchAll(МАТЕМАТИКА)) {
    const от = м.index ?? 0
    if (от > последний) куски.push(<span key={n++}>{text.slice(последний, от)}</span>)
    const отдельно = м[1] !== undefined
    const latex = (м[1] ?? м[2] ?? '').trim()
    куски.push(
      <Formula
        key={n++}
        latex={latex}
        className={отдельно ? 'my-1' : 'inline-block align-middle'}
      />,
    )
    последний = от + м[0].length
  }
  if (последний < text.length) куски.push(<span key={n++}>{text.slice(последний)}</span>)
  return <div className="whitespace-pre-wrap text-sm text-ink">{куски}</div>
}

/* ── поле сообщения ──────────────────────────────────────────────────────── */

/**
 * Поле сообщения: скрепка со строками, слова и одна кнопка.
 *
 * ⏎ отправляет, ⇧⏎ переносит строку: сообщение репетитору — фраза, а не
 * сочинение. Скрепка одна: вложение у всех сообщений одно и то же — строки
 * доски, — и там же строку правят руками.
 */
function Composer({
  run,
  price,
  canAsk,
  onSend,
  attached,
  selected,
  editing,
  onEdit,
  onEditChange,
  onEditSave,
  onEditCancel,
  onHover,
}: TutorPanelProps) {
  const t = useT()
  const [текст, setТекст] = useState('')
  const [список, setСписок] = useState(false)
  const увидит = willSee(attached)
  const можно = canAsk && !run.running && текст.trim().length > 0

  function отправить() {
    if (!можно) return
    onSend(текст.trim())
    setТекст('')
  }

  return (
    <footer className="flex flex-col gap-s2 border-t border-line bg-surface-2 p-s3">
      {список && (
        <div className="max-h-64 overflow-y-auto rounded-sm border border-line bg-surface p-s2">
          <LinesList
            lines={attached}
            editing={editing}
            onEdit={onEdit}
            onEditChange={onEditChange}
            onEditSave={onEditSave}
            onEditCancel={onEditCancel}
            onHover={onHover}
          />
        </div>
      )}

      <Textarea
        label={t('board.chat.placeholder')}
        rows={2}
        value={текст}
        disabled={run.running || !canAsk}
        data-testid="board-message"
        onChange={(e) => setТекст(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault()
            отправить()
          }
        }}
      />

      <div className="flex flex-wrap items-center gap-s2">
        <button
          type="button"
          className="flex items-center gap-1 text-xs text-muted underline"
          aria-expanded={список}
          data-testid="board-attach"
          onClick={() => setСписок((в) => !в)}
        >
          <Icon name="paperclip" size={14} />
          {t('board.lines.attached', { n: увидит })}
          <Icon name={список ? 'chevronDown' : 'chevronUp'} size={14} />
        </button>
        {selected && <span className="text-xs text-info">{t('board.chat.selected')}</span>}
        {!canAsk && <span className="text-xs text-warn">{t('board.ask.noEndpoint')}</span>}
        {run.running ? (
          <Button
            variant="danger"
            className="ml-auto min-h-11"
            loading={run.stopping}
            onClick={run.stop}
          >
            {t('board.ask.stop')}
          </Button>
        ) : (
          <Button
            variant="primary"
            className="ml-auto min-h-11"
            disabled={!можно}
            onClick={отправить}
            data-testid="board-send"
          >
            {t('board.ask.send')}
            {price !== null && (
              <span className="font-mono text-xs opacity-80">
                {' '}
                · {t('board.ask.cost', { n: price })}
              </span>
            )}
          </Button>
        )}
      </div>
    </footer>
  )
}
