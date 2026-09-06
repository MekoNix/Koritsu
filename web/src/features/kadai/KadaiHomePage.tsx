/**
 * KadaiHomePage — главная модуля «Решения»: работа → её решения.
 *
 * Два уровня, а не один, потому что их два и на томе: работа держит материалы,
 * артефакты и потолок расхода, а решений в ней столько, сколько задач задали, и
 * у каждого своё условие, свои пожелания, свой ход стадий, свой список блоков и
 * своя папка файлов контекста. Пока экран показывал одну работу как одно
 * решение, вторая задача в ней затирала первую.
 *
 * Работы берутся из текущего пространства: в другом пространстве чужих работ не
 * видно, и список здесь — это список того пространства, в котором человек
 * сейчас работает.
 *
 * **Прогон отсюда не запускается.** «Создать решение» ведёт на страницу нового
 * запуска (условие, пожелания, файлы контекста), а платный прогон начинается на
 * экране решения — после того, как человек подтвердит распознанное условие.
 */
import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'

import { errorText } from '@/api'
import { useCurrentWorkspace } from '@/api/hooks'
import { useT } from '@/i18n'
import { Button, EmptyState, ErrorState, Field, Icon, Input, Select, SkeletonLines } from '@/ui'
import { useCreateProject, useProjects } from '@/features/projects/data'

import { WorkspaceCaption } from '@/features/workspace/WorkspaceCaption'

import { useDeleteKadaiRun, useKadaiRuns } from './data'
import type { KadaiRunCard } from './types'

