/**
 * DraftPage — черновик набора: `/cards/drafts/:draftId`.
 *
 * Черновик — результат генерации агентом (или загрузки файла) до того, как он
 * стал набором. Живёт на сервере, поэтому переживает перезагрузку, и открывается
 * по тому же адресу со второго устройства.
 *
 * **Пока идёт задание** экран показывает ход кадрами `progress` («тема 2 из 5 ·
 * Первообразная» и полоса «готово / заказано»), кнопку «Остановить» и карточки
 * по мере готовности: на каждый кадр хода черновик перечитывается (не чаще раза
 * в полторы секунды — кадры приходят пачками). Править черновик в это время
 * нельзя: служба дописывает в него карточки, и правка, ушедшая целым JSON,
 * затёрла бы то, что пришло между чтением и сохранением.
 *
 * **После задания** — карточки по темам (вопрос, раскрытие ответа и разбора),
 * проблемы разбора, правка и удаление карточек, «Догенерировать ещё N» по теме,
 * «Сохранить как набор» и «Скачать .json».
 *
 * **Правка = новый JSON.** Черновик разбирается из `text` (`./draftJson`) — все
 * карточки массива, включая отклонённые, с неизвестными полями. Карточка
 * правится полями, JSON собирается заново и уходит целиком
 * `PUT /api/cards/drafts/{id}`. Служба разбирает его тем же разбором, что файл,
 * и отвечает проблемами — их экран и показывает, у своих карточек по `card`.
 * Правка видна сразу: кэш черновика обновляется до ответа и откатывается, если
 * служба отказала.
 *
 * **Повреждённый черновик** (текст не JSON или `cards` не массив) не правится:
 * экран показывает сырой текст только для чтения и даёт его скачать.
 *
 * **Режим дополнения** (`?project=&set=`): «Добавить в набор» вместо «Сохранить
 * как набор» — карточки уходят в существующий набор новой версией.
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'

import { ApiError, errorSaid, errorText, isApiError, type JobEvent } from '@/api'
import { useCurrentWorkspace, useJobStream } from '@/api/hooks'
import { useCancelJob } from '@/features/agent/data'
import { plural } from '@/features/projects/format'
import { useDefaultEndpoint } from '@/features/reports/data'
import { useT } from '@/i18n'
import { cn } from '@/lib/cn'
import {
  BetaTag,
  Button,
  Dialog,
  EmptyState,
  ErrorState,
  Field,
  Icon,
  Input,
  Progress,
  Segmented,
  SkeletonLines,
  Spinner,
  Textarea,
} from '@/ui'

import { cardsFileName, saveTextFile } from '../api'
import type { Draft, Problem } from '../types'
import { CardView } from '../components/CardView'
import { ProblemsTable } from '../components/ProblemsTable'
import { problemCard, problemField } from '../components/problemPlace'
import { useIsPhone } from '../hooks/useIsPhone'
import { CardEditor, type CardPatch } from './CardEditor'
import {
  generateKeys,
  useDraft,
  useGenerate,
  useSaveDraftAsSet,
  useSaveDraftText,
  type AnswerLength,
} from './data'
import {
  groupByTopic,
  headText,
  parseDraft,
  stringifyDraft,
  topicsOf,
  withCard,
  withoutCard,
  type DraftCard,
  type DraftDoc,
} from './draftJson'
import { MAX_CARDS } from './GeneratePage'

/** Кадр хода задания: `ctx.progress(step, total, note)` обработчика. */
type ProgressFrame = { step?: number; total?: number; note?: string }

/** Не чаще этого перечитывать черновик по кадрам хода, мс. */
const REFETCH_EVERY = 1500

type T = ReturnType<typeof useT>

/**
 * Проблемы после удаления карточки `index`: её проблемы уходят, у следующих номер
 * и путь сдвигаются на одну — до ответа службы проблемы остаются у своих карточек.
 */
function shiftProblems(problems: Problem[], index: number): Problem[] {
  return problems.flatMap((p) => {
    const card = problemCard(p)
    if (card === null || card < index) return [p]
    if (card === index) return []
    return [
      {
        ...p,
        card: card - 1,
        path: p.path ? p.path.replace(/^cards\[\d+\]/, `cards[${card - 1}]`) : p.path,
      },
    ]
  })
}

