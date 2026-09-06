/**
 * DiagramsHome — главная страница модуля: что уже построено и где строить новое.
 *
 * Схема живёт в работе: там её XML артефактом, там её запись в журнале запусков
 * и там же код, которым она построена. Поэтому список собирается по работам
 * человека — `GET …/flowcharts` или `GET …/uml` на каждую.
 *
 * **Список у каждого модуля свой, и это главное отличие от прежнего.** Раньше
 * схемы отбирались из значений тегов, а в значении не записано, кто схему
 * построил: блок-схема и диаграмма классов лежали там одинаково и попадали в
 * оба списка сразу. Теперь модуль записан у самой схемы, и человек, пришедший
 * за схемой алгоритма, не разбирает её среди диаграмм классов.
 *
 * Имя схемы рисуется из модуля, номера и названия работы («Схема 2 —
 * Курсовая») тем же `runTitle`, что и в журнале работы: имя одно, и второе
 * такое же правило разошлось бы с первым.
 *
 * Список пустой — не белое поле, а приглашение: пустое состояние обязано
 * предлагать действие, и действие здесь одно — начать новую схему в
 * работе. Работ нет вовсе — состояние другое и ведёт оно в другое место:
 * чинить нечего, пока нет работы.
 */
import { useMutation, useQueries, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate } from 'react-router-dom'

import { keys } from '@/api'
import { useCurrentWorkspace } from '@/api/hooks'
// Имя запуска и короткая дата — те же, что в журнале работы (`runTitle`,
// `formatWhen`): одна и та же схема не может называться на двух экранах
// по-разному.
import { RunName } from '@/features/projects/RunName'
import { formatWhen, runTitle } from '@/features/projects/format'
import { useT } from '@/i18n'
import {
  Button,
  EmptyState,
  ErrorState,
  Icon,
  MenuContent,
  MenuItem,
  MenuLabel,
  MenuRoot,
  MenuTrigger,
  SkeletonLines,
  useToast,
} from '@/ui'

import { WorkspaceCaption, WorkspaceTag } from '@/features/workspace/WorkspaceCaption'

import { deleteDiagram, fetchArtifact, fetchDiagrams, fetchWorkspaceProjects } from './api'
import { safeFilename, saveBlob } from './download'
import type { DiagramInProject, Module } from './types'

