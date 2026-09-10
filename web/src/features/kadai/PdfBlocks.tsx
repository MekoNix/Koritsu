/**
 * PdfBlocks — «как будет в Word» и выбор блока прямо на странице.
 *
 * Превью работы — это не картинка рядом со списком, а место, где с работой
 * разговаривают: человек видит вёрстку, наводит на кусок, который ему не
 * нравится, и пишет замечание тут же. Адрес замечания при этом остаётся тем же
 * ключом блока, что и в списке, и уезжает тем же `kadai_rework`.
 *
 *     Почему свой просмотрщик, а не `<embed>`
 *     ---------------------------------------
 *
 * Встроенный просмотрщик браузера не отдаёт наружу ни координат, ни кликов, ни
 * прокрутки: наложить на него слой областей нельзя в принципе. Поэтому здесь
 * pdf.js — но не свой рендер страниц, а готовый компонент `PDFViewer`: страницы,
 * ленивая отрисовка по видимости и масштаб — его работа, наша — слой областей
 * поверх. Отчётам этого не нужно, и их `reports/PdfPreview` остаётся на
 * `<embed>`: мегабайт кода ради страницы, которую браузер и так рисует, там
 * ничего не покупает.
 *
 * Грузится pdf.js лениво (`import()` в эффекте) и отдельным куском сборки:
 * ядро с просмотрщиком весит около двух мегабайт, и платить за них должен тот
 * экран, который их показывает, а не вход на сайт.
 *
 *     Откуда берутся области
 *     ----------------------
 *
 * При сборке на первый абзац каждого блока ставится закладка, и в PDF она
 * выходит именованным назначением (`pdfBlocks.keyOfBookmark`). Назначение —
 * точка; область блока считается до начала следующего блока (`blockAreas`).
 * Своего разбора текста здесь нет и быть не должно: сопоставление по словам
 * ломается на таблицах, схемах и одинаковых заголовках, и ломается молча.
 *
 * **Слой живёт в долях страницы, а не в пикселях.** Масштаб просмотрщика
 * человек меняет постоянно, и пересчитывать при этом область каждого блока
 * значило бы пересчитывать её сотни раз за сеанс. Меряется только рамка каждой
 * страницы (`pagerendered`, `scalechanging`), а место блока внутри страницы
 * посчитано один раз.
 *
 * **Слой висит внутри полотна просмотрщика, а не поверх окна.** Полотно
 * прокручивается вместе со страницами, и слой внутри него о прокрутке не знает
 * вовсе; слой поверх окна пришлось бы двигать на каждый кадр прокрутки.
 * Собственным узлом, а не разметкой React: полотно принадлежит pdf.js, и он
 * вправе вычистить оттуда всё при смене документа.
 *
 *     Когда областей нет
 *     ------------------
 *
 * Работы, собранные прежде, назначений блоков не несут, и просмотрщик с
 * областями им ничего не даёт. Тогда — прежний `<embed>` и строка о том, что
 * выбирать блоки на странице можно после пересборки. Тем же путём уходит и
 * беда pdf.js: показать вёрстку важнее, чем показать её нашими руками.
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import type { ReactNode } from 'react'
import type { PDFDocumentProxy } from 'pdfjs-dist'
import type { PDFLinkService, PDFViewer } from 'pdfjs-dist/web/pdf_viewer.mjs'

// Рабочий поток pdf.js — отдельным файлом рядом со сборкой, а не строкой с
// чужого CDN: сайт живёт без выхода наружу, и адрес, которого нет, разбор PDF
// просто не начинает.
import workerSrc from 'pdfjs-dist/build/pdf.worker.min.mjs?url'

import { useT } from '@/i18n'
import { cn } from '@/lib/cn'
import { Button, EmptyState, Icon, Spinner } from '@/ui'
import type { BuildState } from '@/features/reports/useBuild'

import { ReworkForm, type ReworkRequest } from './BlockList'
import { blockAreas, bookmarkName, destY, keyOfBookmark, type Anchor, type Area } from './pdfBlocks'
import { blockText, черновик, ВИД } from './stages'
import type { BlockRecordBody } from './types'

/** Масштаб «по ширине» — значение просмотрщика pdf.js. */
const ПО_ШИРИНЕ = 'page-width'

/**
 * Текстовый слой выключён (`TextLayerMode.DISABLE` просмотрщика pdf.js).
 * Своим числом, а не именем: `TextLayerMode` пакет наружу не отдаёт.
 */
const БЕЗ_ТЕКСТА = 0

