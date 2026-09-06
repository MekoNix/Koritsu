/**
 * ReportsHomePage — главная модуля: `/reports`.
 *
 * **Здесь сразу лежат отчёты, а не выбор работы.** Человек приходит сюда за
 * тем, что он писал, и работа для него — не отдельная вещь, которую надо
 * сначала выбрать, а подпись под отчётом. Поэтому список один: все отчёты всех
 * работ текущего пространства карточками, новые сверху. Шаг «сначала выберите
 * работу» отсюда убран — он стоял между человеком и его документом на каждом
 * входе, а в пространстве с одной работой не спрашивал ни о чём.
 *
 * Лента приезжает одним запросом (`GET /api/reports?workspace_id=`), а не
 * списком работ плюс запросом на каждую: время ответа не должно расти вместе с
 * числом работ.
 *
 * **Работа — отбор, а не шаг.** `/reports?project=<работа>` показывает ту же
 * ленту, суженную до одной работы: так сюда ведут ссылки с экрана отчёта и
 * старые закладки, и так же переключается выпадающий список «Все работы» над
 * сеткой. Второй страницы под это не заводится — список один и тот же,
 * отличается он отбором.
 *
 * Карточка показывает первую страницу последней сборки: её кладёт сборка
 * отдельной картинкой (`ReportThumb`), и она не пропадает после перезагрузки.
 * По ней отчёт узнают быстрее, чем по имени, — имена у трёх глав одной работы
 * похожи, а страницы разные. Имя правится прямо здесь (`RunName`): отчёт — это
 * запись журнала запусков, и зовут её одним именем список отчётов, журнал на
 * карточке работы и заголовок экрана отчёта.
 *
 * Имени пространства у карточки нет, хотя оно есть у карточки работы: лента
 * отобрана по текущему пространству целиком, и повторять его на каждой из
 * двадцати карточек значило бы двадцать раз ответить на вопрос, заданный один
 * раз подписью над списком.
 *
 * Удаление сносит **отчёт**: его значения, их версии и его сборки. Бланк
 * остаётся приложенным к работе, а материалы и артефакты — общие, они
 * принадлежат работе и переживают любой её документ.
 */
import { useMemo, useState, type ReactNode } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'

import { useCurrentWorkspace } from '@/api/hooks'
import { useDocumentCrumb } from '@/app/shell/breadcrumbs'
import { useT } from '@/i18n'
import {
  Button,
  Dialog,
  EmptyState,
  ErrorState,
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
  useProjectTemplates,
  useProjects,
} from '@/features/projects/data'
import { formatWhen, runTitle } from '@/features/projects/format'
import { RunName } from '@/features/projects/RunName'
import { WorkspaceCaption } from '@/features/workspace/WorkspaceCaption'

import { ReportThumb } from './ReportThumb'
import { useCreateProjectReport, useDeleteProjectReport, useWorkspaceReports } from './data'
import type { WorkspaceReport } from './types'

/** Что принимает окно выбора файла. То же, что у панели бланков работы. */
const DOCX = '.docx,.dotx,application/vnd.openxmlformats-officedocument.wordprocessingml.document'

