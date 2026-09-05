/**
 * ReportsHomePage — главная модуля: выбор работы. `/reports`.
 *
 * Бриф: «главная страница модуля — выбор отчётов для генерации, поиск,
 * небольшое превью каждого». Превью — это набросок первой страницы, а не
 * настоящий рендер: настоящий стоит задания `build` на каждый проект, то есть
 * запуска LibreOffice ради картинки в списке. Набросок рисуется из
 * идентификатора проекта (тот же приём, что у генеративного аватара), поэтому
 * у одной работы он всегда один и тот же, и список не мельтешит.
 *
 * Проекты — те же, что в области B: список один на всё приложение, и второго
 * здесь не заводится. Отличается только то, что с ними делают дальше.
 */
import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'

import { useT } from '@/i18n'
import { Button, EmptyState, ErrorState, Input, SkeletonLines } from '@/ui'
import { useCurrentWorkspace } from '@/api/hooks'
import { useProjects } from '@/features/projects/data'
import type { Project } from '@/features/projects/types'

export function ReportsHomePage() {
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
                to={`/reports/${p.id}`}
                className="flex h-full flex-col overflow-hidden rounded-md border border-line bg-surface shadow-1 transition-colors hover:border-line-strong focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
              >
                <Thumb project={p} />
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

/**
 * Набросок первой страницы: строки-заглушки, разложенные по идентификатору
 * проекта. Не рендер и не притворяется им — это опознавательный знак карточки,
 * такой же, как генеративный аватар у человека.
 */
function Thumb({ project }: { project: Project }) {
  const строки = useMemo(() => {
    let seed = 0
    for (const знак of project.id) seed = (seed * 31 + знак.charCodeAt(0)) % 100000
    return Array.from({ length: 7 }, (_, i) => {
      seed = (seed * 1103515245 + 12345) % 2147483648
      return 45 + ((seed >> (i + 3)) % 50)
    })
  }, [project.id])

  return (
    <div
      aria-hidden="true"
      className="flex aspect-[1/1.05] flex-col gap-[6%] border-b border-line bg-surface-2 p-[14%]"
    >
      <span className="mx-auto mb-[4%] h-1.5 w-3/5 rounded-full bg-line-strong opacity-90" />
      {строки.map((ширина, i) => (
        <span
          key={i}
          className="h-[3px] rounded-full bg-line-strong opacity-60"
          style={{ width: `${ширина}%` }}
        />
      ))}
    </div>
  )
}

function when(iso: string): string {
  const дата = new Date(iso)
  if (Number.isNaN(дата.getTime())) return iso
  return дата.toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit', year: '2-digit' })
}