export default function DraftPage() {
  const t = useT()
  const phone = useIsPhone()
  const qc = useQueryClient()
  const navigate = useNavigate()
  const { draftId = '' } = useParams()
  const [params] = useSearchParams()
  const projectId = params.get('project')
  const setId = params.get('set')
  const append = !!projectId && !!setId

  const workspace = useCurrentWorkspace()
  const endpoint = useDefaultEndpoint()
  const draft = useDraft(draftId)
  // Правка идёт по тексту черновика: в нём все карточки, включая отклонённые.
  const text = typeof draft.data?.text === 'string' ? draft.data.text : ''
  const { doc, broken } = useMemo((): { doc: DraftDoc | null; broken: boolean } => {
    try {
      return { doc: parseDraft(text), broken: false }
    } catch {
      return { doc: null, broken: true }
    }
  }, [text])
  const saveText = useSaveDraftText(draftId)
  const saveSet = useSaveDraftAsSet(draftId)
  const generate = useGenerate()
  const cancel = useCancelJob()

  // Задание догенерации известно из ответа запуска раньше, чем черновик
  // перечитается: без этого поток хода открылся бы с опозданием на запрос.
  const [startedJob, setStartedJob] = useState<string | null>(null)
  const draftJob = draft.data?.job_id ?? null
  const jobId = startedJob ?? draftJob
  useEffect(() => {
    if (startedJob && draftJob === startedJob) setStartedJob(null)
  }, [startedJob, draftJob])

  const stream = useJobStream(jobId)
  const running = !!jobId && !!stream.job && !stream.done
  const progress = useMemo(() => lastProgress(stream.events), [stream.events])
  const progressFrames = useMemo(
    () => stream.events.filter((e) => e.kind === 'progress').length,
    [stream.events],
  )

  // Перечитать черновик по кадрам хода — с потолком частоты.
  const lastRefetch = useRef(0)
  useEffect(() => {
    if (!progressFrames) return
    const key = generateKeys.draft(draftId)
    const wait = REFETCH_EVERY - (Date.now() - lastRefetch.current)
    const go = () => {
      lastRefetch.current = Date.now()
      void qc.invalidateQueries({ queryKey: key })
    }
    if (wait <= 0) {
      go()
      return
    }
    const timer = setTimeout(go, wait)
    return () => clearTimeout(timer)
  }, [progressFrames, draftId, qc])

  // Конец задания: последний раз перечитать черновик — хвост карточек мог
  // прийти после последнего кадра хода.
  const finished = useRef<string | null>(null)
  useEffect(() => {
    if (!jobId || !stream.done || finished.current === jobId) return
    finished.current = jobId
    void qc.invalidateQueries({ queryKey: generateKeys.draft(draftId) })
  }, [jobId, stream.done, draftId, qc])

  const jobStatus = stream.job?.status
  const jobError =
    stream.done && jobStatus === 'failed'
      ? (() => {
          const e = (stream.job?.error ?? {}) as { code?: string; message?: string }
          return errorSaid(new ApiError(e.code || 'unknown', e.message || '')).text
        })()
      : null

  const problems = useMemo(() => draft.data?.problems ?? [], [draft.data])

  // Проблемы карточек — у своих карточек: номер в проблеме — индекс в массиве
  // `cards` JSON черновика, тот же, что у карточки на экране.
  const cardProblems = useMemo(() => {
    const map = new Map<string, Problem[]>()
    if (!doc) return map
    for (const p of problems) {
      const index = problemCard(p)
      const card = index === null ? undefined : doc.cards[index]
      if (card) map.set(card.key, [...(map.get(card.key) ?? []), p])
    }
    return map
  }, [doc, problems])
  const rejected = useMemo(
    () => new Set(problems.map(problemCard).filter((c): c is number => c !== null)).size,
    [problems],
  )

  const [editing, setEditing] = useState<string | null>(null)
  const [removing, setRemoving] = useState<DraftCard | null>(null)
  const [more, setMore] = useState<{ topic: string | null } | null>(null)

  const busy = running || saveText.isPending || generate.isPending

  /**
   * Правка черновика: сразу на экране, затем целым JSON на сервер. `removed` —
   * индекс удалённой карточки: проблемы следующих сдвигаются до ответа службы.
   */
  function commit(next: DraftDoc, after?: () => void, removed?: number) {
    const key = generateKeys.draft(draftId)
    const before = qc.getQueryData<Draft>(key)
    const nextText = stringifyDraft(next.head, next.cards)
    if (before) {
      qc.setQueryData<Draft>(key, {
        ...before,
        text: nextText,
        problems: removed === undefined ? before.problems : shiftProblems(before.problems ?? [], removed),
      })
    }
    saveText.mutate(nextText, {
      onSuccess: (r) => {
        qc.setQueryData<Draft>(key, (d) =>
          d
            ? {
                ...d,
                problems: r.problems,
                stats: { valid: r.stats.valid ?? d.stats.valid, rejected: r.stats.rejected ?? d.stats.rejected },
              }
            : d,
        )
        after?.()
      },
      onError: () => {
        if (before) qc.setQueryData<Draft>(key, before)
      },
    })
  }

  function saveCard(card: DraftCard, patch: CardPatch) {
    if (!doc) return
    commit(withCard(doc, card.key, patch), () => setEditing(null))
  }

  function removeCard(card: DraftCard) {
    if (!doc) return
    commit(withoutCard(doc, card.key), () => setRemoving(null), card.index)
  }

  const title = (doc && headText(doc.head, 'title')) || draft.data?.set?.title || ''

  function download() {
    // Повреждённый черновик скачивается как есть — его JSON и нужно чинить.
    const body = broken || !doc ? text : text.trim() ? text : stringifyDraft(doc.head, doc.cards)
    saveTextFile(cardsFileName(title), body)
  }

  function saveAsSet() {
    const ws = workspace.data?.id
    const target = append
      ? { project_id: projectId as string, set_id: setId as string }
      : ws
        ? { workspace_id: ws }
        : null
    if (!target) return
    saveSet.mutate(target, {
      onSuccess: (r) => navigate(`/cards/${encodeURIComponent(r.project_id)}/${encodeURIComponent(r.set_id)}`),
    })
  }

  function generateMore(topic: string | null, count: number, length: AnswerLength) {
    const ws = workspace.data?.id
    if (!ws || !endpoint || !doc) return
    generate.mutate(
      {
        workspace_id: ws,
        ...(append ? { project_id: projectId as string, set_id: setId as string } : {}),
        prompt: [headText(doc.head, 'title'), headText(doc.head, 'description')].filter(Boolean).join('\n\n'),
        count,
        length,
        language: headText(doc.head, 'language') || 'ru',
        endpoint,
        draft_id: draftId,
        ...(topic ? { topic } : {}),
      },
      {
        onSuccess: (r) => {
          finished.current = null
          setStartedJob(r.job_id)
          setMore(null)
        },
      },
    )
  }

  // ── состояния загрузки ──
  if (draft.isPending) {
    return (
      <div className="flex flex-col gap-s4">
        <SkeletonLines count={6} />
      </div>
    )
  }
  if (draft.isError) {
    if (isApiError(draft.error) && (draft.error.status === 404 || draft.error.status === 410)) {
      return (
        <EmptyState
          icon="inbox"
          title={t('cards.draft.gone.title')}
          text={t('cards.draft.gone.text')}
          action={
            <Button variant="primary" asChild>
              <Link to="/cards/generate">{t('cards.draft.gone.again')}</Link>
            </Button>
          }
        />
      )
    }
    return <ErrorState error={draft.error} onRetry={() => void draft.refetch()} />
  }

  const cards = doc?.cards ?? []
  const groups = doc ? groupByTopic(doc) : []
  const topicTitles = doc ? topicsOf(doc) : []
  const editingCard = editing ? cards.find((c) => c.key === editing) : undefined
  const canSave = !!doc && cards.length > 0 && !busy
  const canDownload = broken ? !!text : cards.length > 0

  const saveLabel = t(append ? 'cards.draft.addToSet' : 'cards.draft.saveAsSet')

  const header = (
    <header className="flex flex-wrap items-end justify-between gap-s3">
      <div className="min-w-0">
        <p className="mb-1 text-xs text-muted">{t('cards.draft.caption')}</p>
        <h1 className="flex items-center gap-s2 font-display text-2xl font-semibold text-ink-strong">
          <span className="min-w-0 truncate">{title || t('cards.draft.untitled')}</span>
          <BetaTag label={t('shell.beta')} />
        </h1>
        {!broken && <p className="text-sm text-muted">{stats(t, cards.length, topicTitles.length)}</p>}
      </div>
      {!phone && (
        <div className="flex flex-wrap items-center gap-s2">
          <Button variant="ghost" asChild>
            <Link to={append ? `/cards/${projectId}/${setId}` : '/cards'}>
              <Icon name="arrowLeft" size={15} />
              {t(append ? 'cards.generate.toSet' : 'cards.generate.toLibrary')}
            </Link>
          </Button>
          <Button variant="secondary" disabled={!canDownload} onClick={download}>
            <Icon name="download" size={15} />
            {t('cards.draft.download')}
          </Button>
          <Button variant="agent" disabled={!doc || busy} onClick={() => setMore({ topic: null })}>
            <Icon name="agent" size={15} />
            {t('cards.draft.more.button')}
          </Button>
          <Button variant="primary" disabled={!canSave} loading={saveSet.isPending} onClick={saveAsSet}>
            <Icon name="save" size={15} />
            {saveLabel}
          </Button>
        </div>
      )}
    </header>
  )

  return (
    <div className={cn('flex flex-col gap-s4', phone && 'pb-[calc(88px+env(safe-area-inset-bottom))]')}>
      {header}

      {(running || progress) && (
        <RunPanel
          running={running}
          progress={progress}
          cards={cards.length}
          stopping={cancel.isPending}
          onStop={() => jobId && cancel.mutate(jobId)}
          phone={phone}
        />
      )}
      {stream.done && jobStatus === 'cancelled' && (
        <p className="text-sm text-muted">{t('cards.draft.run.stopped')}</p>
      )}
      {jobError && (
        <p className="rounded-sm border border-err bg-err-bg px-s3 py-s2 text-sm text-err">{jobError}</p>
      )}
      {cancel.isError && <p className="text-sm text-err">{errorText(cancel.error)}</p>}
      {saveText.isError && <p className="text-sm text-err">{errorText(saveText.error)}</p>}
      {saveSet.isError && <p className="text-sm text-err">{errorText(saveSet.error)}</p>}

      {problems.length > 0 && (
        <details open={!phone} className="rounded-md border border-warn bg-surface p-s3">
          <summary className="min-h-11 cursor-pointer content-center text-sm font-medium text-warn">
            {t('cards.draft.problems', { n: problems.length })}
            {(rejected > 0 || (draft.data?.stats?.rejected ?? 0) > 0) &&
              ` · ${t('cards.draft.validCount', {
                valid: draft.data?.stats?.valid ?? Math.max(0, cards.length - rejected),
                rejected: draft.data?.stats?.rejected ?? rejected,
              })}`}
          </summary>
          <div className="mt-s2 overflow-x-auto">
            <ProblemsTable problems={problems} />
          </div>
        </details>
      )}

      {broken ? (
        <section
          className="flex min-w-0 flex-col gap-s3 rounded-md border border-err bg-surface p-s3"
          data-testid="cards-draft-broken"
        >
          <div className="flex items-start gap-s2">
            <Icon name="warning" size={18} className="mt-0.5 shrink-0 text-err" />
            <div className="min-w-0">
              <p className="font-semibold text-ink-strong">{t('cards.draft.broken.title')}</p>
              <p className="text-sm text-muted">{t('cards.draft.broken.text')}</p>
            </div>
          </div>
          <Textarea
            label={t('cards.draft.broken.raw')}
            value={text}
            readOnly
            spellCheck={false}
            rows={phone ? 10 : 18}
            className="font-mono text-xs leading-snug"
          />
        </section>
      ) : cards.length === 0 ? (
        running ? (
          <p className="flex items-center gap-s2 text-sm text-muted">
            <Spinner size={16} />
            {t('cards.draft.run.waiting')}
          </p>
        ) : problems.length > 0 ? (
          <EmptyState icon="warning" title={t('cards.draft.noSet.title')} text={t('cards.draft.noSet.text')} />
        ) : (
          <EmptyState icon="inbox" title={t('cards.draft.empty')} />
        )
      ) : (
        groups.map((group) => (
          <section key={group.title ?? ' '} className="flex flex-col gap-s2">
            <header className="flex flex-wrap items-center gap-s2">
              <h2 className="min-w-0 flex-1 truncate font-semibold text-ink-strong">
                {group.title ?? t('cards.draft.noTopic')}
              </h2>
              <span className="text-xs text-muted">{cardsWord(t, group.cards.length)}</span>
              <Button
                variant="ghost"
                size={phone ? 'lg' : 'sm'}
                disabled={busy}
                onClick={() => setMore({ topic: group.title })}
              >
                <Icon name="plus" size={14} />
                {t('cards.draft.more.short')}
              </Button>
            </header>
            <ul className={cn('flex flex-col', phone ? 'gap-s2' : 'divide-y divide-line rounded-md border border-line bg-surface')}>
              {group.cards.map((card) =>
                !phone && editing === card.key ? (
                  <li key={card.key} className="p-s2">
                    <CardEditor
                      card={card}
                      topics={topicTitles}
                      saving={saveText.isPending}
                      onSave={(patch) => saveCard(card, patch)}
                      onCancel={() => setEditing(null)}
                    />
                  </li>
                ) : (
                  <CardRow
                    key={card.key}
                    card={card}
                    phone={phone}
                    problems={cardProblems.get(card.key)}
                    locked={busy}
                    onEdit={() => setEditing(card.key)}
                    onRemove={() => setRemoving(card)}
                  />
                ),
              )}
            </ul>
          </section>
        ))
      )}

      {/* Телефон: правка во весь экран. */}
      {phone && editingCard && (
        <CardEditor
          fullscreen
          card={editingCard}
          topics={topicTitles}
          saving={saveText.isPending}
          onSave={(patch) => saveCard(editingCard, patch)}
          onCancel={() => setEditing(null)}
        />
      )}

      {/* Телефон: действия внизу под пальцем. */}
      {phone && !editingCard && (
        <div className="fixed inset-x-0 bottom-0 z-40 flex gap-s2 border-t border-line bg-surface px-s3 pt-s2 pb-[calc(env(safe-area-inset-bottom)+8px)] shadow-2">
          {running ? (
            <Button
              size="lg"
              variant="danger"
              className="flex-1"
              loading={cancel.isPending}
              onClick={() => jobId && cancel.mutate(jobId)}
            >
              <Icon name="close" size={16} />
              {t('cards.draft.run.stop')}
            </Button>
          ) : (
            <>
              <Button
                size="lg"
                variant="secondary"
                iconOnly
                aria-label={t('cards.draft.download')}
                disabled={!canDownload}
                onClick={download}
              >
                <Icon name="download" size={18} />
              </Button>
              <Button
                size="lg"
                variant="agent"
                iconOnly
                aria-label={t('cards.draft.more.button')}
                disabled={!doc || busy}
                onClick={() => setMore({ topic: null })}
              >
                <Icon name="agent" size={18} />
              </Button>
              <Button
                size="lg"
                variant="primary"
                className="flex-1"
                disabled={!canSave}
                loading={saveSet.isPending}
                onClick={saveAsSet}
              >
                {saveLabel}
              </Button>
            </>
          )}
        </div>
      )}

      <Dialog
        open={!!removing}
        onOpenChange={(open) => !open && setRemoving(null)}
        title={t('cards.draft.remove.title')}
        footer={
          <>
            <Button variant="ghost" onClick={() => setRemoving(null)}>
              {t('common.action.cancel')}
            </Button>
            <Button
              variant="danger"
              loading={saveText.isPending}
              onClick={() => removing && removeCard(removing)}
            >
              {t('common.action.delete')}
            </Button>
          </>
        }
      >
        {removing && (
          <div className="flex flex-col gap-s2">
            <p className="text-sm text-muted">{t('cards.draft.remove.text')}</p>
            <div className="max-h-40 overflow-y-auto rounded-sm border border-line bg-surface-2 p-s2">
              {removing.editable ? (
                <CardView md={removing.q} />
              ) : (
                <pre className="whitespace-pre-wrap break-all font-mono text-xs">{removing.q}</pre>
              )}
            </div>
          </div>
        )}
      </Dialog>

      <MoreDialog
        open={!!more}
        topic={more?.topic ?? null}
        endpoint={endpoint}
        pending={generate.isPending}
        error={generate.isError ? errorText(generate.error) : null}
        onClose={() => setMore(null)}
        onRun={(count, length) => more && generateMore(more.topic, count, length)}
      />
    </div>
  )
}

