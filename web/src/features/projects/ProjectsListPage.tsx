/**
 * ProjectsListPage — «Мои работы»: список проектов личного пространства и
 * корзина.
 *
 * **Корзина — вкладка, а не отдельный экран.** У службы это один и тот же
 * маршрут с `trash=true`, у человека — тот же список, только другого
 * содержания; заводить второй адрес значило бы завести и второе описание
 * колонок, и второй набор пустых состояний.
 *
 * Обязательные состояния: скелетон на первой загрузке, пустое с
 * приглашением завести работу, экран ошибки с повтором, «нет прав» — на 403
 * от службы (в личном пространстве он не случается, но список бывает и общим).
 *
 * Тостов здесь два вида, и оба разрешённые: на отказ службы. Успешное
 * переименование тоста не получает — человек видит новое имя в строке, и это
 * уже сообщение.
 */
import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import { ApiError, errorText } from '@/api'
import { useCurrentWorkspace } from '@/api/hooks'
import { useT } from '@/i18n'
import { cn } from '@/lib/cn'
import {
  Button,
  EmptyState,
  ErrorState,
  ForbiddenState,
  Icon,
  MenuContent,
  MenuItem,
  MenuRoot,
  MenuTrigger,
  Skeleton,
  useToast,
} from '@/ui'

import { CreateProjectDialog } from './CreateProjectDialog'
import { Panel } from './Panel'
import { RenameProjectDialog } from './RenameProjectDialog'
import { useProjects, useRestoreProject, useTrashProject } from './data'
import { formatBytes, formatWhen, plural } from './format'
import type { Project } from './types'

type Tab = 'active' | 'trash'

