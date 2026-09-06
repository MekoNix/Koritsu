/**
 * ReportsHomePage — главная модуля: `/reports`.
 *
 * Выбор идёт в два шага, потому что вещей тоже две: работа (курсовая, отчёт по
 * практике) и отчёты внутри неё. Отчётов в работе несколько — у каждого свой
 * бланк и свои значения, — поэтому сначала выбирают работу, а потом её отчёт.
 * Оба шага живут на одном адресе: выбранная работа стоит в `?project=`, и
 * второй шаг рисует `ProjectReportsPage`. Двум адресам здесь взяться неоткуда —
 * это один выбор, а не два экрана.
 *
 * Работы — те, что лежат в текущем пространстве: список один на всё приложение
 * (`useProjects`), и второго здесь не заводится. Отличается только то, что с
 * ними делают дальше.
 *
 * Картинка на карточке работы — набросок (`ReportThumb`): собранной первой
 * страницы у работы целиком нет, она есть у каждого её отчёта по отдельности.
 */
import { useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'

import { useT } from '@/i18n'
import { Button, EmptyState, ErrorState, Input, SkeletonLines } from '@/ui'
import { useCurrentWorkspace } from '@/api/hooks'
import { useProjects } from '@/features/projects/data'
import { WorkspaceCaption } from '@/features/workspace/WorkspaceCaption'

import { ProjectReportsPage } from './ProjectReportsPage'
import { ReportThumb } from './ReportThumb'

export function ReportsHomePage() {
  const [params] = useSearchParams()
  const выбранная = (params.get('project') ?? '').trim()
  return выбранная ? <ProjectReportsPage projectId={выбранная} /> : <ProjectPicker />
}

/** Первый шаг: какая работа. Список с поиском, карточками и наброском. */
function ProjectPicker() {
  const t = useT()
  const workspace = useCurrentWorkspace()
  const projects = useProjects(workspace.data?.id)
  const [query, setQuery] = useState('')

  const найденные = useMemo(() => {
    const запрос = query.trim().toLowerCase()
    const все = projects.data ?? []
    return запрос ? все.filter((p) => p.name.toLowerCase().includes(запрос)) : все
  }, [projects.data, query])

  return (
    <div className="flex flex-col gap-s5">
      <header className="flex flex-wrap items-end justify-between gap-s3">
        <div>
          {/* Выбор работы — про текущее пространство: подпись отвечает на
              «где эти работы лежат» до того, как человек полезет искать
              пропавшую в другом пространстве. */}
          <WorkspaceCaption className="mb-1" />
          <h1 className="font-display text-2xl font-semibold text-ink-strong">
            {t('reports.home.title')}
          </h1>
          <p className="max-w-[60ch] text-sm text-muted">{t('reports.home.subtitle')}</p>
        </div>
        <Button variant="secondary" asChild>
          <Link to="/projects">{t('reports.home.toProjects')}</Link>
        </Button>
      </header>

      <Input
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder={t('reports.home.search')}
        aria-label={t('reports.home.search')}
        className="max-w-[420px]"
      />

      {projects.isPending ? (
        <div className="grid gap-s4 [grid-template-columns:repeat(auto-fill,minmax(220px,1fr))]">
          {[0, 1, 2, 3].map((i) => (
            <SkeletonLines key={i} count={6} />
          ))}
        </div>
      ) : projects.isError ? (
        <ErrorState error={projects.error} onRetry={() => projects.refetch()} />
      ) : найденные.length === 0 ? (
        <EmptyState
          icon="file"
          title={
            projects.data?.length ? t('reports.home.nothingFound') : t('reports.home.emptyTitle')
          }
          text={projects.data?.length ? undefined : t('reports.home.emptyText')}
          action={
            projects.data?.length ? undefined : (
              <Button variant="primary" asChild>
                <Link to="/projects">{t('reports.home.create')}</Link>
              </Button>
            )
          }
        />
      ) : (
        <ul className="grid gap-s4 [grid-template-columns:repeat(auto-fill,minmax(220px,1fr))]">
          {найденные.map((p) => (
            <li key={p.id}>
              <Link
                to={`/reports?project=${encodeURIComponent(p.id)}`}
                className="flex h-full flex-col overflow-hidden rounded-md border border-line bg-surface shadow-1 transition-colors hover:border-line-strong focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
              >
                <ReportThumb seed={p.id} />
                <div className="flex flex-col gap-1 p-s3">
                  <span className="truncate font-semibold text-ink-strong">{p.name}</span>
                  <span className="text-xs text-muted">
                    {t('reports.home.updated', { at: when(p.updated_at) })}
                  </span>
                </div>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function when(iso: string): string {
  const дата = new Date(iso)
  if (Number.isNaN(дата.getTime())) return iso
  return дата.toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit', year: '2-digit' })
}