/** Пределы масштаба: дальше страница либо нечитаема, либо не помещается вовсе. */
const МЕНЬШЕ = 0.25
const БОЛЬШЕ = 4
const ШАГ = 1.2

/** Рамка страницы в полотне просмотрщика — пиксели при нынешнем масштабе. */
type Короб = { left: number; top: number; width: number; height: number }

export function PdfBlocks({
  build,
  canBuild,
  extra,
  blocks,
  selected,
  scrollAt,
  onSelect,
  onPickable,
  onRework,
  disabled,
}: {
  build: BuildState
  canBuild: boolean
  /** Добавочная кнопка в шапке: у решений это «развернуть на всю ширину». */
  extra?: ReactNode
  blocks: BlockRecordBody[] | undefined
  /** Выбранный блок — общий со списком слева. */
  selected: string | null
  /**
   * Просьба прокрутить страницу к выбранному блоку — счётчик, а не флаг:
   * повторный клик по той же карточке должен прокручивать снова, а флаг
   * «прокрутить к тому же» неотличим от «уже прокрутили».
   */
  scrollAt: number
  onSelect: (ключ: string | null) => void
  /** Какие блоки нашлись в вёрстке: список слева прячет у них форму замечания. */
  onPickable: (ключи: ReadonlySet<string>) => void
  onRework: (запрос: ReworkRequest) => void
  /** Идёт прогон: форма замечания заблокирована. */
  disabled: boolean
}) {
  const t = useT()
  const url = build.pdfInlineUrl

  const корпус = useRef<HTMLDivElement>(null)
  const полотно = useRef<HTMLDivElement>(null)
  const [живой, setЖивой] = useState<{
    viewer: PDFViewer
    links: PDFLinkService
    layer: HTMLDivElement
  } | null>(null)
  const [области, setОбласти] = useState<Area[]>([])
  const [коробки, setКоробки] = useState<(Короб | null)[]>([])
  const [наведён, setНаведён] = useState<string | null>(null)
  // Беда pdf.js и «в этом PDF областей нет» — разные причины одного и того же
  // запасного пути. Второе помнится по адресу документа: пересборка кладёт
  // новый артефакт, и с ним попытку надо повторить.
  const [беда, setБеда] = useState(false)
  const [без_областей, setБезОбластей] = useState<string | null>(null)
  const запасной = беда || (!!url && без_областей === url)

  useEffect(() => {
    const корпус_эл = корпус.current
    const полотно_эл = полотно.current
    if (!url || запасной || !корпус_эл || !полотно_эл) return

    let живо = true
    let слой: HTMLDivElement | null = null
    let просмотрщик: PDFViewer | null = null
    let загрузка: { promise: Promise<PDFDocumentProxy>; destroy: () => Promise<void> } | null = null
    let кадр = 0
    const снять: (() => void)[] = []

    void (async () => {
      try {
        const [, ядро, вид] = await Promise.all([
          import('pdfjs-dist/web/pdf_viewer.css'),
          import('pdfjs-dist'),
          import('pdfjs-dist/web/pdf_viewer.mjs'),
        ])
        if (!живо) return
        ядро.GlobalWorkerOptions.workerSrc = workerSrc

        const шина = new вид.EventBus()
        // `ignoreDestinationZoom` — переход к блоку не меняет масштаб: у
        // назначения PDF в нём записано своё приближение, и страница, прыгнув к
        // блоку, заодно меняла бы размер под ногами.
        const links = new вид.PDFLinkService({ eventBus: шина, ignoreDestinationZoom: true })
        // Ни текстового слоя, ни слоя пометок: и тот и другой лежали бы под
        // нашими областями, где ни выделить текст, ни нажать ссылку всё равно
        // нельзя, — а память на сорока страницах они занимают настоящую.
        const viewer = new вид.PDFViewer({
          container: корпус_эл,
          viewer: полотно_эл,
          eventBus: шина,
          linkService: links,
          textLayerMode: БЕЗ_ТЕКСТА,
          annotationMode: ядро.AnnotationMode.DISABLE,
        })
        просмотрщик = viewer
        links.setViewer(viewer)

        // Мерить рамки страниц — работа с вёрсткой браузера, и звать её на
        // каждое событие отрисовки нельзя: страниц десятки, а событий у них по
        // нескольку на каждое изменение масштаба. Один замер на кадр.
        const перемерить = () => {
          cancelAnimationFrame(кадр)
          кадр = requestAnimationFrame(() => {
            if (!живо) return
            const короба: (Короб | null)[] = []
            for (let i = 0; i < viewer.pagesCount; i++) {
              const страница = viewer.getPageView(i) as { div?: HTMLDivElement } | undefined
              const div = страница?.div
              короба.push(
                div
                  ? {
                      // `clientLeft`/`clientTop` — рамка страницы: слой должен
                      // лечь ровно на полотно страницы, а не на её поля.
                      left: div.offsetLeft + div.clientLeft,
                      top: div.offsetTop + div.clientTop,
                      width: div.clientWidth,
                      height: div.clientHeight,
                    }
                  : null,
              )
            }
            setКоробки(короба)
          })
        }
        const на = (имя: string, что: () => void) => {
          шина.on(имя, что)
          снять.push(() => шина.off(имя, что))
        }
        на('pagesinit', () => {
          viewer.currentScaleValue = ПО_ШИРИНЕ
          перемерить()
        })
        на('pagerendered', перемерить)
        на('pagesloaded', перемерить)
        на('scalechanging', перемерить)

        // Ширина колонки меняется без всякого события pdf.js: «развернуть»,
        // поворот телефона, другое окно. «По ширине» — это не число, а правило,
        // и пересчитать его после смены ширины должен тот, кто эту ширину дал.
        const наблюдатель = new ResizeObserver(() => {
          if (!живо || viewer.pagesCount === 0) return
          const масштаб = viewer.currentScaleValue
          if (масштаб === ПО_ШИРИНЕ || масштаб === 'page-fit' || масштаб === 'auto') {
            viewer.currentScaleValue = масштаб
          }
          viewer.update()
          перемерить()
        })
        наблюдатель.observe(корпус_эл)
        снять.push(() => наблюдатель.disconnect())

        // `withCredentials` — артефакт отдаётся по cookie сессии; без него
        // просмотрщик получил бы отказ вместо документа.
        загрузка = ядро.getDocument({ url, withCredentials: true })
        const документ = await загрузка.promise
        if (!живо) return
        viewer.setDocument(документ)
        links.setDocument(документ, null)

        слой = document.createElement('div')
        слой.style.position = 'absolute'
        слой.style.inset = '0'
        // Поверх страниц, но кликов сам не ловит: ловят их только области.
        слой.style.zIndex = '5'
        слой.style.pointerEvents = 'none'
        полотно_эл.append(слой)

        const якоря = await прочитать_якоря(документ)
        if (!живо) return
        if (якоря.length === 0) {
          setБезОбластей(url)
          return
        }
        setОбласти(blockAreas(якоря, документ.numPages))
        setЖивой({ viewer, links, layer: слой })
      } catch {
        // Чем именно не понравился документ pdf.js, человеку сказать нечего:
        // вёрстку он всё равно увидит, только встроенным просмотрщиком.
        if (живо) setБеда(true)
      }
    })()

    return () => {
      живо = false
      cancelAnimationFrame(кадр)
      for (const снятие of снять) снятие()
      слой?.remove()
      setЖивой(null)
      setОбласти([])
      setКоробки([])
      просмотрщик?.setDocument(null as unknown as PDFDocumentProxy)
      void загрузка?.destroy()
    }
  }, [url, запасной])

  // Новый артефакт — новая попытка: беда прошлого документа к нему отношения
  // не имеет.
  useEffect(() => setБеда(false), [url])

  const по_ключу = useMemo(() => new Map((blocks ?? []).map((блок) => [блок.key, блок])), [blocks])
  const в_вёрстке = useMemo(() => new Set(области.map((о) => о.key)), [области])
  // Подпись показывается один раз на блок: у блока, разорванного между
  // страницами, областей две, и вторая подпись стояла бы посреди текста.
  const головные = useMemo(() => {
    const было = new Set<string>()
    return области.map((о) => {
      if (было.has(о.key)) return false
      было.add(о.key)
      return true
    })
  }, [области])

  useEffect(() => {
    onPickable(в_вёрстке)
  }, [в_вёрстке, onPickable])
  useEffect(() => () => onPickable(new Set()), [onPickable])

  // Прокрутка к блоку по просьбе списка. Номер просьбы запоминается, чтобы
  // просьба, пришедшая до того, как просмотрщик открылся, всё-таки сработала —
  // и чтобы обычная перерисовка не прокручивала страницу сама по себе.
  const прокручено = useRef(0)
  useEffect(() => {
    if (!живой || !selected || scrollAt === прокручено.current) return
    прокручено.current = scrollAt
    void живой.links.goToDestination(bookmarkName(selected))
  }, [scrollAt, selected, живой])

  function приблизить(во_сколько: number) {
    const viewer = живой?.viewer
    if (!viewer) return
    viewer.currentScale = Math.min(БОЛЬШЕ, Math.max(МЕНЬШЕ, viewer.currentScale * во_сколько))
  }

  const выбранный = selected ? по_ключу.get(selected) : undefined

  return (
    <div className="flex h-full min-h-0 flex-col bg-surface-2">
      <div className="flex flex-wrap items-center gap-s2 border-b border-line bg-surface px-s3 py-s2">
        <span className="text-sm font-semibold text-ink-strong">{t('reports.pdf.title')}</span>
        <Button
          variant="secondary"
          size="sm"
          disabled={!canBuild || build.running}
          onClick={build.start}
        >
          {build.running ? <Spinner size={14} /> : <Icon name="refresh" size={14} />}
          {build.pdfUrl ? t('reports.pdf.rebuild') : t('reports.pdf.build')}
        </Button>
        {живой && (
          <span className="flex items-center gap-1">
            <Button variant="ghost" size="sm" onClick={() => приблизить(1 / ШАГ)}>
              {t('kadai.pdf.zoomOut')}
            </Button>
            <Button variant="ghost" size="sm" onClick={() => приблизить(ШАГ)}>
              {t('kadai.pdf.zoomIn')}
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                if (живой) живой.viewer.currentScaleValue = ПО_ШИРИНЕ
              }}
            >
              {t('kadai.pdf.fit')}
            </Button>
          </span>
        )}
        <span className="ml-auto flex items-center gap-s2">
          {extra}
          {build.docxUrl && (
            <Button variant="ghost" size="sm" asChild>
              <a href={build.docxUrl} download>
                {t('reports.pdf.downloadDocx')}
              </a>
            </Button>
          )}
          {build.pdfUrl && (
            <Button variant="ghost" size="sm" asChild>
              <a href={build.pdfUrl} download>
                {t('reports.pdf.downloadPdf')}
              </a>
            </Button>
          )}
        </span>
      </div>

      {/* Беда сборки — строкой над вёрсткой, а не вместо неё: прошлый
          собранный документ всё ещё годен, и убирать его с экрана из-за
          неудачной пересборки значило бы отнимать то, что работает. */}
      {build.error && (
        <p className="border-b border-err bg-err-bg px-s3 py-s2 text-xs text-err">{build.error}</p>
      )}
      {запасной && url && (
        <p className="border-b border-line bg-surface-2 px-s3 py-s2 text-xs text-muted">
          {t(беда ? 'kadai.pdf.failed' : 'kadai.pdf.noAreas')}
        </p>
      )}

      <div className="relative min-h-0 flex-1 overflow-hidden">
        {!url ? (
          build.running ? (
            <div className="flex h-full flex-col items-center justify-center gap-s3 text-sm text-muted">
              <Spinner size={28} />
              {t('reports.pdf.building')}
            </div>
          ) : (
            <EmptyState
              icon="file"
              title={t('reports.pdf.emptyTitle')}
              text={t('reports.pdf.emptyText')}
              action={
                <Button variant="primary" size="sm" onClick={build.start} disabled={!canBuild}>
                  {t('reports.pdf.build')}
                </Button>
              }
            />
          )
        ) : запасной ? (
          <embed
            key={url}
            src={url}
            type="application/pdf"
            title={t('reports.pdf.title')}
            className="h-full w-full"
          />
        ) : (
          // Просмотрщику pdf.js нужен прокручиваемый корпус с известными
          // размерами: полотно со страницами он кладёт внутрь сам.
          <div ref={корпус} className="absolute inset-0 overflow-auto">
            <div ref={полотно} className="pdfViewer relative" />
          </div>
        )}

        {живой &&
          createPortal(
            области.map((о, i) => {
              const короб = коробки[о.page]
              const блок = по_ключу.get(о.key)
              // Область блока, которого в списке уже нет: работа переигрывалась
              // после сборки. Границы соседей она держит, а нажимать на неё
              // нечего — замечание уехало бы к блоку, которого нет.
              if (!короб || !блок) return null
              const выбран = selected === о.key
              const виден = выбран || наведён === о.key
              const подпись = подпись_области(блок, t)
              return (
                <button
                  key={`${о.key}-${о.page}-${i}`}
                  type="button"
                  aria-label={подпись}
                  aria-pressed={выбран}
                  style={{
                    left: короб.left,
                    top: короб.top + о.top * короб.height,
                    width: короб.width,
                    height: (о.bottom - о.top) * короб.height,
                  }}
                  className={cn(
                    'pointer-events-auto absolute block rounded-sm border-2 text-left transition-colors',
                    выбран
                      ? 'border-accent bg-accent-bg'
                      : 'border-transparent hover:border-accent hover:bg-accent-bg',
                  )}
                  onMouseEnter={() => setНаведён(о.key)}
                  onMouseLeave={() => setНаведён((было) => (было === о.key ? null : было))}
                  onFocus={() => setНаведён(о.key)}
                  onBlur={() => setНаведён((было) => (было === о.key ? null : было))}
                  onClick={() => onSelect(выбран ? null : о.key)}
                >
                  {виден && головные[i] && (
                    <span className="pointer-events-none absolute left-0 top-0 max-w-full truncate rounded-br-sm bg-accent px-1.5 py-0.5 text-[11px] text-accent-ink">
                      {подпись}
                    </span>
                  )}
                </button>
              )
            }),
            живой.layer,
          )}
      </div>

      {/* Форма замечания — под страницей, а не поверх неё: окно поверх вёрстки
          закрывает ровно то место, про которое замечание и пишется. */}
      {живой && (
        <div className="border-t border-line bg-surface p-s3">
          {выбранный && в_вёрстке.has(выбранный.key) ? (
            <div className="flex flex-col gap-s2">
              <p className="text-sm font-medium text-ink-strong">{подпись_области(выбранный, t)}</p>
              <ReworkForm block={выбранный} disabled={disabled} onRework={onRework} />
            </div>
          ) : (
            <p className="text-xs text-muted">{t('kadai.pdf.pick')}</p>
          )}
        </div>
      )}

      {build.unfilled.length > 0 && (
        <p className="border-t border-line bg-warn-bg px-s3 py-s2 text-xs text-ink">
          {t('reports.pdf.unfilled', {
            n: build.unfilled.length,
            keys: build.unfilled.slice(0, 5).join(', '),
          })}
        </p>
      )}
    </div>
  )
}