// ── ход задания ──────────────────────────────────────────────────────────────

function lastProgress(events: JobEvent[]): ProgressFrame | null {
  for (let i = events.length - 1; i >= 0; i -= 1) {
    const e = events[i]
    if (e?.kind === 'progress') return (e.data ?? {}) as ProgressFrame
  }
  return null
}

function RunPanel({
  running,
  progress,
  cards,
  stopping,
  onStop,
  phone,
}: {
  running: boolean
  progress: ProgressFrame | null
  cards: number
  stopping: boolean
  onStop: () => void
  phone: boolean
}) {
  const t = useT()
  const step = typeof progress?.step === 'number' ? progress.step : null
  const total = typeof progress?.total === 'number' && progress.total > 0 ? progress.total : null
  return (
    <section
      aria-live="polite"
      className="flex flex-col gap-s2 rounded-md border border-[color-mix(in_srgb,var(--agent)_45%,var(--line))] bg-agent-bg p-s3"
      data-testid="cards-draft-progress"
    >
      <div className="flex flex-wrap items-center gap-s2">
        {running && <Spinner size={16} />}
        <span className="min-w-0 flex-1 text-sm text-ink">
          {[
            progress?.note || (running ? t('cards.draft.run.started') : t('cards.draft.run.done')),
            t('cards.draft.run.cards', { n: step ?? cards }),
          ].join(' · ')}
        </span>
        {running && !phone && (
          <Button variant="danger" size="sm" loading={stopping} onClick={onStop}>
            <Icon name="close" size={14} />
            {t('cards.draft.run.stop')}
          </Button>
        )}
      </div>
      {total !== null && (
        <Progress
          value={(step ?? 0) / total}
          tone="accent"
          label={t('cards.draft.run.of', { step: step ?? 0, total })}
        />
      )}
    </section>
  )
}

