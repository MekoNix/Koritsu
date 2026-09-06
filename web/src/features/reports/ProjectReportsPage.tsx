/**
 * ProjectReportsPage — отчёты одной работы: `/reports?project=<работа>`.
 *
 * Второй шаг главной модуля (`ReportsHomePage`), а не отдельная страница:
 * выбор здесь один и делается он в два шага — сначала работа, потом отчёт в
 * ней, — и разрывать их на два адреса значило бы заставлять возвращаться назад
 * ради второго.
 *
 * **В работе несколько отчётов, и это главное про этот экран.** Титульный лист
 * по одному ГОСТу, приложение по другому, вторая глава третьим бланком — всё
 * это одна работа с общими материалами, но три разных документа. У каждого свой
 * бланк, свои значения тегов с историей и свои сборки, поэтому здесь список
 * карточек, а не одна кнопка «открыть отчёт».
 *
 * Карточка показывает первую страницу последней сборки: её кладёт сборка
 * отдельной картинкой (`ReportThumb`), и она не пропадает после перезагрузки.
 * По ней отчёт узнают в списке быстрее, чем по имени, — имена у трёх глав одной
 * работы похожи, а страницы разные.
 *
 * Работа выбирается тут же, переключателем: человек, закончивший отчёт в одной
 * работе, чаще идёт в другую работу, чем на шаг назад в общий список. В списке
 * — работы текущего пространства, как и везде.
 *
 * Удаление сносит **отчёт**: его значения, их версии и его сборки. Бланк
 * остаётся приложенным к работе, а материалы и артефакты — общие, они
 * принадлежат работе и переживают любой её документ.
 */
import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import { isApiError } from '@/api'
import { useCurrentWorkspace } from '@/api/hooks'
import { useDocumentCrumb } from '@/app/shell/breadcrumbs'
import { useT } from '@/i18n'
import {
  Button,
  Dialog,
  EmptyState,
  ErrorState,
  ForbiddenState,
  Icon,
  Input,
  Select,
  SkeletonLines,
  useToast,
} from '@/ui'
import { FileDrop } from '@/features/projects/FileDrop'
import {
  artifactUrl,
  canEditWorkspace,
  useAttachProjectTemplate,
  useProject,
  useProjectTemplates,
  useProjects,
  useWorkspace,
} from '@/features/projects/data'
import { formatWhen, runTitle } from '@/features/projects/format'
import { RunName } from '@/features/projects/RunName'
import { WorkspaceCaption } from '@/features/workspace/WorkspaceCaption'

import { ReportThumb } from './ReportThumb'
import { useCreateProjectReport, useDeleteProjectReport, useProjectReports } from './data'
import type { ProjectReport } from './types'

/** Что принимает окно выбора файла. То же, что у панели бланков работы. */
const DOCX = '.docx,.dotx,application/vnd.openxmlformats-officedocument.wordprocessingml.document'

