/**
 * ReportWorkPage — экран работы над отчётом: `/reports/:projectId`.
 *
 *     Композиция A («классика») из макета `05-reports.html`
 *     ---------------------------------------------------
 *
 * Три колонки: теги (280px) — заполнение (остаток) — превью PDF (44%).
 * В макете их четыре варианта, и выбран первый, потому что он единственный, где
 * все три вопроса видны одновременно: «что ещё не сделано», «что я пишу сейчас»
 * и «как это будет выглядеть». B прячет список тегов в полоску статусов — по
 * ней нельзя выбрать тег, не наведя курсор; C убирает превью в боковой лист —
 * и человек перестаёт видеть последствия правки; D («правка прямо в PDF»)
 * требует своего просмотрщика PDF с картой «блок → тег», которого у нас нет, и
 * сам макет помечает его гипотезой. Прогресс стоит над списком тегов, а не в
 * шапке страницы: он про список.
 *
 * Обязательные состояния все здесь: скелетон (пока едут теги), пусто (проект
 * без шаблона — тегов нет вовсе), ошибка (с повтором), запрет (роль `viewer` —
 * читать можно, писать нет).
 */
import { useEffect, useMemo, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'

import { isApiError } from '@/api'
import { useUsage } from '@/api/hooks'
import { useDocumentCrumb } from '@/app/shell/breadcrumbs'
import { useT } from '@/i18n'
import { Button, Dialog, EmptyState, ErrorState, ForbiddenState, Icon, SkeletonLines } from '@/ui'
import { ExportDialog } from '@/features/projects/ExportDialog'
import { MaterialsPanel } from '@/features/projects/MaterialsPanel'
import { canEditWorkspace, useMaterials, useProject, useWorkspace } from '@/features/projects/data'

import { PdfPreview } from './PdfPreview'
import { TagEditor } from './TagEditor'
import { TagList } from './TagList'
import { useDefaultEndpoint, useProjectTags, useProjectValues, useProviders } from './data'
import { ModelPicker, PriceHint } from './runControls'
import { emptyKeys, filterTags, type TagFilter } from './tags'
import { BUILD, FILL_REPORT, FILL_TAG } from './types'
import { useBuild } from './useBuild'
import { useFill } from './useFill'

/**
 * Высота рабочей области. Считается от окна, а не берётся `h-full`: три колонки
 * со своей прокруткой обязаны иметь определённую высоту, иначе прокручивается
 * страница целиком и шапка с прогрессом уезжает вверх.
 */
const ВЫСОТА = { height: 'calc(100vh - var(--topbar-h) - 2 * var(--space-5) - 56px)' }

export function ReportWorkPage() {
  const t = useT()
  const { projectId = '' } = useParams()
  const [params] = useSearchParams()

  const project = useProject(projectId)
  const workspace = useWorkspace(project.data?.workspace_id)
  const tags = useProjectTags(projectId)
  const values = useProjectValues(projectId)
  const materials = useMaterials(projectId)
  const providers = useProviders()
  const usage = useUsage()

  const [endpoint, setEndpoint] = useState<string | null>(null)
  const [selected, setSelected] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState<TagFilter>('all')
  const [askAll, setAskAll] = useState(false)
  const [filesOpen, setFilesOpen] = useState(false)
  const [exporting, setExporting] = useState(false)

  const fill = useFill(projectId, endpoint)
  const build = useBuild(projectId)

  useDocumentCrumb(project.data?.name)

  // Пресет по умолчанию — выбранный человеком в настройках, а если он там
  // ничего не выбрал, первый, которым есть чем платить (свой ключ вперёд
  // общего). Ставится один раз: дальше выбор человека, а не наш.
  const по_умолчанию = useDefaultEndpoint()
  useEffect(() => {
    if (endpoint === null && по_умолчанию) setEndpoint(по_умолчанию)
  }, [по_умолчанию, endpoint])

  /**
   * Какой тег открыт при входе.
   *
   * `?tag=<ключ>` — ссылка из панели агента: она приводит человека к тегу,
   * который агент только что переписал, и открыть вместо него первый по списку
   * значило бы отправить его искать правку глазами. Ключа нет или он чужой —
   * первый тег: экран без выбранного тега это пустая середина при полном
   * списке слева, то есть лишний клик на каждом входе.
   *
   * Адрес при дальнейшем выборе не переписывается: `?tag=` — это «куда
   * привели», а не «что открыто сейчас».
   */
  useEffect(() => {
    if (selected !== null) return
    const список = tags.data
    const первый = список?.[0]
    if (!список || !первый) return
    const изАдреса = список.find((x) => x.key === params.get('tag'))
    setSelected((изАдреса ?? первый).key)
  }, [tags.data, selected, params])

  const показанные = useMemo(() => filterTags(tags.data, query, filter), [tags.data, query, filter])
  const выбранный = tags.data?.find((x) => x.key === selected)
  const пустые = emptyKeys(tags.data)
  const canEdit = workspace.data ? canEditWorkspace(workspace.data.role) : true
  const canGenerate = !!endpoint && !fill.running

  if (project.isError) {
    const запрет = isApiError(project.error) && project.error.status === 403
    return запрет ? (
      <ForbiddenState />
    ) : (
      <ErrorState error={project.error} onRetry={() => project.refetch()} />
    )
  }

  if (project.isPending || tags.isPending) {
    return (
      <div className="flex flex-col gap-s4">
        <SkeletonLines count={2} className="max-w-[320px]" />
        <div className="grid gap-s3 [grid-template-columns:280px_1fr_44%]">
          <SkeletonLines count={10} />
          <SkeletonLines count={8} />
          <SkeletonLines count={6} />
        </div>
      </div>
    )
  }

  if (tags.isError) {
    return <ErrorState error={tags.error} onRetry={() => tags.refetch()} />
  }

  if ((tags.data?.length ?? 0) === 0) {
    // Проект без шаблона: тегов нет и взяться им неоткуда. Не ошибка — законный
    // случай (документ строится с нуля), но работать с ним в отчётах нечем.
    return (
      <EmptyState
        icon="file"
        title={t('reports.work.noTemplateTitle')}
        text={t('reports.work.noTemplateText')}
        action={
          <Button variant="primary" asChild>
            <Link to={`/projects/${projectId}`}>{t('reports.work.toProject')}</Link>
          </Button>
        }
      />
    )
  }

  return (
    <div className="flex flex-col gap-s3" style={ВЫСОТА}>
      <header className="flex flex-wrap items-center gap-s3">
        <Button variant="ghost" size="sm" iconOnly aria-label={t('reports.work.back')} asChild>
          <Link to="/reports">
            <Icon name="arrowLeft" size={16} />
          </Link>
        </Button>
        <div className="min-w-0">
          <h1 className="truncate font-display text-lg font-semibold text-ink-strong">
            {project.data?.name}
          </h1>
          <p className="text-xs text-muted">
            {t('reports.work.subtitle', { total: tags.data?.length ?? 0, empty: пустые.length })}
            {!canEdit && ` · ${t('reports.work.readOnly')}`}
          </p>
        </div>
        <div className="ml-auto flex flex-wrap items-center gap-s3">
          <ModelPicker
            providers={providers.data}
            value={endpoint}
            onChange={setEndpoint}
            disabled={fill.running}
          />
          <Button
            variant="agent"
            disabled={!canEdit || fill.running || пустые.length === 0 || !endpoint}
            onClick={() => setAskAll(true)}
          >
            <Icon name="agent" size={16} />
            {t('reports.work.fillAll')}
          </Button>
          {/* Та же выгрузка, что на странице работы, тем же окном: человек,
              дописавший отчёт, забирает файл здесь, не возвращаясь в проект. */}
          <Button variant="secondary" disabled={!canEdit} onClick={() => setExporting(true)}>
            <Icon name="download" size={16} />
            {t('projects.export.action')}
          </Button>
        </div>
      </header>

      {fill.running && fill.kind === FILL_REPORT && (
        <p className="rounded-md border border-line bg-agent-bg px-s3 py-s2 text-xs text-agent">
          {t('reports.work.fillingAll', { done: fill.closed, total: fill.total })}
          {fill.current ? ` · {{${fill.current}}}` : ''}
        </p>
      )}

      <div className="grid min-h-0 flex-1 overflow-hidden rounded-md border border-line bg-surface [grid-template-columns:280px_1fr_44%]">
        <section className="min-h-0 border-r border-line">
          <TagList
            tags={tags.data}
            shown={показанные}
            loading={tags.isPending}
            selected={selected}
            onSelect={setSelected}
            query={query}
            onQuery={setQuery}
            filter={filter}
            onFilter={setFilter}
            busy={fill.busy}
            current={fill.current}
            footer={
              <Button variant="secondary" size="sm" onClick={() => setFilesOpen(true)}>
                <Icon name="folder" size={14} />
                {t('reports.work.files', { n: materials.data?.length ?? 0 })}
              </Button>
            }
          />
        </section>

        <section className="min-h-0 border-r border-line">
          <TagEditor
            projectId={projectId}
            tag={выбранный}
            value={selected ? values.data?.[selected] : undefined}
            streamed={selected ? fill.textFor(selected) : undefined}
            busy={!!selected && fill.busy.has(selected)}
            canEdit={canEdit}
            canGenerate={canGenerate}
            onGenerate={(key) => fill.fillTag(key)}
            priceHint={<PriceHint kind={FILL_TAG} usage={usage.data} />}
          />
        </section>

        <section className="min-h-0">
          <PdfPreview
            build={build}
            canBuild={canEdit}
            priceHint={<PriceHint kind={BUILD} usage={usage.data} />}
          />
        </section>
      </div>

      <Dialog
        open={askAll}
        onOpenChange={setAskAll}
        title={t('reports.fillAll.title')}
        description={t('reports.fillAll.description', { n: пустые.length })}
        footer={
          <>
            <Button variant="ghost" onClick={() => setAskAll(false)}>
              {t('common.action.cancel')}
            </Button>
            <Button
              variant="agent"
              onClick={() => {
                setAskAll(false)
                fill.fillReport(пустые)
              }}
            >
              {t('reports.fillAll.start')}
            </Button>
          </>
        }
      >
        <div className="flex flex-col gap-s3 text-sm">
          <p className="text-muted">{t('reports.fillAll.keepsManual')}</p>
          <ul className="flex flex-wrap gap-1">
            {пустые.map((key) => (
              <li
                key={key}
                className="rounded-sm border border-line-strong px-1.5 py-0.5 font-mono text-xs"
              >
                {`{{${key}}}`}
              </li>
            ))}
          </ul>
          <p className="text-xs text-muted">
            <PriceHint kind={FILL_REPORT} usage={usage.data} />
          </p>
        </div>
      </Dialog>

      {/* Шаблон здесь заведомо есть: экран без тегов до этого места не доходит. */}
      <ExportDialog
        projectId={projectId}
        open={exporting}
        onOpenChange={setExporting}
        hasTemplate
      />

      <Dialog
        open={filesOpen}
        onOpenChange={setFilesOpen}
        title={t('reports.work.filesTitle')}
        description={t('reports.work.filesHint')}
        size="lg"
      >
        <MaterialsPanel projectId={projectId} canEdit={canEdit} />
      </Dialog>
    </div>
  )
}