/**
 * Подпись области: «b-03 · Алгоритм сортировки · написала модель».
 *
 * Ключ в подписи не украшение: это адрес, которым замечание уезжает в службу, и
 * по нему же блок находится в списке слева. Метка источника здесь та же, что и
 * в карточке, — и по той же причине: от неё зависит, перепишет ли блок
 * следующий проход текста.
 */
function подпись_области(блок: BlockRecordBody, t: (ключ: string) => string): string {
  const вид = String(блок.kind ?? '')
  const имя = блок.label?.trim()
  const чей = черновик(вид, blockText(блок))
    ? t('kadai.blocks.draft')
    : t(блок.source === 'manual' ? 'kadai.blocks.source.human' : 'kadai.blocks.source.agent')
  const название = имя || (ВИД[вид] ? t(ВИД[вид]) : вид) || t('kadai.blocks.kind.unknown')
  return `${блок.key} · ${название} · ${чей}`
}

/**
 * Якоря блоков в документе: имя назначения → страница и доля высоты.
 *
 * Читается весь список назначений разом, а не по ключам блоков с экрана:
 * собранный PDF бывает старше списка, и блок, которого в списке уже нет, всё
 * равно задаёт границу соседям. Пересчёт координат в доли идёт через
 * `convertToViewportPoint`: в PDF высота считается снизу, а у повёрнутой
 * страницы — вовсе не по той оси, и своя арифметика здесь ошиблась бы молча.
 */
async function прочитать_якоря(документ: PDFDocumentProxy): Promise<Anchor[]> {
  const назначения = await документ.getDestinations()
  const виды = new Map<
    number,
    { height: number; convertToViewportPoint(x: number, y: number): unknown[] }
  >()
  const якоря: Anchor[] = []
  for (const [имя, назначение] of назначения) {
    const ключ = keyOfBookmark(имя)
    if (!ключ) continue
    const цель: unknown = назначение[0]
    let страница: number
    if (typeof цель === 'number') страница = цель
    else if (цель && typeof цель === 'object')
      страница = await документ.getPageIndex(цель as { num: number; gen: number })
    else continue
    let вид = виды.get(страница)
    if (!вид) {
      вид = (await документ.getPage(страница + 1)).getViewport({ scale: 1 })
      виды.set(страница, вид)
    }
    const y = destY(назначение)
    const верх = y === null ? 0 : Number(вид.convertToViewportPoint(0, y)[1]) / вид.height
    якоря.push({ key: ключ, page: страница, top: верх })
  }
  return якоря
}
