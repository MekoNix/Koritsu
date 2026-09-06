/**
 * ProjectPage — одна работа: заголовок, переходы в модули, файлы.
 *
 * Крошки — «модуль / документ» (по макетам): модуль оболочка определяет
 * по адресу, а имя документа сообщает эта страница через `useDocumentCrumb`.
 * Иерархии «Проекты / … / Отчёт» нет и не заводится.
 *
 * Первым делом на странице — журнал запусков (`RunsPanel`): что в этой работе
 * делали и как оно называется. Переходы в модули стоят под ним и отвечают на
 * другой вопрос — «чем ещё эту работу можно делать»; строятся они из
 * `GET /api/modules`: служба не отдаёт неготовые вовсе, а модуль без экрана
 * работы отсеивает таблица `moduleRoutes` — ссылка в никуда считается ошибкой,
 * а «скоро» запрещено брифом.
 *
 * Отдельное состояние — проект в корзине: служба отвечает на него `409
 * in_trash`, и это не ошибка, а положение дел, из которого есть выход
 * («восстановить»). Показывать здесь общий экран ошибки значило бы отправить
 * человека искать кнопку в другом месте.
 */
import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'

import { ApiError, type ModuleInfo } from '@/api'
import { useModules } from '@/api/hooks'
import { useDocumentCrumb } from '@/app/shell/breadcrumbs'
import { useT } from '@/i18n'
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

import { OtherWorkspaceNotice, WorkspaceCaption } from '@/features/workspace/WorkspaceCaption'

import { ExportDialog } from './ExportDialog'
import { MaterialsPanel } from './MaterialsPanel'
import { Panel } from './Panel'
import { RenameProjectDialog } from './RenameProjectDialog'
import { RunsPanel } from './RunsPanel'
import {
  canEditWorkspace,
  useProject,
  useRestoreProject,
  useTrashProject,
  useWorkspace,
} from './data'
import { formatBytes, formatWhen } from './format'
import { projectModuleLink, type ProjectModuleLink } from './moduleRoutes'

