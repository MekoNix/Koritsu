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
 *
 * **Экран во всю ширину окна** (`useWidePage`), а не в колонке текста, как
 * остальное приложение. Колонок здесь три, и самая узкая из них — превью
 * страницы: полтора сантиметра пустоты по краям забирались бы у неё, то есть
 * у вёрстки, ради которой превью и смотрят.
 *
 * **Бланки работы живут здесь же.** Шаблон выбирают там, где им пользуются, а
 * не в профиле; личная полка остаётся источником файлов. Отчёт при этом
 * заводится из работы (запись журнала `module: reports`), а не наоборот.
 */
import { useEffect, useMemo, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'

import { isApiError } from '@/api'
import { useDocumentCrumb } from '@/app/shell/breadcrumbs'
import { useWidePage } from '@/app/shell/widePage'
import { useT } from '@/i18n'
import {
  Button,
  Dialog,
  EmptyState,
  ErrorState,
  ForbiddenState,
  Icon,
  SkeletonLines,
  Textarea,
} from '@/ui'
import { ExportDialog } from '@/features/projects/ExportDialog'
import { MaterialsPanel } from '@/features/projects/MaterialsPanel'
import { canEditWorkspace, useMaterials, useProject, useWorkspace } from '@/features/projects/data'

import { PdfPreview } from './PdfPreview'
import { TagEditor } from './TagEditor'
import { TagList } from './TagList'
import { TemplatesPanel } from './TemplatesPanel'
import { useDefaultEndpoint, useProjectTags, useProjectValues, useProviders } from './data'
import { ModelPicker } from './runControls'
import { emptyKeys, filterTags, type TagFilter } from './tags'
import { FILL_REPORT } from './types'
import { useBuild } from './useBuild'
import { useFill } from './useFill'

/**
 * Высота рабочей области. Считается от окна, а не берётся `h-full`: три колонки
 * со своей прокруткой обязаны иметь определённую высоту, иначе прокручивается
 * страница целиком и шапка с прогрессом уезжает вверх.
 */
const ВЫСОТА = { height: 'calc(100vh - var(--topbar-h) - 2 * var(--space-3) - 52px)' }

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

  const [endpoint, setEndpoint] = useState<string | null>(null)
  const [selected, setSelected] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState<TagFilter>('all')
  const [askAll, setAskAll] = useState(false)
  const [filesOpen, setFilesOpen] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [templatesOpen, setTemplatesOpen] = useState(false)
  // Общая подсказка на весь прогон. Живёт в экране, а не в манифесте: она
  // про сегодняшний запуск («сухо, без оценок»), а манифест описывает бланк и
  // переживает работу. Задание отдельного тега — другое поле, в его карточке.
  const [runPrompt, setRunPrompt] = useState('')

  const fill = useFill(projectId, endpoint)
  const build = useBuild(projectId)

  useDocumentCrumb(project.data?.name)
  useWidePage()

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
    const список = tags.data?.tags
    const первый = список?.[0]
    if (!список || !первый) return
    const изАдреса = список.find((x) => x.key === params.get('tag'))
    setSelected((изАдреса ?? первый).key)
  }, [tags.data, selected, params])

  const список = tags.data?.tags
  const показанные = useMemo(() => filterTags(список, query, filter), [список, query, filter])
  const выбранный = список?.find((x) => x.key === selected)
  const пустые = emptyKeys(список)
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

  if ((список?.length ?? 0) === 0) {
    // Работа без бланка: тегов нет и взяться им неоткуда. Не ошибка — законный
    // случай (документ строится с нуля), но заполнять в нём нечего. Отсюда же
    // и выход: бланк прикладывают прямо здесь, и тогда теги появляются.
    return (
      <div className="flex flex-col gap-s4">
        <EmptyState
          icon="file"
          title={t('reports.work.noTemplateTitle')}
          text={t('reports.work.noTemplateText')}
          action={
            <Button variant="secondary" asChild>
              <Link to={`/projects/${projectId}`}>{t('reports.work.toProject')}</Link>
            </Button>
          }
        />
        <section className="rounded-md border border-line bg-surface p-s4">
          <h2 className="mb-s3 font-display text-md font-semibold text-ink-strong">
            {t('reports.templates.title')}
          </h2>
          <TemplatesPanel projectId={projectId} canEdit={canEdit} />
        </section>
      </div>
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
            {t('reports.work.subtitle', { total: список?.length ?? 0, empty: пустые.length })}
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
          {/* Бланки работы: приложить, отвязать, выбрать тот, по которому
              собирается документ. Окном, а не четвёртой колонкой: смотрят на
              них раз в работу, а место они заняли бы всегда. */}
          <Button variant="secondary" onClick={() => setTemplatesOpen(true)}>
            <Icon name="file" size={16} />
            {t('reports.templates.action')}
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
            tags={список}
            constructs={tags.data?.constructs}
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
          />
        </section>

        <section className="min-h-0">
          <PdfPreview build={build} canBuild={canEdit} />
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
                fill.fillReport(пустые, runPrompt.trim())
              }}
            >
              {t('reports.fillAll.start')}
            </Button>
          </>
        }
      >
        <div className="flex flex-col gap-s3 text-sm">
          <p className="text-muted">{t('reports.fillAll.keepsManual')}</p>
          {/* Общая подсказка на весь прогон — здесь, у кнопки запуска, а не в
              карточке тега: она про этот запуск и действует сразу на все теги.
              Задание отдельного тега она не отменяет, а дополняет. */}
          <Textarea
            label={t('reports.fillAll.promptLabel')}
            hint={t('reports.fillAll.promptHint')}
            placeholder={t('reports.fillAll.promptPlaceholder')}
            value={runPrompt}
            maxLength={4000}
            className="min-h-[64px] text-sm"
            onChange={(e) => setRunPrompt(e.target.value)}
          />
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
        open={templatesOpen}
        onOpenChange={setTemplatesOpen}
        title={t('reports.templates.title')}
        description={t('reports.templates.hint')}
        size="lg"
      >
        <TemplatesPanel projectId={projectId} canEdit={canEdit} />
      </Dialog>

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
