/**
 * DiagramsHome — главная страница модуля: что уже построено и где строить новое.
 *
 * Схема живёт в проекте — там её артефакт и там её тег, — поэтому список
 * собирается из значений проектов: значение вида `diagram` и есть сохранённая
 * схема. Отдельного маршрута «мои схемы» у службы нет, и заводить его ради
 * одной страницы было бы дороже, чем сложить список здесь: пространства →
 * проекты → значения.
 *
 * Список пустой — не белое поле, а приглашение: пустое состояние обязано
 * предлагать действие, и действие здесь одно — начать новую схему в
 * проекте. Проектов нет вовсе — состояние другое и ведёт оно в другое место:
 * чинить нечего, пока нет проекта.
 *
 * **Список у двух модулей один и тот же, и это не недосмотр.** В значении тега
 * записано, что там схема (`type: "diagram"`), но не записано, кто её построил:
 * блок-схема и диаграмма классов лежат одинаково. Делить список по догадке
 * (скажем, по имени тега) значило бы прятать от человека его же схему всякий
 * раз, когда он назвал тег по-своему.
 */
import { useQueries, useQuery } from '@tanstack/react-query'
import { Link, useNavigate } from 'react-router-dom'

import { errorText, keys } from '@/api'
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

import { diagramsOf, fetchAllProjects, fetchArtifact, fetchValues } from './api'
import { safeFilename, saveBlob } from './download'
import type { Module } from './DiagramWorkbench'
import type { SavedDiagram } from './types'

export function DiagramsHome({ module }: { module: Module }) {
  const t = useT()
  const toast = useToast()
  const navigate = useNavigate()
  const корень = module === 'uml' ? '/uml' : '/flowcharts'

  const projects = useQuery({
    queryKey: keys.diagrams.projects,
    queryFn: fetchAllProjects,
  })

  // Значения — по запросу на проект: одного маршрута «значения всех проектов»
  // у службы нет, а склеивать их в один запрос значило бы завести его.
  const значения = useQueries({
    queries: (projects.data ?? []).map((project) => ({
      queryKey: keys.diagrams.values(project.id),
      queryFn: () => fetchValues(project.id),
    })),
  })

  const схемы: SavedDiagram[] = (projects.data ?? []).flatMap((project, i) => {
    const тело = значения[i]?.data
    return тело ? diagramsOf(project, тело) : []
  })
  const грузится = projects.isPending || значения.some((q) => q.isPending)

  const заголовок = t(
    module === 'uml' ? 'diagrams.home.uml.title' : 'diagrams.home.flowcharts.title',
  )
  const описание = t(module === 'uml' ? 'diagrams.home.uml.lead' : 'diagrams.home.flowcharts.lead')

  return (
    <section className="flex flex-col gap-s4">
      <header className="flex flex-wrap items-start justify-between gap-s3">
        <div className="flex min-w-0 flex-col gap-s2">
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
              {схемы.map((схема) => (
                <li
                  key={`${схема.project.id}:${схема.key}`}
                  className="flex flex-wrap items-center gap-s3 rounded-md border border-line bg-surface p-s3"
                >
                  <Icon
                    name={module === 'uml' ? 'uml' : 'flowchart'}
                    size={18}
                    className="text-muted"
                  />
                  <div className="flex min-w-0 flex-col">
                    <span className="truncate text-sm font-semibold text-ink-strong">
                      {схема.value.caption || схема.key}
                    </span>
                    <span className="truncate text-xs text-muted">
                      {t('diagrams.home.inProject')}: {схема.project.name} ·{' '}
                      {t('diagrams.home.tag')}: {схема.key}
                    </span>
                  </div>
                  <div className="grow" />
                  {схема.value.artifact && (
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() =>
                        void fetchArtifact(схема.project.id, схема.value.artifact as string)
                          .then((blob) => saveBlob(blob, safeFilename(схема.key, 'drawio.xml')))
                          .catch((беда: unknown) =>
                            toast.error(t('diagrams.work.downloadXml'), errorText(беда)),
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
                    onClick={() =>
                      navigate(
                        `${корень}/${схема.project.id}${
                          схема.value.artifact ? `?artifact=${схема.value.artifact}` : ''
                        }`,
                      )
                    }
                  >
                    {t('diagrams.home.open')}
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  )
}

/**
 * «Новая схема». Проект один — сразу в него; несколько — меню выбора.
 *
 * Меню, а не отдельная страница выбора: выбор проекта здесь — это один клик,
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
