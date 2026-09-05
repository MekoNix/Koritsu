/**
 * DiagramWorkbench — рабочий экран схем: слева код и параметры, справа draw.io.
 *
 * Экран один на два модуля службы. Различий у них ровно три — маршрут
 * предпросмотра, третий параметр (режим отрисовки против палитры) и число
 * исходников, — и разводить ради них два дерева файлов значило бы держать две
 * копии одной раскладки, двух загрузок файла и двух сборок Word.
 *
 * Что происходит по шагам:
 *
 * * человек вставляет код → через задержку сайт просит предпросмотр
 *   (`POST /api/flowcharts/preview` или `…/uml/{вид}/preview`) — на томе службы
 *   при этом не появляется ничего;
 * * XML предпросмотра уезжает в кадр `embed.diagrams.net` сообщением; правки
 *   руками возвращаются оттуда и становятся текущей схемой;
 * * «Сохранить в проект» строит схему ещё раз, но уже маршрутом проекта: XML
 *   ложится артефактом, и тем же действием артефакт ставится значением тега —
 *   без этого сборка Word про схему не узнает;
 * * «Скачать Word» ставит задание `build` и ждёт его потоком; готовый DOCX
 *   скачивается артефактом.
 *
 * Тосты — только на конце задания и на отказ, причём провал
 * задания тостит оболочка (`useUserEvents`), а не этот экран: один тост на одну
 * беду. Здесь остаются свои тосты на отказ обычного запроса — сохранения схемы
 * и постановки задания. Отказ предпросмотра тостом не показывается вовсе: он
 * живёт в правой половине экрана, рядом со схемой, которой не получилось.
 */
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'

import { errorText, keys } from '@/api'
import { useJobStream, useUsage } from '@/api/hooks'
import { useDocumentCrumb } from '@/app/shell/breadcrumbs'
import { dictionary, useT } from '@/i18n'
import { cn } from '@/lib/cn'
import { useAppearance } from '@/theme'
import { Button, EmptyState, ErrorState, Icon, Input, SkeletonLines, Spinner, useToast } from '@/ui'

import { CodeEditor } from './CodeEditor'
import { DrawioFrame, type FrameState } from './DrawioFrame'
import { ControlBlock, Notices, Segmented } from './controls'
import { drawioOpenUrl } from './drawio'
import { safeFilename, saveBlob, saveText } from './download'
import {
  buildFlowchart,
  buildUml,
  fetchArtifact,
  fetchArtifactText,
  fetchModes,
  fetchProject,
  fetchThemes,
  previewFlowchart,
  previewUml,
  setValue,
  startBuildJob,
  type NamedSource,
} from './api'
import { usePreview } from './usePreview'
import { LANGS, type Lang, type UmlKind } from './types'

export type Module = 'flowcharts' | 'uml'

/** Расширение файла по языку — для имени нового исходника. */
const РАСШИРЕНИЕ: Record<Lang, string> = { py: 'py', cs: 'cs', cpp: 'cpp' }

/** Ключ тега по умолчанию. Те же слова, что служба даёт артефактам. */
const ТЕГ: Record<'flowchart' | UmlKind, string> = {
  flowchart: 'схема',
  classes: 'классы',
  objects: 'объекты',
}

/** Потолок файла — тот же `file_max_bytes`, что у службы (умолчание 5 МБ). */
const ФАЙЛ_МАКС = 5 * 1024 * 1024

/**
 * Русский ярлык по ключу перевода, а нет ключа — имя от службы как есть.
 *
 * Перечни режимов и палитр отдаёт строитель, а не сайт (`GET …/modes`,
 * `GET …/themes`), и новый режим появится там раньше, чем здесь. Показать его
 * английским именем честнее, чем спрятать: спрятанный режим — это выбор,
 * которого у человека нет и о котором он не узнает.
 */
function ярлык(перевод: (key: string) => string, ключ: string, запасной: string): string {
  return ключ in dictionary ? перевод(ключ) : запасной
}

type SourceFile = { name: string; source: string }