export function ReportsHomePage() {
  const t = useT()
  const toast = useToast()
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()

  const workspace = useCurrentWorkspace()
  const reports = useWorkspaceReports(workspace.data?.id)
  const projects = useProjects(workspace.data?.id)
  const remove = useDeleteProjectReport()

  // Отбор по работе живёт в адресе, а не в состоянии экрана: по этому адресу
  // сюда приходят с экрана отчёта и из старых закладок, и отбор, спрятанный в
  // память страницы, потерялся бы при первой же перезагрузке.
  const работа = (params.get('project') ?? '').trim()
  const [query, setQuery] = useState('')
  const [creating, setCreating] = useState(false)
  const [toDelete, setToDelete] = useState<WorkspaceReport | null>(null)

  const canEdit = canEditWorkspace(workspace.data?.role)
  const имя_работы = (projects.data ?? []).find((p) => p.id === работа)?.name ?? ''
  useDocumentCrumb(имя_работы || undefined)

  const найденные = useMemo(() => {
    const запрос = query.trim().toLowerCase()
    return (reports.data ?? []).filter((отчёт) => {
      if (работа && отчёт.project_id !== работа) return false
      if (!запрос) return true
      const имя = runTitle(t, { module: 'reports', ...отчёт }, отчёт.project_name)
      // Поиск идёт и по работе: человек чаще помнит, в какой работе писал
      // главу, чем как он её назвал.
      return имя.toLowerCase().includes(запрос) || отчёт.project_name.toLowerCase().includes(запрос)
    })
  }, [reports.data, работа, query, t])

  const отобрать = (id: string) => {
    const новые = new URLSearchParams(params)
    if (id) новые.set('project', id)
    else новые.delete('project')
    setParams(новые)
  }

  const снести = () => {
    if (!toDelete) return
    remove.mutate(
      { projectId: toDelete.project_id, runId: toDelete.id },
      { onSuccess: () => setToDelete(null), onError: (e) => toast.fail(e) },
    )
  }

  const кнопка_создания =
    canEdit && (projects.data ?? []).length > 0 ? (
      <Button variant="primary" onClick={() => setCreating(true)}>
        <Icon name="plus" size={16} />
        {t('reports.list.create')}
      </Button>
    ) : null

  return (
    <div className="flex flex-col gap-s5">
      <header className="flex flex-wrap items-end justify-between gap-s3">
        <div className="min-w-0">
          {/* Отчёты показаны по текущему пространству — подпись говорит, по
              какому именно: иначе пропавший отчёт ищут в работе, а он в
              соседнем пространстве. */}
          <WorkspaceCaption ws={workspace.data} className="mb-1" />
          <h1 className="font-display text-2xl font-semibold text-ink-strong">
            {t('reports.home.title')}
          </h1>
          <p className="max-w-[60ch] text-sm text-muted">{t('reports.home.subtitle')}</p>
        </div>
        <div className="flex flex-wrap items-center gap-s3">
          <Button variant="secondary" asChild>
            <Link to="/projects">{t('reports.home.toProjects')}</Link>
          </Button>
          {кнопка_создания}
        </div>
      </header>

      <div className="flex flex-wrap items-center gap-s3">
        <Input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={t('reports.home.search')}
          aria-label={t('reports.home.search')}
          className="max-w-[420px] flex-1"
        />
        {/* Отбор по работе, а не обязательный выбор: пустое значение — «все
            работы», и с него страница открывается. */}
        <Select
          aria-label={t('reports.home.filterProject')}
          value={работа}
          className="w-auto min-w-[200px]"
          onChange={(e) => отобрать(e.target.value)}
        >
          <option value="">{t('reports.list.allProjects')}</option>
          {/* Работа из адреса, которой нет в списке пространства (закладка на
              чужую или удалённую), названа отдельной строкой: иначе выпадающий
              список молча показывал бы «Все работы» при непустом отборе. */}
          {работа && !(projects.data ?? []).some((p) => p.id === работа) ? (
            <option value={работа}>{имя_работы || работа}</option>
          ) : null}
          {(projects.data ?? []).map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </Select>
      </div>

      {reports.isPending || projects.isPending ? (
        <div className="grid gap-s4 [grid-template-columns:repeat(auto-fill,minmax(220px,1fr))]">
          {[0, 1, 2, 3].map((i) => (
            <SkeletonLines key={i} count={6} />
          ))}
        </div>
      ) : reports.isError ? (
        <ErrorState error={reports.error} onRetry={() => void reports.refetch()} />
      ) : найденные.length === 0 ? (
        <EmptyReports
          работ={(projects.data ?? []).length}
          отчётов={(reports.data ?? []).length}
          отбор={!!работа || !!query.trim()}
          создать={кнопка_создания}
        />
      ) : (
        <ul
          className="grid gap-s4 [grid-template-columns:repeat(auto-fill,minmax(220px,1fr))]"
          data-testid="report-cards"
        >
          {найденные.map((отчёт) => (
            <ReportCard
              key={отчёт.id}
              report={отчёт}
              canEdit={canEdit}
              onDelete={() => setToDelete(отчёт)}
            />
          ))}
        </ul>
      )}

      <CreateReportDialog
        open={creating}
        onOpenChange={setCreating}
        projects={projects.data ?? []}
        preferred={работа || последняя_работа(reports.data)}
        onCreated={(projectId, reportId) => navigate(`/reports/${projectId}/${reportId}`)}
      />

      <Dialog
        open={!!toDelete}
        onOpenChange={(open) => !open && setToDelete(null)}
        title={t('reports.list.deleteTitle', {
          name: toDelete
            ? runTitle(t, { module: 'reports', ...toDelete }, toDelete.project_name)
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
 * Какую работу предложить в окне создания, когда её не назвал отбор.
 *
 * Работа самого свежего отчёта: лента отсортирована новыми вверх, и это та
 * работа, в которой человек писал последней. В пространстве с одной работой она
 * же и единственная, поэтому отдельного правила «если работа одна» не нужно.
 */
function последняя_работа(лента: WorkspaceReport[] | undefined): string {
  return лента?.[0]?.project_id ?? ''
}

/**
 * Пустое состояние, а их здесь три, и ведут они в разные места.
 *
 * Работ нет вовсе — чинить нечего, пока нет работы: отчёт живёт в ней. Отчётов
 * нет — предложить завести первый. Ничего не нашлось по отбору — сказать
 * именно это, а не «отчётов пока нет»: второе прочиталось бы как «всё пропало».
 */
function EmptyReports({
  работ,
  отчётов,
  отбор,
  создать,
}: {
  работ: number
  отчётов: number
  отбор: boolean
  создать: ReactNode
}) {
  const t = useT()
  if (работ === 0) {
    return (
      <EmptyState
        icon="folder"
        title={t('reports.home.emptyTitle')}
        text={t('reports.home.emptyText')}
        action={
          <Button variant="primary" asChild>
            <Link to="/projects">{t('reports.home.create')}</Link>
          </Button>
        }
      />
    )
  }
  if (отчётов > 0 && отбор) {
    return <EmptyState icon="file" title={t('reports.home.nothingFound')} />
  }
  return (
    <EmptyState
      icon="file"
      title={t('reports.list.emptyTitle')}
      text={t('reports.list.emptyText')}
      action={создать ?? undefined}
    />
  )
}

/**
 * Карточка отчёта: первая страница, имя, работа, бланк, дата, «удалить».
 *
 * Имя правится прямо здесь (`RunName`), поэтому картинка и подписи лежат в
 * ссылке, а имя — рядом с ней: поле правки и карандаш внутри ссылки открывали
 * бы её от каждого щелчка. Само имя при этом ссылкой остаётся — его рисует
 * `RunName` по `href`.
 *
 * Работа названа ссылкой на саму работу, а не на отбор ленты: с карточки
 * отчёта уходят к материалам и журналу работы, а сузить ленту до одной работы
 * можно выпадающим списком, не уходя со страницы.
 */
function ReportCard({
  report,
  canEdit,
  onDelete,
}: {
  report: WorkspaceReport
  canEdit: boolean
  onDelete: () => void
}) {
  const t = useT()
  const projectId = report.project_id
  const имя = runTitle(t, { module: 'reports', ...report }, report.project_name)
  const адрес = `/reports/${projectId}/${report.id}`
  // `inline=1` обязателен: без него служба отдаёт файл вложением, и картинка в
  // `<img>` не рисуется (`packages/api/modules/artifacts.py`).
  const превью = report.preview_artifact_id
    ? artifactUrl(projectId, report.preview_artifact_id, { inline: true })
    : undefined

  return (
    <li className="relative flex h-full flex-col overflow-hidden rounded-md border border-line bg-surface shadow-1 transition-colors hover:border-line-strong">
      <Link
        to={адрес}
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
          href={адрес}
          className="font-semibold text-ink-strong"
        />
        <Link
          to={`/projects/${projectId}`}
          className="flex min-w-0 items-center gap-1 text-xs text-muted hover:text-ink"
        >
          <Icon name="folder" size={12} className="shrink-0" />
          <span className="truncate">{report.project_name}</span>
        </Link>
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
 * Окно «Создать отчёт»: в какой работе, как назвать и по какому бланку собирать.
 *
 * Работа выбирается здесь же, а не заранее на странице: список общий на всё
 * пространство, и требовать выбрать работу до нажатия значило бы вернуть тот
 * самый шаг, который с главной убран. Предлагается та, в которой человек писал
 * последней (или та, по которой отобрана лента), — переспрашивать в
 * пространстве с одной работой не о чем.
 *
 * Бланк выбирается из приложенных к выбранной работе, а не из личной полки
 * напрямую: приложенный бланк — это то, чем работа собирается, и полка остаётся
 * источником файлов, а не списком выбора. Поэтому здесь же можно приложить
 * новый файл — он попадает и в работу, и на полку, и сразу становится
 * выбранным.
 *
 * Без бланка тоже можно: документ строится с нуля, как и работа без бланка, —
 * законное состояние, а не ошибка. Первый отчёт работы при этом остаётся на её
 * бланке и наследует всё, что в ней уже написано; кто первый, решает служба.
 */
function CreateReportDialog({
  open,
  onOpenChange,
  projects,
  preferred,
  onCreated,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  projects: { id: string; name: string }[]
  preferred: string
  onCreated: (projectId: string, reportId: string) => void
}) {
  const t = useT()
  const toast = useToast()

  const attach = useAttachProjectTemplate()
  const create = useCreateProjectReport()

  const [projectId, setProjectId] = useState('')
  const [name, setName] = useState('')
  const [templateId, setTemplateId] = useState('')
  const [file, setFile] = useState<File | null>(null)

  // Выбранная работа: своя, пока человек её не сменил, — а до того та, что
  // предложила страница. Списывать предложенную в состояние при открытии окна
  // значило бы терять её всякий раз, когда лента приезжает позже окна.
  const выбрана = projects.some((p) => p.id === projectId)
    ? projectId
    : preferred || projects[0]?.id || ''
  // Бланки спрашиваются только при открытом окне: само окно стоит на странице
  // всегда, открыто оно или нет, и без этого условия запрос за бланками уходил
  // бы при каждом входе в список — ради выбора, которого никто не открывал.
  const templates = useProjectTemplates(open ? выбрана || undefined : undefined)

  const закрыть = (open: boolean) => {
    if (!open) {
      setProjectId('')
      setName('')
      setTemplateId('')
      setFile(null)
    }
    onOpenChange(open)
  }

  const сменить_работу = (id: string) => {
    setProjectId(id)
    // Бланк принадлежит работе: оставленный от прежней он был бы чужим, и
    // служба отказала бы уже после нажатия «Создать».
    setTemplateId('')
    setFile(null)
  }

  const приложить = async () => {
    if (!file || !выбрана) return
    try {
      const шаблон = await attach.mutateAsync({ projectId: выбрана, file })
      setTemplateId(шаблон.id)
      setFile(null)
    } catch (e) {
      toast.fail(e)
    }
  }

  const завести = () => {
    if (!выбрана) return
    create.mutate(
      { projectId: выбрана, templateId: templateId || null, name: name.trim() },
      {
        onSuccess: (отчёт) => {
          закрыть(false)
          onCreated(выбрана, отчёт.id)
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
            disabled={attach.isPending || !выбрана}
            onClick={завести}
          >
            {t('reports.list.createAction')}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-s3">
        <Select
          label={t('reports.list.projectLabel')}
          hint={t('reports.list.projectHint')}
          value={выбрана}
          onChange={(e) => сменить_работу(e.target.value)}
        >
          {projects.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </Select>
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