export function ProjectPage() {
  const { projectId = '' } = useParams()
  const t = useT()
  const toast = useToast()
  const navigate = useNavigate()
  const [renaming, setRenaming] = useState(false)
  const [exporting, setExporting] = useState(false)

  const project = useProject(projectId)
  const workspace = useWorkspace(project.data?.workspace_id)
  const modules = useModules()
  const trash = useTrashProject()
  const restore = useRestoreProject()

  useDocumentCrumb(project.data?.name)

  const error = project.error
  const inTrash = error instanceof ApiError && error.code === 'in_trash'
  const forbidden = error instanceof ApiError && error.status === 403
  const missing = error instanceof ApiError && error.status === 404
  const canEdit = canEditWorkspace(workspace.data?.role)

  if (project.isPending) return <ProjectSkeleton />

  if (inTrash) {
    return (
      <EmptyState
        icon="trash"
        title={t('projects.page.inTrash')}
        text={t('projects.page.inTrashHint')}
        action={
          <Button
            variant="primary"
            loading={restore.isPending}
            onClick={() =>
              restore.mutate(projectId, {
                onSuccess: () => void project.refetch(),
                onError: (e) => toast.fail(e),
              })
            }
          >
            <Icon name="restore" size={16} />
            {t('projects.list.restore')}
          </Button>
        }
      />
    )
  }
  if (forbidden) {
    return (
      <ForbiddenState
        action={
          <Button variant="secondary" asChild>
            <Link to="/projects">{t('projects.page.toList')}</Link>
          </Button>
        }
      />
    )
  }
  if (missing) {
    return (
      <EmptyState
        icon="folder"
        title={t('projects.page.missing')}
        text={t('projects.page.missingHint')}
        action={
          <Button variant="secondary" asChild>
            <Link to="/projects">{t('projects.page.toList')}</Link>
          </Button>
        }
      />
    )
  }
  if (error || !project.data) {
    return (
      <ErrorState
        error={error}
        onRetry={() => void project.refetch()}
        action={
          <Button variant="ghost" asChild>
            <Link to="/projects">{t('projects.page.toList')}</Link>
          </Button>
        }
      />
    )
  }

  const карточка = project.data
  // Модуль показывается, только если у него есть и строка в ответе службы, и
  // экран работы на сайте. Одного из двух мало: первое — «готов ли модуль»,
  // второе — «есть ли куда вести».
  const links: { module: ModuleInfo; link: ProjectModuleLink }[] = []
  for (const module of modules.data ?? []) {
    const link = projectModuleLink(module.id)
    if (link) links.push({ module, link })
  }

  return (
    <div className="flex flex-col gap-s4">
      {/* Работа открывается и по ссылке, а ссылка не обязана вести в то
          пространство, в котором человек сейчас работает. */}
      <OtherWorkspaceNotice ws={workspace.data} />

      <header className="flex flex-wrap items-start justify-between gap-s3">
        <div className="min-w-0">
          <WorkspaceCaption ws={workspace.data} className="mb-1" />
          <h1 className="break-words font-display text-xl font-bold tracking-tight text-ink-strong">
            {карточка.name}
          </h1>
          <p className="text-sm text-muted">
            {t('projects.page.updated', { at: formatWhen(карточка.updated_at) })}
            {' · '}
            {formatBytes(t, карточка.bytes_used)}
            {карточка.keys && карточка.keys.length > 0
              ? ` · ${t('projects.page.tags', { n: карточка.keys.length })}`
              : ''}
          </p>
        </div>

        <div className="flex items-center gap-s2">
          {/* Выгрузка — кнопка в проекте, а не пункт
              меню: её ищут глазами, а не через «Ещё». Читателю она не
              показана: архив ложится на том в квоту владельца, и служба
              требует за это роль `editor` (`export/routes.py`). */}
          {canEdit && (
            <Button variant="secondary" onClick={() => setExporting(true)}>
              <Icon name="download" size={16} />
              {t('projects.export.action')}
            </Button>
          )}
          {canEdit && (
            <MenuRoot>
              <MenuTrigger asChild>
                <Button variant="secondary">
                  <Icon name="more" size={16} />
                  {t('common.action.more')}
                </Button>
              </MenuTrigger>
              <MenuContent>
                <MenuItem icon={<Icon name="edit" size={16} />} onSelect={() => setRenaming(true)}>
                  {t('projects.list.rename')}
                </MenuItem>
                <MenuItem
                  danger
                  icon={<Icon name="trash" size={16} />}
                  onSelect={() =>
                    trash.mutate(projectId, {
                      onSuccess: () => navigate('/projects'),
                      onError: (e) => toast.fail(e),
                    })
                  }
                >
                  {t('projects.list.toTrash')}
                </MenuItem>
              </MenuContent>
            </MenuRoot>
          )}
        </div>
      </header>

      <RunsPanel projectId={карточка.id} projectName={карточка.name} canEdit={canEdit} />

      <Panel title={t('projects.page.modules')} note={t('projects.page.modulesNote')}>
        {modules.isPending ? (
          <div className="grid gap-s3 sm:grid-cols-2 lg:grid-cols-3">
            {[0, 1, 2].map((i) => (
              <Skeleton key={i} className="h-16 rounded-md" />
            ))}
          </div>
        ) : links.length === 0 ? (
          <EmptyState compact title={t('projects.page.noModules')} />
        ) : (
          <ul className="grid gap-s3 sm:grid-cols-2 lg:grid-cols-3">
            {links.map(({ module, link }) => (
              <li key={module.id}>
                <Link
                  to={link.href(карточка.id)}
                  className="flex items-center gap-s3 rounded-md border border-line bg-surface-2 px-s3 py-s3 transition-colors hover:border-line-strong hover:bg-surface-3"
                >
                  <Icon
                    name={link.icon}
                    size={22}
                    style={{ color: `var(${link.colorVar})` }}
                    className="shrink-0"
                  />
                  <span className="min-w-0">
                    <span className="block truncate text-sm font-semibold text-ink-strong">
                      {t(`shell.nav.${module.id}`)}
                    </span>
                    <span className="block truncate text-xs text-muted">
                      {t(`projects.page.moduleHint.${module.id}`)}
                    </span>
                  </span>
                  <Icon name="chevronRight" size={16} className="ml-auto shrink-0 text-muted" />
                </Link>
              </li>
            ))}
          </ul>
        )}
      </Panel>

      <MaterialsPanel projectId={карточка.id} canEdit={canEdit} />

      <RenameProjectDialog
        project={renaming ? карточка : null}
        onClose={() => setRenaming(false)}
      />

      {/* Шаблон опознаётся по тегам: карточка проекта отдаёт их ключи, и
          проект без единого ключа — это проект без шаблона, собирать Word из
          которого нечего (то же правило у экрана отчёта). */}
      <ExportDialog
        projectId={карточка.id}
        open={exporting}
        onOpenChange={setExporting}
        hasTemplate={(карточка.keys?.length ?? 0) > 0}
      />
    </div>
  )
}

function ProjectSkeleton() {
  return (
    <div className="flex flex-col gap-s4">
      <Skeleton className="h-7 w-1/3" />
      <Skeleton className="h-3 w-1/5" />
      <Skeleton className="h-28 rounded-md" />
      <Skeleton className="h-64 rounded-md" />
    </div>
  )
}
