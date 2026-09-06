/**
 * DiagramWorkbench — рабочий экран схем: слева код и параметры, справа draw.io.
 *
 * Экран один на два модуля службы. Различий у них ровно три — маршрут
 * построения, третий параметр (режим отрисовки против палитры) и число
 * исходников, — и разводить ради них два дерева файлов значило бы держать две
 * копии одной раскладки, двух загрузок файла и двух сборок Word.
 *
 * **Экран во всю ширину окна** (`useWidePage`), а не в колонке текста: здесь
 * две крупные вещи рядом — поле кода и настоящий редактор draw.io, — и полтора
 * сантиметра пустоты по краям забирают их у обеих. По той же причине половины
 * равные: код читают столько же, сколько смотрят на схему.
 *
 * Что происходит по шагам:
 *
 * * человек вставляет код и нажимает «Построить схему» (Ctrl+Enter). Сама собой
 *   схема строится ровно один раз — когда её ещё не было; дальше правка кода
 *   картинку не трогает (`usePreview`);
 * * построение **и есть сохранение**: XML ложится артефактом работы, схема
 *   попадает в журнал запусков под своим номером («Схема 1 — Курсовая»), а
 *   рядом с ней хранится код и параметры. Кнопки «сохранить в проект» нет —
 *   половина построенных схем терялась бы молча;
 * * имя сохранённой схемы правится прямо в шапке (`RunName`): имя схемы и есть
 *   имя записи журнала, и второго места, где его менять, нет;
 * * следующие нажатия перестраивают **ту же** схему (`PUT …/{run_id}`), а не
 *   заводят вторую: пять нажатий, пока подбирается код, — это одна схема;
 * * XML уезжает в кадр `embed.diagrams.net` сообщением; правки руками
 *   возвращаются оттуда и становятся текущей схемой;
 * * «Редактировать в draw.io» и «Просмотреть диаграмму» открывают схему в
 *   отдельном окне draw.io — тоже сообщением, а не адресом, поэтому длина схемы
 *   ничего не значит (`drawio.ts`);
 * * «Скачать Word» ставит задание `build` и ждёт его потоком; готовый DOCX
 *   скачивается артефактом.
 *
 * Тосты — только на конце задания и на отказ, причём провал задания тостит
 * оболочка (`useUserEvents`), а не этот экран: один тост на одну беду. Отказ
 * построения тостом не показывается вовсе: он живёт в правой половине экрана,
 * рядом со схемой, которой не получилось.
 */
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'

import { errorText, keys } from '@/api'
import { useJobStream } from '@/api/hooks'
import { useDocumentCrumb } from '@/app/shell/breadcrumbs'
import { useWidePage } from '@/app/shell/widePage'
// Имя запуска рисует область работ (`runTitle`), а не этот экран: имя схемы в
// журнале работы и имя схемы здесь — одно и то же имя, и второе такое же
// правило разошлось бы с первым на первом же переименовании.
import { RunName } from '@/features/projects/RunName'
import { runTitle } from '@/features/projects/format'
import { dictionary, useT } from '@/i18n'
import { cn } from '@/lib/cn'
import { useAppearance } from '@/theme'
import {
  Button,
  Dialog,
  EmptyState,
  ErrorState,
  Icon,
  Input,
  SkeletonLines,
  Spinner,
  useToast,
} from '@/ui'

import { CodeEditor } from './CodeEditor'
import { DrawioFrame, type FrameState } from './DrawioFrame'
import { ControlBlock, Notices, Segmented } from './controls'
import { openDrawioWindow } from './drawio'
import { safeFilename, saveBlob, saveText } from './download'
import {
  buildFlowchart,
  buildUml,
  fetchArtifact,
  fetchDiagram,
  fetchModes,
  fetchProject,
  fetchThemes,
  setValue,
  startBuildJob,
  type NamedSource,
} from './api'
import { usePreview } from './usePreview'
import { LANGS, type FullDiagram, type Lang, type Module, type UmlKind } from './types'

export type { Module }

/** Расширение файла по языку — для имени нового исходника. */
const РАСШИРЕНИЕ: Record<Lang, string> = { py: 'py', cs: 'cs', cpp: 'cpp' }