// ── карточка ─────────────────────────────────────────────────────────────────

function CardRow({
  card,
  phone,
  locked,
  problems,
  onEdit,
  onRemove,
}: {
  card: DraftCard
  phone: boolean
  /** Проблемы разбора этой карточки: есть — карточка отклонена. */
  problems?: Problem[]
  locked: boolean
  onEdit: () => void
  onRemove: () => void
}) {
  const t = useT()
  const [open, setOpen] = useState(false)

  const issues = problems?.length ? (
    <ul className="flex flex-col gap-0.5 text-xs text-warn" data-testid="cards-draft-card-problems">
      <li className="font-medium">{t('cards.draft.rejected')}</li>
      {problems.map((p, i) => {
        const field = problemField(t, p)
        return (
          <li key={`${p.code ?? ''}-${i}`} className="break-words">
            {field ? t('cards.draft.problemAt', { place: field, text: p.text ?? '' }) : p.text}
          </li>
        )
      })}
    </ul>
  ) : null

  const question = card.editable ? (
    <CardView md={card.q} className="min-w-0 flex-1 overflow-x-auto" />
  ) : (
    <div className="flex min-w-0 flex-1 flex-col gap-1">
      <span className="text-xs text-warn">{t('cards.draft.notObject')}</span>
      <pre className="m-0 overflow-x-auto whitespace-pre-wrap break-all font-mono text-xs text-ink">{card.q}</pre>
    </div>
  )

  const answer = (
    <div className="flex flex-col gap-s2 border-t border-line pt-s2">
      <CardView md={card.a} className="min-w-0 overflow-x-auto" />
      {card.note && (
        <details className="text-sm">
          <summary className="min-h-11 cursor-pointer content-center text-muted">{t('cards.draft.note')}</summary>
          <CardView md={card.note} className="min-w-0 overflow-x-auto" />
        </details>
      )}
    </div>
  )

  const actions = (
    <div className="flex shrink-0 items-start gap-1">
      <Button
        variant="ghost"
        size={phone ? 'lg' : 'sm'}
        iconOnly
        aria-label={t('cards.draft.edit.button')}
        title={t('cards.draft.edit.button')}
        disabled={locked || !card.editable}
        onClick={onEdit}
      >
        <Icon name="edit" size={15} />
      </Button>
      <Button
        variant="ghost"
        size={phone ? 'lg' : 'sm'}
        iconOnly
        aria-label={t('cards.draft.remove.button')}
        title={t('cards.draft.remove.button')}
        disabled={locked}
        onClick={onRemove}
      >
        <Icon name="trash" size={15} />
      </Button>
    </div>
  )

  if (phone) {
    return (
      <li
        className={cn(
          'flex flex-col gap-s2 rounded-md border bg-surface p-s3 shadow-1',
          issues ? 'border-warn' : 'border-line',
        )}
      >
        <div className="flex items-start gap-s2">
          {card.editable ? (
            <button
              type="button"
              aria-expanded={open}
              className="flex min-h-11 min-w-0 flex-1 items-start gap-s2 text-left"
              onClick={() => setOpen((o) => !o)}
            >
              <Icon name={open ? 'chevronDown' : 'chevronRight'} size={16} className="mt-1 shrink-0 text-muted" />
              <span className="shrink-0 pt-0.5 font-mono text-xs text-muted">{card.index + 1}</span>
              {question}
            </button>
          ) : (
            question
          )}
          {actions}
        </div>
        {issues}
        {open && card.editable && answer}
      </li>
    )
  }

  return (
    <li className="grid grid-cols-[2.5rem_minmax(0,1fr)_auto] gap-s2 px-s3 py-s2">
      {/* Номер — место в массиве `cards`, тот же, что в проблемах разбора. */}
      <span className="pt-0.5 text-right font-mono text-xs text-muted">{card.index + 1}</span>
      <div className="flex min-w-0 flex-col gap-s2">
        <div className="flex min-w-0 items-start gap-s2">
          {question}
          {card.editable && (
            <Button variant="ghost" size="sm" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
              {t(open ? 'cards.draft.hideAnswer' : 'cards.draft.showAnswer')}
            </Button>
          )}
        </div>
        {issues}
        {open && card.editable && answer}
      </div>
      {actions}
    </li>
  )
}