export function KadaiHomePage() {
  const t = useT()
  const navigate = useNavigate()
  const workspace = useCurrentWorkspace()
  const projects = useProjects(workspace.data?.id)
  const { projectId: изАдреса } = useParams()

  const [выбран, setВыбран] = useState('')
  const [заводим, setЗаводим] = useState(false)

  // Работа из адреса старше выбранной руками: сюда ведёт «открыть в модуле» со
  // страницы работы, и показать в этот момент чужой список значило бы не
  // послушаться перехода. Пусто в обоих — первая работа пространства: список из
  // одной работы иначе требовал бы выбрать её вручную ни за чем.
  const работы = useMemo(() => projects.data ?? [], [projects.data])
  const текущая = изАдреса || выбран || работы[0]?.id || ''
  useEffect(() => {
    if (изАдреса) setВыбран(изАдреса)
  }, [изАдреса])

  return (
    <div className="flex flex-col gap-s5">
      <header className="flex flex-wrap items-end justify-between gap-s3">
        <div>
          {/* Выбор работы — про текущее пространство: подпись отвечает на
              «где эти работы лежат» до того, как человек полезет искать
              пропавшую в другом пространстве. */}
          <WorkspaceCaption className="mb-1" />
          <h1 className="font-display text-2xl font-semibold text-ink-strong">
            {t('kadai.home.title')}
          </h1>
          <p className="max-w-[64ch] text-sm text-muted">{t('kadai.home.subtitle')}</p>
        </div>
        <div className="flex flex-wrap items-center gap-s2">
          <Button variant="secondary" onClick={() => setЗаводим((v) => !v)}>
            <Icon name={заводим ? 'close' : 'plus'} size={16} />
            {заводим ? t('common.action.cancel') : t('kadai.home.newWork')}
          </Button>
          <Button
            variant="primary"
            disabled={!текущая}
            onClick={() => navigate(`/kadai/${текущая}/new`)}
          >
            <Icon name="plus" size={16} />
            {t('kadai.home.create')}
          </Button>
        </div>
      </header>

      {заводим && (
        <NewWork
          workspaceId={workspace.data?.id}
          onDone={(projectId) => {
            setВыбран(projectId)
            setЗаводим(false)
            navigate(`/kadai/${projectId}/new`)
          }}
        />
      )}

      {projects.isPending ? (
        <SkeletonLines count={3} />
      ) : projects.isError ? (
        <ErrorState error={projects.error} onRetry={() => projects.refetch()} />
      ) : работы.length === 0 ? (
        <EmptyState
          icon="tasks"
          title={t('kadai.home.emptyTitle')}
          text={t('kadai.home.emptyText')}
          action={
            <Button variant="primary" onClick={() => setЗаводим(true)}>
              {t('kadai.home.newWork')}
            </Button>
          }
        />
      ) : (
        <>
          <Select
            label={t('kadai.home.work')}
            hint={t('kadai.home.workHint', { workspace: workspace.data?.name ?? '' })}
            value={текущая}
            className="max-w-[420px]"
            onChange={(e) => {
              setВыбран(e.target.value)
              navigate(`/kadai/${e.target.value}`)
            }}
          >
            {работы.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </Select>
          {текущая && <SolutionList projectId={текущая} />}
        </>
      )}
    </div>
  )
}

/**
 * Решения выбранной работы карточками.
 *
 * Список спрашивается у службы, а не складывается из журнала запусков: он же
 * чинит работы, заведённые до появления второго решения — первое переезжает из
 * корня работы в свой каталог со всем, что у него было.
 */
function SolutionList({ projectId }: { projectId: string }) {
  const t = useT()
  const runs = useKadaiRuns(projectId)
  const удалить = useDeleteKadaiRun()

  if (runs.isPending) return <SkeletonLines count={4} />
  if (runs.isError) return <ErrorState error={runs.error} onRetry={() => runs.refetch()} />
  if ((runs.data ?? []).length === 0) {
    return (
      <EmptyState
        icon="tasks"
        title={t('kadai.home.noRunsTitle')}
        text={t('kadai.home.noRunsText')}
        action={
          <Button variant="primary" asChild>
            <Link to={`/kadai/${projectId}/new`}>{t('kadai.home.create')}</Link>
          </Button>
        }
      />
    )
  }

  return (
    <>
      <ul
        className="grid gap-s3 [grid-template-columns:repeat(auto-fill,minmax(260px,1fr))]"
        data-testid="kadai-runs"
      >
        {(runs.data ?? []).map((решение) => (
          <li key={решение.id}>
            <article className="flex h-full flex-col gap-s2 rounded-md border border-line bg-surface p-s3 shadow-1">
              <Link
                to={`/kadai/${projectId}/${решение.id}`}
                className="flex items-center gap-s2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
              >
                <Icon name="tasks" size={16} style={{ color: 'var(--mod-kadai)' }} />
                <span className="truncate font-semibold text-ink-strong">{имя(решение, t)}</span>
              </Link>
              <span className="truncate text-xs text-muted">
                {решение.condition_name || t('kadai.home.noCondition')}
              </span>
              <span className="mt-auto flex flex-wrap items-center gap-s2 text-xs text-muted">
                <span>{решение.stage || t('kadai.home.notStarted')}</span>
                <span>{когда(решение.created_at)}</span>
                <Button
                  variant="ghost"
                  size="sm"
                  className="ml-auto"
                  disabled={удалить.isPending}
                  onClick={() => удалить.mutate({ projectId, runId: решение.id })}
                >
                  {t('common.action.delete')}
                </Button>
              </span>
            </article>
          </li>
        ))}
      </ul>
      {удалить.isError && <p className="text-sm text-err">{errorText(удалить.error)}</p>}
    </>
  )
}

/**
 * Форма заведения работы: одно имя.
 *
 * Условие, пожелания и файлы контекста принадлежат решению, а не работе, и
 * спрашиваются на следующем шаге — на странице нового запуска, куда эта форма и
 * ведёт.
 */
function NewWork({
  workspaceId,
  onDone,
}: {
  workspaceId: string | undefined
  onDone: (projectId: string) => void
}) {
  const t = useT()
  const create = useCreateProject()
  const [name, setName] = useState('')
  const [беда, setБеда] = useState<string | null>(null)

  async function завести() {
    if (!workspaceId || !name.trim()) return
    setБеда(null)
    try {
      const проект = await create.mutateAsync({
        workspaceId,
        name: name.trim(),
        template: null,
        module: 'kadai',
      })
      onDone(проект.id)
    } catch (е) {
      setБеда(errorText(е))
    }
  }

  return (
    <section className="flex flex-col gap-s3 rounded-md border border-line bg-surface p-s4 shadow-1">
      <h2 className="font-display text-lg font-semibold text-ink-strong">
        {t('kadai.home.newWork')}
      </h2>
      <Field label={t('kadai.new.workName')} htmlFor="kadai-work-name">
        <Input
          id="kadai-work-name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder={t('kadai.new.namePlaceholder')}
        />
      </Field>
      <Button
        variant="primary"
        className="self-start"
        disabled={!workspaceId || !name.trim()}
        loading={create.isPending}
        onClick={() => void завести()}
      >
        {t('kadai.home.newWorkSubmit')}
      </Button>
      {беда && <p className="text-sm text-err">{беда}</p>}
    </section>
  )
}

/** Имя решения: своё, если дали, иначе «Решение N» — номер считает служба. */
function имя(
  решение: KadaiRunCard,
  t: (key: string, vars?: Record<string, string | number>) => string,
) {
  return решение.name || t('kadai.home.runName', { n: решение.n })
}

/** Время человеку: дата и часы, без секунд. */
function когда(iso: string | null | undefined): string {
  if (!iso) return ''
  const дата = new Date(iso)
  if (Number.isNaN(дата.getTime())) return iso
  return дата.toLocaleString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}