export function ProjectsListPage() {
  const t = useT()
  const toast = useToast()
  const navigate = useNavigate()
  const [tab, setTab] = useState<Tab>('active')
  const [creating, setCreating] = useState(false)
  const [renaming, setRenaming] = useState<Project | null>(null)

  const workspace = useCurrentWorkspace()
  const projects = useProjects(workspace.data?.id, tab === 'trash')
  const trash = useTrashProject()
  const restore = useRestoreProject()

  const fail = (error: unknown) => toast.error(errorText(error))

  const error = workspace.error ?? projects.error
  const forbidden = error instanceof ApiError && error.status === 403

  return (
    <div className="flex flex-col gap-s4">
      <header className="flex flex-wrap items-end justify-between gap-s3">
        <div className="min-w-0">
          <h1 className="font-display text-xl font-bold tracking-tight text-ink-strong">
            {t('projects.list.title')}
          </h1>
          <p className="text-sm text-muted">{t('projects.list.subtitle')}</p>
        </div>
        <Button variant="primary" onClick={() => setCreating(true)}>
          <Icon name="plus" size={16} />
          {t('projects.list.create')}
        </Button>
      </header>

      <div className="flex items-center gap-1 self-start rounded-md border border-line bg-surface p-1">
        {(['active', 'trash'] as const).map((value) => (
          <button
            key={value}
            type="button"
            onClick={() => setTab(value)}
            aria-pressed={tab === value}
            className={cn(
              'rounded-sm px-3 py-1.5 text-sm font-medium transition-colors',
              // Правило брифа: активность — фоном и насыщенностью текста,
              // никаких цветных полосок.
              tab === value ? 'bg-surface-2 text-ink-strong' : 'text-muted hover:text-ink',
            )}
          >
            {t(`projects.list.tab.${value}`)}
          </button>
        ))}
      </div>

      {forbidden ? (
        <ForbiddenState />
      ) : error ? (
        <ErrorState
          error={error}
          onRetry={() => {
            void workspace.refetch()
            void projects.refetch()
          }}
        />
      ) : projects.isPending ? (
        <ListSkeleton />
      ) : projects.data && projects.data.length > 0 ? (
        <Panel flush>
          <ul className="divide-y divide-line">
            {projects.data.map((project) => (
              <li
                key={project.id}
                className="flex min-w-0 items-center gap-s3 px-s4 py-s3 hover:bg-surface-2"
              >
                <Icon name="folder" className="shrink-0 text-muted" />
                <div className="min-w-0 flex-1">
                  {tab === 'active' ? (
                    <Link
                      to={`/projects/${project.id}`}
                      className="block truncate text-sm font-semibold text-ink-strong hover:text-accent"
                    >
                      {project.name}
                    </Link>
                  ) : (
                    <span className="block truncate text-sm font-semibold text-ink-strong">
                      {project.name}
                    </span>
                  )}
                  <span className="text-xs text-muted">
                    {tab === 'trash' && project.purge_after
                      ? t('projects.list.purgeAfter', { at: formatWhen(project.purge_after) })
                      : t('projects.list.updated', { at: formatWhen(project.updated_at) })}
                    {' · '}
                    {formatBytes(t, project.bytes_used)}
                  </span>
                </div>

                {tab === 'active' ? (
                  <MenuRoot>
                    <MenuTrigger asChild>
                      <Button
                        variant="ghost"
                        size="sm"
                        iconOnly
                        aria-label={t('common.action.more')}
                      >
                        <Icon name="more" size={16} />
                      </Button>
                    </MenuTrigger>
                    <MenuContent>
                      <MenuItem
                        icon={<Icon name="external" size={16} />}
                        onSelect={() => navigate(`/projects/${project.id}`)}
                      >
                        {t('common.action.open')}
                      </MenuItem>
                      <MenuItem
                        icon={<Icon name="edit" size={16} />}
                        onSelect={() => setRenaming(project)}
                      >
                        {t('projects.list.rename')}
                      </MenuItem>
                      <MenuItem
                        danger
                        icon={<Icon name="trash" size={16} />}
                        onSelect={() => trash.mutate(project.id, { onError: fail })}
                      >
                        {t('projects.list.toTrash')}
                      </MenuItem>
                    </MenuContent>
                  </MenuRoot>
                ) : (
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={() => restore.mutate(project.id, { onError: fail })}
                    loading={restore.isPending && restore.variables === project.id}
                  >
                    <Icon name="restore" size={16} />
                    {t('projects.list.restore')}
                  </Button>
                )}
              </li>
            ))}
          </ul>
          <p className="px-s4 py-s3 text-xs text-muted">
            {t('projects.list.count', {
              n: projects.data.length,
              word: plural(projects.data.length, [
                t('projects.word.one'),
                t('projects.word.few'),
                t('projects.word.many'),
              ]),
            })}
          </p>
        </Panel>
      ) : tab === 'trash' ? (
        <EmptyState
          icon="trash"
          title={t('projects.list.emptyTrash')}
          text={t('projects.list.emptyTrashHint')}
        />
      ) : (
        <EmptyState
          icon="folder"
          title={t('projects.list.empty')}
          text={t('projects.list.emptyHint')}
          action={
            <Button variant="primary" onClick={() => setCreating(true)}>
              <Icon name="plus" size={16} />
              {t('projects.list.create')}
            </Button>
          }
        />
      )}

      <CreateProjectDialog
        open={creating}
        onOpenChange={setCreating}
        workspaceId={workspace.data?.id}
        onCreated={(id) => navigate(`/projects/${id}`)}
      />
      <RenameProjectDialog project={renaming} onClose={() => setRenaming(null)} />
    </div>
  )
}

/** Скелетон списка: структура известна заранее, поэтому не спиннер. */
function ListSkeleton() {
  return (
    <Panel flush>
      <ul className="divide-y divide-line">
        {[0, 1, 2, 3].map((i) => (
          <li key={i} className="flex items-center gap-s3 px-s4 py-s4">
            <Skeleton className="h-5 w-5 rounded-sm" />
            <div className="flex min-w-0 flex-1 flex-col gap-1.5">
              <Skeleton className="w-1/3" />
              <Skeleton className="h-2.5 w-1/5" />
            </div>
          </li>
        ))}
      </ul>
    </Panel>
  )
}