// ── догенерация ──────────────────────────────────────────────────────────────

function MoreDialog({
  open,
  topic,
  endpoint,
  pending,
  error,
  onClose,
  onRun,
}: {
  open: boolean
  topic: string | null
  endpoint: string | null
  pending: boolean
  error: string | null
  onClose: () => void
  onRun: (count: number, length: AnswerLength) => void
}) {
  const t = useT()
  const [count, setCount] = useState(10)
  const [length, setLength] = useState<AnswerLength>('short')
  const ok = Number.isInteger(count) && count >= 1 && count <= MAX_CARDS && !!endpoint

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => !o && onClose()}
      title={topic ? t('cards.draft.more.titleTopic', { topic }) : t('cards.draft.more.title')}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            {t('common.action.cancel')}
          </Button>
          <Button variant="agent" disabled={!ok} loading={pending} onClick={() => onRun(count, length)}>
            <Icon name="agent" size={15} />
            {t('cards.draft.more.run', { n: count })}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-s3">
        <Field label={t('cards.draft.more.count')} hint={t('cards.generate.count.limit', { max: MAX_CARDS })}>
          <Input
            type="number"
            inputMode="numeric"
            min={1}
            max={MAX_CARDS}
            value={Number.isFinite(count) ? count : ''}
            onChange={(e) => setCount(Math.trunc(Number(e.target.value)))}
            aria-label={t('cards.draft.more.count')}
            wrapperClassName="w-28"
          />
        </Field>
        <Field label={t('cards.generate.length.label')}>
          <Segmented
            label={t('cards.generate.length.label')}
            value={length}
            onChange={setLength}
            options={[
              { value: 'short', label: t('cards.generate.length.short') },
              { value: 'full', label: t('cards.generate.length.full') },
            ]}
          />
        </Field>
        {!endpoint && (
          <p className="text-sm text-warn">
            {t('cards.generate.run.noEndpoint')}{' '}
            <Link to="/settings/agent" className="underline">
              {t('cards.generate.run.toSettings')}
            </Link>
          </p>
        )}
        {error && <p className="text-sm text-err">{error}</p>}
      </div>
    </Dialog>
  )
}

// ── слова ────────────────────────────────────────────────────────────────────

function cardsWord(t: T, n: number): string {
  return `${n} ${plural(n, [t('cards.draft.word.card1'), t('cards.draft.word.card2'), t('cards.draft.word.card5')])}`
}

function stats(t: T, cards: number, topics: number): string {
  const topicsWord = plural(topics, [
    t('cards.draft.word.topic1'),
    t('cards.draft.word.topic2'),
    t('cards.draft.word.topic5'),
  ])
  return `${cardsWord(t, cards)} · ${topics} ${topicsWord}`
}
