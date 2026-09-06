/**
 * KadaiWorkPage — экран одного решения: `/kadai/:projectId/:runId`.
 *
 * Решений в работе несколько, и весь экран работает с одним: `runId` уезжает
 * параметром `run` в каждый запрос и в задание прогона. Без него страница
 * второго решения показывала бы ход первого — с его условием, его блоками и
 * его историей версий.
 *
 * Сверху шаги стадий, слева работа (условие → блоки), справа история версий
 * списка, а после первой сборки — ещё и «как будет в Word». Порядок не
 * декоративный, он повторяет порядок решений: сначала подтвердить условие,
 * потом смотреть на блоки, и только потом — на вёрстку. Вёрстки до сборки не
 * существует, поэтому и вкладки с ней до неё нет.
 *
 *     Три вещи, которые здесь неочевидны
 *     ----------------------------------
 *
 * **Между условием и решением стоит шаг.** «Всё верно» — это не кнопка
 * вежливости: ошибка распознавания в одной формуле даёт безупречно решённую
 * чужую задачу. Пока условие не подтверждено,
 * прогон не запускается вовсе.
 *
 * **Ход стадий склеивается из снимка и потока.** Снимок (`GET …/kadai`) знает
 * все семь состояний, но устаревает; события `stage` приезжают по ходу.
 * Опрашивать снимок раз в секунду значило бы гнать запрос ради того, что уже
 * приехало (см. `stages.mergeStages`).
 *
 * **«Как будет в Word» — это стадия «сборка», а не задание `build`.** Задание
 * `build` собирает документ по шаблону и манифесту, а у работы `kadai` шаблона
 * нет вовсе: она — список блоков. Собрать её умеет только сценарий, и его
 * `сборка` кладёт DOCX и PDF артефактами; идентификаторы их приезжают в снимке
 * полем `made`.
 *
 * Тостов здесь нет: провал задания тостит оболочка по коду из уведомления, а
 * беда остаётся на экране строкой.
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'

import { errorText, keys } from '@/api'
import { useDocumentCrumb } from '@/app/shell/breadcrumbs'
import { useT } from '@/i18n'
import { Button, ErrorState, Icon, Segmented, SkeletonLines } from '@/ui'
import {
  artifactUrl,
  useMaterials,
  usePendingMaterials,
  useProject,
} from '@/features/projects/data'
import { useDefaultEndpoint, useProviders } from '@/features/reports/data'
import { PdfPreview } from '@/features/reports/PdfPreview'
import type { BuildState } from '@/features/reports/useBuild'
import { ModelPicker } from '@/features/reports/runControls'

import { BlockList, type ReworkRequest } from './BlockList'
import { BlockVersions } from './BlockVersions'
import { ConditionStep } from './ConditionStep'
import { ContextFiles } from './ContextFiles'
import { StageStrip } from './StageStrip'
import { WishesBox } from './WishesBox'
import {
  useBlocks,
  useContextMaterials,
  useKadaiRuns,
  useKadaiStatus,
  useKadaiWishes,
  useRestartKadai,
  useSetCondition,
  useSetKadaiWishes,
  useStageNames,
} from './data'
import { запомненный } from './preset'
import { STUMBLED, currentStage, mergeStages, reached, ПУСТЫЕ_ПОЖЕЛАНИЯ } from './stages'
import { KADAI_RUN } from './types'
import { useKadaiRun } from './useKadaiRun'

/** Стадия, после которой готовы DOCX и PDF. Дальше только ZIP. */
const СБОРКА = 'сборка'

/** Сколько раз перечитывать опись в ожидании разбора условия (полторы минуты). */
const ОПРОСОВ = 60