export function DiagramWorkbench({ module }: { module: Module }) {
  const t = useT()
  const toast = useToast()
  const { appearance } = useAppearance()
  const qc = useQueryClient()
  const { projectId = '' } = useParams()
  const [search, setSearch] = useSearchParams()

  const umlKind: UmlKind = search.get('kind') === 'objects' ? 'objects' : 'classes'
  const открытыйАртефакт = search.get('artifact')

  // ── что строим ─────────────────────────────────────────────────────────────
  const [lang, setLang] = useState<Lang>('py')
  const [mode, setMode] = useState('default')
  const [theme, setTheme] = useState(appearance.mode === 'dark' ? 'dark' : 'light')
  const [files, setFiles] = useState<SourceFile[]>([{ name: 'source.py', source: '' }])
  const [активный, setАктивный] = useState(0)
  const [tagKey, setTagKey] = useState(ТЕГ[module === 'uml' ? umlKind : 'flowchart'])
  const [caption, setCaption] = useState('')
  const [savedArtifact, setSavedArtifact] = useState<string | null>(null)
  const [saveError, setSaveError] = useState<unknown>(null)
  const [saving, setSaving] = useState(false)
  const [jobId, setJobId] = useState<string | null>(null)
  const [frameState, setFrameState] = useState<FrameState>('connecting')

  const текущий = files[Math.min(активный, files.length - 1)] ?? { name: 'source', source: '' }
  const естьКод = files.some((f) => f.source.trim().length > 0)

  // ── справочники службы ─────────────────────────────────────────────────────
  const modes = useQuery({
    queryKey: keys.diagrams.modes,
    queryFn: fetchModes,
    enabled: module === 'flowcharts',
    staleTime: Infinity,
  })
  const themes = useQuery({
    queryKey: keys.diagrams.themes,
    queryFn: fetchThemes,
    enabled: module === 'uml',
    staleTime: Infinity,
  })
  const project = useQuery({
    queryKey: ['diagrams', 'project', projectId] as const,
    queryFn: () => fetchProject(projectId),
    enabled: !!projectId,
  })
  const usage = useUsage()

  useDocumentCrumb(project.data?.name)

  // ── предпросмотр ───────────────────────────────────────────────────────────
  const sources = useMemo<NamedSource[]>(
    () => files.filter((f) => f.source.trim()).map((f) => ({ name: f.name, source: f.source })),
    [files],
  )

  const signature = useMemo(
    () =>
      JSON.stringify([
        module,
        umlKind,
        lang,
        module === 'flowcharts' ? mode : theme,
        sources.map((s) => [s.name, s.source]),
      ]),
    [module, umlKind, lang, mode, theme, sources],
  )

  const request = useCallback(() => {
    if (module === 'flowcharts') {
      return previewFlowchart({ source: sources[0]?.source ?? '', lang, mode })
    }
    return previewUml(umlKind, { sources, lang, theme })
  }, [module, umlKind, lang, mode, theme, sources])

  const preview = usePreview({ signature, enabled: естьКод, request })
  const { setXml } = preview

  // Схема, открытая из списка сохранённых: показываем её, пока не вставили код.
  const артефакт = useQuery({
    queryKey: keys.diagrams.artifact(projectId, открытыйАртефакт ?? ''),
    queryFn: () => fetchArtifactText(projectId, открытыйАртефакт as string),
    enabled: !!projectId && !!открытыйАртефакт,
    staleTime: Infinity,
  })
  useEffect(() => {
    if (артефакт.data) setXml(артефакт.data)
  }, [артефакт.data, setXml])

  // ── сохранить в проект ─────────────────────────────────────────────────────
  const сохранить = useCallback(async (): Promise<string | null> => {
    if (!projectId || !естьКод) return null
    setSaving(true)
    setSaveError(null)
    try {
      const готово =
        module === 'flowcharts'
          ? await buildFlowchart(projectId, { source: sources[0]?.source ?? '', lang, mode })
          : await buildUml(projectId, umlKind, { sources, lang, theme })
      // Артефакт сам по себе в отчёт не попадёт: сборка читает значения тегов,
      // поэтому тем же действием ставим схему значением. Иначе «сохранил» и
      // «в документе появилось» оказались бы двумя разными действиями, о
      // разнице между которыми человеку никто не сказал.
      const ключ = tagKey.trim()
      if (ключ) {
        await setValue(projectId, ключ, {
          type: 'diagram',
          artifact: готово.artifact,
          ...(caption.trim() ? { caption: caption.trim() } : {}),
        })
      }
      setSavedArtifact(готово.artifact)
      // Список сохранённых схем на главной модуля собирается из значений
      // проекта — значит, после записи он устарел ровно в этот момент.
      void qc.invalidateQueries({ queryKey: keys.diagrams.values(projectId) })
      return готово.artifact
    } catch (беда) {
      setSaveError(беда)
      toast.error(t('diagrams.work.saveFailed'), errorText(беда))
      return null
    } finally {
      setSaving(false)
    }
  }, [
    projectId,
    естьКод,
    module,
    umlKind,
    sources,
    lang,
    mode,
    theme,
    tagKey,
    caption,
    toast,
    t,
    qc,
  ])

  // ── Word: задание `build` и его поток ──────────────────────────────────────
  const job = useJobStream(jobId)
  const скачано = useRef<string | null>(null)

  useEffect(() => {
    const карточка = job.job
    if (!карточка || !job.done || !jobId) return
    if (скачано.current === jobId) return
    скачано.current = jobId
    // Провал задания тостит оболочка (`useUserEvents`) по коду из уведомления:
    // свой тост был бы вторым на одну беду.
    if (карточка.status !== 'done') return
    const артефакты = (карточка.result?.artifacts ?? {}) as Record<string, string>
    const docx = артефакты.docx
    if (!docx) {
      toast.error(t('diagrams.work.wordFailed'))
      return
    }
    // Сборка отдаёт документ и **вместе с ним** список того, что в него не
    // попало (`result.errors`): `ok: true` тут значит «DOCX собран», а не «всё
    // получилось». Промолчать об этом значило бы отдать человеку документ без
    // схемы и не сказать, почему её там нет.
    const беды = (карточка.result?.errors ?? []) as { key?: string; message?: string }[]
    void fetchArtifact(projectId, docx)
      .then((blob) => {
        saveBlob(blob, safeFilename(project.data?.name ?? 'koritsu', 'docx'))
        const первая = беды.find((б) => б.message)?.message
        if (первая) toast.warn(t('diagrams.work.wordReady'), первая)
        else toast.success(t('diagrams.work.wordReady'), t('diagrams.work.wordReadyText'))
      })
      .catch((беда: unknown) => toast.error(t('diagrams.work.wordFailed'), errorText(беда)))
  }, [job.done, job.job, jobId, projectId, project.data?.name, toast, t])

  const скачатьWord = useCallback(async () => {
    const артефакт = savedArtifact ?? (await сохранить())
    if (!артефакт) return
    try {
      const id = await startBuildJob(
        projectId,
        safeFilename(project.data?.name ?? 'koritsu', 'docx'),
      )
      скачано.current = null
      setJobId(id)
    } catch (беда) {
      toast.error(t('diagrams.work.wordFailed'), errorText(беда))
    }
  }, [savedArtifact, сохранить, projectId, project.data?.name, toast, t])

  // ── файл с кодом ───────────────────────────────────────────────────────────
  const ввод = useRef<HTMLInputElement | null>(null)
  const [fileError, setFileError] = useState<string | null>(null)

  const принятьФайл = useCallback(
    async (file: File) => {
      setFileError(null)
      if (file.size > ФАЙЛ_МАКС) {
        setFileError(t('diagrams.file.tooBig', { n: Math.round(ФАЙЛ_МАКС / 1024) }))
        return
      }
      const текст = await file.text()
      // Двоичное содержимое читается как текст с U+FFFD — по нему его и узнаём.
      if (текст.includes('\u0000') || текст.includes('�')) {
        setFileError(t('diagrams.file.notText'))
        return
      }
      const по_имени = file.name.toLowerCase()
      const язык: Lang | null = по_имени.endsWith('.py')
        ? 'py'
        : по_имени.endsWith('.cs')
          ? 'cs'
          : /\.(cpp|cc|cxx|hpp|h)$/.test(по_имени)
            ? 'cpp'
            : null
      if (язык) setLang(язык)
      setFiles((было) => {
        const кусок = { name: file.name, source: текст }
        if (module === 'flowcharts') return [кусок]
        // У UML исходников несколько; пустую заготовку первым делом заменяем.
        const без_пустых = было.filter((f) => f.source.trim())
        return [...без_пустых, кусок]
      })
      setАктивный(module === 'flowcharts' ? 0 : Math.max(0, files.length))
    },
    [module, files.length, t],
  )

  // ── шапка и кнопки ─────────────────────────────────────────────────────────
  const заголовок = t(
    module === 'uml' ? 'diagrams.home.uml.title' : 'diagrams.home.flowcharts.title',
  )
  const открыть = preview.xml ? drawioOpenUrl(preview.xml, project.data?.name ?? 'koritsu') : null
  const ценаWord = usage.data?.prices?.build
  const wordИдёт = !!jobId && !job.done

  if (project.isError) {
    return <ErrorState error={project.error} onRetry={() => void project.refetch()} />
  }

  return (
    <section className="flex flex-col gap-s4">
      <header className="flex flex-col gap-s2">
        <Link
          to={module === 'uml' ? '/uml' : '/flowcharts'}
          className="inline-flex w-fit items-center gap-1.5 text-sm text-muted hover:text-ink"
        >
          <Icon name="arrowLeft" size={16} />
          {t('diagrams.work.backToList')}
        </Link>
        <h1 className="font-display text-xl font-bold tracking-tight text-ink-strong">
          {заголовок}
        </h1>
        <p className="max-w-[70ch] text-sm text-muted">
          {t(module === 'uml' ? 'diagrams.home.uml.lead' : 'diagrams.home.flowcharts.lead')}
        </p>
      </header>

      <div className="flex flex-wrap items-center gap-s2">
        <Button
          variant="secondary"
          disabled={!preview.xml}
          onClick={() =>
            preview.xml &&
            saveText(preview.xml, safeFilename(project.data?.name ?? 'koritsu', 'drawio.xml'))
          }
        >
          <Icon name="download" size={16} />
          {t('diagrams.work.downloadXml')}
        </Button>
        <Button
          variant="secondary"
          loading={wordИдёт || saving}
          disabled={!естьКод || wordИдёт}
          onClick={() => void скачатьWord()}
        >
          <Icon name="file" size={16} />
          {t('diagrams.work.downloadWord')}
        </Button>
        {/* Ссылкой, а не `onClick`: работает Ctrl+клик и «открыть в новой
            вкладке». `noopener` обязателен — иначе чужая вкладка получает
            ссылку на нашу. Схемы нет или она длиннее ссылки — кнопка гаснет и
            говорит словами, почему. */}
        {открыть ? (
          <Button variant="secondary" asChild>
            <a href={открыть} target="_blank" rel="noreferrer noopener">
              <Icon name="external" size={16} />
              {t('diagrams.work.openInDrawio')}
            </a>
          </Button>
        ) : (
          <Button
            variant="secondary"
            disabled
            title={preview.xml ? t('diagrams.work.openTooBig') : undefined}
          >
            <Icon name="external" size={16} />
            {t('diagrams.work.openInDrawio')}
          </Button>
        )}
        <Button
          variant="secondary"
          loading={saving}
          disabled={!естьКод || saving}
          onClick={() => void сохранить()}
        >
          <Icon name="save" size={16} />
          {t('diagrams.work.save')}
        </Button>
        <div className="grow" />
        <Button
          variant="primary"
          loading={preview.pending}
          disabled={!естьКод}
          onClick={preview.run}
        >
          <Icon name={module === 'uml' ? 'uml' : 'flowchart'} size={16} />
          {t('diagrams.work.build')}
        </Button>
      </div>

      {ценаWord !== undefined && usage.data && (
        <p className="text-xs text-muted">
          {t('diagrams.work.wordPrice', {
            n: ценаWord,
            left: usage.data.remaining_units,
          })}
        </p>
      )}
      {savedArtifact && !saveError && (
        <p className="flex items-center gap-1.5 text-xs text-ok">
          <Icon name="checkCircle" size={14} />
          {t('diagrams.work.saved')} · {t('diagrams.work.savedTag', { key: tagKey })}
        </p>
      )}

      <div className="grid min-h-[460px] gap-s4 lg:h-[calc(100vh-320px)] lg:grid-cols-[minmax(340px,40%)_1fr]">
        {/* ── слева: код и параметры ─────────────────────────────────────── */}
        <div className="flex min-h-0 flex-col gap-s3 overflow-auto rounded-md border border-line bg-surface p-s3">
          <div className="flex flex-wrap gap-s3">
            <ControlBlock label={t('diagrams.work.lang')}>
              <Segmented
                label={t('diagrams.work.lang')}
                value={lang}
                onChange={setLang}
                options={LANGS.map((id) => ({ value: id, label: t(`diagrams.lang.${id}`) }))}
              />
            </ControlBlock>

            {module === 'flowcharts' ? (
              <ControlBlock label={t('diagrams.work.mode')}>
                {modes.isPending ? (
                  <SkeletonLines count={1} className="w-[220px]" />
                ) : (
                  <Segmented
                    label={t('diagrams.work.mode')}
                    value={mode}
                    onChange={setMode}
                    options={(modes.data ?? []).map((m) => ({
                      value: m.id,
                      label: ярлык(t, `diagrams.mode.${m.id}`, m.id),
                      title: m.description,
                    }))}
                  />
                )}
              </ControlBlock>
            ) : (
              <>
                <ControlBlock label={t('diagrams.work.kind')}>
                  <Segmented
                    label={t('diagrams.work.kind')}
                    value={umlKind}
                    onChange={(значение) => {
                      const следующий = new URLSearchParams(search)
                      следующий.set('kind', значение)
                      setSearch(следующий, { replace: true })
                      setTagKey(ТЕГ[значение])
                    }}
                    options={[
                      { value: 'classes', label: t('diagrams.work.classes') },
                      { value: 'objects', label: t('diagrams.work.objects') },
                    ]}
                  />
                </ControlBlock>
                <ControlBlock label={t('diagrams.work.theme')}>
                  <Segmented
                    label={t('diagrams.work.theme')}
                    value={theme}
                    onChange={setTheme}
                    options={(themes.data ?? ['dark', 'light', 'css']).map((id) => ({
                      value: id,
                      label: ярлык(t, `diagrams.theme.${id}`, id),
                    }))}
                  />
                </ControlBlock>
              </>
            )}
          </div>

          {module === 'uml' && (
            <ControlBlock
              label={t('diagrams.work.files')}
              hint={umlKind === 'objects' ? t('diagrams.work.entryHint') : undefined}
            >
              <div className="flex flex-wrap items-center gap-1">
                {files.map((file, i) => (
                  <span
                    key={`${file.name}-${i}`}
                    className={cn(
                      'inline-flex items-center gap-1 rounded-sm border px-2 py-1 text-xs',
                      i === активный
                        ? 'border-accent bg-accent-bg text-ink-strong'
                        : 'border-line-strong bg-surface-2 text-muted',
                    )}
                  >
                    <button type="button" onClick={() => setАктивный(i)}>
                      {file.name}
                      {i === 0 && umlKind === 'objects' ? ` · ${t('diagrams.work.entry')}` : ''}
                    </button>
                    {files.length > 1 && (
                      <button
                        type="button"
                        aria-label={t('diagrams.work.removeFile')}
                        onClick={() => {
                          setFiles((было) => было.filter((_, n) => n !== i))
                          setАктивный((n) => (n > 0 ? n - 1 : 0))
                        }}
                      >
                        <Icon name="close" size={12} />
                      </button>
                    )}
                  </span>
                ))}
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => {
                    setFiles((было) => [
                      ...было,
                      { name: `source${было.length + 1}.${РАСШИРЕНИЕ[lang]}`, source: '' },
                    ])
                    setАктивный(files.length)
                  }}
                >
                  <Icon name="plus" size={14} />
                  {t('diagrams.work.addFile')}
                </Button>
              </div>
            </ControlBlock>
          )}

          <div className="flex min-h-[220px] flex-1 flex-col overflow-hidden rounded-sm border border-line bg-surface-2">
            <div className="flex items-center justify-between gap-s2 border-b border-line px-s3 py-2 text-xs text-muted">
              <span className="truncate font-mono">{текущий.name}</span>
              <span>{t('diagrams.work.lines', { n: текущий.source.split('\n').length })}</span>
            </div>
            <div className="min-h-0 flex-1 overflow-auto">
              <CodeEditor
                value={текущий.source}
                lang={lang}
                ariaLabel={t('diagrams.work.codeLabel')}
                placeholder={t('diagrams.work.codePlaceholder')}
                onSubmit={preview.run}
                onChange={(значение) =>
                  setFiles((было) =>
                    было.map((f, i) => (i === активный ? { ...f, source: значение } : f)),
                  )
                }
              />
            </div>
            <div className="flex items-center justify-between gap-s2 border-t border-line px-s3 py-2">
              <span className="text-xs text-muted">{t('diagrams.work.buildHint')}</span>
              <div className="flex items-center gap-s2">
                <input
                  ref={ввод}
                  type="file"
                  className="hidden"
                  accept=".py,.cs,.cpp,.cc,.cxx,.hpp,.h,text/plain"
                  onChange={(событие) => {
                    const file = событие.target.files?.[0]
                    if (file) void принятьФайл(file)
                    событие.target.value = ''
                  }}
                />
                <Button size="sm" variant="ghost" onClick={() => ввод.current?.click()}>
                  <Icon name="upload" size={14} />
                  {t('diagrams.work.upload')}
                </Button>
              </div>
            </div>
          </div>
          {fileError && <p className="text-xs text-err">{fileError}</p>}

          <div className="flex flex-wrap gap-s3">
            <Input
              label={t('diagrams.work.tagKey')}
              hint={t('diagrams.work.tagKeyHint')}
              value={tagKey}
              onChange={(событие) => setTagKey(событие.target.value)}
              wrapperClassName="min-w-[180px] flex-1"
            />
            <Input
              label={t('diagrams.work.caption')}
              hint={t('diagrams.work.captionHint')}
              value={caption}
              onChange={(событие) => setCaption(событие.target.value)}
              wrapperClassName="min-w-[180px] flex-1"
            />
          </div>
        </div>

        {/* ── справа: встроенный draw.io ─────────────────────────────────── */}
        <div className="flex min-h-0 flex-col overflow-hidden rounded-md border border-line bg-surface">
          <div className="flex items-center gap-s2 border-b border-line px-s3 py-2 text-xs">
            <span className="font-semibold text-ink">draw.io</span>
            <span className="truncate text-muted">
              {frameState === 'ready'
                ? t('diagrams.preview.editorHint')
                : t('diagrams.preview.title')}
            </span>
            <div className="grow" />
            {preview.pending && <Spinner size={14} />}
            {preview.waiting && !preview.pending && (
              <span className="text-muted">{t('diagrams.work.waiting')}</span>
            )}
            {wordИдёт && <span className="text-muted">{t('diagrams.work.wordStarted')}</span>}
          </div>

          <div className="relative min-h-[320px] flex-1">
            {!естьКод && !preview.xml ? (
              <EmptyState
                icon="flowchart"
                title={t('diagrams.preview.empty')}
                text={t('diagrams.preview.emptyText')}
                className="h-full"
              />
            ) : (
              <DrawioFrame
                xml={preview.xml}
                onEdited={preview.setXml}
                onStateChange={setFrameState}
                className="h-full w-full"
              />
            )}
          </div>

          <div className="flex flex-col gap-s2 border-t border-line px-s3 py-2">
            {preview.rateLimited && (
              <p className="text-xs text-warn">{t('diagrams.preview.rateLimited')}</p>
            )}
            {preview.error != null && !preview.rateLimited && (
              <p className="text-xs text-err">{errorText(preview.error)}</p>
            )}
            {!preview.auto && !preview.rateLimited && (
              <p className="text-xs text-muted">{t('diagrams.work.autoOff')}</p>
            )}
            <Notices notices={preview.notices} />
          </div>
        </div>
      </div>
    </section>
  )
}
