/**
 * KadaiWorkPage — экран одного прогона: `/kadai/:projectId/:runId`.
 *
 * Экран стоит в двух модулях сразу. В «Решениях» это решение задачи и кончается
 * оно архивом; в «Отчётах» тот же прогон — отчёт из задания
 * (`/reports/:projectId/live/:runId`): он останавливается на сборке, стадии
 * «Архив» в полоске шагов нет, а вместо архива из готовых блоков делается бланк
 * с тегами. Слова, адреса и эта разница приезжают пропом `scope` (`./module`).
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
 * **Блок выбирают на вёрстке, а список — оглавление к ней.** Собранная
 * страница показывает блоки там, где они на самом деле стоят, и замечание
 * пишется прямо по ним (`PdfBlocks`); список слева ведёт к блоку и показывает
 * то, чего в вёрстке не видно, — черновики и заготовки, пропущенные сборкой.
 * Выбранный блок у них общий, поэтому он и живёт здесь, а не в каждом своим.
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
 * **Действие на экране всегда одно.** Прогон идёт — «Остановить»; работа ждёт
 * слова человека — «Продолжить» в плашке ожидания; работа встала — «Начать
 * заново» в строке беды. Две кнопки с одинаковой подписью в разных углах — это
 * не выбор, а вопрос «какая из них та», и отвечать на него человек будет
 * нажатием наугад, стоящим цены задания.
 *
 * Тостов здесь нет: провал задания тостит оболочка по коду из уведомления, а
 * беда остаётся на экране строкой.
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'

import { errorSaid, keys } from '@/api'
import { useDocumentCrumb } from '@/app/shell/breadcrumbs'
import { useT } from '@/i18n'
import { withBase } from '@/lib/basePath'
import { cn } from '@/lib/cn'
import { Button, ErrorState, Icon, Segmented, SkeletonLines, useToast } from '@/ui'
import {
  artifactUrl,
  useMaterials,
  usePendingMaterials,
  useProject,
} from '@/features/projects/data'
import { useDefaultEndpoint, useMakeKadaiTemplate, useProviders } from '@/features/reports/data'
import type { BuildState } from '@/features/reports/useBuild'
import { ModelPicker } from '@/features/reports/runControls'

import { BlockList, type ReworkRequest } from './BlockList'
import { BlockVersions } from './BlockVersions'
import { ConditionStep } from './ConditionStep'
import { ContextFiles } from './ContextFiles'
import { PdfBlocks } from './PdfBlocks'
import { StageStrip } from './StageStrip'
import { WishesBox } from './WishesBox'
import { РЕШЕНИЕ, type KadaiScope, type KadaiTemplateWords } from './module'
import {
  useBlocks,
  useContextMaterials,
  useKadaiRuns,
  useKadaiStatus,
  useKadaiWishes,
  useRestartKadai,
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

export function KadaiWorkPage({ scope = РЕШЕНИЕ }: { scope?: KadaiScope }) {
  const t = useT()
  const слова = scope.words
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
  // Опись папки контекста решения, а не всей работы: в ней лежит условие и всё,
  // что человек приложил к этой задаче, и из неё же условие выбирают, пока оно
  // не названо.
  const свои = useContextMaterials(projectId, runId)
  const materials = useMaterials(projectId)
  const ждущие = usePendingMaterials(projectId)
  const providers = useProviders()
  const wishes = useKadaiWishes(projectId, runId)
  const saveWishes = useSetKadaiWishes()
  const restart = useRestartKadai(projectId, runId)

  const решение = (runs.data ?? []).find((з) => з.id === runId)
  const заголовок = решение
    ? решение.name || t(слова.runName, { n: решение.n })
    : (project.data?.name ?? t('kadai.work.title'))

  useDocumentCrumb(заголовок)

  const [endpoint, setEndpoint] = useState<string | null>(null)
  // Умолчание пресета: выбор человека из профиля, иначе правило сайта.
  const умолчание = useDefaultEndpoint()
  const [confirmed, setConfirmed] = useState(false)
  const [вкладка, setВкладка] = useState<'preview' | 'versions'>('preview')
  // Развёрнутое превью: вёрстка во всю ширину экрана, список блоков — под ней.
  // Правая колонка узка по делу (слева работают, справа сверяют), но сверять
  // вёрстку по колонке в четверть страницы нельзя: поля и переносы — это как
  // раз то, что в узком столбце не видно.
  const [развёрнуто, setРазвёрнуто] = useState(false)
  // Выбранный блок один на весь экран: карточка списка и область на странице
  // вёрстки — два вида одного и того же выбора, и своё «выбрано» у каждого
  // разъехалось бы на первом же клике. Отсюда же счётчик просьб прокрутить
  // вёрстку: клик по карточке ведёт к блоку на странице, а не только красит её.
  const [выбран, setВыбран] = useState<string | null>(null)
  const [к_блоку, setКБлоку] = useState(0)
  // Какие блоки нашлись в собранной вёрстке. У них форма замечания стоит под
  // страницей, а не в карточке; у остальных (работа ещё не собиралась,
  // заготовку пропустили) — по-прежнему в карточке.
  const [в_вёрстке, setВВёрстке] = useState<ReadonlySet<string>>(() => new Set())
  const пресет = endpoint ?? запомненный(runId) ?? умолчание

  const run = useKadaiRun(projectId, пресет, runId)
  // Стадии, которых модуль не обещает, отсеиваются здесь, а не в полоске: по
  // этому же списку считается «работа встала» и «что идёт сейчас», и стадия,
  // убранная только с картинки, оставляла бы экран в вечном ожидании.
  const стадии = useMemo(
    () =>
      mergeStages(stageNames.data ?? [], status.data?.stages, run.stageEvents).filter(
        (стадия) => !scope.skip.includes(стадия.name),
      ),
    [stageNames.data, status.data?.stages, run.stageEvents, scope.skip],
  )

  // Материал-условие — ровно тот, который назван условием у службы
  // (`Project.condition`): снимок знает его и до первого прогона, и сразу после
  // правки. Первый файл папки за условие не сходит — «первым» там оказывается
  // то скан, то методичка, то прежняя версия условия, и человек платил бы за
  // решение задачи, которую не выбирал. Не названо — шаг условия предложит
  // выбрать файл из папки.
  //
  // Ищется он в папке решения, а потом в описи работы: условием бывает назван и
  // общий файл работы, и в папке решения его тогда нет.
  const ид_условия = status.data?.condition?.material
  const прежние_условия = status.data?.condition_past
  const условие = useMemo(() => {
    const папка = свои.data ?? []
    const опись = materials.data ?? []
    return папка.find((m) => m.id === ид_условия) ?? опись.find((m) => m.id === ид_условия)
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

  // Условие к этой минуте уже названо: без него прогон не запускается вовсе
  // (кнопка выключена, а сценарий отказал бы «условие задачи не приложено»).
  // Называть его отсюда, за человека, экран не берётся — какой файл считать
  // условием, решает он на своём шаге.
  function запустить(until: string | null) {
    if (!условие) return
    run.start({
      until,
      stages: stageNames.data ?? [],
      wishes: wishes.data ?? ПУСТЫЕ_ПОЖЕЛАНИЯ,
      first: !работа_заведена,
    })
  }

  function замечание({ block, kind, note }: ReworkRequest) {
    run.rework({ block, kind, note })
  }

  // Выбор в списке ведёт вёрстку к блоку; выбор на странице только красит
  // карточку (страница уже там, где на неё смотрят).
  function выбрать_в_списке(ключ: string | null) {
    setВыбран(ключ)
    if (ключ) setКБлоку((было) => было + 1)
  }

  // «Начать заново»: сброс стадии ничего не стоит и модель не зовёт, а вот
  // прогон после него — обычное платное задание. Оба шага делаются одним
  // нажатием намеренно: разорванные, они оставили бы работу в состоянии
  // «сброшена, но никуда не идёт», и человек решал бы, что кнопка не сработала.
  function начать_заново() {
    restart.mutate(undefined, { onSuccess: () => запустить(scope.until) })
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
    // файл вложением, и браузер его скачивает вместо показа (`PdfBlocks`).
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
          <Link to={scope.list(projectId)}>
            <Icon name="arrowLeft" size={15} />
            {t(слова.toList)}
          </Link>
        </Button>
      </header>

      {stageNames.isPending || status.isPending ? (
        <SkeletonLines count={3} />
      ) : (
        <StageStrip
          stages={стадии}
          running={run.running}
          note={run.note}
          moves={run.moves}
          hold={остановка?.stage ?? null}
        />
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

      {/* Бланк с тегами из блоков — выход модуля «Отчёты» вместо архива.
          Стоит рядом со стадиями, а не под вёрсткой: делают его тогда же,
          когда смотрят на готовый документ. */}
      {scope.template && (
        <TemplateFromBlocks
          projectId={projectId}
          runId={runId}
          words={scope.template}
          empty={(blocks.data ?? []).length === 0}
          disabled={run.running}
        />
      )}

      {/* Работа ждёт человека. Плашка заметная и с одной крупной кнопкой
          намеренно: сценарий останавливается там, где ошибка дороже всего
          (понял ли он задание, то ли строение), и остановка эта неотличима от
          «ничего не происходит», если про неё сказано мелкой строкой. Пока
          работа ждёт, кнопки пуска в панели пресета нет вовсе: две одинаковые
          кнопки «продолжить» на одном экране — это вопрос «а какая из них
          та?», а не выбор. */}
      {остановка && (
        <section className="flex flex-col gap-s2 rounded-md border border-warn bg-warn-bg p-s3">
          <p className="flex items-center gap-s2 text-sm font-semibold text-ink-strong">
            <Icon name="info" size={16} className="shrink-0 text-warn" />
            {t('kadai.run.holdFor', { what: остановка.show })}
          </p>
          <p className="text-sm text-ink">{остановка.note || t('kadai.run.holdWhat')}</p>
          <div className="flex flex-wrap items-center gap-s3">
            <Button
              variant="primary"
              disabled={run.running || встала || !пресет || !условие}
              loading={run.running}
              onClick={() => запустить(scope.until)}
            >
              {t('kadai.run.continue')}
            </Button>
            <span className="text-xs text-ink">{t('kadai.run.holdHint')}</span>
          </div>
        </section>
      )}

      {/* Прогон остановлен человеком. Не беда и не итог: работа стоит там, где
          её застали, всё сделанное до этого хода лежит на томе, и следующий
          прогон продолжит с той же стадии. Сказать это надо словами — иначе
          замерший экран читается как поломка. */}
      {run.stopped && !run.running && (
        <p className="flex flex-wrap items-center gap-s2 rounded-md border border-line bg-surface-2 px-s3 py-s2 text-sm text-ink">
          <Icon name="info" size={15} className="shrink-0 text-muted" />
          {t(слова.stopped)}
        </p>
      )}

      {(run.error || встала) && (
        <section className="flex flex-col gap-s2 rounded-md border border-err bg-err-bg px-s3 py-s2 text-sm">
          <p className="text-err">
            {run.error ?? заметка_споткнувшейся(стадии) ?? t('kadai.run.stumbled')}
          </p>
          {/* Сырьё от службы — под раскрывашкой, а не строкой. Приезжает оно
              редко и означает, что беду не успели назвать словами: `repr`
              исключения, JSON поставщика, вывод чужой программы. Выбросить его
              нельзя (в жалобе это единственная зацепка), а поставить на экран
              строкой — значит занять место тем, с чем человеку нечего делать. */}
          {run.errorRaw && (
            <details className="text-xs">
              <summary className="cursor-pointer text-muted focus-visible:outline focus-visible:-outline-offset-2 focus-visible:outline-accent">
                {t('kadai.run.details')}
              </summary>
              <pre className="mt-s2 max-h-[180px] overflow-auto whitespace-pre-wrap rounded-sm border border-line bg-surface-2 p-s2 font-mono text-ink">
                {run.errorRaw}
              </pre>
            </details>
          )}
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
              {/* `errorSaid`, а не `errorText`: сброс стадии отказывает тем же
                  кодом, что и прогон, и причину («стадии такой нет», «работа
                  ещё не заведена») служба пишет по-русски сама. */}
              {restart.isError && (
                <p className="text-xs text-err">{errorSaid(restart.error).text}</p>
              )}
            </>
          )}
        </section>
      )}

      {/* Две колонки: слева работают, справа сверяют. Разворот выключает
          вторую колонку и ставит вёрстку первой во всю ширину — список блоков
          уходит под неё. Порядком, а не отдельной страницей: работа со списком
          и сверка вёрстки — это один и тот же разговор с одной работой, и
          переход между ними не должен стоить перезагрузки экрана.

          Узкий экран колонок не разводит вовсе (`xl:`), и там вёрстка стоит под
          списком всегда: колонка в половину телефона — не превью. */}
      <div
        className={cn(
          'grid min-h-0 gap-s4',
          !развёрнуто && 'xl:grid-cols-[minmax(0,1fr)_minmax(420px,0.9fr)]',
        )}
      >
        <div className={cn('flex min-w-0 flex-col gap-s3', развёрнуто && 'order-2')}>
          <ConditionStep
            projectId={projectId}
            runId={runId}
            material={условие}
            named={!!ид_условия}
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
              {/* Пока работа ждёт человека, крупная кнопка «Продолжить» стоит
                  в плашке ожидания и она одна на экране: вторая, такая же, но
                  здесь, — это не выбор, а загадка. */}
              {!остановка && (
                <Button
                  variant="primary"
                  size="sm"
                  className="ml-auto"
                  disabled={!confirmed || !условие || !пресет || встала}
                  loading={run.running}
                  onClick={() => запустить(scope.until)}
                >
                  {работа_заведена ? t(слова.again) : t(слова.start)}
                </Button>
              )}
              {/* Остановка — просьба, а не выключатель: ждущее задание служба
                  снимает сразу, идущее останавливается на ближайшей проверке, и
                  всё, что успело лечь на том, там и останется. */}
              {run.running && (
                <Button
                  variant="secondary"
                  size="sm"
                  className={остановка ? 'ml-auto' : undefined}
                  loading={run.stopping}
                  onClick={run.stop}
                >
                  <Icon name="close" size={14} />
                  {t('kadai.run.stop')}
                </Button>
              )}
            </div>
            {!confirmed && <p className="text-xs text-muted">{t('kadai.run.confirmFirst')}</p>}
            {остановка && !run.running && (
              <p className="text-xs text-warn">{t('kadai.run.holdAbove')}</p>
            )}
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
              В промпт уезжают файлы папки, условие и те общие файлы работы,
              которые к решению подключили: файл соседней задачи сбивает модель
              так же, как чужое условие, и платит за это человек. Прежние
              версии условия помечены и модели не показываются. */}
          <ContextFiles
            projectId={projectId}
            runId={runId}
            conditionId={ид_условия}
            pastIds={прежние_условия}
            disabled={run.running}
          />

          {/* Пояснение над списком, а не подсказкой по наведению: «блок» — это
              слово продукта, и человек, впервые открывший решение, видит
              двадцать карточек, про которые непонятно ни что это, ни что с
              ними делать. Три строки отвечают ровно на три вопроса: что это,
              кто это написал, что будет от нажатия. */}
          <div className="flex flex-col gap-1">
            <h2 className="text-sm font-semibold text-ink-strong">{t('kadai.blocks.title')}</h2>
            <p className="text-xs text-muted">{t('kadai.blocks.about')}</p>
          </div>
          <BlockList
            blocks={blocks.data}
            loading={blocks.isPending}
            disabled={run.running}
            selected={выбран}
            onSelect={выбрать_в_списке}
            pickable={в_вёрстке}
            onRework={замечание}
          />
        </div>

        <div className={cn('flex min-h-0 min-w-0 flex-col gap-s2', развёрнуто && 'order-1')}>
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
            // Высота — в долях экрана, а не в пикселях: страница A4 в рамке
            // высотой в треть экрана показывает не вёрстку, а её кусок, и
            // ошибку переноса в такой рамке не увидеть. Развёрнутая рамка выше
            // ещё на десятую: колонки рядом уже нет, и место есть.
            <div
              className={cn(
                'overflow-hidden rounded-md border border-line',
                развёрнуто ? 'min-h-[85vh]' : 'min-h-[75vh]',
              )}
            >
              <PdfBlocks
                build={build}
                canBuild={!!пресет && !!условие && confirmed}
                blocks={blocks.data}
                selected={выбран}
                scrollAt={к_блоку}
                onSelect={setВыбран}
                onPickable={setВВёрстке}
                onRework={замечание}
                disabled={run.running}
                extra={
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => setРазвёрнуто((было) => !было)}
                    aria-pressed={развёрнуто}
                  >
                    <Icon name={развёрнуто ? 'panelOpen' : 'panelClose'} size={14} />
                    {t(развёрнуто ? 'kadai.preview.collapse' : 'kadai.preview.expand')}
                  </Button>
                }
              />
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