export function ProjectReportsPage({ projectId }: { projectId: string }) {
  const t = useT()
  const toast = useToast()
  const navigate = useNavigate()

  const project = useProject(projectId)
  const workspace = useWorkspace(project.data?.workspace_id)
  const current = useCurrentWorkspace()
  const siblings = useProjects(current.data?.id)
  const reports = useProjectReports(projectId)
  const remove = useDeleteProjectReport(projectId)

  const [creating, setCreating] = useState(false)
  const [toDelete, setToDelete] = useState<ProjectReport | null>(null)

  useDocumentCrumb(project.data?.name)

  const canEdit = workspace.data ? canEditWorkspace(workspace.data.role) : false
  const имя_работы = project.data?.name ?? ''

  if (project.isError) {
    const запрет = isApiError(project.error) && project.error.status === 403
    return запрет ? (
      <ForbiddenState />
    ) : (
      <ErrorState error={project.error} onRetry={() => void project.refetch()} />
    )
  }

  const снести = () => {
    if (!toDelete) return
    remove.mutate(
      { runId: toDelete.id },
      {
        onSuccess: () => setToDelete(null),
        onError: (e) => toast.fail(e),
      },
    )
  }

  return (
    <div className="flex flex-col gap-s5">
      <header className="flex flex-wrap items-end justify-between gap-s3">
        <div className="min-w-0">
          {/* В каком пространстве лежит работа — до списка отчётов: иначе
              пропавший отчёт ищут в работе, а он в другом пространстве. */}
          <WorkspaceCaption ws={workspace.data} className="mb-1" />
          <h1 className="truncate font-display text-2xl font-semibold text-ink-strong">
            {имя_работы || t('reports.home.title')}
          </h1>
          <p className="text-sm text-muted">{t('reports.list.subtitle')}</p>
        </div>
        <div className="flex flex-wrap items-center gap-s3">
          {/* Переключатель работ, а не только кнопка «назад»: список отчётов
              одной работы — то место, откуда чаще всего идут в соседнюю
              работу. */}
          <Select
            aria-label={t('reports.list.pickProject')}
            value={projectId}
            className="w-auto min-w-[200px]"
            onChange={(e) => navigate(`/reports?project=${encodeURIComponent(e.target.value)}`)}
          >
            {(siblings.data ?? []).some((p) => p.id === projectId) ? null : (
              <option value={projectId}>{имя_работы}</option>
            )}
            {(siblings.data ?? []).map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </Select>
          <Button variant="secondary" asChild>
            <Link to="/reports">{t('reports.list.allProjects')}</Link>
          </Button>
          {canEdit && (
            <Button variant="primary" onClick={() => setCreating(true)}>
              <Icon name="plus" size={16} />
              {t('reports.list.create')}
            </Button>
          )}
        </div>
      </header>

      {reports.isPending ? (
        <div className="grid gap-s4 [grid-template-columns:repeat(auto-fill,minmax(220px,1fr))]">
          {[0, 1, 2, 3].map((i) => (
            <SkeletonLines key={i} count={6} />
          ))}
        </div>
      ) : reports.isError ? (
        <ErrorState error={reports.error} onRetry={() => void reports.refetch()} />
      ) : (reports.data ?? []).length === 0 ? (
        <EmptyState
          icon="file"
          title={t('reports.list.emptyTitle')}
          text={t('reports.list.emptyText')}
          action={
            canEdit ? (
              <Button variant="primary" onClick={() => setCreating(true)}>
                {t('reports.list.create')}
              </Button>
            ) : undefined
          }
        />
      ) : (
        <ul
          className="grid gap-s4 [grid-template-columns:repeat(auto-fill,minmax(220px,1fr))]"
          data-testid="report-cards"
        >
          {(reports.data ?? []).map((отчёт) => (
            <ReportCard
              key={отчёт.id}
              report={отчёт}
              projectId={projectId}
              projectName={имя_работы}
              canEdit={canEdit}
              onDelete={() => setToDelete(отчёт)}
            />
          ))}
        </ul>
      )}

      <CreateReportDialog
        projectId={projectId}
        open={creating}
        onOpenChange={setCreating}
        onCreated={(id) => navigate(`/reports/${projectId}/${id}`)}
      />

      <Dialog
        open={!!toDelete}
        onOpenChange={(open) => !open && setToDelete(null)}
        title={t('reports.list.deleteTitle', {
          name: toDelete
            ? runTitle(t, { module: 'reports', name: toDelete.name, n: toDelete.n }, имя_работы)
            : '',
        })}
        footer={
          <>
            <Button variant="ghost" onClick={() => setToDelete(null)}>
              {t('common.action.cancel')}
            </Button>
            <Button variant="danger" loading={remove.isPending} onClick={снести}>
              {t('reports.list.delete')}
            </Button>
          </>
        }
      >
        <p className="text-sm text-muted">{t('reports.list.deleteHint')}</p>
      </Dialog>
    </div>
  )
}

/**
 * Карточка отчёта: первая страница, имя, бланк, дата, «удалить».
 *
 * Имя правится прямо здесь (`RunName`): отчёт — это запись журнала запусков, а
 * зовут её одним и тем же именем список отчётов, журнал на карточке работы и
 * заголовок экрана отчёта. Переименовывать там, где увидел, — то же правило,
 * что у схем; уводить ради этого на другую страницу значило бы просить человека
 * найти в журнале строку, которую он в эту минуту держит перед глазами.
 *
 * Из-за этого картинка и подписи лежат в ссылке, а имя — рядом с ней: поле
 * правки и карандаш внутри ссылки открывали бы её от каждого щелчка. Само имя
 * при этом ссылкой остаётся — его рисует `RunName` по `href`.
 */
function ReportCard({
  report,
  projectId,
  projectName,
  canEdit,
  onDelete,
}: {
  report: ProjectReport
  projectId: string
  projectName: string
  canEdit: boolean
  onDelete: () => void
}) {
  const t = useT()
  const имя = runTitle(t, { module: 'reports', name: report.name, n: report.n }, projectName)
  // `inline=1` обязателен: без него служба отдаёт файл вложением, и картинка в
  // `<img>` не рисуется (`packages/api/modules/artifacts.py`).
  const превью = report.preview_artifact_id
    ? artifactUrl(projectId, report.preview_artifact_id, { inline: true })
    : undefined

  return (
    <li className="relative flex h-full flex-col overflow-hidden rounded-md border border-line bg-surface shadow-1 transition-colors hover:border-line-strong">
      <Link
        to={`/reports/${projectId}/${report.id}`}
        className="flex min-w-0 flex-col focus-visible:outline focus-visible:-outline-offset-2 focus-visible:outline-accent"
      >
        <ReportThumb seed={report.id} src={превью} alt={имя} />
      </Link>
      <div className="flex min-w-0 flex-1 flex-col gap-1 p-s3">
        <RunName
          projectId={projectId}
          runId={report.id}
          name={report.name}
          title={имя}
          canEdit={canEdit}
          href={`/reports/${projectId}/${report.id}`}
          className="font-semibold text-ink-strong"
        />
        <span className="truncate text-xs text-muted">
          {report.template_name || t('reports.list.noTemplate')}
          {' · '}
          {t('reports.templates.tags', { n: report.tags })}
        </span>
        <span className="text-xs text-muted">{formatWhen(report.created_at)}</span>
      </div>
      {canEdit && (
        <Button
          variant="ghost"
          size="sm"
          iconOnly
          className="absolute right-1 top-1 bg-surface/80"
          aria-label={t('reports.list.deleteAction', { name: имя })}
          onClick={onDelete}
        >
          <Icon name="trash" size={16} />
        </Button>
      )}
    </li>
  )
}

/**
 * Окно «Создать отчёт»: как назвать и по какому бланку собирать.
 *
 * Бланк выбирается из приложенных к работе, а не из личной полки напрямую:
 * приложенный бланк — это то, чем работа собирается, и полка остаётся
 * источником файлов, а не списком выбора. Поэтому здесь же можно приложить
 * новый файл — он попадает и в работу, и на полку, и сразу становится выбранным.
 *
 * Без бланка тоже можно: документ строится с нуля, как и работа без бланка, —
 * законное состояние, а не ошибка. Первый отчёт работы при этом остаётся на её
 * бланке и наследует всё, что в ней уже написано; кто первый, решает служба.
 */
function CreateReportDialog({
  projectId,
  open,
  onOpenChange,
  onCreated,
}: {
  projectId: string
  open: boolean
  onOpenChange: (open: boolean) => void
  onCreated: (reportId: string) => void
}) {
  const t = useT()
  const toast = useToast()

  const templates = useProjectTemplates(projectId)
  const attach = useAttachProjectTemplate()
  const create = useCreateProjectReport(projectId)

  const [name, setName] = useState('')
  const [templateId, setTemplateId] = useState('')
  const [file, setFile] = useState<File | null>(null)

  const закрыть = (open: boolean) => {
    if (!open) {
      setName('')
      setTemplateId('')
      setFile(null)
    }
    onOpenChange(open)
  }

  const приложить = async () => {
    if (!file) return
    try {
      const шаблон = await attach.mutateAsync({ projectId, file })
      setTemplateId(шаблон.id)
      setFile(null)
    } catch (e) {
      toast.fail(e)
    }
  }

  const завести = () => {
    create.mutate(
      { templateId: templateId || null, name: name.trim() },
      {
        onSuccess: (отчёт) => {
          закрыть(false)
          onCreated(отчёт.id)
        },
        onError: (e) => toast.fail(e),
      },
    )
  }

  return (
    <Dialog
      open={open}
      onOpenChange={закрыть}
      title={t('reports.list.create')}
      description={t('reports.list.createHint')}
      footer={
        <>
          <Button variant="ghost" onClick={() => закрыть(false)}>
            {t('common.action.cancel')}
          </Button>
          {/* Пока приложенный файл едет в службу, заводить отчёт нельзя: до
              ответа бланка у него нет, и отчёт получился бы пустым — с файлом,
              который человек только что выбрал, но который никуда не попал. */}
          <Button
            variant="primary"
            loading={create.isPending}
            disabled={attach.isPending}
            onClick={завести}
          >
            {t('reports.list.createAction')}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-s3">
        <Input
          label={t('reports.list.nameLabel')}
          hint={t('reports.list.nameHint')}
          value={name}
          maxLength={200}
          onChange={(e) => setName(e.target.value)}
        />
        <Select
          label={t('reports.list.templateLabel')}
          hint={t('reports.list.templateHint')}
          value={templateId}
          disabled={templates.isPending}
          onChange={(e) => setTemplateId(e.target.value)}
        >
          <option value="">{t('reports.list.noTemplateOption')}</option>
          {(templates.data ?? []).map((ш) => (
            <option key={ш.id} value={ш.id}>
              {ш.name}
            </option>
          ))}
        </Select>
        {file ? (
          <div className="flex items-center gap-s2 rounded-sm border border-line bg-surface-2 px-s3 py-s2">
            <Icon name="file" size={16} className="shrink-0 text-muted" />
            <span className="min-w-0 flex-1 truncate text-sm text-ink">{file.name}</span>
            <Button
              variant="primary"
              size="sm"
              loading={attach.isPending}
              onClick={() => void приложить()}
            >
              {t('reports.templates.attachFile')}
            </Button>
            <Button
              variant="ghost"
              size="sm"
              iconOnly
              aria-label={t('common.action.cancel')}
              onClick={() => setFile(null)}
            >
              <Icon name="close" size={16} />
            </Button>
          </div>
        ) : (
          <FileDrop
            compact
            accept={DOCX}
            label={t('reports.templates.dropLabel')}
            hint={t('reports.templates.dropHint')}
            onFiles={(files) => setFile(files[0] ?? null)}
          />
        )}
      </div>
    </Dialog>
  )
}
