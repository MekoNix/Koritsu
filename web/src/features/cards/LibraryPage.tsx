/**
 * LibraryPage — главная «Тренажёра»: наборы карточек текущего пространства.
 *
 * У каждого набора — название, число тем и карточек и **моя** доля «знаю»: прогресс
 * личный, другие участники и автор набора его не видят. «Решать» сразу заводит заход
 * по моим настройкам; название ведёт на страницу набора, где настройки, темы и список.
 *
 * Работы здесь нет, как у доски и ассемблера: набор — решение неявной работы, но
 * выбирать её незачем.
 *
 * **Две раскладки.** На компьютере — сетка карточек; на телефоне — одна колонка,
 * кнопки во всю ширину и высотой под палец.
 *
 * **Пусто.** Владелец и редактор видят три входа: «Загрузить файл», «Создать агентом»
 * и «Пример набора» (текст примера идёт обычной загрузкой, с превью). Читатель наборы не
 * создаёт — ему сказано, откуда они появятся.
 */
import { useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import { useCurrentWorkspace } from '@/api/hooks'
import { useT } from '@/i18n'
import { BetaTag, Button, EmptyState, ErrorState, Icon, Input, Progress, SkeletonLines, useToast } from '@/ui'
import { canEditWorkspace } from '@/features/projects/data'
import { WorkspaceCaption } from '@/features/workspace/WorkspaceCaption'

import { useCardSets, useStartSession } from './api'
import { cardsPaths, type PlayLocationState } from './paths'
import { hasSample } from './samples'
import { knownPercent, type CardSetInfo } from './types'

export function LibraryPage() {
  const t = useT()
  const navigate = useNavigate()
  const toast = useToast()
  const workspace = useCurrentWorkspace()
  const sets = useCardSets(workspace.data?.id)
  const start = useStartSession()
  const [query, setQuery] = useState('')
  const [стартует, setСтартует] = useState<string | null>(null)
  const canEdit = canEditWorkspace(workspace.data?.role)

  const найденные = useMemo(() => {
    const q = query.trim().toLowerCase()
    const все = sets.data ?? []
    return q ? все.filter((s) => (s.title || '').toLowerCase().includes(q)) : все
  }, [sets.data, query])

  const решать = (s: CardSetInfo) => {
    setСтартует(s.set_id)
    start.mutate(
      { projectId: s.project_id, setId: s.set_id, preset: 'settings' },
      {
        onSuccess: (session) => {
          const state: PlayLocationState = { start: session }
          navigate(cardsPaths.play(s.project_id, s.set_id, session.session_id), { state })
        },
        onError: (беда) => toast.fail(беда, t('cards.common.startFailed')),
        onSettled: () => setСтартует(null),
      },
    )
  }

  const кнопкаЗагрузки = (
    <Button variant="primary" className="max-[640px]:min-h-[44px] max-[640px]:flex-1" onClick={() => navigate(cardsPaths.upload)}>
      <Icon name="upload" size={16} />
      {t('cards.library.upload')}
    </Button>
  )
  const кнопкаАгента = (
    <Button variant="agent" className="max-[640px]:min-h-[44px] max-[640px]:flex-1" onClick={() => navigate(cardsPaths.generate())}>
      <Icon name="agent" size={16} />
      {t('cards.library.generate')}
    </Button>
  )

  const пусто = (sets.data ?? []).length === 0

  return (
    <div className="flex flex-col gap-s5">
      <header className="flex flex-wrap items-end justify-between gap-s3">
        <div className="min-w-0">
          <WorkspaceCaption ws={workspace.data} className="mb-1" />
          <h1 className="m-0 flex items-center gap-s2 font-display text-2xl font-semibold text-ink-strong max-[640px]:text-xl">
            {t('cards.title')}
            <BetaTag label={t('shell.beta')} />
          </h1>
          <p className="m-0 max-w-[64ch] text-sm text-muted">{t('cards.library.subtitle')}</p>
        </div>
        {canEdit && !пусто && (
          <div className="flex flex-wrap gap-s2 max-[640px]:w-full">
            {кнопкаЗагрузки}
            {кнопкаАгента}
          </div>
        )}
      </header>

      {sets.isPending || workspace.isPending ? (
        <SkeletonLines count={4} />
      ) : sets.isError ? (
        <ErrorState error={sets.error} onRetry={() => void sets.refetch()} />
      ) : пусто ? (
        <EmptyState
          icon="cards"
          title={t('cards.library.emptyTitle')}
          text={canEdit ? t('cards.library.emptyText') : t('cards.library.emptyViewer')}
          className="max-[640px]:px-0"
          action={
            canEdit ? (
              <div className="flex flex-wrap justify-center gap-s2 max-[640px]:w-[min(360px,calc(100vw-32px))] max-[640px]:flex-col">
                {кнопкаЗагрузки}
                {кнопкаАгента}
                {hasSample && (
                  <Button variant="secondary" className="max-[640px]:min-h-[44px]" onClick={() => navigate(cardsPaths.sample)}>
                    <Icon name="file" size={16} />
                    {t('cards.library.sample')}
                  </Button>
                )}
              </div>
            ) : undefined
          }
        />
      ) : (
        <>
          {(sets.data ?? []).length > 3 && (
            <Input
              value={query}
              type="search"
              className="max-[640px]:min-h-[44px] max-[640px]:text-md"
              wrapperClassName="min-[641px]:max-w-[420px]"
              icon={<Icon name="search" size={16} />}
              placeholder={t('cards.library.search')}
              aria-label={t('cards.library.search')}
              onChange={(e) => setQuery(e.target.value)}
            />
          )}
          {найденные.length === 0 ? (
            <EmptyState icon="search" title={t('cards.library.nothingFound')} />
          ) : (
            <ul className="m-0 flex list-none flex-col gap-s3 p-0 min-[641px]:grid min-[641px]:[grid-template-columns:repeat(auto-fill,minmax(280px,1fr))]">
              {найденные.map((s) => (
                <li key={`${s.project_id}/${s.set_id}`} className="min-w-0">
                  <SetTile set={s} starting={стартует === s.set_id} onSolve={() => решать(s)} />
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </div>
  )
}

function SetTile({ set, starting, onSolve }: { set: CardSetInfo; starting: boolean; onSolve: () => void }) {
  const t = useT()
  const процент = knownPercent(set.my_known, set.cards)
  const адрес = cardsPaths.set(set.project_id, set.set_id)
  return (
    <article className="flex h-full flex-col gap-s3 rounded-md border border-line bg-surface p-s4 shadow-1">
      <Link
        to={адрес}
        className="flex min-h-[44px] items-start gap-s2 text-ink-strong no-underline hover:no-underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
      >
        <Icon name="cards" size={18} className="mt-0.5" style={{ color: 'var(--mod-cards)' }} />
        <span className="line-clamp-2 min-w-0 break-words font-semibold">{set.title || t('cards.common.untitled')}</span>
      </Link>
      <p className="m-0 text-xs text-muted">
        {t('cards.common.topicsCount', { n: set.topics })} · {t('cards.common.cardsCount', { n: set.cards })}
      </p>
      <div className="flex items-center gap-s3">
        <Progress
          value={процент / 100}
          tone={процент === 100 ? 'ok' : 'accent'}
          label={t('cards.common.knownPercent', { p: процент })}
          className="flex-1"
        />
        <span className="shrink-0 font-mono text-xs text-muted">{t('cards.common.knownPercent', { p: процент })}</span>
      </div>
      <div className="mt-auto flex gap-s2">
        <Button
          variant="primary"
          className="flex-1 max-[640px]:min-h-[44px]"
          loading={starting}
          disabled={!set.cards}
          onClick={onSolve}
        >
          {t('cards.library.solve')}
        </Button>
        <Button asChild variant="secondary" className="max-[640px]:min-h-[44px]">
          <Link to={адрес}>{t('cards.library.open')}</Link>
        </Button>
      </div>
    </article>
  )
}