export function DiagramsHome({ module }: { module: Module }) {
  const t = useT()
  const toast = useToast()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const корень = module === 'uml' ? '/uml' : '/flowcharts'

  // Работы текущего пространства, а не все сразу: в пространстве кафедры на
  // главной схем личным работам делать нечего. Пространство входит в ключ кэша
  // — иначе переключение показывало бы прежний список до его устаревания.
  const workspace = useCurrentWorkspace()
  const workspaceId = workspace.data?.id ?? ''
  const projects = useQuery({
    queryKey: keys.diagrams.projects(workspaceId),
    enabled: !!workspaceId,
    queryFn: () => fetchWorkspaceProjects(workspaceId),
  })

  // По запросу на работу: списка «схемы всех работ» у службы нет, а склеивать
  // их в один запрос значило бы завести его.
  const списки = useQueries({
    queries: (projects.data ?? []).map((project) => ({
      queryKey: keys.diagrams.list(module, project.id),
      queryFn: () => fetchDiagrams(module, project.id),
    })),
  })

  const схемы: DiagramInProject[] = (projects.data ?? []).flatMap((project, i) =>
    (списки[i]?.data ?? []).map((diagram) => ({ project, diagram })),
  )
  const грузится = projects.isPending || списки.some((q) => q.isPending)

  const удалить = useMutation({
    mutationFn: ({ projectId, runId }: { projectId: string; runId: string }) =>
      deleteDiagram(projectId, runId),
    onSuccess: (_итог, { projectId }) => {
      void qc.invalidateQueries({ queryKey: keys.diagrams.list(module, projectId) })
      // Запись журнала — та же самая: список «Что в работе» на странице работы
      // обязан обновиться тем же действием.
      void qc.invalidateQueries({ queryKey: keys.projects.one(projectId) })
    },
    onError: (беда: unknown) => toast.fail(беда, t('diagrams.home.removeFailed')),
  })

  const заголовок = t(
    module === 'uml' ? 'diagrams.home.uml.title' : 'diagrams.home.flowcharts.title',
  )
  const описание = t(module === 'uml' ? 'diagrams.home.uml.lead' : 'diagrams.home.flowcharts.lead')

  return (
    <section className="flex flex-col gap-s4">
      <header className="flex flex-wrap items-start justify-between gap-s3">
        <div className="flex min-w-0 flex-col gap-s2">
          {/* Схемы показываются по работам текущего пространства — подпись
              говорит, по какому именно. */}
          <WorkspaceCaption ws={workspace.data} />
          <h1 className="font-display text-xl font-bold tracking-tight text-ink-strong">
            {заголовок}
          </h1>
          <p className="max-w-[70ch] text-sm text-muted">{описание}</p>
        </div>
        <NewDiagramButton projects={projects.data ?? []} root={корень} />
      </header>

      {projects.isError && (
        <ErrorState error={projects.error} onRetry={() => void projects.refetch()} />
      )}

      {!projects.isError && (
        <div className="flex flex-col gap-s3">
          <h2 className="text-sm font-semibold uppercase tracking-wider text-muted">
            {t('diagrams.home.saved')}
          </h2>

          {грузится && <SkeletonLines count={4} />}

          {!грузится && схемы.length === 0 && (projects.data ?? []).length > 0 && (
            <EmptyState
              icon={module === 'uml' ? 'uml' : 'flowchart'}
              title={t('diagrams.home.emptyTitle')}
              text={t('diagrams.home.emptyText')}
              action={<NewDiagramButton projects={projects.data ?? []} root={корень} />}
            />
          )}

          {!грузится && (projects.data ?? []).length === 0 && (
            <EmptyState
              icon="folder"
              title={t('diagrams.home.noProjectsTitle')}
              text={t('diagrams.home.noProjectsText')}
              action={
                <Button variant="primary" asChild>
                  <Link to="/projects">{t('diagrams.home.toProjects')}</Link>
                </Button>
              }
            />
          )}

          {схемы.length > 0 && (
            <ul className="flex flex-col gap-s2">
              {схемы.map(({ project, diagram }) => {
                const имя = runTitle(t, diagram, project.name)
                return (
                  <li
                    key={diagram.run_id}
                    className="flex flex-wrap items-center gap-s3 rounded-md border border-line bg-surface p-s3"
                  >
                    <Icon
                      name={module === 'uml' ? 'uml' : 'flowchart'}
                      size={18}
                      className="text-muted"
                    />
                    <div className="flex min-w-0 flex-col">
                      {/* Схема переименовывается там, где человек её нашёл:
                          карандаш рядом с именем или двойной щелчок по нему.
                          Имя схемы — это имя записи журнала, поэтому правит его
                          общий `RunName`, а не второе поле рядом. */}
                      <RunName
                        projectId={project.id}
                        runId={diagram.run_id}
                        name={diagram.name}
                        title={имя}
                        className="text-sm font-semibold text-ink-strong"
                      />
                      <span className="truncate text-xs text-muted">
                        {t('diagrams.home.inProject')}: {project.name}
                        {diagram.created_at ? ` · ${formatWhen(diagram.created_at)}` : ''}
                      </span>
                      {/* Работа названа — назовём и пространство, в котором она
                          лежит: строку схемы читают в отрыве от шапки. */}
                      <WorkspaceTag project={project} />
                    </div>
                    <div className="grow" />
                    {diagram.artifact && (
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() =>
                          void fetchArtifact(project.id, diagram.artifact)
                            .then((blob) => saveBlob(blob, safeFilename(имя, 'drawio.xml')))
                            .catch((беда: unknown) =>
                              toast.fail(беда, t('diagrams.work.downloadXml')),
                            )
                        }
                      >
                        <Icon name="download" size={14} />
                        {t('diagrams.work.downloadXml')}
                      </Button>
                    )}
                    <Button
                      size="sm"
                      variant="secondary"
                      onClick={() => navigate(`${корень}/${project.id}?run=${diagram.run_id}`)}
                    >
                      {t('diagrams.home.open')}
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      aria-label={t('diagrams.home.remove', { name: имя })}
                      loading={удалить.isPending && удалить.variables?.runId === diagram.run_id}
                      onClick={() =>
                        удалить.mutate({ projectId: project.id, runId: diagram.run_id })
                      }
                    >
                      <Icon name="trash" size={14} />
                    </Button>
                  </li>
                )
              })}
            </ul>
          )}
        </div>
      )}
    </section>
  )
}

/**
 * «Новая схема». Работа одна — сразу в неё; несколько — меню выбора.
 *
 * Меню, а не отдельная страница выбора: выбор работы здесь — это один клик,
 * а страница ради одного клика читается как ещё один шаг.
 */
function NewDiagramButton({
  projects,
  root,
}: {
  projects: { id: string; name: string }[]
  root: string
}) {
  const t = useT()
  const navigate = useNavigate()
  if (projects.length === 0) return null
  if (projects.length === 1) {
    return (
      <Button variant="primary" onClick={() => navigate(`${root}/${projects[0]?.id ?? ''}`)}>
        <Icon name="plus" size={16} />
        {t('diagrams.home.new')}
      </Button>
    )
  }
  return (
    <MenuRoot>
      <MenuTrigger asChild>
        <Button variant="primary">
          <Icon name="plus" size={16} />
          {t('diagrams.home.new')}
          <Icon name="chevronDown" size={14} />
        </Button>
      </MenuTrigger>
      <MenuContent>
        <MenuLabel>{t('diagrams.home.chooseProject')}</MenuLabel>
        {projects.map((project) => (
          <MenuItem
            key={project.id}
            icon={<Icon name="folder" size={16} />}
            onSelect={() => navigate(`${root}/${project.id}`)}
          >
            {project.name}
          </MenuItem>
        ))}
      </MenuContent>
    </MenuRoot>
  )
}