/**
 * Бланк с тегами из блоков прогона: кнопка и то, что осталось после неё.
 *
 * Бланк — обычный `.docx` с тегами `{{ключ:метка}}`, то есть вход в тот же
 * шаблонный путь, которым собирается любой отчёт работы: написанное один раз
 * строение переиспользуется дальше без модели.
 *
 * Ссылки на файл и на полку стоят строкой на экране, а не только в тосте: тост
 * уходит через шесть секунд, и ссылка, которую не успели нажать, вернулась бы
 * только повторным заданием — а оно кладёт на полку второй бланк.
 *
 * Пустой список блоков служба отвергает («собирать нечего»), поэтому кнопка
 * до первого строения выключена: платить отказом за нажатие незачем.
 */
function TemplateFromBlocks({
  projectId,
  runId,
  words,
  empty,
  disabled,
}: {
  projectId: string
  runId: string
  words: KadaiTemplateWords
  /** Блоков ещё нет: делать бланк не из чего. */
  empty: boolean
  disabled: boolean
}) {
  const t = useT()
  const toast = useToast()
  const бланк = useMakeKadaiTemplate(projectId, runId)
  const готов = бланк.data ?? null

  return (
    <section className="flex flex-wrap items-center gap-s2 rounded-md border border-line bg-surface-2 px-s3 py-s2 text-sm text-ink">
      <Icon name="file" size={15} className="shrink-0 text-muted" />
      <span className="min-w-0">{готов ? t(words.done, { name: готов.name }) : t(words.hint)}</span>
      {готов && (
        <>
          <Button variant="ghost" size="sm" asChild>
            <a href={withBase(готов.blob)} download>
              <Icon name="download" size={14} />
              {t(words.download)}
            </a>
          </Button>
          <Button variant="ghost" size="sm" asChild>
            <Link to="/settings/templates">{t(words.shelf)}</Link>
          </Button>
        </>
      )}
      <Button
        variant="secondary"
        size="sm"
        className="ml-auto"
        disabled={disabled || empty}
        loading={бланк.isPending}
        onClick={() =>
          бланк.mutate(undefined, {
            onSuccess: (это) => toast.success(t(words.toast), это.name),
            onError: (беда) => toast.fail(беда),
          })
        }
      >
        {t(words.make)}
      </Button>
    </section>
  )
}

/** Заметка споткнувшейся стадии: она уже написана для человека. */
function заметка_споткнувшейся(стадии: { state: string; note?: string | null }[]): string | null {
  const беда = стадии.find((s) => s.state === STUMBLED)
  return беда?.note || null
}
