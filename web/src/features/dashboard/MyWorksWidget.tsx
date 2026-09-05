/**
 * MyWorksWidget — «Мои работы»: последние заведённые работы.
 *
 * Имя виджета — из правки 2 макетов: иерархии «Проекты / … / Отчёт» нет, есть
 * работа как папка (документ, файлы, схемы), и на дашборде она называется так
 * же, как в сайдбаре.
 *
 * Показываются пять последних. Служба отдаёт список в порядке создания,
 * поэтому свежие берутся с конца — сортировать по `updated_at` на клиенте
 * значило бы каждый раз показывать разное при одинаковом ответе службы
 * (у работы, которую только что открыли, время меняется от чтения тегов).
 */
import { Link } from 'react-router-dom'

import { useT } from '@/i18n'
import { Button, EmptyState, ErrorState, Icon, Skeleton } from '@/ui'
import { usePersonalWorkspace, useProjects } from '@/features/projects/data'
import { formatWhen } from '@/features/projects/format'

import { Widget } from './Widget'

const СКОЛЬКО = 5

export function MyWorksWidget() {
  const t = useT()
  const workspace = usePersonalWorkspace()
  const projects = useProjects(workspace.data?.id)

  const последние = [...(projects.data ?? [])].reverse().slice(0, СКОЛЬКО)

  return (
    <Widget
      title={t('dashboard.works.title')}
      note={t('dashboard.works.note')}
      className="lg:col-span-12"
      action={
        <Button variant="ghost" size="sm" asChild>
          <Link to="/projects">{t('dashboard.works.all')}</Link>
        </Button>
      }
      flush
    >
      {projects.isPending ? (
        <ul className="flex flex-col gap-s2 px-s4 pb-s4">
          {[0, 1, 2].map((i) => (
            <li key={i} className="flex items-center gap-s3">
              <Skeleton className="h-5 w-5 rounded-sm" />
              <Skeleton className="w-1/4" />
            </li>
          ))}
        </ul>
      ) : projects.isError ? (
        <div className="px-s4 pb-s4">
          <ErrorState error={projects.error} onRetry={() => void projects.refetch()} />
        </div>
      ) : последние.length === 0 ? (
        <EmptyState
          compact
          icon="folder"
          title={t('dashboard.works.empty')}
          text={t('dashboard.works.emptyHint')}
          action={
            <Button variant="primary" size="sm" asChild>
              <Link to="/projects">
                <Icon name="plus" size={16} />
                {t('projects.list.create')}
              </Link>
            </Button>
          }
        />
      ) : (
        <ul className="divide-y divide-line border-t border-line">
          {последние.map((project) => (
            <li key={project.id}>
              <Link
                to={`/projects/${project.id}`}
                className="flex min-w-0 items-center gap-s3 px-s4 py-s3 hover:bg-surface-2"
              >
                <Icon name="folder" className="shrink-0 text-muted" />
                <span className="min-w-0 flex-1 truncate text-sm font-medium text-ink-strong">
                  {project.name}
                </span>
                <span className="shrink-0 text-xs text-muted">
                  {formatWhen(project.updated_at)}
                </span>
                <Icon name="chevronRight" size={16} className="shrink-0 text-muted" />
              </Link>
            </li>
          ))}
        </ul>
      )}
    </Widget>
  )
}