/**
 * Язык по расширению имени файла, а нет расширения — `null`.
 *
 * Одно правило на оба способа завести исходник: загрузку с диска и «Добавить
 * файл». Второе такое же разошлось бы с первым на первом же новом расширении,
 * и один и тот же `.hpp` открывался бы то как C++, то как Python.
 */
function языкПоИмени(name: string): Lang | null {
  const имя = name.toLowerCase()
  if (имя.endsWith('.py')) return 'py'
  if (имя.endsWith('.cs')) return 'cs'
  if (/\.(cpp|cc|cxx|hpp|h)$/.test(имя)) return 'cpp'
  return null
}

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
  useWidePage()

  const umlKind: UmlKind = search.get('kind') === 'objects' ? 'objects' : 'classes'
  const открытая = search.get('run')

  // ── что строим ─────────────────────────────────────────────────────────────
  const [lang, setLang] = useState<Lang>('py')
  const [mode, setMode] = useState('default')
  const [theme, setTheme] = useState(appearance.mode === 'dark' ? 'dark' : 'light')
  // У UML исходников несколько, и при входе их **ноль**: файл, заведённый до
  // того, как человек что-то написал, — это пустая заготовка, о которой он не
  // просил, и убрать её было нельзя. Файлы заводит только человек — кнопкой
  // «Добавить файл» или загрузкой с диска, — и любой из них, включая
  // последний, он вправе убрать. У блок-схем исходник один и списка нет:
  // маршрут службы принимает ровно один `source`, и выбор «какой из двух»
  // означал бы выбор, которого у постройки не бывает.
  const [files, setFiles] = useState<SourceFile[]>(
    module === 'uml' ? [] : [{ name: 'source.py', source: '' }],
  )
  const [активный, setАктивный] = useState(0)
  const [tagKey, setTagKey] = useState(ТЕГ[module === 'uml' ? umlKind : 'flowchart'])
  const [caption, setCaption] = useState('')
  /** Запись журнала сохранённой схемы: есть — перестраиваем её, нет — заводим. */
  const [runId, setRunId] = useState<string | null>(открытая)
  const [сохранена, setСохранена] = useState<{ n: number; name: string } | null>(null)
  const [jobId, setJobId] = useState<string | null>(null)
  const [frameState, setFrameState] = useState<FrameState>('connecting')
  /** Окно «Добавить файл»: имя спрашивается, язык выводится из расширения. */
  const [добавление, setДобавление] = useState(false)
  const [новоеИмя, setНовоеИмя] = useState('')

  const текущий = files[Math.min(активный, files.length - 1)] ?? {
    name: `source.${РАСШИРЕНИЕ[lang]}`,
    source: '',
  }
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

  useDocumentCrumb(project.data?.name)

  // ── построение ─────────────────────────────────────────────────────────────
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

  /**
   * Построить и тем же действием сохранить.
   *
   * Ключ тега ставится следом за постройкой: схема в работе и схема в
   * документе — разные вещи, и сборка Word читает именно значения тегов. Отказ
   * тега схему не отменяет — она уже сохранена, — поэтому он только тостит.
   */
  const request = useCallback(async () => {
    const готово: FullDiagram =
      module === 'flowcharts'
        ? await buildFlowchart(projectId, { source: sources[0]?.source ?? '', lang, mode }, runId)
        : await buildUml(projectId, umlKind, { sources, lang, theme }, runId)
    setRunId(готово.run_id)
    setСохранена({ n: готово.n, name: готово.name })
    void qc.invalidateQueries({ queryKey: keys.diagrams.list(module, projectId) })
    void qc.invalidateQueries({ queryKey: keys.diagrams.one(module, projectId, готово.run_id) })
    // Запись журнала — та же самая: список «Что в работе» на странице работы
    // обязан узнать о новой схеме тем же действием.
    void qc.invalidateQueries({ queryKey: keys.projects.one(projectId) })

    const ключ = tagKey.trim()
    if (ключ) {
      try {
        await setValue(projectId, ключ, {
          type: 'diagram',
          artifact: готово.artifact,
          ...(caption.trim() ? { caption: caption.trim() } : {}),
        })
      } catch (беда) {
        toast.error(t('diagrams.work.tagFailed'), errorText(беда))
      }
    }
    return { xml: готово.xml, notices: готово.notices }
  }, [module, projectId, sources, lang, mode, theme, umlKind, runId, tagKey, caption, qc, toast, t])

  const preview = usePreview({ signature, enabled: естьКод && !!projectId, request })
  const { showBuilt } = preview

  // ── схема, открытая из списка ──────────────────────────────────────────────
  const сохранённая = useQuery({
    queryKey: keys.diagrams.one(module, projectId, открытая ?? ''),
    queryFn: () => fetchDiagram(module, projectId, открытая as string),
    enabled: !!projectId && !!открытая,
    staleTime: Infinity,
  })

  // Открытая схема наполняет экран целиком: код, параметры и картинку. Без
  // кода экран показывал бы чужую схему рядом с пустым полем — то самое, из-за
  // чего сохранённая схема была бесполезна.
  const наполнено = useRef<string | null>(null)
  useEffect(() => {
    const схема = сохранённая.data
    if (!схема || наполнено.current === схема.run_id) return
    наполнено.current = схема.run_id
    setRunId(схема.run_id)
    setСохранена({ n: схема.n, name: схема.name })
    setLang(схема.lang)
    if (схема.mode) setMode(схема.mode)
    if (схема.theme) setTheme(схема.theme)
    if (схема.sources.length) {
      setFiles(схема.sources.map((к) => ({ name: к.name || 'source', source: к.source })))
      setАктивный(0)
    }
    if (схема.kind === 'classes' || схема.kind === 'objects') {
      const следующий = new URLSearchParams(search)
      следующий.set('kind', схема.kind)
      setSearch(следующий, { replace: true })
      setTagKey(ТЕГ[схема.kind])
    }
    showBuilt(схема.xml, схема.notices)
  }, [сохранённая.data, search, setSearch, showBuilt])

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
    if (!runId) {
      toast.error(t('diagrams.work.wordNeedsProject'))
      return
    }
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
  }, [runId, projectId, project.data?.name, toast, t])

  // ── код и файлы ────────────────────────────────────────────────────────────

  /** Правка кода. Файлов нет — править нечего: поля кода на экране тоже нет. */
  const правитьКод = useCallback(
    (значение: string) => {
      setFiles((было) => было.map((f, i) => (i === активный ? { ...f, source: значение } : f)))
    },
    [активный],
  )

  /**
   * Завести пустой исходник. Имя спрашивается, язык выводится из расширения.
   *
   * Имя без точки дополняется расширением выбранного языка: «модуль» на экране
   * с выбранным Python — это `модуль.py`, и заставлять человека дописывать то,
   * что уже выбрано переключателем, незачем.
   */
  const добавитьФайл = useCallback(() => {
    const введено = новоеИмя.trim()
    const основа = введено || `source${files.length + 1}`
    const имя = основа.includes('.') ? основа : `${основа}.${РАСШИРЕНИЕ[lang]}`
    const язык = языкПоИмени(имя)
    if (язык) setLang(язык)
    setFiles((было) => [...было, { name: имя, source: '' }])
    setАктивный(files.length)
    setДобавление(false)
    setНовоеИмя('')
  }, [новоеИмя, files.length, lang])

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
      if (текст.includes(' ') || текст.includes('�')) {
        setFileError(t('diagrams.file.notText'))
        return
      }
      const язык = языкПоИмени(file.name)
      if (язык) setLang(язык)
      setFiles((было) => {
        const кусок = { name: file.name, source: текст }
        // У блок-схем исходник один: маршрут службы принимает ровно один
        // `source`, и загруженный файл встаёт на место прежнего.
        if (module === 'flowcharts') return [кусок]
        // У UML загруженный файл встаёт рядом с теми, что уже завели, — и
        // пустые среди них остаются. Пустой файл здесь не заготовка службы, а
        // файл, о котором человек попросил кнопкой «Добавить файл»; выбросить
        // его за него значило бы решить за человека, из чего строится
        // диаграмма.
        return [...было, кусок]
      })
      setАктивный(module === 'flowcharts' ? 0 : files.length)
    },
    [module, files.length, t],
  )

  // ── шапка и кнопки ─────────────────────────────────────────────────────────
  const заголовок = t(
    module === 'uml' ? 'diagrams.home.uml.title' : 'diagrams.home.flowcharts.title',
  )
  const имяСхемы =
    сохранена &&
    runTitle(t, { module, name: сохранена.name, n: сохранена.n }, project.data?.name ?? '')
  const wordИдёт = !!jobId && !job.done

  const открытьВDrawio = useCallback(
    (вид: 'edit' | 'view') => {
      if (!preview.xml) return
      const открылось = openDrawioWindow(
        вид,
        preview.xml,
        { dark: appearance.mode === 'dark', title: project.data?.name ?? 'koritsu' },
        вид === 'edit' ? preview.setXml : undefined,
      )
      if (!открылось) toast.error(t('diagrams.work.windowBlocked'))
    },
    [preview.xml, preview.setXml, appearance.mode, project.data?.name, toast, t],
  )

  if (project.isError) {
    return <ErrorState error={project.error} onRetry={() => void project.refetch()} />
  }

  return (
    <section className="flex flex-col gap-s3">
      <header className="flex flex-col gap-s2">
        <Link
          to={module === 'uml' ? '/uml' : '/flowcharts'}
          className="inline-flex w-fit items-center gap-1.5 text-sm text-muted hover:text-ink"
        >
          <Icon name="arrowLeft" size={16} />
          {t('diagrams.work.backToList')}
        </Link>
        <div className="flex flex-wrap items-center gap-x-s3 gap-y-1">
          <h1 className="font-display text-xl font-bold tracking-tight text-ink-strong">
            {заголовок}
          </h1>
          {/* Имя схемы стоит в шапке и правится там же: это имя записи журнала,
              то самое, под которым схема лежит в списке модуля и в «Что в
              работе». Пока схемы нет, называть нечего — строки тоже нет. */}
          {runId && сохранена && имяСхемы && (
            <span className="flex min-w-0 items-center gap-1.5 text-sm text-muted">
              <Icon name="checkCircle" size={14} className="shrink-0 text-ok" />
              {t('diagrams.work.savedAs')}
              <RunName
                projectId={projectId}
                runId={runId}
                name={сохранена.name}
                title={имяСхемы}
                className="font-semibold text-ink-strong"
                onRenamed={(имя) => setСохранена((было) => (было ? { ...было, name: имя } : было))}
              />
            </span>
          )}
        </div>
      </header>

      <div className="flex flex-wrap items-center gap-s2">
        <Button
          variant="primary"
          loading={preview.pending}
          disabled={!естьКод || preview.pending}
          onClick={preview.run}
        >
          <Icon name={module === 'uml' ? 'uml' : 'flowchart'} size={16} />
          {t('diagrams.work.build')}
        </Button>
        {/* Выключенная кнопка молча ничего не делает, и человек ищет причину в
            себе. Причина у неё одна: строить нечего. */}
        {!естьКод && <p className="text-xs text-muted">{t('diagrams.work.buildNeedsCode')}</p>}
        <Button variant="secondary" disabled={!preview.xml} onClick={() => открытьВDrawio('edit')}>
          <Icon name="external" size={16} />
          {t('diagrams.work.editInDrawio')}
        </Button>
        <Button variant="secondary" disabled={!preview.xml} onClick={() => открытьВDrawio('view')}>
          <Icon name="eye" size={16} />
          {t('diagrams.work.viewDiagram')}
        </Button>
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
          loading={wordИдёт}
          disabled={!runId || wordИдёт}
          onClick={() => void скачатьWord()}
        >
          <Icon name="file" size={16} />
          {t('diagrams.work.downloadWord')}
        </Button>
        <div className="grow" />
      </div>

      <div className="grid min-h-[520px] gap-s3 lg:h-[calc(100vh-210px)] lg:grid-cols-2">
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
                      // Смена вида — это новая диаграмма, а не перестройка
                      // прежней: классы и объекты отвечают на разные вопросы, и
                      // подменить одно другим под тем же именем и номером
                      // значило бы потерять первую.
                      следующий.delete('run')
                      setSearch(следующий, { replace: true })
                      setRunId(null)
                      setСохранена(null)
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

          {/* Поле выбора файла одно на оба состояния экрана: оно нужно и
              списку исходников, и пустому экрану без единого файла. */}
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

          {module === 'uml' && (
            <ControlBlock
              label={t('diagrams.work.files')}
              hint={
                files.length && umlKind === 'objects' ? t('diagrams.work.entryHint') : undefined
              }
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
                    {/* Убрать можно любой исходник, и последний тоже: файл,
                        который нельзя удалить, — это чужое решение о том, из
                        чего строится диаграмма. Без файлов «Построить»
                        выключается и говорит, почему. */}
                    <button
                      type="button"
                      aria-label={t('diagrams.work.removeFileNamed', { name: file.name })}
                      onClick={() => {
                        setFiles((было) => было.filter((_, n) => n !== i))
                        setАктивный((n) => (n > 0 ? n - 1 : 0))
                      }}
                    >
                      <Icon name="close" size={12} />
                    </button>
                  </span>
                ))}
                <Button size="sm" variant="ghost" onClick={() => setДобавление(true)}>
                  <Icon name="plus" size={14} />
                  {t('diagrams.work.addFile')}
                </Button>
              </div>
            </ControlBlock>
          )}

          {files.length === 0 ? (
            <div className="flex min-h-[320px] flex-1 flex-col items-center justify-center gap-s3 rounded-sm border border-dashed border-line bg-surface-2 p-s3 text-center">
              <p className="max-w-[46ch] text-sm text-muted">{t('diagrams.work.noFiles')}</p>
              <div className="flex flex-wrap items-center justify-center gap-s2">
                <Button size="sm" variant="secondary" onClick={() => setДобавление(true)}>
                  <Icon name="plus" size={14} />
                  {t('diagrams.work.addFile')}
                </Button>
                <Button size="sm" variant="ghost" onClick={() => ввод.current?.click()}>
                  <Icon name="upload" size={14} />
                  {t('diagrams.work.upload')}
                </Button>
              </div>
            </div>
          ) : (
            <div className="flex min-h-[320px] flex-1 flex-col overflow-hidden rounded-sm border border-line bg-surface-2">
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
                  onChange={правитьКод}
                />
              </div>
              <div className="flex items-center justify-between gap-s2 border-t border-line px-s3 py-2">
                <span className="text-xs text-muted">{t('diagrams.work.buildHint')}</span>
                <Button size="sm" variant="ghost" onClick={() => ввод.current?.click()}>
                  <Icon name="upload" size={14} />
                  {t('diagrams.work.upload')}
                </Button>
              </div>
            </div>
          )}
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
            {!preview.xml ? (
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
            {preview.stale && !preview.pending && (
              <p className="text-xs text-muted">{t('diagrams.work.codeChanged')}</p>
            )}
            <Notices notices={preview.notices} />
          </div>
        </div>
      </div>

      {/* Имя спрашивается окном, а не придумывается молча: имя исходника стоит
          в замечаниях разбора («в схему не вошло: goto case, main.cs:12»), и
          `source3.py` вместо `main.cs` там ничего не объясняет. Язык при этом
          не спрашивается: расширение о нём уже сказало. */}
      <Dialog
        open={добавление}
        onOpenChange={(открыто) => {
          setДобавление(открыто)
          if (!открыто) setНовоеИмя('')
        }}
        title={t('diagrams.work.addFileTitle')}
        footer={
          <>
            <Button variant="ghost" onClick={() => setДобавление(false)}>
              {t('common.action.cancel')}
            </Button>
            <Button variant="primary" onClick={добавитьФайл}>
              {t('diagrams.work.addFile')}
            </Button>
          </>
        }
      >
        <Input
          label={t('diagrams.work.fileName')}
          hint={t('diagrams.work.fileNameHint')}
          value={новоеИмя}
          autoFocus
          placeholder={`source${files.length + 1}.${РАСШИРЕНИЕ[lang]}`}
          onChange={(событие) => setНовоеИмя(событие.target.value)}
          onKeyDown={(событие) => {
            if (событие.key === 'Enter') {
              событие.preventDefault()
              добавитьФайл()
            }
          }}
        />
      </Dialog>
    </section>
  )
}