export function KadaiWorkPage() {
  const t = useT()
  const { projectId = '', runId = '' } = useParams()
  const project = useProject(projectId)
  // Список решений спрашивается ради имени в заголовке — и ради переезда
  // старых работ: первое решение перебирается из корня работы в свой каталог
  // именно на чтении списка, и без него открытое по прямой ссылке решение
  // показало бы пустой ход стадий у работы, которая давно решена.
  const runs = useKadaiRuns(projectId)
  // Ход стадий и блоки спрашиваются ПОСЛЕ списка решений, а не вместе с ним:
  // переезд старой работы в каталоги решений делает именно список, и запрос,
  // обогнавший его, прочитал бы пустой каталог и показал бы решённую работу
  // незапускавшейся.
  const развели = runs.isSuccess || runs.isError
  const status = useKadaiStatus(развели ? projectId : undefined, runId)
  const stageNames = useStageNames()
  const blocks = useBlocks(развели ? projectId : undefined, runId)
  // Опись папки контекста решения, а не всей работы: условие лежит в ней, и
  // искать его среди общих файлов работы значило бы принять за условие чужой
  // файл.
  const свои = useContextMaterials(projectId, runId)
  const materials = useMaterials(projectId)
  const ждущие = usePendingMaterials(projectId)
  const providers = useProviders()
  const setCondition = useSetCondition()
  const wishes = useKadaiWishes(projectId, runId)
  const saveWishes = useSetKadaiWishes()
  const restart = useRestartKadai(projectId, runId)

  const решение = (runs.data ?? []).find((з) => з.id === runId)
  const заголовок = решение
    ? решение.name || t('kadai.home.runName', { n: решение.n })
    : (project.data?.name ?? t('kadai.work.title'))

  useDocumentCrumb(заголовок)

  const [endpoint, setEndpoint] = useState<string | null>(null)
  // Умолчание пресета: выбор человека из профиля, иначе правило сайта.
  const умолчание = useDefaultEndpoint()
  const [confirmed, setConfirmed] = useState(false)
  const [вкладка, setВкладка] = useState<'preview' | 'versions'>('preview')
  const пресет = endpoint ?? запомненный(runId) ?? умолчание

  const run = useKadaiRun(projectId, пресет, runId)
  const стадии = useMemo(
    () => mergeStages(stageNames.data ?? [], status.data?.stages, run.stageEvents),
    [stageNames.data, status.data?.stages, run.stageEvents],
  )

  // Материал-условие: назван проектом (снимок) или, пока не назван, первый в
  // описи — его же и назовёт кнопка «всё верно».
  const ид_условия = status.data?.condition?.material
  const условие = useMemo(() => {
    const папка = свои.data ?? []
    const опись = materials.data ?? []
    return (
      папка.find((m) => m.id === ид_условия) ?? опись.find((m) => m.id === ид_условия) ?? папка[0]
    )
  }, [свои.data, materials.data, ид_условия])

  // Работа, у которой уже есть стадии, условие переживает перезагрузку: спорить
  // с ней вопросом «всё верно?» второй раз незачем.
  useEffect(() => {
    if (reached(стадии, 'разбор задания')) setConfirmed(true)
  }, [стадии])

  // Пока разбор не кончился, опись перечитывается: файл принят `202`, а
  // разбирает его очередь (`parse`), и материала в момент открытия экрана ещё
  // нет. Без этого страница навсегда показывает «условие не приложено» — при
  // том, что оно приложено и разбирается прямо сейчас. Ждать только условия
  // мало: файлы контекста ложатся в папку следом за ним и разбираются дольше,
  // а опрос, остановленный на условии, оставил бы папку без них до перезагрузки
  // страницы. Опрос ограничен по числу шагов: у проекта без единого файла ждать
  // нечего, и вечный запрос раз в полторы секунды был бы дороже пустого экрана.
  const qc = useQueryClient()
  const шагов = useRef(0)
  const разбирается = (ждущие.data ?? []).length > 0
  useEffect(() => {
    if ((условие && !разбирается) || шагов.current > ОПРОСОВ) return
    const таймер = setInterval(() => {
      шагов.current += 1
      void qc.invalidateQueries({ queryKey: keys.kadai.context(projectId, runId) })
      // Общие файлы работы гасятся тем же шагом: файл, приложенный ко всей
      // работе, разбирается той же очередью и до её конца в списке не значится.
      void qc.invalidateQueries({ queryKey: keys.kadai.common(projectId, runId) })
      void qc.invalidateQueries({ queryKey: keys.projects.materials(projectId) })
      void qc.invalidateQueries({ queryKey: keys.projects.pending(projectId) })
    }, 1500)
    return () => clearInterval(таймер)
  }, [условие, разбирается, projectId, runId, qc])

  const работа_заведена = !!status.data?.work
  const остановка = status.data?.hold ?? null
  const споткнулась = стадии.some((s) => s.state === STUMBLED)
  // Работа, которая уже споткнулась, повторным прогоном не чинится: сценарий
  // проходит стадии, только пока работа `running` (`kadai.run.run`), а
  // споткнувшаяся — `failed`. Второе нажатие «продолжить» стоило бы цены
  // задания и не сделало бы ничего. Возвращает её в ход «начать заново»
  // (`POST …/kadai/restart`) — бесплатно и без модели.
  const встала = споткнулась || status.data?.state === 'failed'

  function запустить(until: string | null) {
    if (!условие) return
    const пуск = () =>
      run.start({
        until,
        stages: stageNames.data ?? [],
        wishes: wishes.data ?? ПУСТЫЕ_ПОЖЕЛАНИЯ,
        first: !работа_заведена,
      })
    // Условие называется прямо перед прогоном, если проект ещё не знает своего:
    // до этого прогон отказал бы «условие задачи не приложено».
    if (ид_условия) {
      пуск()
      return
    }
    setCondition.mutate({ projectId, materialId: условие.id, runId }, { onSuccess: пуск })
  }

  function замечание({ block, kind, note }: ReworkRequest) {
    run.rework({ block, kind, note })
  }

  // «Начать заново»: сброс стадии ничего не стоит и модель не зовёт, а вот
  // прогон после него — обычное платное задание. Оба шага делаются одним
  // нажатием намеренно: разорванные, они оставили бы работу в состоянии
  // «сброшена, но никуда не идёт», и человек решал бы, что кнопка не сработала.
  function начать_заново() {
    restart.mutate(undefined, { onSuccess: () => запустить(null) })
  }

  if (project.isError) return <ErrorState error={project.error} onRetry={() => project.refetch()} />

  const собрано = status.data?.made ?? {}
  // Собиралась ли работа хоть раз: до этого превью показывать нечего.
  const собиралась = !!собрано.docx || !!собрано.pdf
  const build: BuildState = {
    running: run.running && run.kind === KADAI_RUN,
    artifacts: { docx: собрано.docx, pdf: собрано.pdf },
    pdfUrl: собрано.pdf ? artifactUrl(projectId, собрано.pdf) : null,
    // Просмотрщику нужен тот же адрес с `?inline=1`: без него служба отдаёт
    // файл вложением, и `<embed>` не рисует его, а скачивает (`PdfPreview`).
    pdfInlineUrl: собрано.pdf ? artifactUrl(projectId, собрано.pdf, { inline: true }) : null,
    docxUrl: собрано.docx ? artifactUrl(projectId, собрано.docx) : null,
    error: run.error,
    unfilled: [],
    start: () => запустить(СБОРКА),
  }

  return (
    <div className="flex min-h-0 flex-col gap-s4">
      <header className="flex flex-wrap items-end justify-between gap-s3">
        <div className="min-w-0">
          <h1 className="truncate font-display text-2xl font-semibold text-ink-strong">
            {заголовок}
          </h1>
          <p className="text-sm text-muted">
            {t('kadai.work.inWork', { work: project.data?.name ?? '' })}
          </p>
        </div>
        <Button variant="ghost" asChild>
          <Link to={`/kadai/${projectId}`}>
            <Icon name="arrowLeft" size={15} />
            {t('kadai.work.toList')}
          </Link>
        </Button>
      </header>

      {stageNames.isPending || status.isPending ? (
        <SkeletonLines count={3} />
      ) : (
        <StageStrip stages={стадии} running={run.running} note={run.note} />
      )}

      {/* Архив стадии «архив». Кнопка появляется только когда он есть: стадия
          кладёт ZIP артефактом (`orchestrator.kadai._положить_архив`), и до неё
          скачивать нечего. Ссылка ведёт на адрес артефакта — тот же, по
          которому приезжают DOCX и PDF. */}
      {собрано.archive && (
        <p className="flex flex-wrap items-center gap-s2 rounded-md border border-line bg-surface-2 px-s3 py-s2 text-sm text-ink">
          <Icon name="download" size={15} className="text-muted" />
          {t('kadai.archive.ready')}
          <Button variant="secondary" size="sm" className="ml-auto" asChild>
            <a href={artifactUrl(projectId, собрано.archive)} download>
              {t('kadai.archive.download')}
            </a>
          </Button>
        </p>
      )}

      {остановка && (
        <p className="flex flex-wrap items-center gap-s2 rounded-md border border-warn bg-warn-bg px-s3 py-s2 text-sm text-ink">
          <Icon name="info" size={15} className="text-warn" />
          {t('kadai.run.holdFor', { what: остановка.show })}
          {остановка.note ? ` — ${остановка.note}` : ''}
          <Button
            variant="secondary"
            size="sm"
            className="ml-auto"
            disabled={run.running || встала}
            onClick={() => запустить(null)}
          >
            {t('kadai.run.continue')}
          </Button>
        </p>
      )}

      {(run.error || встала) && (
        <section className="flex flex-col gap-s2 rounded-md border border-err bg-err-bg px-s3 py-s2 text-sm">
          <p className="text-err">
            {run.error ?? заметка_споткнувшейся(стадии) ?? t('kadai.run.stumbled')}
          </p>
          {встала && (
            <>
              <p className="text-xs text-ink">{t('kadai.run.restartHint')}</p>
              <div className="flex flex-wrap items-center gap-s2">
                <Button
                  variant="secondary"
                  size="sm"
                  className="ml-auto"
                  disabled={run.running || !пресет}
                  loading={restart.isPending}
                  onClick={начать_заново}
                >
                  {t('kadai.run.restart')}
                </Button>
              </div>
              {restart.isError && <p className="text-xs text-err">{errorText(restart.error)}</p>}
            </>
          )}
        </section>
      )}

      <div className="grid min-h-0 gap-s4 xl:grid-cols-[minmax(0,1fr)_minmax(380px,0.85fr)]">
        <div className="flex min-w-0 flex-col gap-s3">
          <ConditionStep
            projectId={projectId}
            runId={runId}
            material={условие}
            ocr={!!status.data?.condition?.ocr}
            confirmed={confirmed}
            onConfirm={() => setConfirmed(true)}
            disabled={run.running}
          />

          <section className="flex flex-col gap-s2 rounded-md border border-line bg-surface p-s3 shadow-1">
            <div className="flex flex-wrap items-center gap-s3">
              <ModelPicker
                providers={providers.data}
                value={пресет}
                onChange={setEndpoint}
                disabled={run.running}
              />
              <Button
                variant="primary"
                size="sm"
                className="ml-auto"
                disabled={!confirmed || !условие || !пресет || встала}
                loading={run.running}
                onClick={() => запустить(null)}
              >
                {работа_заведена ? t('kadai.run.again') : t('kadai.run.start')}
              </Button>
            </div>
            {!confirmed && <p className="text-xs text-muted">{t('kadai.run.confirmFirst')}</p>}
            {run.running && currentStage(стадии) && (
              <p className="text-xs text-muted">
                {t('kadai.run.now', { stage: currentStage(стадии) ?? '' })}
              </p>
            )}
          </section>

          <WishesBox
            wishes={wishes.data}
            loading={wishes.isPending}
            saving={saveWishes.isPending}
            error={saveWishes.error}
            started={работа_заведена}
            disabled={run.running}
            onSave={(это) => saveWishes.mutate({ projectId, runId, wishes: это })}
          />

          {/* Папка контекста этого решения и общие файлы работы с галочками.
              В промпт уезжают файлы папки, условие и те общие файлы, с которых
              галочку не сняли: файл соседней задачи сбивает модель так же, как
              чужое условие, а методичка работы нужна каждой её задаче. */}
          <ContextFiles
            projectId={projectId}
            runId={runId}
            conditionId={ид_условия}
            disabled={run.running}
          />

          <h2 className="text-sm font-semibold text-ink-strong">{t('kadai.blocks.title')}</h2>
          <BlockList
            blocks={blocks.data}
            loading={blocks.isPending}
            disabled={run.running}
            onRework={замечание}
          />
        </div>

        <div className="flex min-h-0 min-w-0 flex-col gap-s2">
          {/* Превью «как будет в Word» появляется только после первой сборки.
              До неё показывать нечего: работа собирается стадией «Сборка», и
              пустая рамка с кнопкой выглядела как ожидание того, чего в проекте
              ещё нет. */}
          {собиралась && (
            <Segmented
              value={вкладка}
              onChange={(v) => setВкладка(v as 'preview' | 'versions')}
              options={[
                { value: 'preview', label: t('kadai.tabs.preview') },
                { value: 'versions', label: t('kadai.tabs.versions') },
              ]}
            />
          )}
          {собиралась && вкладка === 'preview' ? (
            <div className="min-h-[520px] overflow-hidden rounded-md border border-line">
              <PdfPreview build={build} canBuild={!!пресет && !!условие && confirmed} />
            </div>
          ) : (
            <div className="rounded-md border border-line bg-surface p-s3">
              <BlockVersions
                projectId={projectId}
                runId={runId}
                blocks={blocks.data}
                canEdit={!run.running}
              />
            </div>
          )}
          {status.data && status.data.problems.length > 0 && (
            <ul className="flex flex-col gap-1 rounded-md border border-line bg-surface-2 p-s3 text-xs text-ink">
              {status.data.problems.slice(0, 8).map((p, i) => (
                <li key={i} className={p.level === 'error' ? 'text-err' : 'text-muted'}>
                  {p.message}
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  )
}

/** Заметка споткнувшейся стадии: она уже написана для человека. */
function заметка_споткнувшейся(стадии: { state: string; note?: string | null }[]): string | null {
  const беда = стадии.find((s) => s.state === STUMBLED)
  return беда?.note || null
}
